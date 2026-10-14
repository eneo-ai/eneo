"""The native jobs protocol as the shared client speaks it."""

from __future__ import annotations

import asyncio
import io
import re
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from eneo.files.transcript import (
    TranscriptSegment,
    TranscriptWord,
)
from eneo.transcription_services import client as client_module
from eneo.transcription_services.client import (
    CredentialsRejected,
    JobFailureKind,
    JobNotFound,
    MalformedResponse,
    RequestFailed,
    SubmissionOutcomeUnknown,
    SubmissionRefused,
    SubmissionRejected,
    TranscriptionJobRequest,
    UnexpectedStatus,
    parse_result_segments,
)
from tests.unit.transcription_services.scripted_service import (
    JOB_ID,
    RESULT_BODY,
    ScriptedService,
    accepted,
    make_client,
    status,
)

LABEL = TranscriptionJobRequest(
    task="diarize", language="sv", segments=[TranscriptSegment("hej du", 0.0, 0.7)]
)
TIME = TranscriptionJobRequest(
    task="timestamp",
    language="sv",
    segments=[TranscriptSegment("hej du", 0.0, 0.7)],
    model="whisper-1",
)


async def _submit(
    service: ScriptedService,
    request: TranscriptionJobRequest = LABEL,
    *,
    base_url: str = "http://tolka.test",
) -> str:
    return await make_client(service, base_url=base_url).submit_job(
        request,
        filename="meeting.mp3",
        mimetype="audio/mpeg",
        payload=io.BytesIO(b"fake"),
        idempotency_key="key-1",
    )


def _form(service: ScriptedService, index: int = 0) -> bytes:
    return service.requests[index].read()


def _fields(service: ScriptedService) -> dict[str, str]:
    """The job's text form fields; the audio part is not one."""
    return {
        name.decode(): value.decode()
        for name, value in re.findall(
            rb'name="(\w+)"\r\n\r\n(.*?)\r\n--', _form(service), re.S
        )
    }


async def test_submit_sends_the_multipart_job_contract() -> None:
    service = ScriptedService(submit_responses=[accepted()])

    assert await _submit(service) == JOB_ID

    request = service.requests[0]
    assert request.headers["authorization"] == "Bearer devtoken"
    assert request.headers["idempotency-key"] == "key-1"
    body = _form(service)
    assert b'name="file"' in body and b"fake" in body
    # A diarize job asks for speaker labels on a transcript it carries. No
    # model is named unless the request carries one.
    assert _fields(service) == {
        "task": "diarize",
        "language": "sv",
        "diarize": "true",
        "segments": '[{"text":"hej du","start":0.0,"end":0.7}]',
    }


async def test_a_timestamp_job_sends_its_transcript_and_no_speaker_fields() -> None:
    service = ScriptedService(submit_responses=[accepted()])
    client = make_client(service)
    # Speaker review belongs to diarize jobs, whatever the client opted into.
    client.include_speaker_review = True

    await client.submit_job(
        TIME,
        filename="a.wav",
        mimetype="audio/wav",
        payload=io.BytesIO(b"audio"),
    )

    assert _fields(service) == {
        "task": "timestamp",
        "language": "sv",
        "segments": '[{"text":"hej du","start":0.0,"end":0.7}]',
        "model": "whisper-1",
    }


async def test_diarize_job_sends_the_transcript_and_its_model() -> None:
    service = ScriptedService(submit_responses=[accepted()])

    await _submit(
        service,
        TranscriptionJobRequest(
            task="diarize",
            language="sv",
            words=[TranscriptWord("hej", 0.0, 0.4), TranscriptWord("du", 0.5, 0.7)],
            model="whisper-1",
        ),
    )

    body = _form(service)
    assert b'name="task"' in body and b"diarize" in body
    assert b'name="model"' in body and b"whisper-1" in body
    assert (
        b'[{"word":"hej","start":0.0,"end":0.4},{"word":"du","start":0.5,"end":0.7}]'
        in body
    )


async def test_diarize_job_accepts_segments_without_words() -> None:
    service = ScriptedService(submit_responses=[accepted()])

    await _submit(
        service,
        TranscriptionJobRequest(
            task="diarize",
            language="sv",
            segments=[TranscriptSegment("hej du", 0.0, 0.7)],
        ),
    )

    body = _form(service)
    assert b'[{"text":"hej du","start":0.0,"end":0.7}]' in body
    assert b'name="words"' not in body


