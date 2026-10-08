from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import Iterator
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest

from eneo.files.transcript import (
    TranscriptSegment,
    TranscriptWord,
)
from eneo.flows.runtime import remote_transcription
from eneo.flows.runtime import step_deadline as step_deadline_module
from eneo.flows.runtime.remote_transcription import (
    RemoteFlowTranscriber,
    RemoteTranscriptionCancelledException,
    build_remote_flow_transcriber,
)
from eneo.flows.runtime.run_cancellation import (
    FlowStepCancelledError,
    run_cancel_probe_scope,
)
from eneo.flows.runtime.step_deadline import (
    StepDeadline,
    require_step_budget,
    step_deadline_scope,
)
from eneo.flows.runtime.transcription import TranscriptionProviderError
from eneo.main.config import Settings
from eneo.main.exceptions import (
    APIKeyNotConfiguredException,
    OpenAIException,
    ProviderRejectedRequestException,
    TypedIOValidationException,
)
from eneo.model_providers.domain.provider_call_observer import (
    TranscriptionCallRequestFacts,
)
from eneo.transcription_services import client as client_module
from tests.unit.main.test_config_flow_transcription_service import make_settings
from tests.unit.transcription_services.scripted_service import (
    JOB_ID,
    RESULT_BODY,
    ScriptedService,
    accepted,
    make_client,
    status,
)
from tests.unittests.flows import audio_spool_test_support

spool_contract = audio_spool_test_support.spool_contract

PROVIDER_TARGETS = [
    pytest.param("http://tolka.test", "external/tolka.test", id="standard"),
    pytest.param(
        "https://dummy-user:dummy-url-secret@tolka.test:8443",
        "external/tolka.test:8443",
        id="private-userinfo",
    ),
    pytest.param("http://[::1]:8100", "external/[::1]:8100", id="ipv6-port"),
]


@pytest.fixture
def remote_logs(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    logger = remote_transcription.logger
    previous_level = logger.level
    logger.addHandler(caplog.handler)
    logger.setLevel(logging.INFO)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)
        logger.setLevel(previous_level)


def make_transcriber(
    service: ScriptedService,
    *,
    base_url: str = "http://tolka.test",
    poll_interval_seconds: float = 0.001,
    result_timeout_seconds: float = 5.0,
) -> RemoteFlowTranscriber:
    return RemoteFlowTranscriber(
        make_client(
            service, base_url=base_url, result_timeout_seconds=result_timeout_seconds
        ),
        poll_interval_seconds=poll_interval_seconds,
    )


class RecordingObserver:
    operation_scope = "tenant/run/step/attempt-1"

    def __init__(self) -> None:
        self.started_facts: list[object] = []
        self.completed_calls: list[tuple[UUID, object]] = []
        self.rejected_calls: list[tuple[UUID, str]] = []
        self.unknown_calls: list[tuple[UUID, str]] = []
        self.accepted_calls: list[tuple[UUID, str]] = []

    async def accepted(self, call_id: UUID, provider_response_id: str) -> None:
        self.accepted_calls.append((call_id, provider_response_id))

    async def started(self, request: object) -> UUID:
        self.started_facts.append(request)
        return uuid4()

    async def completed(self, call_id: UUID, result: object) -> None:
        self.completed_calls.append((call_id, result))

    async def rejected(self, call_id: UUID, reason: str) -> None:
        self.rejected_calls.append((call_id, reason))

    async def outcome_unknown(self, call_id: UUID, reason: str) -> None:
        self.unknown_calls.append((call_id, reason))


async def audio_file(spool_contract, blob: bytes = b"fake-mp3-bytes"):
    return await spool_contract.spool(
        SimpleNamespace(
            id=UUID(int=1), name="meeting.mp3", mimetype="audio/mpeg", blob=blob
        )
    )


