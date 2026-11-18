"""Build and reopen a local index keyed by its corpus and embedding model."""

import json
from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from qdrant_client import QdrantClient, models

from .corpus import Document
from .embeddings import OllamaEmbeddings
from .retrieval import COLLECTION_NAME, index_corpus


def index_fingerprint(data: bytes, embedder: OllamaEmbeddings) -> dict[str, str]:
    return {
        "corpus_sha256": sha256(data).hexdigest(),
        "model": embedder.model,
        "model_digest": embedder.model_digest(),
        "embedding_template": "title-newline-text-v1",
    }


def index_path(root: Path, fingerprint: dict[str, str]) -> Path:
    key = sha256(json.dumps(fingerprint, sort_keys=True).encode("utf-8")).hexdigest()
    return root / key


@contextmanager
def open_index(
    path: Path, fingerprint: dict[str, str], document_count: int,
) -> Iterator[tuple[QdrantClient, dict]]:
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("No matching index for this corpus and model. Run the index command first.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("fingerprint") != fingerprint
        or manifest.get("document_count") != document_count
        or type(manifest.get("dimensions")) is not int
        or manifest["dimensions"] < 1
    ):
        raise ValueError("Index manifest does not match the corpus or embedding configuration")

    with closing(QdrantClient(path=str(path))) as client:
        if not client.collection_exists(COLLECTION_NAME):
            raise ValueError("The index collection is missing")
        vectors = client.get_collection(COLLECTION_NAME).config.params.vectors
        if (
            not isinstance(vectors, models.VectorParams)
            or vectors.size != manifest["dimensions"]
            or vectors.distance != models.Distance.COSINE
            or client.count(COLLECTION_NAME, exact=True).count != document_count
        ):
            raise ValueError("The index collection does not match the manifest")
        yield client, manifest


def embed_query(embedder: OllamaEmbeddings, question: str, manifest: dict) -> list[float]:
    vector, = embedder.embed([question])
    if len(vector) != manifest["dimensions"]:
        raise ValueError("The query embedding dimension does not match the index")
    if embedder.model_digest() != manifest["fingerprint"]["model_digest"]:
        raise ValueError("The Ollama model changed while embedding the question")
    return vector


def build_index(
    location: Path,
    fingerprint: dict[str, str],
    documents: Mapping[str, Document],
    embedder: OllamaEmbeddings,
) -> dict:
    if not location.exists():
        vectors = embedder.embed([f"{doc.title}\n{doc.text}" for doc in documents.values()])
        if embedder.model_digest() != fingerprint["model_digest"]:
            raise ValueError("The Ollama model changed while building the index. Run index again.")
        manifest = {
            "fingerprint": fingerprint,
            "document_count": len(documents),
            "dimensions": len(vectors[0]),
        }
        location.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".building-", dir=location.parent) as temp:
            staging = Path(temp) / "index"
            with closing(QdrantClient(path=str(staging))) as client:
                index_corpus(client, documents, vectors)
            (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            try:
                staging.rename(location)
            except OSError:
                if not location.is_dir():
                    raise

    with open_index(location, fingerprint, len(documents)) as (_, manifest):
        return manifest
