"""Compare access filtering inside Qdrant and after candidate retrieval."""

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from math import isfinite
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

from .corpus import KNOWN_ROLES, Document


COLLECTION_NAME = "pfa_documents"


@dataclass(frozen=True)
class SearchHit:
    document: Document
    score: float


@dataclass(frozen=True)
class SearchResult:
    hits: list[SearchHit]
    candidate_count: int
    rejected_count: int


def index_corpus(
    client: QdrantClient,
    documents: Mapping[str, Document],
    vectors: Sequence[Sequence[float]],
    *,
    collection: str = COLLECTION_NAME,
) -> None:
    """Create a collection with one vector per document in corpus order."""
    if not vectors or len(documents) != len(vectors):
        raise ValueError("provide one vector per document")

    size = len(vectors[0])
    if not size or any(
        len(vector) != size or not all(map(isfinite, vector)) or not any(vector)
        for vector in vectors
    ):
        raise ValueError("vectors must have the same positive dimension and be finite and nonzero")

    points = [
        models.PointStruct(
            id=str(uuid5(NAMESPACE_URL, f"pfa-rag-keycloak/{document.id}")),
            vector=list(vector),
            payload={
                "document_id": document.id,
                "allowed_roles": sorted(document.allowed_roles),
            },
        )
        for document, vector in zip(documents.values(), vectors, strict=True)
    ]
    client.create_collection(
        collection_name=collection,
        vectors_config=models.VectorParams(size=size, distance=models.Distance.COSINE),
    )
    client.upsert(collection_name=collection, points=points, wait=True)


def retrieve(
    client: QdrantClient,
    documents: Mapping[str, Document],
    query_vector: Sequence[float],
    roles: Set[str],
    *,
    strategy: str,
    top_k: int = 5,
    candidate_limit: int = 20,
    collection: str = COLLECTION_NAME,
) -> list[SearchHit]:
    """Return only hits permitted by the original corpus metadata."""
    return search(
        client, documents, query_vector, roles, strategy=strategy, top_k=top_k,
        candidate_limit=candidate_limit, collection=collection,
    ).hits


def search(
    client: QdrantClient,
    documents: Mapping[str, Document],
    query_vector: Sequence[float],
    roles: Set[str],
    *,
    strategy: str,
    top_k: int = 5,
    candidate_limit: int = 20,
    collection: str = COLLECTION_NAME,
) -> SearchResult:
    """Return only hits permitted by the original corpus metadata."""
    if strategy not in {"pre_filter", "post_filter"}:
        raise ValueError(f"unknown retrieval strategy {strategy!r}")
    if top_k < 1 or candidate_limit < 1:
        raise ValueError("top_k and candidate_limit must be positive")

    recognized_roles = roles & KNOWN_ROLES
    if not recognized_roles:
        return SearchResult([], 0, 0)

    query_filter = None
    if strategy == "pre_filter":
        query_filter = models.Filter(
            must=[models.FieldCondition(
                key="allowed_roles",
                match=models.MatchAny(any=sorted(recognized_roles)),
            )],
        )

    points = client.query_points(
        collection_name=collection,
        query=list(query_vector),
        query_filter=query_filter,
        search_params=models.SearchParams(exact=True),
        limit=top_k if strategy == "pre_filter" else candidate_limit,
        with_payload=["document_id"],
    ).points

    hits = []
    for point in points:
        document_id = (point.payload or {}).get("document_id")
        document = documents.get(document_id) if isinstance(document_id, str) else None
        if document is not None and document.can_read(recognized_roles):
            hits.append(SearchHit(document=document, score=point.score))
    return SearchResult(hits[:top_k], len(points), len(points) - len(hits))
