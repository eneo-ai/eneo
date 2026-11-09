"""A log describes an exception by its kinds, status code and where it was
raised; its message, which can quote content, is never part of it."""

import logging

import pytest

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
