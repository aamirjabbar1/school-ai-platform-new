"""
The printed fee voucher.

Drawn to match the voucher LSS already issues, because parents recognise their
voucher and a bank teller recognises the layout they stamp forty times a
morning. Changing either is a cost with no benefit.

One landscape A4 page carries three identical copies — Bank, School, Student —
separated by a dotted cut line, each with:

    crest · Lahore School System · e-mail · web            BankIslami mark
    challan number in a box            barcode of that number
    "To pay using KuickPay use Voucher Id as …"
    Name · F.Name · Issue/Due/Valid Till · Reg. No./Gr. No. · Class/Child # · Months
    POST TO CMD - BANK ISLAMI -
    fee heads, numbered, with amounts
    Total
    Late Fine · Discount · Prev. Bal · Paid · Net Bal.
    the note about the 10th and Rs.50/- per day
    CAMPUS-02 / BANK ISLAMI / account / All Over Pakistan
    the copy's name

Everything that is school policy rather than layout — bank, account, campus
code, the note, the daily fine — comes from `voucher_settings`, so the office
changes it without a deployment.
"""
from __future__ import annotations

import io
import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from reportlab.graphics.barcode import code128
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas

from services.erp.fees import ZERO, money

logger = logging.getLogger("agent")

COPIES = ("Bank Copy", "School Copy", "Student Copy")

PAGE = landscape(A4)
PAGE_WIDTH, PAGE_HEIGHT = PAGE
MARGIN = 0.6 * cm
GUTTER = 0.4 * cm
COPY_WIDTH = (PAGE_WIDTH - 2 * MARGIN - 2 * GUTTER) / 3

# Grey used for rules and labels — the sample is almost entirely black on white,
# which is what survives a fax machine and a bank's laser printer.
RULE = colors.HexColor("#9aa0a6")
LABEL_BG = colors.HexColor("#f2f2f2")


def _logo() -> ImageReader | None:
    from services.branding import LOGO_PATH
    path = Path(LOGO_PATH)
    if not path.exists():
        return None
    try:
        return ImageReader(str(path))
    except Exception as exc:                        # noqa: BLE001
        logger.warning("voucher: could not load logo %s: %s", path, exc)
        return None


