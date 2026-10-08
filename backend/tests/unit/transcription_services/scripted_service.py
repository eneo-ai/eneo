"""A scripted native transcription service for client and Flow tests."""

from __future__ import annotations

import httpx

from eneo.transcription_services.client import TranscriptionServiceClient

JOB_ID = "abc123"

RESULT_BODY = {
    "language": "sv",
    "duration_seconds": 123.5,
    "model": "KBLab/kb-whisper-large",
    "text": "[00:00:00 - 00:00:05] SPEAKER_00: Hej och välkomna.",
    "segments": [
        {
            "start": 0.0,
            "end": 5.2,
            "speaker": "SPEAKER_00",
            "text": "Hej och välkomna.",
            "words": [{"word": "Hej", "start": 0.0, "end": 0.4}],
        }
    ],
    "alignment": "segment_split",
}


class ScriptedService:
    """Plays back a scripted sequence of responses per endpoint."""

    def __init__(
        self,
        *,
        submit_responses: list[httpx.Response] | None = None,
        status_responses: list[httpx.Response | Exception] | None = None,
        result_responses: list[httpx.Response] | None = None,
        cancel_responses: list[httpx.Response] | None = None,
        ready_responses: list[httpx.Response | Exception] | None = None,
    ) -> None:
        self.submit_responses = submit_responses or []
        self.status_responses = status_responses or []
        self.result_responses = result_responses or []
        self.cancel_responses = cancel_responses or []
        self.ready_responses = ready_responses or []
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST" and path == "/v1/jobs":
            return self.submit_responses.pop(0)
        if request.method == "GET" and path == f"/v1/jobs/{JOB_ID}":
            response = self.status_responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        if request.method == "GET" and path == f"/v1/jobs/{JOB_ID}/result":
            return self.result_responses.pop(0)
        if request.method == "DELETE" and path == f"/v1/jobs/{JOB_ID}":
            if self.cancel_responses:
                return self.cancel_responses.pop(0)
            return httpx.Response(
                202, json={"job_id": JOB_ID, "cancellation_requested": True}
            )
        if request.method == "GET" and path == "/v1/health/ready":
            response = self.ready_responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        raise AssertionError(f"unexpected request: {request.method} {path}")

    @property
    def submit_count(self) -> int:
        return sum(
            1
            for request in self.requests
            if request.method == "POST" and request.url.path == "/v1/jobs"
        )

    @property
    def cancel_count(self) -> int:
        return sum(1 for request in self.requests if request.method == "DELETE")


def accepted() -> httpx.Response:
    return httpx.Response(202, json={"job_id": JOB_ID, "status": "queued"})


def status(value: str, *, queue_position: int | None = None) -> httpx.Response:
    # Mirrors the service contract: stage and queue_position are always
    # present, the latter only set while queued.
    stage = "transcribing" if value == "running" else value
    return httpx.Response(
        200,
        json={
            "job_id": JOB_ID,
            "status": value,
            "stage": stage,
            "queue_position": queue_position,
        },
    )


def make_client(
    service: ScriptedService,
    *,
    base_url: str = "http://tolka.test",
    submit_timeout_seconds: float = 5.0,
    result_timeout_seconds: float = 5.0,
) -> TranscriptionServiceClient:
    return TranscriptionServiceClient(
        base_url=base_url,
        api_key="devtoken",
        submit_timeout_seconds=submit_timeout_seconds,
        result_timeout_seconds=result_timeout_seconds,
        transport=httpx.MockTransport(service.handler),
    )