@pytest.mark.parametrize("base_url,expected_model", PROVIDER_TARGETS)
async def test_accepted_job_is_recorded_before_the_first_poll(
    spool_contract, base_url: str, expected_model: str
) -> None:
    # Mutant: configured URL userinfo reaches observable provider-call facts.
    observer = RecordingObserver()

    class Service(ScriptedService):
        def handler(self, request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                assert len(observer.accepted_calls) == 1
                assert observer.accepted_calls[0][1] == JOB_ID
            return super().handler(request)

    service = Service(
        submit_responses=[accepted()],
        status_responses=[status("completed")],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )
    await make_transcriber(service, base_url=base_url).transcribe(
        await audio_file(spool_contract),
        SimpleNamespace(),
        observer=observer,
        file_id=UUID(int=1),
    )
    assert observer.completed_calls[0][0] == observer.accepted_calls[0][0]
    [facts] = observer.started_facts
    assert isinstance(facts, TranscriptionCallRequestFacts)
    assert facts.requested_model == expected_model


@pytest.mark.parametrize("error", [httpx.WriteError, httpx.ReadTimeout])
async def test_lost_submission_response_resubmits_once_with_same_key(
    spool_contract, error
):
    class Service(ScriptedService):
        def handler(self, request):
            if request.method == "POST" and self.submit_count == 0:
                self.requests.append(request)
                request.read()
                raise error("response lost", request=request)
            return super().handler(request)

    service = Service(
        submit_responses=[accepted(), accepted()],
        status_responses=[status("completed")],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )
    observer = RecordingObserver()
    await make_transcriber(service).transcribe(
        await audio_file(spool_contract),
        SimpleNamespace(),
        observer=observer,
        file_id=UUID(int=1),
    )
    submits = [request for request in service.requests if request.method == "POST"]
    assert len(submits) == 2
    assert (
        submits[0].headers["Idempotency-Key"] == submits[1].headers["Idempotency-Key"]
    )
    assert len(service.submit_responses) == 1
    assert len(observer.started_facts) == 1
    assert len(observer.accepted_calls) == 1
    assert observer.unknown_calls == []


@pytest.mark.parametrize("refusal", [429, 503])
@pytest.mark.parametrize(
    "retry_after, expected_wait",
    [
        ("2", 2),
        ("Sun, 20 Sep 2026 10:00:02 GMT", 2),
        ("0", 1),
        ("Sun, 20 Sep 2026 09:59:00 GMT", 1),
    ],
)
async def test_admission_wait_honours_retry_after(
    spool_contract, refusal, retry_after, expected_wait, monkeypatch
):
    clock = {"now": 0.0}
    waits = []

    async def sleep(delay):
        waits.append(delay)
        clock["now"] += delay

    monkeypatch.setattr(step_deadline_module, "_now", lambda: clock["now"])
    monkeypatch.setattr(remote_transcription.asyncio, "sleep", sleep)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 20, 10, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(client_module, "datetime", Clock)
    monkeypatch.setattr(remote_transcription.random, "uniform", lambda *_: 1.0)
    service = ScriptedService(
        submit_responses=[
            httpx.Response(refusal, headers={"Retry-After": retry_after}),
            accepted(),
        ],
        status_responses=[status("completed")],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )
    observer = RecordingObserver()
    with step_deadline_scope(StepDeadline.start(10), step_order=1):
        await make_transcriber(service, poll_interval_seconds=1).transcribe(
            await audio_file(spool_contract),
            SimpleNamespace(),
            observer=observer,
            file_id=UUID(int=1),
        )
    assert sum(waits) == expected_wait
    assert service.submit_count == 2
    assert len(observer.started_facts) == 1
    assert observer.unknown_calls == []


async def test_admission_deadline_records_known_refusal(spool_contract, monkeypatch):
    clock = {"now": 0.0}

    async def sleep(delay):
        clock["now"] += delay

    monkeypatch.setattr(step_deadline_module, "_now", lambda: clock["now"])
    monkeypatch.setattr(remote_transcription.asyncio, "sleep", sleep)
    service = ScriptedService(
        submit_responses=[
            httpx.Response(
                429, headers={"Retry-After": "5"}, json={"detail": "job queue is full"}
            )
        ]
    )
    observer = RecordingObserver()
    with step_deadline_scope(StepDeadline.start(2), step_order=1):
        with pytest.raises(TypedIOValidationException) as exc_info:
            await make_transcriber(service, poll_interval_seconds=1).transcribe(
                await audio_file(spool_contract),
                SimpleNamespace(),
                observer=observer,
                file_id=UUID(int=1),
            )
    assert exc_info.value.provider_work_may_have_completed is False
    assert clock["now"] == 2
    assert service.submit_count == 1
    assert observer.accepted_calls == []
    assert observer.unknown_calls == []
    assert [reason for _, reason in observer.rejected_calls] == ["provider_rejected"]
    from eneo.flows.flow_run_error import FlowRunErrorDetails

    details = FlowRunErrorDetails.from_budget_context(exc_info.value.context)
    assert details.transcription_failure_kind.value == "capacity"
    assert details.transcription_service_reason == "job queue is full"


@pytest.mark.parametrize(
    "detail, expected",
    [
        ("unsupported input " * 100, ("unsupported input " * 100)[:512]),
        (
            [
                {"loc": ["body", "file"], "msg": "Field required", "type": "missing"},
                {"msg": "Second error"},
            ],
            "Field required",
        ),
    ],
)
async def test_submission_validation_reason_uses_vemsa_detail(
    spool_contract, detail, expected
):
    service = ScriptedService(
        submit_responses=[httpx.Response(422, json={"detail": detail})]
    )
    observer = RecordingObserver()
    with pytest.raises(ProviderRejectedRequestException) as exc_info:
        await make_transcriber(service).transcribe(
            await audio_file(spool_contract),
            SimpleNamespace(),
            observer=observer,
            file_id=UUID(int=1),
        )
    assert exc_info.value.failure_kind.value == "input"
    assert exc_info.value.service_reason == expected
    assert observer.unknown_calls == []
    assert [reason for _, reason in observer.rejected_calls] == ["provider_rejected"]


async def test_cancellation_before_dispatch_keeps_audio_usage_complete(spool_contract):
    from eneo.flows.application.flow_run_service import _transcription_usage

    service = ScriptedService()
    observer = RecordingObserver()
    with (
        run_cancel_probe_scope(AsyncMock(return_value=True)),
        step_deadline_scope(StepDeadline.start(20), step_order=1) as scope,
    ):
        with pytest.raises(FlowStepCancelledError):
            await make_transcriber(service).transcribe(
                await audio_file(spool_contract),
                SimpleNamespace(),
                observer=observer,
                file_id=UUID(int=1),
            )
    assert service.submit_count == 0
    assert observer.unknown_calls == []
    assert observer.started_facts == []
    assert scope.provider_outcome_unresolved is False
    usage = _transcription_usage(None, recording_seconds=42)
    assert usage.audio_seconds == 0
    assert usage.completeness == "complete"


async def test_poll_ticks_publish_transcription_progress():
    observed = []

    class Service(ScriptedService):
        def handler(self, request):
            if self.requests:
                observed.append(
                    (scope.transcription_stage, scope.transcription_queue_position)
                )
            return super().handler(request)

    service = Service(
        status_responses=[
            status("queued", queue_position=3),
            status("running"),
            status("completed"),
        ],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )
    with step_deadline_scope(StepDeadline.start(10), step_order=1) as scope:
        await make_transcriber(service).wait_for_result(JOB_ID)
    assert observed == [("queued", 3), ("transcribing", None), ("completed", None)]


async def test_poll_timeout_retains_last_progress_in_error_details(monkeypatch):
    from eneo.flows.flow_run_error import FlowRunErrorDetails

    clock = {"now": 0.0}

    async def sleep(delay):
        clock["now"] += delay

    monkeypatch.setattr(step_deadline_module, "_now", lambda: clock["now"])
    monkeypatch.setattr(remote_transcription.asyncio, "sleep", sleep)
    service = ScriptedService(status_responses=[status("queued", queue_position=3)])
    with step_deadline_scope(StepDeadline.start(1), step_order=1):
        with pytest.raises(TypedIOValidationException) as exc_info:
            await make_transcriber(service, poll_interval_seconds=1).wait_for_result(
                JOB_ID
            )
    details = FlowRunErrorDetails.from_budget_context(exc_info.value.context)
    assert details.transcription_stage == "queued"
    assert details.transcription_queue_position == 3
    assert exc_info.value.step_phase.value == "transcription"
    assert service.cancel_count == 1


@pytest.mark.parametrize(
    "base_url,observed,expected_requests,expected_error",
    [
        ("http://tolka.test", True, 2, OpenAIException),
        ("http://tolka.test:invalid-port", True, 0, TranscriptionProviderError),
        ("http://tolka.test:invalid-port", False, 0, TranscriptionProviderError),
    ],
)
async def test_failed_submission_preserves_typed_errors_and_receipts(
    spool_contract,
    base_url: str,
    observed: bool,
    expected_requests: int,
    expected_error: type[Exception],
):
    # Mutant: target metadata parsing escapes the submission error boundary.
    requests = []

    def handle(request):
        requests.append(request)
        raise httpx.ReadTimeout("response lost", request=request)

    transcriber = make_transcriber(ScriptedService(), base_url=base_url)
    transcriber.client._transport = httpx.MockTransport(handle)
    observer = RecordingObserver()
    with pytest.raises(expected_error):
        await transcriber.transcribe(
            await audio_file(spool_contract),
            SimpleNamespace(),
            observer=observer if observed else None,
            file_id=UUID(int=1),
        )
    assert len(requests) == expected_requests
    assert all(request.method == "POST" for request in requests)
    if expected_requests == 2:
        assert (
            requests[0].headers["Idempotency-Key"]
            == requests[1].headers["Idempotency-Key"]
        )
    assert len(observer.started_facts) == int(observed)
    assert [reason for _, reason in observer.unknown_calls] == (
        ["provider_error"] if observed else []
    )
    assert observer.accepted_calls == []


@pytest.mark.parametrize("change", ["scope", "file_id", "digest", "task"])
async def test_submission_key_is_stable_and_scoped_to_operation(spool_contract, change):
    service = ScriptedService(
        submit_responses=[accepted(), accepted(), accepted()],
        status_responses=[
            status("completed"),
            status("completed"),
            status("completed"),
        ],
        result_responses=[httpx.Response(200, json=RESULT_BODY) for _ in range(3)],
    )
    observer = RecordingObserver()
    transcriber = make_transcriber(service)
    file_id = UUID(int=1)
    await transcriber.transcribe(
        await audio_file(spool_contract),
        SimpleNamespace(),
        observer=observer,
        file_id=file_id,
    )
    await transcriber.transcribe(
        await audio_file(spool_contract),
        SimpleNamespace(),
        observer=observer,
        file_id=file_id,
    )
    if change == "scope":
        observer.operation_scope = "other-tenant/run/step/attempt-2"
    elif change == "file_id":
        file_id = uuid4()
    file = await audio_file(
        spool_contract, b"different audio" if change == "digest" else b"fake-mp3-bytes"
    )
    if change == "task":
        await transcriber.label_speakers(
            file,
            words=[TranscriptWord(word="Hej", start=0, end=1)],
            model_name=RESULT_BODY["model"],
            observer=observer,
            file_id=file_id,
        )
    else:
        await transcriber.transcribe(
            file, SimpleNamespace(), observer=observer, file_id=file_id
        )
    keys = [
        request.headers["Idempotency-Key"]
        for request in service.requests
        if request.method == "POST"
    ]
    assert keys[0] == keys[1]
    assert keys[2] != keys[0]


async def test_run_cancellation_interrupts_admission_wait(spool_contract, monkeypatch):
    cancelled = False

    async def sleep(delay):
        nonlocal cancelled
        cancelled = True

    async def probe():
        return cancelled

    monkeypatch.setattr(remote_transcription.asyncio, "sleep", sleep)
    service = ScriptedService(
        submit_responses=[httpx.Response(429, headers={"Retry-After": "10"})]
    )
    observer = RecordingObserver()
    with (
        run_cancel_probe_scope(probe),
        step_deadline_scope(StepDeadline.start(20), step_order=1),
    ):
        with pytest.raises(FlowStepCancelledError):
            await make_transcriber(service).transcribe(
                await audio_file(spool_contract),
                SimpleNamespace(),
                observer=observer,
                file_id=UUID(int=1),
            )
    assert service.submit_count == 1
    assert observer.unknown_calls == []
    assert observer.accepted_calls == []
    assert [reason for _, reason in observer.rejected_calls] == ["provider_rejected"]


@pytest.mark.parametrize(
    "kind, expected",
    [
        (None, "provider"),
        ("new-kind", "provider"),
        ("capacity", "capacity"),
        ("input", "input"),
        ("internal", "internal"),
    ],
)
async def test_terminal_failure_kind_never_parses_reason(kind, expected):
    service = ScriptedService(
        status_responses=[
            httpx.Response(
                200,
                json={
                    "status": "failed",
                    "failure_kind": kind,
                    "error": "capacity input cancelled",
                },
            )
        ]
    )
    with pytest.raises(ProviderRejectedRequestException) as exc_info:
        await make_transcriber(service).wait_for_result(JOB_ID)
    assert exc_info.value.failure_kind.value == expected
    assert exc_info.value.service_reason == "capacity input cancelled"


def test_every_service_failure_kind_has_a_flow_failure_kind():
    from eneo.flows.flow_run_error import TranscriptionFailureKind
    from eneo.transcription_services.client import JobFailureKind

    assert {kind.value for kind in JobFailureKind} <= {
        kind.value for kind in TranscriptionFailureKind
    }


async def test_acceptance_persistence_failure_cancels_without_polling(spool_contract):
    from eneo.model_providers.domain.provider_call_observer import (
        ProviderCallObserverError,
    )

    observer = RecordingObserver()
    observer.accepted = AsyncMock(side_effect=ProviderCallObserverError("write failed"))
    service = ScriptedService(submit_responses=[accepted()])
    with pytest.raises(ProviderCallObserverError):
        await make_transcriber(service).transcribe(
            await audio_file(spool_contract),
            SimpleNamespace(),
            observer=observer,
            file_id=UUID(int=1),
        )
    assert service.submit_count == 1
    assert service.cancel_count == 1
    assert not any(request.method == "GET" for request in service.requests)


@pytest.mark.parametrize("base_url,expected_model", PROVIDER_TARGETS)
async def test_label_speakers_returns_service_text_and_records_its_own_call(
    spool_contract, base_url: str, expected_model: str
) -> None:
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("completed")],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )
    # Mutant: the diarization suffix leaves URL credentials in provider-call facts.
    transcriber = make_transcriber(service, base_url=base_url)
    observer = RecordingObserver()

    result = await transcriber.label_speakers(
        await audio_file(spool_contract),
        words=[TranscriptWord("hej", 0.0, 0.4)],
        model_name=RESULT_BODY["model"],
        language="sv",
        observer=observer,
        file_id=UUID(int=1),
    )

    assert result.text == RESULT_BODY["text"]
    [facts] = observer.started_facts
    assert isinstance(facts, TranscriptionCallRequestFacts)
    assert facts.requested_model == f"{expected_model}#diarize"
    assert len(observer.completed_calls) == 1
    body = service.requests[0].read()
    assert b'name="task"' in body and b'name="model"' in body


