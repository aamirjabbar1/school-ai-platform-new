"""
Document ingestion pipeline (Claude-only extraction, vision-aware):

  1. Download file bytes from MinIO
  2. Extract text + figure descriptions via Claude Sonnet 4.6
       PDF:  8 pages/chunk, max_tokens=16384, vision-enabled prompt
       DOCX: 3000 words/batch, structuring pass
  3. Structure-aware chunking that respects pages/chapters/tables/figures
  4. Generate embeddings via OpenAI text-embedding-3-large
  5. Insert chunks into PostgreSQL (metadata + text)
  6. Insert vectors into Milvus (all metadata + embedding)
  7. Mark Document.is_ingested = True

RAG search:
  1. Embed the query (OpenAI)
  2. ANN search in Milvus with optional filters
  3. Return chunks with structured context (no Anthropic Citations API)
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

# Smaller PDF slices so the model can output every word verbatim within
# max_tokens. 8 pages × ~500 words = ~4000 words ≈ 6k output tokens; figures
# and tables push this higher, so we leave plenty of headroom.
_PDF_PAGES_PER_CHUNK = 8
_PDF_MAX_TOKENS = 16384

_DOCX_WORDS_PER_BATCH = 3000
_DOCX_MAX_TOKENS = 8192

# Org limit is 30k input tokens/min on Sonnet 4.6.
# Sequential calls (1 at a time) with a short gap stay under the limit.
_INTER_CHUNK_DELAY_SECS = 1


# Vision-aware extraction prompt: reproduces every word, transcribes equations
# in LaTeX, describes every figure inline, and emits [Page N] markers so the
# downstream chunker can attach real page numbers.
_EXTRACTION_PROMPT = (
    "Extract ALL content from this PDF exactly as written. Do not skip, summarize, "
    "shorten, or paraphrase anything. Reproduce every sentence, every list item, "
    "every caption, every footnote, every header, and every footer.\n\n"
    "FORMATTING RULES:\n"
    "- At the start of each PDF page, put a marker on its own line: [Page N] "
    "(use the page number printed on the page; if none is visible, use the "
    "sequential index starting from 1).\n"
    "- Mark the start of a chapter with a single '#' heading, e.g. '# Chapter 3: Photosynthesis'.\n"
    "- Mark sections with '##' and subsections with '###'. Headings sit on their own line.\n"
    "- Preserve paragraph breaks as a blank line.\n"
    "- Reproduce numbered and bulleted lists item-by-item.\n"
    "- Reproduce tables as full GitHub-flavoured markdown tables with every cell, "
    "every row, every column, and the header separator row. Never abbreviate, "
    "summarise, or skip any cell.\n"
    "- Transcribe mathematical equations and formulas in LaTeX: inline as $...$, "
    "display as $$...$$. Preserve subscripts, superscripts, fractions, integrals.\n"
    "- For each figure, image, diagram, chart, illustration, photograph, map, "
    "or scientific schematic, insert at the position where it appears in the page:\n"
    "    [FIGURE: <2-4 sentence description>] \n"
    "  The description must be concrete and searchable: name what is shown, "
    "any visible labels, axes, units, key data values, and any equations or "
    "annotations. Include the figure number/caption verbatim if present.\n"
    "- Output plain structured text only. No introductions, no commentary, "
    "no 'here is the extracted text', no closing remarks."
)

_STRUCTURING_PROMPT = (
    "Clean and structure the following extracted document content. "
    "Preserve all text exactly, fix any spacing or formatting artifacts, "
    "maintain document hierarchy (# for chapters, ## for sections, ### for subsections), "
    "format tables as full markdown tables, and keep equations in LaTeX. "
    "Output clean structured text only.\n\n"
)


# ─── CLAUDE-BASED TEXT EXTRACTION ─────────────────────────────────────────────

async def _extract_pdf_claude(data: bytes) -> str:
    """Split PDF into 8-page chunks, extract text + figure descriptions sequentially."""
    from pypdf import PdfReader, PdfWriter

    client = anthropic.AsyncAnthropic(max_retries=5)
    reader = PdfReader(io.BytesIO(data))
    total_pages = len(reader.pages)

    chunk_starts = list(range(0, total_pages, _PDF_PAGES_PER_CHUNK))
    results: list[str] = []

    for i, start in enumerate(chunk_starts):
        end = min(start + _PDF_PAGES_PER_CHUNK, total_pages)

        writer = PdfWriter()
        for page_num in range(start, end):
            writer.add_page(reader.pages[page_num])

        chunk_buf = io.BytesIO()
        writer.write(chunk_buf)
        pdf_b64 = base64.standard_b64encode(chunk_buf.getvalue()).decode()

        # Hint Claude with the absolute page numbers in the original PDF so
        # the [Page N] markers it emits match real page numbers.
        offset_hint = (
            f"\n\nThis PDF slice covers pages {start + 1} through {end} of the "
            f"original document. Use those page numbers in [Page N] markers."
        )

        response = await client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=_PDF_MAX_TOKENS,
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
                    {"type": "text", "text": _EXTRACTION_PROMPT + offset_hint},
                ],
            }],
        )
        results.append(response.content[0].text)

        if i < len(chunk_starts) - 1:
            await asyncio.sleep(_INTER_CHUNK_DELAY_SECS)

    return "\n\n".join(results)


async def _extract_docx_claude(data: bytes) -> str:
    """Extract DOCX content via python-docx, then structure sequentially via Claude Sonnet."""
    from docx import Document as DocxDoc

    client = anthropic.AsyncAnthropic(max_retries=5)
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

    results: list[str] = []
    for i, raw_text in enumerate(batches):
        response = await client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=_DOCX_MAX_TOKENS,
            messages=[{
                "role": "user",
                "content": _STRUCTURING_PROMPT + raw_text,
            }],
        )
        results.append(response.content[0].text)
        if i < len(batches) - 1:
            await asyncio.sleep(_INTER_CHUNK_DELAY_SECS)

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


# ─── STRUCTURE-AWARE CHUNKING ────────────────────────────────────────────────
#
# Goals:
#   - Real page numbers (parsed from [Page N] markers Claude emits)
#   - Chapter/section context preserved (running counter)
#   - Tables and [FIGURE: ...] blocks are NEVER split across chunks
#   - Greedy paragraph packing up to a target word count, with overlap
#   - Hard char cap so we never exceed Milvus's chunk_text capacity
CHUNK_TARGET_WORDS = 600
CHUNK_OVERLAP_WORDS = 100
CHUNK_MIN_WORDS = 30
# Milvus chunk_text capacity is 16000; leave headroom for safety.
CHUNK_MAX_CHARS = 15000

_PAGE_RE = re.compile(r'\[Page\s+(\d+)\]', re.IGNORECASE)


def _segment_by_page(text: str) -> list[tuple[int, str]]:
    """Split text by [Page N] markers; returns [(page_num, content), ...]."""
    matches = list(_PAGE_RE.finditer(text))
    if not matches:
        return [(1, text)] if text.strip() else []

    pages: list[tuple[int, str]] = []
    pre = text[:matches[0].start()].strip()
    if pre:
        pages.append((1, pre))

    for i, m in enumerate(matches):
        try:
            page_num = int(m.group(1))
        except ValueError:
            page_num = i + 1
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if content:
            pages.append((page_num, content))
    return pages


def _split_into_units(text: str) -> list[str]:
    """Break a page into atomic units: paragraphs, headings, list blocks,
    markdown tables, and [FIGURE: ...] blocks. Tables and figures stay intact."""
    units: list[str] = []
    lines = text.split("\n")
    buffer: list[str] = []
    in_table = False

    def flush():
        if buffer:
            joined = "\n".join(buffer).strip()
            if joined:
                units.append(joined)
            buffer.clear()

    for line in lines:
        stripped = line.strip()
        is_table_line = stripped.startswith("|")
        is_blank = not stripped

        if in_table:
            if is_table_line or stripped.startswith(":---") or re.match(r"^[-:|\s]+$", stripped):
                buffer.append(line)
                continue
            # Table just ended
            flush()
            in_table = False
            if is_blank:
                continue
            buffer.append(line)
            continue

        if is_table_line:
            flush()
            in_table = True
            buffer.append(line)
            continue

        if is_blank:
            flush()
            continue

        buffer.append(line)

    flush()
    return units


def _compute_chapter_map(units: list[str]) -> list[tuple[int, str]]:
    """For each unit, return (chapter_number, chapter_title) currently in scope."""
    out: list[tuple[int, str]] = []
    cur_num, cur_title = 0, ""
    for unit in units:
        first_line = unit.split("\n", 1)[0].strip()
        if re.match(r"^#\s+(?!#)", first_line):
            cur_num += 1
            cur_title = first_line[2:].strip()[:300]
        out.append((cur_num, cur_title))
    return out


def chunk_text(raw_text: str) -> list[dict]:
    """Structure-aware chunker. Preserves tables, figures, real page numbers,
    and chapter context across chunks."""
    cleaned = re.sub(r'\r\n', '\n', raw_text)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

    pages = _segment_by_page(cleaned)
    if not pages:
        return []

    # Flatten into a unit stream that remembers each unit's page number
    units: list[str] = []
    unit_pages: list[int] = []
    for page_num, page_text in pages:
        for u in _split_into_units(page_text):
            units.append(u)
            unit_pages.append(page_num)

    if not units:
        return []

    chapter_map = _compute_chapter_map(units)

    chunks: list[dict] = []
    i = 0
    while i < len(units):
        cur_parts: list[str] = []
        cur_words = 0
        cur_chars = 0
        first_page = unit_pages[i]
        j = i

        while j < len(units):
            unit = units[j]
            unit_words = len(unit.split())
            unit_chars = len(unit) + 2  # join separator approx

            # Stop adding if this unit would overflow AND we already have content
            if cur_parts and (
                cur_words + unit_words > CHUNK_TARGET_WORDS
                or cur_chars + unit_chars > CHUNK_MAX_CHARS
            ):
                break

            cur_parts.append(unit)
            cur_words += unit_words
            cur_chars += unit_chars
            j += 1

            # Once we hit the target, close the chunk. A single oversized
            # unit (giant table / figure block) is accepted whole to avoid
            # splitting it.
            if cur_words >= CHUNK_TARGET_WORDS or cur_chars >= CHUNK_MAX_CHARS:
                break

        chunk_body = "\n\n".join(cur_parts).strip()
        if len(chunk_body) > CHUNK_MAX_CHARS:
            chunk_body = chunk_body[:CHUNK_MAX_CHARS]

        if cur_words >= CHUNK_MIN_WORDS:
            chapter_num, chapter_title = chapter_map[i]
            chunks.append({
                "text":           chunk_body,
                "word_count":     cur_words,
                "index":          len(chunks),
                "chapter_number": chapter_num,
                "chapter_title":  chapter_title,
                "page_number":    first_page,
            })

        if j == i:
            j = i + 1
        if j >= len(units):
            break

        # Rewind for overlap: walk back until we accumulate ~CHUNK_OVERLAP_WORDS
        overlap = 0
        k = j - 1
        while k > i and overlap < CHUNK_OVERLAP_WORDS:
            overlap += len(units[k].split())
            k -= 1
        i = max(k, i + 1)

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

        # 3. Chunk (structure-aware: pages, chapters, tables, figures)
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
                "chunk_text":     chunk["text"][:CHUNK_MAX_CHARS],
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
#
# Hybrid retrieval pipeline:
#   1. Classify the query (point / conceptual / exhaustive / filtered)
#   2. Detect document/subject/class via the cached document index
#   3. Route:
#        exhaustive  → full-document retrieval (all chunks, in order)
#        point       → single hybrid search (vector + BM25 fusion)
#        conceptual /
#        filtered    → multi-query hybrid search (parallel, dedupe by best score)
#   4. Fuse vector + BM25 scores with weights 0.6 / 0.4
#   5. Fallback ladder if filtered search returns nothing.

# Hybrid fusion weights — vector dominates because curriculum queries are
# mostly conceptual; BM25 still boosts exact-keyword matches (formulas,
# article numbers, named theorems, specific Urdu/English terms).
_VECTOR_WEIGHT = 0.6
_BM25_WEIGHT   = 0.4
_VECTOR_CANDIDATES = 60
_BM25_CANDIDATES   = 60
_FUSION_TOP_K      = 40
_EXHAUSTIVE_MAX    = 200


async def _hybrid_search(
    query: str,
    subject: str | None = None,
    class_level: str | None = None,
    document_type: str | None = None,
    language: str | None = None,
    academic_year: str | None = None,
    term: str | None = None,
    document_title: str | None = None,
    top_k: int = _FUSION_TOP_K,
) -> list[dict]:
    """Run vector + BM25 in parallel and fuse with weighted normalised scores."""
    from services import bm25_service

    query_embedding = await asyncio.to_thread(embedding_service.embed_query, query)

    # Build a document_title-aware Milvus filter for vector search by routing
    # through the existing search_chunks (it already supports the other filters).
    # We don't have a `document_title` parameter on search_chunks, so when the
    # classifier detected a document title we still feed it as filter via
    # scalar pre-filtering at the BM25 layer + filter the vector results
    # client-side.
    vector_task = asyncio.to_thread(
        vector_service.search_chunks,
        query_embedding,
        subject, class_level, document_type, language, academic_year, term,
        _VECTOR_CANDIDATES,
    )
    bm25_task = asyncio.to_thread(
        bm25_service.get_retriever().search,
        query, _BM25_CANDIDATES,
        subject, class_level, document_type, language,
        academic_year, term, document_title,
    )

    vector_hits, bm25_hits = await asyncio.gather(
        vector_task, bm25_task, return_exceptions=True
    )
    if isinstance(vector_hits, Exception):
        print(f"[_hybrid_search] vector error: {vector_hits}")
        vector_hits = []
    if isinstance(bm25_hits, Exception):
        print(f"[_hybrid_search] bm25 error: {bm25_hits}")
        bm25_hits = []

    # Client-side filter on document_title (vector path doesn't support it).
    if document_title:
        vector_hits = [
            r for r in vector_hits if r.get("document_title") == document_title
        ]

    # ── Score fusion ─────────────────────────────────────────────────────────
    # Vector hits are ranked → assign rank-based normalised score [1.0 → 1/N]
    # BM25 hits arrive with their already-normalised score in r["score"]
    pool: dict[str, dict] = {}
    n_vec = len(vector_hits) or 1
    for rank, r in enumerate(vector_hits):
        cid = r.get("chunk_id")
        if not cid:
            continue
        rec = dict(r)
        rec["_vec_norm"] = 1.0 - (rank / n_vec)
        rec["_bm25_norm"] = 0.0
        pool[cid] = rec

    for r in bm25_hits:
        cid = r.get("chunk_id")
        if not cid:
            continue
        bm25_score = float(r.get("score", 0.0))
        if cid in pool:
            pool[cid]["_bm25_norm"] = bm25_score
        else:
            rec = dict(r)
            rec["_vec_norm"] = 0.0
            rec["_bm25_norm"] = bm25_score
            pool[cid] = rec

    for r in pool.values():
        r["score"] = (
            _VECTOR_WEIGHT * r.pop("_vec_norm")
            + _BM25_WEIGHT * r.pop("_bm25_norm")
        )

    return sorted(pool.values(), key=lambda x: -x["score"])[:top_k]


async def _multi_query_hybrid(
    queries: list[str],
    **filters,
) -> list[dict]:
    """Run several hybrid searches in parallel and merge keeping the best score per chunk."""
    if not queries:
        return []

    tasks = [_hybrid_search(q, **filters) for q in queries]
    all_hits = await asyncio.gather(*tasks, return_exceptions=True)

    merged: dict[str, dict] = {}
    for hits in all_hits:
        if isinstance(hits, Exception):
            print(f"[_multi_query_hybrid] sub-query failed: {hits}")
            continue
        for r in hits:
            cid = r.get("chunk_id")
            if not cid:
                continue
            if cid not in merged or r["score"] > merged[cid]["score"]:
                merged[cid] = r

    return sorted(merged.values(), key=lambda x: -x["score"])


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
    Hybrid retrieval pipeline (vector + BM25 + classifier-driven routing).

    Routes the query to the best retrieval strategy based on classification, then
    falls back across less-restrictive filters so the user always gets something
    when their question doesn't perfectly match the available corpus.
    """
    from services.query_classifier import classify_query

    try:
        cls = await classify_query(
            query,
            subject_hint=subject,
            class_hint=class_level,
        )
        qtype       = cls["type"]
        doc_title   = cls["document_title"]
        sub_queries = cls["sub_queries"] or []

        # Auto-fill filters that were not explicitly passed in
        eff_subject = subject or cls["subject"]
        eff_class   = class_level or cls["class_level"]
        eff_chapter = cls.get("chapter_title")

        print(
            f"[search_knowledge_base] type={qtype} doc='{doc_title}' "
            f"subject='{eff_subject}' class='{eff_class}' "
            f"sub_queries={len(sub_queries)} reason='{cls['reason']}'"
        )

        # ── Route 1: exhaustive (full document) ──────────────────────────────
        if qtype == "exhaustive" and doc_title:
            results = await asyncio.to_thread(
                vector_service.query_all_chunks_for_document,
                doc_title,
                eff_subject,
                eff_class,
                language,
                eff_chapter,
                _EXHAUSTIVE_MAX,
            )
            if results:
                return results[:_EXHAUSTIVE_MAX]
            # if nothing, fall through to hybrid

        # ── Route 2/3: hybrid (with optional multi-query expansion) ──────────
        filters = {
            "subject":        eff_subject,
            "class_level":    eff_class,
            "document_type":  document_type,
            "language":       language,
            "academic_year":  academic_year,
            "term":           term,
            "document_title": doc_title,
        }

        if qtype in ("conceptual", "filtered") and sub_queries:
            queries = [query] + sub_queries
            hits = await _multi_query_hybrid(queries, **filters)
        else:
            hits = await _hybrid_search(query, **filters)

        if hits:
            return hits[:limit]

        # ── Fallback ladder: progressively drop filters ──────────────────────
        # Only one fallback at a time to avoid blowing past the K limit on
        # a noisy corpus. Drop document_title first (most specific), then
        # subject, then class, then everything.
        if doc_title:
            hits = await _hybrid_search(
                query, subject=eff_subject, class_level=eff_class,
                document_type=document_type, language=language,
            )
            if hits:
                return hits[:limit]
        if eff_subject:
            hits = await _hybrid_search(
                query, class_level=eff_class,
                document_type=document_type, language=language,
            )
            if hits:
                return hits[:limit]
        if eff_class:
            hits = await _hybrid_search(
                query, document_type=document_type, language=language,
            )
            if hits:
                return hits[:limit]

        # Last resort: full corpus
        return (await _hybrid_search(query))[:limit]

    except Exception as exc:
        print(f"[search_knowledge_base] error: {exc}")
        import traceback
        traceback.print_exc()
        return []


# ─── BUILD CONTEXT STRING FOR PROMPTS ────────────────────────────────────────

def build_context(search_results: list[dict]) -> str | None:
    """Plain-text RAG context. No Anthropic Citations API; the AI may still
    refer to a chapter/page naturally in prose."""
    if not search_results:
        return None
    parts = []
    for i, r in enumerate(search_results):
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
