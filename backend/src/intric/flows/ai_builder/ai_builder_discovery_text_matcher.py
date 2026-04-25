from __future__ import annotations

import re
from collections.abc import Iterable

_NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)


def normalize_discovery_text(value: str) -> str:
    collapsed = _NON_WORD_RE.sub(" ", value.casefold()).strip()
    return " ".join(collapsed.split())


def contains_phrase(text: str, phrase: str) -> bool:
    if not text or not phrase:
        return False
    normalized_phrase = normalize_discovery_text(phrase)
    if not normalized_phrase:
        return False
    return f" {normalized_phrase} " in f" {text} "


def contains_any_phrase(text: str, phrases: Iterable[str]) -> bool:
    return any(contains_phrase(text, phrase) for phrase in phrases)


def contains_token_prefix(text: str, prefix: str) -> bool:
    if not text or not prefix:
        return False
    normalized_prefix = normalize_discovery_text(prefix)
    if not normalized_prefix:
        return False
    return any(token.startswith(normalized_prefix) for token in text.split())


def contains_any_token_prefix(text: str, prefixes: Iterable[str]) -> bool:
    return any(contains_token_prefix(text, prefix) for prefix in prefixes)