async def test_label_speakers_rejects_a_service_that_ignored_the_task(
    spool_contract,
) -> None:
    # A pre-task service runs a full transcription and reports its own model.
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("completed")],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )
    transcriber = make_transcriber(service)

    with pytest.raises(OpenAIException) as excinfo:
        await transcriber.label_speakers(
            await audio_file(spool_contract),
            words=[TranscriptWord("hej", 0.0, 0.4)],
            model_name="not-the-service-model",
            file_id=UUID(int=1),
        )

    assert excinfo.value.details["reason"] == "diarize_task_unsupported"


async def test_transcribe_returns_service_text_verbatim_with_duration(
    spool_contract,
) -> None:
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("queued"), status("running"), status("completed")],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )
    transcriber = make_transcriber(service)
    observer = RecordingObserver()

    result = await transcriber.transcribe(
        await audio_file(spool_contract),
        SimpleNamespace(),
        language=None,
        persist_cache_to_file=False,
        observer=observer,
        file_id=UUID(int=1),
    )

    assert result.text == RESULT_BODY["text"]
    assert result.duration_seconds == 42.0
    assert result.diarization == "external"
    assert result.alignment == "segment_split"
    assert result.transcript_segments == (
        TranscriptSegment(
            "Hej och välkomna.",
            0.0,
            5.2,
            speaker="SPEAKER_00",
            words=(TranscriptWord("Hej", 0.0, 0.4),),
        ),
    )
    assert service.submit_count == 1

    submit_request = service.requests[0]
    assert b"auto" in submit_request.read()

    [facts] = observer.started_facts
    assert facts.audio_seconds == 42.0
    assert facts.provider == "external"
    [(_, result_facts)] = observer.completed_calls
    assert result_facts.response_model == "KBLab/kb-whisper-large"
    assert result_facts.provider_response_id == JOB_ID
    assert observer.rejected_calls == []
    assert observer.unknown_calls == []


