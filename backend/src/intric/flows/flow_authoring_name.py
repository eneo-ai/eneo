from __future__ import annotations

import re

MAX_FLOW_NAME_LENGTH = 120

_WHITESPACE_RE = re.compile(r"\s+")
_SLUG_DELIMITER_RE = re.compile(r"[_-]+")
_SLUG_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_GENERATED_NAME_TOKENS = {
    "artifact",
    "artifacts",
    "builder",
    "chain",
    "flow",
    "lone",
    "pattern",
    "revision",
    "step",
}
_CONNECTOR_TOKENS = {"and", "for", "from", "of", "to", "with"}
_ACRONYM_TOKENS = {
    "ai",
    "api",
    "csv",
    "docx",
    "http",
    "id",
    "json",
    "mcp",
    "ocr",
    "pdf",
    "url",
    "xml",
}


def normalize_flow_name(value: str) -> str:
    normalized = _WHITESPACE_RE.sub(" ", value).strip()
    if not normalized:
        raise ValueError("Flow names must not be empty.")
    normalized = _humanize_generated_slug_name(normalized)
    if len(normalized) > MAX_FLOW_NAME_LENGTH:
        raise ValueError(
            f"Flow names must be at most {MAX_FLOW_NAME_LENGTH} characters long."
        )
    return normalized


def normalize_optional_flow_name(value: str | None) -> str | None:
    if value is None:
        return None
    return normalize_flow_name(value)


def _humanize_generated_slug_name(value: str) -> str:
    if not _looks_generated_slug_like(value):
        return value

    raw_tokens = [token.casefold() for token in _SLUG_TOKEN_RE.findall(value)]
    kept_tokens = [
        token
        for token in raw_tokens
        if token not in _CONNECTOR_TOKENS and token not in _GENERATED_NAME_TOKENS
    ]
    if len(kept_tokens) < 2:
        kept_tokens = raw_tokens

    return " ".join(_format_name_token(token) for token in kept_tokens)


def _looks_generated_slug_like(value: str) -> bool:
    if " " in value or not _SLUG_DELIMITER_RE.search(value):
        return False
    delimiter_count = len(_SLUG_DELIMITER_RE.findall(value))
    tokens = [token.casefold() for token in _SLUG_TOKEN_RE.findall(value)]
    if len(tokens) < 4:
        return False
    if delimiter_count >= 3:
        return True
    return any(token in _GENERATED_NAME_TOKENS for token in tokens)


def _format_name_token(token: str) -> str:
    if token in _ACRONYM_TOKENS:
        return token.upper()
    return token[:1].upper() + token[1:]
