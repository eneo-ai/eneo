from __future__ import annotations

import io
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest

from eneo.flows.runtime import remote_transcription
from eneo.flows.runtime.remote_transcription import (
    RemoteFlowTranscriber,
    RemoteTranscriptionClient,
    build_remote_flow_transcriber,
)
from eneo.main.exceptions import (
    APIKeyNotConfiguredException,
    OpenAIException,
    ProviderRejectedRequestException,
)

JOB_ID = "abc123"

RESULT_BODY = {
    "language": "sv",
    "duration_seconds": 123.5,
    "model": "KBLab/kb-whisper-large",
    "text": "[00:00:00 - 00:00:05] SPEAKER_00: Hej och välkomna.",
    "segments": [],
}


class ScriptedService:
    """Plays back a scripted sequence of responses per endpoint."""

    def __init__(
        self,
        *,
        submit_responses: list[httpx.Response] | None = None,
        status_responses: list[httpx.Response] | None = None,
        result_responses: list[httpx.Response] | None = None,
    ) -> None:
        self.submit_responses = submit_responses or []
        self.status_responses = status_responses or []
        self.result_responses = result_responses or []
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST" and path == "/v1/jobs":
            return self.submit_responses.pop(0)
        if request.method == "GET" and path == f"/v1/jobs/{JOB_ID}":
            return self.status_responses.pop(0)
        if request.method == "GET" and path == f"/v1/jobs/{JOB_ID}/result":
            return self.result_responses.pop(0)
        raise AssertionError(f"unexpected request: {request.method} {path}")

    @property
    def submit_count(self) -> int:
        return sum(
            1
            for request in self.requests
            if request.method == "POST" and request.url.path == "/v1/jobs"
        )


def accepted() -> httpx.Response:
    return httpx.Response(202, json={"job_id": JOB_ID, "status": "queued"})


def status(value: str) -> httpx.Response:
    return httpx.Response(200, json={"job_id": JOB_ID, "status": value})


def make_client(
    service: ScriptedService, **overrides: float
) -> RemoteTranscriptionClient:
    return RemoteTranscriptionClient(
        base_url="http://tolka.test",
        api_key="devtoken",
        submit_timeout_seconds=overrides.get("submit_timeout_seconds", 5.0),
        poll_interval_seconds=overrides.get("poll_interval_seconds", 0.001),
        poll_timeout_seconds=overrides.get("poll_timeout_seconds", 5.0),
        result_timeout_seconds=overrides.get("result_timeout_seconds", 5.0),
        transport=httpx.MockTransport(service.handler),
    )


class RecordingObserver:
    def __init__(self) -> None:
        self.started_facts: list[object] = []
        self.completed_calls: list[tuple[UUID, object]] = []
        self.rejected_calls: list[tuple[UUID, str]] = []
        self.unknown_calls: list[tuple[UUID, str]] = []

    async def started(self, request: object) -> UUID:
        self.started_facts.append(request)
        return uuid4()

    async def completed(self, call_id: UUID, result: object) -> None:
        self.completed_calls.append((call_id, result))

    async def rejected(self, call_id: UUID, reason: str) -> None:
        self.rejected_calls.append((call_id, reason))

    async def outcome_unknown(self, call_id: UUID, reason: str) -> None:
        self.unknown_calls.append((call_id, reason))


def audio_file(blob: bytes = b"fake-mp3-bytes") -> SimpleNamespace:
    return SimpleNamespace(name="meeting.mp3", mimetype="audio/mpeg", blob=blob)


@pytest.fixture(autouse=True)
def fixed_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        remote_transcription, "_measure_original_seconds", lambda _: 42.0
    )


async def test_submit_sends_multipart_job_contract() -> None:
    service = ScriptedService(submit_responses=[accepted()])
    client = make_client(service)

    job_id = await client.submit(
        filename="meeting.mp3",
        mimetype="audio/mpeg",
        payload=io.BytesIO(b"fake"),
        language="sv",
    )

    assert job_id == JOB_ID
    request = service.requests[0]
    assert request.headers["authorization"] == "Bearer devtoken"
    body = request.read()
    assert b'name="file"' in body
    assert b"fake" in body
    assert b'name="language"' in body and b"sv" in body
    assert b'name="diarize"' in body and b"true" in body


async def test_transcribe_returns_service_text_verbatim_with_duration() -> None:
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("queued"), status("running"), status("completed")],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )
    transcriber = RemoteFlowTranscriber(make_client(service))
    observer = RecordingObserver()

    result = await transcriber.transcribe(
        audio_file(),
        SimpleNamespace(),
        language=None,
        persist_cache_to_file=False,
        observer=observer,
    )

    assert result.text == RESULT_BODY["text"]
    assert result.duration_seconds == 123.5
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


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, APIKeyNotConfiguredException),
        (429, OpenAIException),
        (413, ProviderRejectedRequestException),
        (422, ProviderRejectedRequestException),
        (500, OpenAIException),
    ],
)
async def test_submit_status_maps_to_typed_provider_errors(
    status_code: int, expected: type[Exception]
) -> None:
    service = ScriptedService(submit_responses=[httpx.Response(status_code)])
    client = make_client(service)

    with pytest.raises(expected) as excinfo:
        await client.submit(
            filename="a.mp3",
            mimetype="audio/mpeg",
            payload=io.BytesIO(b"x"),
            language=None,
        )

    if status_code == 429:
        assert excinfo.value.details["reason"] == "provider_rate_limited"
        assert excinfo.value.details["retryable"] is True


