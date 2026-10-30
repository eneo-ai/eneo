"""Short text a person reads on one line: run labels and speaker names."""

from __future__ import annotations

import unicodedata

ONE_LINE_TEXT_MAX_CHARS = 120
_NOT_ONE_LINE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})


def breaks_one_line(char: str) -> bool:
    """A control, format, surrogate or line or paragraph separator character:
    it breaks the line the text is shown on, or cannot be seen."""
    return unicodedata.category(char) in _NOT_ONE_LINE_CATEGORIES


def _visible_line(text: str) -> str:
    visible = "".join(
        char for char in text if char.isspace() or not breaks_one_line(char)
    )
    return " ".join(visible.split())


def one_line(text: str) -> str | None:
    """``text`` made one short line: whitespace, line breaks included,
    collapses to single spaces and other characters that break the line or
    cannot be seen go. Left empty or over the bound, it is None."""
    cleaned = _visible_line(text)
    return cleaned if 0 < len(cleaned) <= ONE_LINE_TEXT_MAX_CHARS else None


def one_line_start(text: str) -> str | None:
    """``text`` (NFC) made one line as ``one_line`` does, and cut to the bound
    where it is longer; None when nothing visible is left."""
    cleaned = _visible_line(unicodedata.normalize("NFC", text))
    return cleaned[:ONE_LINE_TEXT_MAX_CHARS].rstrip() or None
