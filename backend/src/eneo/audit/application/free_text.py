"""Free text that ends up in audit records and next to them.

A reason typed by an administrator is shown to other people and stored in
the audit log, so it is reduced to one plain line: no control characters, no
bidirectional overrides that could make it read differently from what was
stored, and no hidden zero-width characters.
"""

import unicodedata
from typing import Annotated

from pydantic import AfterValidator

# The spaces_users and widgets CHECK constraints use the same bounds.
REASON_MIN_LENGTH = 10
REASON_MAX_LENGTH = 500

_FORMAT_CONTROLS = frozenset(
    {
        "\u061c",  # Arabic letter mark
        *(chr(code) for code in range(0x200B, 0x2010)),  # zero-width, LRM, RLM
        *(chr(code) for code in range(0x202A, 0x202F)),  # bidi embeddings
        *(chr(code) for code in range(0x2066, 0x206A)),  # bidi isolates
    }
)


def _is_removed(char: str) -> bool:
    return char in _FORMAT_CONTROLS or (
        not char.isspace() and unicodedata.category(char) == "Cc"
    )


def normalize_free_text(value: str) -> str:
    """NFC, without control and bidi characters, every whitespace run
    (line breaks included) collapsed to one space, and stripped."""
    text = unicodedata.normalize("NFC", value)
    kept = "".join(char for char in text if not _is_removed(char))
    # str.split() splits on every Unicode whitespace character, including
    # the C0 controls \t, \n and \r and the separators U+2028 and U+2029.
    return " ".join(kept.split())


def _normalized_reason(value: str) -> str:
    normalized = normalize_free_text(value)
    if not REASON_MIN_LENGTH <= len(normalized) <= REASON_MAX_LENGTH:
        raise ValueError(
            f"The reason must be between {REASON_MIN_LENGTH} and"
            f" {REASON_MAX_LENGTH} characters long."
        )
    return normalized


AuditedReason = Annotated[str, AfterValidator(_normalized_reason)]
