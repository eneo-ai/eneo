# MIT License

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from eneo.files.audio import AudioFile
from eneo.files.transcript import TranscriptSegment
from eneo.main.logging import get_logger
from eneo.model_providers.domain.model_route import resolve_model_route
from eneo.model_providers.infrastructure import litellm_transport
from eneo.model_providers.infrastructure.litellm_provider import (
    build_litellm_provider_kwargs,
)

if TYPE_CHECKING:
    from eneo.model_providers.infrastructure.outbound_headers_runtime import (
        ProviderOutboundHeaders,
    )
    from eneo.model_providers.infrastructure.tenant_model_credential_resolver import (
        TenantModelCredentialResolver,
    )
    from eneo.transcription_models.domain import TranscriptionModel

logger = get_logger(__name__)


@dataclass(frozen=True)
class AdapterTranscription:
    """What one transcription produced: the Markdown text and timed segments."""

    text: str
    segments: tuple[TranscriptSegment, ...]


def _clock(seconds: float) -> str:
    whole = max(0, int(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


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
        outbound_headers: "ProviderOutboundHeaders | None" = None,
    ) -> None:
        super().__init__()
        self.model = model
        self.credential_resolver = credential_resolver
        self.provider_type = provider_type
        # Decrypted when the adapter is built (inside the job's session
        # scope); resolved per chunk request, which needs no database.
        self.outbound_headers = outbound_headers

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
        if self.outbound_headers is not None and self.outbound_headers.headers:
            # LiteLLM 1.101's OpenAI-compatible transcription route drops
            # extra_headers (transport-capture tests pin this). Sending the
            # request without the configured headers would be a silently
            # weaker request, so it is refused before anything is sent.
            # Apply them here (apply_outbound_headers) once LiteLLM forwards
            # extra_headers on this route.
            self.outbound_headers.reject(None, "transcription_unsupported")

        api_key = kwargs.get("api_key")
        if isinstance(api_key, str):
            logger.debug(
                f"[LiteLLM] {self.litellm_model}: Prepared kwargs "
                f"with api_key={self._mask_api_key(api_key)}"
            )

        return kwargs

    async def get_text_from_file(self, audio_file: AudioFile) -> str:
        """The transcript as Markdown: one block per 5-minute chunk with its window."""
        return (await self.transcribe_file(audio_file)).text

    async def transcribe_file(
        self, audio_file: AudioFile, *, language: str | None = None
    ) -> AdapterTranscription:
        """Transcribe an audio file in 5-minute chunks.

        Returns the Markdown text and one timed segment per non-empty chunk
        (the provider's own timestamps are not requested; the chunk windows
        are the only timing trusted). ``language`` is the ISO code to pin the
        provider to; None lets it detect, except for KB-Whisper (Swedish).
        """
        five_minutes = 60 * 5
        total_duration_seconds = float(audio_file.duration)
        blocks: list[str] = []
        segments: list[TranscriptSegment] = []

        async with audio_file.asplit_file(seconds=five_minutes) as files:
            total_chunks = len(files)
            for index, path in enumerate(files):
                block_text = await self._transcribe_chunk(path, language=language)
                start = float(index * five_minutes)
                end = (
                    total_duration_seconds
                    if index == total_chunks - 1
                    else float((index + 1) * five_minutes)
                )
                chunk_text = block_text.strip()
                if not chunk_text:
                    continue
                segments.append(
                    TranscriptSegment(text=chunk_text, start=start, end=end)
                )
                blocks.append(f"### {_clock(start)} - {_clock(end)}\n\n{block_text}")

        return AdapterTranscription(text="\n\n".join(blocks), segments=tuple(segments))

    @retry(
        wait=wait_random_exponential(min=1, max=20),
        stop=stop_after_attempt(3),
        retry=retry_if_not_exception_type(
            litellm_transport.NON_RETRYABLE_PROVIDER_ERRORS
        ),
        reraise=True,
    )
    async def _transcribe_chunk(
        self, file_path: Path, *, language: str | None = None
    ) -> str:
        """
        Transcribe a single audio chunk using LiteLLM.
        """
        kwargs = self._prepare_kwargs()

        if language is not None:
            kwargs["language"] = language
        # Set language for Swedish models (KB-Whisper)
        elif "kb-whisper" in self.model.model_name.lower():
            kwargs["language"] = "sv"
            logger.debug(
                f"[LiteLLM] {self.litellm_model}: Setting language=sv for KB-Whisper"
            )

        logger.info(
            f"[LiteLLM] {self.litellm_model}: Making transcription request for chunk"
        )

        try:
            with open(file_path, "rb") as audio_file:
                response = await litellm_transport.atranscription(
                    model=self.litellm_model,
                    file=audio_file,
                    **kwargs,
                )

            logger.debug(f"[LiteLLM] {self.litellm_model}: Transcription successful")
            return response.text  # type: ignore[return-value]

        except Exception as e:
            logger.exception(f"[LiteLLM] {self.litellm_model}: Unknown exception:")
            litellm_transport.raise_public_litellm_error(
                e,
                provider_type=self.provider_type,
                is_unavailable=litellm_transport.is_provider_unavailable_error,
                raise_unavailable=litellm_transport.raise_provider_unavailable,
            )
