# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.

"""Free text that ends up in audit records and next to them.

A reason typed by an administrator is shown to other people and stored in
the audit log, so it is reduced to one plain line that reads as it was
stored. This module is the reference for the rule; the web client's
``reason.ts`` mirrors it:

1. Remove control characters that are not whitespace, format characters
   (category Cf: zero-width, bidirectional, tag characters), lone
   surrogates, every default-ignorable code point (Hangul fillers,
   variation selectors, the combining grapheme joiner) and the blank
   Braille pattern U+2800.
2. Compose to NFC. Removing first means nothing composes across a
   removed character, so normalising twice gives the same text.
3. Replace every run of whitespace (Unicode White_Space, line breaks
   included) with one space, and trim.

A reason needs at least ``REASON_MIN_LENGTH`` visible characters, those
that are neither whitespace nor combining marks, and at most
``REASON_MAX_LENGTH`` code points after normalisation.
"""

import re
import unicodedata
from typing import Annotated

from pydantic import AfterValidator

# The CHECK constraints on the stored reasons count code points within the
# same bounds.
REASON_MIN_LENGTH = 10
REASON_MAX_LENGTH = 500

# Unicode White_Space. Python's str.isspace() also counts U+001C-U+001F,
# which are removed as controls here.
_WHITESPACE = "\t\n\v\f\r \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000"
_WHITESPACE_RUN = re.compile(f"[{_WHITESPACE}]+")
_IS_WHITESPACE = re.compile(f"[{_WHITESPACE}]")

# Default_Ignorable_Code_Point (DerivedCoreProperties.txt). The property is
# closed: its reserved ranges are assigned in advance.
_DEFAULT_IGNORABLE = (
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFF8),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)
_BRAILLE_BLANK = 0x2800
_REMOVED_CATEGORIES = frozenset({"Cf", "Cs"})


def _is_removed(char: str) -> bool:
    code = ord(char)
    if code == _BRAILLE_BLANK:
        return True
    if any(low <= code <= high for low, high in _DEFAULT_IGNORABLE):
        return True
    category = unicodedata.category(char)
    if category == "Cc":
        return _IS_WHITESPACE.match(char) is None
    return category in _REMOVED_CATEGORIES


def normalize_free_text(value: str) -> str:
    """The text as it is stored: invisible and control characters removed,
    NFC, every whitespace run collapsed to one space, trimmed. Idempotent."""
    kept = "".join(char for char in value if not _is_removed(char))
    composed = unicodedata.normalize("NFC", kept)
    return _WHITESPACE_RUN.sub(" ", composed).strip(" ")


def visible_length(text: str) -> int:
    """Characters that show: neither whitespace nor a combining mark."""
    return sum(
        1
        for char in text
        if _IS_WHITESPACE.match(char) is None
        and not unicodedata.category(char).startswith("M")
    )


def _normalized_reason(value: str) -> str:
    normalized = normalize_free_text(value)
    if (
        visible_length(normalized) < REASON_MIN_LENGTH
        or len(normalized) > REASON_MAX_LENGTH
    ):
        raise ValueError(
            f"The reason needs at least {REASON_MIN_LENGTH} visible characters"
            f" and at most {REASON_MAX_LENGTH} characters."
        )
    return normalized


AuditedReason = Annotated[str, AfterValidator(_normalized_reason)]
