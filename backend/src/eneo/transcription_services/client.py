"""Client for the native transcription-service jobs API.

A native service (Vemsa, or any server speaking its protocol) works on an
uploaded recording as an asynchronous job:

* ``POST /v1/jobs`` takes the audio and form fields and answers 202 with a job id;
* ``GET /v1/jobs/{id}`` reports the job's status, stage and queue position;
* ``GET /v1/jobs/{id}/result`` returns the transcript once the job completed;
* ``DELETE /v1/jobs/{id}`` asks the service to stop a job;
* authenticated ``GET /v1/health/ready`` reports whether it would admit a job.

Every method sends one request and reports every failure as a
``TranscriptionServiceError``. Waiting, deadlines and cancellation on behalf of
a caller belong to the caller, so the client keeps no state between calls.
Error messages never carry the endpoint URL, the credential or transport text,
any of which can contain the other two.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Any, BinaryIO, NoReturn, cast
from uuid import uuid4

import httpx

from eneo.files.transcript import (
    TranscriptSegment,
    TranscriptWord,
)
from eneo.main.logging import get_logger
from eneo.transcription_services.models import TranscriptionOperation

logger = get_logger(__name__)

JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"

SERVICE_REASON_MAX_CHARS = 512
_STAGE_MAX_CHARS = 128
_SERVICE_VERSION_MAX_CHARS = 64

# Failures after the upload started: the service may have admitted the job
# even though its answer never arrived.
_RESPONSE_LOST = (
    httpx.WriteError,
    httpx.ReadError,
    httpx.WriteTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)


class JobFailureKind(StrEnum):
    """Why the service failed a job; the protocol's closed set."""

    INPUT = "input"
    CAPACITY = "capacity"
    PROVIDER = "provider"
    INTERNAL = "internal"
    CANCELLED = "cancelled"


class TranscriptionServiceError(Exception):
    """A request to the service failed. The message is safe to log."""


class RequestFailed(TranscriptionServiceError):
    """No HTTP response arrived: the connection, request or transfer failed."""

    def __init__(self, error_type: str) -> None:
        super().__init__(f"request failed: {error_type}")
        self.error_type = error_type


class UnexpectedStatus(TranscriptionServiceError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"http {status_code}")
        self.status_code = status_code


class MalformedResponse(TranscriptionServiceError):
    pass


class CredentialsRejected(TranscriptionServiceError):
    def __init__(self) -> None:
        super().__init__("the service rejected the credentials")


class SubmissionRefused(TranscriptionServiceError):
    """The service is at capacity; the same submission may be retried."""

    def __init__(self, retry_after: float | None, service_reason: str | None) -> None:
        super().__init__("the service refused the job for now")
        self.retry_after = retry_after
        self.service_reason = service_reason


class SubmissionRejected(TranscriptionServiceError):
    """The service will not run this request: its input is invalid."""

    def __init__(self, service_reason: str | None) -> None:
        super().__init__("the service rejected the job's input")
        self.service_reason = service_reason


class SubmissionOutcomeUnknown(TranscriptionServiceError):
    """The upload began but its answer was lost; the job may exist."""


class JobNotFound(TranscriptionServiceError):
    """The service no longer knows the job: purged, or never stored."""


@dataclass(frozen=True, slots=True)
class TranscriptionJobRequest:
    """The form fields of one job, checked when built so that an invalid
    request fails before anything is recorded or sent."""

    operation: TranscriptionOperation
    language: str | None
    diarize: bool = True
    # A diarize job labels these instead of transcribing the audio itself.
    words: Sequence[TranscriptWord] | None = None
    segments: Sequence[TranscriptSegment] | None = None
    # The model that produced a diarize job's transcript; the service echoes
    # it in the result.
    model: str | None = None
    max_speakers: int | None = None

    def __post_init__(self) -> None:
        if self.operation is TranscriptionOperation.DIARIZE:
            if self.segments and any(
                segment.speaker_attribution or segment.overlap_ids
                for segment in self.segments
            ):
                raise ValueError(
                    "Reviewed transcripts require explicit re-diarization and decision invalidation."
                )
            if not self.words and not self.segments:
                raise ValueError("A diarize job needs a timestamped transcript.")
        if self.max_speakers is not None:
            _require_positive_speaker_bound(self.max_speakers)


@dataclass(frozen=True, slots=True)
class TranscriptionJobStatus:
    """One answer of ``GET /v1/jobs/{id}``."""

    status: str
    stage: str | None = None
    queue_position: int | None = None
    failure_kind: JobFailureKind | None = None
    service_reason: str | None = None

    def describe(self) -> str:
        if self.queue_position is not None:
            return f"{self.status} (position {self.queue_position})"
        if self.stage is not None and self.stage != self.status:
            return f"{self.status}/{self.stage}"
        return self.status


