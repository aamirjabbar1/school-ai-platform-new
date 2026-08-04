"""
HTTP helpers shared by the download endpoints.
"""
from __future__ import annotations

import re
from urllib.parse import quote

_ASCII_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
# Path separators and control characters must never reach a saved filename.
_PATH_UNSAFE = re.compile(r"[/\\\x00-\x1f\x7f]+")
# An ASCII remnant shorter than this ("5" from an Urdu title) names nothing
# useful, so the caller's fallback reads better.
_MIN_ASCII_STEM = 3
_MAX_STEM = 120


def attachment_disposition(stem: str, extension: str, *, fallback: str = "download") -> str:
    """Build a Content-Disposition header that survives non-Latin filenames.

    HTTP headers are Latin-1, so a title in Urdu, Arabic or any non-Latin script
    cannot go into a plain `filename=`: the response fails while being sent,
    after the document was built successfully. RFC 6266 handles this with two
    parameters — an ASCII `filename` any client can read, plus a percent-encoded
    UTF-8 `filename*` that every current browser prefers.
    """
    stem = _PATH_UNSAFE.sub("_", (stem or "").strip())[:_MAX_STEM].strip() or fallback

    ascii_stem = _ASCII_UNSAFE.sub("_", stem).strip("._-")
    ascii_stem = re.sub(r"_{2,}", "_", ascii_stem)
    if len(ascii_stem.strip("._-")) < _MIN_ASCII_STEM:
        ascii_stem = fallback

    utf8_name = quote(f"{stem}.{extension}", safe="")
    return (
        f'attachment; filename="{ascii_stem}.{extension}"; '
        f"filename*=UTF-8''{utf8_name}"
    )
