from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_REDACTED_VALUE = "[REDACTED]"
REDACTION_POLICY_VERSION = "flow-evidence-redaction.v3"
_MAX_NESTED_URL_REDACTION_DEPTH = 8
_SENSITIVE_URL_QUERY_EXACT_KEYS = {"code", "state"}
_SENSITIVE_EXACT_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "password",
    "passwd",
    "secret",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "bearer",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "auth_token",
    "session_token",
    "csrf_token",
    "x_api_key",
    "client_secret",
    "webhook_secret",
    "private_key",
    "secret_key",
    "signature",
    "signed_url",
}
_SENSITIVE_SUFFIXES = (
    "_token",
    "_secret",
    "_password",
    "_passwd",
    "_cookie",
    "_credential",
    "_credentials",
    "_authorization",
    "_api_key",
    "_apikey",
    "_signature",
    "_signed_url",
)
_BEARER_TOKEN_PATTERN = re.compile(r"(?i)\bbearer\s+[a-z0-9._\-~+/]+=*")
_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_URL_TRAILING_PROSE_PUNCTUATION = ".,;:!?)]}"


@dataclass(frozen=True)
class MaskedField:
    path: str
    key: str | None
    reason: str


@dataclass(frozen=True)
class RedactionResult:
    value: Any
    masked_paths: tuple[str, ...]
    masked_fields: tuple[MaskedField, ...] = ()


@dataclass(frozen=True)
class StringRedactionResult:
    value: str
    reason: str | None = None


def is_sensitive_key(key: str | None) -> bool:
    if key is None:
        return False

    normalized_key = _normalize_key(key)
    if not normalized_key:
        return False
    if normalized_key in _SENSITIVE_EXACT_KEYS:
        return True
    if any(normalized_key.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES):
        return True

    key_tokens = set(normalized_key.split("_"))
    token_pairs = (
        {"api", "key"},
        {"access", "token"},
        {"refresh", "token"},
        {"id", "token"},
        {"auth", "token"},
        {"session", "token"},
        {"client", "secret"},
        {"webhook", "secret"},
        {"private", "key"},
        {"secret", "key"},
        {"signed", "url"},
    )
    if any(pair.issubset(key_tokens) for pair in token_pairs):
        return True
    if "authorization" in key_tokens:
        return True
    if "cookie" in key_tokens:
        return True
    if "credential" in key_tokens or "credentials" in key_tokens:
        return True
    return False


def redact_url_secrets(value: str) -> str:
    return _redact_url_secrets(value, nested_depth=0)


