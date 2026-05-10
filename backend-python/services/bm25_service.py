"""
BM25 keyword search over the school document corpus.

Built on rank_bm25.BM25Okapi. The retriever loads every chunk from Milvus on
first use (and on TTL expiry) and caches the tokenized index in memory.

Tokenization is bilingual (English + Urdu/Arabic script):
  - normalises Arabic-Indic / Persian digits → Latin digits
  - normalises Alef variants (إأآا → ا)
  - normalises Yeh variants (ي → ی) and Kaf variants (ك → ک)
  - removes a small set of bilingual stop words
  - lowercases Latin tokens

Used as one half of a vector + keyword hybrid retriever:
   fusion_score = 0.6 * vector_norm + 0.4 * bm25_norm
"""
from __future__ import annotations

import re
import threading
import time
from typing import Optional

from rank_bm25 import BM25Okapi
from pymilvus import Collection

from services.vector_service import COLLECTION_NAME

# ─── TOKENIZER ────────────────────────────────────────────────────────────────

# Arabic-Indic + Persian digits → Latin
_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ALEF_RE = re.compile(r"[إأآا]")
_YEH_RE  = re.compile(r"[يی]")
_KAF_RE  = re.compile(r"ك")
_TAA_RE  = re.compile(r"ة")

_ENGLISH_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "at",
    "by", "for", "with", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "should", "can",
    "could", "may", "might", "must", "this", "that", "these", "those", "i",
    "you", "he", "she", "it", "we", "they", "them", "his", "her", "their",
    "what", "which", "who", "whom", "how", "when", "where", "why", "as", "from",
    "up", "out", "into", "onto", "than", "then", "so", "about", "any", "some",
    "no", "not", "all", "each", "such", "very", "more", "most", "other", "own",
}

_URDU_STOPWORDS = {
    "کا", "کی", "کے", "کو", "میں", "سے", "پر", "اور", "یا", "ہے", "ہیں",
    "تھا", "تھی", "تھے", "نہیں", "یہ", "وہ", "کیا", "کیسے", "کب", "کیوں",
    "ایک", "بھی", "ہی", "تو", "نے", "ہو", "ہوں", "ہوتا", "ہوتی", "ہوگا",
    "اگر", "جو", "جب", "جہاں", "جیسا", "جیسے", "اب", "تک", "کوئی", "کچھ",
    "میرا", "میری", "میرے", "ہمارا", "ہماری", "ہمارے", "آپ", "تم",
}

_STOPWORDS = _ENGLISH_STOPWORDS | _URDU_STOPWORDS

# Captures Latin words, Arabic-script words (incl. Urdu), digits.
_TOKEN_RE = re.compile(r"[\w؀-ۿݐ-ݿࢠ-ࣿ]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Bilingual tokenizer for English + Urdu/Arabic curriculum text."""
    if not text:
        return []
    text = text.translate(_DIGIT_MAP)
    text = _ALEF_RE.sub("ا", text)
    text = _YEH_RE.sub("ی", text)
    text = _KAF_RE.sub("ک", text)
    text = _TAA_RE.sub("ہ", text)
    text = text.lower()
    tokens = _TOKEN_RE.findall(text)
    return [t for t in tokens if len(t) > 1 and t not in _STOPWORDS]


# ─── BM25 RETRIEVER ──────────────────────────────────────────────────────────

class BM25Retriever:
    """In-memory BM25 retriever over the entire document_chunks collection.

    The index is rebuilt lazily on first search and again whenever the cached
    index is older than RELOAD_TTL_SECS. This means newly-ingested documents
    appear in BM25 results within a few minutes without an explicit signal
    between Celery workers and the FastAPI process.
    """

    RELOAD_TTL_SECS = 300  # 5 minutes

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded_at: float = 0.0
        self._bm25: Optional[BM25Okapi] = None
        self._meta: list[dict] = []  # parallel to BM25 doc list

    def _stale(self) -> bool:
        return (time.time() - self._loaded_at) > self.RELOAD_TTL_SECS

    def _load(self, force: bool = False) -> None:
        with self._lock:
            if not force and self._bm25 is not None and not self._stale():
                return
            try:
                col = Collection(COLLECTION_NAME)
                col.load()

                fields = [
                    "chunk_id", "document_id", "chunk_index",
                    "document_title", "subject", "class_level",
                    "document_type", "language", "academic_year", "term",
                    "chapter_number", "chapter_title", "page_number",
                    "chunk_text",
                ]

                # Use query_iterator for efficient scan across the whole collection
                meta: list[dict] = []
                tokenised: list[list[str]] = []
                itr = col.query_iterator(
                    batch_size=2000,
                    output_fields=fields,
                    expr="chunk_index >= 0",
                )
                while True:
                    batch = itr.next()
                    if not batch:
                        itr.close()
                        break
                    for r in batch:
                        meta.append(r)
                        tokenised.append(tokenize(r.get("chunk_text", "")))

                if tokenised:
                    self._bm25 = BM25Okapi(tokenised)
                    self._meta = meta
                    print(f"[BM25] Index built: {len(tokenised)} documents")
                else:
                    self._bm25 = None
                    self._meta = []
                    print("[BM25] No documents to index")
                self._loaded_at = time.time()
            except Exception as exc:
                print(f"[BM25] Load failed: {exc}")
                # Backoff briefly so we don't hammer Milvus on every search
                self._loaded_at = time.time() - (self.RELOAD_TTL_SECS - 30)

    def reload(self) -> None:
        """Force a rebuild on next search."""
        with self._lock:
            self._loaded_at = 0.0
            self._bm25 = None
            self._meta = []

    def search(
        self,
        query: str,
        limit: int = 60,
        subject: Optional[str] = None,
        class_level: Optional[str] = None,
        document_type: Optional[str] = None,
        language: Optional[str] = None,
        academic_year: Optional[str] = None,
        term: Optional[str] = None,
        document_title: Optional[str] = None,
    ) -> list[dict]:
        self._load()
        if not self._bm25 or not self._meta:
            return []

        tokens = tokenize(query)
        if not tokens:
            return []

        scores = self._bm25.get_scores(tokens)
        if scores.max() <= 0:
            return []

        # Apply scalar filters by zeroing out non-matching docs
        for i, m in enumerate(self._meta):
            if subject and m.get("subject") != subject:
                scores[i] = 0
                continue
            if class_level and m.get("class_level") != class_level:
                scores[i] = 0
                continue
            if document_type and m.get("document_type") != document_type:
                scores[i] = 0
                continue
            if language and m.get("language") != language:
                scores[i] = 0
                continue
            if academic_year and m.get("academic_year") != academic_year:
                scores[i] = 0
                continue
            if term and m.get("term") != term:
                scores[i] = 0
                continue
            if document_title and m.get("document_title") != document_title:
                scores[i] = 0

        max_score = scores.max()
        if max_score <= 0:
            return []

        top_idx = sorted(range(len(scores)), key=lambda i: -scores[i])[:limit]

        out: list[dict] = []
        for i in top_idx:
            if scores[i] <= 0:
                break
            m = dict(self._meta[i])
            m["score"] = float(scores[i] / max_score)  # normalised to [0, 1]
            out.append(m)
        return out


_retriever: Optional[BM25Retriever] = None


def get_retriever() -> BM25Retriever:
    global _retriever
    if _retriever is None:
        _retriever = BM25Retriever()
    return _retriever
