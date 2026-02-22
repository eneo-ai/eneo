"""Minimal adapter for tenant models using LiteLLM."""

import base64
import json
import re
import uuid
from typing import TYPE_CHECKING, AsyncIterator

import litellm
from litellm import (
    AuthenticationError,
    APIError,
    BadRequestError,
    RateLimitError,
    get_supported_openai_params,
)

from intric.ai_models.completion_models.completion_model import (
    Completion,
    ResponseType,
    ToolCallMetadata,
)
from intric.completion_models.infrastructure.adapters.base_adapter import (
    CompletionModelAdapter,
)
from intric.files.file_models import File
from intric.logging.logging import LoggingDetails
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
    from intric.mcp_servers.infrastructure.proxy import MCPProxySession
    from intric.mcp_servers.infrastructure.tool_approval import ToolApprovalManager


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
        non_model_params = {
            "api_key",
            "api_base",
            "api_version",
            "api_type",
            "organization",
            "deployment_name",
        }

        try:
            # Get supported params for this model
            supported = get_supported_openai_params(model=self.litellm_model)
            if supported is None:
                logger.debug(
                    f"Could not determine supported params for {self.litellm_model}"
                )
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
            logger.debug(
                f"Could not check supported params for {self.litellm_model}: {e}"
            )
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

    def _merge_mcp_tools(
        self,
        intric_tools: list[dict],
        mcp_proxy: "MCPProxySession | None",
    ) -> list[dict]:
        """Merge Intric built-in tools with MCP proxy tools.

        Only includes MCP tools if the model supports tool calling.
        Models without tool support (e.g. vLLM without --enable-auto-tool-choice)
        will reject requests containing tools.
        """
        if not self.model.supports_tool_calling:
            if mcp_proxy:
                logger.info(
                    f"[MCP] Skipping MCP tools for model '{self.model.name}' "
                    f"(supports_tool_calling=False)"
                )
            return intric_tools
        mcp_tools = mcp_proxy.get_tools_for_llm() if mcp_proxy else []
        return intric_tools + mcp_tools

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
            messages.append(
                {
                    "role": "user",
                    "content": self._build_content(
                        input=msg.question,
                        images=msg.images + msg.generated_images,
                    ),
                }
            )
            # Assistant response
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.answer or "[image generated]",
                }
            )

        # Add current question with images
        messages.append(
            {
                "role": "user",
                "content": self._build_content(
                    input=context.input,
                    images=context.images,
                ),
            }
        )

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
            if hasattr(model_kwargs, "model_dump"):
                model_kwargs_dict = model_kwargs.model_dump(exclude_none=True)
            elif hasattr(model_kwargs, "dict"):
                model_kwargs_dict = model_kwargs.dict(exclude_none=True)
            else:
                model_kwargs_dict = (
                    model_kwargs if isinstance(model_kwargs, dict) else {}
                )

            # Claude-specific: Scale temperature from (0, 2) to (0, 1)
            if self.provider_type == "anthropic" and "temperature" in model_kwargs_dict:
                temp = model_kwargs_dict["temperature"]
                if temp is not None:
                    model_kwargs_dict["temperature"] = temp / 2
                    logger.debug(
                        f"Scaled temperature for Anthropic: {temp} -> {temp / 2}"
                    )

            # Only pass reasoning_effort if the model actually supports it
            # (per LiteLLM's supported_openai_params) and the value is meaningful
            if "reasoning_effort" in model_kwargs_dict:
                supported_params = litellm.get_supported_openai_params(model=self.litellm_model) or []
                if "reasoning_effort" not in supported_params or model_kwargs_dict["reasoning_effort"] in (None, "none", ""):
                    del model_kwargs_dict["reasoning_effort"]

            # Ensure max_tokens is set - some APIs (e.g., vLLM, OpenAI-compatible)
            # require it explicitly or return empty responses
            if (
                "max_tokens" not in model_kwargs_dict
                and "max_completion_tokens" not in model_kwargs_dict
            ):
                # Use 1/4 of model's token limit, capped at 4096
                default_max = (
                    min(self.model.token_limit // 4, 4096)
                    if self.model.token_limit
                    else 4096
                )
                model_kwargs_dict["max_tokens"] = default_max
                logger.debug(
                    f"Added default max_tokens={default_max} (from token_limit={self.model.token_limit})"
                )

            kwargs.update(model_kwargs_dict)

        # Remove non-serializable params that must not reach litellm
        for key in ("mcp_proxy", "require_tool_approval", "approval_manager"):
            additional_kwargs.pop(key, None)

        # Merge with additional kwargs
        kwargs.update(additional_kwargs)

        return kwargs

    async def get_response(
        self,
        context: "Context",
        model_kwargs: dict,
        mcp_proxy: "MCPProxySession | None" = None,
        **kwargs,
    ) -> Completion:
        """
        Get non-streaming completion from tenant model.

        Args:
            context: Conversation context with messages
            model_kwargs: Model parameters (temperature, etc.)
            mcp_proxy: Optional MCP proxy session for tool execution
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

        # Build combined tools (Intric built-in + MCP)
        intric_tools = self._build_tools_from_context(context)
        all_tools = self._merge_mcp_tools(intric_tools, mcp_proxy)
        if all_tools:
            litellm_kwargs["tools"] = all_tools

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

            # DEBUG: Log raw response
            logger.debug(f"[DEBUG] Raw response: {response}")

            # Parse response
            completion = Completion()
            if response.choices and len(response.choices) > 0:
                choice = response.choices[0]
                msg = choice.message

                # DEBUG: Log message details
                logger.debug(f"[DEBUG] Message: {msg}")
                if hasattr(msg, "reasoning_content"):
                    logger.debug(f"[DEBUG] reasoning_content: {msg.reasoning_content}")

                # Check if model wants to call MCP tools
                if hasattr(msg, "tool_calls") and msg.tool_calls and mcp_proxy:
                    allowed_tools = mcp_proxy.get_allowed_tool_names()
                    for tc in msg.tool_calls:
                        if tc.function.name not in allowed_tools:
                            raise OpenAIException(
                                f"Unauthorized MCP tool call: {tc.function.name}"
                            )

                    # Add assistant message with tool calls to conversation
                    messages.append(
                        {
                            "role": "assistant",
                            "content": msg.content,
                            "tool_calls": [
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    },
                                }
                                for tc in msg.tool_calls
                            ],
                        }
                    )

                    # Execute tools via proxy
                    proxy_calls = [
                        (
                            tc.function.name,
                            json.loads(tc.function.arguments)
                            if tc.function.arguments
                            else {},
                        )
                        for tc in msg.tool_calls
                    ]
                    results = await mcp_proxy.call_tools_parallel(proxy_calls)

                    # Add tool results to messages
                    for tc, result in zip(msg.tool_calls, results):
                        result_text = ""
                        if result.get("content"):
                            for ci in result["content"]:
                                if ci.get("type") == "text":
                                    result_text += ci.get("text", "")
                        if result.get("is_error"):
                            result_text = json.dumps(
                                {"error": result_text or "Tool execution failed"}
                            )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": result_text,
                            }
                        )

                    # Follow-up completion without tools
                    follow_up_kwargs = {
                        k: v for k, v in litellm_kwargs.items() if k != "tools"
                    }
                    response = await litellm.acompletion(
                        model=self.litellm_model,
                        messages=messages,
                        stream=False,
                        drop_params=True,
                        **follow_up_kwargs,
                    )
                    msg = response.choices[0].message

                if hasattr(msg, "content") and msg.content:
                    completion.text = self._strip_thinking_content(msg.content)
                completion.stop = choice.finish_reason == "stop"

            logger.info(
                f"[TenantModelAdapter] {self.litellm_model}: Completion successful"
            )
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
            if (
                "Virtual Network/Firewall" in error_message
                or "Firewall rules" in error_message
            ):
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
        mcp_proxy: "MCPProxySession | None" = None,
        **kwargs,
    ) -> AsyncIterator:
        """
        Initialize streaming completion from tenant model.
        Phase 1: Create stream connection before EventSourceResponse.

        Args:
            context: Conversation context with messages
            model_kwargs: Model parameters (temperature, etc.)
            mcp_proxy: Optional MCP proxy session for tool execution
            **kwargs: Additional kwargs

        Returns:
            AsyncIterator: Stream of completion chunks

        Raises:
            APIKeyNotConfiguredException: If credentials are invalid
            OpenAIException: For API errors, rate limits, network issues
        """
        # DEBUG: Log incoming parameters
        logger.debug(f"[DEBUG] model_kwargs received: {model_kwargs}")
        logger.debug(f"[DEBUG] extra kwargs received: {kwargs}")

        # Prepare LiteLLM kwargs with credentials and provider-specific handling
        litellm_kwargs = self._prepare_kwargs(model_kwargs=model_kwargs, **kwargs)

        # Convert messages to OpenAI format (with vision support)
        messages = self._create_messages_from_context(context)

        # Build combined tools (Intric built-in + MCP)
        intric_tools = self._build_tools_from_context(context)
        all_tools = self._merge_mcp_tools(intric_tools, mcp_proxy)
        if all_tools:
            litellm_kwargs["tools"] = all_tools

        # Check which params will be dropped and log effective params
        dropped = self._get_dropped_params(litellm_kwargs)

        logger.info(
            f"[TenantModelAdapter] Creating streaming connection to {self.litellm_model} "
            f"with {len(messages)} messages, params: {self._get_effective_params(litellm_kwargs, dropped)}"
        )

        try:
            # DEBUG: Log what we're sending (with masked credentials)
            logger.debug(f"[DEBUG] litellm_model: {self.litellm_model}")
            logger.debug(f"[DEBUG] messages: {messages}")
            logger.debug(
                f"[DEBUG] litellm_kwargs (effective): {self._get_effective_params(litellm_kwargs, dropped)}"
            )

            # Create stream with drop_params=True to handle unsupported params gracefully
            stream = await litellm.acompletion(
                model=self.litellm_model,
                messages=messages,
                stream=True,
                drop_params=True,
                **litellm_kwargs,
            )

            # Store context for MCP tool execution in iterate_stream
            setattr(
                stream,
                "_eneo_context",
                {
                    "messages": messages,
                    "kwargs": litellm_kwargs,
                    "has_tools": bool(all_tools),
                    "mcp_proxy": mcp_proxy,
                },
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
            if (
                "Virtual Network/Firewall" in error_message
                or "Firewall rules" in error_message
            ):
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
        model_kwargs: dict = None,
        require_tool_approval: bool = False,
        approval_manager: "ToolApprovalManager | None" = None,
    ) -> AsyncIterator[Completion]:
        """
        Iterate streaming response from tenant model.
        Phase 2: Iterate pre-created stream inside EventSourceResponse.

        Handles both thinking-block stripping (Qwen3) and MCP tool call
        accumulation/execution with multi-turn loop support.

        Args:
            stream: Stream from prepare_streaming()
            context: Optional conversation context (for logging)
            model_kwargs: Optional model parameters (for logging)
            require_tool_approval: Whether MCP tool calls need user approval
            approval_manager: Manager for tool approval flow

        Yields:
            Completion: Chunks of completion (yields error events for mid-stream failures)
        """
        try:
            logger.info(
                f"[TenantModelAdapter] {self.litellm_model}: Starting stream iteration"
            )

            # Get MCP context stored by prepare_streaming
            eneo_ctx = getattr(stream, "_eneo_context", None)
            mcp_proxy = eneo_ctx.get("mcp_proxy") if eneo_ctx else None

            # Shared state for tool call accumulation across stream draining
            class _StreamResult:
                has_tool_calls = False
                tool_calls_acc: dict = {}

            result = _StreamResult()

            async def _drain_stream(s, res):
                """Drain a stream: yield text Completions, accumulate tool calls into res."""
                buffer = ""
                inside_thinking = False
                thinking_stripped = False
                res.has_tool_calls = False
                res.tool_calls_acc = {}

                async for chunk in s:
                    # logger.debug(f"[DEBUG] Raw chunk: {chunk}")

                    if not (chunk.choices and len(chunk.choices) > 0):
                        continue

                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason
                    logger.debug(f"[DEBUG] Delta: {delta}")

                    # Accumulate tool call deltas
                    if delta and hasattr(delta, "tool_calls") and delta.tool_calls:
                        res.has_tool_calls = True
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in res.tool_calls_acc:
                                res.tool_calls_acc[idx] = {
                                    "id": getattr(tc_delta, "id", None),
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }
                            if getattr(tc_delta, "id", None):
                                res.tool_calls_acc[idx]["id"] = tc_delta.id
                            if hasattr(tc_delta, "function"):
                                fn = tc_delta.function
                                if getattr(fn, "name", None):
                                    res.tool_calls_acc[idx]["function"]["name"] = (
                                        fn.name
                                    )
                                if getattr(fn, "arguments", None):
                                    res.tool_calls_acc[idx]["function"][
                                        "arguments"
                                    ] += fn.arguments

                    # Handle text content with thinking-block stripping
                    content = ""
                    if hasattr(delta, "content") and delta.content:
                        content = delta.content

                    if content:
                        buffer += content

                        if "<think>" in buffer and not inside_thinking:
                            inside_thinking = True
                            pre_think = buffer.split("<think>")[0]
                            if pre_think.strip():
                                yield Completion(text=pre_think)
                            buffer = buffer[buffer.index("<think>") :]

                        if inside_thinking and "</think>" in buffer:
                            inside_thinking = False
                            thinking_stripped = True
                            post_think = buffer.split("</think>", 1)[1].lstrip()
                            buffer = post_think
                            if buffer:
                                yield Completion(text=buffer)
                                buffer = ""

                        if not inside_thinking and buffer and not thinking_stripped:
                            yield Completion(text=buffer)
                            buffer = ""
                        elif not inside_thinking and buffer and thinking_stripped:
                            yield Completion(text=buffer)
                            buffer = ""

                    # Handle final chunk (flush buffer but don't yield stop yet)
                    if finish_reason:
                        if buffer and not inside_thinking:
                            cleaned = self._strip_thinking_content(buffer)
                            if cleaned:
                                yield Completion(text=cleaned)
                        buffer = ""

            # --- Drain initial stream ---
            async for comp in _drain_stream(stream, result):
                yield comp

            # --- MCP tool call loop ---
            if (
                result.has_tool_calls
                and mcp_proxy
                and eneo_ctx
                and eneo_ctx.get("has_tools")
            ):
                messages = eneo_ctx["messages"]
                litellm_kwargs = eneo_ctx["kwargs"]
                allowed_tools = mcp_proxy.get_allowed_tool_names()

                max_rounds = 10
                tool_round = 0

                while result.has_tool_calls and tool_round < max_rounds:
                    tool_round += 1
                    logger.info(f"[MCP] Tool round {tool_round}")

                    # Reconstruct tool calls from accumulator
                    tool_calls = [
                        result.tool_calls_acc[idx]
                        for idx in sorted(result.tool_calls_acc.keys())
                    ]

                    # Security validation
                    for tc in tool_calls:
                        name = tc["function"]["name"]
                        if name not in allowed_tools:
                            raise OpenAIException(f"Unauthorized MCP tool: {name}")

                    # Build tool metadata for frontend
                    tool_metadata = []
                    for tc in tool_calls:
                        name = tc["function"]["name"]
                        try:
                            args = (
                                json.loads(tc["function"]["arguments"])
                                if tc["function"]["arguments"]
                                else None
                            )
                        except json.JSONDecodeError:
                            args = None
                        info = mcp_proxy.get_tool_info(name)
                        if info:
                            sname, tname = info
                        elif "__" in name:
                            sname, tname = name.split("__", 1)
                        else:
                            sname, tname = "", name
                        tool_metadata.append(
                            ToolCallMetadata(
                                server_name=sname,
                                tool_name=tname,
                                arguments=args,
                                tool_call_id=tc["id"],
                                ui_resource_uri=mcp_proxy.get_tool_ui_resource_uri(
                                    name
                                ),
                                mcp_server_id=mcp_proxy.get_tool_mcp_server_id(name),
                            )
                        )

                    # Approval flow
                    if require_tool_approval and approval_manager:
                        approval_id = str(uuid.uuid4())
                        tool_call_ids = [tc["id"] for tc in tool_calls]
                        approval_manager.request_approval(approval_id, tool_call_ids)

                        yield Completion(
                            response_type=ResponseType.TOOL_APPROVAL_REQUIRED,
                            tool_calls_metadata=tool_metadata,
                            approval_id=approval_id,
                        )

                        decisions = await approval_manager.wait_for_approval(
                            approval_id
                        )
                        approval_map = {d.tool_call_id: d.approved for d in decisions}

                        yield Completion(
                            response_type=ResponseType.TOOL_CALL,
                            tool_calls_metadata=[
                                ToolCallMetadata(
                                    server_name=tm.server_name,
                                    tool_name=tm.tool_name,
                                    arguments=tm.arguments,
                                    tool_call_id=tm.tool_call_id,
                                    approved=approval_map.get(tm.tool_call_id, False),
                                    ui_resource_uri=tm.ui_resource_uri,
                                    mcp_server_id=tm.mcp_server_id,
                                )
                                for tm in tool_metadata
                            ],
                        )

                        approved_tcs = [
                            tc for tc in tool_calls if approval_map.get(tc["id"], False)
                        ]
                        denied_tcs = [
                            tc
                            for tc in tool_calls
                            if not approval_map.get(tc["id"], False)
                        ]
                    else:
                        yield Completion(
                            response_type=ResponseType.TOOL_CALL,
                            tool_calls_metadata=tool_metadata,
                        )
                        approved_tcs = tool_calls
                        denied_tcs = []

                    # Add assistant message with tool calls to conversation
                    messages.append(
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": tc["id"],
                                    "type": "function",
                                    "function": {
                                        "name": tc["function"]["name"],
                                        "arguments": tc["function"]["arguments"],
                                    },
                                }
                                for tc in tool_calls
                            ],
                        }
                    )

                    # Execute approved tools
                    if approved_tcs:
                        proxy_calls = [
                            (
                                tc["function"]["name"],
                                json.loads(tc["function"]["arguments"])
                                if tc["function"]["arguments"]
                                else {},
                            )
                            for tc in approved_tcs
                        ]
                        results = await mcp_proxy.call_tools_parallel(proxy_calls)
                        tool_results_metadata = []
                        for tc, res in zip(approved_tcs, results):
                            text = ""
                            if res.get("content"):
                                for ci in res["content"]:
                                    if ci.get("type") == "text":
                                        text += ci.get("text", "")
                            if res.get("is_error"):
                                text = json.dumps(
                                    {"error": text or "Tool execution failed"}
                                )
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tc["id"],
                                    "content": text,
                                }
                            )
                            # Track result for frontend
                            name = tc["function"]["name"]
                            info = mcp_proxy.get_tool_info(name)
                            if info:
                                sname, tname = info
                            elif "__" in name:
                                sname, tname = name.split("__", 1)
                            else:
                                sname, tname = "", name
                            tool_results_metadata.append(
                                ToolCallMetadata(
                                    server_name=sname,
                                    tool_name=tname,
                                    tool_call_id=tc["id"],
                                    result=text,
                                    result_meta=res.get("_meta"),
                                    ui_resource_uri=mcp_proxy.get_tool_ui_resource_uri(name),
                                    mcp_server_id=mcp_proxy.get_tool_mcp_server_id(name),
                                )
                            )

                        # Send tool results to frontend (merges by tool_call_id)
                        if tool_results_metadata:
                            yield Completion(
                                response_type=ResponseType.TOOL_CALL,
                                tool_calls_metadata=tool_results_metadata,
                            )

                    # Add denied tool results
                    for tc in denied_tcs:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": "Tool execution was denied by user.",
                            }
                        )

                    # Follow-up streaming request (keep tools for next round)
                    follow_up = await litellm.acompletion(
                        model=self.litellm_model,
                        messages=messages,
                        stream=True,
                        drop_params=True,
                        **litellm_kwargs,
                    )

                    # Drain follow-up stream
                    async for comp in _drain_stream(follow_up, result):
                        yield comp

                if tool_round >= max_rounds:
                    logger.warning(f"[MCP] Reached max tool rounds ({max_rounds})")

            # Final stop
            yield Completion(text="", stop=True)

            logger.info(
                f"[TenantModelAdapter] {self.litellm_model}: Stream iteration completed"
            )

        except Exception as exc:
            # Mid-stream errors: yield error event instead of raising
            logger.error(
                f"[TenantModelAdapter] {self.litellm_model}: Error during stream iteration: {exc}",
                exc_info=True,
            )
            yield Completion(
                text="",
                error=f"Stream error: {str(exc)}",
                error_code=500,
                response_type=ResponseType.ERROR,
                stop=True,
            )

    def get_token_limit_of_model(self) -> int:
        """
        Get token limit for tenant model (with reserved space for completion).

        Returns:
            int: Maximum tokens available for input context
        """
        return self.model.token_limit - TOKENS_RESERVED_FOR_COMPLETION

    def get_logging_details(
        self, context: "Context", model_kwargs: dict
    ) -> LoggingDetails:
        """
        Build logging details for extended logging.

        Args:
            context: Conversation context
            model_kwargs: Model parameters

        Returns:
            LoggingDetails with context, model_kwargs, and json_body
        """
        import json

        messages = self._create_messages_from_context(context)

        # Convert model_kwargs to a plain dict
        if hasattr(model_kwargs, "model_dump"):
            kwargs_dict = model_kwargs.model_dump(exclude_none=True)
        elif hasattr(model_kwargs, "dict"):
            kwargs_dict = model_kwargs.dict(exclude_none=True)
        else:
            kwargs_dict = model_kwargs if isinstance(model_kwargs, dict) else {}

        return LoggingDetails(
            model_kwargs=kwargs_dict,
            json_body=json.dumps(messages),
        )
