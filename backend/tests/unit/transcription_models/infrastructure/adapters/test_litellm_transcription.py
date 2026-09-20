"""Chunk windows from the LiteLLM transcription adapter."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.flows.runtime import step_deadline as step_deadline_module
from eneo.flows.runtime.step_deadline import StepDeadline, step_deadline_scope
from eneo.main.exceptions import TypedIOValidationException
from eneo.transcription_models.infrastructure.adapters import litellm_transcription
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    LiteLLMTranscriptionAdapter,
    TranscriptSegment,
)

TRANSPORT = (
    "eneo.transcription_models.infrastructure.adapters.litellm_transcription."
    "litellm_transport.atranscription"
)


class _CredentialResolverStub:
    provider_id = "provider-id"
    provider_type = "openai"

    def get_api_key(self, *, required: bool = False) -> str:
        return "test-key"

    def get_credential_field(self, *, field: str, required: bool = False) -> str | None:
        return None


class _Observer:
    def __init__(self) -> None:
        self.started_requests: list[object] = []
        self.completed_calls: list[UUID] = []
        self.rejected_reasons: list[str] = []
        self.unknown_reasons: list[str] = []

    async def started(self, request: object) -> UUID:
        self.started_requests.append(request)
        return uuid4()

    async def completed(self, call_id: UUID, result: object) -> None:
        self.completed_calls.append(call_id)

    async def rejected(self, call_id: UUID, reason: str) -> None:
        self.rejected_reasons.append(reason)

    async def outcome_unknown(self, call_id: UUID, reason: str) -> None:
        self.unknown_reasons.append(reason)


def _adapter() -> LiteLLMTranscriptionAdapter:
    return LiteLLMTranscriptionAdapter(
        model=SimpleNamespace(name="Whisper", model_name="whisper-1"),
        credential_resolver=_CredentialResolverStub(),
        provider_type="openai",
    )


def _audio(tmp_path: Path, chunk_seconds: list[float], monkeypatch) -> SimpleNamespace:
    """A stand-in for AudioFile that splits into pre-measured chunks."""
    paths = []
    for index, seconds in enumerate(chunk_seconds):
        path = tmp_path / f"chunk-{index}.wav"
        path.write_bytes(f"chunk {index}".encode())
        paths.append(path)
    measured = {path: seconds for path, seconds in zip(paths, chunk_seconds)}
    monkeypatch.setattr(
        litellm_transcription, "_measure_seconds", lambda p: measured[p]
    )

    @asynccontextmanager
    async def asplit_file(*, seconds: int):
        async def chunks():
            for path in paths:
                yield path

        yield chunks()

    return SimpleNamespace(duration=sum(chunk_seconds), asplit_file=asplit_file)


async def test_segments_are_the_measured_chunk_windows(monkeypatch, tmp_path) -> None:
    calls: list[dict[str, object]] = []
    texts = iter([" hej ", "du"])

    async def fake(**kwargs):
        calls.append(kwargs)
        # Provider timings are deliberately nonsense; they must not be used.
        return SimpleNamespace(
            text=next(texts),
            words=[{"word": "hej", "start": 0.0, "end": 900.0}],
            segments=[{"text": "hej", "start": 0.0, "end": 900.0}],
        )

    monkeypatch.setattr(TRANSPORT, AsyncMock(side_effect=fake))
    audio = _audio(tmp_path, [300.7, 120.0], monkeypatch)

    result = await _adapter().get_text_from_file(audio)  # type: ignore[arg-type]

    # Provider timestamps are never requested.
    assert all("response_format" not in call for call in calls)
    assert all("timestamp_granularities" not in call for call in calls)
    # Chunk windows accumulate the measured lengths, including fractional seconds.
    assert result.segments == (
        TranscriptSegment("hej", 0.0, 300.7),
        TranscriptSegment("du", 300.7, 420.7),
    )
    assert result.text.startswith("### 0:00 - 5:00\n\n hej ")


async def test_chunk_headings_follow_the_measured_offsets(
    monkeypatch, tmp_path
) -> None:
    """Transcript headings use the same measured offsets as their segments."""
    texts = iter(["a", "b", "c"])

    async def fake(**kwargs):
        return SimpleNamespace(text=next(texts))

    monkeypatch.setattr(TRANSPORT, AsyncMock(side_effect=fake))
    audio = _audio(tmp_path, [300.7, 300.7, 60.0], monkeypatch)

    result = await _adapter().get_text_from_file(audio)  # type: ignore[arg-type]

    assert result.text == (
        "### 0:00 - 5:00\n\na\n\n### 5:00 - 10:01\n\nb\n\n### 10:01 - 11:01\n\nc"
    )
    assert result.segments == (
        TranscriptSegment("a", 0.0, 300.7),
        TranscriptSegment("b", 300.7, 601.4),
        TranscriptSegment("c", 601.4, 661.4),
    )


async def test_no_chunk_is_sent_after_the_step_budget_expires(
    monkeypatch, tmp_path
) -> None:
    """Inside a flow attempt the adapter refuses the next chunk once the
    published budget is spent, even inside the executor's backstop grace."""
    clock = {"now": 0.0}
    monkeypatch.setattr(step_deadline_module, "_now", lambda: clock["now"])

    async def fake(**kwargs):
        clock["now"] += 1.0
        return SimpleNamespace(text="ord")

    transport = AsyncMock(side_effect=fake)
    monkeypatch.setattr(TRANSPORT, transport)
    audio = _audio(tmp_path, [300.0, 300.0, 300.0], monkeypatch)

    with step_deadline_scope(StepDeadline.start(1.5), step_order=2):
        with pytest.raises(TypedIOValidationException) as exc_info:
            await _adapter().get_text_from_file(audio)  # type: ignore[arg-type]

    assert exc_info.value.code == "flow_step_timeout"
    assert exc_info.value.step_phase.value == "transcription"
    assert "Step 2: " in str(exc_info.value)
    assert "transcription chunk 3" in str(exc_info.value)
    assert transport.await_count == 2


