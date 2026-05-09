"""
Document ingestion pipeline:
  1. Download file bytes from MinIO
  2. Extract text via Claude Sonnet 4.6 (PDF: 50 pages/chunk, DOCX: 3000 words/batch)
  3. Split into 400-word chunks with 50-word overlap; extract chapter/page per chunk
  4. Generate embeddings via OpenAI text-embedding-3-large
  5. Insert chunk records into PostgreSQL (metadata + text)
  6. Insert vectors into Milvus (all metadata fields + embedding)
  7. Update Document.is_ingested = True in PostgreSQL

RAG search:
  1. Embed the query (OpenAI)
  2. ANN search in Milvus with optional filters:
     subject, class_level, document_type, language, academic_year, term
  3. Return structured results with full citation info
"""
import asyncio
import base64
import io
import re
import uuid

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Document, DocumentChunk
from services import storage_service, embedding_service, vector_service


_CLAUDE_MODEL = "claude-sonnet-4-6"
_PDF_PAGES_PER_CHUNK = 50
_DOCX_WORDS_PER_BATCH = 3000
_MAX_CONCURRENT_CLAUDE_CALLS = 3

_EXTRACTION_PROMPT = (
    "Extract all text from this PDF exactly as written. "
    "Preserve headings, subheadings, paragraph breaks, bullet points, "
    "numbered lists, and tables (format tables as markdown). "
    "Mark chapter headings with a single # prefix and section headings with ##. "
    "Include page numbers where visible. Output plain structured text only, no commentary."
)

_STRUCTURING_PROMPT = (
    "Clean and structure the following extracted document content. "
    "Preserve all text exactly, fix any spacing or formatting artifacts, "
    "maintain document hierarchy (headings with #, subheadings with ##, body), "
    "and format tables as markdown. Output clean structured text only.\n\n"
)


# ─── CLAUDE-BASED TEXT EXTRACTION ─────────────────────────────────────────────

async def _extract_pdf_claude(data: bytes) -> str:
    """Split PDF into 50-page chunks, extract text from each via Claude Sonnet."""
    from pypdf import PdfReader, PdfWriter

    client = anthropic.AsyncAnthropic()
    sem = asyncio.Semaphore(_MAX_CONCURRENT_CLAUDE_CALLS)
    reader = PdfReader(io.BytesIO(data))
    total_pages = len(reader.pages)

    async def process_chunk(start: int, end: int) -> str:
        writer = PdfWriter()
        for page_num in range(start, end):
            writer.add_page(reader.pages[page_num])

        chunk_buf = io.BytesIO()
        writer.write(chunk_buf)
        pdf_b64 = base64.standard_b64encode(chunk_buf.getvalue()).decode()

        async with sem:
            response = await client.messages.create(
                model=_CLAUDE_MODEL,
                max_tokens=8192,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_b64,
                            },
                        },
                        {"type": "text", "text": _EXTRACTION_PROMPT},
                    ],
                }],
            )
        return response.content[0].text

    tasks = [
        process_chunk(start, min(start + _PDF_PAGES_PER_CHUNK, total_pages))
        for start in range(0, total_pages, _PDF_PAGES_PER_CHUNK)
    ]
    results = await asyncio.gather(*tasks)
    return "\n\n".join(results)


async def _extract_docx_claude(data: bytes) -> str:
    """Extract DOCX content via python-docx, then structure and clean via Claude Sonnet."""
    from docx import Document as DocxDoc

    client = anthropic.AsyncAnthropic()
    sem = asyncio.Semaphore(_MAX_CONCURRENT_CLAUDE_CALLS)
    doc = DocxDoc(io.BytesIO(data))

    raw_blocks: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = para.style.name if para.style else ""
        if "Heading 1" in style:
            raw_blocks.append(f"# {text}")
        elif "Heading 2" in style:
            raw_blocks.append(f"## {text}")
        elif "Heading" in style:
            raw_blocks.append(f"### {text}")
        else:
            raw_blocks.append(text)

    for table in doc.tables:
        rows = [" | ".join(c.text.strip() for c in row.cells) for row in table.rows]
        if rows:
            raw_blocks.append("\n".join(rows))

    batches: list[str] = []
    current: list[str] = []
    current_words = 0
    for block in raw_blocks:
        w = len(block.split())
        if current_words + w > _DOCX_WORDS_PER_BATCH and current:
            batches.append("\n\n".join(current))
            current, current_words = [block], w
        else:
            current.append(block)
            current_words += w
    if current:
        batches.append("\n\n".join(current))

    if not batches:
        return ""

    async def process_batch(raw_text: str) -> str:
        async with sem:
            response = await client.messages.create(
                model=_CLAUDE_MODEL,
                max_tokens=8192,
                messages=[{
                    "role": "user",
                    "content": _STRUCTURING_PROMPT + raw_text,
                }],
            )
        return response.content[0].text

    results = await asyncio.gather(*[process_batch(b) for b in batches])
    return "\n\n".join(results)


