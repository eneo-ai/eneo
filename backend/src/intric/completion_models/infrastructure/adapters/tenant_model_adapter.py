"""Minimal adapter for tenant models using LiteLLM."""
import base64
import re
from typing import TYPE_CHECKING, AsyncIterator

import litellm
from litellm import (
    AuthenticationError,
    APIError,
    BadRequestError,
    RateLimitError,
    get_supported_openai_params,
)

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

# Regex to match Qwen3 thinking blocks: <think>...</think>
THINKING_BLOCK_PATTERN = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

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

    def _mask_sensitive_params(self, params: dict) -> dict:
        """Return copy of params with masked API key for safe logging."""
        safe_params = params.copy()
        if "api_key" in safe_params:
            key = safe_params["api_key"]
            safe_params["api_key"] = f"...{key[-4:]}" if len(key) > 4 else "***"
        return safe_params

    def _get_dropped_params(self, litellm_kwargs: dict) -> set:
        """Get which params will be dropped by LiteLLM for this model."""
        # Params that are not model params (credentials, config)
        non_model_params = {"api_key", "api_base", "api_version", "api_type", "organization", "deployment_name"}

        try:
            # Get supported params for this model
            supported = get_supported_openai_params(model=self.litellm_model)
            if supported is None:
                logger.debug(f"Could not determine supported params for {self.litellm_model}")
                return set()

            supported_set = set(supported)
            params_to_send = set(litellm_kwargs.keys()) - non_model_params
            dropped = params_to_send - supported_set

            if dropped:
                logger.warning(
                    f"[TenantModelAdapter] Dropping unsupported params for {self.litellm_model}: {dropped}"
                )

            return dropped
        except Exception as e:
            # Don't fail the request if we can't check params
            logger.debug(f"Could not check supported params for {self.litellm_model}: {e}")
            return set()

    def _get_effective_params(self, litellm_kwargs: dict, dropped: set) -> dict:
        """Return params dict with dropped params removed and API key masked."""
        effective = {k: v for k, v in litellm_kwargs.items() if k not in dropped}
        return self._mask_sensitive_params(effective)

    def _strip_thinking_content(self, text: str) -> str:
        """
        Strip Qwen3-style thinking blocks from response text.

        Qwen3 models with thinking enabled wrap reasoning in <think>...</think> tags.
        This method removes those blocks to return only the final response.

        Args:
            text: Response text potentially containing thinking blocks

        Returns:
            str: Text with thinking blocks removed
        """
        if not text:
            return text
        return THINKING_BLOCK_PATTERN.sub("", text).strip()

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

            # Only pass reasoning_effort for models that support reasoning
            if "reasoning_effort" in model_kwargs_dict and not self.model.reasoning:
                del model_kwargs_dict["reasoning_effort"]

            # Ensure max_tokens is set - some APIs (e.g., vLLM, OpenAI-compatible)
            # require it explicitly or return empty responses
            if "max_tokens" not in model_kwargs_dict and "max_completion_tokens" not in model_kwargs_dict:
                # Use 1/4 of model's token limit, capped at 4096
                default_max = min(self.model.token_limit // 4, 4096) if self.model.token_limit else 4096
                model_kwargs_dict["max_tokens"] = default_max
                logger.debug(f"Added default max_tokens={default_max} (from token_limit={self.model.token_limit})")

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

        # Check which params will be dropped and log effective params
        dropped = self._get_dropped_params(litellm_kwargs)

        logger.info(
            f"[TenantModelAdapter] Making completion request to {self.litellm_model} "
            f"with {len(messages)} messages, params: {self._get_effective_params(litellm_kwargs, dropped)}"
        )

        try:
            # Call LiteLLM with drop_params=True to handle unsupported params gracefully
            response = await litellm.acompletion(
                model=self.litellm_model,
                messages=messages,
                stream=False,
                drop_params=True,
                **litellm_kwargs,
            )

            # Parse response
            completion = Completion()
            if response.choices and len(response.choices) > 0:
                choice = response.choices[0]

                if hasattr(choice.message, "content"):
                    content = choice.message.content
                    # Strip thinking blocks for models like Qwen3
                    completion.text = self._strip_thinking_content(content)
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

        except BadRequestError as exc:
            # Surface the actual error message for invalid parameters/values
            error_message = str(exc)
            logger.error(
                f"Bad request for tenant model {self.model.name}: {error_message}",
                extra={
                    "provider_type": self.provider_type,
                    "model": self.litellm_model,
                },
            )
            raise OpenAIException(f"Invalid request: {error_message}") from exc

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

        # Check which params will be dropped and log effective params
        dropped = self._get_dropped_params(litellm_kwargs)

        logger.info(
            f"[TenantModelAdapter] Creating streaming connection to {self.litellm_model} "
            f"with {len(messages)} messages, params: {self._get_effective_params(litellm_kwargs, dropped)}"
        )

        try:
            # Create stream with drop_params=True to handle unsupported params gracefully
            stream = await litellm.acompletion(
                model=self.litellm_model,
                messages=messages,
                stream=True,
                drop_params=True,
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

        except BadRequestError as exc:
            # Surface the actual error message for invalid parameters/values
            error_message = str(exc)
            logger.error(
                f"Bad request for streaming tenant model {self.model.name}: {error_message}",
                extra={
                    "provider_type": self.provider_type,
                    "model": self.litellm_model,
                },
            )
            raise OpenAIException(f"Invalid request: {error_message}") from exc

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

            # Buffer for handling thinking blocks that span chunks
            buffer = ""
            inside_thinking = False
            thinking_stripped = False

            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta

                    content = ""
                    if hasattr(delta, "content") and delta.content:
                        content = delta.content

                    finish_reason = chunk.choices[0].finish_reason

                    # Handle thinking blocks for Qwen3-style models
                    if content:
                        buffer += content

                        # Check if we're entering a thinking block
                        if "<think>" in buffer and not inside_thinking:
                            inside_thinking = True
                            # Keep content before <think>
                            pre_think = buffer.split("<think>")[0]
                            if pre_think.strip():
                                yield Completion(text=pre_think)
                            buffer = buffer[buffer.index("<think>"):]

                        # Check if thinking block is complete
                        if inside_thinking and "</think>" in buffer:
                            inside_thinking = False
                            thinking_stripped = True
                            # Get content after </think>
                            post_think = buffer.split("</think>", 1)[1].lstrip()
                            buffer = post_think
                            if buffer:
                                yield Completion(text=buffer)
                                buffer = ""

                        # If not in thinking block, yield content
                        if not inside_thinking and buffer and not thinking_stripped:
                            yield Completion(text=buffer)
                            buffer = ""
                        elif not inside_thinking and buffer and thinking_stripped:
                            yield Completion(text=buffer)
                            buffer = ""

                    # Handle final chunk
                    if finish_reason:
                        # Yield any remaining buffer (stripped of thinking if incomplete)
                        if buffer and not inside_thinking:
                            cleaned = self._strip_thinking_content(buffer)
                            if cleaned:
                                yield Completion(text=cleaned)
                        yield Completion(text="", stop=finish_reason == "stop")

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
