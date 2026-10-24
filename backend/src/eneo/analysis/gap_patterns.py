"""Phrases with which an assistant admits it could not answer.

The pattern runs both in Postgres (``answer ~* pattern``, ARE syntax) and in
Python (``re``), so it deliberately uses only the subset the two dialects
agree on: alternation, ``\\s``, character classes, ``?`` and ``+``. No
look-around, no ``\\b``, no named groups. Matching is case-insensitive on
both sides.

The phrases are conservative: they name the *inability* ("hittar tyvärr
inte", "kan inte hjälpa"), never a mere caveat. A hit is a signal for the
operator to verify with ``read_conversation``, not a verdict.
"""

from __future__ import annotations

import re

_SWEDISH = (
    r"hittar\s+(tyvärr\s+)?(inte|ingen|inga)",
    r"har\s+(tyvärr\s+)?(inte|ingen)\s+(någon\s+)?(information|uppgift|underlag)",
    r"finns\s+(tyvärr\s+)?(inte|ingen|inga)\s+(någon\s+)?(information|uppgift|underlag)",
    r"kan\s+(tyvärr\s+)?(inte|ej)\s+(hjälpa|svara|besvara|hitta|ge)",
    r"saknar\s+(tyvärr\s+)?(information|uppgift|underlag)",
    r"framgår\s+(tyvärr\s+)?inte",
    r"(inte|ej)\s+(i|bland)\s+(mina|de|dina)\s+(källor|dokument|underlag)",
    r"utanför\s+(mitt|mina|de)\s+(område|källor|kunskap)",
    r"vet\s+(tyvärr\s+)?inte",
    r"ingen\s+information\s+om",
)

_ENGLISH = (
    r"(could\s+not|couldn'?t|cannot|can'?t|do\s+not|don'?t|did\s+not|didn'?t)\s+"
    r"(find|locate|see|answer|help)",
    r"no\s+(information|details?|data)\s+(about|on|regarding|available)",
    r"not\s+(available|found|covered|mentioned)\s+in\s+(my|the)\s+"
    r"(sources|documents|knowledge|materials)",
    r"(i\s+am|i'?m)\s+(not\s+able|unable)\s+to",
    r"unable\s+to\s+(find|answer|locate|help)",
    r"outside\s+(my|the)\s+(scope|sources|knowledge)",
    r"(sources|documents)\s+do\s+not\s+(contain|cover|mention|include)",
)

NOT_KNOWING_PATTERNS: tuple[str, ...] = _SWEDISH + _ENGLISH

# One alternation for the SQL side; each branch is safe to OR together.
NOT_KNOWING_REGEX = "|".join(f"({pattern})" for pattern in NOT_KNOWING_PATTERNS)

_COMPILED = re.compile(NOT_KNOWING_REGEX, re.IGNORECASE)


def not_knowing_fragment(answer: str) -> str | None:
    """The matched phrase, or ``None`` when the answer admits nothing."""
    match = _COMPILED.search(answer)
    return match.group(0) if match else None