def _rupees(value) -> str:
    """8085 → "8,085". Whole rupees: the sample shows no paisa, and a fee
    voucher with a decimal on it invites an argument at the counter.

    Half-up, explicitly. `quantize` defaults to banker's rounding, which turns
    8,060.50 into 8,060 — a rupee the school would never see again, and a
    figure that disagrees with the ledger behind it.
    """
    amount = money(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{int(amount):,}"


def _date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


class _Copy:
    """Draws one of the three copies. Coordinates are local to its column."""

    def __init__(self, canvas, left: float, data: dict, settings: dict, label: str):
        self.c = canvas
        self.left = left
        self.right = left + COPY_WIDTH
        self.data = data
        self.s = settings
        self.label = label
        self.y = PAGE_HEIGHT - MARGIN

    # ── helpers ──
    def _line(self, y: float, width: float = 0.5, colour=RULE):
        self.c.setStrokeColor(colour)
        self.c.setLineWidth(width)
        self.c.line(self.left, y, self.right, y)

    def _box(self, top: float, height: float, fill=None):
        self.c.setStrokeColor(RULE)
        self.c.setLineWidth(0.5)
        if fill:
            self.c.setFillColor(fill)
            self.c.rect(self.left, top - height, COPY_WIDTH, height, stroke=1, fill=1)
            self.c.setFillColor(colors.black)
        else:
            self.c.rect(self.left, top - height, COPY_WIDTH, height, stroke=1, fill=0)

    def _text(self, x: float, y: float, value: str, size: float = 7, bold=False):
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        self.c.setFillColor(colors.black)
        self.c.drawString(x, y, value or "")

    def _right_text(self, x: float, y: float, value: str, size: float = 7, bold=False):
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        self.c.setFillColor(colors.black)
        self.c.drawRightString(x, y, value or "")

    # ── sections ──
    def header(self):
        top = self.y
        logo = _logo()
        if logo is not None:
            try:
                self.c.drawImage(logo, self.left + 1, top - 1.05 * cm,
                                 width=1.45 * cm, height=1.45 * cm,
                                 preserveAspectRatio=True, mask="auto")
            except Exception:                        # noqa: BLE001
                pass

        self._text(self.left + 1.6 * cm, top - 0.5 * cm,
                   self.s.get("school_name", "Lahore School System"), size=11.5, bold=True)
        self._text(self.left + 1.6 * cm, top - 0.82 * cm,
                   f"E-Mail: {self.s.get('email', '')}", size=6.2)
        self._text(self.left + 1.6 * cm, top - 1.04 * cm,
                   f"Web: {self.s.get('website', '')}", size=6.2)

        # The bank's name sits where its mark sits on the printed voucher.
        self._right_text(self.right - 2, top - 0.65 * cm,
                         self.s.get("bank_name", "BankIslami"), size=12, bold=True)

        self.y = top - 1.45 * cm

    def challan(self):
        top = self.y
        height = 0.95 * cm
        box_width = COPY_WIDTH * 0.44

        self.c.setStrokeColor(colors.black)
        self.c.setLineWidth(0.8)
        self.c.rect(self.left, top - height, box_width, height, stroke=1, fill=0)
        self._text(self.left + 0.25 * cm, top - 0.62 * cm,
                   self.data.get("challan_no", ""), size=13)

        # The barcode is the challan number: it is what the teller scans, and it
        # must be the same number the box shows or the payment lands nowhere.
        challan = self.data.get("challan_no", "")
        if challan:
            try:
                barcode = code128.Code128(challan, barHeight=0.85 * cm, barWidth=0.5)
                barcode.drawOn(self.c, self.left + box_width + 0.3 * cm, top - height + 0.05 * cm)
            except Exception as exc:                 # noqa: BLE001
                logger.warning("voucher: barcode failed for %s: %s", challan, exc)

        self.y = top - height - 0.12 * cm

    def kuickpay(self):
        if not self.data.get("kuickpay_id"):
            return
        top = self.y
        height = 0.9 * cm
        self._box(top, height)
        self._text(self.left + 0.18 * cm, top - 0.32 * cm,
                   "To pay using KuickPay use Voucher Id as", size=8)
        self._text(self.left + 0.18 * cm, top - 0.68 * cm,
                   self.data["kuickpay_id"], size=11, bold=True)
        self.y = top - height - 0.12 * cm

    def _row(self, top: float, cells: list[tuple[str, str, float]], height: float = 0.6 * cm):
        """One table row: (label, value, share-of-width) tuples."""
        self.c.setStrokeColor(RULE)
        self.c.setLineWidth(0.5)
        x = self.left
        for label, value, share in cells:
            width = COPY_WIDTH * share
            label_width = width * (0.42 if len(cells) > 1 else 0.28)

            self.c.setFillColor(LABEL_BG)
            self.c.rect(x, top - height, label_width, height, stroke=1, fill=1)
            self.c.setFillColor(colors.black)
            self.c.rect(x + label_width, top - height, width - label_width, height,
                        stroke=1, fill=0)

            self._text(x + 0.12 * cm, top - height + 0.2 * cm, label, size=7.6, bold=True)
            self._text(x + label_width + 0.12 * cm, top - height + 0.2 * cm, value, size=8.4)
            x += width
        return top - height

    def details(self):
        d = self.data
        y = self.y
        y = self._row(y, [("Name", d.get("student_name", ""), 1.0)])
        y = self._row(y, [("F.Name", d.get("father_name", ""), 1.0)])
        y = self._row(y, [("Issue Date", _date(d.get("issue_date")), 0.5),
                          ("Due Date", _date(d.get("due_date")), 0.5)])
        y = self._row(y, [("Valid Till", _date(d.get("valid_till")), 0.5), ("", "", 0.5)])
        y = self._row(y, [("Reg. No.", d.get("registration_no", ""), 0.5),
                          ("Gr. No.", d.get("gr_no", ""), 0.5)])
        y = self._row(y, [("Class", d.get("class_name", ""), 0.5),
                          ("Child #", str(d.get("child_number", "") or ""), 0.5)])
        y = self._row(y, [("Months", d.get("months", ""), 1.0)])
        self.y = y - 0.12 * cm

    def post_to(self):
        top = self.y
        height = 0.58 * cm
        self._box(top, height)
        text = self.s.get("post_to", "POST TO CMD")
        self.c.setFont("Helvetica-Bold", 8.2)
        self.c.setFillColor(colors.black)
        label_width = self.c.stringWidth(text, "Helvetica-Bold", 8.2)
        centre = self.left + COPY_WIDTH / 2
        tail = f" - {self.s.get('bank_name', 'BANK ISLAMI').upper()} -"
        tail_width = self.c.stringWidth(tail, "Helvetica", 8.2)
        start = centre - (label_width + tail_width) / 2
        self.c.drawString(start, top - height + 0.19 * cm, text)
        self.c.setFont("Helvetica", 8.2)
        self.c.drawString(start + label_width, top - height + 0.19 * cm, tail)
        self.y = top - height - 0.12 * cm

    def heads(self, bottom: float):
        y = self.y
        height = 0.55 * cm

        self.c.setStrokeColor(RULE)
        self.c.setLineWidth(0.5)
        self.c.line(self.left, y, self.right, y)
        self._text(self.left + 0.6 * cm, y - 0.37 * cm, "Fee Head", size=8.4, bold=True)
        self._right_text(self.right - 0.12 * cm, y - 0.37 * cm, "Amount", size=8.4, bold=True)
        y -= height
        self.c.line(self.left, y, self.right, y)

        for index, line in enumerate(self.data.get("lines", []), start=1):
            self._text(self.left + 0.12 * cm, y - 0.37 * cm, str(index), size=8.4)
            self._text(self.left + 0.6 * cm, y - 0.37 * cm, line["head"], size=8.4)
            self._right_text(self.right - 0.12 * cm, y - 0.37 * cm,
                             _rupees(line["amount"]), size=8.4)
            y -= height

        # Grow into whatever space is left, so the note and the copy label sit
        # at the foot of the column on every voucher regardless of how many fee
        # heads it carries.
        spare = y - bottom
        if spare > 0:
            y -= spare
            self.c.setStrokeColor(RULE)
            self.c.line(self.left, y, self.right, y)

        self.c.line(self.left, y, self.right, y)
        self._right_text(self.right - 2.0 * cm, y - 0.38 * cm, "Total", size=8.8, bold=True)
        self._right_text(self.right - 0.12 * cm, y - 0.38 * cm,
                         _rupees(self.data.get("total", 0)), size=8.8, bold=True)
        y -= height
        self.c.line(self.left, y, self.right, y)
        self.y = y - 0.1 * cm

    def totals(self):
        y = self.y
        height = 0.55 * cm
        columns = [
            ("Late Fine", _rupees(self.data.get("late_fine", 0))),
            ("Discount", _rupees(self.data.get("discount", 0))),
            ("Prev. Bal", _rupees(self.data.get("previous_balance", 0))),
            ("Paid", _rupees(self.data.get("paid", 0))),
            ("Net Bal.", _rupees(self.data.get("net_balance", 0))),
        ]
        width = COPY_WIDTH / len(columns)

        x = self.left
        for label, _ in columns:
            self._text(x + 0.08 * cm, y - 0.37 * cm, label, size=7.4, bold=True)
            x += width
        y -= height
        self.c.setStrokeColor(RULE)
        self.c.line(self.left, y, self.right, y)

        x = self.left
        for index, (_, value) in enumerate(columns):
            last = index == len(columns) - 1
            self._right_text(x + width - 0.1 * cm, y - 0.38 * cm, value,
                             size=8.2, bold=last)
            x += width
        self.y = y - height - 0.1 * cm

    def note(self):
        y = self.y
        self._text(self.left, y - 0.25 * cm, "Note", size=8)
        y -= 0.45 * cm
        height = 1.5 * cm
        self._box(y, height)

        self.c.setFont("Helvetica-Oblique", 6.6)
        self.c.setFillColor(colors.black)
        text_y = y - 0.22 * cm
        for line in self._wrap(self.s.get("note", ""), 6.6, COPY_WIDTH - 0.35 * cm):
            self.c.drawString(self.left + 0.12 * cm, text_y, line)
            text_y -= 0.24 * cm
        y -= height + 0.1 * cm

        bank_line = self.s.get("bank_line", "")
        height = 0.8 * cm
        self._box(y, height)
        self.c.setFont("Helvetica", 6.8)
        text_y = y - 0.22 * cm
        for line in self._wrap(bank_line, 6.8, COPY_WIDTH - 0.35 * cm):
            self.c.drawString(self.left + 0.12 * cm, text_y, line)
            text_y -= 0.26 * cm
        self.y = y - height - 0.25 * cm

    def _wrap(self, text: str, size: float, width: float) -> list[str]:
        words = (text or "").split()
        lines, current = [], ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if self.c.stringWidth(candidate, "Helvetica", size) <= width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines[:6]

    def footer(self):
        self.c.setFont("Helvetica", 9)
        self.c.setFillColor(colors.black)
        self.c.drawCentredString(self.left + COPY_WIDTH / 2, self.y, self.label)

    # Height of everything drawn below the fee table: the totals strip, the
    # note, the bank line and the copy label.
    FOOTER_HEIGHT = 4.5 * cm

    def draw(self):
        self.header()
        self.challan()
        self.kuickpay()
        self.details()
        self.post_to()
        self.heads(bottom=MARGIN + self.FOOTER_HEIGHT)
        self.totals()
        self.note()
        self.footer()


def _cut_line(canvas, x: float):
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.setDash(1, 3)
    canvas.line(x, MARGIN, x, PAGE_HEIGHT - MARGIN)
    canvas.setDash()


def render(vouchers: list[dict], settings: dict) -> bytes:
    """One page per voucher, three copies across it."""
    buffer = io.BytesIO()
    canvas = pdfcanvas.Canvas(buffer, pagesize=PAGE)
    canvas.setTitle("Fee Voucher")

    for voucher in vouchers:
        for index, label in enumerate(COPIES):
            left = MARGIN + index * (COPY_WIDTH + GUTTER)
            _Copy(canvas, left, voucher, settings, label).draw()
            if index < len(COPIES) - 1:
                _cut_line(canvas, left + COPY_WIDTH + GUTTER / 2)
        canvas.showPage()

    canvas.save()
    return buffer.getvalue()
