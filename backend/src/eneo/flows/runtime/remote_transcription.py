"""Speaker labels for flow transcripts from a native speaker service.

A flow's transcription model writes the text; the space's speaker service (an
organisation's connection) labels who says what, through an async job API
(``eneo.transcription_services.client``): submit the audio and the transcript
as a diarize job, poll it until it reaches a terminal state, then fetch the
labelled result.

This module owns what a flow attempt adds around those requests: provider-call
receipts, admission retries within the step budget, the poll schedule,
progress, cancellation and the typed provider errors flow steps report.
Polling is a plain idle await: flow execution runs on its own dedicated ARQ
worker, so a waiting job holds nothing but its job slot. A job eneo stops
waiting for (run cancelled, worker interrupted, poll deadline) is cancelled
service-side so it does not keep burning GPU time for a result nobody will
read.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NoReturn
from uuid import UUID, uuid4

from eneo.files.audio import AudioMimeTypes
from eneo.flows.domain.provider_call_evidence_gap import (
    ProviderCallEvidenceGap,
    ProviderCallPersistenceOutcome,
)
from eneo.flows.domain.speaker_labels import render_segments
from eneo.flows.enums import FlowStepPhase
from eneo.flows.flow_run_error import TranscriptionFailureKind
from eneo.flows.infrastructure.flow_provider_call_recorder import (
    ProviderCallEvidencePersistenceError,
)
from eneo.flows.runtime.audio_spool import SpooledAudio
from eneo.flows.runtime.run_cancellation import (
    FlowStepCancelledError,
    RunCancelProbe,
    current_run_cancel_probe,
)
from eneo.flows.runtime.step_deadline import (
    StepDeadline,
    budget_refusal,
    current_step_deadline_scope,
    mark_provider_request_in_flight,
    record_step_phase,
    record_step_progress,
    require_step_budget,
    settle_provider_request,
)
from eneo.flows.runtime.transcription import (
    TranscriptionProviderError,
    TranscriptionProviderRejectedError,
)
from eneo.main.exceptions import (
    APIKeyNotConfiguredException,
    ProviderRejectedRequestException,
    TypedIOValidationException,
)
from eneo.main.logging import get_logger
from eneo.model_providers.domain.provider_call_observer import (
    ProviderCallObserverError,
    TranscriptionCallResultFacts,
    build_transcription_call_request_facts,
)
from eneo.model_providers.infrastructure import litellm_transport
from eneo.settings.encryption_service import EncryptionService
from eneo.transcription_services.client import (
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_FAILED,
    CredentialsRejected,
    JobFailureKind,
    RequestFailed,
    SubmissionOutcomeUnknown,
    SubmissionRefused,
    SubmissionRejected,
    TranscriptionJobRequest,
    TranscriptionJobResult,
    TranscriptionServiceClient,
    TranscriptionServiceError,
    UnexpectedStatus,
)
from eneo.transcription_services.models import TranscriptionOperation
from eneo.transcription_services.repository import (
    TranscriptionServiceConnectionRepository,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from eneo.files.transcript import (
        TranscriptSegment,
        TranscriptWord,
    )
    from eneo.model_providers.domain.provider_call_observer import (
        ProviderCallObserver,
    )

logger = get_logger(__name__)

# Observer identity for calls delegated to the external service. The result
# facts record the model the service actually ran.
REMOTE_TRANSCRIPTION_PROVIDER = "external"

# Consecutive poll failures tolerated before the job's outcome is declared
# unknown. A single dropped poll must not fail a job the service may still
# complete.
_MAX_CONSECUTIVE_POLL_FAILURES = 5

# Cancelling a job is best effort and must not hold up the caller's own
# cancellation for long.
_CANCEL_TIMEOUT_SECONDS = 10.0


class RemoteTranscriptionCancelledException(TranscriptionProviderError):
    """The service reported the job cancelled before it produced a result."""


class RemoteFlowTranscriber:
    """A native service that labels the speakers of a transcript a flow's
    transcription model produced."""

    def __init__(
        self, client: TranscriptionServiceClient, *, poll_interval_seconds: float
    ) -> None:
        self.client = client
        self.poll_interval_seconds = poll_interval_seconds

    async def label_speakers(
        self,
        file: SpooledAudio,
        *,
        file_id: UUID,
        words: Sequence[TranscriptWord] | None,
        model_name: str,
        segments: Sequence[TranscriptSegment] | None = None,
        language: str | None = None,
        observer: ProviderCallObserver | None = None,
        max_speakers: int | None = None,
    ) -> TranscriptionJobResult:
        """Have the service add speaker labels to a transcript produced elsewhere.

        The audio is uploaded again for diarization; the transcript comes back
        rendered with the same speaker-labelled lines a full job produces.
        """
        result, _ = await self._run_job(
            file,
            file_id=file_id,
            request=TranscriptionJobRequest(
                operation=TranscriptionOperation.DIARIZE,
                language=language,
                diarize=True,
                words=words,
                segments=segments,
                model=model_name,
                max_speakers=max_speakers,
            ),
            observer=observer,
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
            raise TranscriptionProviderError(
                litellm_transport.PROVIDER_ERROR_MESSAGE,
                code="provider_error",
                details={"reason": "diarize_task_unsupported", "retryable": False},
            )
        return result

    async def wait_for_result(
        self,
        job_id: str,
        *,
        run_cancelled: RunCancelProbe | None = None,
    ) -> TranscriptionJobResult:
        """Poll the job until terminal, then fetch its structured result.

        ``run_cancelled`` is asked once per poll tick; when it answers true the
        job is cancelled service-side and ``FlowStepCancelledError`` is raised
        so the executor records the step as cancelled rather than failed.
        """
        record_step_phase(FlowStepPhase.TRANSCRIPTION)
        scope = current_step_deadline_scope()
        remaining = scope.deadline.remaining() if scope is not None else None
        timeout = asyncio.timeout(remaining)
        try:
            async with timeout:
                return await self._poll_until_result(
                    job_id, run_cancelled=run_cancelled
                )
        except TypedIOValidationException:
            await self._stop_job(job_id)
            raise
        except TimeoutError:
            if not timeout.expired() or scope is None:
                raise
            await self._stop_job(job_id)
            raise scope.deadline.timeout_error(
                step_order=scope.step_order,
                phase="transcription",
                provider_request_in_flight=True,
            ) from None

    async def _poll_until_result(
        self, job_id: str, *, run_cancelled: RunCancelProbe | None
    ) -> TranscriptionJobResult:
        scope = current_step_deadline_scope()
        consecutive_failures = 0
        last_seen = None
        poll_failure: TranscriptionProviderError | None = None

        while True:
            if scope is not None and scope.deadline.expired():
                raise scope.deadline.timeout_error(
                    step_order=scope.step_order,
                    phase="transcription",
                    provider_request_in_flight=True,
                )
            if run_cancelled is not None and await _probe_quietly(
                run_cancelled, job_id=job_id
            ):
                await self._stop_job(job_id)
                raise FlowStepCancelledError(
                    "Run was cancelled while waiting for transcription."
                )
            try:
                seen = await self.client.get_job_status(job_id)
            except (RequestFailed, UnexpectedStatus) as error:
                consecutive_failures += 1
                logger.warning(
                    "remote_transcription.poll_failed consecutive_failures=%s failure=%s",
                    consecutive_failures,
                    error,
                )
                # The client's message is safe; the transport error behind it
                # can quote credentials, so it is not chained.
                poll_failure = TranscriptionProviderError(
                    f"External transcription poll failed: {error}.",
                    code="provider_error",
                ).with_traceback(error.__traceback__)
            except TranscriptionServiceError as error:
                _raise_provider_error(error)
            else:
                consecutive_failures = 0
                record_step_progress(
                    seen.describe(),
                    transcription_stage=seen.stage,
                    transcription_queue_position=seen.queue_position,
                )
                if seen != last_seen:
                    logger.info(
                        "remote_transcription.progress job_id=%s state=%s",
                        job_id,
                        seen.describe(),
                    )
                    last_seen = seen
                if seen.status == JOB_COMPLETED:
                    try:
                        result = await self.client.get_job_result(job_id)
                    except TranscriptionServiceError as error:
                        _raise_provider_error(error)
                    if result is not None:
                        result = _with_canonical_segments(result)
                        require_step_budget(phase="transcription result")
                        return result
                    # A raced 409: the status flapped; keep polling.
                elif seen.status == JOB_FAILED:
                    raise TranscriptionProviderRejectedError(
                        litellm_transport.INVALID_REQUEST_MESSAGE,
                        failure_kind=_flow_failure_kind(
                            seen.failure_kind,
                            default=TranscriptionFailureKind.PROVIDER,
                        ),
                        service_reason=seen.service_reason,
                        code="provider_rejected_request",
                        details={
                            "reason": "provider_rejected_request",
                            "retryable": False,
                        },
                    )
                elif seen.status == JOB_CANCELLED:
                    # Cancelled service-side (operator, retention, or a cancel
                    # eneo sent that raced this poll). No result will come; the
                    # audio was not transcribed, so a re-run is reasonable.
                    raise RemoteTranscriptionCancelledException(
                        litellm_transport.PROVIDER_ERROR_MESSAGE,
                        failure_kind=_flow_failure_kind(
                            seen.failure_kind,
                            default=TranscriptionFailureKind.CANCELLED,
                        ),
                        service_reason=seen.service_reason,
                        code="provider_error",
                        details={"reason": "provider_cancelled", "retryable": True},
                    )
                await asyncio.sleep(self.poll_interval_seconds)
                continue

            if consecutive_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise TranscriptionProviderError(
                    litellm_transport.PROVIDER_ERROR_MESSAGE,
                    code="provider_error",
                    details={"reason": "provider_error", "retryable": True},
                ) from poll_failure
            await asyncio.sleep(self.poll_interval_seconds)

    async def _stop_job(self, job_id: str) -> None:
        """Ask the service to stop a job eneo will not wait for.

        Nothing here raises: the caller is already on its way out and the
        worst case is the job running to completion unread, which is what
        happened before cancellation existed.
        """
        try:
            async with asyncio.timeout(_CANCEL_TIMEOUT_SECONDS):
                await self.client.cancel_job(
                    job_id, timeout_seconds=_CANCEL_TIMEOUT_SECONDS
                )
        except asyncio.CancelledError:
            raise
        except (TranscriptionServiceError, TimeoutError) as error:
            # The chained transport error can quote credentials; log the
            # client's safe text only.
            logger.warning(
                "remote_transcription.cancel_failed job_id=%s failure=%s",
                job_id,
                str(error) or type(error).__name__,
            )
        except Exception:
            logger.warning(
                "remote_transcription.cancel_failed job_id=%s", job_id, exc_info=True
            )

    async def _run_job(
        self,
        file: SpooledAudio,
        *,
        file_id: UUID,
        request: TranscriptionJobRequest,
        observer: ProviderCallObserver | None,
    ) -> tuple[TranscriptionJobResult, float]:
        record_step_phase(FlowStepPhase.TRANSCRIPTION)
        if not AudioMimeTypes.has_value(file.mimetype):
            raise ValueError("File needs to be an audio file")
        audio_seconds = await file.measure_duration()
        job_id, call_id = await self._submit_job(
            file_id=file_id,
            file_path=file.path,
            filename=file.filename,
            mimetype=file.mimetype,
            request=request,
            audio_seconds=audio_seconds,
            audio_digest=file.digest,
            observer=observer,
        )

        # The job is provider work in flight until the service answers.
        mark_provider_request_in_flight(True)
        acceptance: asyncio.Task[None] | None = None
        waiting_for_result = False
        try:
            if observer is not None and call_id is not None:
                acceptance = asyncio.create_task(observer.accepted(call_id, job_id))
                await self._await_job_receipt(
                    acceptance,
                    call_id=call_id,
                    job_id=job_id,
                    outcome="started",
                    deadline=asyncio.get_running_loop().time()
                    + self.client.result_timeout_seconds,
                )
            await file.aclose()
            waiting_for_result = True
            result = await self.wait_for_result(
                job_id, run_cancelled=current_run_cancel_probe()
            )
        except asyncio.CancelledError:
            # The worker is going away; tell the service to stop the job so it
            # does not finish work nobody will collect. Shielded so the cancel
            # already delivered to this task cannot interrupt the request. The
            # stop is best effort, so the provider outcome remains unresolved.
            settle_provider_request(known=False)
            await asyncio.shield(self._stop_job(job_id))
            if observer is not None and call_id is not None:
                cleanup_deadline = (
                    asyncio.get_running_loop().time()
                    + self.client.result_timeout_seconds
                )
                if acceptance is not None:
                    await self._await_job_receipt(
                        acceptance,
                        call_id=call_id,
                        job_id=job_id,
                        outcome="started",
                        deadline=cleanup_deadline,
                    )
                await self._await_job_receipt(
                    asyncio.create_task(
                        observer.outcome_unknown(call_id, "request_cancelled")
                    ),
                    call_id=call_id,
                    job_id=job_id,
                    outcome="request_cancelled",
                    deadline=cleanup_deadline,
                )
            raise
        except ProviderCallObserverError as persistence_error:
            settle_provider_request(known=False)
            try:
                await self._stop_job(job_id)
            except (asyncio.CancelledError, TimeoutError) as interruption:
                # The best-effort cancel was interrupted (task cancellation or
                # the outer deadline); the persistence-gap facts carry the known
                # job id and must reach terminal error handling, not be replaced.
                raise persistence_error from interruption
            raise
        except (FlowStepCancelledError, RemoteTranscriptionCancelledException):
            settle_provider_request(known=False)
            if observer is not None and call_id is not None:
                await observer.outcome_unknown(call_id, "request_cancelled")
            raise
        except ProviderRejectedRequestException:
            settle_provider_request(known=True)
            if observer is not None and call_id is not None:
                await observer.rejected(call_id, "provider_rejected")
            raise
        except Exception:
            settle_provider_request(known=False)
            if not waiting_for_result:
                await self._stop_job(job_id)
            if observer is not None and call_id is not None:
                await observer.outcome_unknown(call_id, "provider_error")
            raise

        settle_provider_request(known=True)
        if observer is not None and call_id is not None:
            await observer.completed(
                call_id,
                TranscriptionCallResultFacts(
                    response_model=result.model,
                    provider_response_id=job_id,
                ),
            )
        return result, audio_seconds

    @staticmethod
    async def _await_job_receipt(
        receipt: asyncio.Task[None],
        *,
        call_id: UUID,
        job_id: str,
        outcome: ProviderCallPersistenceOutcome,
        deadline: float,
    ) -> None:
        # Cancellation of the caller leaves the transaction alive for bounded
        # cleanup; cancellation of a stalled transaction must not extend the wait.
        done, _ = await asyncio.wait(
            {receipt}, timeout=max(0, deadline - asyncio.get_running_loop().time())
        )
        if not done:
            receipt.cancel()
            receipt.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
            raise ProviderCallEvidencePersistenceError(
                facts=ProviderCallEvidenceGap(
                    call_id=call_id,
                    provider_response_id=job_id,
                    outcome=outcome,
                )
            )
        try:
            receipt.result()
        except ProviderCallEvidencePersistenceError as exc:
            exc.facts = exc.facts.model_copy(update={"provider_response_id": job_id})
            raise

    async def _submit_job(
        self,
        *,
        file_id: UUID,
        file_path: Path,
        filename: str,
        mimetype: str,
        request: TranscriptionJobRequest,
        audio_seconds: float,
        audio_digest: str,
        observer: ProviderCallObserver | None,
    ) -> tuple[str, UUID | None]:
        """Own admission retries for one logical job and one provider receipt."""
        record_step_phase(FlowStepPhase.TRANSCRIPTION)
        require_step_budget(phase="transcription job submission")
        probe = current_run_cancel_probe()
        if probe is not None and await probe():
            raise FlowStepCancelledError(
                "Run was cancelled during transcription admission."
            )
        call_id: UUID | None = None
        if observer is not None:
            provider_model = (
                f"{REMOTE_TRANSCRIPTION_PROVIDER}/"
                f"{self.client.destination_host or 'transcription-service'}"
            )
            # A diarize job is its own provider call on the same audio; the
            # suffix keeps it apart from the model call that transcribed it.
            requested_model = f"{provider_model}#diarize"
            call_id = await observer.started(
                build_transcription_call_request_facts(
                    requested_model=requested_model,
                    provider=REMOTE_TRANSCRIPTION_PROVIDER,
                    language=request.language,
                    audio_digest=audio_digest,
                    audio_seconds=audio_seconds,
                )
            )

        # Writing the receipt may itself have consumed the budget; the job is
        # admitted only against the clock as it is now, and a receipt that then
        # cannot be honoured is settled as the refusal it is.
        refusal = budget_refusal(phase="transcription job submission (not sent)")
        if refusal is not None:
            if observer is not None and call_id is not None:
                await observer.rejected(call_id, "budget_exhausted")
            raise refusal
        scope = current_step_deadline_scope()
        deadline = (
            scope.deadline
            if scope is not None
            else StepDeadline.start(self.client.submit_timeout_seconds)
        )
        operation_scope = (
            observer.operation_scope if observer is not None else str(uuid4())
        )
        idempotency_key = hashlib.sha256(
            json.dumps(
                [operation_scope, str(file_id), audio_digest, request.operation],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        uncertain = False
        submission_outcome: Literal["unsent", "refused", "uncertain"] = "unsent"
        last_refusal: SubmissionRefused | None = None
        try:
            while True:
                if deadline.expired():
                    error = deadline.timeout_error(
                        step_order=scope.step_order if scope is not None else 0,
                        phase="transcription job admission",
                        provider_request_in_flight=uncertain,
                    )
                    if last_refusal is not None:
                        error.context = {
                            **(error.context or {}),
                            "transcription_failure_kind": TranscriptionFailureKind.CAPACITY,
                            "transcription_service_reason": last_refusal.service_reason,
                        }
                    raise error
                if (
                    submission_outcome != "unsent"
                    and probe is not None
                    and await probe()
                ):
                    raise FlowStepCancelledError(
                        "Run was cancelled during transcription admission."
                    )
                timeout = asyncio.timeout(deadline.remaining())
                submission_outcome = "uncertain"
                try:
                    async with timeout:
                        with open(file_path, "rb") as payload:
                            mark_provider_request_in_flight(True)
                            job_id = await self.client.submit_job(
                                request,
                                filename=filename,
                                mimetype=mimetype,
                                payload=payload,
                                idempotency_key=idempotency_key,
                            )
                    return job_id, call_id
                except SubmissionRefused as exc:
                    last_refusal = exc
                    submission_outcome = "uncertain" if uncertain else "refused"
                    if submission_outcome == "refused":
                        settle_provider_request(known=True)
                    delay = exc.retry_after
                    if delay is None or delay < self.poll_interval_seconds:
                        delay = max(
                            delay or 0,
                            self.poll_interval_seconds * random.uniform(0.8, 1.2),
                        )
                    while delay > 0 and not deadline.expired():
                        if probe is not None and await probe():
                            raise FlowStepCancelledError(
                                "Run was cancelled during transcription admission."
                            )
                        interval = min(
                            delay, self.poll_interval_seconds, deadline.remaining()
                        )
                        await asyncio.sleep(interval)
                        delay -= interval
                except SubmissionOutcomeUnknown as exc:
                    if uncertain:
                        _raise_provider_error(exc)
                    uncertain = True
                except SubmissionRejected as exc:
                    submission_outcome = "uncertain" if uncertain else "refused"
                    _raise_provider_error(exc)
                except TranscriptionServiceError as exc:
                    _raise_provider_error(exc)
                except TimeoutError:
                    if not timeout.expired():
                        raise
                    raise deadline.timeout_error(
                        step_order=scope.step_order if scope is not None else 0,
                        phase="transcription job submission",
                        provider_request_in_flight=True,
                    ) from None
        except (asyncio.CancelledError, FlowStepCancelledError):
            settle_provider_request(known=submission_outcome != "uncertain")
            if observer is not None and call_id is not None:
                if submission_outcome == "refused":
                    await observer.rejected(call_id, "provider_rejected")
                else:
                    await observer.outcome_unknown(call_id, "request_cancelled")
            raise
        except Exception:
            settle_provider_request(known=submission_outcome != "uncertain")
            if observer is not None and call_id is not None:
                if submission_outcome == "unsent":
                    await observer.rejected(call_id, "budget_exhausted")
                elif submission_outcome == "refused":
                    await observer.rejected(call_id, "provider_rejected")
                else:
                    await observer.outcome_unknown(call_id, "provider_error")
            raise


def _raise_provider_error(error: TranscriptionServiceError) -> NoReturn:
    """Report a failed service request as the flow's typed provider error."""
    if isinstance(error, CredentialsRejected):
        raise APIKeyNotConfiguredException(
            "The speaker identification service rejected its API key. An "
            "administrator can enter a new key for the connection."
        ) from error
    if isinstance(error, SubmissionRejected):
        raise TranscriptionProviderRejectedError(
            litellm_transport.INVALID_REQUEST_MESSAGE,
            failure_kind=TranscriptionFailureKind.INPUT,
            service_reason=error.service_reason,
            code="provider_rejected_request",
            details={"reason": "provider_rejected_request", "retryable": False},
        ) from error
    # A lost answer after the upload began is an unknown outcome, never an
    # unavailable service, even when a timeout lost it.
    if not isinstance(
        error, SubmissionOutcomeUnknown
    ) and litellm_transport.is_provider_unavailable_error(error):
        litellm_transport.raise_provider_unavailable(error)
    raise TranscriptionProviderError(
        litellm_transport.PROVIDER_ERROR_MESSAGE,
        code="provider_error",
        details={"reason": "provider_error", "retryable": True},
    ) from error


