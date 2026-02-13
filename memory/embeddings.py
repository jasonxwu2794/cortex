"""Embedding generation and similarity utilities."""

from __future__ import annotations

import numpy as np
from typing import Protocol


class Embedder(Protocol):
    """Interface for embedding providers."""
    def embed(self, text: str) -> np.ndarray: ...
    def embed_batch(self, texts: list[str]) -> list[np.ndarray]: ...


_model_cache: dict[str, object] = {}


class LocalEmbedder:
    """Local embeddings using sentence-transformers MiniLM-L6-v2."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        if model_name not in _model_cache:
            from sentence_transformers import SentenceTransformer
            _model_cache[model_name] = SentenceTransformer(model_name)
        self.model = _model_cache[model_name]

    def embed(self, text: str) -> np.ndarray:
        return self.model.encode(text, normalize_embeddings=True)

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        embeddings = self.model.encode(texts, normalize_embeddings=True)
        return [embeddings[i] for i in range(len(texts))]


class APIEmbedder:
    """Stub for API-based embeddings (OpenAI, Voyage, Cohere)."""

    def __init__(self, api_key: str = "", provider: str = "openai", model: str = "text-embedding-3-small"):
        self.api_key = api_key
        self.provider = provider
        self.model = model
        # TODO: implement actual API calls

    def embed(self, text: str) -> np.ndarray:
        raise NotImplementedError("API embeddings not yet implemented. Use LocalEmbedder.")

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        raise NotImplementedError("API embeddings not yet implemented. Use LocalEmbedder.")


_embedder_cache: dict[str, Embedder] = {}


def get_embedder(config: dict | None = None) -> Embedder:
    """Factory function to create an embedder based on config. Caches instances."""
    cfg = config or {}
    cache_key = f"{cfg.get('type', 'local')}:{cfg.get('model', 'all-MiniLM-L6-v2')}"
    if cache_key in _embedder_cache:
        return _embedder_cache[cache_key]

    if cfg.get("type") == "api":
        embedder = APIEmbedder(
            api_key=cfg.get("api_key", ""),
            provider=cfg.get("provider", "openai"),
            model=cfg.get("model", "text-embedding-3-small"),
        )
    else:
        embedder = LocalEmbedder(model_name=cfg.get("model", "all-MiniLM-L6-v2"))

    _embedder_cache[cache_key] = embedder
    return embedder


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def serialize_embedding(embedding: np.ndarray) -> bytes:
    """Serialize a numpy embedding to bytes for SQLite storage."""
    return embedding.astype(np.float32).tobytes()


def deserialize_embedding(data: bytes, dim: int = 384) -> np.ndarray:
    """Deserialize bytes back to a numpy embedding."""
    return np.frombuffer(data, dtype=np.float32).copy()
