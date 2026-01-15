# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

import base64
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import litellm
from fastapi import HTTPException
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from intric.ai_models.litellm_providers.provider_registry import LiteLLMProviderRegistry
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException, OpenAIException
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.image_models.domain.image_model import ImageModel
    from intric.settings.credential_resolver import CredentialResolver

logger = get_logger(__name__)


@dataclass
class ImageGenerationResult:
    """Result from image generation."""

    blob: bytes
    mimetype: str
    revised_prompt: Optional[str] = None


class LiteLLMImageAdapter:
    """Adapter for generating images using LiteLLM."""

    def __init__(
        self,
        model: "ImageModel",
        credential_resolver: Optional["CredentialResolver"] = None,
    ):
        self.model = model
        self.credential_resolver = credential_resolver

        # Store the original model name for provider detection
        self._original_model_name = model.litellm_model_name or model.name

        # Get provider configuration based on litellm_model_name
        if model.litellm_model_name:
            provider = LiteLLMProviderRegistry.get_provider_for_model(
                model.litellm_model_name
            )

            if provider.needs_custom_config():
                self.litellm_model = provider.get_litellm_model(model.litellm_model_name)
                self.api_config = provider.get_api_config()
                logger.debug(
                    f"[LiteLLM] Using custom provider config for image model "
                    f"{model.name}: {list(self.api_config.keys())}"
                )
            else:
                self.litellm_model = model.litellm_model_name
                self.api_config = {}
        else:
            # Use the model name directly for standard providers
            self.litellm_model = model.name
            self.api_config = {}

        logger.debug(
            f"[LiteLLM] Initializing image adapter for model: "
            f"{model.name} -> {self.litellm_model}"
        )

    def _mask_sensitive_params(self, params: dict) -> dict:
        """Return copy of params with masked API key for safe logging."""
        safe_params = params.copy()
        if "api_key" in safe_params:
            key = safe_params["api_key"]
            safe_params["api_key"] = f"...{key[-4:]}" if len(key) > 4 else "***"
        return safe_params

    def _detect_provider(self, model_name: str) -> str:
        """Detect provider from model name using shared registry logic."""
        return LiteLLMProviderRegistry.detect_provider_from_model_name(model_name)

    @retry(
        wait=wait_random_exponential(min=1, max=20),
        stop=stop_after_attempt(3),
        retry=retry_if_not_exception_type(BadRequestException),
        reraise=True,
    )
    async def generate_images(
        self,
        prompt: str,
        n: int = 1,
        size: str = "1024x1024",
        quality: str = "standard",
    ) -> list[ImageGenerationResult]:
        """
        Generate images using LiteLLM.

        Args:
            prompt: Text prompt for image generation
            n: Number of images to generate (1-4)
            size: Image size (e.g., "1024x1024")
            quality: Image quality (e.g., "standard", "hd")

        Returns:
            List of ImageGenerationResult with blob data and metadata
        """
        try:
            # Validate parameters against model capabilities
            num_images = min(n, self.model.max_images_per_request)
            if size not in self.model.supported_sizes:
                size = self.model.supported_sizes[0] if self.model.supported_sizes else "1024x1024"
            if quality not in self.model.supported_qualities:
                quality = self.model.supported_qualities[0] if self.model.supported_qualities else "standard"

            # Build request parameters
            params = {
                "prompt": prompt,
                "model": self.litellm_model,
                "n": num_images,
                "size": size,
                "quality": quality,
                "response_format": "b64_json",  # Get base64 data for storage
            }

            # Add provider-specific API configuration
            if self.api_config:
                params.update(self.api_config)
                logger.debug(
                    f"[LiteLLM] {self.litellm_model}: Adding provider config: "
                    f"{list(self.api_config.keys())}"
                )

            # Inject tenant-specific API key if credential_resolver is provided
            if self.credential_resolver:
                provider = self._detect_provider(self._original_model_name)
                try:
                    api_key = self.credential_resolver.get_api_key(provider)
                    params["api_key"] = api_key
                    logger.debug(
                        f"[LiteLLM] {self.litellm_model}: Injecting tenant API key for {provider}"
                    )
                except ValueError as e:
                    logger.error(
                        f"[LiteLLM] {self.litellm_model}: Credential resolution failed: {e}"
                    )
                    raise HTTPException(
                        status_code=503,
                        detail=f"Image generation service unavailable: {str(e)}",
                    )

                # Inject endpoint for Azure and other providers with custom endpoints
                settings = get_settings()
                endpoint = self.credential_resolver.get_credential_field(
                    provider=provider,
                    field="endpoint",
                    required=(provider in {"azure"}),
                )

                if endpoint:
                    params["api_base"] = endpoint
                    logger.debug(
                        f"[LiteLLM] {self.litellm_model}: Injecting endpoint: {endpoint}"
                    )

                # Inject api_version for Azure
                if provider == "azure":
                    api_version = self.credential_resolver.get_credential_field(
                        "azure",
                        "api_version",
                        settings.azure_api_version,
                        required=(
                            self.credential_resolver.tenant is not None
                            and self.credential_resolver.settings.tenant_credentials_enabled
                        ),
                    )
                    if api_version:
                        params["api_version"] = api_version
                        logger.debug(
                            f"[LiteLLM] {self.litellm_model}: Injecting api_version: {api_version}"
                        )

            safe_params = {k: v for k, v in params.items() if k != "prompt"}
            logger.debug(
                f"[LiteLLM] {self.litellm_model}: Making image generation request with params: "
                f"{self._mask_sensitive_params(safe_params)}"
            )

            # Call LiteLLM API to generate images
            response = await litellm.aimage_generation(**params)

            logger.debug(f"[LiteLLM] {self.litellm_model}: Image generation successful")

            # Process results
            results = []
            revised_prompt = getattr(response, "revised_prompt", None)

            for image_data in response.data:
                # Handle both b64_json and url responses
                if hasattr(image_data, "b64_json") and image_data.b64_json:
                    blob = base64.b64decode(image_data.b64_json)
                elif hasattr(image_data, "url") and image_data.url:
                    # Download from URL if b64_json not available
                    import httpx

                    async with httpx.AsyncClient() as client:
                        img_response = await client.get(image_data.url)
                        blob = img_response.content
                else:
                    logger.warning(
                        f"[LiteLLM] {self.litellm_model}: No image data in response"
                    )
                    continue

                # Use revised_prompt from individual image if available
                img_revised_prompt = getattr(image_data, "revised_prompt", revised_prompt)

                results.append(
                    ImageGenerationResult(
                        blob=blob,
                        mimetype="image/png",  # LiteLLM returns PNG by default
                        revised_prompt=img_revised_prompt,
                    )
                )

            return results

        except litellm.AuthenticationError:
            provider = self._detect_provider(self._original_model_name)
            tenant_id = (
                self.credential_resolver.tenant.id
                if self.credential_resolver and self.credential_resolver.tenant
                else None
            )
            tenant_name = (
                self.credential_resolver.tenant.name
                if self.credential_resolver and self.credential_resolver.tenant
                else None
            )

            logger.error(
                "Tenant API credential authentication failed for image generation",
                extra={
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "tenant_name": tenant_name,
                    "provider": provider,
                    "error_type": "AuthenticationError",
                    "model": self.litellm_model,
                },
            )

            raise HTTPException(
                status_code=401,
                detail=f"Invalid API credentials for provider {provider}. "
                f"Please verify your API key configuration.",
            )
        except litellm.BadRequestError as e:
            logger.exception(f"[LiteLLM] {self.litellm_model}: Bad request error:")
            raise BadRequestException(f"Invalid image generation request: {str(e)}") from e
        except litellm.RateLimitError as e:
            logger.exception(f"[LiteLLM] {self.litellm_model}: Rate limit error:")
            raise OpenAIException("Image generation rate limit exceeded") from e
        except litellm.ContentPolicyViolationError as e:
            logger.warning(f"[LiteLLM] {self.litellm_model}: Content policy violation:")
            raise BadRequestException(
                "Your prompt was rejected due to content policy. "
                "Please modify your prompt and try again."
            ) from e
        except Exception as e:
            logger.exception(f"[LiteLLM] {self.litellm_model}: Unknown error:")
            raise OpenAIException(f"Image generation failed: {str(e)}") from e