async def test_receipt_written_as_the_budget_runs_out_is_settled_not_sent(
    monkeypatch, tmp_path
) -> None:
    """Writing the receipt can consume the last of the budget; the request is
    then refused, and the receipt is settled as a known refusal instead of
    lingering as an open call."""
    clock = {"now": 0.0}
    monkeypatch.setattr(step_deadline_module, "_now", lambda: clock["now"])
    transport = AsyncMock(return_value=SimpleNamespace(text="ord"))
    monkeypatch.setattr(TRANSPORT, transport)
    audio = _audio(tmp_path, [300.0], monkeypatch)

    class _SlowReceipt(_Observer):
        async def started(self, request: object) -> UUID:
            clock["now"] = 2.0  # the receipt transaction ate the budget
            return await super().started(request)

    observer = _SlowReceipt()
    with step_deadline_scope(StepDeadline.start(1.0), step_order=1):
        with pytest.raises(TypedIOValidationException) as exc_info:
            await _adapter().get_text_from_file(audio, observer=observer)  # type: ignore[arg-type]

    assert exc_info.value.code == "flow_step_timeout"
    assert exc_info.value.step_phase.value == "transcription"
    assert "(not sent)" in str(exc_info.value)
    assert transport.await_count == 0
    assert len(observer.started_requests) == 1
    assert observer.rejected_reasons == ["budget_exhausted"]


async def test_cancelled_request_keeps_the_in_flight_fact_for_the_timeout_message(
    monkeypatch, tmp_path
) -> None:
    """When the executor's backstop cancels a request mid-flight, the provider
    may still complete it; the published fact must survive the adapter's
    cleanup so the step's timeout message carries the disclosure."""

    async def hang(**kwargs):
        await asyncio.sleep(10)

    monkeypatch.setattr(TRANSPORT, AsyncMock(side_effect=hang))
    audio = _audio(tmp_path, [300.0], monkeypatch)
    observer = _Observer()

    with step_deadline_scope(StepDeadline.start(30.0), step_order=1) as scope:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await _adapter().get_text_from_file(audio, observer=observer)  # type: ignore[arg-type]
        assert scope.provider_request_in_flight is False
        assert scope.provider_outcome_unresolved is True
        assert (
            scope.deadline.timeout_error(
                step_order=1, phase="transcription"
            ).provider_work_may_have_completed
            is True
        )