@pytest.mark.parametrize("max_speakers", [3, None])
async def test_speaker_bound_is_sent_only_when_set(max_speakers) -> None:
    service = ScriptedService(submit_responses=[accepted()])

    await _submit(service, replace(LABEL, max_speakers=max_speakers))

    assert (b'name="max_speakers"' in _form(service)) is (max_speakers is not None)


@pytest.mark.parametrize("enabled", [False, True])
async def test_speaker_review_is_requested_only_by_explicit_opt_in(enabled) -> None:
    service = ScriptedService(submit_responses=[accepted()])
    client = make_client(service)
    client.include_speaker_review = enabled

    await client.submit_job(
        LABEL,
        filename="a.wav",
        mimetype="audio/wav",
        payload=io.BytesIO(b"audio"),
    )

    assert (b'name="include_speaker_review"' in _form(service)) == enabled


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"words": []}, id="diarize-without-transcript"),
        pytest.param({"task": "timestamp"}, id="timestamp-without-transcript"),
        pytest.param(
            {"task": "timestamp", "words": [TranscriptWord("x", 0, 1)]},
            id="timestamp-with-words",
        ),
        pytest.param(
            {
                "task": "timestamp",
                "segments": [TranscriptSegment("x", 0, 1)],
                "max_speakers": 2,
            },
            id="timestamp-with-a-speaker-bound",
        ),
        pytest.param(
            {
                "segments": [
                    TranscriptSegment("x", 0, 1, speaker_attribution="provisional")
                ]
            },
            id="reviewed-transcript",
        ),
        pytest.param(
            {"segments": [TranscriptSegment("x", 0, 1)], "max_speakers": 0},
            id="zero-speakers",
        ),
        pytest.param(
            {"segments": [TranscriptSegment("x", 0, 1)], "max_speakers": True},
            id="boolean-speakers",
        ),
        pytest.param(
            {"segments": [TranscriptSegment("x", 0, 1)], "max_speakers": 1.5},
            id="fractional-speakers",
        ),
    ],
)
def test_an_invalid_request_cannot_be_built(fields) -> None:
    with pytest.raises(ValueError):
        TranscriptionJobRequest(**{"task": "diarize", "language": "sv", **fields})


@pytest.mark.parametrize(
    "response, error, details",
    [
        (httpx.Response(401), CredentialsRejected, {}),
        (
            httpx.Response(429, headers={"Retry-After": "7"}, json={"detail": "full"}),
            SubmissionRefused,
            {"retry_after": 7.0, "service_reason": "full"},
        ),
        (
            httpx.Response(503, headers={"Retry-After": "2"}),
            SubmissionRefused,
            {"retry_after": 2.0, "service_reason": None},
        ),
        (httpx.Response(503), UnexpectedStatus, {"status_code": 503}),
        (
            httpx.Response(413, json={"detail": "transcript exceeds 8 bytes"}),
            SubmissionRejected,
            {"service_reason": "transcript exceeds 8 bytes"},
        ),
        (
            httpx.Response(
                422,
                json={
                    "detail": [
                        {"loc": ["body", "file"], "msg": "Field required"},
                        {"msg": "Second error"},
                    ]
                },
            ),
            SubmissionRejected,
            {"service_reason": "Field required"},
        ),
        (
            httpx.Response(422, json={"detail": "x" * 600}),
            SubmissionRejected,
            {"service_reason": "x" * 512},
        ),
        (httpx.Response(409), UnexpectedStatus, {"status_code": 409}),
        (httpx.Response(500), UnexpectedStatus, {"status_code": 500}),
        (httpx.Response(202, json={"status": "queued"}), MalformedResponse, {}),
    ],
)
async def test_submission_answers_map_to_typed_errors(response, error, details) -> None:
    with pytest.raises(error) as raised:
        await _submit(ScriptedService(submit_responses=[response]))

    for name, value in details.items():
        assert getattr(raised.value, name) == value


