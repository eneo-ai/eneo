"""Skip reasons: every text the sync writes, or wrote, has a code the UIs translate."""

import aiohttp
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from eneo.integration.domain.skip_reasons import (
    ALREADY_SYNCED_REASON,
    CORRUPT_FILE_REASON,
    EMPTY_CONTENT_REASON,
    LEGACY_RETRY_SUFFIX,
    MISSING_ITEM_ID_REASON,
    NO_TEXT_LAYER_REASON,
    PASSWORD_PROTECTED_REASON,
    SCOPE_PATH_UNAVAILABLE_REASON,
    SKIP_REASON_CODES,
    classify_skip_reason,
    error_reason,
    error_skipped,
    extraction_limit_reason,
    file_too_large_reason,
    reason_text,
    set_aside_reason,
    skipped,
    skipped_by_code,
    unsupported_type_reason,
    visible_skip_params,
    with_code,
)
from eneo.integration.presentation.models import IntegrationSkippedDocument

# Every text the sync composes today, with the code and parameters it stands for.
WRITTEN_TEXTS = [
    pytest.param(
        unsupported_type_reason("legacy Word .doc, save as .docx"),
        "unsupported_type",
        {"label": "legacy Word .doc, save as .docx"},
        id="unsupported",
    ),
    pytest.param(NO_TEXT_LAYER_REASON, "no_text_layer", {}, id="no-text-layer"),
    pytest.param(EMPTY_CONTENT_REASON, "empty_content", {}, id="empty"),
    pytest.param(
        file_too_large_reason(50 * 1024 * 1024),
        "file_too_large",
        {"limit_mb": "50"},
        id="too-large",
    ),
    pytest.param(
        file_too_large_reason(1_500_000),
        "file_too_large",
        {"limit_mb": "1.43051"},
        id="too-large-fraction",
    ),
    pytest.param(
        extraction_limit_reason("2000000 bytes of text"),
        "extraction_limit",
        {"limit": "text_bytes", "value": 2000000},
        id="limit-text",
    ),
    pytest.param(
        extraction_limit_reason("1000 PDF pages"),
        "extraction_limit",
        {"limit": "pdf_pages", "value": 1000},
        id="limit-pages",
    ),
    pytest.param(
        extraction_limit_reason("document resource limit"),
        "extraction_limit",
        {"limit": "resource"},
        id="limit-resource",
    ),
    pytest.param(
        extraction_limit_reason("extraction deadline"),
        "extraction_limit",
        {"limit": "deadline"},
        id="limit-deadline",
    ),
    pytest.param(
        extraction_limit_reason("text output limit"),
        "extraction_limit",
        {"limit": "output"},
        id="limit-output",
    ),
    pytest.param(
        error_reason("Incomplete download of 'a.docx' (1 of 2 bytes)"),
        "incomplete_download",
        {"detail": "Incomplete download of 'a.docx' (1 of 2 bytes)"},
        id="incomplete",
    ),
    pytest.param(
        error_reason(PASSWORD_PROTECTED_REASON), "password_protected", {}, id="password"
    ),
    pytest.param(error_reason(CORRUPT_FILE_REASON), "corrupt_file", {}, id="corrupt"),
    pytest.param(
        error_reason("HTTP 403 Forbidden"),
        "http_error",
        {"status": 403, "message": "Forbidden"},
        id="http",
    ),
    pytest.param(
        error_reason("HTTP 410"),
        "http_error",
        {"status": 410, "message": ""},
        id="http-no-reason",
    ),
    pytest.param(
        error_reason("Cache service error"),
        "error",
        {"detail": "Cache service error"},
        id="error",
    ),
    pytest.param(
        "Could not remove out-of-scope: Database error",
        "removal_failed",
        {"what": "out-of-scope", "detail": "Database error"},
        id="removal",
    ),
    pytest.param(
        "Could not list folder contents: HTTP 503 Service Unavailable",
        "listing_failed",
        {"detail": "HTTP 503 Service Unavailable"},
        id="listing",
    ),
    pytest.param(
        SCOPE_PATH_UNAVAILABLE_REASON, "scope_path_unavailable", {}, id="scope-path"
    ),
    pytest.param(MISSING_ITEM_ID_REASON, "missing_item_id", {}, id="missing-id"),
    pytest.param(
        set_aside_reason(3, error_reason("HTTP 502 Bad Gateway")),
        "set_aside",
        {"attempts": 3, "detail": "Error: HTTP 502 Bad Gateway"},
        id="set-aside",
    ),
]


# Texts only older releases wrote; rows holding them are classified when served.
LEGACY_TEXTS = [
    pytest.param(ALREADY_SYNCED_REASON, "unchanged", {}, id="already-synced-2-2"),
]


