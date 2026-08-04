"""
Urdu / Arabic text support for the PDF renderer.

Word shapes text itself, which is why the .docx exports have always been fine.
reportlab does not: it draws the code points it is handed, left to right, in the
order it is handed them. Urdu therefore came out as isolated, unjoined letters
running the wrong way, and every letter missing from the body font printed as a
hollow box — DejaVu Sans carries almost none of the Urdu-specific ones
(ٹ ڈ ڑ ں ھ ے).

Three separate steps are needed, which is why they live here rather than being
folded into the escaping helper:

  1. Shaping      Arabic letters change form depending on their neighbours.
                  arabic_reshaper maps a word onto the presentation forms that
                  actually join up.
  2. Word order   Inside a word the visual order is the reverse of the logical
                  (storage) order; python-bidi applies the Unicode bidirectional
                  algorithm per word.
  3. Line order   The order of *words* can only be fixed after reportlab has
                  decided where the lines break — reverse the whole sentence up
                  front and a sentence that wraps reads bottom-line-first. The
                  `Paragraph` below hooks the line breaker and flips each run of
                  Urdu words once the lines are known.

Everything here degrades quietly. Without the shaping libraries, or without an
Urdu font installed, text still renders (badly) instead of raising: a lesson
plan that looks wrong beats a download that 500s.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Callable

from reportlab.platypus import Paragraph as _RLParagraph

from services import branding

try:
    import arabic_reshaper
except ImportError:  # pragma: no cover - exercised only on an incomplete install
    arabic_reshaper = None
    print("[rtl] arabic-reshaper is not installed — Urdu letters will not join up")

try:
    from bidi import get_display          # python-bidi >= 0.6
except ImportError:
    try:
        from bidi.algorithm import get_display   # python-bidi < 0.6
    except ImportError:  # pragma: no cover
        get_display = None
        print("[rtl] python-bidi is not installed — Urdu will read left to right")


# Urdu lives in the main Arabic block; the rest are included so Arabic, Persian
# and Hebrew quotations in a paper are handled by the same path.
_RTL_RE = re.compile(
    "["
    "֐-׿"      # Hebrew
    "؀-ۿ"      # Arabic — Urdu's letters and digits live here
    "܀-ݏ"      # Syriac
    "ݐ-ݿ"      # Arabic Supplement
    "ࡰ-࢟"      # Arabic Extended-B
    "ࢠ-ࣿ"      # Arabic Extended-A
    "ﭐ-﷿"      # Arabic Presentation Forms-A
    "ﹰ-﻿"      # Arabic Presentation Forms-B
    "]"
)
# Anything that anchors a run to the left-to-right flow.
_LTR_RE = re.compile("[0-9A-Za-zÀ-ɏ]")
_WHITESPACE_RE = re.compile(r"(\s+)")

_RTL, _LTR = "R", "L"


def has_rtl(text: Any) -> bool:
    """True if the text contains anything written right to left."""
    return bool(text) and bool(_RTL_RE.search(str(text)))


# ─── Escaping + shaping ───────────────────────────────────────────────────────

def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@lru_cache(maxsize=1)
def _reshaper():
    if arabic_reshaper is None:
        return None
    # The library deletes harakat by default. Early-grade Urdu material is often
    # written *with* them, and silently dropping them would change the content
    # the teacher asked for, so they are kept.
    return arabic_reshaper.ArabicReshaper(configuration={"delete_harakat": False})


def _shape_word(word: str) -> str:
    """Joined, visually ordered form of a single right-to-left word."""
    reshaper = _reshaper()
    if reshaper is not None:
        word = reshaper.reshape(word)
    if get_display is not None:
        try:
            word = get_display(word, base_dir="R")
        except TypeError:      # older signature without base_dir
            word = get_display(word)
    return word


def escape(text: Any) -> str:
    """Escape text for a reportlab Paragraph, shaping any Urdu/Arabic in it.

    Latin text is untouched. Right-to-left words are shaped and tagged with the
    Urdu face, so a mixed sentence keeps the document font for its English half.
    """
    if text is None:
        return ""
    s = str(text)
    if not _RTL_RE.search(s):
        return _xml(s)

    font = branding.urdu_font()
    out = []
    for token in _WHITESPACE_RE.split(s):
        if token and _RTL_RE.search(token):
            shaped = _xml(_shape_word(token))
            out.append(f'<font name="{font}">{shaped}</font>' if font else shaped)
        else:
            out.append(_xml(token))
    return "".join(out)


# ─── Right-to-left line layout ────────────────────────────────────────────────

def _reorder_words(words: list, text_of: Callable[[Any], str]) -> list:
    """Flip each run of right-to-left words within one laid-out line."""
    directions = []
    for word in words:
        text = text_of(word) or ""
        if _RTL_RE.search(text):
            directions.append(_RTL)
        elif _LTR_RE.search(text):
            directions.append(_LTR)
        else:
            directions.append(None)     # punctuation — takes its neighbours' side

    if _RTL not in directions:
        return words

    # A dash or bracket sitting between two Urdu words belongs to the Urdu run;
    # anywhere else it stays with the left-to-right flow.
    for i, direction in enumerate(directions):
        if direction is not None:
            continue
        before = next((d for d in reversed(directions[:i]) if d is not None), None)
        after = next((d for d in directions[i + 1:] if d is not None), None)
        directions[i] = _RTL if before == _RTL and after == _RTL else _LTR

    ordered: list = []
    run: list = []
    for word, direction in zip(words, directions):
        if direction == _RTL:
            run.append(word)
            continue
        if run:
            ordered.extend(reversed(run))
            run = []
        ordered.append(word)
    ordered.extend(reversed(run))
    return ordered


def _reorder_lines(para) -> None:
    """Lay the right-to-left runs of an already-broken paragraph out visually."""
    lines = getattr(para, "lines", None)
    if not lines or getattr(para, "_rtl_reordered", False):
        return

    for index, line in enumerate(lines):
        if isinstance(line, tuple):
            # Single-style paragraph: (extraSpace, [word, ...]) with plain strings.
            words = line[1]
            ordered = _reorder_words(list(words), lambda w: w)
            lines[index] = (line[0], ordered, *line[2:])
        else:
            # Mixed styles: a line object carrying one Frag per word.
            words = getattr(line, "words", None)
            if words:
                line.words = _reorder_words(list(words), lambda f: getattr(f, "text", ""))

    para._rtl_reordered = True


class Paragraph(_RLParagraph):
    """A platypus Paragraph that lays Urdu/Arabic word runs out right to left.

    reportlab breaks lines in logical order, which is what we want — the first
    words of a sentence land on the first line. Only once those lines exist can
    each run of Urdu words be flipped into reading order, so that is done here
    rather than in the markup.
    """

    def breakLines(self, width):
        para = super().breakLines(width)
        try:
            _reorder_lines(para)
        except Exception as exc:
            # Worst case the words read left to right; they are still joined,
            # still legible, and the document is still produced.
            print(f"[rtl] could not reorder right-to-left text: {exc}")
        return para