@pytest.mark.parametrize(
    "lost",
    [
        httpx.WriteError,
        httpx.ReadError,
        httpx.WriteTimeout,
        httpx.ReadTimeout,
        httpx.RemoteProtocolError,
    ],
)
async def test_an_answer_lost_after_upload_is_an_unknown_outcome(lost) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise lost("dummy-transport-secret", request=request)

    client = make_client(ScriptedService())
    client._transport = httpx.MockTransport(handler)

    with pytest.raises(SubmissionOutcomeUnknown) as raised:
        await client.submit_job(
            LABEL,
            filename="a.mp3",
            mimetype="audio/mpeg",
            payload=io.BytesIO(b"x"),
        )

    assert "dummy-transport-secret" not in str(raised.value)
    assert lost.__name__ in str(raised.value)


async def test_a_request_that_never_left_is_a_failed_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dummy-transport-secret", request=request)

    client = make_client(
        ScriptedService(), base_url="http://dummy-user:dummy-url-secret@tolka.test"
    )
    client._transport = httpx.MockTransport(handler)

    with pytest.raises(RequestFailed) as raised:
        await client.submit_job(
            LABEL,
            filename="a.mp3",
            mimetype="audio/mpeg",
            payload=io.BytesIO(b"x"),
        )

    assert str(raised.value) == "request failed: ConnectError"
    assert isinstance(raised.value.__cause__, httpx.ConnectError)


async def test_job_status_reports_stage_queue_position_and_failure() -> None:
    service = ScriptedService(
        status_responses=[
            status("queued", queue_position=3),
            httpx.Response(
                200,
                json={
                    "status": "failed",
                    "stage": "s" * 200,
                    "queue_position": -1,
                    "failure_kind": "capacity",
                    "error": "e" * 600,
                },
            ),
        ]
    )
    client = make_client(service)

    queued = await client.get_job_status(JOB_ID)
    failed = await client.get_job_status(JOB_ID)

    assert (queued.status, queued.stage, queued.queue_position) == (
        "queued",
        "queued",
        3,
    )
    assert queued.describe() == "queued (position 3)"
    assert failed.failure_kind is JobFailureKind.CAPACITY
    assert failed.queue_position is None
    assert failed.stage == "s" * 128
    assert failed.service_reason == "e" * 512


@pytest.mark.parametrize(
    "kind, expected",
    [
        (None, None),
        ("new-kind", None),
        (["capacity"], None),
        *((kind.value, kind) for kind in JobFailureKind),
    ],
)
async def test_failure_kind_is_the_closed_protocol_set(kind, expected) -> None:
    service = ScriptedService(
        status_responses=[
            httpx.Response(
                200, json={"status": "failed", "failure_kind": kind, "error": "input"}
            )
        ]
    )

    seen = await make_client(service).get_job_status(JOB_ID)

    assert seen.failure_kind == expected


@pytest.mark.parametrize(
    "response, error",
    [
        (httpx.Response(401), CredentialsRejected),
        (httpx.Response(404), JobNotFound),
        (httpx.Response(503), UnexpectedStatus),
        (httpx.Response(200, json={"stage": "running"}), MalformedResponse),
        (httpx.ReadTimeout("dummy-poll-secret"), RequestFailed),
    ],
)
async def test_job_status_failures_are_typed(response, error) -> None:
    service = ScriptedService(status_responses=[response])

    with pytest.raises(error) as raised:
        await make_client(service).get_job_status(JOB_ID)

    assert "dummy-poll-secret" not in str(raised.value)


async def test_job_result_parses_the_transcript_and_its_sidecar() -> None:
    service = ScriptedService(
        result_responses=[
            httpx.Response(409, json={"detail": {"status": "running"}}),
            httpx.Response(200, json={**RESULT_BODY, "speaker_review": {"v": 1}}),
        ]
    )
    client = make_client(service)

    assert await client.get_job_result(JOB_ID) is None
    result = await client.get_job_result(JOB_ID)

    assert result is not None
    assert result.text == RESULT_BODY["text"]
    assert result.duration_seconds == 123.5
    assert (result.model, result.language, result.alignment) == (
        "KBLab/kb-whisper-large",
        "sv",
        "segment_split",
    )
    assert result.speaker_review == {"v": 1}
    assert result.segments == (
        TranscriptSegment(
            "Hej och välkomna.",
            0.0,
            5.2,
            speaker="SPEAKER_00",
            words=(TranscriptWord("Hej", 0.0, 0.4),),
        ),
    )