async def test_segments_that_do_not_render_the_text_are_dropped(spool_contract):
    mismatch = {**RESULT_BODY, "text": "[00:00:00 - 00:00:05] SPEAKER_01: Annat."}
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("completed")],
        result_responses=[httpx.Response(200, json=mismatch)],
    )

    result = await make_transcriber(service).transcribe(
        await audio_file(spool_contract), SimpleNamespace(), file_id=UUID(int=1)
    )

    assert result.text == mismatch["text"]
    assert result.transcript_segments is None


@pytest.mark.parametrize(
    ("status_code", "expected", "observed_reason"),
    [
        (401, APIKeyNotConfiguredException, "provider_error"),
        (413, ProviderRejectedRequestException, "provider_rejected"),
        (422, ProviderRejectedRequestException, "provider_rejected"),
        (500, OpenAIException, "provider_error"),
    ],
)
async def test_submit_answers_become_typed_provider_errors(
    spool_contract, status_code: int, expected: type[Exception], observed_reason: str
) -> None:
    service = ScriptedService(submit_responses=[httpx.Response(status_code)])
    observer = RecordingObserver()

    with pytest.raises(expected) as excinfo:
        await make_transcriber(service).transcribe(
            await audio_file(spool_contract),
            SimpleNamespace(),
            observer=observer,
            file_id=UUID(int=1),
        )

    if status_code == 500:
        assert excinfo.value.details == {"reason": "provider_error", "retryable": True}
    settled = [reason for _, reason in observer.rejected_calls + observer.unknown_calls]
    assert settled == [observed_reason]


async def test_failed_job_is_rejected_and_recorded(spool_contract) -> None:
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("failed")],
    )
    transcriber = make_transcriber(service)
    observer = RecordingObserver()

    with pytest.raises(ProviderRejectedRequestException):
        await transcriber.transcribe(
            await audio_file(spool_contract),
            SimpleNamespace(),
            observer=observer,
            file_id=UUID(int=1),
        )

    assert [reason for _, reason in observer.rejected_calls] == ["provider_rejected"]
    assert observer.unknown_calls == []
    assert service.submit_count == 1


async def test_successful_job_does_not_resolve_an_unknown_submission(
    spool_contract, monkeypatch
):
    clock = {"now": 0.0}
    monkeypatch.setattr(step_deadline_module, "_now", lambda: clock["now"])
    service = ScriptedService(
        submit_responses=[httpx.Response(500), accepted()],
        status_responses=[status("completed")],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )
    transcriber = make_transcriber(service)
    observer = RecordingObserver()
    with step_deadline_scope(StepDeadline.start(30), step_order=1):
        with pytest.raises(OpenAIException):
            await transcriber.transcribe(
                await audio_file(spool_contract),
                SimpleNamespace(),
                observer=observer,
                file_id=UUID(int=1),
            )
        await transcriber.transcribe(
            await audio_file(spool_contract),
            SimpleNamespace(),
            observer=observer,
            file_id=UUID(int=1),
        )
        clock["now"] = 30.0
        with pytest.raises(TypedIOValidationException) as exc_info:
            require_step_budget(phase="next transcription")

    assert service.submit_count == 2
    assert [reason for _, reason in observer.unknown_calls] == ["provider_error"]
    assert len(observer.completed_calls) == 1
    assert exc_info.value.provider_work_may_have_completed is True


