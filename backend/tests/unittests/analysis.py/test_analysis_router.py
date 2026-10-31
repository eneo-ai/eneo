import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    ResponseType,
    TokenUsage,
)
from eneo.analysis.analysis import AskAnalysis
from eneo.analysis.analysis_router import (
    _normalize_datetime_range,
    ask_question_about_questions,
    ask_unified_questions_about_questions,
    get_metadata_aggregated,
)
from eneo.analysis.analysis_service import NO_QUESTIONS_ANSWER
from eneo.main.exceptions import BadRequestException, InternalServerException


def test_both_dates_none_falls_back_to_days_since():
    """When both dates are None, falls back to days_since default range."""
    from_date, to_date = _normalize_datetime_range(
        from_date=None, to_date=None, days_since=30
    )

    assert to_date.tzinfo == timezone.utc
    assert from_date.tzinfo == timezone.utc
    assert (to_date - from_date).days == 30


def test_only_from_date_provided():
    """When only from_date is provided, to_date defaults to now."""
    explicit_from = datetime(2026, 1, 1, tzinfo=timezone.utc)
    from_date, to_date = _normalize_datetime_range(
        from_date=explicit_from, to_date=None, days_since=30
    )

    assert from_date == explicit_from
    assert to_date.tzinfo == timezone.utc
    # to_date should be approximately now
    assert abs((datetime.now(timezone.utc) - to_date).total_seconds()) < 5


def test_only_to_date_provided():
    """When only to_date is provided, from_date defaults to now - days_since."""
    # Use a future date so from_date (now - 7 days) is still before to_date
    explicit_to = datetime.now(timezone.utc) + timedelta(days=1)
    from_date, to_date = _normalize_datetime_range(
        from_date=None, to_date=explicit_to, days_since=7
    )

    assert to_date == explicit_to
    assert from_date.tzinfo == timezone.utc
    # from_date should be approximately 7 days before now
    expected_from = datetime.now(timezone.utc) - timedelta(days=7)
    assert abs((from_date - expected_from).total_seconds()) < 5


def test_from_date_after_to_date_raises():
    """When from_date > to_date, raises BadRequestException."""
    with pytest.raises(BadRequestException, match="from_date must be before to_date"):
        _normalize_datetime_range(
            from_date=datetime(2026, 2, 10, tzinfo=timezone.utc),
            to_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            days_since=30,
        )


def test_naive_datetimes_get_utc():
    """Naive datetimes get UTC tzinfo attached."""
    from_date, to_date = _normalize_datetime_range(
        from_date=datetime(2026, 1, 1),
        to_date=datetime(2026, 2, 1),
        days_since=30,
    )

    assert from_date.tzinfo == timezone.utc
    assert to_date.tzinfo == timezone.utc
    assert from_date == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert to_date == datetime(2026, 2, 1, tzinfo=timezone.utc)


def test_both_dates_provided_passthrough():
    """When both dates are provided, they pass through with tz normalization."""
    explicit_from = datetime(2026, 1, 15, tzinfo=timezone.utc)
    explicit_to = datetime(2026, 2, 15, tzinfo=timezone.utc)
    from_date, to_date = _normalize_datetime_range(
        from_date=explicit_from, to_date=explicit_to, days_since=30
    )

    assert from_date == explicit_from
    assert to_date == explicit_to


@pytest.mark.parametrize("time_zone", ["Not/AZone", "/UTC", ""])
async def test_aggregated_metadata_rejects_invalid_zone_before_reading(time_zone):
    container = MagicMock()
    with pytest.raises(BadRequestException, match="Invalid IANA time zone"):
        await get_metadata_aggregated(container=container, time_zone=time_zone)
    container.analysis_service.assert_not_called()


@pytest.fixture(
    params=[ask_question_about_questions, ask_unified_questions_about_questions]
)
def analysis_endpoint(request):
    return request.param


async def _analysis_response(endpoint, chunks, closed):
    async def completion_stream():
        try:
            for chunk in chunks:
                yield chunk
        finally:
            closed.append(True)

    service = AsyncMock()
    result = SimpleNamespace(completion=completion_stream())
    service.ask_question_on_questions.return_value = result
    service.unified_ask_question_on_questions.return_value = result
    service.should_queue_unified_analysis_job.return_value = False
    container = MagicMock()
    container.analysis_service.return_value = service
    return await endpoint(
        assistant_id=uuid4(),
        ask_analysis=AskAnalysis(question="What are the trends?", stream=True),
        container=container,
    )


def _body(send):
    return b"".join(call.args[0].get("body", b"") for call in send.call_args_list)


async def test_analysis_provider_error_fails_after_partial_output_and_closes_source(
    analysis_endpoint,
):
    closed = []
    response = await _analysis_response(
        analysis_endpoint,
        [
            Completion(text="Partial analysis"),
            Completion(
                text="",
                error="private-provider-detail",
                response_type=ResponseType.ERROR,
                stop=True,
            ),
        ],
        closed,
    )
    send = AsyncMock()
    with pytest.raises(InternalServerException) as error:
        await response.stream_response(send)
    assert _body(send) == b'data: {"answer":"Partial analysis"}\r\n\r\n'
    assert "private-provider-detail" not in str(error.value)
    assert not any(
        call.args[0]["type"] == "http.response.body" and not call.args[0]["more_body"]
        for call in send.call_args_list
    )
    assert closed == [True]


@pytest.mark.parametrize("terminal_text", ["", "First second"])
async def test_analysis_terminal_usage_does_not_repeat_streamed_text(
    analysis_endpoint, terminal_text
):
    closed = []
    response = await _analysis_response(
        analysis_endpoint,
        [
            Completion(text="First"),
            Completion(text=" second"),
            Completion(
                text=terminal_text,
                stop=True,
                usage=TokenUsage(prompt_tokens=10, completion_tokens=2),
            ),
        ],
        closed,
    )
    send = AsyncMock()
    await response.stream_response(send)
    assert _body(send) == (
        b'data: {"answer":"First"}\r\n\r\ndata: {"answer":" second"}\r\n\r\n'
    )
    assert send.call_args.args[0]["more_body"] is False
    assert closed == [True]


async def test_analysis_stream_emits_the_terminal_no_questions_answer(
    analysis_endpoint,
):
    closed = []
    response = await _analysis_response(
        analysis_endpoint,
        [Completion(text=NO_QUESTIONS_ANSWER, stop=True)],
        closed,
    )
    send = AsyncMock()
    await response.stream_response(send)
    expected = json.dumps(
        {"answer": NO_QUESTIONS_ANSWER}, separators=(",", ":")
    ).encode()
    assert _body(send) == b"data: " + expected + b"\r\n\r\n"
    assert send.call_args.args[0] == {
        "type": "http.response.body",
        "body": b"",
        "more_body": False,
    }
    assert closed == [True]
