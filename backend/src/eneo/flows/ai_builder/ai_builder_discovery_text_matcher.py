from __future__ import annotations

import re
from collections.abc import Iterable

_NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)
_SWEDISH_ARTIFACT_COMPOUND_PREFIXES: tuple[str, ...] = (
    "docx",
    "word",
    "pdf",
    "json",
)
# Covers the common Swedish artifact noun forms users compound with Word/PDF/JSON.
# Possessive forms are left unsplit until a real prompt needs them.
_SWEDISH_ARTIFACT_COMPOUND_SUFFIX_CANONICALS: tuple[tuple[str, str], ...] = (
    ("dokumentets", "dokument"),
    ("dokumentet", "dokument"),
    ("dokumenten", "dokument"),
    ("dokument", "dokument"),
    ("rapporterna", "rapport"),
    ("rapporten", "rapport"),
    ("rapporter", "rapport"),
    ("rapport", "rapport"),
    ("mallarna", "mall"),
    ("mallen", "mall"),
    ("mallar", "mall"),
    ("mall", "mall"),
    ("filerna", "fil"),
    ("filen", "fil"),
    ("filer", "fil"),
    ("fil", "fil"),
)


def normalize_discovery_text(value: str) -> str:
    collapsed = _NON_WORD_RE.sub(" ", value.casefold()).strip()
    tokens = [
        split_token
        for token in collapsed.split()
        for split_token in _split_swedish_artifact_compound(token)
    ]
    return " ".join(tokens)


def _split_swedish_artifact_compound(token: str) -> tuple[str, ...]:
    for prefix in _SWEDISH_ARTIFACT_COMPOUND_PREFIXES:
        if not token.startswith(prefix):
            continue
        suffix = token[len(prefix) :]
        for (
            suffix_candidate,
            canonical_suffix,
        ) in _SWEDISH_ARTIFACT_COMPOUND_SUFFIX_CANONICALS:
            if suffix == suffix_candidate:
                return (prefix, canonical_suffix)
    return (token,)


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
