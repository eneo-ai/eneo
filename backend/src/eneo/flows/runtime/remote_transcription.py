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
a waiting job holds nothing but its job slot.
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, NoReturn, cast
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

if TYPE_CHECKING:
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


@dataclass(frozen=True, slots=True)
class RemoteTranscriptionResult:
    """The service's structured result for one completed job."""

    text: str
    duration_seconds: float | None
    model: str | None
    language: str | None


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
    ) -> str:
        """Submit one audio file as a transcription job and return its job id.

        The service admits or rejects before reading the body (queue-full is a
        pre-body 429), so a connection torn down mid-upload is treated as the
        rate limiting it usually is rather than as an unknown outcome.
        """
        try:
            async with self._http_client(timeout=self.submit_timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/v1/jobs",
                    headers=self._headers,
                    files={"file": (filename, payload, mimetype)},
                    data={"language": language or "auto", "diarize": "true"},
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

    async def wait_for_result(self, job_id: str) -> RemoteTranscriptionResult:
        """Poll the job until terminal, then fetch its structured result."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.poll_timeout_seconds
        consecutive_failures = 0

        async with self._http_client(timeout=self.result_timeout_seconds) as client:
            while True:
                if loop.time() >= deadline:
                    raise OpenAIException(
                        litellm_transport.PROVIDER_ERROR_MESSAGE,
                        code="provider_error",
                        details={"reason": "provider_error", "retryable": True},
                    )
                try:
                    status = await self._poll_once(client, job_id)
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
                if status == _TERMINAL_COMPLETED:
                    result = await self._fetch_result(client, job_id)
                    if result is not None:
                        return result
                    # A raced 409: the status flapped; keep polling.
                elif status == _TERMINAL_FAILED:
                    raise ProviderRejectedRequestException(
                        litellm_transport.INVALID_REQUEST_MESSAGE,
                        code="provider_rejected_request",
                        details={
                            "reason": "provider_rejected_request",
                            "retryable": False,
                        },
                    )
                await asyncio.sleep(self.poll_interval_seconds)

    async def _poll_once(self, client: httpx.AsyncClient, job_id: str) -> str:
        response = await client.get(
            f"{self.base_url}/v1/jobs/{job_id}", headers=self._headers
        )
        if response.status_code == 200:
            status = _json_object(response).get("status")
            if not isinstance(status, str):
                raise OpenAIException(
                    litellm_transport.PROVIDER_ERROR_MESSAGE,
                    code="provider_error",
                    details={"reason": "provider_error", "retryable": True},
                )
            return status
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
        return RemoteTranscriptionResult(
            text=text,
            duration_seconds=float(duration)
            if isinstance(duration, (int, float))
            else None,
            model=model if isinstance(model, str) else None,
            language=language if isinstance(language, str) else None,
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
        persist_cache_to_file: bool = True,
        observer: "ProviderCallObserver | None" = None,
    ) -> TranscribedAudio:
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
                audio_seconds=audio_seconds,
                audio_digest=audio_digest,
                observer=observer,
            )
        finally:
            if temp_file_path is not None:
                with suppress(FileNotFoundError):
                    temp_file_path.unlink()

        try:
            result = await self.client.wait_for_result(job_id)
        except asyncio.CancelledError:
            # No cancel endpoint exists: the service runs the job to
            # completion regardless, so the outcome is genuinely unknown.
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
        return TranscribedAudio(
            text=result.text,
            duration_seconds=result.duration_seconds or audio_seconds,
        )

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
            call_id = await observer.started(
                build_transcription_call_request_facts(
                    requested_model=self._requested_model,
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
