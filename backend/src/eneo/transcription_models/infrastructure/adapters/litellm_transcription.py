# MIT License

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import UUID

from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from eneo.files.audio import AudioFile

# The flow attempt's budget, when a flow step is what runs this adapter; the
# scope is ambient (like the run-cancel probe) so no caller threads it.
from eneo.flows.runtime.step_deadline import require_step_budget
from eneo.main.exceptions import (
    ProviderRejectedRequestException,
    TypedIOValidationException,
)
from eneo.main.logging import get_logger
from eneo.model_providers.domain.model_route import resolve_model_route
from eneo.model_providers.domain.provider_call_observer import (
    ProviderCallObserver,
    ProviderCallObserverError,
    TranscriptionCallResultFacts,
    build_transcription_call_request_facts,
)
from eneo.model_providers.infrastructure import litellm_transport
from eneo.model_providers.infrastructure.litellm_provider import (
    build_litellm_provider_kwargs,
)

if TYPE_CHECKING:
    from eneo.model_providers.infrastructure.tenant_model_credential_resolver import (
        TenantModelCredentialResolver,
    )
    from eneo.transcription_models.domain import TranscriptionModel

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TranscriptWord:
    """One recognized word with absolute timestamps (seconds from audio start).

    ``probability`` is the service's confidence in the word's placement when
    it reports one. Its meaning follows the result's ``alignment``: a decoder
    posterior for ``provider_words``, the forced-alignment score for
    ``forced``, where exactly ``0.0`` marks a word the aligner could not fit
    to the audio and spread evenly over its window instead.
    """

    word: str
    start: float
    end: float
    probability: float | None = None


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """A stretch of transcript with absolute timestamps (seconds from audio start).

    ``speaker`` is the diarization label (``SPEAKER_NN``) when a service
    assigned one; providers that only transcribe leave it ``None``.
    """

    text: str
    start: float
    end: float
    speaker: str | None = None
    # Word timings inside the segment, when the service produced them.
    words: tuple[TranscriptWord, ...] | None = None
    speaker_attribution: str | None = None
    overlap_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AdapterTranscription:
    """A whole file's transcript and the chunk windows it was decoded in.

    ``segments`` holds one entry per non-empty chunk, spanning the chunk's
    measured duration. Those boundaries come from the audio Eneo itself split
    and measured, so they are the only timestamps in the transcript that can be
    trusted; the provider's own word and segment timings are never surfaced.
    """

    text: str
    segments: tuple[TranscriptSegment, ...]


