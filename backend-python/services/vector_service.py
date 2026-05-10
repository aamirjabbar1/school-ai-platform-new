"""
Milvus vector database service.

Collection: document_chunks
Schema:
  chunk_id        VARCHAR(36)          primary key (UUID from PostgreSQL)
  document_id     VARCHAR(36)          bulk delete + filter
  chunk_index     INT64                ordering within document
  document_title  VARCHAR(500)         source citation display
  subject         VARCHAR(100)         filter: Math, Science, English, Urdu …
  class_level     VARCHAR(50)          filter: Grade 1 … Grade 12
  document_type   VARCHAR(50)          filter: book | exam | assignment | notes | worksheet
  language        VARCHAR(20)          filter: English | Urdu | Bilingual
  academic_year   VARCHAR(20)          filter: 2024-2025
  term            VARCHAR(30)          filter: Term 1 | Term 2 | Term 3 | Annual
  chapter_number  INT64                citation: chapter position (0 = unknown)
  chapter_title   VARCHAR(300)         citation: chapter heading text
  page_number     INT64                citation: approximate page (0 = unknown)
  chunk_text      VARCHAR(16000)       full chunk text (~600 words, tables/figures inline)
  embedding       FLOAT_VECTOR(3072)   OpenAI text-embedding-3-large cosine embeddings

Indexes:
  embedding     → HNSW / COSINE        ANN search
  document_id   → INVERTED scalar      fast filter + bulk delete
  subject       → INVERTED scalar      fast filter
  class_level   → INVERTED scalar      fast filter
  document_type → INVERTED scalar      fast filter
  language      → INVERTED scalar      fast filter
  academic_year → INVERTED scalar      fast filter
  term          → INVERTED scalar      fast filter

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

_INVERTED = {"index_type": "INVERTED"}

# Maximum bytes for chunk_text. Bumped from 8000 → 16000 to fit larger
# structure-aware chunks (~600 words) plus inline markdown tables and
# [FIGURE: ...] descriptions without silent truncation.
_CHUNK_TEXT_MAX_LENGTH = 16000


# ─── Connection ───────────────────────────────────────────────────────────────

def connect(host: str, port: int) -> None:
    connections.connect("default", host=host, port=port)
    print(f"[OK] Milvus connected at {host}:{port}")


# ─── Collection bootstrap ─────────────────────────────────────────────────────

def ensure_collection() -> Collection:
    """Create the collection and indexes if they don't exist, then load it.

    If an existing collection has an old chunk_text max_length (< 16000), it
    is dropped and recreated. Existing vectors are lost — re-ingest documents
    after a schema bump.
    """
    if utility.has_collection(COLLECTION_NAME):
        col = Collection(COLLECTION_NAME)
        existing = {f.name: f for f in col.schema.fields}
        ml = (existing.get("chunk_text").params or {}).get("max_length", 0) if "chunk_text" in existing else 0
        if ml < _CHUNK_TEXT_MAX_LENGTH:
            print(
                f"[Milvus] Dropping '{COLLECTION_NAME}' — chunk_text max_length "
                f"{ml} < required {_CHUNK_TEXT_MAX_LENGTH}. Re-ingest documents."
            )
            utility.drop_collection(COLLECTION_NAME)
        else:
            col.load()
            return col

    fields = [
        # ── Identity ──────────────────────────────────────────────────────────
        FieldSchema(name="chunk_id",       dtype=DataType.VARCHAR, max_length=36,  is_primary=True, auto_id=False),
        FieldSchema(name="document_id",    dtype=DataType.VARCHAR, max_length=36),
        FieldSchema(name="chunk_index",    dtype=DataType.INT64),

        # ── Document-level metadata ───────────────────────────────────────────
        FieldSchema(name="document_title", dtype=DataType.VARCHAR, max_length=500),
        FieldSchema(name="subject",        dtype=DataType.VARCHAR, max_length=100),
        FieldSchema(name="class_level",    dtype=DataType.VARCHAR, max_length=50),
        FieldSchema(name="document_type",  dtype=DataType.VARCHAR, max_length=50),
        FieldSchema(name="language",       dtype=DataType.VARCHAR, max_length=20),
        FieldSchema(name="academic_year",  dtype=DataType.VARCHAR, max_length=20),
        FieldSchema(name="term",           dtype=DataType.VARCHAR, max_length=30),

        # ── Chunk-level location ──────────────────────────────────────────────
        FieldSchema(name="chapter_number", dtype=DataType.INT64),
        FieldSchema(name="chapter_title",  dtype=DataType.VARCHAR, max_length=300),
        FieldSchema(name="page_number",    dtype=DataType.INT64),

        # ── Content + vector ──────────────────────────────────────────────────
        FieldSchema(name="chunk_text",     dtype=DataType.VARCHAR, max_length=_CHUNK_TEXT_MAX_LENGTH),
        FieldSchema(name="embedding",      dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
    ]

    schema = CollectionSchema(fields, description="School curriculum document chunks")
    col = Collection(COLLECTION_NAME, schema, consistency_level="Strong")

    # Vector index
    col.create_index(
        "embedding",
        {
            "index_type": "HNSW",
            "metric_type": "COSINE",
            "params": {"M": 16, "efConstruction": 256},
        },
    )

    # Scalar indexes for filtering
    for field in ("document_id", "subject", "class_level", "document_type",
                  "language", "academic_year", "term", "document_title"):
        col.create_index(field, _INVERTED)

    col.load()
    print(f"[OK] Milvus collection '{COLLECTION_NAME}' created and loaded.")
    return col


# Track whether we have already called load() in this process. Each Celery
# worker process and the FastAPI process keep their own flag — that is safe
# because Milvus holds the in-memory state server-side.
_collection_loaded: bool = False


def _get_collection() -> Collection:
    global _collection_loaded
    col = Collection(COLLECTION_NAME)
    if not _collection_loaded:
        col.load()
        _collection_loaded = True
    return col


# ─── Write operations ─────────────────────────────────────────────────────────

def insert_chunks(chunks: list[dict]) -> None:
    """
    Insert a batch of chunk records.
    Each dict must have all schema fields:
      chunk_id, document_id, chunk_index, document_title, subject, class_level,
      document_type, language, academic_year, term, chapter_number, chapter_title,
      page_number, chunk_text, embedding.
    """
    if not chunks:
        return

    col = _get_collection()
    fields_order = [
        "chunk_id", "document_id", "chunk_index",
        "document_title", "subject", "class_level",
        "document_type", "language", "academic_year", "term",
        "chapter_number", "chapter_title", "page_number",
        "chunk_text", "embedding",
    ]
    data = [[c[f] for c in chunks] for f in fields_order]
    col.insert(data)
    col.flush()


def delete_document_chunks(document_id: str) -> None:
    """Remove all vectors belonging to a document."""
    col = _get_collection()
    results = col.query(
        expr=f'document_id == "{document_id}"',
        output_fields=["chunk_id"],
        consistency_level="Strong",
    )
    if not results:
        return
    pks = [r["chunk_id"] for r in results]
    for i in range(0, len(pks), 1000):
        batch = pks[i : i + 1000]
        pk_list = ", ".join(f'"{pk}"' for pk in batch)
        col.delete(f"chunk_id in [{pk_list}]")
    col.flush()


# ─── Search ───────────────────────────────────────────────────────────────────

def search_chunks(
    query_embedding: list[float],
    subject: str | None = None,
    class_level: str | None = None,
    document_type: str | None = None,
    language: str | None = None,
    academic_year: str | None = None,
    term: str | None = None,
    limit: int = 8,
) -> list[dict]:
    """
    ANN search with optional scalar pre-filters.
    Returns chunks ordered by cosine similarity (highest first).
    """
    col = _get_collection()

    filters: list[str] = []
    for field, value in (
        ("subject",       subject),
        ("class_level",   class_level),
        ("document_type", document_type),
        ("language",      language),
        ("academic_year", academic_year),
        ("term",          term),
    ):
        if value:
            safe = value.replace('"', '\\"')
            filters.append(f'{field} == "{safe}"')

    expr = " && ".join(filters) if filters else None

    results = col.search(
        data=[query_embedding],
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {"ef": 64}},
        limit=limit,
        expr=expr,
        output_fields=[
            "chunk_id", "document_id", "chunk_index",
            "document_title", "subject", "class_level",
            "document_type", "language", "academic_year", "term",
            "chapter_number", "chapter_title", "page_number",
            "chunk_text",
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
            "document_type":  e.get("document_type"),
            "language":       e.get("language"),
            "academic_year":  e.get("academic_year"),
            "term":           e.get("term"),
            "chapter_number": e.get("chapter_number"),
            "chapter_title":  e.get("chapter_title"),
            "page_number":    e.get("page_number"),
            "chunk_text":     e.get("chunk_text"),
            "score":          float(hit.score),
        })
    return chunks


# ─── Full-document retrieval (exhaustive mode) ────────────────────────────────

def query_all_chunks_for_document(
    document_title: str,
    subject: str | None = None,
    class_level: str | None = None,
    language: str | None = None,
    chapter_title: str | None = None,
    limit: int = 16384,
) -> list[dict]:
    """Fetch every chunk of a document (or chapter) in reading order.

    Used for `exhaustive` queries where the agent needs ALL content, not
    just a similar subset. Bypasses ANN search.
    """
    col = _get_collection()

    def esc(s: str) -> str:
        return s.replace('"', '\\"')

    conditions = [f'document_title == "{esc(document_title)}"']
    if subject:
        conditions.append(f'subject == "{esc(subject)}"')
    if class_level:
        conditions.append(f'class_level == "{esc(class_level)}"')
    if language:
        conditions.append(f'language == "{esc(language)}"')
    if chapter_title:
        conditions.append(f'chapter_title == "{esc(chapter_title)}"')

    expr = " && ".join(conditions)
    results = col.query(
        expr=expr,
        output_fields=[
            "chunk_id", "document_id", "chunk_index",
            "document_title", "subject", "class_level",
            "document_type", "language", "academic_year", "term",
            "chapter_number", "chapter_title", "page_number",
            "chunk_text",
        ],
        limit=limit,
        consistency_level="Strong",
    )

    # Sort by document then chunk_index → preserves natural reading order
    results.sort(key=lambda r: (r.get("document_title", ""), r.get("chunk_index", 0)))
    for r in results:
        r["score"] = 1.0
    return results
