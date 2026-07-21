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
from reportlab.lib.pagesizes import A4, landscape
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


# ─── LESSON PLAN PDF ──────────────────────────────────────────────────────────

# Order matters: each is rendered as a labelled fragment inside the relevant
# table cell, so a plan with sparse fields still reads cleanly.
_PLAN_CELL_GROUPS = [
    ("Topic", [("chapter", "Chapter"), ("topic", "Topic"), ("subtopic", "Subtopic")]),
    ("Objectives & Outcomes", [("objectives", "Objectives"), ("outcomes", "Outcomes"), ("prior_knowledge", "Prior knowledge")]),
    ("Methodology & Activities", [("methodology", "Method"), ("teacher_activities", "Teacher"), ("student_activities", "Students"), ("group_activity", "Activity"), ("hots", "HOTS")]),
    ("Resources & Examples", [("resources", "Resources"), ("real_life_examples", "Real-life"), ("differentiation", "Differentiation")]),
    ("Homework & Assessment", [("classwork", "Classwork"), ("homework", "Homework"), ("assessment", "Assessment"), ("remarks", "Remarks")]),
]


def _plan_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title":   ParagraphStyle("lp_title",   parent=base["Title"],   fontSize=17, spaceAfter=4),
        "sub":     ParagraphStyle("lp_sub",     parent=base["Normal"],  fontSize=10, textColor=colors.grey, alignment=1, spaceAfter=10),
        "overview":ParagraphStyle("lp_over",    parent=base["Normal"],  fontSize=9.5, textColor=colors.HexColor("#374151"), backColor=colors.HexColor("#f3f4f6"), borderPadding=8, spaceAfter=12, leading=13),
        "th":      ParagraphStyle("lp_th",      parent=base["Normal"],  fontSize=8.5, textColor=colors.white, fontName="Helvetica-Bold", leading=11),
        "wk":      ParagraphStyle("lp_wk",      parent=base["Normal"],  fontSize=8.5, fontName="Helvetica-Bold", leading=11),
        "cell":    ParagraphStyle("lp_cell",    parent=base["Normal"],  fontSize=7.5, leading=10),
        "sumhead": ParagraphStyle("lp_sumhead", parent=base["Heading2"],fontSize=13, spaceBefore=16, spaceAfter=8, textColor=colors.HexColor("#1e3a8a")),
        "sumcell": ParagraphStyle("lp_sumcell", parent=base["Normal"],  fontSize=9.5, leading=13),
    }


def _cell_para(lesson: dict, fields: list[tuple[str, str]], styles: dict) -> Paragraph:
    """Compose a multi-field plan cell as a single Paragraph with bold labels."""
    parts = []
    for key, label in fields:
        val = lesson.get(key)
        if val:
            parts.append(f"<b>{_esc(label)}:</b> {_esc(val)}")
    return Paragraph("<br/>".join(parts) if parts else "&nbsp;", styles["cell"])


def _plan_meta_line(plan: dict) -> str:
    bits = [plan.get("subject"), plan.get("class_name")]
    if plan.get("section"):
        bits.append(f"Section {plan['section']}")
    if plan.get("board"):
        bits.append(plan["board"])
    ptype = (plan.get("plan_type") or "").replace("_", " ").title()
    if ptype:
        bits.append(f"{ptype} Plan")
    return " &nbsp;•&nbsp; ".join(_esc(b) for b in bits if b)


def build_lesson_plan_pdf(plan: dict) -> bytes:
    """Render a lesson plan as a printable A4 PDF.

    New plans use the 17-section LSS document format; older saved plans that only
    carry a `lessons[]` schedule fall back to the legacy landscape grid.
    """
    plan_data = plan.get("plan_data") or {}
    if _is_lss_plan(plan_data):
        return _build_lss_plan_pdf(plan, plan_data)
    return _build_legacy_plan_pdf(plan, plan_data)


def _is_lss_plan(plan_data: dict) -> bool:
    return any(plan_data.get(k) for k in ("learning_outcomes", "teaching_methodology", "weekly_plan"))


# ─── LSS 17-section document (portrait A4) ────────────────────────────────────

