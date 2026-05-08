import re
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Document, DocumentChunk

# ─── TEXT EXTRACTION ──────────────────────────────────────────────────────────


def extract_text_from_pdf(file_path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(file_path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def extract_text_from_docx(file_path: str) -> str:
    from docx import Document as DocxDocument
    doc = DocxDocument(file_path)
    parts = []
    # Extract paragraph text
    for p in doc.paragraphs:
        if p.text.strip():
            parts.append(p.text)
    # Extract table content (lesson plans often use tables)
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def extract_text_from_txt(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def extract_text_from_doc(file_path: str) -> str:
    """Extract text from old .doc files using Word COM automation (Windows)."""
    import os
    abs_path = os.path.abspath(file_path)
    try:
        import win32com.client
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        doc = word.Documents.Open(abs_path)
        text = doc.Content.Text
        doc.Close(False)
        word.Quit()
        if not text or len(text.strip()) < 50:
            raise ValueError("Could not extract meaningful text from .doc file")
        return text
    except ImportError:
        # Fallback to olefile binary extraction
        try:
            import olefile
            ole = olefile.OleFileIO(abs_path)
            text_parts = []
            for stream in ole.listdir():
                try:
                    raw = ole.openstream(stream).read()
                    decoded = raw.decode("utf-8", errors="ignore")
                    readable = re.findall(r'[\x20-\x7E\u0600-\u06FF\u0750-\u077F]{10,}', decoded)
                    if readable:
                        text_parts.extend(readable)
                except Exception:
                    pass
            ole.close()
            result = "\n".join(text_parts)
            if len(result.strip()) < 50:
                raise ValueError("Could not extract meaningful text from .doc file")
            return result
        except ImportError:
            raise ValueError("pywin32 or olefile required for .doc files")


def extract_text(file_path: str, file_type: str) -> str:
    ext = file_type.lower().lstrip(".")
    if ext == "pdf":
        return extract_text_from_pdf(file_path)
    elif ext == "docx":
        return extract_text_from_docx(file_path)
    elif ext in ("doc", "inp"):
        return extract_text_from_doc(file_path)
    elif ext == "txt":
        return extract_text_from_txt(file_path)
    else:
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
    chunks = []
    i = 0

    while i < len(words):
        end = min(i + CHUNK_SIZE, len(words))
        chunk = " ".join(words[i:end])
        if len(chunk.strip()) > 50:
            chunks.append({"text": chunk.strip(), "word_count": end - i, "index": len(chunks)})
        i += CHUNK_SIZE - CHUNK_OVERLAP

    return chunks


# ─── DOCUMENT INGESTION ──────────────────────────────────────────────────────


async def ingest_document(document_id: str, db: AsyncSession):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise ValueError("Document not found")

    try:
        raw_text = extract_text(doc.file_path, doc.file_type)

        if not raw_text or len(raw_text.strip()) < 50:
            raise ValueError("Could not extract meaningful text from document")

        chunks = chunk_text(raw_text)
        if not chunks:
            raise ValueError("No valid text chunks could be created")

        # Delete old chunks
        await db.execute(
            DocumentChunk.__table__.delete().where(DocumentChunk.document_id == document_id)
        )

        # Insert new chunks
        for chunk in chunks:
            db.add(DocumentChunk(
                document_id=document_id,
                chunk_text=chunk["text"],
                chunk_index=chunk["index"],
                word_count=chunk["word_count"],
            ))

        doc.is_ingested = True
        doc.total_chunks = len(chunks)
        doc.ingestion_error = None
        await db.commit()

        return {"success": True, "chunks_created": len(chunks)}

    except Exception as e:
        doc.is_ingested = False
        doc.ingestion_error = str(e)
        await db.commit()
        raise


# ─── KNOWLEDGE BASE SEARCH ───────────────────────────────────────────────────


async def search_knowledge_base(
    query: str, db: AsyncSession, subject: str = None, class_level: str = None, limit: int = 8
) -> list[dict]:
    try:
        keywords = [w for w in query.split() if len(w) > 2]
        if not keywords:
            return []

        # Build LIKE conditions - search in chunk_text, title, AND subject
        chunk_conds = [f"dc.chunk_text LIKE :kw{i}" for i in range(len(keywords))]
        title_conds = [f"d.title LIKE :kw{i}" for i in range(len(keywords))]
        subject_conds = [f"d.subject LIKE :kw{i}" for i in range(len(keywords))]
        # Match if ANY keyword found in chunk_text OR title OR subject
        conditions = " OR ".join(chunk_conds + title_conds + subject_conds)

        # Relevance = count of how many keywords match in each chunk + title bonus
        relevance_parts = [f"(CASE WHEN dc.chunk_text LIKE :kw{i} THEN 1 ELSE 0 END)" for i in range(len(keywords))]
        title_parts = [f"(CASE WHEN d.title LIKE :kw{i} THEN 3 ELSE 0 END)" for i in range(len(keywords))]
        subject_parts = [f"(CASE WHEN d.subject LIKE :kw{i} THEN 2 ELSE 0 END)" for i in range(len(keywords))]
        relevance_score = " + ".join(relevance_parts + title_parts + subject_parts)

        params = {f"kw{i}": f"%{kw}%" for i, kw in enumerate(keywords)}
        params["lim"] = limit

        doc_filter = ""
        if subject:
            doc_filter += " AND d.subject LIKE :subject"
            params["subject"] = f"%{subject}%"
        if class_level:
            doc_filter += " AND (d.class_level LIKE :class_level OR d.class_level = 'All Classes')"
            params["class_level"] = f"%{class_level}%"

        sql = text(f"""
            SELECT
                dc.id, dc.chunk_text, dc.chunk_index,
                d.title AS document_title, d.subject, d.class_level,
                ({relevance_score}) AS rank
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE d.is_ingested = 1 AND ({conditions}) {doc_filter}
            ORDER BY rank DESC, dc.chunk_index ASC
            LIMIT :lim
        """)

        result = await db.execute(sql, params)
        rows = result.mappings().all()
        return [dict(r) for r in rows]

    except Exception as e:
        print(f"Knowledge base search error: {e}")
        return []


# ─── BUILD CONTEXT ────────────────────────────────────────────────────────────


def build_context(search_results: list[dict]) -> str | None:
    if not search_results:
        return None

    parts = []
    for i, r in enumerate(search_results):
        parts.append(
            f'[Source {i + 1}: "{r["document_title"]}" ({r["subject"]} - {r["class_level"]})]\n{r["chunk_text"]}'
        )
    return "\n\n---\n\n".join(parts)
