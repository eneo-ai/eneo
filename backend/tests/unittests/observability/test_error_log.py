"""A log describes an exception by its kinds, status code and where it was
raised; its message, which can quote content, is never part of it."""

import json
import logging

import aiohttp
import httpx
import pytest
from aiohttp.client_reqrep import RequestInfo
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from eneo.main.logging import OTELJSONFormatter
from eneo.observability.error_log import error_facts, log_error


class _ProviderError(Exception):
    status_code = 400


def _fail() -> None:
    try:
        raise _ProviderError("the provider echoed: private input")
    except _ProviderError as error:
        raise RuntimeError("wrapped: private input") from error


def test_an_exception_is_described_without_its_messages() -> None:
    try:
        _fail()
    except RuntimeError as error:
        facts = error_facts(error)

    assert "private input" not in repr(facts)
    assert facts["error_type"] == "RuntimeError <- _ProviderError"
    assert facts["error_status"] == 400
    assert str(facts["error_at"]).endswith("in _fail")
    assert any(
        str(location).endswith("in test_an_exception_is_described_without_its_messages")
        for location in facts["error_stack"]  # type: ignore[union-attr]
    )


def test_a_suppressed_context_is_left_out() -> None:
    try:
        try:
            raise ValueError("private input")
        except ValueError:
            raise KeyError("x") from None
    except KeyError as error:
        facts = error_facts(error)

    assert facts["error_type"] == "KeyError"
    assert facts["error_status"] is None


def test_a_logged_error_names_its_kinds_and_place_never_its_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    log = logging.getLogger("tests.error_log")
    try:
        _fail()
    except RuntimeError as error:
        with caplog.at_level(logging.WARNING, logger="tests.error_log"):
            log_error(
                log,
                logging.WARNING,
                "Could not sync knowledge %s",
                "k-1",
                error=error,
                extra={"job_id": "j-1"},
            )

    [record] = caplog.records
    assert record.levelno == logging.WARNING
    assert record.getMessage().startswith(
        "Could not sync knowledge k-1: RuntimeError <- _ProviderError at "
    )
    assert not record.exc_info and not record.stack_info
    assert "private input" not in repr(record.__dict__)
    assert record.__dict__["job_id"] == "j-1"
    assert record.__dict__["error_status"] == 400
    # The record points at the caller, not at the helper.
    assert (
        record.funcName
        == "test_a_logged_error_names_its_kinds_and_place_never_its_text"
    )


_SIGNED_URL = "https://files.example/doc.pdf?tempauth=signed-token"


def _aiohttp_error(status: int) -> aiohttp.ClientResponseError:
    url = URL(_SIGNED_URL)
    return aiohttp.ClientResponseError(
        RequestInfo(url, "GET", CIMultiDictProxy(CIMultiDict()), url),
        (),
        status=status,
        message="private reason",
    )


def _httpx_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", _SIGNED_URL)
    response = httpx.Response(
        status, request=request, extensions={"reason_phrase": b"private reason"}
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        return error
    raise AssertionError("raise_for_status did not raise")


def _raised_from(
    error: Exception, wrapper: type[Exception] = RuntimeError
) -> Exception:
    try:
        raise wrapper("wrapped: private input") from error
    except wrapper as raised:
        return raised


@pytest.mark.parametrize(
    ("error", "status"),
    [
        pytest.param(_aiohttp_error(403), 403, id="aiohttp"),
        pytest.param(_httpx_error(503), 503, id="httpx"),
        pytest.param(_raised_from(_aiohttp_error(403)), 403, id="aiohttp-as-cause"),
        pytest.param(_aiohttp_error(0), None, id="aiohttp-without-status"),
        # The first status in the chain wins, outermost first.
        pytest.param(
            _raised_from(_httpx_error(503), _ProviderError),
            400,
            id="outer-status-code-before-httpx-cause",
        ),
    ],
)
def test_an_http_client_error_is_logged_with_its_status_never_its_text_or_url(
    caplog: pytest.LogCaptureFixture, error: Exception, status: int | None
) -> None:
    log = logging.getLogger("tests.error_log")
    with caplog.at_level(logging.WARNING, logger="tests.error_log"):
        log_error(log, logging.WARNING, "Could not download a file", error=error)

    [record] = caplog.records
    formatted = OTELJSONFormatter().format(record)
    assert json.loads(formatted)["attributes"].get("error_status") == status
    # The error's message, reason phrase and URL; none of them can be part of
    # a file path in the recorded stack.
    for text in (
        "wrapped: private input",
        "private reason",
        "files.example",
        "signed-token",
    ):
        assert text not in formatted
        assert text not in repr(record.__dict__)