async def test_a_job_result_keeps_its_transcript_when_the_duration_is_no_number() -> (
    None
):
    # Kills the mutant that reads duration_seconds with float(): an integer
    # beyond float raises OverflowError and the finished job is lost.
    body = {**RESULT_BODY, "duration_seconds": 10**400}
    service = ScriptedService(result_responses=[httpx.Response(200, json=body)])

    result = await make_client(service).get_job_result(JOB_ID)

    assert result is not None
    assert (result.text, result.duration_seconds) == (RESULT_BODY["text"], None)


@pytest.mark.parametrize(
    "response, error",
    [
        (httpx.Response(401), CredentialsRejected),
        (httpx.Response(500), UnexpectedStatus),
        (httpx.Response(200, json={"segments": []}), MalformedResponse),
    ],
)
async def test_job_result_failures_are_typed(response, error) -> None:
    service = ScriptedService(result_responses=[response])

    with pytest.raises(error):
        await make_client(service).get_job_result(JOB_ID)


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, None),
        ("not a list", None),
        ([], ()),
        (
            [{"start": 2, "end": 3, "text": "b"}, {"start": 1, "end": 2, "text": "a"}],
            (TranscriptSegment("a", 1.0, 2.0), TranscriptSegment("b", 2.0, 3.0)),
        ),
    ],
)
def test_result_segments_come_back_in_time_order(raw, expected) -> None:
    assert parse_result_segments(raw) == expected


@pytest.mark.parametrize(
    "invalid",
    [
        "garbage",
        {"start": "1", "end": 2, "text": "bad"},
        {"start": 1, "end": True, "text": "bad"},
        {"start": 1, "end": 2},
        {"start": float("nan"), "end": 2, "text": "bad"},
        {"start": 1, "end": float("inf"), "text": "bad"},
        {"start": 10**400, "end": 2, "text": "bad"},
    ],
    ids=[
        "non_object",
        "string_start",
        "boolean_end",
        "no_text",
        "nan_start",
        "infinite_end",
        "integer_beyond_float_start",
    ],
)
def test_one_malformed_segment_drops_the_whole_sidecar(invalid) -> None:
    assert (
        parse_result_segments([{"start": 1, "end": 2, "text": "ok"}, invalid]) is None
    )


def test_result_segments_carry_word_timings_and_drop_malformed_words() -> None:
    parsed = parse_result_segments(
        [
            {
                "start": 0,
                "end": 2,
                "text": "hej du",
                "speaker": "SPEAKER_00",
                "words": [
                    {"word": "hej", "start": 0.1, "end": 0.4, "probability": 0.93},
                    {"word": "du", "start": 0.5, "end": 0.8, "probability": 0.0},
                    {"word": "trasig", "start": "x", "end": 1.0},
                    {"word": "nan", "start": float("nan"), "end": 1.0},
                    {"word": "inf", "start": 1.0, "end": float("inf")},
                    {
                        "word": "osäker",
                        "start": 1.0,
                        "end": 1.2,
                        "probability": float("nan"),
                    },
                    "garbage",
                ],
            },
            {"start": 2, "end": 3, "text": "utan ord", "speaker": ""},
            {"start": 3, "end": 4, "text": "fel typ", "words": "nej"},
        ]
    )

    assert parsed is not None
    assert parsed[0].words == (
        TranscriptWord("hej", 0.1, 0.4, probability=0.93),
        TranscriptWord("du", 0.5, 0.8, probability=0.0),
        TranscriptWord("osäker", 1.0, 1.2, probability=None),
    )
    assert parsed[1].speaker is None
    assert parsed[1].words is None
    assert parsed[2].words is None


@pytest.mark.parametrize("answer", [200, 202, 404])
async def test_cancel_accepts_every_answer_that_leaves_nothing_running(answer) -> None:
    service = ScriptedService(cancel_responses=[httpx.Response(answer)])

    await make_client(service, result_timeout_seconds=1.0).cancel_job(
        JOB_ID, timeout_seconds=10.0
    )

    assert service.cancel_count == 1
    # The caller's stop budget, not the result-download timeout.
    assert service.requests[0].extensions["timeout"]["connect"] == 10.0


