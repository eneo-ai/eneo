"""Minimal adapter for tenant models using LiteLLM."""
import base64
from typing import TYPE_CHECKING, AsyncIterator

import litellm
from litellm import AuthenticationError, APIError, RateLimitError

from intric.ai_models.completion_models.completion_model import Completion, ResponseType
from intric.completion_models.infrastructure.adapters.base_adapter import (
    CompletionModelAdapter,
)
from intric.files.file_models import File
from intric.main.exceptions import APIKeyNotConfiguredException, OpenAIException
from intric.main.logging import get_logger
from intric.model_providers.infrastructure.tenant_model_credential_resolver import (
    TenantModelCredentialResolver,
)

logger = get_logger(__name__)

TOKENS_RESERVED_FOR_COMPLETION = 1000

if TYPE_CHECKING:
    from intric.ai_models.completion_models.completion_model import Context
    from intric.completion_models.domain.completion_model import CompletionModel


class TenantModelAdapter(CompletionModelAdapter):
    """
    Minimal adapter for tenant models that conform to LiteLLM standards.
    Auto-constructs LiteLLM model name from provider type + model name.
    No special cases - just passes credentials and endpoint to LiteLLM.

    Examples:
        - OpenAI: "openai/gpt-4o"
        - Azure: "azure/my-deployment"
        - vLLM: "openai/meta-llama/Meta-Llama-3-70B-Instruct"
        - Anthropic: "anthropic/claude-3-5-sonnet-20241022"
    """

    def __init__(
        self,
        model: "CompletionModel",
        credential_resolver: TenantModelCredentialResolver,
        provider_type: str,
    ):
        """
        Initialize adapter with tenant model.

        Args:
            model: Tenant completion model (must have provider_id)
            credential_resolver: Resolver for tenant provider credentials
            provider_type: LiteLLM provider type (e.g., "openai", "azure", "anthropic")

        Raises:
            ValueError: If model is not a tenant model
        """
        if not hasattr(model, "provider_id") or not model.provider_id:
            raise ValueError(
                "TenantModelAdapter requires a tenant model with provider_id"
            )

        super().__init__(model)
        self.credential_resolver = credential_resolver

        # Construct LiteLLM model name with provider prefix
        # LiteLLM requires the provider prefix to know which client to use
        # When using custom api_base, LiteLLM strips one prefix level and sends the rest to the API
        # Example: "openai/openai/gpt-4" -> sends "openai/gpt-4" to custom endpoint
        self.litellm_model = f"{provider_type}/{model.name}"
        self.provider_type = provider_type

    def _build_image(self, file: File) -> dict:
        """
        Build image content block for OpenAI-compatible format.

        Args:
            file: Image file with blob data

        Returns:
            dict: Image content in OpenAI format
        """
        image_data = base64.b64encode(file.blob).decode("utf-8")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{file.mimetype};base64,{image_data}"},
        }

    def _build_content(self, input: str, images: list[File]) -> list[dict] | str:
        """
        Build message content with text and images.

        Args:
            input: Text content
            images: List of image files

        Returns:
            list[dict] | str: Content array if images present, otherwise string
        """
        # Build content array with text
        content = []
        if input:
            content.append({"type": "text", "text": input})

        # Add images
        for image in images:
            content.append(self._build_image(image))

        # Return string if only text, array if images included
        if len(content) == 1 and content[0].get("type") == "text":
            return input
        return content

    def _build_tools_from_context(self, context: "Context") -> list[dict]:
        """
        Build tools/functions array from context function definitions.

        Args:
            context: Context with function definitions

        Returns:
            list[dict]: Tools in format appropriate for provider
        """
        if not context.function_definitions:
            return []

        # Only enable tools for vision models (same logic as other adapters)
        if not self.model.vision:
            return []

        # Use OpenAI format (compatible with most providers via LiteLLM)
        return [
            {
                "type": "function",
                "function": {
                    "name": func_def.name,
                    "description": func_def.description,
                    "parameters": func_def.schema,
                    "strict": True,
                },
            }
            for func_def in context.function_definitions
        ]

    def _create_messages_from_context(self, context: "Context") -> list[dict]:
        """
        Convert Intric context to OpenAI message format with vision support.

        Args:
            context: Intric context with messages in question/answer format

        Returns:
            list: Messages in OpenAI format with role/content (including images)
        """
        messages = []

        # Add system message if prompt exists
        if context.prompt:
            messages.append({"role": "system", "content": context.prompt})

        # Convert previous Q&A pairs to user/assistant messages (with images)
        for msg in context.messages:
            # User message with question + images
            messages.append({
                "role": "user",
                "content": self._build_content(
                    input=msg.question,
                    images=msg.images + msg.generated_images,
                ),
            })
            # Assistant response
            messages.append({
                "role": "assistant",
                "content": msg.answer or "[image generated]",
            })

        # Add current question with images
        messages.append({
            "role": "user",
            "content": self._build_content(
                input=context.input,
                images=context.images,
            ),
        })

        return messages

    def _prepare_kwargs(self, model_kwargs: dict = None, **additional_kwargs) -> dict:
        """
        Prepare kwargs for LiteLLM call with credentials and provider-specific handling.

        Args:
            model_kwargs: Model parameters (temperature, etc.)
            **additional_kwargs: Additional parameters to pass to LiteLLM

        Returns:
            dict: LiteLLM kwargs with api_key, api_base, and config fields
        """
        kwargs = {}

        # Inject API key (required)
        api_key = self.credential_resolver.get_api_key()
        if api_key:
            kwargs["api_key"] = api_key
        else:
            raise ValueError(f"No API key available for tenant model {self.model.name}")

        # Inject custom endpoint if present
        endpoint = self.credential_resolver.get_credential_field(field="endpoint")
        if endpoint:
            kwargs["api_base"] = endpoint

        # Inject additional config fields (e.g., api_version for Azure)
        config_fields = ["api_version", "api_type", "organization"]
        for field in config_fields:
            value = self.credential_resolver.get_credential_field(field=field)
            if value:
                kwargs[field] = value

        # Handle Azure deployment name if present
        if self.model.deployment_name and self.provider_type == "azure":
            # Azure models use deployment_name instead of model name
            kwargs["deployment_name"] = self.model.deployment_name

        # Process model kwargs with provider-specific adjustments
        if model_kwargs:
            # Convert Pydantic ModelKwargs to dict if needed
            if hasattr(model_kwargs, 'model_dump'):
                model_kwargs_dict = model_kwargs.model_dump(exclude_none=True)
            elif hasattr(model_kwargs, 'dict'):
                model_kwargs_dict = model_kwargs.dict(exclude_none=True)
            else:
                model_kwargs_dict = model_kwargs if isinstance(model_kwargs, dict) else {}

            # Claude-specific: Scale temperature from (0, 2) to (0, 1)
            if self.provider_type == "anthropic" and "temperature" in model_kwargs_dict:
                temp = model_kwargs_dict["temperature"]
                if temp is not None:
                    model_kwargs_dict["temperature"] = temp / 2
                    logger.debug(
                        f"Scaled temperature for Anthropic: {temp} -> {temp / 2}"
                    )

            # Reasoning model support: Add max_completion_tokens for reasoning models
            if self.model.reasoning:
                # O1 and similar reasoning models need max_completion_tokens
                if "max_completion_tokens" not in model_kwargs_dict:
                    model_kwargs_dict["max_completion_tokens"] = 5000
                    logger.debug("Added max_completion_tokens=5000 for reasoning model")

            kwargs.update(model_kwargs_dict)

        # Merge with additional kwargs
        kwargs.update(additional_kwargs)

        return kwargs

    async def get_response(
        self,
        context: "Context",
        model_kwargs: dict,
        **kwargs,
    ) -> Completion:
        """
        Get non-streaming completion from tenant model.

        Args:
            context: Conversation context with messages
            model_kwargs: Model parameters (temperature, etc.)
            **kwargs: Additional kwargs

        Returns:
            Completion: Response from model

        Raises:
            APIKeyNotConfiguredException: If credentials are invalid
            OpenAIException: For API errors, rate limits, network issues
        """
        # Prepare LiteLLM kwargs with credentials and provider-specific handling
        litellm_kwargs = self._prepare_kwargs(model_kwargs=model_kwargs, **kwargs)

        # Convert messages to OpenAI format (with vision support)
        messages = self._create_messages_from_context(context)

        # Add tools if function definitions are present
        tools = self._build_tools_from_context(context)
        if tools:
            litellm_kwargs["tools"] = tools

        logger.info(
            f"[TenantModelAdapter] Making completion request to {self.litellm_model} "
            f"with {len(messages)} messages"
        )

        try:
            # Call LiteLLM
            response = await litellm.acompletion(
                model=self.litellm_model,
                messages=messages,
                stream=False,
                **litellm_kwargs,
            )

            # Parse response
            completion = Completion()
            if response.choices and len(response.choices) > 0:
                choice = response.choices[0]
                if hasattr(choice.message, "content"):
                    completion.text = choice.message.content
                completion.stop = choice.finish_reason == "stop"

            logger.info(f"[TenantModelAdapter] {self.litellm_model}: Completion successful")
            return completion

        except AuthenticationError as exc:
            logger.error(
                f"Authentication failed for tenant model {self.model.name}",
                extra={
                    "provider_type": self.provider_type,
                    "model": self.litellm_model,
                    "error_type": "AuthenticationError",
                },
            )
            raise APIKeyNotConfiguredException(
                f"Invalid API credentials for provider '{self.provider_type}'. "
                f"Please verify your API key configuration."
            ) from exc

        except RateLimitError as exc:
            logger.error(
                f"Rate limit error for tenant model {self.model.name}",
                extra={
                    "provider_type": self.provider_type,
                    "model": self.litellm_model,
                },
            )
            raise OpenAIException(
                f"Rate limit exceeded for {self.provider_type}. Please try again later."
            ) from exc

        except APIError as exc:
            error_message = str(exc)
            logger.error(
                f"API error for tenant model {self.model.name}: {error_message}",
                extra={
                    "provider_type": self.provider_type,
                    "model": self.litellm_model,
                },
            )

            # Check for specific error types
            if "Virtual Network/Firewall" in error_message or "Firewall rules" in error_message:
                raise OpenAIException(
                    "Access denied: Virtual Network/Firewall rules. "
                    "Please check your network configuration."
                ) from exc
            elif "rate limit" in error_message.lower():
                raise OpenAIException(
                    f"Rate limit exceeded for {self.provider_type}. Please try again later."
                ) from exc
            else:
                raise OpenAIException(f"API error: {error_message}") from exc

        except Exception as exc:
            logger.exception(
                f"[TenantModelAdapter] Unexpected error for {self.litellm_model}"
            )
            raise OpenAIException("Unknown error occurred") from exc

    async def prepare_streaming(
        self,
        context: "Context",
        model_kwargs: dict,
        **kwargs,
    ) -> AsyncIterator:
        """
        Initialize streaming completion from tenant model.
        Phase 1: Create stream connection before EventSourceResponse.

        Args:
            context: Conversation context with messages
            model_kwargs: Model parameters (temperature, etc.)
            **kwargs: Additional kwargs

        Returns:
            AsyncIterator: Stream of completion chunks

        Raises:
            APIKeyNotConfiguredException: If credentials are invalid
            OpenAIException: For API errors, rate limits, network issues
        """
        # Prepare LiteLLM kwargs with credentials and provider-specific handling
        litellm_kwargs = self._prepare_kwargs(model_kwargs=model_kwargs, **kwargs)

        # Convert messages to OpenAI format (with vision support)
        messages = self._create_messages_from_context(context)

        # Add tools if function definitions are present
        tools = self._build_tools_from_context(context)
        if tools:
            litellm_kwargs["tools"] = tools

        logger.info(
            f"[TenantModelAdapter] Creating streaming connection to {self.litellm_model} "
            f"with {len(messages)} messages"
        )

        try:
            # Create stream - can raise exceptions for auth/network errors
            stream = await litellm.acompletion(
                model=self.litellm_model,
                messages=messages,
                stream=True,
                **litellm_kwargs,
            )

            logger.info(
                f"[TenantModelAdapter] {self.litellm_model}: Stream connection created successfully"
            )
            return stream

        except AuthenticationError as exc:
            logger.error(
                f"Authentication failed for streaming tenant model {self.model.name}",
                extra={
                    "provider_type": self.provider_type,
                    "model": self.litellm_model,
                    "error_type": "AuthenticationError",
                },
            )
            raise APIKeyNotConfiguredException(
                f"Invalid API credentials for provider '{self.provider_type}'. "
                f"Please verify your API key configuration."
            ) from exc

        except RateLimitError as exc:
            logger.error(
                f"Rate limit error for streaming tenant model {self.model.name}",
                extra={
                    "provider_type": self.provider_type,
                    "model": self.litellm_model,
                },
            )
            raise OpenAIException(
                f"Rate limit exceeded for {self.provider_type}. Please try again later."
            ) from exc

        except APIError as exc:
            error_message = str(exc)
            logger.error(
                f"API error for streaming tenant model {self.model.name}: {error_message}",
                extra={
                    "provider_type": self.provider_type,
                    "model": self.litellm_model,
                },
            )

            # Check for specific error types
            if "Virtual Network/Firewall" in error_message or "Firewall rules" in error_message:
                raise OpenAIException(
                    "Access denied: Virtual Network/Firewall rules. "
                    "Please check your network configuration."
                ) from exc
            elif "rate limit" in error_message.lower():
                raise OpenAIException(
                    f"Rate limit exceeded for {self.provider_type}. Please try again later."
                ) from exc
            else:
                raise OpenAIException(f"API error: {error_message}") from exc

        except Exception as exc:
            logger.exception(
                f"[TenantModelAdapter] Unexpected error creating stream for {self.litellm_model}"
            )
            raise OpenAIException("Unknown error occurred") from exc

    async def iterate_stream(
        self,
        stream: AsyncIterator,
        context: "Context" = None,
        model_kwargs: dict = None
    ) -> AsyncIterator[Completion]:
        """
        Iterate streaming response from tenant model.
        Phase 2: Iterate pre-created stream inside EventSourceResponse.

        Args:
            stream: Stream from prepare_streaming()
            context: Optional conversation context (for logging)
            model_kwargs: Optional model parameters (for logging)

        Yields:
            Completion: Chunks of completion (yields error events for mid-stream failures)
        """
        try:
            logger.info(f"[TenantModelAdapter] {self.litellm_model}: Starting stream iteration")

            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta

                    completion = Completion()
                    if hasattr(delta, "content") and delta.content:
                        completion.text = delta.content

                    finish_reason = chunk.choices[0].finish_reason
                    if finish_reason:
                        completion.stop = finish_reason == "stop"

                    # Only yield if there's content or it's the final chunk
                    if completion.text or completion.stop:
                        yield completion

            logger.info(f"[TenantModelAdapter] {self.litellm_model}: Stream iteration completed")

        except Exception as exc:
            # Mid-stream errors: yield error event instead of raising
            logger.error(
                f"[TenantModelAdapter] {self.litellm_model}: Error during stream iteration: {exc}"
            )
            yield Completion(
                text="",
                error=f"Stream error: {str(exc)}",
                error_code=500,
                response_type=ResponseType.ERROR,
                stop=True
            )

    def get_token_limit_of_model(self) -> int:
        """
        Get token limit for tenant model (with reserved space for completion).

        Returns:
            int: Maximum tokens available for input context
        """
        return self.model.token_limit - TOKENS_RESERVED_FOR_COMPLETION