@dataclass(frozen=True, slots=True)
class TranscriptionJobResult:
    """The structured result of one completed job."""

    text: str
    duration_seconds: float | None
    model: str | None
    language: str | None
    # How the service placed words in time for speaker labelling, when it
    # reports it. A diarize job is expected to report "forced"; segment_split
    # and segment_only mean it fell back to labelling whole segments.
    alignment: str | None = None
    # The service's segments behind ``text``, one per rendered line, with the
    # same speaker labels. None when the service sent none or a malformed list.
    segments: tuple[TranscriptSegment, ...] | None = None
    speaker_review: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ServiceReadiness:
    """Authenticated ``GET /v1/health/ready`` outcome for this client's token.

    ``identifies_speakers`` is whether the service lists ``diarize`` among
    its supported tasks; None when it reports no task list (an older
    deployment). Whether the service is up or has room says nothing about
    what it supports.
    """

    ready: bool
    accepting_jobs: bool
    detail: str
    identifies_speakers: bool | None = None
    service_version: str | None = None


class TranscriptionServiceClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        submit_timeout_seconds: float,
        result_timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
        include_speaker_review: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.submit_timeout_seconds = submit_timeout_seconds
        self.result_timeout_seconds = result_timeout_seconds
        self._transport = transport
        self.include_speaker_review = include_speaker_review

    @property
    def destination_host(self) -> str | None:
        """``host[:port]`` of the service without userinfo; None when the URL
        does not parse."""
        try:
            return httpx.URL(self.base_url).netloc.decode("ascii") or None
        except httpx.InvalidURL:
            return None

    async def submit_job(
        self,
        request: TranscriptionJobRequest,
        *,
        filename: str,
        mimetype: str,
        payload: BinaryIO,
        idempotency_key: str | None = None,
    ) -> str:
        """Upload one recording as a job and return its id.

        Admission is known only when the service answers: a lost answer after
        the upload began raises ``SubmissionOutcomeUnknown``.
        """
        data = _form_fields(request, include_speaker_review=self.include_speaker_review)
        logger.info(
            "remote_transcription.speaker_prior mode=%s",
            "maximum" if "max_speakers" in data else "automatic",
        )
        try:
            async with self._http(timeout=self.submit_timeout_seconds) as http:
                response = await http.post(
                    f"{self.base_url}/v1/jobs",
                    headers={
                        **self._auth,
                        "Idempotency-Key": idempotency_key or str(uuid4()),
                    },
                    files={"file": (filename, payload, mimetype)},
                    data=data,
                )
        except _RESPONSE_LOST as exc:
            raise SubmissionOutcomeUnknown(
                f"submission answer lost: {type(exc).__name__}"
            ) from exc
        except Exception as exc:
            raise RequestFailed(type(exc).__name__) from exc

        if response.status_code == 202:
            job_id = _json_object(response).get("job_id")
            if not isinstance(job_id, str) or not job_id:
                raise MalformedResponse("accepted job without a job id")
            logger.info(
                "remote_transcription.submitted job_id=%s filename=%s",
                job_id,
                filename,
            )
            return job_id
        _raise_for_submit_status(response)

    async def get_job_status(self, job_id: str) -> TranscriptionJobStatus:
        response = await self._get(f"/v1/jobs/{job_id}")
        if response.status_code == 200:
            return _job_status(_json_object(response))
        if response.status_code == 401:
            raise CredentialsRejected()
        if response.status_code == 404:
            raise JobNotFound("job not found")
        raise UnexpectedStatus(response.status_code)

    async def get_job_result(self, job_id: str) -> TranscriptionJobResult | None:
        """The completed job's result; None while the service still answers
        409 because the job is not complete."""
        response = await self._get(f"/v1/jobs/{job_id}/result")
        if response.status_code == 409:
            return None
        if response.status_code == 401:
            raise CredentialsRejected()
        if response.status_code != 200:
            raise UnexpectedStatus(response.status_code)
        return _job_result(_json_object(response))

    async def cancel_job(self, job_id: str, *, timeout_seconds: float) -> None:
        """Ask the service to stop a job. 202 (stopping), 200 (already
        terminal) and 404 (no longer known) all leave nothing running.

        The caller sets the budget: a stop is sent while the caller is already
        leaving, often after its own deadline, so the result-download timeout
        is not the right bound.
        """
        try:
            async with self._http(timeout=timeout_seconds) as http:
                response = await http.delete(
                    f"{self.base_url}/v1/jobs/{job_id}", headers=self._auth
                )
        except Exception as exc:
            raise RequestFailed(type(exc).__name__) from exc
        logger.info(
            "remote_transcription.cancel job_id=%s status_code=%s",
            job_id,
            response.status_code,
        )
        if response.status_code == 401:
            raise CredentialsRejected()
        if response.status_code not in (200, 202, 404):
            raise UnexpectedStatus(response.status_code)

    async def check_readiness(self) -> ServiceReadiness:
        """Is the service up, and would it admit a job from this token?

        503 means the service is down. 200 with ``queue_accepting_jobs`` false
        means a submit would be refused (the answer is scoped to this token, so
        it also reflects this client's active-job limit). Only rejected
        credentials raise: they are a configuration error, not a state. The
        whole answer must arrive within ``result_timeout_seconds``; httpx
        bounds each read, not a response that trickles in.
        """
        try:
            async with asyncio.timeout(self.result_timeout_seconds):
                response = await self._get("/v1/health/ready")
        except RequestFailed as exc:
            return ServiceReadiness(
                ready=False,
                accepting_jobs=False,
                detail=f"unreachable: {exc.error_type}",
            )
        except TimeoutError:
            return ServiceReadiness(
                ready=False, accepting_jobs=False, detail="unreachable: no answer"
            )
        if response.status_code == 401:
            raise CredentialsRejected()
        body = _json_object(response)
        identifies_speakers = _identifies_speakers(body.get("supported_tasks"))
        version = body.get("service_version")
        service_version = (
            version[:_SERVICE_VERSION_MAX_CHARS] if isinstance(version, str) else None
        )
        if response.status_code != 200:
            return ServiceReadiness(
                ready=False,
                accepting_jobs=False,
                detail=f"http {response.status_code}",
                identifies_speakers=identifies_speakers,
                service_version=service_version,
            )
        accepting_jobs = body.get("queue_accepting_jobs")
        if not isinstance(accepting_jobs, bool):
            # The protocol's readiness answer always carries the admission
            # flag; an answer without it is not a service Eneo can rely on.
            return ServiceReadiness(
                ready=False,
                accepting_jobs=False,
                detail="malformed readiness response",
                identifies_speakers=identifies_speakers,
                service_version=service_version,
            )
        return ServiceReadiness(
            ready=True,
            accepting_jobs=accepting_jobs,
            detail="accepting jobs" if accepting_jobs else "queue not accepting jobs",
            identifies_speakers=identifies_speakers,
            service_version=service_version,
        )

    @property
    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _http(self, *, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    async def _get(self, path: str) -> httpx.Response:
        try:
            async with self._http(timeout=self.result_timeout_seconds) as http:
                return await http.get(f"{self.base_url}{path}", headers=self._auth)
        except Exception as exc:
            raise RequestFailed(type(exc).__name__) from exc


def parse_result_segments(raw: object) -> tuple[TranscriptSegment, ...] | None:
    """A result's segment sidecar in time order; None unless every entry is
    well formed.

    Segments are the structured view of the result's rendered lines. A service
    that sends none, or a list with any malformed entry, still produced a
    usable transcript: the caller keeps the text and drops the sidecar.
    """
    if not isinstance(raw, list):
        return None
    segments: list[TranscriptSegment] = []
    for entry in cast(list[object], raw):
        if not isinstance(entry, dict):
            return None
        item = cast(dict[str, object], entry)
        text = item.get("text")
        start = _finite_number(item.get("start"))
        end = _finite_number(item.get("end"))
        if not isinstance(text, str) or start is None or end is None:
            return None
        speaker = item.get("speaker")
        attribution = item.get("speaker_attribution")
        overlap_ids = item.get("overlap_ids")
        segments.append(
            TranscriptSegment(
                text=text,
                start=start,
                end=end,
                speaker=speaker if isinstance(speaker, str) and speaker else None,
                words=_parse_words(item.get("words")),
                speaker_attribution=attribution
                if isinstance(attribution, str)
                else None,
                overlap_ids=tuple(
                    value
                    for value in cast(list[object], overlap_ids)
                    if isinstance(value, str)
                )
                if isinstance(overlap_ids, list)
                else (),
            )
        )
    segments.sort(key=lambda segment: (segment.start, segment.end))
    return tuple(segments)


def _require_positive_speaker_bound(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("max_speakers must be a positive integer")


def _form_fields(
    request: TranscriptionJobRequest, *, include_speaker_review: bool
) -> dict[str, str]:
    data: dict[str, str] = {
        "language": request.language or "auto",
        "diarize": "true" if request.diarize else "false",
    }
    if include_speaker_review and request.diarize:
        data["include_speaker_review"] = "true"
    if request.operation is TranscriptionOperation.DIARIZE:
        data["task"] = request.operation.value
        if request.words:
            data["words"] = json.dumps(
                [
                    {"word": word.word, "start": word.start, "end": word.end}
                    for word in request.words
                ],
                separators=(",", ":"),
            )
        if request.segments:
            data["segments"] = json.dumps(
                [
                    {"text": seg.text, "start": seg.start, "end": seg.end}
                    for seg in request.segments
                ],
                separators=(",", ":"),
            )
    if request.model:
        data["model"] = request.model
    if request.diarize and request.max_speakers is not None:
        data["max_speakers"] = str(request.max_speakers)
    return data


def _raise_for_submit_status(response: httpx.Response) -> NoReturn:
    if response.status_code == 401:
        raise CredentialsRejected()
    if response.status_code == 429 or (
        response.status_code == 503 and "Retry-After" in response.headers
    ):
        raise SubmissionRefused(
            _retry_after_seconds(response), _response_detail(response)
        )
    if response.status_code in (413, 422):
        raise SubmissionRejected(_response_detail(response))
    raise UnexpectedStatus(response.status_code)


def _job_status(body: dict[str, object]) -> TranscriptionJobStatus:
    status = body.get("status")
    if not isinstance(status, str):
        raise MalformedResponse("job status without a status")
    stage = body.get("stage")
    queue_position = body.get("queue_position")
    return TranscriptionJobStatus(
        status=status,
        stage=stage[:_STAGE_MAX_CHARS] if isinstance(stage, str) else None,
        queue_position=(
            queue_position
            if isinstance(queue_position, int)
            and not isinstance(queue_position, bool)
            and queue_position >= 0
            else None
        ),
        failure_kind=_failure_kind(body.get("failure_kind")),
        service_reason=_bounded_reason(body.get("error")),
    )


def _job_result(body: dict[str, object]) -> TranscriptionJobResult:
    text = body.get("text")
    if not isinstance(text, str):
        raise MalformedResponse("job result without text")
    duration = body.get("duration_seconds")
    model = body.get("model")
    language = body.get("language")
    alignment = body.get("alignment")
    review = body.get("speaker_review")
    return TranscriptionJobResult(
        text=text,
        duration_seconds=float(duration)
        if isinstance(duration, (int, float))
        else None,
        model=model if isinstance(model, str) else None,
        language=language if isinstance(language, str) else None,
        alignment=alignment if isinstance(alignment, str) else None,
        segments=parse_result_segments(body.get("segments")),
        speaker_review=cast(dict[str, Any], review)
        if isinstance(review, dict)
        else None,
    )


def _identifies_speakers(raw: object) -> bool | None:
    """Whether the reported task list includes ``diarize``; None without a list."""
    if not isinstance(raw, list):
        return None
    return TranscriptionOperation.DIARIZE.value in cast(list[object], raw)


def _failure_kind(raw: object) -> JobFailureKind | None:
    """A service that predates typed failures sends none; an unknown kind is
    treated the same rather than guessed from the reason text."""
    try:
        return JobFailureKind(raw)
    except (ValueError, TypeError):
        return None


def _bounded_reason(raw: object) -> str | None:
    return raw[:SERVICE_REASON_MAX_CHARS] if isinstance(raw, str) else None


def _response_detail(response: httpx.Response) -> str | None:
    """FastAPI's ``detail``: a message, or the first validation error's."""
    detail = _json_object(response).get("detail")
    if isinstance(detail, list):
        first = cast(list[object], detail)[0] if detail else None
        detail = (
            cast(dict[str, object], first).get("msg")
            if isinstance(first, dict)
            else None
        )
    return _bounded_reason(detail)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    delay: float
    try:
        delay = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0.0, delay) if math.isfinite(delay) else None


def _parse_words(raw: object) -> tuple[TranscriptWord, ...] | None:
    """Word timings of a result segment; malformed words are dropped.

    A segment without a usable word list keeps ``words=None`` so a reader
    falls back to the segment window rather than trusting partial timings.
    """
    if not isinstance(raw, list):
        return None
    words: list[TranscriptWord] = []
    for entry in cast(list[object], raw):
        if not isinstance(entry, dict):
            continue
        item = cast(dict[str, object], entry)
        word = item.get("word")
        start = _finite_number(item.get("start"))
        end = _finite_number(item.get("end"))
        if not isinstance(word, str) or start is None or end is None:
            continue
        words.append(
            TranscriptWord(
                word=word,
                start=start,
                end=end,
                probability=_finite_number(item.get("probability")),
            )
        )
    return tuple(words)


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _json_object(response: httpx.Response) -> dict[str, object]:
    try:
        body = response.json()
    except ValueError:
        return {}
    if isinstance(body, dict):
        return cast(dict[str, object], body)
    return {}
