"""
Text embedding service using OpenAI text-embedding-3-large.

Model: text-embedding-3-large
  - Dimension: 3072
  - Metric:    COSINE
  - API key:   OPENAI_API_KEY environment variable

All functions are synchronous.
Call them with `await asyncio.to_thread(fn, ...)` from async contexts.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import openai as _openai_t

EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIM = 3072
_BATCH_SIZE = 100  # OpenAI allows up to 2048 inputs; 100 is safe for large texts

_client: "_openai_t.OpenAI | None" = None


def _get_client() -> "_openai_t.OpenAI":
    global _client
    if _client is None:
        import openai
        _client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. Returns a list of float vectors."""
    client = _get_client()
    results: list[list[float]] = []

    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        # Response items are ordered by index
        batch_embeddings = sorted(response.data, key=lambda e: e.index)
        results.extend(e.embedding for e in batch_embeddings)

    return results


def embed_query(query: str) -> list[float]:
    """Embed a single query string."""
    return embed_texts([query])[0]
