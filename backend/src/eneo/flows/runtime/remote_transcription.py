"""External transcription service client for flow audio steps.

Eneo owns transcription administration (flow config, model governance, usage
accounting) but delegates the transcription itself to an external service with
an async job API: submit the original audio bytes as a multipart job, poll the
job until it reaches a terminal state, then fetch the structured result. The
service transcribes and diarizes server-side, so its rendered transcript
(speaker-labeled, timestamped lines) is returned verbatim — no client-side
chunking or timestamp headers.

Configured through deployment settings (``flow_transcription_service_url`` and
friends); unset means flows use the model-registry transcription path. Polling
is a plain idle await: flow execution runs on its own dedicated ARQ worker, so
a waiting job holds nothing but its job slot. A job eneo stops waiting for
(run cancelled, worker interrupted, poll deadline) is cancelled service-side
so it does not keep burning GPU time for a result nobody will read.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Literal, NoReturn, cast
from urllib.parse import urlsplit
from uuid import UUID

import audioread  # pyright: ignore[reportMissingTypeStubs]
import httpx
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from eneo.files.audio import AudioMimeTypes
from eneo.files.transcriber import TranscribedAudio
from eneo.flows.runtime.run_cancellation import (
    FlowStepCancelledError,
    RunCancelProbe,
    current_run_cancel_probe,
)
from eneo.main.exceptions import (
    APIKeyNotConfiguredException,
    OpenAIException,
    ProviderRejectedRequestException,
)
from eneo.main.logging import get_logger
from eneo.model_providers.domain.provider_call_observer import (
    ProviderCallObserverError,
    TranscriptionCallResultFacts,
    build_transcription_call_request_facts,
)
from eneo.model_providers.infrastructure import litellm_transport
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    TranscriptSegment,
    TranscriptWord,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from eneo.files.file_models import File
    from eneo.main.config import Settings
    from eneo.model_providers.domain.provider_call_observer import (
        ProviderCallObserver,
    )
    from eneo.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )

logger = get_logger(__name__)

# Observer identity for calls delegated to the external service. The result
# facts record the model the service actually ran.
REMOTE_TRANSCRIPTION_PROVIDER = "external"

# Consecutive poll failures tolerated before the job's outcome is declared
# unknown. A single dropped poll must not fail a job the service may still
# complete.
_MAX_CONSECUTIVE_POLL_FAILURES = 5

_TERMINAL_COMPLETED = "completed"
_TERMINAL_FAILED = "failed"
_TERMINAL_CANCELLED = "cancelled"

# Cancelling a job is best effort and must not hold up the caller's own
# cancellation for long.
_CANCEL_TIMEOUT_SECONDS = 10.0

# Job kinds the service accepts: transcribe end to end, or label speakers on a
# transcript the caller produced (words with absolute timestamps).
JobTask = Literal["transcribe", "diarize"]


class RemoteTranscriptionCancelledException(OpenAIException):
    """The service reported the job cancelled before it produced a result."""


@dataclass(frozen=True, slots=True)
class RemoteJobStatus:
    """One poll of ``GET /v1/jobs/{id}``."""

    status: str
    stage: str | None = None
    queue_position: int | None = None

    def describe(self) -> str:
        if self.queue_position is not None:
            return f"{self.status} (position {self.queue_position})"
        if self.stage is not None and self.stage != self.status:
            return f"{self.status}/{self.stage}"
        return self.status


@dataclass(frozen=True, slots=True)
class RemoteServiceReadiness:
    """Authenticated ``GET /v1/health/ready`` outcome for this client."""

    ready: bool
    accepting_jobs: bool
    detail: str


@dataclass(frozen=True, slots=True)
class RemoteTranscriptionResult:
    """The service's structured result for one completed job."""

    text: str
    duration_seconds: float | None
    model: str | None
    language: str | None
    # How the service placed words in time for speaker labelling, when it
    # reports it. A diarize job is expected to report "forced"; segment_split
    # and segment_only mean it fell back to labelling whole segments.
    alignment: str | None = None
    # The service's segments behind ``text``, one per rendered line, with the
    # same speaker labels. None when the service sent none.
    segments: tuple[TranscriptSegment, ...] | None = None