async def test_cancelled_submission_is_not_resubmitted(spool_contract) -> None:
    """The step's budget ran out while the job was being submitted: the
    cancellation propagates without the retry policy sending the job again."""
    service = ScriptedService()
    transcriber = make_transcriber(service)

    async def cancelled_request(request):
        service.requests.append(request)
        raise asyncio.CancelledError()

    transcriber.client._transport = httpx.MockTransport(cancelled_request)
    observer = RecordingObserver()

    with step_deadline_scope(StepDeadline.start(30), step_order=1) as scope:
        with pytest.raises(asyncio.CancelledError):
            await transcriber.transcribe(
                await audio_file(spool_contract),
                SimpleNamespace(),
                observer=observer,
                file_id=UUID(int=1),
            )
        assert scope.provider_request_in_flight is False
        assert scope.provider_outcome_unresolved is True
        assert (
            scope.deadline.timeout_error(
                step_order=1, phase="transcription"
            ).provider_work_may_have_completed
            is True
        )

    assert [reason for _, reason in observer.unknown_calls] == ["request_cancelled"]
    assert service.submit_count == 1


async def test_no_job_is_submitted_after_the_step_budget_expires(
    spool_contract, monkeypatch
) -> None:
    clock = {"now": 0.0}
    monkeypatch.setattr(step_deadline_module, "_now", lambda: clock["now"])
    service = ScriptedService(submit_responses=[accepted()])
    transcriber = make_transcriber(service)
    observer = RecordingObserver()

    with step_deadline_scope(StepDeadline.start(10.0), step_order=3):
        clock["now"] = 11.0
        with pytest.raises(TypedIOValidationException) as exc_info:
            await transcriber.transcribe(
                await audio_file(spool_contract),
                SimpleNamespace(),
                observer=observer,
                file_id=UUID(int=1),
            )

    assert exc_info.value.code == "flow_step_timeout"
    assert "transcription job submission" in str(exc_info.value)
    assert service.submit_count == 0
    assert observer.started_facts == []


async def test_receipt_written_as_the_budget_runs_out_is_settled_not_submitted(
    spool_contract,
    monkeypatch,
) -> None:
    clock = {"now": 0.0}
    monkeypatch.setattr(step_deadline_module, "_now", lambda: clock["now"])
    service = ScriptedService(submit_responses=[accepted()])
    transcriber = make_transcriber(service)

    class _SlowReceipt(RecordingObserver):
        async def started(self, request: object) -> UUID:
            clock["now"] = 2.0
            return await super().started(request)

    observer = _SlowReceipt()
    with step_deadline_scope(StepDeadline.start(1.0), step_order=3):
        with pytest.raises(TypedIOValidationException) as exc_info:
            await transcriber.transcribe(
                await audio_file(spool_contract),
                SimpleNamespace(),
                observer=observer,
                file_id=UUID(int=1),
            )

    assert "(not sent)" in str(exc_info.value)
    assert service.submit_count == 0
    assert len(observer.started_facts) == 1
    assert [reason for _, reason in observer.rejected_calls] == ["budget_exhausted"]


async def test_cancelled_poll_keeps_the_in_flight_fact_and_stops_the_job(
    spool_contract,
) -> None:
    """The executor's backstop cancels the wait for a submitted job: the job is
    told to stop (best effort), and the in-flight fact stays published so the
    step's timeout message says the provider may still have completed it."""
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("running") for _ in range(500)],
    )
    transcriber = make_transcriber(service, poll_interval_seconds=0.01)
    observer = RecordingObserver()

    with step_deadline_scope(StepDeadline.start(30.0), step_order=2) as scope:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.1):
                await transcriber.transcribe(
                    await audio_file(spool_contract),
                    SimpleNamespace(),
                    observer=observer,
                    file_id=UUID(int=1),
                )
        assert scope.provider_request_in_flight is False
        assert scope.provider_outcome_unresolved is True
        assert (
            scope.deadline.timeout_error(
                step_order=2, phase="transcription"
            ).provider_work_may_have_completed
            is True
        )

    assert service.submit_count == 1
    assert service.cancel_count == 1
    assert [reason for _, reason in observer.unknown_calls] == ["request_cancelled"]


async def test_poll_deadline_cancels_job_and_is_unknown_outcome(spool_contract) -> None:
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("queued", queue_position=3) for _ in range(50)],
    )
    transcriber = make_transcriber(service)
    observer = RecordingObserver()

    with step_deadline_scope(StepDeadline.start(0.01), step_order=1):
        with pytest.raises(TypedIOValidationException):
            await transcriber.transcribe(
                await audio_file(spool_contract),
                SimpleNamespace(),
                observer=observer,
                file_id=UUID(int=1),
            )

    assert [reason for _, reason in observer.unknown_calls] == ["provider_error"]
    assert service.submit_count == 1
    # The job is stopped service-side instead of running unread to completion.
    assert service.cancel_count == 1


async def test_cancelled_job_is_terminal_and_recorded_as_cancelled(
    spool_contract,
) -> None:
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("running"), status("cancelled")],
    )
    transcriber = make_transcriber(service)
    observer = RecordingObserver()

    with pytest.raises(RemoteTranscriptionCancelledException) as excinfo:
        await transcriber.transcribe(
            await audio_file(spool_contract),
            SimpleNamespace(),
            observer=observer,
            file_id=UUID(int=1),
        )

    assert excinfo.value.details == {"reason": "provider_cancelled", "retryable": True}
    assert excinfo.value.failure_kind.value == "cancelled"
    assert [reason for _, reason in observer.unknown_calls] == ["request_cancelled"]
    assert observer.rejected_calls == []
    # Already terminal: nothing to cancel, and the status endpoint was left alone
    # once the terminal state was seen.
    assert service.cancel_count == 0
    assert service.status_responses == []


