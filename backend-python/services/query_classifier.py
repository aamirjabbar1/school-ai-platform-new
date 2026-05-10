"""
Query classifier + dynamic document index for the school knowledge base.

Classifies a query into one of:
  - point        — specific factual question (definition, formula, single Q)
  - conceptual   — broad topic with multiple angles ("explain", "how does")
  - exhaustive   — enumerate ALL instances ("list all formulas in Chapter 5")
  - filtered     — topic question scoped to a specific named document

For conceptual/filtered queries it also generates 3-5 sub-queries used by
the multi-query expansion stage in document_service.search_knowledge_base.

Detection of document titles, subjects, and classes uses an in-memory
cache built from Milvus's distinct values (rebuilt every TTL seconds).
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Optional

import anthropic


# ─── Regex fast-paths ────────────────────────────────────────────────────────

_POINT_PATTERNS = [
    re.compile(r"\bquestion\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bq\.?\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bexercise\s*\d+(?:\.\d+)?\b", re.IGNORECASE),
    re.compile(r"\bdefine\b", re.IGNORECASE),
    re.compile(r"\bformula\s+(?:for|of)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+is\s+the\s+(?:formula|definition|meaning|value)\b", re.IGNORECASE),
    re.compile(r"\bsolve\s+(?:for|the)\b", re.IGNORECASE),
]

_EXHAUSTIVE_PATTERNS = [
    re.compile(r"\blist\s+(?:all|every)\b", re.IGNORECASE),
    re.compile(r"\ball\s+(?:formulas|examples|definitions|exercises|theorems|laws|rules)\b", re.IGNORECASE),
    re.compile(r"\bevery\s+\w+\b", re.IGNORECASE),
    re.compile(r"\benumerate\b", re.IGNORECASE),
    re.compile(r"\bthroughout\s+the\b", re.IGNORECASE),
    re.compile(r"\bgive\s+me\s+all\b", re.IGNORECASE),
    # Urdu equivalents
    re.compile(r"تمام|سارے|ہر\s+ایک"),
]


# ─── Dynamic document index ───────────────────────────────────────────────────

_INDEX_LOCK = threading.Lock()
_INDEX: Optional[dict] = None
_INDEX_LOADED_AT: float = 0.0
_INDEX_TTL_SECS = 300  # 5 minutes


def _load_index(force: bool = False) -> dict:
    global _INDEX, _INDEX_LOADED_AT
    with _INDEX_LOCK:
        if (
            not force
            and _INDEX is not None
            and (time.time() - _INDEX_LOADED_AT) < _INDEX_TTL_SECS
        ):
            return _INDEX

        try:
            from pymilvus import Collection
            from services.vector_service import COLLECTION_NAME
            col = Collection(COLLECTION_NAME)
            col.load()
            results = col.query(
                expr="chunk_index >= 0",
                output_fields=["document_title", "subject", "class_level", "chapter_title"],
                limit=16384,
                consistency_level="Eventually",
            )
            titles: set[str] = set()
            subjects: set[str] = set()
            classes: set[str] = set()
            chapters: set[str] = set()
            for r in results:
                if t := r.get("document_title"):
                    titles.add(t)
                if s := r.get("subject"):
                    subjects.add(s)
                if cl := r.get("class_level"):
                    classes.add(cl)
                if ct := r.get("chapter_title"):
                    chapters.add(ct)
            _INDEX = {
                "titles":   sorted(titles, key=len, reverse=True),
                "subjects": sorted(subjects, key=len, reverse=True),
                "classes":  sorted(classes, key=len, reverse=True),
                "chapters": sorted(chapters, key=len, reverse=True),
            }
            _INDEX_LOADED_AT = time.time()
            print(
                f"[QueryClassifier] Index loaded: "
                f"{len(titles)} titles, {len(subjects)} subjects, "
                f"{len(classes)} classes, {len(chapters)} chapters"
            )
        except Exception as exc:
            print(f"[QueryClassifier] Could not load doc index: {exc}")
            _INDEX = {"titles": [], "subjects": [], "classes": [], "chapters": []}
            # Backoff so we don't hammer Milvus on every query
            _INDEX_LOADED_AT = time.time() - (_INDEX_TTL_SECS - 30)

        return _INDEX


def reload_document_index() -> None:
    global _INDEX, _INDEX_LOADED_AT
    with _INDEX_LOCK:
        _INDEX = None
        _INDEX_LOADED_AT = 0.0


def _find_substring(query_lower: str, candidates: list[str]) -> Optional[str]:
    """Longest-first substring match (case-insensitive)."""
    for cand in candidates:
        if cand and cand.lower() in query_lower:
            return cand
    return None


def _regex_classify(query: str) -> Optional[str]:
    if any(p.search(query) for p in _EXHAUSTIVE_PATTERNS):
        return "exhaustive"
    if any(p.search(query) for p in _POINT_PATTERNS):
        return "point"
    return None


# ─── LLM classification ──────────────────────────────────────────────────────

_LLM_CLIENT: Optional[anthropic.AsyncAnthropic] = None
_HAIKU_MODEL = "claude-haiku-4-5-20251001"


def _llm() -> anthropic.AsyncAnthropic:
    global _LLM_CLIENT
    if _LLM_CLIENT is None:
        _LLM_CLIENT = anthropic.AsyncAnthropic(max_retries=2)
    return _LLM_CLIENT


async def _llm_classify(
    query: str,
    detected_title: Optional[str],
    detected_subject: Optional[str],
) -> Optional[dict]:
    """Returns {"type", "sub_queries", "reason"} or None on failure."""
    prompt = (
        "You are a query classifier for a school knowledge base of textbooks, "
        "notes, exam papers, and worksheets. Classify the query and return ONE "
        "JSON object only.\n\n"
        "Categories:\n"
        '- "point": specific factual question with a precise short answer '
        "(definition, single formula, single exercise, single fact)\n"
        '- "conceptual": broad topic that benefits from multiple angles '
        "(explanation, comparison, 'how does X work', 'why does Y happen')\n"
        '- "exhaustive": user wants ALL instances enumerated '
        "(all formulas in a chapter, every experiment, every law)\n"
        '- "filtered": topic question scoped to a specific book/chapter the user named\n\n'
        "For conceptual/filtered, also generate 3-5 short sub-queries (5-10 words each) "
        "that explore different facets. Sub-queries must be standalone search queries.\n\n"
        "Respond with ONLY this JSON, no prose, no fences:\n"
        "{\n"
        '  "type": "point|conceptual|exhaustive|filtered",\n'
        '  "sub_queries": ["...", "..."],\n'
        '  "reason": "one short sentence"\n'
        "}\n\n"
        f"Query: {query}\n"
        f"Detected document: {detected_title or '(none)'}\n"
        f"Detected subject: {detected_subject or '(none)'}\n"
    )
    try:
        response = await _llm().messages.create(
            model=_HAIKU_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Strip code fences if Haiku adds them
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
        data = json.loads(text)
        return {
            "type":        data.get("type", "conceptual"),
            "sub_queries": [s for s in (data.get("sub_queries") or []) if isinstance(s, str)][:5],
            "reason":      data.get("reason", "llm classification"),
        }
    except Exception as exc:
        print(f"[QueryClassifier] LLM call failed: {exc}")
        return None


# ─── Public entry point ──────────────────────────────────────────────────────

async def classify_query(
    query: str,
    subject_hint: Optional[str] = None,
    class_hint: Optional[str] = None,
) -> dict:
    """Classify a query and detect filterable metadata.

    Returns:
      {
        "type":           "point" | "conceptual" | "exhaustive" | "filtered",
        "document_title": str | None,
        "subject":        str | None,
        "class_level":    str | None,
        "chapter_title":  str | None,
        "sub_queries":    list[str],
        "reason":         str,
      }
    """
    index = _load_index()
    q_lower = query.lower()

    detected_title    = _find_substring(q_lower, index["titles"])
    detected_subject  = _find_substring(q_lower, index["subjects"]) or subject_hint
    detected_class    = _find_substring(q_lower, index["classes"]) or class_hint
    detected_chapter  = _find_substring(q_lower, index["chapters"])

    fast = _regex_classify(query)

    # Fast-paths that skip the LLM
    if fast == "exhaustive":
        return {
            "type":           "exhaustive",
            "document_title": detected_title,
            "subject":        detected_subject,
            "class_level":    detected_class,
            "chapter_title":  detected_chapter,
            "sub_queries":    [],
            "reason":         "matched exhaustive keyword",
        }
    if fast == "point" and not detected_title:
        return {
            "type":           "point",
            "document_title": None,
            "subject":        detected_subject,
            "class_level":    detected_class,
            "chapter_title":  detected_chapter,
            "sub_queries":    [],
            "reason":         "matched point pattern",
        }

    # LLM classification
    llm_result = await _llm_classify(query, detected_title, detected_subject)

    if llm_result is None:
        # Regex/heuristic fallback when the LLM call fails
        fallback_type = fast or ("filtered" if detected_title else "conceptual")
        return {
            "type":           fallback_type,
            "document_title": detected_title,
            "subject":        detected_subject,
            "class_level":    detected_class,
            "chapter_title":  detected_chapter,
            "sub_queries":    [],
            "reason":         "regex/fallback (LLM failed)",
        }

    qtype = llm_result["type"]
    # If the user named a document but the LLM said "conceptual", upgrade to "filtered"
    if qtype == "conceptual" and detected_title:
        qtype = "filtered"

    return {
        "type":           qtype,
        "document_title": detected_title,
        "subject":        detected_subject,
        "class_level":    detected_class,
        "chapter_title":  detected_chapter,
        "sub_queries":    llm_result["sub_queries"],
        "reason":         llm_result["reason"],
    }
