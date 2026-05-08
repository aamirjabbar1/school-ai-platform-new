"""
Milvus vector database service.

Collection: document_chunks
Schema:
  chunk_id       VARCHAR(36)         primary key (UUID from PostgreSQL)
  document_id    VARCHAR(36)         for filtering + bulk delete
  chunk_index    INT64               ordering within document
  document_title VARCHAR(500)        shown as source citation
  subject        VARCHAR(100)        filter by subject
  class_level    VARCHAR(50)         filter by class level
  chunk_text     VARCHAR(8000)       full chunk text (~400 words ≈ 2400 chars)
  embedding      FLOAT_VECTOR(384)   BAAI/bge-small-en-v1.5 cosine embeddings

Indexes:
  embedding   → HNSW / COSINE  (ANN search)
  document_id → INVERTED scalar (fast filter + bulk delete)
  subject     → INVERTED scalar (fast filter)

All functions are synchronous (pymilvus is sync).
Call from async contexts with `await asyncio.to_thread(fn, ...)`.
"""
from __future__ import annotations

from pymilvus import (
    connections,
    Collection,
    CollectionSchema,
    FieldSchema,
    DataType,
    utility,
)

from services.embedding_service import EMBEDDING_DIM

COLLECTION_NAME = "document_chunks"

# ─── Connection ───────────────────────────────────────────────────────────────

def connect(host: str, port: int) -> None:
    connections.connect("default", host=host, port=port)
    print(f"[OK] Milvus connected at {host}:{port}")


# ─── Collection bootstrap ─────────────────────────────────────────────────────

def ensure_collection() -> Collection:
    """Create the collection and indexes if they don't exist, then load it."""
    if utility.has_collection(COLLECTION_NAME):
        col = Collection(COLLECTION_NAME)
        col.load()
        return col

    fields = [
        FieldSchema(name="chunk_id",       dtype=DataType.VARCHAR, max_length=36,   is_primary=True, auto_id=False),
        FieldSchema(name="document_id",    dtype=DataType.VARCHAR, max_length=36),
        FieldSchema(name="chunk_index",    dtype=DataType.INT64),
        FieldSchema(name="document_title", dtype=DataType.VARCHAR, max_length=500),
        FieldSchema(name="subject",        dtype=DataType.VARCHAR, max_length=100),
        FieldSchema(name="class_level",    dtype=DataType.VARCHAR, max_length=50),
        FieldSchema(name="chunk_text",     dtype=DataType.VARCHAR, max_length=8000),
        FieldSchema(name="embedding",      dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
    ]
    schema = CollectionSchema(fields, description="School curriculum document chunks with embeddings")
    col = Collection(COLLECTION_NAME, schema, consistency_level="Strong")

    # Vector index: HNSW with cosine similarity
    col.create_index(
        "embedding",
        {
            "index_type": "HNSW",
            "metric_type": "COSINE",
            "params": {"M": 16, "efConstruction": 256},
        },
    )

    # Scalar indexes for fast filtering and deletion
    col.create_index("document_id", {"index_type": "INVERTED"})
    col.create_index("subject",     {"index_type": "INVERTED"})

    col.load()
    print(f"[OK] Milvus collection '{COLLECTION_NAME}' created with HNSW index.")
    return col


def _get_collection() -> Collection:
    col = Collection(COLLECTION_NAME)
    col.load()
    return col


# ─── Write operations ─────────────────────────────────────────────────────────

def insert_chunks(chunks: list[dict]) -> None:
    """
    Insert a batch of chunk records.
    Each dict must have: chunk_id, document_id, chunk_index, document_title,
                         subject, class_level, chunk_text, embedding (list[float]).
    """
    if not chunks:
        return

    col = _get_collection()
    fields_order = [
        "chunk_id", "document_id", "chunk_index", "document_title",
        "subject", "class_level", "chunk_text", "embedding",
    ]
    data = [[c[f] for c in chunks] for f in fields_order]
    col.insert(data)
    col.flush()


def delete_document_chunks(document_id: str) -> None:
    """Remove all vectors belonging to a document."""
    col = _get_collection()
    # Query primary keys first, then delete by PK (most reliable approach)
    results = col.query(
        expr=f'document_id == "{document_id}"',
        output_fields=["chunk_id"],
        consistency_level="Strong",
    )
    if not results:
        return
    pks = [r["chunk_id"] for r in results]
    # Delete in batches of 1000 to avoid expression length limits
    batch_size = 1000
    for i in range(0, len(pks), batch_size):
        batch = pks[i : i + batch_size]
        pk_list = ", ".join(f'"{pk}"' for pk in batch)
        col.delete(f"chunk_id in [{pk_list}]")
    col.flush()


# ─── Search ───────────────────────────────────────────────────────────────────

def search_chunks(
    query_embedding: list[float],
    subject: str | None = None,
    class_level: str | None = None,
    limit: int = 8,
) -> list[dict]:
    """
    ANN search. Returns chunks ordered by cosine similarity (highest first).
    Optional subject/class_level filters are applied as scalar pre-filters.
    """
    col = _get_collection()

    # Build filter expression
    filters: list[str] = []
    if subject:
        safe_subject = subject.replace('"', '\\"')
        filters.append(f'subject == "{safe_subject}"')
    if class_level:
        safe_class = class_level.replace('"', '\\"')
        filters.append(f'class_level == "{safe_class}"')
    expr = " && ".join(filters) if filters else None

    search_params = {
        "metric_type": "COSINE",
        "params": {"ef": 64},
    }

    results = col.search(
        data=[query_embedding],
        anns_field="embedding",
        param=search_params,
        limit=limit,
        expr=expr,
        output_fields=[
            "chunk_id", "document_id", "chunk_index",
            "document_title", "subject", "class_level", "chunk_text",
        ],
        consistency_level="Strong",
    )

    chunks = []
    for hit in results[0]:
        e = hit.entity
        chunks.append({
            "chunk_id":       e.get("chunk_id"),
            "document_id":    e.get("document_id"),
            "chunk_index":    e.get("chunk_index"),
            "document_title": e.get("document_title"),
            "subject":        e.get("subject"),
            "class_level":    e.get("class_level"),
            "chunk_text":     e.get("chunk_text"),
            "score":          float(hit.score),
        })
    return chunks
