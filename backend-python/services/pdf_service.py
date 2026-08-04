"""
Render a QuestionPaper into a printable PDF using reportlab.

Two flavours:
  build_question_paper_pdf(paper, include_answers=False)
    → bytes containing a multi-page A4 PDF with the question paper

The student-side download passes include_answers=False; the teacher download
includes a final "Answer Key" page when answers are present.

Every page is laid out inside the official LSS template (see services/branding.py),
which supplies the ruled border, crest, wordmark, page numbers and copyright
notice — this module only ever produces the content that sits inside that frame.

The first page also carries the standard LSS paper head: the examination title
derived from the paper type, the candidate/marking field block, and the marks
summary grid.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    Spacer,
    PageBreak,
    Table,
    TableStyle,
    KeepTogether,
)

from services import branding
from services.exam_patterns import attainable_marks, choice_note, exam_title


def _styles() -> dict:
    base = getSampleStyleSheet()
    styles = {
        "title":       ParagraphStyle("title",       parent=base["Title"],   fontSize=18, spaceAfter=4),
        "exam":        ParagraphStyle("exam",        parent=base["Title"],   fontSize=15, spaceBefore=2, spaceAfter=2, textColor=colors.HexColor("#0f172a")),
        "subtitle":    ParagraphStyle("subtitle",    parent=base["Normal"],  fontSize=10, textColor=colors.grey, alignment=1, spaceAfter=12),
        "field":       ParagraphStyle("field",       parent=base["Normal"],  fontSize=10, leading=13),
        "fieldlabel":  ParagraphStyle("fieldlabel",  parent=base["Normal"],  fontSize=10, leading=13, fontName="Helvetica-Bold"),
        "markshead":   ParagraphStyle("markshead",   parent=base["Normal"],  fontSize=9.5, leading=12, fontName="Helvetica-Bold", alignment=1),
        "markscell":   ParagraphStyle("markscell",   parent=base["Normal"],  fontSize=9.5, leading=12, alignment=1),
        "marksrow":    ParagraphStyle("marksrow",    parent=base["Normal"],  fontSize=9.5, leading=12, fontName="Helvetica-Bold"),
        "section":     ParagraphStyle("section",     parent=base["Heading2"], fontSize=13, spaceBefore=14, spaceAfter=4, textColor=colors.HexColor("#1e3a8a")),
        "sectionnote": ParagraphStyle("sectionnote", parent=base["Normal"],  fontSize=9.5, leading=12, spaceAfter=8, textColor=colors.HexColor("#374151"), fontName="Helvetica-Oblique"),
        "instr":       ParagraphStyle("instr",       parent=base["Normal"],  fontSize=10, textColor=colors.HexColor("#374151"), backColor=colors.HexColor("#f3f4f6"), borderPadding=8, leftIndent=4, rightIndent=4, spaceAfter=12),
        "question":    ParagraphStyle("question",    parent=base["Normal"],  fontSize=11, leftIndent=4, spaceAfter=4, leading=15),
        "qmeta":       ParagraphStyle("qmeta",       parent=base["Normal"],  fontSize=9,  textColor=colors.HexColor("#374151"), alignment=2, spaceAfter=8),
        "option":      ParagraphStyle("option",      parent=base["Normal"],  fontSize=10, leftIndent=24, spaceAfter=2, leading=14),
        "answer_head": ParagraphStyle("answer_head", parent=base["Heading2"], fontSize=14, spaceBefore=18, spaceAfter=8, textColor=colors.HexColor("#065f46")),
        "sub2h":       ParagraphStyle("sub2h",       parent=base["Normal"],  fontSize=10.5, fontName="Helvetica-Bold", spaceBefore=4, spaceAfter=6, textColor=colors.HexColor("#1e3a8a")),
        "answer":      ParagraphStyle("answer",      parent=base["Normal"],  fontSize=10, leftIndent=4, spaceAfter=6, leading=14),
    }
    return branding.use_document_fonts(styles)


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


# ─── LSS paper head (candidate fields + marks summary) ────────────────────────

def _exam_date(paper: dict) -> str:
    """Printed examination date — the teacher's, or today's if none was set."""
    raw = paper.get("exam_date")
    if raw:
        try:
            value = raw if isinstance(raw, date) else datetime.fromisoformat(str(raw)).date()
            return value.strftime("%d-%m-%Y")
        except (TypeError, ValueError):
            return str(raw)
    return date.today().strftime("%d-%m-%Y")


def _paper_field_block(paper: dict, styles: dict) -> Table:
    """The candidate / marking fields printed above every LSS paper.

    Values the system already knows are filled in; the rest are ruled blanks for
    the invigilator and examiner to complete by hand.
    """
    duration = paper.get("duration_minutes")
    # (label, value) pairs laid out two to a row, in the official field order.
    fields = [
        ("Name", None),                     ("Subject", paper.get("subject")),
        ("Checked By", None),               ("C.C.", None),
        ("Class", paper.get("class_name")), ("Date", _exam_date(paper)),
        ("Section", paper.get("section")),  ("Total Marks", paper.get("total_marks")),
        ("Marks Obtained", None),           ("Time Allowed", f"{duration} min" if duration else None),
    ]

    rows: list[list] = []
    blanks: list[tuple[int, int]] = []      # (col, row) of cells needing a rule
    for i in range(0, len(fields), 2):
        row = []
        for col, (label, value) in enumerate(fields[i:i + 2]):
            filled = value not in (None, "")
            row.append(Paragraph(f"{_esc(label)}:", styles["fieldlabel"]))
            row.append(Paragraph(_esc(value) if filled else "&nbsp;", styles["field"]))
            if not filled:
                blanks.append((col * 2 + 1, len(rows)))
        rows.append(row)

    W = branding.content_width(A4)
    label_w, value_w = 3.1 * cm, W / 2 - 3.1 * cm
    table = Table(rows, colWidths=[label_w, value_w, label_w, value_w])
    style = [
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]
    style += [("LINEBELOW", (c, r), (c, r), 0.5, colors.HexColor("#111111")) for c, r in blanks]
    table.setStyle(TableStyle(style))
    return table


def _section_label(name: str, index: int) -> str:
    """Short column heading for the marks grid ('Section A: MCQs' → 'Section A')."""
    head = (name or "").split(":")[0].strip()
    if head and len(head) <= 18:
        return head
    return f"Section {chr(ord('A') + index)}"


def _section_marks(questions: list[dict]) -> int:
    """Marks a section contributes, honouring any internal choice it carries."""
    attempt = next((q.get("attempt_count") for q in questions if q.get("attempt_count")), None)
    return attainable_marks([q.get("marks") for q in questions], attempt)


def _marks_summary_table(paper: dict, sections: list[tuple[str, list[dict]]], styles: dict) -> Table:
    """Per-section marks grid: allotted on one row, obtained left blank."""
    labels = [_section_label(name, i) for i, (name, _) in enumerate(sections)] or ["Section A"]
    allotted = [_section_marks(qs) for _, qs in sections] or [0]

    total = paper.get("total_marks")
    if total in (None, ""):
        total = sum(allotted)

    header = [Paragraph("&nbsp;", styles["markshead"])]
    header += [Paragraph(_esc(l), styles["markshead"]) for l in labels]
    header.append(Paragraph("Total", styles["markshead"]))

    allotted_row = [Paragraph("Total Marks", styles["marksrow"])]
    allotted_row += [Paragraph(str(m), styles["markscell"]) for m in allotted]
    allotted_row.append(Paragraph(str(total), styles["markscell"]))

    obtained_row = [Paragraph("Marks Obtained", styles["marksrow"])]
    obtained_row += [Paragraph("&nbsp;", styles["markscell"]) for _ in labels]
    obtained_row.append(Paragraph("&nbsp;", styles["markscell"]))

    W = branding.content_width(A4)
    first_w = 3.6 * cm
    rest_w = (W - first_w) / (len(labels) + 1)
    table = Table(
        [header, allotted_row, obtained_row],
        colWidths=[first_w] + [rest_w] * (len(labels) + 1),
    )
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#111111")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _source_audit(story: list, questions: list[dict], styles: dict) -> None:
    """Grades 1-2 source trail, printed on the staff copy only.

    The caller gates this on `include_answers`, which is False for students, so
    the internal references never reach a candidate's paper.
    """
    traced = [q for q in questions if q.get("source")]
    if not traced:
        return

    from services.primary_papers import source_label

    story.append(Paragraph("Question Sources (internal — not for students)", styles["sub2h"]))
    rows = [[
        Paragraph("Q", styles["markshead"]),
        Paragraph("Source", styles["markshead"]),
        Paragraph("Reference", styles["markshead"]),
    ]]
    for q in traced:
        src = q.get("source") or {}
        reference = src.get("reference", "")
        if src.get("planner_title"):
            reference = f"{reference} — {src['planner_title']}"
        rows.append([
            Paragraph(_esc(q.get("number", "")), styles["answer"]),
            Paragraph(_esc(source_label(src.get("type"))), styles["answer"]),
            Paragraph(_esc(reference), styles["answer"]),
        ])

    W = branding.content_width(A4)
    table = Table(rows, colWidths=[1.2 * cm, 4.6 * cm, W - 5.8 * cm], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    story.append(Spacer(1, 12))


def build_question_paper_pdf(paper: dict, include_answers: bool = False) -> bytes:
    styles = _styles()
    story: list = []
    questions = paper.get("questions") or []
    sections = _group_questions_by_section(questions)

    # ── Standard LSS paper head ────────────────────────────────────────────
    story.append(Paragraph(_esc(exam_title(paper.get("paper_type"))), styles["exam"]))
    subject = paper.get("subject", "")
    class_name = paper.get("class_name", "")
    story.append(Paragraph(
        f"{_esc(subject)} &nbsp;•&nbsp; {_esc(class_name)}", styles["subtitle"],
    ))
    story.append(_paper_field_block(paper, styles))
    story.append(Spacer(1, 8))
    story.append(_marks_summary_table(paper, sections, styles))
    story.append(Spacer(1, 12))

    # ── Instructions ───────────────────────────────────────────────────────
    instructions = paper.get("instructions")
    if instructions:
        story.append(Paragraph(f"<b>Instructions:</b> {_esc(instructions)}", styles["instr"]))

    # ── Questions, grouped by section ──────────────────────────────────────
    for section_name, qs in sections:
        marks_note = f"({_section_marks(qs)} marks)"
        story.append(Paragraph(f"{_esc(section_name)} &nbsp;{marks_note}", styles["section"]))

        # A candidate cannot sit the paper without the choice rule, so state it —
        # unless the section's own instructions already do, which is common.
        attempt = next((q.get("attempt_count") for q in qs if q.get("attempt_count")), None)
        written = (qs[0].get("section_instructions") or "").strip() if qs else ""
        note = "" if "attempt" in written.lower() else choice_note(len(qs), attempt)
        directions = " ".join(x for x in (note, written) if x)
        if directions:
            story.append(Paragraph(_esc(directions), styles["sectionnote"]))

        for q in qs:
            number = q.get("number", "")
            text = _esc(q.get("question", ""))
            marks = q.get("marks")

            block: list = []
            block.append(Paragraph(f"<b>Q{number}.</b> {text}", styles["question"]))

            options = q.get("options") or []
            for opt in options:
                block.append(Paragraph(_esc(opt), styles["option"]))

            # Marks belong on an exam paper; the difficulty rating is internal
            # planning metadata and would have to be edited out before printing.
            if marks is not None:
                block.append(Paragraph(
                    f"({marks} mark{'s' if marks != 1 else ''})", styles["qmeta"],
                ))

            block.append(Spacer(1, 4))
            # Keep each question (with its options) on the same page when possible
            story.append(KeepTogether(block))

    # ── Answer Key (teachers only) ─────────────────────────────────────────
    answer_key = paper.get("answer_key") or []
    if include_answers and answer_key:
        story.append(PageBreak())
        story.append(Paragraph("Answer Key", styles["answer_head"]))
        _source_audit(story, questions, styles)
        for ans in answer_key:
            num = ans.get("number", "")
            correct = _esc(ans.get("correct_answer", ""))
            marks = ans.get("marks")
            suffix = f" ({marks} mark{'s' if marks != 1 else ''})" if marks else ""
            story.append(Paragraph(f"<b>Q{num}.</b> {correct}{suffix}", styles["answer"]))

    return branding.build_branded_pdf(
        story, pagesize=A4, title=paper.get("title", "Question Paper")
    )


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
    return branding.use_document_fonts({
        "title":   ParagraphStyle("lp_title",   parent=base["Title"],   fontSize=17, spaceAfter=4),
        "sub":     ParagraphStyle("lp_sub",     parent=base["Normal"],  fontSize=10, textColor=colors.grey, alignment=1, spaceAfter=10),
        "overview":ParagraphStyle("lp_over",    parent=base["Normal"],  fontSize=9.5, textColor=colors.HexColor("#374151"), backColor=colors.HexColor("#f3f4f6"), borderPadding=8, spaceAfter=12, leading=13),
        "th":      ParagraphStyle("lp_th",      parent=base["Normal"],  fontSize=8.5, textColor=colors.white, fontName="Helvetica-Bold", leading=11),
        "wk":      ParagraphStyle("lp_wk",      parent=base["Normal"],  fontSize=8.5, fontName="Helvetica-Bold", leading=11),
        "cell":    ParagraphStyle("lp_cell",    parent=base["Normal"],  fontSize=7.5, leading=10),
        "sumhead": ParagraphStyle("lp_sumhead", parent=base["Heading2"],fontSize=13, spaceBefore=16, spaceAfter=8, textColor=colors.HexColor("#1e3a8a")),
        "sumcell": ParagraphStyle("lp_sumcell", parent=base["Normal"],  fontSize=9.5, leading=13),
    })


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
    return branding.use_document_fonts({
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
    })


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
    styles = _lss_styles()
    W = branding.content_width(A4)
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

    return branding.build_branded_pdf(
        story, pagesize=A4, title=plan.get("title", "Lesson Plan")
    )


# ─── Legacy schedule grid (landscape A4) ──────────────────────────────────────

def _build_legacy_plan_pdf(plan: dict, plan_data: dict) -> bytes:
    """Render an older lesson plan (schedule grid + summary) in landscape A4."""
    lessons = plan_data.get("lessons") or []
    summary = plan_data.get("summary") or {}

    pagesize = landscape(A4)
    W = branding.content_width(pagesize)
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

    # Proportions of the original grid, rescaled to the branded content width.
    weights = [2.4, 4.6, 4.8, 6.2, 4.4, 4.4]
    col_widths = [W * w / sum(weights) for w in weights]
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
            sum_tbl = Table(rows, colWidths=[6 * cm, W - 6 * cm])
            sum_tbl.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(sum_tbl)

    return branding.build_branded_pdf(
        story, pagesize=pagesize, title=plan.get("title", "Lesson Plan")
    )