class LiteLLMTranscriptionAdapter:
    """
    LiteLLM-based transcription adapter.

    Routes through LiteLLM for consistent provider handling.
    Constructs model name as {provider_type}/{model.model_name}.
    """

    def __init__(
        self,
        model: "TranscriptionModel",
        credential_resolver: "TenantModelCredentialResolver",
        provider_type: str,
    ) -> None:
        super().__init__()
        self.model = model
        self.credential_resolver = credential_resolver
        self.provider_type = provider_type

        # Construct LiteLLM model name with provider prefix
        # LiteLLM requires the provider prefix to know which client to use
        # Users should set provider_type to a LiteLLM-compatible value
        # (e.g., "openai", "hosted_vllm" for OpenAI-compatible APIs)
        self.litellm_model = resolve_model_route(
            provider_type=provider_type,
            model_name=model.model_name,
        )

        logger.debug(
            f"[LiteLLM] Initializing transcription adapter for model: {model.name} -> {self.litellm_model}"
        )

    def _mask_api_key(self, api_key: str) -> str:
        """Mask API key for safe logging."""
        return f"...{api_key[-4:]}" if len(api_key) > 4 else "***"

    def _prepare_kwargs(self) -> dict[str, object]:
        """
        Prepare kwargs for LiteLLM transcription call with credentials.
        """
        kwargs = build_litellm_provider_kwargs(self.credential_resolver)

        api_key = kwargs.get("api_key")
        if isinstance(api_key, str):
            logger.debug(
                f"[LiteLLM] {self.litellm_model}: Prepared kwargs "
                f"with api_key={self._mask_api_key(api_key)}"
            )

        return kwargs

    async def get_text_from_file(
        self,
        audio_file: AudioFile,
        *,
        language: str | None = None,
        observer: "ProviderCallObserver | None" = None,
    ) -> AdapterTranscription:
        """
        Transcribe an audio file, splitting into 5-minute chunks with timestamps.

        Each chunk's measured length is accumulated so the returned segments
        and the transcript's chunk headings place every chunk's text in its
        absolute window of the whole file: the splitter emits whole blocks, so
        a chunk can be longer than its nominal five minutes.
        """
        text = ""
        five_minutes = 60 * 5
        segments: list[TranscriptSegment] = []
        offset_seconds = 0.0

        async with audio_file.asplit_file(seconds=five_minutes) as files:
            for chunk_index, path in enumerate(files):
                require_step_budget(phase=f"transcription chunk {chunk_index + 1}")
                measured_seconds = await asyncio.to_thread(_measure_seconds, path)
                block_text = await self._transcribe_chunk(
                    path,
                    language=language,
                    observer=observer,
                    audio_seconds=measured_seconds,
                )
                chunk_start = offset_seconds
                offset_seconds += measured_seconds
                chunk_text = block_text.strip()
                if chunk_text:
                    segments.append(
                        TranscriptSegment(
                            text=chunk_text,
                            start=chunk_start,
                            end=offset_seconds,
                        )
                    )

                if chunk_index > 0:
                    text += "\n\n"
                text += (
                    f"### {_clock(chunk_start)} - {_clock(offset_seconds)}\n\n"
                    f"{block_text}"
                )

        return AdapterTranscription(text=text, segments=tuple(segments))

    @retry(
        wait=wait_random_exponential(min=1, max=20),
        stop=stop_after_attempt(3),
        retry=retry_if_not_exception_type(
            # A failure to record what a request did must never send that request
            # again: the provider already did the work and may already have
            # charged for it. Neither may a cancelled attempt (the step's budget
            # ran out) or a typed refusal: retrying would send a request the
            # runtime has already decided not to send.
            litellm_transport.NON_RETRYABLE_PROVIDER_ERRORS
            + (
                ProviderCallObserverError,
                asyncio.CancelledError,
                TypedIOValidationException,
            )
        ),
        reraise=True,
    )
    async def _transcribe_chunk(
        self,
        file_path: Path,
        *,
        language: str | None = None,
        observer: "ProviderCallObserver | None" = None,
        audio_seconds: float,
    ) -> str:
        """
        Transcribe a single audio chunk using LiteLLM.

        Each network attempt is its own recorded request, so a retry after an
        unknown outcome is visible rather than folded into the attempt it
        replaced.
        """
        kwargs = self._prepare_kwargs()

        if language is not None:
            kwargs["language"] = language
            logger.debug(
                f"[LiteLLM] {self.litellm_model}: Setting language=%s from flow/app input",
                language,
            )
        # Keep legacy default for KB-Whisper when no explicit language hint is provided.
        elif "kb-whisper" in self.model.model_name.lower():
            kwargs["language"] = "sv"
            logger.debug(
                f"[LiteLLM] {self.litellm_model}: Setting language=sv fallback for KB-Whisper"
            )

        logger.info(
            f"[LiteLLM] {self.litellm_model}: Making transcription request for chunk"
        )

        call_id: UUID | None = None
        if observer is not None:
            effective_language = kwargs.get("language")
            call_id = await observer.started(
                build_transcription_call_request_facts(
                    requested_model=self.litellm_model,
                    provider=self.provider_type,
                    language=(
                        effective_language
                        if isinstance(effective_language, str)
                        else None
                    ),
                    audio_digest=await asyncio.to_thread(_digest_file, file_path),
                    audio_seconds=audio_seconds,
                )
            )

        # Also guards every retry: a request is never started after the
        # step's budget ran out.
        require_step_budget(phase="transcription request")
        try:
            with open(file_path, "rb") as audio_file:
                response = await litellm_transport.atranscription(
                    model=self.litellm_model,
                    file=audio_file,
                    **kwargs,
                )
        except asyncio.CancelledError:
            if observer is not None and call_id is not None:
                await observer.outcome_unknown(call_id, "request_cancelled")
            raise
        except Exception as e:
            logger.exception(f"[LiteLLM] {self.litellm_model}: Unknown exception:")
            try:
                litellm_transport.raise_public_litellm_error(
                    e,
                    provider_type=self.provider_type,
                    is_unavailable=litellm_transport.is_provider_unavailable_error,
                    raise_unavailable=litellm_transport.raise_provider_unavailable,
                )
            except ProviderRejectedRequestException:
                # The provider answered and refused. That is a known outcome, so
                # it must not leave the run's audio total marked incomplete.
                if observer is not None and call_id is not None:
                    await observer.rejected(call_id, "provider_rejected")
                raise
            except Exception:
                if observer is not None and call_id is not None:
                    await observer.outcome_unknown(call_id, "provider_error")
                raise
            raise AssertionError("Provider error mapping unexpectedly returned.")

        logger.debug(f"[LiteLLM] {self.litellm_model}: Transcription successful")
        if observer is not None and call_id is not None:
            await observer.completed(
                call_id,
                TranscriptionCallResultFacts(
                    response_model=getattr(response, "model", None),
                    provider_response_id=getattr(response, "id", None),
                ),
            )
        return cast(str, response.text)  # type: ignore[reportUnknownMemberType]


def _clock(seconds: float) -> str:
    """M:SS from a measured offset, floored like the segment windows."""
    whole = int(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def _measure_seconds(file_path: Path) -> float:
    return AudioFile(str(file_path)).duration


def _digest_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