async def test_settled_request_clears_the_in_flight_fact(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(TRANSPORT, AsyncMock(return_value=SimpleNamespace(text="ord")))
    audio = _audio(tmp_path, [300.0], monkeypatch)

    with step_deadline_scope(StepDeadline.start(30.0), step_order=1) as scope:
        await _adapter().get_text_from_file(audio)  # type: ignore[arg-type]
        assert scope.provider_request_in_flight is False


async def test_timed_out_request_keeps_unknown_outcome_on_budget_refusal(
    monkeypatch, tmp_path
) -> None:
    clock = {"now": 0.0}
    monkeypatch.setattr(step_deadline_module, "_now", lambda: clock["now"])
    monkeypatch.setattr(
        LiteLLMTranscriptionAdapter._transcribe_chunk.retry, "sleep", AsyncMock()
    )

    async def timed_out(**kwargs):
        clock["now"] += kwargs["timeout"]
        raise TimeoutError("Request timed out after dispatch")

    transport = AsyncMock(side_effect=timed_out)
    monkeypatch.setattr(TRANSPORT, transport)
    audio = _audio(tmp_path, [300.0], monkeypatch)
    observer = _Observer()
    with step_deadline_scope(StepDeadline.start(30), step_order=1):
        with pytest.raises(TypedIOValidationException) as exc_info:
            await _adapter().get_text_from_file(audio, observer=observer)

    transport.assert_awaited_once()
    assert len(observer.started_requests) == 1
    assert observer.unknown_reasons == ["provider_error"]
    assert observer.completed_calls == []
    assert observer.rejected_reasons == []
    assert exc_info.value.code == "flow_step_timeout"
    assert exc_info.value.provider_work_may_have_completed is True


async def test_successful_retry_does_not_resolve_an_earlier_unknown_request(
    monkeypatch, tmp_path
) -> None:
    clock = {"now": 0.0}
    monkeypatch.setattr(step_deadline_module, "_now", lambda: clock["now"])
    monkeypatch.setattr(
        LiteLLMTranscriptionAdapter._transcribe_chunk.retry, "sleep", AsyncMock()
    )
    attempts = 0

    async def transcribe(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            clock["now"] = 1.0
            raise TimeoutError("Request timed out after dispatch")
        clock["now"] = 30.0
        return SimpleNamespace(text="ord")

    transport = AsyncMock(side_effect=transcribe)
    monkeypatch.setattr(TRANSPORT, transport)
    audio = _audio(tmp_path, [300.0, 300.0], monkeypatch)
    observer = _Observer()
    with step_deadline_scope(StepDeadline.start(30), step_order=1):
        with pytest.raises(TypedIOValidationException) as exc_info:
            await _adapter().get_text_from_file(audio, observer=observer)

    assert transport.await_count == 2
    assert len(observer.started_requests) == 2
    assert observer.unknown_reasons == ["provider_error"]
    assert len(observer.completed_calls) == 1
    assert observer.rejected_reasons == []
    assert exc_info.value.code == "flow_step_timeout"
    assert exc_info.value.provider_work_may_have_completed is True


async def test_cancelled_chunk_request_is_not_retried(monkeypatch, tmp_path) -> None:
    """A cancellation (the step's budget ran out) must propagate without the
    retry policy sending another request."""
    transport = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(TRANSPORT, transport)
    audio = _audio(tmp_path, [300.0, 300.0], monkeypatch)

    with pytest.raises(asyncio.CancelledError):
        await _adapter().get_text_from_file(audio)  # type: ignore[arg-type]

    assert transport.await_count == 1


async def test_silent_chunks_keep_their_place_but_emit_no_segment(
    monkeypatch, tmp_path
) -> None:
    texts = iter(["hej", "   ", "du"])

    async def fake(**kwargs):
        return SimpleNamespace(text=next(texts))

    monkeypatch.setattr(TRANSPORT, AsyncMock(side_effect=fake))
    audio = _audio(tmp_path, [300.0, 300.0, 60.0], monkeypatch)

    result = await _adapter().get_text_from_file(audio)  # type: ignore[arg-type]

    assert result.segments == (
        TranscriptSegment("hej", 0.0, 300.0),
        TranscriptSegment("du", 600.0, 660.0),
    )


async def test_transcript_with_no_text_has_no_segments(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(TRANSPORT, AsyncMock(return_value=SimpleNamespace(text="")))
    audio = _audio(tmp_path, [10.0], monkeypatch)

    result = await _adapter().get_text_from_file(audio)  # type: ignore[arg-type]

    assert result.segments == ()


async def test_transcription_request_uses_remaining_attempt_budget(
    monkeypatch, tmp_path
):
    clock = {"now": 0.0}
    monkeypatch.setattr(step_deadline_module, "_now", lambda: clock["now"])
    transport = AsyncMock(return_value=SimpleNamespace(text="ord"))
    monkeypatch.setattr(TRANSPORT, transport)
    audio = _audio(tmp_path, [300.0], monkeypatch)
    with step_deadline_scope(StepDeadline.start(7200), step_order=1):
        clock["now"] = 100.0
        await _adapter().get_text_from_file(audio)
    assert transport.await_args.kwargs["timeout"] == 7100