@pytest.mark.parametrize("stop_answer", [202, 500], ids=["stopped", "stop-refused"])
async def test_run_cancellation_stops_polling_and_cancels_job(
    spool_contract, stop_answer
) -> None:
    # A refused stop is logged, never raised over the cancellation itself.
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("queued", queue_position=1) for _ in range(50)],
        cancel_responses=[httpx.Response(stop_answer)],
    )
    transcriber = make_transcriber(service, result_timeout_seconds=1.0)
    observer = RecordingObserver()
    answers = iter([False, False, True])

    async def run_cancelled() -> bool:
        return next(answers)

    with run_cancel_probe_scope(run_cancelled):
        with pytest.raises(FlowStepCancelledError):
            await transcriber.transcribe(
                await audio_file(spool_contract),
                SimpleNamespace(),
                observer=observer,
                file_id=UUID(int=1),
            )

    assert service.cancel_count == 1
    [stop] = [request for request in service.requests if request.method == "DELETE"]
    # The stop keeps its own budget when result downloads time out sooner.
    assert stop.extensions["timeout"]["connect"] == 10.0
    assert [reason for _, reason in observer.unknown_calls] == ["request_cancelled"]
    assert len(service.status_responses) > 40


async def test_a_failed_stop_is_logged_without_transport_detail(
    spool_contract, remote_logs
) -> None:
    class Service(ScriptedService):
        def handler(self, request):
            if request.method == "DELETE":
                self.requests.append(request)
                raise httpx.ConnectError("dummy-cancel-secret", request=request)
            return super().handler(request)

    service = Service(
        submit_responses=[accepted()],
        status_responses=[status("queued") for _ in range(5)],
    )
    answers = iter([False, True])

    async def run_cancelled() -> bool:
        return next(answers)

    with run_cancel_probe_scope(run_cancelled):
        with pytest.raises(FlowStepCancelledError):
            await make_transcriber(service).transcribe(
                await audio_file(spool_contract),
                SimpleNamespace(),
                file_id=UUID(int=1),
            )

    [failure] = [r for r in remote_logs.records if "cancel_failed" in r.getMessage()]
    assert "request failed: ConnectError" in failure.getMessage()
    assert failure.exc_info is None
    assert "dummy-cancel-secret" not in remote_logs.text


async def test_rendering_that_spends_the_budget_is_a_timeout(monkeypatch) -> None:
    # The canonical-text check runs inside the attempt's budget: a check that
    # exhausts it fails the step and stops the job like any late result.
    clock = {"now": 0.0}
    monkeypatch.setattr(step_deadline_module, "_now", lambda: clock["now"])
    render = remote_transcription.render_segments

    def slow_render(segments):
        clock["now"] = 11.0
        return render(segments)

    monkeypatch.setattr(remote_transcription, "render_segments", slow_render)
    service = ScriptedService(
        status_responses=[status("completed")],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )

    with step_deadline_scope(StepDeadline.start(10), step_order=1):
        with pytest.raises(TypedIOValidationException) as exc_info:
            await make_transcriber(service).wait_for_result(JOB_ID)

    assert exc_info.value.code == "flow_step_timeout"
    assert service.cancel_count == 1


async def test_failing_cancellation_probe_keeps_waiting() -> None:
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("queued"), status("completed")],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )

    async def broken_probe() -> bool:
        raise RuntimeError("db pool exhausted")

    result = await make_transcriber(service).wait_for_result(
        JOB_ID, run_cancelled=broken_probe
    )

    assert result.text == RESULT_BODY["text"]
    assert service.cancel_count == 0


async def test_worker_cancellation_cancels_job_service_side(spool_contract) -> None:
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("running") for _ in range(50)],
    )
    transcriber = make_transcriber(service, poll_interval_seconds=0.05)
    observer = RecordingObserver()

    task = asyncio.create_task(
        transcriber.transcribe(
            await audio_file(spool_contract),
            SimpleNamespace(),
            observer=observer,
            file_id=UUID(int=1),
        )
    )
    while service.submit_count == 0:
        await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert service.cancel_count == 1
    assert [reason for _, reason in observer.unknown_calls] == ["request_cancelled"]


