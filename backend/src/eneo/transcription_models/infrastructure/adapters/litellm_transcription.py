# MIT License

import asyncio
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from eneo.files.audio import AudioFile
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
    ) -> str:
        """
        Transcribe an audio file, splitting into 5-minute chunks with timestamps.
        """
        text = ""
        five_minutes = 60 * 5
        chunk_index = 0
        total_duration_seconds = int(audio_file.duration)

        async with audio_file.asplit_file(seconds=five_minutes) as files:
            total_chunks = len(files)

            for i, path in enumerate(files):
                start_time = chunk_index * five_minutes
                chunk_end = (
                    total_duration_seconds
                    if i == total_chunks - 1
                    else (chunk_index + 1) * five_minutes
                )
                block_text = await self._transcribe_chunk(
                    path,
                    language=language,
                    observer=observer,
                    audio_seconds=max(float(chunk_end - start_time), 0.0),
                )

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

        return text

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
        audio_seconds: float = 0.0,
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
            if observer is not None and call_id is not None:
                await observer.outcome_unknown(call_id, "provider_error")
            litellm_transport.raise_public_litellm_error(
                e,
                provider_type=self.provider_type,
                is_unavailable=litellm_transport.is_provider_unavailable_error,
                raise_unavailable=litellm_transport.raise_provider_unavailable,
            )
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
        return response.text  # type: ignore[return-value]


def _digest_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