@pytest.mark.parametrize(("text", "code", "params"), WRITTEN_TEXTS + LEGACY_TEXTS)
def test_every_written_text_has_its_code(text, code, params):
    assert classify_skip_reason(text) == (code, params, False)


@pytest.mark.parametrize(("text", "code", "params"), WRITTEN_TEXTS + LEGACY_TEXTS)
def test_the_text_of_a_code_classifies_back_to_it(text, code, params):
    """The renderer and the classifier agree, so coded and legacy rows read alike."""
    assert reason_text(code, params) == text


def test_every_code_is_written_by_some_text():
    assert {
        code for _, code, _ in (p.values for p in WRITTEN_TEXTS + LEGACY_TEXTS)
    } == set(SKIP_REASON_CODES)


def test_an_unchanged_file_from_2_2_is_not_served_as_an_error():
    """2.2.x delta syncs listed files they had already processed as skipped."""
    served = IntegrationSkippedDocument.model_validate(
        {"file": "Protokoll.docx", "reason": ALREADY_SYNCED_REASON}
    )

    assert (served.code, served.params, served.retry) == ("unchanged", {}, False)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (
            error_reason("HTTP 503 Service Unavailable") + LEGACY_RETRY_SUFFIX,
            "http_error",
        ),
        (
            "Could not remove unextractable: db down" + LEGACY_RETRY_SUFFIX,
            "removal_failed",
        ),
        (NO_TEXT_LAYER_REASON + LEGACY_RETRY_SUFFIX, "no_text_layer"),
    ],
)
def test_the_retry_suffix_of_older_rows_becomes_the_flag(text, code):
    classified, _, retry = classify_skip_reason(text)

    assert (classified, retry) == (code, True)
    assert skipped("a.docx", text) == {
        "file": "a.docx",
        "reason": text[: -len(LEGACY_RETRY_SUFFIX)],
        "code": code,
        "params": classify_skip_reason(text)[1],
        "retry": True,
    }


@pytest.mark.parametrize(
    "text",
    ["", "   ", "Something new the sync might say", "Error: "],
)
def test_unknown_text_is_an_error_with_the_text_as_detail(text):
    assert classify_skip_reason(text)[0] == "error"


def test_a_removal_written_before_2_2_names_no_kind():
    assert classify_skip_reason("Could not remove: database unavailable") == (
        "removal_failed",
        {"what": "", "detail": "database unavailable"},
        False,
    )


def test_skipped_by_code_renders_the_text_and_keeps_the_parameters():
    detail = skipped_by_code("X", "listing_failed", detail="HTTP 429 Too Many Requests")

    assert detail == {
        "file": "X",
        "reason": "Could not list folder contents: HTTP 429 Too Many Requests",
        "code": "listing_failed",
        "params": {"detail": "HTTP 429 Too Many Requests"},
    }
    assert skipped_by_code("X", "missing_item_id", retry=True)["retry"] is True


def test_error_skipped_describes_exceptions_by_their_kind():
    refused = aiohttp.ClientResponseError(
        request_info=None,
        history=(),
        status=404,
        message="Not Found",  # type: ignore[arg-type]
    )

    assert error_skipped("a.docx", refused) == {
        "file": "a.docx",
        "reason": "Error: HTTP 404 Not Found",
        "code": "http_error",
        "params": {"status": 404, "message": "Not Found"},
    }
    assert (
        error_skipped(
            "a.docx", RedisConnectionError("Error 111 connecting to redis:6379")
        )["code"]
        == "error"
    )


def test_with_code_trusts_a_coded_detail_and_classifies_a_bare_one():
    coded = {
        "file": "a.docx",
        "reason": "whatever was stored",
        "code": "http_error",
        "params": {"status": 403, "message": "Forbidden", "ignored": None},
        "retry": True,
    }
    assert with_code(coded) == {
        "file": "a.docx",
        "reason": "whatever was stored",
        "code": "http_error",
        "params": {"status": 403, "message": "Forbidden"},
        "retry": True,
    }
    assert with_code({"file": None, "reason": EMPTY_CONTENT_REASON}) == {
        "file": "",
        "reason": EMPTY_CONTENT_REASON,
        "code": "empty_content",
        "params": {},
    }
    assert (
        with_code({"file": "x", "reason": None, "code": "not-a-code"})["code"]
        == "error"
    )


def test_visible_params_clean_free_text_like_reasons():
    params = visible_skip_params(
        {"detail": "connect to host db.internal:5432 failed", "status": 503}
    )

    assert params == {"detail": "connect to host [redacted] failed", "status": 503}
