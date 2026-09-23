"""Short text a person reads on one line: run labels and speaker names."""

from __future__ import annotations

import unicodedata

ONE_LINE_TEXT_MAX_CHARS = 120
_NOT_ONE_LINE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})


def breaks_one_line(char: str) -> bool:
    """A control, format, surrogate or line or paragraph separator character:
    it breaks the line the text is shown on, or cannot be seen."""
    return unicodedata.category(char) in _NOT_ONE_LINE_CATEGORIES