@pytest.mark.parametrize(
    "answer, error", [(401, CredentialsRejected), (500, UnexpectedStatus)]
)
async def test_cancel_reports_a_refused_stop(answer, error) -> None:
    service = ScriptedService(cancel_responses=[httpx.Response(answer)])

    with pytest.raises(error):
        await make_client(service).cancel_job(JOB_ID, timeout_seconds=10.0)


@pytest.mark.parametrize(
    ("response", "ready", "accepting", "detail", "base_url"),
    [
        (
            httpx.Response(200, json={"queue_accepting_jobs": True}),
            True,
            True,
            "accepting jobs",
            "http://tolka.test",
        ),
        (
            httpx.Response(200, json={"queue_accepting_jobs": False}),
            True,
            False,
            "queue not accepting jobs",
            "http://tolka.test",
        ),
        (
            httpx.Response(200, json={"status": "ready"}),
            False,
            False,
            "malformed readiness response",
            "http://tolka.test",
        ),
        (
            httpx.Response(200, text="ok"),
            False,
            False,
            "malformed readiness response",
            "http://tolka.test",
        ),
        (httpx.Response(503), False, False, "http 503", "http://tolka.test"),
        (
            httpx.Response(200, json={"queue_accepting_jobs": True}),
            True,
            True,
            "accepting jobs",
            "http://dummy-user:dummy-url-secret@tolka.test",
        ),
        (
            httpx.ConnectError("dummy-readiness-secret"),
            False,
            False,
            "unreachable: ConnectError",
            "http://tolka.test",
        ),
        (
            httpx.Response(503),
            False,
            False,
            "unreachable: InvalidURL",
            "http://tolka.test:invalid-port",
        ),
    ],
    ids=[
        "ready",
        "admission-refused",
        "no-admission-flag",
        "not-json",
        "unavailable",
        "private-url",
        "private-transport-detail",
        "invalid-target-is-not-ready",
    ],
)
async def test_readiness_reports_service_and_admission_state(
    response, ready, accepting, detail, base_url
) -> None:
    service = ScriptedService(ready_responses=[response])

    readiness = await make_client(service, base_url=base_url).check_readiness()

    assert (readiness.ready, readiness.accepting_jobs, readiness.detail) == (
        ready,
        accepting,
        detail,
    )
    if base_url == "http://tolka.test" and service.requests:
        assert service.requests[0].headers["authorization"] == "Bearer devtoken"


@pytest.mark.parametrize(
    ("answer", "reason", "status_code"),
    [
        (httpx.Response(200, json={"queue_accepting_jobs": True}), None, None),
        (httpx.Response(200, json={"queue_accepting_jobs": False}), None, None),
        (httpx.Response(404, text="Not Found"), "http_status", 404),
        (httpx.Response(503, json={"status": "not_ready"}), "http_status", 503),
        (httpx.Response(200, json={"status": "ready"}), "malformed", None),
        (httpx.Response(200, text="<html></html>"), "malformed", None),
        (httpx.ConnectError("dummy-readiness-secret"), "unreachable", None),
        (httpx.ConnectTimeout("dummy-readiness-secret"), "timeout", None),
        (httpx.ReadTimeout("dummy-readiness-secret"), "timeout", None),
    ],
    ids=[
        "ready",
        "admission-refused",
        "wrong-address",
        "not-ready",
        "no-admission-flag",
        "not-json",
        "no-connection",
        "connect-timeout",
        "read-timeout",
    ],
)
async def test_readiness_names_why_it_got_no_usable_answer(
    answer, reason, status_code
) -> None:
    service = ScriptedService(ready_responses=[answer])

    readiness = await make_client(service).check_readiness()

    assert (readiness.reason, readiness.status_code) == (reason, status_code)


async def test_rejected_readiness_credentials_are_a_configuration_error() -> None:
    service = ScriptedService(ready_responses=[httpx.Response(401)])

    with pytest.raises(CredentialsRejected):
        await make_client(service).check_readiness()