def _flow_failure_kind(
    kind: JobFailureKind | None, *, default: TranscriptionFailureKind
) -> TranscriptionFailureKind:
    return TranscriptionFailureKind(kind.value) if kind is not None else default


def _with_canonical_segments(
    result: TranscriptionJobResult,
) -> TranscriptionJobResult:
    """Keep the segment sidecar only when it renders to the canonical text.

    The rendered text is the contract; segments are the structured view of the
    same lines that a reader UI uses to seek audio.
    """
    if result.segments is None or render_segments(result.segments) == result.text:
        return result
    return replace(result, segments=None)


# Fixed bounds for one speaker-labelling job, chosen for hour-long meetings on
# a queue that may be busy; an organisation's connection sets no timeouts.
SPEAKER_JOB_SUBMIT_TIMEOUT_SECONDS = 600
SPEAKER_JOB_RESULT_TIMEOUT_SECONDS = 120
SPEAKER_JOB_POLL_INTERVAL_SECONDS = 5.0


async def connect_speaker_service(
    connection_id: UUID,
    *,
    repository: TranscriptionServiceConnectionRepository,
    encryption: EncryptionService,
    include_speaker_review: bool,
) -> RemoteFlowTranscriber:
    """The speaker service of ``connection_id`` as it is stored now: the
    address and key are read together, so an edit made meanwhile never pairs
    one with the other."""
    connection, ciphertext = await repository.get_with_key(connection_id)
    return RemoteFlowTranscriber(
        TranscriptionServiceClient(
            base_url=connection.endpoint_url,
            api_key=encryption.decrypt(ciphertext),
            include_speaker_review=include_speaker_review,
            submit_timeout_seconds=SPEAKER_JOB_SUBMIT_TIMEOUT_SECONDS,
            result_timeout_seconds=SPEAKER_JOB_RESULT_TIMEOUT_SECONDS,
        ),
        poll_interval_seconds=SPEAKER_JOB_POLL_INTERVAL_SECONDS,
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