_LSS_COVER_LABELS = [
    ("subject", "Subject"), ("class_name", "Class"), ("book_name", "Book Name"),
    ("edition", "Edition"), ("academic_session", "Academic Session"), ("term", "Term"),
    ("unit_number", "Unit Number"), ("unit_title", "Unit Title"), ("chapter_topic", "Chapter / Topic"),
]


def _lss_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title":  ParagraphStyle("lss_title",  parent=base["Title"],    fontSize=18, spaceAfter=2, textColor=colors.HexColor("#0f172a")),
        "sub":    ParagraphStyle("lss_sub",     parent=base["Normal"],   fontSize=10, alignment=1, textColor=colors.grey, spaceAfter=10),
        "sec":    ParagraphStyle("lss_sec",     parent=base["Heading2"], fontSize=13, spaceBefore=14, spaceAfter=6, textColor=colors.white,
                                 backColor=colors.HexColor("#1e3a8a"), borderPadding=(5, 6, 5, 6), leading=17),
        "sub2":   ParagraphStyle("lss_sub2",    parent=base["Normal"],   fontSize=10.5, fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=3, textColor=colors.HexColor("#1e3a8a")),
        "body":   ParagraphStyle("lss_body",    parent=base["Normal"],   fontSize=10, leading=15, spaceAfter=5),
        "bullet": ParagraphStyle("lss_bullet",  parent=base["Normal"],   fontSize=10, leading=14, leftIndent=16, bulletIndent=4, spaceAfter=2),
        "cell":   ParagraphStyle("lss_cell",    parent=base["Normal"],   fontSize=9.5, leading=13),
        "cellb":  ParagraphStyle("lss_cellb",   parent=base["Normal"],   fontSize=9.5, leading=13, fontName="Helvetica-Bold"),
        "th":     ParagraphStyle("lss_th",      parent=base["Normal"],   fontSize=9.5, leading=13, fontName="Helvetica-Bold", textColor=colors.white),
    }


def _lss_heading(story: list, styles: dict, n: int, text: str) -> None:
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"{n}. {_esc(text)}", styles["sec"]))


def _lss_paragraphs(story: list, styles: dict, text: Any) -> None:
    """Render a possibly multi-paragraph string; blank lines split paragraphs."""
    if not text:
        return
    for para in str(text).split("\n"):
        para = para.strip()
        if para:
            story.append(Paragraph(_esc(para), styles["body"]))


def _lss_bullets(story: list, styles: dict, items: list, *, numbered: bool = False) -> None:
    for i, item in enumerate(items or [], start=1):
        if item in (None, ""):
            continue
        marker = f"{i}." if numbered else "&bull;"
        story.append(Paragraph(f"{marker}&nbsp;&nbsp;{_esc(item)}", styles["bullet"]))


def _lss_table(story: list, styles: dict, headers: list, rows: list, col_widths: list) -> None:
    data = [[Paragraph(_esc(h), styles["th"]) for h in headers]]
    for row in rows:
        data.append([Paragraph(_esc(c), styles["cell"]) for c in row])
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(tbl)