@pytest.mark.parametrize(
    "base_url, host",
    [
        ("http://tolka.test", "tolka.test"),
        ("https://dummy-user:dummy-url-secret@tolka.test:8443", "tolka.test:8443"),
        ("http://[::1]:8100/", "[::1]:8100"),
        ("http://tolka.test:invalid-port", None),
    ],
)
def test_destination_host_never_carries_userinfo(base_url, host) -> None:
    assert make_client(ScriptedService(), base_url=base_url).destination_host == host


@pytest.mark.parametrize(
    "retry_after, expected",
    [
        ("2", 2.0),
        ("Sun, 20 Sep 2026 10:00:02 GMT", 2.0),
        ("Sun, 20 Sep 2026 09:59:00 GMT", 0.0),
        ("-3", 0.0),
        ("soon", None),
        ("inf", None),
    ],
)
async def test_retry_after_accepts_seconds_and_http_dates(
    retry_after, expected, monkeypatch
) -> None:
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 20, 10, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(client_module, "datetime", Clock)
    service = ScriptedService(
        submit_responses=[httpx.Response(429, headers={"Retry-After": retry_after})]
    )

    with pytest.raises(SubmissionRefused) as raised:
        await _submit(service)

    assert raised.value.retry_after == expected


def test_the_client_loads_without_flow_code() -> None:
    # The import-linter contract sees static imports only; a package
    # initialiser that loads modules dynamically could still pull Flows in.
    probe = (
        "import sys, eneo.transcription_services.client; "
        "print(sorted(m for m in sys.modules if m.startswith('eneo.flows')))"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).parents[3],
        capture_output=True,
        text=True,
        check=True,
    )
    assert loaded.stdout.strip() == "[]"


@pytest.mark.parametrize(
    "body, identifies_speakers, version",
    [
        ({"queue_accepting_jobs": True}, None, None),
        (
            {
                "queue_accepting_jobs": True,
                "supported_tasks": ["diarize", "align", 7],
                "service_version": "1.4.0",
            },
            True,
            "1.4.0",
        ),
        (
            {"queue_accepting_jobs": True, "supported_tasks": ["transcribe"]},
            False,
            None,
        ),
        ({"queue_accepting_jobs": True, "supported_tasks": "diarize"}, None, None),
        (
            {"queue_accepting_jobs": True, "service_version": "v" * 100},
            None,
            "v" * 64,
        ),
    ],
    ids=[
        "older-service",
        "reports-diarize",
        "reports-no-diarize",
        "not-a-list",
        "long-version",
    ],
)
async def test_readiness_reports_speaker_identification_separately_from_capacity(
    body, identifies_speakers, version
) -> None:
    service = ScriptedService(ready_responses=[httpx.Response(200, json=body)])

    readiness = await make_client(service).check_readiness()

    assert readiness.ready is True
    assert (readiness.identifies_speakers, readiness.service_version) == (
        identifies_speakers,
        version,
    )


@pytest.mark.parametrize(
    ("tasks", "times_words"),
    [
        (None, None),
        (["align", "diarize"], False),
        (["align", "diarize", "timestamp"], True),
        ("timestamp", None),
    ],
    ids=["older-service", "no-timestamp", "reports-timestamp", "not-a-list"],
)
async def test_readiness_reports_whether_the_service_times_words(
    tasks, times_words
) -> None:
    body = {"queue_accepting_jobs": True}
    if tasks is not None:
        body["supported_tasks"] = tasks
    service = ScriptedService(ready_responses=[httpx.Response(200, json=body)])

    readiness = await make_client(service).check_readiness()

    assert readiness.times_words is times_words


async def test_an_unready_service_still_reports_what_it_supports() -> None:
    service = ScriptedService(
        ready_responses=[
            httpx.Response(
                503, json={"status": "not_ready", "supported_tasks": ["diarize"]}
            )
        ]
    )

    readiness = await make_client(service).check_readiness()

    assert (readiness.ready, readiness.identifies_speakers) == (False, True)


async def test_a_readiness_answer_that_never_arrives_is_bounded_in_total() -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json={"queue_accepting_jobs": True})

    client = make_client(ScriptedService(), result_timeout_seconds=0.05)
    client._transport = httpx.MockTransport(slow)

    async with asyncio.timeout(1):
        readiness = await client.check_readiness()

    assert (readiness.ready, readiness.detail, readiness.reason) == (
        False,
        "unreachable: no answer",
        "timeout",
    )