class RemoteTranscriptionClient:
    """Async job API client: submit multipart, poll status, fetch result.

    Maps every service failure into the canonical typed provider-error
    disposition; callers never see raw HTTP errors.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        submit_timeout_seconds: float,
        poll_interval_seconds: float,
        poll_timeout_seconds: float,
        result_timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.submit_timeout_seconds = submit_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.poll_timeout_seconds = poll_timeout_seconds
        self.result_timeout_seconds = result_timeout_seconds
        self._transport = transport

    def _http_client(self, *, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def submit(
        self,
        *,
        filename: str,
        mimetype: str,
        payload: BinaryIO,
        language: str | None,
        diarize: bool = True,
        task: JobTask = "transcribe",
        words: "Sequence[TranscriptWord] | None" = None,
        segments: "Sequence[TranscriptSegment] | None" = None,
        model: str | None = None,
        max_speakers: int | None = None,
    ) -> str:
        """Submit one audio file as a job and return its job id.

        ``task="diarize"`` sends the caller's word-timestamped transcript as a
        JSON part; the service then only adds speaker labels. ``model`` is
        echoed back by the service in its result and names what transcribed.

        The service admits or rejects before reading the body (queue-full is a
        pre-body 429), so a connection torn down mid-upload is treated as the
        rate limiting it usually is rather than as an unknown outcome.
        """
        data: dict[str, str] = {
            "language": language or "auto",
            "diarize": "true" if diarize else "false",
        }
        if task == "diarize":
            if not words and not segments:
                raise ValueError("A diarize job needs a timestamped transcript.")
            data["task"] = task
            if words:
                data["words"] = json.dumps(
                    [
                        {"word": word.word, "start": word.start, "end": word.end}
                        for word in words
                    ],
                    separators=(",", ":"),
                )
            if segments:
                data["segments"] = json.dumps(
                    [
                        {"text": seg.text, "start": seg.start, "end": seg.end}
                        for seg in segments
                    ],
                    separators=(",", ":"),
                )
        if model:
            data["model"] = model
        if diarize and max_speakers is not None and max_speakers >= 1:
            data["max_speakers"] = str(max_speakers)
        try:
            async with self._http_client(timeout=self.submit_timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/v1/jobs",
                    headers=self._headers,
                    files={"file": (filename, payload, mimetype)},
                    data=data,
                )
        except httpx.WriteError as exc:
            # The service hangs up mid-upload when it refuses admission; the
            # refusal status is unreadable, so classify by the only admission
            # rule that closes connections early.
            raise OpenAIException(
                litellm_transport.RATE_LIMIT_MESSAGE,
                code="provider_rate_limited",
                details={"reason": "provider_rate_limited", "retryable": True},
            ) from exc
        except Exception as exc:
            self._raise_transport_error(exc)

        if response.status_code == 202:
            job_id = self._parse_job_id(response)
            logger.info(
                "remote_transcription.submitted job_id=%s filename=%s",
                job_id,
                filename,
            )
            return job_id
        self._raise_for_submit_status(response)

    async def wait_for_result(
        self,
        job_id: str,
        *,
        run_cancelled: RunCancelProbe | None = None,
    ) -> RemoteTranscriptionResult:
        """Poll the job until terminal, then fetch its structured result.

        ``run_cancelled`` is asked once per poll tick; when it answers true the
        job is cancelled service-side and ``FlowStepCancelledError`` is raised
        so the executor records the step as cancelled rather than failed.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.poll_timeout_seconds
        consecutive_failures = 0
        last_seen: RemoteJobStatus | None = None

        async with self._http_client(timeout=self.result_timeout_seconds) as client:
            while True:
                if loop.time() >= deadline:
                    await self.cancel(job_id, client=client)
                    raise OpenAIException(
                        litellm_transport.PROVIDER_ERROR_MESSAGE,
                        code="provider_error",
                        details={"reason": "provider_error", "retryable": True},
                    )
                if run_cancelled is not None and await _probe_quietly(
                    run_cancelled, job_id=job_id
                ):
                    await self.cancel(job_id, client=client)
                    raise FlowStepCancelledError(
                        "Run was cancelled while waiting for transcription."
                    )
                try:
                    seen = await self._poll_once(client, job_id)
                except (
                    APIKeyNotConfiguredException,
                    ProviderRejectedRequestException,
                    OpenAIException,
                ):
                    raise
                except Exception:
                    consecutive_failures += 1
                    if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                        raise OpenAIException(
                            litellm_transport.PROVIDER_ERROR_MESSAGE,
                            code="provider_error",
                            details={
                                "reason": "provider_error",
                                "retryable": True,
                            },
                        ) from None
                    await asyncio.sleep(self.poll_interval_seconds)
                    continue

                consecutive_failures = 0
                if seen != last_seen:
                    logger.info(
                        "remote_transcription.progress job_id=%s state=%s",
                        job_id,
                        seen.describe(),
                    )
                    last_seen = seen
                if seen.status == _TERMINAL_COMPLETED:
                    result = await self._fetch_result(client, job_id)
                    if result is not None:
                        return result
                    # A raced 409: the status flapped; keep polling.
                elif seen.status == _TERMINAL_FAILED:
                    raise ProviderRejectedRequestException(
                        litellm_transport.INVALID_REQUEST_MESSAGE,
                        code="provider_rejected_request",
                        details={
                            "reason": "provider_rejected_request",
                            "retryable": False,
                        },
                    )
                elif seen.status == _TERMINAL_CANCELLED:
                    # Cancelled service-side (operator, retention, or a cancel
                    # eneo sent that raced this poll). No result will come; the
                    # audio was not transcribed, so a re-run is reasonable.
                    raise RemoteTranscriptionCancelledException(
                        litellm_transport.PROVIDER_ERROR_MESSAGE,
                        code="provider_error",
                        details={"reason": "provider_cancelled", "retryable": True},
                    )
                await asyncio.sleep(self.poll_interval_seconds)

    async def cancel(
        self, job_id: str, *, client: httpx.AsyncClient | None = None
    ) -> None:
        """Ask the service to stop a job eneo will not wait for.

        Best effort and idempotent on the service side (202 for an active job,
        200 for one already terminal, 404 for one it no longer knows). Nothing
        here raises: the caller is already on its way out and the worst case
        is the job running to completion unread, which is what happened before
        cancellation existed.
        """

        async def _send(http: httpx.AsyncClient) -> None:
            response = await http.delete(
                f"{self.base_url}/v1/jobs/{job_id}", headers=self._headers
            )
            logger.info(
                "remote_transcription.cancel job_id=%s status_code=%s",
                job_id,
                response.status_code,
            )

        try:
            async with asyncio.timeout(_CANCEL_TIMEOUT_SECONDS):
                if client is not None:
                    await _send(client)
                else:
                    async with self._http_client(
                        timeout=_CANCEL_TIMEOUT_SECONDS
                    ) as own:
                        await _send(own)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "remote_transcription.cancel_failed job_id=%s", job_id, exc_info=True
            )

    async def check_readiness(self) -> RemoteServiceReadiness:
        """Authenticated pre-flight: is the service up, and would it admit a job?

        503 means the service is down. 200 with ``queue_accepting_jobs`` false
        means a submit would be refused with 429 (the check is scoped to this
        client's token, so it also reflects this client's active-job limit).
        Transport failures are reported as not ready rather than raised; only
        bad credentials raise, since that is a configuration error.
        """
        try:
            async with self._http_client(timeout=self.result_timeout_seconds) as client:
                response = await client.get(
                    f"{self.base_url}/v1/health/ready", headers=self._headers
                )
        except Exception as exc:
            return RemoteServiceReadiness(
                ready=False, accepting_jobs=False, detail=f"unreachable: {exc!r}"
            )
        if response.status_code == 401:
            self._raise_bad_credentials()
        if response.status_code != 200:
            return RemoteServiceReadiness(
                ready=False,
                accepting_jobs=False,
                detail=f"http {response.status_code}",
            )
        body = _json_object(response)
        accepting = body.get("queue_accepting_jobs")
        accepting_jobs = accepting if isinstance(accepting, bool) else True
        return RemoteServiceReadiness(
            ready=True,
            accepting_jobs=accepting_jobs,
            detail="accepting jobs" if accepting_jobs else "queue not accepting jobs",
        )

    async def _poll_once(
        self, client: httpx.AsyncClient, job_id: str
    ) -> RemoteJobStatus:
        response = await client.get(
            f"{self.base_url}/v1/jobs/{job_id}", headers=self._headers
        )
        if response.status_code == 200:
            body = _json_object(response)
            status = body.get("status")
            if not isinstance(status, str):
                raise OpenAIException(
                    litellm_transport.PROVIDER_ERROR_MESSAGE,
                    code="provider_error",
                    details={"reason": "provider_error", "retryable": True},
                )
            stage = body.get("stage")
            queue_position = body.get("queue_position")
            return RemoteJobStatus(
                status=status,
                stage=stage if isinstance(stage, str) else None,
                queue_position=(
                    queue_position
                    if isinstance(queue_position, int)
                    and not isinstance(queue_position, bool)
                    else None
                ),
            )
        if response.status_code == 401:
            self._raise_bad_credentials()
        if response.status_code == 404:
            # The job vanished (purged, or the service lost it). The audio may
            # already have been transcribed and billed.
            raise OpenAIException(
                litellm_transport.PROVIDER_ERROR_MESSAGE,
                code="provider_error",
                details={"reason": "provider_error", "retryable": True},
            )
        response.raise_for_status()
        raise AssertionError("unreachable: non-error status not handled")

    async def _fetch_result(
        self, client: httpx.AsyncClient, job_id: str
    ) -> RemoteTranscriptionResult | None:
        response = await client.get(
            f"{self.base_url}/v1/jobs/{job_id}/result", headers=self._headers
        )
        if response.status_code == 409:
            return None
        if response.status_code == 401:
            self._raise_bad_credentials()
        if response.status_code != 200:
            raise OpenAIException(
                litellm_transport.PROVIDER_ERROR_MESSAGE,
                code="provider_error",
                details={"reason": "provider_error", "retryable": True},
            )
        body = _json_object(response)
        text = body.get("text")
        if not isinstance(text, str):
            raise OpenAIException(
                litellm_transport.PROVIDER_ERROR_MESSAGE,
                code="provider_error",
                details={"reason": "provider_error", "retryable": True},
            )
        duration = body.get("duration_seconds")
        model = body.get("model")
        language = body.get("language")
        alignment = body.get("alignment")
        return RemoteTranscriptionResult(
            text=text,
            duration_seconds=float(duration)
            if isinstance(duration, (int, float))
            else None,
            model=model if isinstance(model, str) else None,
            language=language if isinstance(language, str) else None,
            alignment=alignment if isinstance(alignment, str) else None,
            segments=_parse_result_segments(body.get("segments")),
        )

    def _parse_job_id(self, response: httpx.Response) -> str:
        job_id = _json_object(response).get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise OpenAIException(
                litellm_transport.PROVIDER_ERROR_MESSAGE,
                code="provider_error",
                details={"reason": "provider_error", "retryable": True},
            )
        return job_id

    def _raise_for_submit_status(self, response: httpx.Response) -> NoReturn:
        if response.status_code == 401:
            self._raise_bad_credentials()
        if response.status_code == 429:
            raise OpenAIException(
                litellm_transport.RATE_LIMIT_MESSAGE,
                code="provider_rate_limited",
                details={"reason": "provider_rate_limited", "retryable": True},
            )
        if response.status_code in (413, 422):
            raise ProviderRejectedRequestException(
                litellm_transport.INVALID_REQUEST_MESSAGE,
                code="provider_rejected_request",
                details={
                    "reason": "provider_rejected_request",
                    "retryable": False,
                },
            )
        raise OpenAIException(
            litellm_transport.PROVIDER_ERROR_MESSAGE,
            code="provider_error",
            details={"reason": "provider_error", "retryable": True},
        )

    def _raise_bad_credentials(self) -> NoReturn:
        raise APIKeyNotConfiguredException(
            "Invalid API credentials for the external transcription service. "
            "Please verify FLOW_TRANSCRIPTION_SERVICE_API_KEY."
        )

    def _raise_transport_error(self, exc: Exception) -> NoReturn:
        if litellm_transport.is_provider_unavailable_error(exc):
            litellm_transport.raise_provider_unavailable(exc)
        raise OpenAIException(
            litellm_transport.PROVIDER_ERROR_MESSAGE,
            code="provider_error",
            details={"reason": "provider_error", "retryable": True},
        ) from exc


