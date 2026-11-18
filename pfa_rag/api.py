"""Serve the Keycloak browser client and role-scoped retrieval API."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from http import HTTPStatus
from os import getenv
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from .audit import AccessJournal, AuditUnavailable
from .auth import IdentityUnavailable, InvalidAccessToken, KeycloakVerifier, Principal
from .corpus import Document, parse_corpus
from .embeddings import OllamaEmbeddings
from .generation import InvalidGeneration, OllamaAnswers, answer_text
from .index import embed_query, index_fingerprint, index_path, open_index
from .retrieval import retrieve
from .schemas import AnswerResponse, DocumentResponse, IdentityResponse, RetrievalRequest, RetrievalResponse, Source


WEB = Path(__file__).resolve().parent / "web"


@dataclass(frozen=True)
class Settings:
    issuer: str = "http://localhost:8088/realms/pfa-rag"
    audience: str = "pfa-api"
    web_client: str = "pfa-web"
    ollama_url: str = "http://127.0.0.1:11434"
    embedding_model: str = "bge-m3"
    corpus: Path = Path("data/corpus.jsonl")
    index_dir: Path = Path(".pfa-index")
    generation_model: str = "qwen3.5:9b"
    audit_db: Path = Path(".pfa-state/access.sqlite3")

    @classmethod
    def from_environment(cls) -> "Settings":
        defaults = cls()
        return cls(
            issuer=getenv("PFA_OIDC_ISSUER", defaults.issuer).rstrip("/"),
            audience=getenv("PFA_API_AUDIENCE", defaults.audience),
            web_client=getenv("PFA_WEB_CLIENT", defaults.web_client),
            ollama_url=getenv("PFA_OLLAMA_URL", defaults.ollama_url),
            embedding_model=getenv("PFA_EMBEDDING_MODEL", defaults.embedding_model),
            corpus=Path(getenv("PFA_CORPUS", str(defaults.corpus))),
            index_dir=Path(getenv("PFA_INDEX_DIR", str(defaults.index_dir))),
            generation_model=getenv("PFA_GENERATION_MODEL", defaults.generation_model),
            audit_db=Path(getenv("PFA_AUDIT_DB", str(defaults.audit_db))),
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_environment()
    verifier = KeycloakVerifier(settings.issuer, settings.audience)
    embedder = OllamaEmbeddings(settings.ollama_url, settings.embedding_model)
    generator = OllamaAnswers(settings.ollama_url, settings.generation_model)
    journal = AccessJournal(settings.audit_db)
    index_lock = Lock()
    bearer = HTTPBearer(auto_error=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        data = await run_in_threadpool(settings.corpus.read_bytes)
        app.state.corpus_data = data
        app.state.documents = parse_corpus(data, settings.corpus)
        await run_in_threadpool(journal.initialize)
        yield

    app = FastAPI(title="PFA · RAG à droits d’accès", version="0.3.0", lifespan=lifespan)

    @app.middleware("http")
    async def prevent_protected_response_caching(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/v1/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_problem(_: Request, error: HTTPException):
        return JSONResponse(
            {"type": f"urn:pfa:error:{error.status_code}", "title": HTTPStatus(error.status_code).phrase,
             "status": error.status_code, "detail": error.detail},
            status_code=error.status_code, headers=error.headers, media_type="application/problem+json",
        )

    @app.exception_handler(AuditUnavailable)
    async def unavailable_journal(request: Request, _: AuditUnavailable):
        return await http_problem(request, HTTPException(503, "The access journal is unavailable"))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, error: RequestValidationError):
        return JSONResponse(
            {"type": "urn:pfa:error:422", "title": "Invalid request", "status": 422,
             "detail": "Check the request fields.",
             "errors": [
                 {"field": ".".join(map(str, item["loc"])), "message": item["msg"]}
                 for item in error.errors()
             ]},
            status_code=422, media_type="application/problem+json",
        )

    def current_principal(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> Principal:
        unauthenticated = HTTPException(
            401, "A valid Keycloak access token is required", headers={"WWW-Authenticate": "Bearer"},
        )
        if credentials is None:
            raise unauthenticated
        try:
            principal = verifier.verify(credentials.credentials)
        except InvalidAccessToken as error:
            raise unauthenticated from error
        except IdentityUnavailable as error:
            raise HTTPException(503, "The identity service is unavailable") from error
        if not principal.roles:
            raise HTTPException(403, "An application role is required")
        return principal

    CurrentPrincipal = Annotated[Principal, Depends(current_principal)]

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(WEB / "index.html")

    @app.get("/vendor/{module}", include_in_schema=False)
    def keycloak_client(module: str):
        if module not in {"keycloak.js", "deprecations.js"}:
            raise HTTPException(404, "Module unavailable")
        file = WEB / "node_modules" / "keycloak-js" / "lib" / module
        if not file.is_file():
            raise HTTPException(503, "Install the browser dependency with npm ci --prefix pfa_rag/web")
        return FileResponse(file, media_type="text/javascript")

    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    @app.get("/api/config", include_in_schema=False)
    def public_config() -> dict[str, str]:
        return {"issuer": verifier.issuer, "client_id": settings.web_client}

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/readyz")
    def readiness() -> dict[str, str]:
        try:
            verifier.check_ready()
            generator.model_digest()
            fingerprint = index_fingerprint(app.state.corpus_data, embedder)
            location = index_path(settings.index_dir, fingerprint)
            with index_lock, open_index(location, fingerprint, len(app.state.documents)):
                return {"status": "ready"}
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(503, "Keycloak, Ollama, or the index is unavailable") from error

    @app.get("/api/v1/me")
    def identity(principal: CurrentPrincipal) -> IdentityResponse:
        return IdentityResponse(username=principal.username, roles=sorted(principal.roles))

    def source_of(document: Document) -> Source:
        return Source(
            document_id=document.id, title=document.title,
            url=f"/api/v1/documents/{quote(document.id, safe='')}",
        )

    def lookup(body: RetrievalRequest, principal: Principal) -> list[Document]:
        documents = app.state.documents
        fingerprint = index_fingerprint(app.state.corpus_data, embedder)
        location = index_path(settings.index_dir, fingerprint)
        with index_lock, open_index(location, fingerprint, len(documents)) as (client, manifest):
            vector = embed_query(embedder, body.question, manifest)
            hits = retrieve(client, documents, vector, principal.roles, strategy=body.strategy)
        return [hit.document for hit in hits]

    @app.get("/api/v1/documents/{document_id}")
    def source_document(document_id: str, principal: CurrentPrincipal) -> DocumentResponse:
        start = perf_counter()
        document = app.state.documents.get(document_id)
        allowed = document is not None and document.can_read(principal.roles)
        request_id = journal.start("source", principal, [document_id] if allowed else [])
        journal.finish(request_id, "opened" if allowed else "unavailable", [], 1000 * (perf_counter() - start))
        if not allowed:
            raise HTTPException(404, "Source unavailable")
        return DocumentResponse(document_id=document.id, title=document.title, text=document.text)

    def question_context(operation: str, body: RetrievalRequest, principal: Principal, start: float):
        try:
            documents = lookup(body, principal)
        except (OSError, RuntimeError, ValueError) as error:
            request_id = journal.start(operation, principal, [], question=body.question, strategy=body.strategy)
            journal.finish(request_id, "retrieval_unavailable", [], 1000 * (perf_counter() - start))
            raise HTTPException(503, "Retrieval is temporarily unavailable") from error

        request_id = journal.start(
            operation, principal, [document.id for document in documents],
            question=body.question, strategy=body.strategy,
        )
        return request_id, documents

    @app.post("/api/v1/retrievals")
    def retrieval(body: RetrievalRequest, principal: CurrentPrincipal) -> RetrievalResponse:
        start = perf_counter()
        request_id, documents = question_context("retrieval", body, principal, start)
        journal.finish(request_id, "retrieved", [], 1000 * (perf_counter() - start))
        return RetrievalResponse(strategy=body.strategy, sources=[source_of(doc) for doc in documents])

    @app.post("/api/v1/answers")
    def answer(body: RetrievalRequest, principal: CurrentPrincipal) -> AnswerResponse:
        start = perf_counter()
        request_id, documents = question_context("answer", body, principal, start)
        model_start = perf_counter()
        try:
            selected = generator.select(body.question, principal.roles, documents)
        except (RuntimeError, OSError, ValueError) as error:
            end = perf_counter()
            invalid = isinstance(error, InvalidGeneration)
            result = "invalid_generation" if invalid else "generation_unavailable"
            journal.finish(request_id, result, [], 1000 * (end - start), 1000 * (end - model_start))
            status = 502 if invalid else 503
            raise HTTPException(status, "A grounded answer could not be produced") from error

        end = perf_counter()
        used = {passage.document.id: passage.document for passage in selected}
        result = "answered" if selected else "insufficient_evidence"
        journal.finish(
            request_id, result, list(used), 1000 * (end - start),
            1000 * (end - model_start) if documents else 0,
        )
        return AnswerResponse(
            request_id=request_id, status=result, strategy=body.strategy,
            answer=answer_text(selected), citations=[source_of(doc) for doc in used.values()],
        )

    return app


app = create_app()