@pytest.mark.parametrize(
    ("response", "ready", "accepting", "base_url"),
    [
        (
            httpx.Response(200, json={"queue_accepting_jobs": True}),
            True,
            True,
            "http://tolka.test",
        ),
        (
            httpx.Response(200, json={"queue_accepting_jobs": False}),
            True,
            False,
            "http://tolka.test",
        ),
        (
            httpx.Response(503),
            False,
            False,
            "http://dummy-user:dummy-url-secret@tolka.test",
        ),
        (
            httpx.ConnectError("dummy-readiness-secret"),
            False,
            False,
            "http://tolka.test",
        ),
    ],
    ids=["ready", "admission-refused", "private-unavailable-url", "private-detail"],
)
async def test_startup_readiness_is_logged_without_private_detail(
    response: httpx.Response | Exception,
    ready: bool,
    accepting: bool,
    base_url: str,
    remote_logs: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mutants: raw transport detail or configured URL escapes into startup diagnostics.
    transcriber = make_transcriber(
        ScriptedService(ready_responses=[response]), base_url=base_url
    )
    monkeypatch.setattr(
        remote_transcription, "build_remote_flow_transcriber", lambda _: transcriber
    )

    await remote_transcription.log_remote_transcription_readiness(
        make_settings(
            flow_transcription_service_url=base_url,
            flow_transcription_service_api_key="devtoken",
        )
    )

    records = [
        r for r in remote_logs.records if r.name == remote_transcription.__name__
    ]
    assert len(records) == 1
    assert f"ready={ready} accepting_jobs={accepting}" in records[0].getMessage()
    assert "dummy-url-secret" not in remote_logs.text
    assert "dummy-readiness-secret" not in remote_logs.text
    assert records[0].exc_info is None


@pytest.mark.parametrize(
    "base_url", ["http://tolka.test", "http://dummy-user:dummy-url-secret@tolka.test"]
)
async def test_rejected_startup_credentials_are_logged_without_the_url(
    base_url: str,
    remote_logs: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mutant: the credential-rejection diagnostic prints URL credentials.
    transcriber = make_transcriber(
        ScriptedService(ready_responses=[httpx.Response(401)]), base_url=base_url
    )
    monkeypatch.setattr(
        remote_transcription, "build_remote_flow_transcriber", lambda _: transcriber
    )

    await remote_transcription.log_remote_transcription_readiness(
        make_settings(
            flow_transcription_service_url=base_url,
            flow_transcription_service_api_key="devtoken",
        )
    )

    records = [
        r for r in remote_logs.records if r.name == remote_transcription.__name__
    ]
    assert len(records) == 1
    assert "credentials rejected" in records[0].getMessage()
    assert "dummy-url-secret" not in remote_logs.text
    assert records[0].exc_info is None


@pytest.mark.parametrize(
    "polls,recovers,expected_failure_counts,final_failure",
    [
        (
            [httpx.Response(500), httpx.Response(503), status("completed")],
            True,
            [1, 2],
            None,
        ),
        (
            [httpx.Response(503)] * 4
            + [status("running")]
            + [httpx.Response(503)] * 4
            + [status("completed")],
            True,
            [1, 2, 3, 4, 1, 2, 3, 4],
            None,
        ),
        ([httpx.Response(403)] * 5, False, [1, 2, 3, 4, 5], "http 403"),
        ([httpx.Response(503)] * 5, False, [1, 2, 3, 4, 5], "http 503"),
        (
            [httpx.ReadTimeout("dummy-poll-secret")] * 5,
            False,
            [1, 2, 3, 4, 5],
            "request failed: ReadTimeout",
        ),
    ],
    ids=[
        "recover",
        "reset-after-progress",
        "unchanged-403-retries",
        "bounded-503",
        "private-transport-cause",
    ],
)
async def test_poll_tolerates_transient_failures(
    polls, recovers, expected_failure_counts, final_failure, remote_logs
) -> None:
    # Mutants: silent retry, missing/sensitive final cause, no counter reset or early exhaustion.
    service = ScriptedService(
        status_responses=polls.copy(),
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )
    transcriber = make_transcriber(service)
    if recovers:
        result = await transcriber.wait_for_result(JOB_ID)
        assert result.text == RESULT_BODY["text"]
    else:
        with pytest.raises(TranscriptionProviderError) as raised:
            await transcriber.wait_for_result(JOB_ID)
        error = raised.value
        assert error.details == {"reason": "provider_error", "retryable": True}
        cause = error.__cause__
        assert isinstance(cause, TranscriptionProviderError)
        assert cause.__traceback__ is not None
        assert cause.__context__ is None and error.__context__ is None
        diagnostic = "".join(traceback.format_exception(error))
        assert final_failure in diagnostic
        assert "dummy-poll-secret" not in diagnostic
    failures = [
        r
        for r in remote_logs.records
        if r.name == remote_transcription.__name__ and r.levelno == logging.WARNING
    ]
    assert [r.args[0] for r in failures] == expected_failure_counts
    assert all(r.exc_info is None for r in failures)
    assert "dummy-poll-secret" not in remote_logs.text
    assert not service.status_responses


@pytest.mark.parametrize(
    "poll, expected",
    [
        (httpx.Response(404), OpenAIException),
        (httpx.Response(401), APIKeyNotConfiguredException),
        (httpx.Response(200, json={"stage": "running"}), OpenAIException),
    ],
    ids=["job-vanished", "credentials-rejected", "malformed-status"],
)
async def test_a_definite_poll_answer_fails_without_retry(poll, expected) -> None:
    service = ScriptedService(status_responses=[poll])

    with pytest.raises(expected) as excinfo:
        await make_transcriber(service).wait_for_result(JOB_ID)

    if expected is OpenAIException:
        assert excinfo.value.details["reason"] == "provider_error"
    assert [request.method for request in service.requests] == ["GET"]


async def test_raced_409_result_reenters_poll_loop() -> None:
    service = ScriptedService(
        status_responses=[status("completed"), status("completed")],
        result_responses=[
            httpx.Response(409, json={"detail": {"status": "running"}}),
            httpx.Response(200, json=RESULT_BODY),
        ],
    )

    result = await make_transcriber(service).wait_for_result(JOB_ID)

    assert result.duration_seconds == 123.5


async def test_unreachable_result_download_is_a_provider_outage() -> None:
    class Service(ScriptedService):
        def handler(self, request):
            if request.url.path.endswith("/result"):
                raise httpx.ConnectError("refused", request=request)
            return super().handler(request)

    service = Service(status_responses=[status("completed")])

    with pytest.raises(OpenAIException) as excinfo:
        await make_transcriber(service).wait_for_result(JOB_ID)

    assert excinfo.value.code == "provider_unavailable"


async def test_submit_retries_rate_limit_then_succeeds(
    spool_contract,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(remote_transcription.asyncio, "sleep", no_sleep)
    service = ScriptedService(
        submit_responses=[httpx.Response(429), accepted()],
        status_responses=[status("completed")],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )
    transcriber = make_transcriber(service)
    observer = RecordingObserver()

    result = await transcriber.transcribe(
        await audio_file(spool_contract),
        SimpleNamespace(),
        observer=observer,
        file_id=UUID(int=1),
    )

    assert result.text == RESULT_BODY["text"]
    assert service.submit_count == 2
    assert len(observer.started_facts) == 1
    assert observer.unknown_calls == []
    assert len(observer.completed_calls) == 1


async def test_transcribe_rejects_non_audio_file() -> None:
    service = ScriptedService()
    transcriber = make_transcriber(service)

    with pytest.raises(ValueError):
        await transcriber.transcribe(
            SimpleNamespace(name="doc.pdf", mimetype="application/pdf", blob=b"x"),
            SimpleNamespace(),
            file_id=UUID(int=1),
        )

    assert service.requests == []


@pytest.mark.parametrize("bound", [0, -1, True])
async def test_invalid_speaker_bound_records_no_provider_call(spool_contract, bound):
    service = ScriptedService()
    observer = RecordingObserver()

    with pytest.raises(ValueError):
        await make_transcriber(service).transcribe(
            await audio_file(spool_contract),
            SimpleNamespace(),
            observer=observer,
            file_id=UUID(int=1),
            max_speakers=bound,
        )

    assert service.requests == []
    assert observer.started_facts == []


def test_build_remote_flow_transcriber_requires_configuration() -> None:
    unset = SimpleNamespace(
        flow_transcription_service_url=None,
        flow_transcription_service_api_key=None,
    )
    with pytest.raises(APIKeyNotConfiguredException):
        build_remote_flow_transcriber(unset)

    configured = SimpleNamespace(
        flow_transcription_include_speaker_review=True,
        flow_transcription_service_url="http://tolka.test",
        flow_transcription_service_api_key="devtoken",
        flow_transcription_service_submit_timeout_seconds=600,
        flow_transcription_service_poll_interval_seconds=5.0,
        flow_transcription_service_result_timeout_seconds=120,
    )
    transcriber = build_remote_flow_transcriber(configured)
    assert transcriber.client.base_url == "http://tolka.test"
    assert transcriber.client.include_speaker_review is True
    assert transcriber.client.submit_timeout_seconds == 600
    assert transcriber.client.result_timeout_seconds == 120
    assert transcriber.poll_interval_seconds == 5.0


async def test_flow_audio_step_runs_through_remote_transcriber(spool_contract) -> None:
    """The remote engine satisfies the flow step's transcriber seam end to end."""
    from uuid import uuid4 as new_id

    from eneo.flows.flow_api_error_code import FlowApiErrorCode
    from eneo.flows.runtime.transcription import transcribe_audio_input
    from eneo.main.exceptions import TypedIOValidationException

    file_id = new_id()
    file_info = SimpleNamespace(id=file_id, name="meeting.mp3", mimetype="audio/mpeg")

    open_audio_download = spool_contract.downloads([file_info])

    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("completed")],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )
    result = await transcribe_audio_input(
        files=[file_info],
        transcriber=make_transcriber(service),
        transcription_model=SimpleNamespace(id=new_id(), name="anchor-model"),
        language="auto",
        step_order=1,
        max_files=3,
        max_inline_text_bytes=1_048_576,
        open_audio_download=open_audio_download,
    )

    assert result.text == RESULT_BODY["text"]
    assert result.audio_seconds == 42.0
    assert result.model_name == "anchor-model"

    cancelled = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("queued") for _ in range(5)],
    )

    async def run_cancelled() -> bool:
        return True

    with run_cancel_probe_scope(run_cancelled):
        with pytest.raises(FlowStepCancelledError):
            await transcribe_audio_input(
                files=[file_info],
                transcriber=make_transcriber(cancelled),
                transcription_model=SimpleNamespace(id=new_id(), name="anchor-model"),
                language="auto",
                step_order=1,
                max_files=3,
                max_inline_text_bytes=1_048_576,
                open_audio_download=open_audio_download,
            )

    failing = ScriptedService(submit_responses=[httpx.Response(422)])
    with pytest.raises(TypedIOValidationException) as excinfo:
        await transcribe_audio_input(
            files=[file_info],
            transcriber=make_transcriber(failing),
            transcription_model=SimpleNamespace(id=new_id(), name="anchor-model"),
            language="auto",
            step_order=1,
            max_files=3,
            max_inline_text_bytes=1_048_576,
            open_audio_download=open_audio_download,
        )
    assert excinfo.value.code == FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_FAILED.value


