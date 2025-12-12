# MIT License

from pathlib import Path
from typing import TYPE_CHECKING

import litellm
from fastapi import HTTPException
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from intric.files.audio import AudioFile
from intric.main.exceptions import BadRequestException, OpenAIException
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.model_providers.infrastructure.tenant_model_credential_resolver import (
        TenantModelCredentialResolver,
    )
    from intric.transcription_models.domain import TranscriptionModel

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
    ):
        self.model = model
        self.credential_resolver = credential_resolver
        self.provider_type = provider_type

        # Construct LiteLLM model name with provider prefix
        # LiteLLM requires the provider prefix to know which client to use
        # Users should set provider_type to a LiteLLM-compatible value
        # (e.g., "openai", "hosted_vllm" for OpenAI-compatible APIs)
        self.litellm_model = f"{provider_type}/{model.model_name}"

        logger.debug(
            f"[LiteLLM] Initializing transcription adapter for model: {model.name} -> {self.litellm_model}"
        )

    def _mask_api_key(self, api_key: str) -> str:
        """Mask API key for safe logging."""
        return f"...{api_key[-4:]}" if len(api_key) > 4 else "***"

    def _prepare_kwargs(self) -> dict:
        """
        Prepare kwargs for LiteLLM transcription call with credentials.
        """
        kwargs = {}

        # Inject API key (required)
        api_key = self.credential_resolver.get_api_key()
        kwargs["api_key"] = api_key

        # Inject custom endpoint if present (for berget, hosted_vllm, etc.)
        endpoint = self.credential_resolver.get_credential_field(field="endpoint")
        if endpoint:
            kwargs["api_base"] = endpoint
            logger.debug(
                f"[LiteLLM] {self.litellm_model}: Injecting endpoint: {endpoint}"
            )

        logger.debug(
            f"[LiteLLM] {self.litellm_model}: Prepared kwargs with api_key={self._mask_api_key(api_key)}"
        )

        return kwargs

    async def get_text_from_file(self, audio_file: AudioFile) -> str:
        """
        Transcribe an audio file, splitting into 5-minute chunks with timestamps.
        """
        text = ""
        five_minutes = 60 * 5
        chunk_index = 0
        total_duration_seconds = int(audio_file.info.duration)

        async with audio_file.asplit_file(seconds=five_minutes) as files:
            total_chunks = len(files)

            for i, path in enumerate(files):
                block_text = await self._transcribe_chunk(path)
                start_time = chunk_index * five_minutes

                # For the last chunk, calculate the correct end time based on total duration
                if i == total_chunks - 1:
                    end_time = total_duration_seconds
                else:
                    end_time = (chunk_index + 1) * five_minutes

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
        retry=retry_if_not_exception_type(BadRequestException),
        reraise=True,
    )
    async def _transcribe_chunk(self, file_path: Path) -> str:
        """
        Transcribe a single audio chunk using LiteLLM.
        """
        kwargs = self._prepare_kwargs()

        # Set language for Swedish models (KB-Whisper)
        if "kb-whisper" in self.model.model_name.lower():
            kwargs["language"] = "sv"
            logger.debug(
                f"[LiteLLM] {self.litellm_model}: Setting language=sv for KB-Whisper"
            )

        logger.info(
            f"[LiteLLM] {self.litellm_model}: Making transcription request for chunk"
        )

        try:
            with open(file_path, "rb") as audio_file:
                response = await litellm.atranscription(
                    model=self.litellm_model,
                    file=audio_file,
                    **kwargs,
                )

            logger.debug(f"[LiteLLM] {self.litellm_model}: Transcription successful")
            return response.text

        except litellm.AuthenticationError:
            logger.error(
                f"[LiteLLM] {self.litellm_model}: Authentication failed",
                extra={
                    "provider_id": str(self.credential_resolver.provider_id),
                    "provider_type": self.provider_type,
                },
            )
            raise HTTPException(
                status_code=401,
                detail=f"Invalid API credentials for provider {self.provider_type}. "
                "Please verify your API key configuration.",
            )
        except litellm.BadRequestError as e:
            logger.exception(f"[LiteLLM] {self.litellm_model}: Bad request error:")
            raise BadRequestException("Invalid input") from e
        except litellm.RateLimitError as e:
            logger.exception(f"[LiteLLM] {self.litellm_model}: Rate limit error:")
            raise OpenAIException("LiteLLM Rate limit exception") from e
        except Exception as e:
            logger.exception(f"[LiteLLM] {self.litellm_model}: Unknown exception:")
            raise OpenAIException(f"Unknown LiteLLM exception: {e}") from e