def _build_lss_plan_pdf(plan: dict, plan_data: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, title=plan.get("title", "Lesson Plan"),
        leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.6 * cm,
    )
    styles = _lss_styles()
    W = A4[0] - 3.6 * cm  # usable width
    story: list = []

    story.append(Paragraph(_esc(plan_data.get("title") or plan.get("title", "Lesson Plan")), styles["title"]))
    story.append(Paragraph(_plan_meta_line(plan), styles["sub"]))

    # 1. Cover Page
    cover = plan_data.get("cover") or {}
    cover_rows = [[Paragraph(f"<b>{_esc(label)}</b>", styles["cellb"]), Paragraph(_esc(cover.get(key, "")), styles["cell"])]
                  for key, label in _LSS_COVER_LABELS if cover.get(key)]
    if cover_rows:
        _lss_heading(story, styles, 1, "Cover Page")
        t = Table(cover_rows, colWidths=[5 * cm, W - 5 * cm])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t)

    # 2. Students Learning Outcomes
    outcomes = plan_data.get("learning_outcomes") or []
    if outcomes:
        _lss_heading(story, styles, 2, "Students Learning Outcomes")
        story.append(Paragraph("<b>Students will be able to:</b>", styles["body"]))
        _lss_bullets(story, styles, outcomes, numbered=True)

    # 3. Starter Activity
    if plan_data.get("starter_activity"):
        _lss_heading(story, styles, 3, "Starter Activity")
        _lss_paragraphs(story, styles, plan_data["starter_activity"])

    # 4. Brainstorming Questions
    if plan_data.get("brainstorming_questions"):
        _lss_heading(story, styles, 4, "Brainstorming Questions")
        _lss_bullets(story, styles, plan_data["brainstorming_questions"])

    # 5. Teaching Methodology
    methodology = plan_data.get("teaching_methodology") or []
    if methodology:
        _lss_heading(story, styles, 5, "Teaching Methodology")
        for stage in methodology:
            if isinstance(stage, dict):
                if stage.get("heading"):
                    story.append(Paragraph(_esc(stage["heading"]), styles["sub2"]))
                _lss_paragraphs(story, styles, stage.get("detail"))
            else:
                _lss_paragraphs(story, styles, stage)

    # 6. Guided Practice
    if plan_data.get("guided_practice"):
        _lss_heading(story, styles, 6, "Guided Practice")
        _lss_paragraphs(story, styles, plan_data["guided_practice"])

    # 7. Independent Practice
    if plan_data.get("independent_practice"):
        _lss_heading(story, styles, 7, "Independent Practice")
        _lss_paragraphs(story, styles, plan_data["independent_practice"])

    # 8. Wrap-up
    wrap = plan_data.get("wrap_up") or {}
    if wrap:
        _lss_heading(story, styles, 8, "Wrap-up")
        if wrap.get("revision_questions"):
            story.append(Paragraph("Revision Questions", styles["sub2"]))
            _lss_bullets(story, styles, wrap["revision_questions"])
        if wrap.get("oral_recap"):
            story.append(Paragraph("Oral Recap", styles["sub2"]))
            _lss_paragraphs(story, styles, wrap["oral_recap"])
        if wrap.get("quick_review"):
            story.append(Paragraph("Quick Classroom Review", styles["sub2"]))
            _lss_paragraphs(story, styles, wrap["quick_review"])

    # 9. Resources Required
    if plan_data.get("resources"):
        _lss_heading(story, styles, 9, "Resources Required")
        _lss_bullets(story, styles, plan_data["resources"])

    # 10. Assessment
    if plan_data.get("assessment"):
        _lss_heading(story, styles, 10, "Assessment")
        _lss_bullets(story, styles, plan_data["assessment"])

    # 11. Week-wise Planning
    weekly = plan_data.get("weekly_plan") or []
    if weekly:
        _lss_heading(story, styles, 11, "Week-wise Planning")
        rows = [[d.get("day", ""), d.get("classwork", ""), d.get("homework", "")] for d in weekly]
        _lss_table(story, styles, ["Day", "Classwork", "Homework"],
                   rows, [3 * cm, (W - 3 * cm) * 0.55, (W - 3 * cm) * 0.45])

    # 12. Vocabulary
    vocab = plan_data.get("vocabulary") or []
    if vocab:
        _lss_heading(story, styles, 12, "Vocabulary")
        rows = [[v.get("word", ""), v.get("meaning", "")] for v in vocab]
        _lss_table(story, styles, ["Word", "Meaning"], rows, [5 * cm, W - 5 * cm])

    # 13. Question / Answers
    qa = plan_data.get("qa") or []
    if qa:
        _lss_heading(story, styles, 13, "Question / Answers")
        for i, item in enumerate(qa, start=1):
            story.append(Paragraph(f"<b>Q{i}. {_esc(item.get('question', ''))}</b>", styles["body"]))
            story.append(Paragraph(f"<b>Ans.</b> {_esc(item.get('answer', ''))}", styles["body"]))

    # 14. Worksheets
    worksheets = plan_data.get("worksheets") or []
    if worksheets:
        _lss_heading(story, styles, 14, "Worksheets")
        for ws in worksheets:
            if isinstance(ws, dict):
                if ws.get("type"):
                    story.append(Paragraph(_esc(ws["type"]), styles["sub2"]))
                _lss_bullets(story, styles, ws.get("items") or [])
            else:
                _lss_bullets(story, styles, [ws])

    # 15. Differentiated Instruction
    diff = plan_data.get("differentiation") or {}
    if diff:
        _lss_heading(story, styles, 15, "Differentiated Instruction")
        for key, label in (("slow_learners", "Slow Learners"), ("average_learners", "Average Learners"), ("high_achievers", "High Achievers")):
            if diff.get(key):
                story.append(Paragraph(label, styles["sub2"]))
                _lss_paragraphs(story, styles, diff[key])

    # 16. Cross-Curricular Links
    cross = plan_data.get("cross_curricular") or []
    if cross:
        _lss_heading(story, styles, 16, "Cross-Curricular Links")
        rows = [[c.get("subject", ""), c.get("connection", "")] for c in cross if isinstance(c, dict)]
        if rows:
            _lss_table(story, styles, ["Subject", "Connection"], rows, [4.5 * cm, W - 4.5 * cm])

    # 17. Values & Life Skills
    if plan_data.get("values"):
        _lss_heading(story, styles, 17, "Values & Life Skills")
        _lss_bullets(story, styles, plan_data["values"])

    doc.build(story)
    return buf.getvalue()


