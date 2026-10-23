"""Why a sync skipped a file: a stable code with parameters, and the English
text older rows and the job summary carry.

Every skipped detail the sync writes has a code, its parameters and a retry
flag; the frontends translate by code. Rows written before codes existed hold
the text only and are classified when served, so one classifier covers every
string the sync has ever written and the texts stay defined in one place.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal, cast, get_args

from typing_extensions import NotRequired, TypedDict

from eneo.observability.error_text import user_visible_error

SkipReasonCode = Literal[
    "unsupported_type",
    "no_text_layer",
    "empty_content",
    "file_too_large",
    "extraction_limit",
    "incomplete_download",
    "password_protected",
    "corrupt_file",
    "http_error",
    "removal_failed",
    "listing_failed",
    "scope_path_unavailable",
    "missing_item_id",
    "unchanged",
    "set_aside",
    "error",
]
SKIP_REASON_CODES: tuple[SkipReasonCode, ...] = get_args(SkipReasonCode)

# What an extraction limit was about; the value, when there is one, is a count.
ExtractionLimitKind = Literal[
    "text_bytes", "pdf_pages", "resource", "deadline", "output", "other"
]

SkipReasonParams = dict[str, str | int]


class SkippedDetail(TypedDict):
    file: str
    reason: str
    code: NotRequired[SkipReasonCode]
    params: NotRequired[SkipReasonParams]
    # The pass could not finish the item; the next sync tries it again.
    retry: NotRequired[bool]


NO_TEXT_LAYER_REASON = "No text layer (scanned document; OCR is not supported)"
EMPTY_CONTENT_REASON = "Empty or unreadable content"
PASSWORD_PROTECTED_REASON = "Password-protected file"
CORRUPT_FILE_REASON = "Corrupt or malformed file"
SCOPE_PATH_UNAVAILABLE_REASON = "Folder scope path unavailable"
MISSING_ITEM_ID_REASON = "Missing item id"
# 2.2.x delta syncs listed a file whose change was already processed as skipped.
ALREADY_SYNCED_REASON = "Already synced (no changes)"

# The parser ran to completion and found nothing. Only these reasons may
# remove an existing index entry; every other outcome is non-destructive.
NO_TEXT_REASONS: frozenset[str] = frozenset(
    {NO_TEXT_LAYER_REASON, EMPTY_CONTENT_REASON}
)

# Older rows carry the retry flag as this suffix on the text.
LEGACY_RETRY_SUFFIX = " (retried by the next sync)"

_EXTRACTION_LIMIT_TEXT: dict[str, str] = {
    "resource": "document resource limit",
    "deadline": "extraction deadline",
    "output": "text output limit",
}


def unsupported_type_reason(label: str) -> str:
    return f"Unsupported file type ({label})"


def file_too_large_reason(limit_bytes: int) -> str:
    """Skip reason for a download above ``SHAREPOINT_MAX_DOWNLOAD_BYTES``."""
    limit_mb = limit_bytes / (1024 * 1024)
    return f"File too large (exceeds {limit_mb:g} MB limit)"


def extraction_limit_reason(limit: str) -> str:
    return f"Exceeds extraction limit ({limit})"


def set_aside_reason(attempts: int, detail: str) -> str:
    """An item that kept failing, set aside so newer changes keep flowing; a
    later sync tries it again."""
    return f"Set aside after {attempts} failed attempts, tried again later: {detail}"


def error_reason(detail: str | BaseException) -> str:
    """``Error: <detail>``; an exception is described by ``user_visible_error``."""
    return user_visible_error(f"Error: {user_visible_error(detail)}")


def reason_text(code: SkipReasonCode, params: Mapping[str, str | int]) -> str:
    """The English text of a coded reason, as older clients and logs read it."""
    if code == "unsupported_type":
        return unsupported_type_reason(str(params.get("label", "")))
    if code == "no_text_layer":
        return NO_TEXT_LAYER_REASON
    if code == "empty_content":
        return EMPTY_CONTENT_REASON
    if code == "file_too_large":
        return f"File too large (exceeds {params.get('limit_mb', '')} MB limit)"
    if code == "extraction_limit":
        return extraction_limit_reason(_extraction_limit_text(params))
    if code == "incomplete_download":
        return error_reason(str(params.get("detail", "Incomplete download")))
    if code == "password_protected":
        return error_reason(PASSWORD_PROTECTED_REASON)
    if code == "corrupt_file":
        return error_reason(CORRUPT_FILE_REASON)
    if code == "http_error":
        message = str(params.get("message", "")).strip()
        return error_reason(f"HTTP {params.get('status', '')} {message}".strip())
    if code == "removal_failed":
        return f"Could not remove {params.get('what', '')}: {params.get('detail', '')}"
    if code == "listing_failed":
        return f"Could not list folder contents: {params.get('detail', '')}"
    if code == "scope_path_unavailable":
        return SCOPE_PATH_UNAVAILABLE_REASON
    if code == "missing_item_id":
        return MISSING_ITEM_ID_REASON
    if code == "unchanged":
        return ALREADY_SYNCED_REASON
    if code == "set_aside":
        return set_aside_reason(
            int(params.get("attempts", 0)), str(params.get("detail", ""))
        )
    return error_reason(str(params.get("detail", "")))


def _extraction_limit_text(params: Mapping[str, str | int]) -> str:
    kind = str(params.get("limit", "other"))
    if kind == "text_bytes":
        return f"{params.get('value', '')} bytes of text"
    if kind == "pdf_pages":
        return f"{params.get('value', '')} PDF pages"
    return _EXTRACTION_LIMIT_TEXT.get(kind) or str(params.get("detail", kind))


def skipped_by_code(
    file: str,
    code: SkipReasonCode,
    *,
    retry: bool = False,
    **params: str | int,
) -> SkippedDetail:
    """A detail whose writer knows the code; the text follows from it."""
    detail: SkippedDetail = {
        "file": file,
        "reason": reason_text(code, params),
        "code": code,
        "params": dict(params),
    }
    if retry:
        detail["retry"] = True
    return detail


def skipped(file: str, reason: str, *, retry: bool = False) -> SkippedDetail:
    """A detail for ``reason`` text the sync composed; the code is read from it."""
    code, params, legacy_retry = classify_skip_reason(reason)
    detail: SkippedDetail = {
        "file": file,
        "reason": _strip_legacy_suffix(reason),
        "code": code,
        "params": params,
    }
    if retry or legacy_retry:
        detail["retry"] = True
    return detail


def error_skipped(file: str, error: str | BaseException) -> SkippedDetail:
    """A detail for an error, described without URLs, credentials or hosts."""
    return skipped(file, error_reason(error))


_UNSUPPORTED_TYPE = re.compile(r"^Unsupported file type \((.+)\)$", re.S)
_FILE_TOO_LARGE = re.compile(r"^File too large \(exceeds (.+) MB limit\)$")
_EXTRACTION_LIMIT = re.compile(r"^Exceeds extraction limit \((.+)\)$", re.S)
_LIMIT_TEXT_BYTES = re.compile(r"^(\d+) bytes of text$")
_LIMIT_PDF_PAGES = re.compile(r"^(\d+) PDF pages$")
_REMOVAL_FAILED = re.compile(r"^Could not remove ?([^:]*): (.+)$", re.S)
_LISTING_FAILED = re.compile(r"^Could not list folder contents: (.+)$", re.S)
_SET_ASIDE = re.compile(
    r"^Set aside after (\d+) failed attempts, tried again later: (.+)$",
    re.S,
)
_ERROR = re.compile(r"^Error: (.+)$", re.S)
_HTTP_ERROR = re.compile(r"^HTTP (\d{3})\b\s*(.*)$", re.S)
_INCOMPLETE_DOWNLOAD = re.compile(r"^Incomplete download\b")


def _strip_legacy_suffix(reason: str) -> str:
    text = reason.strip()
    if text.endswith(LEGACY_RETRY_SUFFIX):
        return text[: -len(LEGACY_RETRY_SUFFIX)].rstrip()
    return text


def classify_skip_reason(
    reason: str,
) -> tuple[SkipReasonCode, SkipReasonParams, bool]:
    """The code, parameters and retry flag a reason text stands for.

    Covers every text the sync writes today and wrote before codes existed,
    including the retry suffix older rows carry. Anything unknown is an
    ``error`` with the text as its detail, never a crash.
    """
    stripped = reason.strip()
    text = _strip_legacy_suffix(stripped)
    retry = text != stripped
    if text == NO_TEXT_LAYER_REASON:
        return "no_text_layer", {}, retry
    if text == EMPTY_CONTENT_REASON:
        return "empty_content", {}, retry
    if text == SCOPE_PATH_UNAVAILABLE_REASON:
        return "scope_path_unavailable", {}, retry
    if text == MISSING_ITEM_ID_REASON:
        return "missing_item_id", {}, retry
    if text == ALREADY_SYNCED_REASON:
        return "unchanged", {}, retry
    if match := _UNSUPPORTED_TYPE.match(text):
        return "unsupported_type", {"label": match.group(1)}, retry
    if match := _FILE_TOO_LARGE.match(text):
        return "file_too_large", {"limit_mb": match.group(1)}, retry
    if match := _EXTRACTION_LIMIT.match(text):
        return "extraction_limit", _extraction_limit_params(match.group(1)), retry
    if match := _REMOVAL_FAILED.match(text):
        params: SkipReasonParams = {"what": match.group(1), "detail": match.group(2)}
        return "removal_failed", params, retry
    if match := _LISTING_FAILED.match(text):
        return "listing_failed", {"detail": match.group(1)}, retry
    if match := _SET_ASIDE.match(text):
        attempts = int(match.group(1))
        return "set_aside", {"attempts": attempts, "detail": match.group(2)}, retry
    if match := _ERROR.match(text):
        return _classify_error(match.group(1)) + (retry,)
    return "error", {"detail": text}, retry


def _extraction_limit_params(limit: str) -> SkipReasonParams:
    if match := _LIMIT_TEXT_BYTES.match(limit):
        return {"limit": "text_bytes", "value": int(match.group(1))}
    if match := _LIMIT_PDF_PAGES.match(limit):
        return {"limit": "pdf_pages", "value": int(match.group(1))}
    for kind, text in _EXTRACTION_LIMIT_TEXT.items():
        if limit == text:
            return {"limit": kind}
    return {"limit": "other", "detail": limit}


def _classify_error(detail: str) -> tuple[SkipReasonCode, SkipReasonParams]:
    if match := _HTTP_ERROR.match(detail):
        return "http_error", {"status": int(match.group(1)), "message": match.group(2)}
    if _INCOMPLETE_DOWNLOAD.match(detail):
        return "incomplete_download", {"detail": detail}
    if detail == PASSWORD_PROTECTED_REASON:
        return "password_protected", {}
    if detail == CORRUPT_FILE_REASON:
        return "corrupt_file", {}
    return "error", {"detail": detail}


def with_code(detail: Mapping[str, Any]) -> SkippedDetail:
    """``detail`` with a code, parameters and retry flag, whatever it was stored with."""
    file = detail.get("file")
    reason = detail.get("reason")
    file = file if isinstance(file, str) else ""
    reason = reason if isinstance(reason, str) else ""
    code = detail.get("code")
    params = detail.get("params")
    if code in SKIP_REASON_CODES and isinstance(params, dict):
        coded: SkippedDetail = {
            "file": file,
            "reason": _strip_legacy_suffix(reason),
            "code": code,
            "params": {
                str(key): value
                for key, value in cast(dict[str, Any], params).items()
                if isinstance(value, (str, int)) and not isinstance(value, bool)
            },
        }
        if detail.get("retry") is True:
            coded["retry"] = True
        return coded
    return skipped(file, reason)


def visible_skip_params(params: Mapping[str, str | int]) -> SkipReasonParams:
    """Parameters with their free text cleaned the way reasons are."""
    return {
        key: user_visible_error(value) if isinstance(value, str) else value
        for key, value in params.items()
    }


# Skips of delta items never placed in the item's scope: older syncs named
# their file, which may lie anywhere in the drive. "Could not remove:" is what
# releases before 2.2 wrote for deleted items, which were never placed either.
_UNPLACED_SKIP_REASONS = (
    "Folder scope path unavailable",
    "Missing item id",
    "Could not remove out-of-scope",
    "Could not remove removed:",
    "Could not remove:",
)


def visible_skip(detail: Mapping[str, Any]) -> SkippedDetail:
    """The detail as served: coded, its text cleaned, unplaced items unnamed."""
    stored = detail.get("reason")
    cleaned = user_visible_error(stored) if isinstance(stored, str) else ""
    coded = with_code({**detail, "reason": cleaned})
    reason = coded["reason"]
    visible: SkippedDetail = {
        "file": "" if reason.startswith(_UNPLACED_SKIP_REASONS) else coded["file"],
        "reason": reason,
        "code": coded.get("code", "error"),
        "params": visible_skip_params(coded.get("params", {})),
    }
    if coded.get("retry"):
        visible["retry"] = True
    return visible
