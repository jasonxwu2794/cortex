"""Embedding generation and similarity utilities.

Uses ONNX Runtime + tokenizers directly — no PyTorch dependency (~50MB total).
Falls back to sentence-transformers if available.
"""

from __future__ import annotations

import os
import json
import numpy as np
from pathlib import Path
from typing import Protocol


class Embedder(Protocol):
    """Interface for embedding providers."""
    def embed(self, text: str) -> np.ndarray: ...
    def embed_batch(self, texts: list[str]) -> list[np.ndarray]: ...


_model_cache: dict[str, object] = {}

# Default model cache directory
_MODELS_DIR = Path(os.environ.get("EMBEDDING_MODELS_DIR", Path.home() / ".cache" / "embedding-models"))


class ONNXEmbedder:
    """Local embeddings using ONNX Runtime + tokenizers (no PyTorch needed).

    Downloads the ONNX model from HuggingFace on first use (~30MB).
    """

    MODEL_REPO = "sentence-transformers/all-MiniLM-L6-v2"
    ONNX_FILE = "onnx/model.onnx"
    DIM = 384

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        if model_name not in _model_cache:
            _model_cache[model_name] = self._load_model()
        self._session, self._tokenizer = _model_cache[model_name]

    def _download_model(self, model_dir: Path) -> None:
        """Download ONNX model and tokenizer from HuggingFace."""
        import urllib.request

        model_dir.mkdir(parents=True, exist_ok=True)
        base_url = f"https://huggingface.co/{self.MODEL_REPO}/resolve/main"

        files = {
            "onnx/model.onnx": "model.onnx",
            "tokenizer.json": "tokenizer.json",
            "tokenizer_config.json": "tokenizer_config.json",
        }

        for remote, local in files.items():
            dest = model_dir / local
            if not dest.exists():
                url = f"{base_url}/{remote}"
                urllib.request.urlretrieve(url, str(dest))

    def _load_model(self):
        """Load ONNX session and tokenizer."""
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_dir = _MODELS_DIR / self.model_name

        # Download if not cached
        if not (model_dir / "model.onnx").exists():
            self._download_model(model_dir)

        session = ort.InferenceSession(
            str(model_dir / "model.onnx"),
            providers=["CPUExecutionProvider"],
        )
        tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        tokenizer.enable_padding(length=128)
        tokenizer.enable_truncation(max_length=128)

        return session, tokenizer

    def _mean_pooling(self, token_embeddings: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
        """Mean pooling with attention mask."""
        mask_expanded = np.expand_dims(attention_mask, -1).astype(np.float32)
        summed = np.sum(token_embeddings * mask_expanded, axis=1)
        counts = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
        return summed / counts

    def _normalize(self, embeddings: np.ndarray) -> np.ndarray:
        """L2 normalize."""
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.clip(norms, a_min=1e-9, a_max=None)
        return embeddings / norms

    def _encode(self, texts: list[str]) -> np.ndarray:
        """Encode texts to normalized embeddings."""
        encoded = self._tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        token_type_ids = np.zeros_like(input_ids, dtype=np.int64)

        outputs = self._session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            },
        )

        embeddings = self._mean_pooling(outputs[0], attention_mask)
        return self._normalize(embeddings)

    def embed(self, text: str) -> np.ndarray:
        return self._encode([text])[0]

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        embeddings = self._encode(texts)
        return [embeddings[i] for i in range(len(texts))]


class SentenceTransformersEmbedder:
    """Fallback: sentence-transformers (requires PyTorch)."""

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


def _create_local_embedder(model_name: str = "all-MiniLM-L6-v2") -> Embedder:
    """Create the best available local embedder: ONNX first, sentence-transformers fallback."""
    try:
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
        return ONNXEmbedder(model_name)
    except ImportError:
        pass

    try:
        return SentenceTransformersEmbedder(model_name)
    except ImportError:
        raise ImportError(
            "No embedding backend available. Install one of:\n"
            "  pip install onnxruntime tokenizers   (lightweight, recommended)\n"
            "  pip install sentence-transformers     (heavier, requires PyTorch)"
        )


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
        embedder = _create_local_embedder(model_name=cfg.get("model", "all-MiniLM-L6-v2"))

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
