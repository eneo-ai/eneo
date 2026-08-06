"""The single field-naming identity boundary.

Identity is folded, wording is the author's: code that must decide
whether two field names mean the same thing compares folded forms and
never rewrites or rejects a name for its language. This module is a
leaf so every layer — intent admission, result contracts, critics,
template binding — can share the one folding rule without import
cycles.
"""

from __future__ import annotations

import re
import unicodedata

_FIELD_NAME_SEPARATOR_RE = re.compile(r"[^0-9a-z]+")


def fold_result_field_name(name: str) -> str:
    """Fold a schema field name for identity comparison.

    Case, diacritics, and separator style must not decide whether a role is
    recognized: proposals name fields in natural Swedish ("åtgärder",
    "öppna frågor") while the accepted vocabulary is stored ASCII-folded.
    """

    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return _FIELD_NAME_SEPARATOR_RE.sub("_", stripped.casefold()).strip("_")