def _redact_url_secrets(value: str, *, nested_depth: int) -> str:
    if nested_depth > _MAX_NESTED_URL_REDACTION_DEPTH:
        return _REDACTED_VALUE

    try:
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.netloc:
            return value

        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port is not None else ""
        netloc = f"{host}{port}"

        if not parse_qsl(parsed.query, keep_blank_values=True):
            if parsed.username is None and parsed.password is None:
                return value
            return urlunsplit(
                (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
            )

        redacted_query: list[tuple[str, str]] = []
        for key, item_value in parse_qsl(parsed.query, keep_blank_values=True):
            if _is_sensitive_url_query_key(key):
                redacted_query.append((key, _REDACTED_VALUE))
            elif "://" in item_value:
                redacted_query.append(
                    (
                        key,
                        _redact_url_secrets(
                            item_value,
                            nested_depth=nested_depth + 1,
                        ),
                    )
                )
            else:
                redacted_query.append((key, item_value))

        return urlunsplit(
            (
                parsed.scheme,
                netloc if parsed.username or parsed.password else parsed.netloc,
                parsed.path,
                urlencode(redacted_query, doseq=True),
                parsed.fragment,
            )
        )
    except ValueError:
        return _REDACTED_VALUE


def _is_sensitive_url_query_key(key: str) -> bool:
    normalized_key = _normalize_key(key)
    return (
        normalized_key in _SENSITIVE_URL_QUERY_EXACT_KEYS
        or "token" in normalized_key
        or "secret" in normalized_key
        or is_sensitive_key(key)
    )


def _redact_embedded_url(match: re.Match[str]) -> str:
    url = match.group(0)
    trailing_punctuation = ""
    while url and url[-1] in _URL_TRAILING_PROSE_PUNCTUATION:
        trailing_punctuation = url[-1] + trailing_punctuation
        url = url[:-1]
    return f"{redact_url_secrets(url)}{trailing_punctuation}"


def redact_string(value: str, *, key: str | None) -> str:
    return redact_string_with_reason(value, key=key).value


def redact_string_with_reason(value: str, *, key: str | None) -> StringRedactionResult:
    if is_sensitive_key(key):
        return StringRedactionResult(value=_REDACTED_VALUE, reason="sensitive_key")

    redacted_value = value
    reason: str | None = None
    if "://" in redacted_value:
        url_redacted = _URL_PATTERN.sub(_redact_embedded_url, redacted_value)
        if url_redacted != redacted_value:
            redacted_value = url_redacted
            reason = "sensitive_url"

    bearer_redacted = _BEARER_TOKEN_PATTERN.sub("Bearer [REDACTED]", redacted_value)
    if bearer_redacted != redacted_value:
        redacted_value = bearer_redacted
        reason = reason or "bearer_token"

    return StringRedactionResult(value=redacted_value, reason=reason)


def redact_payload(value: Any, *, key: str | None = None) -> Any:
    return redact_payload_with_manifest(value, key=key).value


def redact_payload_with_manifest(
    value: Any,
    *,
    key: str | None = None,
    path: str | None = None,
) -> RedactionResult:
    if isinstance(value, dict):
        redacted_dict: dict[str, Any] = {}
        dict_masked_paths: list[str] = []
        dict_masked_fields: list[MaskedField] = []
        raw_items = cast(dict[object, Any], value)
        for raw_item_key, item_value in raw_items.items():
            item_key = str(raw_item_key)
            child_path = f"{path}.{item_key}" if path else item_key
            child_result = redact_payload_with_manifest(
                item_value,
                key=item_key,
                path=child_path,
            )
            redacted_dict[item_key] = child_result.value
            dict_masked_paths.extend(child_result.masked_paths)
            dict_masked_fields.extend(child_result.masked_fields)
        return RedactionResult(
            value=redacted_dict,
            masked_paths=tuple(dict_masked_paths),
            masked_fields=tuple(dict_masked_fields),
        )
    if isinstance(value, list):
        redacted_items: list[Any] = []
        list_masked_paths: list[str] = []
        list_masked_fields: list[MaskedField] = []
        for index, item in enumerate(cast(list[Any], value)):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            child_result = redact_payload_with_manifest(
                item,
                key=key,
                path=child_path,
            )
            redacted_items.append(child_result.value)
            list_masked_paths.extend(child_result.masked_paths)
            list_masked_fields.extend(child_result.masked_fields)
        return RedactionResult(
            value=redacted_items,
            masked_paths=tuple(list_masked_paths),
            masked_fields=tuple(list_masked_fields),
        )
    if isinstance(value, str):
        redacted_string = redact_string_with_reason(value, key=key)
        string_masked_paths = (path,) if path and redacted_string.value != value else ()
        string_masked_fields: tuple[MaskedField, ...] = ()
        if path and redacted_string.value != value:
            string_masked_fields = (
                MaskedField(
                    path=path,
                    key=key,
                    reason=redacted_string.reason or "sensitive_value",
                ),
            )
        return RedactionResult(
            value=redacted_string.value,
            masked_paths=string_masked_paths,
            masked_fields=string_masked_fields,
        )
    return RedactionResult(value=value, masked_paths=())


def _normalize_key(key: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower())
    return normalized.strip("_")
