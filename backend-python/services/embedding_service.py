"""
Text embedding service using fastembed (local ONNX inference, no API key needed).

Model: BAAI/bge-small-en-v1.5
  - Dimension: 384
  - Size: ~33 MB (downloaded on first use, cached in /root/.cache/fastembed)
  - Metric: COSINE

All functions are synchronous (onnxruntime is sync).
Call them with `await asyncio.to_thread(fn, ...)` from async contexts.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastembed import TextEmbedding

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

_model: "TextEmbedding | None" = None


def _get_model() -> "TextEmbedding":
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_name=EMBEDDING_MODEL)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. Returns a list of float vectors."""
    model = _get_model()
    return [emb.tolist() for emb in model.embed(texts)]


def embed_query(query: str) -> list[float]:
    """Embed a single query string."""
    return embed_texts([query])[0]