class RemoteFlowTranscriber:
    """Flow-step transcriber backed by the external transcription service.

    Implements the same call surface ``Transcriber.transcribe`` exposes to the
    flow audio step (``FlowStepTranscriber``), so the runtime swaps engines at
    wiring time without touching step execution. The configured transcription
    model stays the governance anchor; it is not what transcribes.
    """

    def __init__(self, client: RemoteTranscriptionClient) -> None:
        self.client = client
        host = urlsplit(client.base_url).netloc or "transcription-service"
        self._requested_model = f"{REMOTE_TRANSCRIPTION_PROVIDER}/{host}"

    async def transcribe(
        self,
        file: "File",
        transcription_model: "TranscriptionModel",
        *,
        language: str | None = None,
        diarize: bool = True,
        persist_cache_to_file: bool = True,
        observer: "ProviderCallObserver | None" = None,
        max_speakers: int | None = None,
    ) -> TranscribedAudio:
        result, audio_seconds = await self._run_job(
            file,
            language=language,
            diarize=diarize,
            task="transcribe",
            words=None,
            segments=None,
            model=None,
            observer=observer,
            max_speakers=max_speakers,
        )
        return TranscribedAudio(
            text=result.text,
            duration_seconds=result.duration_seconds or audio_seconds,
            transcript_segments=result.segments,
            diarization="external" if diarize else None,
            alignment=result.alignment if diarize else None,
        )

    async def label_speakers(
        self,
        file: "File",
        *,
        words: "Sequence[TranscriptWord] | None",
        model_name: str,
        segments: "Sequence[TranscriptSegment] | None" = None,
        language: str | None = None,
        observer: "ProviderCallObserver | None" = None,
        max_speakers: int | None = None,
    ) -> RemoteTranscriptionResult:
        """Have the service add speaker labels to a transcript produced elsewhere.

        The audio is uploaded again for diarization; the transcript comes back
        rendered with the same speaker-labelled lines a full job produces.
        """
        result, _ = await self._run_job(
            file,
            language=language,
            diarize=True,
            task="diarize",
            words=words,
            segments=segments,
            model=model_name,
            observer=observer,
            max_speakers=max_speakers,
        )
        # A service that predates diarize jobs ignores the unknown fields and
        # transcribes the audio itself with its own model. The echoed model is
        # the only signal, and that text must not replace the flow's transcript.
        if result.model != model_name:
            logger.error(
                "remote_transcription.diarize_unsupported expected_model=%s got=%s",
                model_name,
                result.model,
            )
            raise OpenAIException(
                litellm_transport.PROVIDER_ERROR_MESSAGE,
                code="provider_error",
                details={"reason": "diarize_task_unsupported", "retryable": False},
            )
        return result

    async def _run_job(
        self,
        file: "File",
        *,
        language: str | None,
        diarize: bool,
        task: JobTask,
        words: "Sequence[TranscriptWord] | None",
        segments: "Sequence[TranscriptSegment] | None",
        model: str | None,
        observer: "ProviderCallObserver | None",
        max_speakers: int | None = None,
    ) -> tuple[RemoteTranscriptionResult, float]:
        mimetype: str = file.mimetype or ""
        if file.blob is None or not AudioMimeTypes.has_value(mimetype):
            raise ValueError("File needs to be an audio file")

        # The original bytes are sent as-is; the service decodes server-side.
        # A temp copy exists only to measure duration and digest without
        # holding a second in-memory copy.
        suffix = Path(str(file.name or "")).suffix or ".audio"
        temp_file_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file_path = Path(temp_file.name)
                temp_file.write(file.blob)

            audio_seconds = await asyncio.to_thread(
                _measure_original_seconds, temp_file_path
            )
            audio_digest = await asyncio.to_thread(_digest_file, temp_file_path)

            job_id, call_id = await self._submit_job(
                file_path=temp_file_path,
                filename=str(file.name or temp_file_path.name),
                mimetype=mimetype,
                language=language,
                diarize=diarize,
                task=task,
                words=words,
                segments=segments,
                model=model,
                max_speakers=max_speakers,
                audio_seconds=audio_seconds,
                audio_digest=audio_digest,
                observer=observer,
            )
        finally:
            if temp_file_path is not None:
                with suppress(FileNotFoundError):
                    temp_file_path.unlink()

        try:
            result = await self.client.wait_for_result(
                job_id, run_cancelled=current_run_cancel_probe()
            )
        except asyncio.CancelledError:
            # The worker is going away; tell the service to stop the job so it
            # does not finish work nobody will collect. Shielded so the cancel
            # already delivered to this task cannot interrupt the request.
            await asyncio.shield(self.client.cancel(job_id))
            if observer is not None and call_id is not None:
                await observer.outcome_unknown(call_id, "request_cancelled")
            raise
        except (FlowStepCancelledError, RemoteTranscriptionCancelledException):
            # The job was stopped, by eneo or by the service; the audio was not
            # transcribed and nothing was billed.
            if observer is not None and call_id is not None:
                await observer.outcome_unknown(call_id, "request_cancelled")
            raise
        except ProviderRejectedRequestException:
            if observer is not None and call_id is not None:
                await observer.rejected(call_id, "provider_rejected")
            raise
        except Exception:
            if observer is not None and call_id is not None:
                await observer.outcome_unknown(call_id, "provider_error")
            raise

        if observer is not None and call_id is not None:
            await observer.completed(
                call_id,
                TranscriptionCallResultFacts(
                    response_model=result.model,
                    provider_response_id=job_id,
                ),
            )
        return result, audio_seconds

    @retry(
        wait=wait_random_exponential(min=1, max=20),
        stop=stop_after_attempt(3),
        retry=retry_if_not_exception_type(
            # A failure to record what a request did must never send that
            # request again: the provider already did the work and may already
            # have charged for it.
            litellm_transport.NON_RETRYABLE_PROVIDER_ERRORS
            + (ProviderCallObserverError,)
        ),
        reraise=True,
    )
    async def _submit_job(
        self,
        *,
        file_path: Path,
        filename: str,
        mimetype: str,
        language: str | None,
        diarize: bool,
        task: JobTask,
        words: "Sequence[TranscriptWord] | None",
        segments: "Sequence[TranscriptSegment] | None",
        model: str | None,
        max_speakers: int | None,
        audio_seconds: float,
        audio_digest: str,
        observer: "ProviderCallObserver | None",
    ) -> tuple[str, UUID | None]:
        """Submit one job; each network attempt is its own recorded request.

        Once a job id exists, nothing resubmits: later failures surface as
        the unknown outcomes they are rather than duplicating the job. The
        returned call id stays open for the poll phase to close.
        """
        call_id: UUID | None = None
        if observer is not None:
            # A diarize job is its own provider call on the same audio; the
            # suffix keeps it distinguishable from a full transcription of it.
            requested_model = (
                f"{self._requested_model}#diarize"
                if task == "diarize"
                else self._requested_model
            )
            call_id = await observer.started(
                build_transcription_call_request_facts(
                    requested_model=requested_model,
                    provider=REMOTE_TRANSCRIPTION_PROVIDER,
                    language=language,
                    audio_digest=audio_digest,
                    audio_seconds=audio_seconds,
                )
            )

        try:
            with open(file_path, "rb") as payload:
                job_id = await self.client.submit(
                    filename=filename,
                    mimetype=mimetype,
                    payload=payload,
                    language=language,
                    diarize=diarize,
                    task=task,
                    words=words,
                    segments=segments,
                    model=model,
                    max_speakers=max_speakers,
                )
                return job_id, call_id
        except asyncio.CancelledError:
            if observer is not None and call_id is not None:
                await observer.outcome_unknown(call_id, "request_cancelled")
            raise
        except ProviderRejectedRequestException:
            # The service answered and refused. That is a known outcome, so it
            # must not leave the run's audio total marked incomplete.
            if observer is not None and call_id is not None:
                await observer.rejected(call_id, "provider_rejected")
            raise
        except Exception:
            if observer is not None and call_id is not None:
                await observer.outcome_unknown(call_id, "provider_error")
            raise


