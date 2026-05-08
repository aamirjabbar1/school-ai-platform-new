"""
Document ingestion pipeline:
  1. Download file bytes from MinIO
  2. Extract text (PDF / DOCX / DOC / TXT)
  3. Split into 400-word chunks with 50-word overlap
  4. Generate embeddings via fastembed (BAAI/bge-small-en-v1.5)
  5. Insert chunk records into PostgreSQL (metadata + text)
  6. Insert vectors into Milvus (chunk_id + embedding)
  7. Update Document.is_ingested = True in PostgreSQL

RAG search:
  1. Embed the query (fastembed)
  2. ANN search in Milvus with optional subject/class_level filter
  3. Return structured results (chunk_text, document_title, subject, class_level)
"""
import asyncio
import io
import re
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Document, DocumentChunk
from services import storage_service, embedding_service, vector_service


# ─── TEXT EXTRACTION (operates on bytes) ──────────────────────────────────────

def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx(data: bytes) -> str:
    from docx import Document as DocxDoc
    doc = DocxDoc(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _extract_doc(data: bytes) -> str:
    """Old .doc format: try olefile binary extraction."""
    try:
        import olefile
        ole = olefile.OleFileIO(io.BytesIO(data))
        text_parts = []
        for stream in ole.listdir():
            try:
                raw = ole.openstream(stream).read()
                readable = re.findall(r'[\x20-\x7E؀-ۿݐ-ݿ]{10,}', raw.decode("utf-8", errors="ignore"))
                text_parts.extend(readable)
            except Exception:
                pass
        ole.close()
        result = "\n".join(text_parts)
        if len(result.strip()) < 50:
            raise ValueError("olefile extracted too little text")
        return result
    except ImportError:
        raise ValueError("olefile package required for .doc files")


def _extract_txt(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def extract_text_from_bytes(data: bytes, file_type: str) -> str:
    ext = file_type.lower().lstrip(".")
    if ext == "pdf":
        return _extract_pdf(data)
    if ext == "docx":
        return _extract_docx(data)
    if ext in ("doc", "inp"):
        return _extract_doc(data)
    if ext == "txt":
        return _extract_txt(data)
    raise ValueError(f"Unsupported file type: {file_type}")


# ─── TEXT CHUNKING ────────────────────────────────────────────────────────────

CHUNK_SIZE = 400
CHUNK_OVERLAP = 50


def chunk_text(raw_text: str) -> list[dict]:
    cleaned = re.sub(r"\r\n", "\n", raw_text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return []

    words = cleaned.split()
    chunks, i = [], 0
    while i < len(words):
        end = min(i + CHUNK_SIZE, len(words))
        chunk = " ".join(words[i:end])
        if len(chunk.strip()) > 50:
            chunks.append({"text": chunk.strip(), "word_count": end - i, "index": len(chunks)})
        i += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


# ─── DOCUMENT INGESTION ───────────────────────────────────────────────────────

async def ingest_document(document_id: str, db: AsyncSession) -> dict:
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise ValueError("Document not found")

    try:
        # 1. Download from MinIO (sync → thread)
        file_bytes = await asyncio.to_thread(storage_service.download_file, doc.file_path)

        # 2. Extract text (sync CPU → thread)
        raw_text = await asyncio.to_thread(extract_text_from_bytes, file_bytes, doc.file_type)
        if not raw_text or len(raw_text.strip()) < 50:
            raise ValueError("Could not extract meaningful text from document")

        # 3. Chunk
        chunks = chunk_text(raw_text)
        if not chunks:
            raise ValueError("No valid text chunks could be created")

        # 4. Embed all chunks in one batch (sync CPU → thread)
        texts = [c["text"] for c in chunks]
        embeddings = await asyncio.to_thread(embedding_service.embed_texts, texts)

        # 5. Delete old PostgreSQL chunks
        await db.execute(
            DocumentChunk.__table__.delete().where(DocumentChunk.document_id == document_id)
        )

        # 6. Insert new PostgreSQL chunks (metadata + text)
        pg_chunks = []
        for chunk, emb in zip(chunks, embeddings):
            chunk_id = str(uuid.uuid4())
            pg_chunks.append(DocumentChunk(
                id=chunk_id,
                document_id=document_id,
                chunk_text=chunk["text"],
                chunk_index=chunk["index"],
                word_count=chunk["word_count"],
            ))
        db.add_all(pg_chunks)
        await db.flush()  # get IDs without committing yet

        # 7. Build Milvus records (use same chunk_id as PostgreSQL)
        milvus_records = [
            {
                "chunk_id":       pg_c.id,
                "document_id":    document_id,
                "chunk_index":    chunk["index"],
                "document_title": doc.title[:500],
                "subject":        doc.subject[:100],
                "class_level":    doc.class_level[:50],
                "chunk_text":     chunk["text"][:8000],
                "embedding":      emb,
            }
            for pg_c, chunk, emb in zip(pg_chunks, chunks, embeddings)
        ]

        # 8. Delete old Milvus vectors + insert new (sync → thread)
        await asyncio.to_thread(vector_service.delete_document_chunks, document_id)
        await asyncio.to_thread(vector_service.insert_chunks, milvus_records)

        # 9. Update document status
        doc.is_ingested = True
        doc.total_chunks = len(chunks)
        doc.ingestion_error = None
        await db.commit()

        return {"success": True, "chunks_created": len(chunks)}

    except Exception as exc:
        await db.rollback()
        # Mark document as failed
        try:
            result = await db.execute(select(Document).where(Document.id == document_id))
            doc = result.scalar_one_or_none()
            if doc:
                doc.is_ingested = False
                doc.ingestion_error = str(exc)[:500]
                await db.commit()
        except Exception:
            pass
        raise


# ─── KNOWLEDGE BASE SEARCH (vector search via Milvus) ────────────────────────

async def search_knowledge_base(
    query: str,
    subject: str | None = None,
    class_level: str | None = None,
    limit: int = 8,
) -> list[dict]:
    """
    Semantic search over ingested document chunks using Milvus ANN.
    Returns chunks sorted by cosine similarity.
    """
    try:
        # Embed query (sync CPU → thread)
        query_embedding = await asyncio.to_thread(embedding_service.embed_query, query)

        # Vector search in Milvus (sync → thread)
        results = await asyncio.to_thread(
            vector_service.search_chunks,
            query_embedding,
            subject,
            class_level,
            limit,
        )
        return results
    except Exception as exc:
        print(f"[search_knowledge_base] error: {exc}")
        return []


# ─── BUILD CONTEXT STRING FOR PROMPTS ────────────────────────────────────────

def build_context(search_results: list[dict]) -> str | None:
    if not search_results:
        return None
    parts = [
        f'[Source {i + 1}: "{r["document_title"]}" ({r["subject"]} – {r["class_level"]})]\n{r["chunk_text"]}'
        for i, r in enumerate(search_results)
    ]
    return "\n\n---\n\n".join(parts)