def _extract_doc_sync(data: bytes) -> str:
    """Legacy .doc format via olefile binary extraction."""
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


async def extract_text_from_bytes(data: bytes, file_type: str) -> str:
    ext = file_type.lower().lstrip(".")
    if ext == "pdf":
        return await _extract_pdf_claude(data)
    if ext == "docx":
        return await _extract_docx_claude(data)
    if ext in ("doc", "inp"):
        return await asyncio.to_thread(_extract_doc_sync, data)
    if ext == "txt":
        return data.decode("utf-8", errors="replace")
    raise ValueError(f"Unsupported file type: {file_type}")


# ─── TEXT CHUNKING WITH CHAPTER EXTRACTION ───────────────────────────────────

CHUNK_SIZE = 400
CHUNK_OVERLAP = 50
_WORDS_PER_PAGE = 275  # average for a textbook page


def _build_chapter_map(text: str) -> list[tuple[int, int, str]]:
    """
    Scan multi-line text for top-level headings (# but not ##).
    Returns sorted list of (word_offset, chapter_number, chapter_title).
    word_offset is the cumulative word count before that heading line.
    """
    breakpoints: list[tuple[int, int, str]] = [(0, 0, "")]
    chapter_num = 0
    word_offset = 0

    for line in text.split("\n"):
        stripped = line.strip()
        if re.match(r"^# (?!#)", stripped):
            title = stripped[2:].strip()
            chapter_num += 1
            breakpoints.append((word_offset, chapter_num, title))
        word_offset += len(stripped.split()) if stripped else 0

    return breakpoints


def _chapter_at(breakpoints: list[tuple[int, int, str]], word_pos: int) -> tuple[int, str]:
    chapter_num, chapter_title = 0, ""
    for offset, num, title in breakpoints:
        if offset <= word_pos:
            chapter_num, chapter_title = num, title
        else:
            break
    return chapter_num, chapter_title


