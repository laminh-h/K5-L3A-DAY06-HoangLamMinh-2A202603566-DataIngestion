"""Persistent vector store: Chroma (local, on disk) with cosine distance and metadata filters.

Docker/PostgreSQL is not available on the author's machine, so the starter's pgvector
skeleton was replaced by Chroma, which GUIDE.md lists as an accepted equivalent.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import Chunk

# Only these metadata keys may be used as filters (values come from the question, never from gold).
ALLOWED_FILTER_KEYS = {"edition", "year", "section", "document_id", "language"}


def build_where(filters: dict[str, Any] | None) -> dict[str, Any] | None:
    if not filters:
        return None
    unknown = set(filters) - ALLOWED_FILTER_KEYS
    if unknown:
        raise ValueError(f"Filter keys not allowed: {sorted(unknown)}")
    clauses = [{k: {"$eq": v}} for k, v in sorted(filters.items())]
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


class ChromaStore:
    def __init__(self, path: Path, dimensions: int, model_name: str) -> None:
        import chromadb

        self.path = Path(path)
        self.dimensions = dimensions
        self.model_name = model_name
        self.client = chromadb.PersistentClient(path=str(self.path))

    def collection_name(self, index: str) -> str:
        return f"day6_index_{index}"

    def collection(self, index: str):
        col = self.client.get_or_create_collection(
            name=self.collection_name(index),
            embedding_function=None,
            metadata={"hnsw:space": "cosine", "embedding_model": self.model_name, "dimensions": self.dimensions},
        )
        meta = col.metadata or {}
        if meta.get("embedding_model") not in (None, self.model_name) or meta.get("dimensions") not in (None, self.dimensions):
            raise RuntimeError(f"Collection {col.name} was built with {meta}; refusing to mix models/dimensions")
        return col

    def existing(self, index: str, document_id: str) -> dict[str, str]:
        """chunk_id -> content_hash already stored for this document."""
        got = self.collection(index).get(where={"document_id": document_id}, include=["metadatas"])
        return {i: (m or {}).get("content_hash", "") for i, m in zip(got["ids"], got["metadatas"])}

    def upsert(self, index: str, chunks: list[Chunk], vectors: list[list[float]], batch: int = 500) -> None:
        """Write chunks with stable IDs (re-running replaces, never duplicates)."""
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        for v in vectors:
            if len(v) != self.dimensions:
                raise ValueError(f"Vector has {len(v)} dims, expected {self.dimensions}")
        ids = [c.chunk_id for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate chunk IDs in one upsert")
        col = self.collection(index)
        for s in range(0, len(chunks), batch):
            part = chunks[s:s + batch]
            col.upsert(
                ids=[c.chunk_id for c in part],
                embeddings=vectors[s:s + batch],
                documents=[c.text for c in part],
                metadatas=[{"document_id": c.document_id, "source": c.source, "page": c.page, **c.metadata}
                           for c in part],
            )

    def delete(self, index: str, ids: list[str]) -> None:
        if ids:
            self.collection(index).delete(ids=ids)

    def count(self, index: str) -> int:
        return self.collection(index).count()

    def search(self, index: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Top-k by cosine distance; optional metadata pre-filter. score = 1 - cosine distance."""
        if len(query_vector) != self.dimensions:
            raise ValueError(f"Query vector has {len(query_vector)} dims, expected {self.dimensions}")
        res = self.collection(index).query(
            query_embeddings=[query_vector], n_results=top_k, where=build_where(filters),
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        for rank, (cid, doc, meta, dist) in enumerate(zip(res["ids"][0], res["documents"][0],
                                                          res["metadatas"][0], res["distances"][0]), start=1):
            hits.append({"rank": rank, "chunk_id": cid, "score": round(1.0 - float(dist), 6),
                         "text": doc, "metadata": meta})
        return hits
