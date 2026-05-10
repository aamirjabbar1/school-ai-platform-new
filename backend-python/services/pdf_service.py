"""
Render a QuestionPaper into a printable PDF using reportlab.

Two flavours:
  build_question_paper_pdf(paper, include_answers=False)
    → bytes containing a multi-page A4 PDF with the question paper

The student-side download passes include_answers=False; the teacher download
includes a final "Answer Key" page when answers are present.
"""
from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    PageBreak,
    Table,
    TableStyle,
    KeepTogether,
)


def _styles() -> dict:
    base = getSampleStyleSheet()
    styles = {
        "title":       ParagraphStyle("title",       parent=base["Title"],   fontSize=18, spaceAfter=4),
        "subtitle":    ParagraphStyle("subtitle",    parent=base["Normal"],  fontSize=10, textColor=colors.grey, alignment=1, spaceAfter=12),
        "section":     ParagraphStyle("section",     parent=base["Heading2"], fontSize=13, spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#1e3a8a")),
        "instr":       ParagraphStyle("instr",       parent=base["Normal"],  fontSize=10, textColor=colors.HexColor("#374151"), backColor=colors.HexColor("#f3f4f6"), borderPadding=8, leftIndent=4, rightIndent=4, spaceAfter=12),
        "question":    ParagraphStyle("question",    parent=base["Normal"],  fontSize=11, leftIndent=4, spaceAfter=4, leading=15),
        "qmeta":       ParagraphStyle("qmeta",       parent=base["Normal"],  fontSize=9,  textColor=colors.grey, leftIndent=4, spaceAfter=8),
        "option":      ParagraphStyle("option",      parent=base["Normal"],  fontSize=10, leftIndent=24, spaceAfter=2, leading=14),
        "answer_head": ParagraphStyle("answer_head", parent=base["Heading2"], fontSize=14, spaceBefore=18, spaceAfter=8, textColor=colors.HexColor("#065f46")),
        "answer":      ParagraphStyle("answer",      parent=base["Normal"],  fontSize=10, leftIndent=4, spaceAfter=6, leading=14),
    }
    return styles


def _esc(text: Any) -> str:
    """Escape text for reportlab Paragraph (XML-like)."""
    if text is None:
        return ""
    s = str(text)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _group_questions_by_section(questions: list[dict]) -> list[tuple[str, list[dict]]]:
    """Preserve order while grouping by `section` field."""
    sections: list[tuple[str, list[dict]]] = []
    by_name: dict[str, list[dict]] = {}
    for q in questions:
        name = q.get("section") or "Questions"
        if name not in by_name:
            by_name[name] = []
            sections.append((name, by_name[name]))
        by_name[name].append(q)
    return sections


def build_question_paper_pdf(paper: dict, include_answers: bool = False) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        title=paper.get("title", "Question Paper"),
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
    )
    styles = _styles()
    story: list = []

    # ── Header table: title + meta block ───────────────────────────────────
    title = _esc(paper.get("title", "Question Paper"))
    story.append(Paragraph(title, styles["title"]))

    paper_type = (paper.get("paper_type") or "").replace("_", " ").title()
    meta = f"{_esc(paper.get('subject', ''))} &nbsp;•&nbsp; {_esc(paper.get('class_name', ''))} &nbsp;•&nbsp; {_esc(paper_type)}"
    story.append(Paragraph(meta, styles["subtitle"]))

    info_data = [
        ["Total Marks", str(paper.get("total_marks", "—")),
         "Duration", f'{paper.get("duration_minutes", "—")} min'],
        ["Date", "____________________", "Name", "____________________"],
    ]
    info_tbl = Table(info_data, colWidths=[3 * cm, 4 * cm, 3 * cm, 5 * cm])
    info_tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#374151")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#374151")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, colors.HexColor("#e5e7eb")),
    ]))
    story.append(info_tbl)
    story.append(Spacer(1, 12))

    # ── Instructions ───────────────────────────────────────────────────────
    instructions = paper.get("instructions")
    if instructions:
        story.append(Paragraph(f"<b>Instructions:</b> {_esc(instructions)}", styles["instr"]))

    # ── Questions, grouped by section ──────────────────────────────────────
    questions = paper.get("questions") or []
    sections = _group_questions_by_section(questions)

    for section_name, qs in sections:
        story.append(Paragraph(_esc(section_name), styles["section"]))
        for q in qs:
            number = q.get("number", "")
            text = _esc(q.get("question", ""))
            marks = q.get("marks")
            difficulty = q.get("difficulty")

            block: list = []
            block.append(Paragraph(f"<b>Q{number}.</b> {text}", styles["question"]))

            options = q.get("options") or []
            for opt in options:
                block.append(Paragraph(_esc(opt), styles["option"]))

            meta_parts = []
            if marks is not None:
                meta_parts.append(f"{marks} mark{'s' if marks != 1 else ''}")
            if difficulty:
                meta_parts.append(difficulty)
            if meta_parts:
                block.append(Paragraph(" • ".join(meta_parts), styles["qmeta"]))

            block.append(Spacer(1, 4))
            # Keep each question (with its options) on the same page when possible
            story.append(KeepTogether(block))

    # ── Answer Key (teachers only) ─────────────────────────────────────────
    answer_key = paper.get("answer_key") or []
    if include_answers and answer_key:
        story.append(PageBreak())
        story.append(Paragraph("Answer Key", styles["answer_head"]))
        for ans in answer_key:
            num = ans.get("number", "")
            correct = _esc(ans.get("correct_answer", ""))
            marks = ans.get("marks")
            suffix = f" ({marks} mark{'s' if marks != 1 else ''})" if marks else ""
            story.append(Paragraph(f"<b>Q{num}.</b> {correct}{suffix}", styles["answer"]))

    doc.build(story)
    return buf.getvalue()
