"""A log describes an exception by its kinds, status code and where it was
raised; its message, which can quote content, is never part of it."""

from eneo.observability.error_log import error_facts


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