# ─── Legacy schedule grid (landscape A4) ──────────────────────────────────────

def _build_legacy_plan_pdf(plan: dict, plan_data: dict) -> bytes:
    """Render an older lesson plan (schedule grid + summary) in landscape A4."""
    lessons = plan_data.get("lessons") or []
    summary = plan_data.get("summary") or {}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        title=plan.get("title", "Lesson Plan"),
        leftMargin=1.2 * cm, rightMargin=1.2 * cm,
        topMargin=1.2 * cm, bottomMargin=1.2 * cm,
    )
    styles = _plan_styles()
    story: list = []

    story.append(Paragraph(_esc(plan.get("title", "Lesson Plan")), styles["title"]))
    meta = _plan_meta_line(plan)
    if plan.get("academic_session"):
        meta += f" &nbsp;•&nbsp; Session {_esc(plan['academic_session'])}"
    story.append(Paragraph(meta, styles["sub"]))

    overview = plan_data.get("overview")
    if overview:
        story.append(Paragraph(_esc(overview), styles["overview"]))

    # ── Schedule table ─────────────────────────────────────────────────────
    headers = ["Wk / Date"] + [g[0] for g in _PLAN_CELL_GROUPS]
    header_row = [Paragraph(_esc(h), styles["th"]) for h in headers]
    table_data = [header_row]

    for ls in lessons:
        wk_bits = []
        if ls.get("week") is not None:
            wk_bits.append(f"<b>Week {_esc(ls.get('week'))}</b>")
        for key in ("dates", "day", "period"):
            if ls.get(key):
                wk_bits.append(_esc(ls.get(key)))
        wk_cell = Paragraph("<br/>".join(wk_bits) if wk_bits else "&nbsp;", styles["wk"])
        row = [wk_cell] + [_cell_para(ls, g[1], styles) for g in _PLAN_CELL_GROUPS]
        table_data.append(row)

    col_widths = [2.4 * cm, 4.6 * cm, 4.8 * cm, 6.2 * cm, 4.4 * cm, 4.4 * cm]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)

    # ── Summary ────────────────────────────────────────────────────────────
    if summary:
        story.append(Paragraph("Plan Summary", styles["sumhead"]))
        labels = [
            ("academic_session", "Academic Session"), ("subject", "Subject"),
            ("grade", "Grade"), ("board", "Board"),
            ("total_chapters", "Total Chapters"), ("total_weeks", "Total Teaching Weeks"),
            ("total_teaching_days", "Total Teaching Days"), ("total_lessons", "Total Lessons"),
            ("total_practical_lessons", "Total Practical Lessons"),
            ("total_assessments", "Total Assessments"), ("total_homework", "Total Homework"),
            ("revision_schedule", "Revision Schedule"),
            ("exam_prep_schedule", "Exam Preparation Schedule"),
            ("expected_completion_date", "Expected Completion Date"),
        ]
        rows = []
        for key, label in labels:
            val = summary.get(key)
            if val in (None, ""):
                continue
            rows.append([
                Paragraph(f"<b>{_esc(label)}</b>", styles["sumcell"]),
                Paragraph(_esc(val), styles["sumcell"]),
            ])
        if rows:
            sum_tbl = Table(rows, colWidths=[6 * cm, 19.6 * cm])
            sum_tbl.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(sum_tbl)

    doc.build(story)
    return buf.getvalue()
