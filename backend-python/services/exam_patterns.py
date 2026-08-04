"""
Examination pattern rules — which board a class sits under, which uploaded
papers are authoritative, and what a generated paper is called.

Two vocabularies meet here and are deliberately kept apart:

  * `Document.paper_type`      what an *uploaded* knowledge-base paper is
                               (model_paper, past_paper, test, midterm, final, mcqs)
  * `QuestionPaper.paper_type` what a *generated* paper is
                               (monthly_test, mid_term, final_exam, model_paper, ...)

Both are exposed through this module so the retrieval layer, the prompt and the
PDF renderer all agree on titles and precedence.
"""
from __future__ import annotations

import re

# ─── Generated paper → printed examination title ──────────────────────────────
#
# The title printed at the top of the first page. `paper_type` on a generated
# paper *is* the examination type, so the renderer never has to guess.

EXAM_TITLES: dict[str, str] = {
    "monthly_test": "MONTHLY TEST",
    "mid_term":     "MID-TERM EXAMINATION",
    "midterm":      "MID-TERM EXAMINATION",
    "final_exam":   "FINAL EXAMINATION",
    "final":        "FINAL EXAMINATION",
    "model_paper":  "MODEL PAPER",
    "quiz":         "QUIZ",
    "class_test":   "CLASS TEST",
    "annual":       "ANNUAL EXAMINATION",
}


def exam_title(paper_type: str | None) -> str:
    """Printed examination title for a generated paper."""
    key = (paper_type or "").strip().lower()
    if key in EXAM_TITLES:
        return EXAM_TITLES[key]
    return (key.replace("_", " ").upper() or "EXAMINATION PAPER")


# ─── Uploaded paper precedence ────────────────────────────────────────────────
#
# Lower number = consulted first. A model paper defines the current official
# pattern; past papers show how that pattern has actually been examined; the
# rest are supporting evidence.

PAPER_TYPE_RANK: dict[str, int] = {
    "model_paper": 0,
    "past_paper":  1,
    "final":       2,
    "midterm":     3,
    "test":        4,
    "mcqs":        5,
}
_UNRANKED = 9

PAPER_TYPE_LABELS: dict[str, str] = {
    "model_paper": "Model Paper",
    "past_paper":  "Past Paper",
    "final":       "Final Examination Paper",
    "midterm":     "Midterm Paper",
    "test":        "Monthly / Class Test",
    "mcqs":        "MCQs Sheet",
}


# ─── Board rules ──────────────────────────────────────────────────────────────

FEDERAL_BOARD = "Federal Board"
LSS_BOARD = "Lahore School System"

# Classes 8 and above sit the Federal Board pattern; 1–7 follow the school's own
# pattern. (The written rule covers 1–10; 11–12 are board classes too, so they
# inherit the Federal Board branch.)
_FEDERAL_FROM_CLASS = 8

_CLASS_NUM_RE = re.compile(r"(\d+)")


def class_number(class_name: str | None) -> int | None:
    """Numeric grade from a class label ('Class 9 - A' → 9). None for pre-primary."""
    match = _CLASS_NUM_RE.search(class_name or "")
    return int(match.group(1)) if match else None


def board_for_class(class_name: str | None) -> str:
    """Which examination pattern governs papers for this class."""
    num = class_number(class_name)
    if num is not None and num >= _FEDERAL_FROM_CLASS:
        return FEDERAL_BOARD
    return LSS_BOARD


_FEDERAL_HINTS = ("federal", "fbise", "fbse")
_LSS_HINTS = ("lahore school", "lss")


def _board_hint(text: str) -> str | None:
    """Board a document advertises in its own title / description, if any."""
    low = (text or "").lower()
    if any(h in low for h in _FEDERAL_HINTS):
        return FEDERAL_BOARD
    if any(h in low for h in _LSS_HINTS):
        return LSS_BOARD
    return None


def pattern_sort_key(doc, preferred_board: str) -> tuple:
    """Sort key implementing the reference priority order.

    For a Federal Board class:
      1. Latest Federal Board model paper
      2. Latest Federal Board past papers
      3. Earlier Federal Board papers
      4. Lahore School System past papers
      5. Teacher-uploaded (unlabelled) papers
      6. Everything else

    For a Classes 1–7 class the school's own papers come first instead.

    `doc` is a `Document` row; newer academic years and upload dates win ties, so
    a freshly uploaded model paper automatically supersedes older patterns.
    """
    hint = _board_hint(f"{doc.title or ''} {doc.description or ''}")
    if hint is None:
        # A paper that names no board is the school's own by default: governing
        # for the LSS classes, "teacher-uploaded" (below both boards) otherwise.
        board_rank = 0 if preferred_board == LSS_BOARD else 2
    else:
        board_rank = 0 if hint == preferred_board else 1

    rank = PAPER_TYPE_RANK.get((doc.paper_type or "").strip().lower(), _UNRANKED)
    created = doc.created_at.timestamp() if doc.created_at else 0.0
    return (board_rank, rank, -_year_value(doc.academic_year), -created)


def _year_value(academic_year: str | None) -> int:
    """Leading year of an academic-year label ('2025-26' → 2025); 0 if absent."""
    match = _CLASS_NUM_RE.search(academic_year or "")
    return int(match.group(1)) if match else 0


# ─── Internal choice ──────────────────────────────────────────────────────────
#
# Board papers routinely print more questions than count: "attempt any 6 of 9".
# The marks that decide the paper total are therefore the best `attempt_count`
# questions, not every question on the page.

def attainable_marks(marks: list[int], attempt_count: int | None = None) -> int:
    """Marks a candidate can actually score from one section."""
    values = sorted((m or 0 for m in marks), reverse=True)
    if attempt_count and 0 < attempt_count < len(values):
        values = values[:attempt_count]
    return sum(values)


def choice_note(question_count: int, attempt_count: int | None) -> str:
    """Printed instruction for a section with internal choice, else ''."""
    if attempt_count and 0 < attempt_count < question_count:
        return f"Attempt any {attempt_count} of {question_count} questions."
    return ""


def paper_total_marks(questions: list[dict]) -> int:
    """Total marks of a stored paper (a flat list carrying its section fields)."""
    by_section: dict[str, list[dict]] = {}
    for q in questions or []:
        by_section.setdefault(q.get("section") or "Questions", []).append(q)
    return sum(
        attainable_marks(
            [q.get("marks") for q in group],
            next((q.get("attempt_count") for q in group if q.get("attempt_count")), None),
        )
        for group in by_section.values()
    )