def chunk_text(raw_text: str) -> list[dict]:
    # Normalise line endings, collapse excess blank lines
    cleaned = re.sub(r"\r\n", "\n", raw_text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    # Build chapter map before flattening whitespace
    chapter_map = _build_chapter_map(cleaned)

    # Flatten to a single word stream
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return []

    words = cleaned.split()
    chunks: list[dict] = []
    i = 0
    while i < len(words):
        end = min(i + CHUNK_SIZE, len(words))
        chunk = " ".join(words[i:end])
        if len(chunk.strip()) > 50:
            chapter_num, chapter_title = _chapter_at(chapter_map, i)
            page_num = max(1, round(i / _WORDS_PER_PAGE) + 1)
            chunks.append({
                "text":           chunk.strip(),
                "word_count":     end - i,
                "index":          len(chunks),
                "chapter_number": chapter_num,
                "chapter_title":  chapter_title[:300],
                "page_number":    page_num,
            })
        i += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


# ─── DOCUMENT INGESTION ───────────────────────────────────────────────────────

async def ingest_document(document_id: str, db: AsyncSession) -> dict:
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise ValueError("Document not found")

    try:
        # 1. Download from MinIO
        file_bytes = await asyncio.to_thread(storage_service.download_file, doc.file_path)

        # 2. Extract text via Claude Sonnet 4.6
        raw_text = await extract_text_from_bytes(file_bytes, doc.file_type)
        if not raw_text or len(raw_text.strip()) < 50:
            raise ValueError("Could not extract meaningful text from document")

        # 3. Chunk (with chapter + page metadata)
        chunks = chunk_text(raw_text)
        if not chunks:
            raise ValueError("No valid text chunks could be created")

        # 4. Embed all chunks in one batched call
        texts = [c["text"] for c in chunks]
        embeddings = await asyncio.to_thread(embedding_service.embed_texts, texts)

        # 5. Delete old PostgreSQL chunks
        await db.execute(
            DocumentChunk.__table__.delete().where(DocumentChunk.document_id == document_id)
        )

        # 6. Insert new PostgreSQL chunks
        pg_chunks = []
        for chunk in chunks:
            pg_chunks.append(DocumentChunk(
                id=str(uuid.uuid4()),
                document_id=document_id,
                chunk_text=chunk["text"],
                chunk_index=chunk["index"],
                word_count=chunk["word_count"],
            ))
        db.add_all(pg_chunks)
        await db.flush()

        # 7. Build Milvus records with full metadata
        milvus_records = [
            {
                "chunk_id":       pg_c.id,
                "document_id":    document_id,
                "chunk_index":    chunk["index"],
                "document_title": doc.title[:500],
                "subject":        doc.subject[:100],
                "class_level":    doc.class_level[:50],
                "document_type":  (doc.document_type or "book")[:50],
                "language":       (doc.language or "English")[:20],
                "academic_year":  (doc.academic_year or "")[:20],
                "term":           (doc.term or "")[:30],
                "chapter_number": chunk["chapter_number"],
                "chapter_title":  chunk["chapter_title"][:300],
                "page_number":    chunk["page_number"],
                "chunk_text":     chunk["text"][:8000],
                "embedding":      emb,
            }
            for pg_c, chunk, emb in zip(pg_chunks, chunks, embeddings)
        ]

        # 8. Delete old Milvus vectors + insert new
        await asyncio.to_thread(vector_service.delete_document_chunks, document_id)
        await asyncio.to_thread(vector_service.insert_chunks, milvus_records)

        # 9. Mark as ingested
        doc.is_ingested = True
        doc.total_chunks = len(chunks)
        doc.ingestion_error = None
        await db.commit()

        return {"success": True, "chunks_created": len(chunks)}

    except Exception as exc:
        await db.rollback()
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


# ─── KNOWLEDGE BASE SEARCH ────────────────────────────────────────────────────

async def search_knowledge_base(
    query: str,
    subject: str | None = None,
    class_level: str | None = None,
    document_type: str | None = None,
    language: str | None = None,
    academic_year: str | None = None,
    term: str | None = None,
    limit: int = 8,
) -> list[dict]:
    """
    Semantic search over ingested document chunks.
    All filter parameters are optional and can be combined.
    document_type: "book" | "exam" | "assignment" | "notes" | "worksheet"
    """
    try:
        query_embedding = await asyncio.to_thread(embedding_service.embed_query, query)
        results = await asyncio.to_thread(
            vector_service.search_chunks,
            query_embedding,
            subject,
            class_level,
            document_type,
            language,
            academic_year,
            term,
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
    parts = []
    for i, r in enumerate(search_results):
        # Build a rich citation header
        location_parts = []
        if r.get("chapter_number") and r["chapter_number"] > 0:
            ch = f"Chapter {r['chapter_number']}"
            if r.get("chapter_title"):
                ch += f": {r['chapter_title']}"
            location_parts.append(ch)
        if r.get("page_number") and r["page_number"] > 0:
            location_parts.append(f"p. {r['page_number']}")
        if r.get("term"):
            location_parts.append(r["term"])
        if r.get("academic_year"):
            location_parts.append(r["academic_year"])

        location = " | ".join(location_parts)
        doc_info = f'"{r["document_title"]}" ({r["subject"]} – {r["class_level"]} – {r.get("document_type", "book")})'
        header = f"[Source {i + 1}: {doc_info}]"
        if location:
            header += f"\n[{location}]"

        parts.append(f"{header}\n{r['chunk_text']}")

    return "\n\n---\n\n".join(parts)
