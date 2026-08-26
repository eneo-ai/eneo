# MIT License

import asyncio
import hashlib
from collections.abc import Mapping, Sequence
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
from eneo.main.exceptions import (
    ProviderCapabilityRejectedException,
    ProviderRejectedRequestException,
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
    """One recognized word with absolute timestamps (seconds from audio start)."""

    word: str
    start: float
    end: float


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """One provider segment with absolute timestamps (seconds from audio start)."""

    text: str
    start: float
    end: float


@dataclass(frozen=True, slots=True)
class ChunkTranscription:
    text: str
    # None when timestamps were not requested or the provider returned none.
    words: tuple[TranscriptWord, ...] | None
    segments: tuple[TranscriptSegment, ...] | None


@dataclass(frozen=True, slots=True)
class AdapterTranscription:
    """A whole file's transcript, with timestamps when every chunk had them.

    ``words`` carries word-level timestamps; ``segments`` the coarser
    segment-level ones, which many servers return even when they skip words.
    Both are None when timestamps were not requested, or when the provider
    could not deliver that granularity for at least one chunk
    (``timestamps_degraded`` is True when neither survived). A partial list
    would silently mislabel speakers, so each is all or nothing.
    """

    text: str
    words: tuple[TranscriptWord, ...] | None
    segments: tuple[TranscriptSegment, ...] | None
    timestamps_degraded: bool


def _extract_segments(response: object) -> tuple[TranscriptSegment, ...] | None:
    raw: object = getattr(response, "segments", None)
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return None
    segments: list[TranscriptSegment] = []
    for item in cast(Sequence[object], raw):
        text: object
        start: object
        end: object
        if isinstance(item, Mapping):
            mapping = cast(Mapping[str, object], item)
            text, start, end = (
                mapping.get("text"),
                mapping.get("start"),
                mapping.get("end"),
            )
        else:
            text = getattr(item, "text", None)
            start = getattr(item, "start", None)
            end = getattr(item, "end", None)
        if not isinstance(text, str):
            return None
        if isinstance(start, bool) or not isinstance(start, (int, float)):
            return None
        if isinstance(end, bool) or not isinstance(end, (int, float)):
            return None
        stripped = text.strip()
        if stripped:
            segments.append(
                TranscriptSegment(text=stripped, start=float(start), end=float(end))
            )
    return tuple(segments) if segments else None


def _extract_words(response: object) -> tuple[TranscriptWord, ...] | None:
    raw: object = getattr(response, "words", None)
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return None
    words: list[TranscriptWord] = []
    for item in cast(Sequence[object], raw):
        text: object
        start: object
        end: object
        if isinstance(item, Mapping):
            mapping = cast(Mapping[str, object], item)
            text, start, end = (
                mapping.get("word"),
                mapping.get("start"),
                mapping.get("end"),
            )
        else:
            text = getattr(item, "word", None)
            start = getattr(item, "start", None)
            end = getattr(item, "end", None)
        if not isinstance(text, str):
            return None
        if isinstance(start, bool) or not isinstance(start, (int, float)):
            return None
        if isinstance(end, bool) or not isinstance(end, (int, float)):
            return None
        words.append(
            TranscriptWord(word=text.strip(), start=float(start), end=float(end))
        )
    return tuple(words) if words else None


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
        want_words: bool = False,
    ) -> AdapterTranscription:
        """
        Transcribe an audio file, splitting into 5-minute chunks with timestamps.

        With ``want_words`` each chunk is asked for word-level timestamps, which
        are shifted by the measured length of the chunks before it so they are
        absolute for the whole file. A provider that refuses or omits them
        degrades the whole file to text only; the transcript itself is never
        affected.
        """
        text = ""
        five_minutes = 60 * 5
        chunk_index = 0
        total_duration_seconds = int(audio_file.duration)
        words: list[TranscriptWord] = []
        segments: list[TranscriptSegment] = []
        words_available = True
        segments_available = True
        degraded = False
        offset_seconds = 0.0

        async with audio_file.asplit_file(seconds=five_minutes) as files:
            total_chunks = len(files)

            for i, path in enumerate(files):
                start_time = chunk_index * five_minutes
                chunk_end = (
                    total_duration_seconds
                    if i == total_chunks - 1
                    else (chunk_index + 1) * five_minutes
                )
                # The timestamps below are nominal five-minute markers; the
                # splitter emits whole blocks, so what this request actually
                # sends has to be measured from the file itself.
                measured_seconds = await asyncio.to_thread(_measure_seconds, path)
                request_words = want_words and not degraded
                try:
                    chunk = await self._transcribe_chunk(
                        path,
                        language=language,
                        observer=observer,
                        audio_seconds=measured_seconds,
                        want_words=request_words,
                    )
                except ProviderCapabilityRejectedException:
                    if not request_words:
                        raise
                    logger.warning(
                        f"[LiteLLM] {self.litellm_model}: provider rejected word "
                        "timestamps; continuing without them"
                    )
                    degraded = True
                    chunk = await self._transcribe_chunk(
                        path,
                        language=language,
                        observer=observer,
                        audio_seconds=measured_seconds,
                        want_words=False,
                    )
                # Timestamp plausibility is judged by the external service, which
                # can force-align from the audio; forward what the provider gave.
                if request_words:
                    if chunk.words is None:
                        words_available = False
                    if chunk.segments is None:
                        segments_available = False
                    if chunk.words is None and chunk.segments is None:
                        logger.warning(
                            f"[LiteLLM] {self.litellm_model}: provider returned no "
                            "timestamps; continuing without them"
                        )
                        degraded = True
                if not degraded and chunk.words is not None:
                    words.extend(
                        TranscriptWord(
                            word=word.word,
                            start=word.start + offset_seconds,
                            end=word.end + offset_seconds,
                        )
                        for word in chunk.words
                    )
                if not degraded and chunk.segments is not None:
                    segments.extend(
                        TranscriptSegment(
                            text=segment.text,
                            start=segment.start + offset_seconds,
                            end=segment.end + offset_seconds,
                        )
                        for segment in chunk.segments
                    )
                offset_seconds += measured_seconds
                block_text = chunk.text

                end_time = chunk_end

                start_time_formatted = f"{start_time // 60}:{start_time % 60:02d}"
                end_time_formatted = f"{end_time // 60}:{end_time % 60:02d}"

                # Add markdown formatting with timestamp
                if chunk_index > 0:
                    text += "\n\n"
                text += (
                    f"### {start_time_formatted} - {end_time_formatted}\n\n{block_text}"
                )
                chunk_index += 1

        keep_words = want_words and not degraded and words_available and bool(words)
        keep_segments = (
            want_words and not degraded and segments_available and bool(segments)
        )
        return AdapterTranscription(
            text=text,
            words=tuple(words) if keep_words else None,
            segments=tuple(segments) if keep_segments else None,
            timestamps_degraded=want_words and not (keep_words or keep_segments),
        )

    @retry(
        wait=wait_random_exponential(min=1, max=20),
        stop=stop_after_attempt(3),
        retry=retry_if_not_exception_type(
            # A failure to record what a request did must never send that request
            # again: the provider already did the work and may already have
            # charged for it.
            litellm_transport.NON_RETRYABLE_PROVIDER_ERRORS
            + (ProviderCallObserverError,)
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
        want_words: bool = False,
    ) -> ChunkTranscription:
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

        if want_words:
            kwargs["response_format"] = "verbose_json"
            # Segments are the fallback when a server has no word alignment.
            kwargs["timestamp_granularities"] = ["word", "segment"]

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
        return ChunkTranscription(
            text=response.text,  # type: ignore[arg-type]
            words=_extract_words(response) if want_words else None,
            segments=_extract_segments(response) if want_words else None,
        )


def _measure_seconds(file_path: Path) -> float:
    return AudioFile(str(file_path)).duration


def _digest_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