def build_remote_flow_transcriber(settings: "Settings") -> RemoteFlowTranscriber:
    url = settings.flow_transcription_service_url
    api_key = settings.flow_transcription_service_api_key
    if not url or not api_key:
        raise APIKeyNotConfiguredException(
            "The external transcription service is not configured."
        )
    return RemoteFlowTranscriber(
        RemoteTranscriptionClient(
            base_url=url,
            api_key=api_key,
            submit_timeout_seconds=(
                settings.flow_transcription_service_submit_timeout_seconds
            ),
            poll_interval_seconds=(
                settings.flow_transcription_service_poll_interval_seconds
            ),
            poll_timeout_seconds=(
                settings.flow_transcription_service_poll_timeout_seconds
            ),
            result_timeout_seconds=(
                settings.flow_transcription_service_result_timeout_seconds
            ),
        )
    )


async def log_remote_transcription_readiness(settings: "Settings") -> None:
    """Startup diagnostic: can this deployment's token submit jobs right now?

    Logs only; a service that is down at worker start may be up by the time a
    flow runs, and each submit still handles refusal on its own.
    """
    if not settings.flow_transcription_service_configured:
        return
    transcriber = build_remote_flow_transcriber(settings)
    try:
        readiness = await transcriber.client.check_readiness()
    except APIKeyNotConfiguredException:
        logger.error(
            "remote_transcription.readiness url=%s credentials rejected",
            transcriber.client.base_url,
        )
        return
    log = (
        logger.info if readiness.ready and readiness.accepting_jobs else logger.warning
    )
    log(
        "remote_transcription.readiness url=%s ready=%s accepting_jobs=%s detail=%s",
        transcriber.client.base_url,
        readiness.ready,
        readiness.accepting_jobs,
        readiness.detail,
    )