async def test_failed_job_is_rejected_and_recorded() -> None:
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("failed")],
    )
    transcriber = RemoteFlowTranscriber(make_client(service))
    observer = RecordingObserver()

    with pytest.raises(ProviderRejectedRequestException):
        await transcriber.transcribe(audio_file(), SimpleNamespace(), observer=observer)

    assert [reason for _, reason in observer.rejected_calls] == ["provider_rejected"]
    assert observer.unknown_calls == []
    assert service.submit_count == 1


async def test_poll_deadline_is_unknown_outcome_without_resubmit() -> None:
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("queued") for _ in range(50)],
    )
    transcriber = RemoteFlowTranscriber(make_client(service, poll_timeout_seconds=0.01))
    observer = RecordingObserver()

    with pytest.raises(OpenAIException):
        await transcriber.transcribe(audio_file(), SimpleNamespace(), observer=observer)

    assert [reason for _, reason in observer.unknown_calls] == ["provider_error"]
    assert service.submit_count == 1


async def test_poll_tolerates_transient_failures() -> None:
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[
            httpx.Response(500),
            httpx.Response(503),
            status("completed"),
        ],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )
    client = make_client(service)

    result = await client.wait_for_result(JOB_ID)

    assert result.text == RESULT_BODY["text"]


async def test_poll_404_means_job_vanished() -> None:
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[httpx.Response(404)],
    )
    client = make_client(service)

    with pytest.raises(OpenAIException) as excinfo:
        await client.wait_for_result(JOB_ID)

    assert excinfo.value.details["reason"] == "provider_error"


async def test_raced_409_result_reenters_poll_loop() -> None:
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("completed"), status("completed")],
        result_responses=[
            httpx.Response(409, json={"detail": {"status": "running"}}),
            httpx.Response(200, json=RESULT_BODY),
        ],
    )
    client = make_client(service)

    result = await client.wait_for_result(JOB_ID)

    assert result.duration_seconds == 123.5


async def test_submit_retries_rate_limit_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(RemoteFlowTranscriber._submit_job.retry, "sleep", no_sleep)
    service = ScriptedService(
        submit_responses=[httpx.Response(429), accepted()],
        status_responses=[status("completed")],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )
    transcriber = RemoteFlowTranscriber(make_client(service))
    observer = RecordingObserver()

    result = await transcriber.transcribe(
        audio_file(), SimpleNamespace(), observer=observer
    )

    assert result.text == RESULT_BODY["text"]
    assert service.submit_count == 2
    # Each network attempt is its own recorded request: the refused attempt
    # closed as unknown, the successful one completed.
    assert len(observer.started_facts) == 2
    assert len(observer.unknown_calls) == 1
    assert len(observer.completed_calls) == 1


async def test_transcribe_rejects_non_audio_file() -> None:
    service = ScriptedService()
    transcriber = RemoteFlowTranscriber(make_client(service))

    with pytest.raises(ValueError):
        await transcriber.transcribe(
            SimpleNamespace(name="doc.pdf", mimetype="application/pdf", blob=b"x"),
            SimpleNamespace(),
        )

    assert service.requests == []


def test_build_remote_flow_transcriber_requires_configuration() -> None:
    unset = SimpleNamespace(
        flow_transcription_service_url=None,
        flow_transcription_service_api_key=None,
    )
    with pytest.raises(APIKeyNotConfiguredException):
        build_remote_flow_transcriber(unset)

    configured = SimpleNamespace(
        flow_transcription_service_url="http://tolka.test",
        flow_transcription_service_api_key="devtoken",
        flow_transcription_service_submit_timeout_seconds=600,
        flow_transcription_service_poll_interval_seconds=5.0,
        flow_transcription_service_poll_timeout_seconds=3300,
        flow_transcription_service_result_timeout_seconds=120,
    )
    transcriber = build_remote_flow_transcriber(configured)
    assert transcriber.client.base_url == "http://tolka.test"


def test_result_parsing_defends_against_malformed_payloads() -> None:
    service = ScriptedService()
    client = make_client(service)

    response = httpx.Response(202, json={"status": "queued"})
    with pytest.raises(OpenAIException):
        client._parse_job_id(response)


async def test_flow_audio_step_runs_through_remote_transcriber() -> None:
    """The remote engine satisfies the flow step's transcriber seam end to end."""
    from uuid import uuid4 as new_id

    from eneo.flows.flow_api_error_code import FlowApiErrorCode
    from eneo.flows.runtime.transcription import transcribe_audio_input
    from eneo.main.exceptions import TypedIOValidationException

    file_id = new_id()
    file_info = SimpleNamespace(id=file_id, name="meeting.mp3", mimetype="audio/mpeg")

    async def load_audio_payload(requested_id: object) -> SimpleNamespace:
        assert requested_id == file_id
        return audio_file()

    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("completed")],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )
    result = await transcribe_audio_input(
        files=[file_info],
        transcriber=RemoteFlowTranscriber(make_client(service)),
        transcription_model=SimpleNamespace(id=new_id(), name="anchor-model"),
        language="auto",
        step_order=1,
        max_files=3,
        max_inline_text_bytes=1_048_576,
        load_audio_payload=load_audio_payload,
    )

    assert result.text == RESULT_BODY["text"]
    assert result.audio_seconds == 123.5
    assert result.model_name == "anchor-model"

    failing = ScriptedService(submit_responses=[httpx.Response(422)])
    with pytest.raises(TypedIOValidationException) as excinfo:
        await transcribe_audio_input(
            files=[file_info],
            transcriber=RemoteFlowTranscriber(make_client(failing)),
            transcription_model=SimpleNamespace(id=new_id(), name="anchor-model"),
            language="auto",
            step_order=1,
            max_files=3,
            max_inline_text_bytes=1_048_576,
            load_audio_payload=load_audio_payload,
        )
    assert excinfo.value.code == FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_FAILED.value