@pytest.mark.parametrize(
    "duration,budget,succeeds",
    [(2700, 3600, True), (5400, 3600, False), (5400, 7200, True)],
)
async def test_remote_poll_spends_the_attempt_budget(
    monkeypatch, duration, budget, succeeds
):
    clock = {"now": 0.0}
    monkeypatch.setattr(step_deadline_module, "_now", lambda: clock["now"])

    async def advance(_seconds):
        clock["now"] += duration

    monkeypatch.setattr(remote_transcription.asyncio, "sleep", advance)
    timeouts = []
    real_timeout = asyncio.timeout

    def capture_timeout(delay):
        timeouts.append(delay)
        return real_timeout(delay)

    monkeypatch.setattr(remote_transcription.asyncio, "timeout", capture_timeout)
    service = ScriptedService(
        status_responses=[
            status("running"),
            status("completed"),
            status("running"),
            status("completed"),
        ],
        result_responses=[
            httpx.Response(200, json=RESULT_BODY),
            httpx.Response(200, json=RESULT_BODY),
        ],
    )
    transcriber = build_remote_flow_transcriber(
        Settings.model_construct(
            flow_transcription_service_url="http://tolka.test",
            flow_transcription_service_api_key="devtoken",
        )
    )
    transcriber.client._transport = httpx.MockTransport(service.handler)
    for _ in range(2 if succeeds else 1):
        timeout_index = len(timeouts)
        with step_deadline_scope(StepDeadline.start(budget), step_order=1):
            if succeeds:
                result = await transcriber.wait_for_result(JOB_ID)
                assert result.text == RESULT_BODY["text"]
            else:
                with pytest.raises(TypedIOValidationException) as exc_info:
                    await transcriber.wait_for_result(JOB_ID)
                assert exc_info.value.code == "flow_step_timeout"
                assert exc_info.value.step_phase.value == "transcription"
        assert timeouts[timeout_index] == budget


async def test_remote_poll_bounds_a_stalled_request_by_the_attempt_budget(monkeypatch):
    service = ScriptedService()
    transcriber = make_transcriber(service)

    async def stalled(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(transcriber.client, "get_job_status", stalled)
    with step_deadline_scope(StepDeadline.start(0.02), step_order=1):
        async with asyncio.timeout(0.3):
            with pytest.raises(TypedIOValidationException):
                await transcriber.wait_for_result(JOB_ID)
    assert service.cancel_count == 1


async def test_remote_poll_without_attempt_has_no_duration_limit(monkeypatch):
    timeouts = []
    real_timeout = asyncio.timeout

    def capture_timeout(delay):
        timeouts.append(delay)
        return real_timeout(delay)

    monkeypatch.setattr(remote_transcription.asyncio, "timeout", capture_timeout)
    service = ScriptedService(
        status_responses=[status("running"), status("completed")],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )
    result = await make_transcriber(service).wait_for_result(JOB_ID)
    assert result.text == RESULT_BODY["text"]
    assert timeouts == [None]