async def _probe_quietly(probe: RunCancelProbe, *, job_id: str) -> bool:
    """A failed cancellation probe must not fail the job; keep waiting."""
    try:
        return await probe()
    except Exception:
        logger.warning(
            "remote_transcription.cancel_probe_failed job_id=%s",
            job_id,
            exc_info=True,
        )
        return False


def _parse_result_segments(raw: object) -> tuple[TranscriptSegment, ...] | None:
    """Segments from a result body; malformed entries are dropped, not fatal.

    The rendered text is the contract; segments are the structured view of the
    same lines that a reader UI uses to seek audio. A service that sends none
    (or garbage) still produced a usable transcript.
    """
    if not isinstance(raw, list):
        return None
    segments: list[TranscriptSegment] = []
    for entry in cast(list[object], raw):
        if not isinstance(entry, dict):
            continue
        item = cast(dict[str, object], entry)
        text = item.get("text")
        start = item.get("start")
        end = item.get("end")
        if (
            not isinstance(text, str)
            or isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
        ):
            continue
        speaker = item.get("speaker")
        segments.append(
            TranscriptSegment(
                text=text,
                start=float(start),
                end=float(end),
                speaker=speaker if isinstance(speaker, str) and speaker else None,
                words=_parse_result_words(item.get("words")),
            )
        )
    return tuple(segments)


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _parse_result_words(raw: object) -> tuple[TranscriptWord, ...] | None:
    """Word timings from a result segment; malformed words are dropped.

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


def _json_object(response: httpx.Response) -> dict[str, object]:
    try:
        body = response.json()
    except ValueError:
        return {}
    if isinstance(body, dict):
        return cast(dict[str, object], body)
    return {}


def _measure_original_seconds(file_path: Path) -> float:
    # audioread lacks type stubs; its file handles expose ``duration``.
    with audioread.audio_open(str(file_path)) as handle:  # pyright: ignore[reportUnknownMemberType]
        return float(handle.duration)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType, reportAttributeAccessIssue]


def _digest_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
