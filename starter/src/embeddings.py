"""Real embedding model (local Sentence Transformers). No mock / random fallback."""
from __future__ import annotations

from typing import Any, Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class SentenceTransformerEmbedder:
    """Local multilingual model; symmetric (same encoding for queries and documents, no prefix).

    Vectors are L2-normalized so cosine distance in the store equals 1 - dot product.
    Raises if the model cannot be loaded - the pipeline never silently switches to fake vectors.
    """

    def __init__(self, model_name: str, device: str = "cpu", batch_size: int = 32) -> None:
        from sentence_transformers import SentenceTransformer  # heavy import kept local

        self.model_name = model_name
        self.batch_size = batch_size
        self._model = SentenceTransformer(model_name, device=device)
        dims = self._model.get_sentence_embedding_dimension()
        if not dims:
            raise RuntimeError(f"Could not determine embedding dimensions for {model_name}")
        self.dimensions = int(dims)
        self.max_seq_length = int(self._model.max_seq_length)

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                     convert_to_numpy=True, show_progress_bar=False)
        return vectors.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts) if texts else []

    def embed_query(self, question: str) -> list[float]:
        return self._encode([question])[0]

    def token_lengths(self, texts: list[str]) -> list[int]:
        """Number of tokenizer tokens (incl. special tokens) per text, before truncation."""
        tok = self._model.tokenizer
        return [len(ids) for ids in tok(texts, add_special_tokens=True, truncation=False)["input_ids"]]

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "provider": "local (sentence-transformers)",
            "model": self.model_name,
            "dimensions": self.dimensions,
            "max_seq_length_tokens": self.max_seq_length,
            "normalize_embeddings": True,
            "query_document_handling": "symmetric: identical encoding, no instruction prefix",
        }
        try:
            import sentence_transformers
            import torch
            import transformers
            info["versions"] = {"sentence-transformers": sentence_transformers.__version__,
                                "transformers": transformers.__version__, "torch": torch.__version__}
        except Exception:  # version reporting is best-effort
            pass
        try:
            from huggingface_hub import scan_cache_dir
            for repo in scan_cache_dir().repos:
                if repo.repo_id == self.model_name:
                    info["revision"] = sorted(r.commit_hash for r in repo.revisions)
        except Exception:
            pass
        return info
