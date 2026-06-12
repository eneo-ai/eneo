"""Minimal adapter for tenant models using LiteLLM."""

import json
import re
import socket
import uuid
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Callable,
    Literal,
    NoReturn,
    Optional,
    Protocol,
    TypedDict,
    cast,
)

import aiohttp
import httpx
import litellm
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from typing_extensions import override

from intric.ai_models.completion_models.completion_model import (
    Completion,
    ModelKwargs,
    ResponseType,
    TokenUsage,
    ToolCallMetadata,
)
from intric.completion_models.infrastructure.adapters.base_adapter import (
    CompletionModelAdapter,
)
from intric.completion_models.infrastructure.message_payload import (
    build_content,
    build_turn_messages,
)
from intric.logging.logging import LoggingDetails
from intric.main.exceptions import APIKeyNotConfiguredException, OpenAIException
from intric.main.logging import get_logger
from intric.model_providers.infrastructure.tenant_model_credential_resolver import (
    TenantModelCredentialResolver,
)

logger = get_logger(__name__)

PROVIDER_UNAVAILABLE_MESSAGE = (
    "AI service is temporarily unavailable. Please try again later."
)
PROVIDER_UNAVAILABLE_CODE = "provider_unavailable"
# Some providers wrap DNS/socket failures in generic APIError/RuntimeError types.
# Keep this fallback narrow so transient upstream failures stay distinguishable.
_PROVIDER_UNAVAILABLE_TEXT = (
    "cannot connect",
    "connection refused",
    "connection reset",
    "connection timed out",
    "temporary failure in name resolution",
    "name or service not known",
    "service unavailable",
    "timed out",
)
_PROVIDER_UNAVAILABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    APIConnectionError,
    Timeout,
    ServiceUnavailableError,
    InternalServerError,
    httpx.ConnectError,
    httpx.TimeoutException,
    aiohttp.ClientError,
    socket.gaierror,
    ConnectionError,
    TimeoutError,
)


# Regex to match Qwen3 thinking blocks: <think>...</think>
THINKING_BLOCK_PATTERN = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


class _LiteLLMUsageDetails(Protocol):
    reasoning_tokens: int | None


class _LiteLLMUsage(Protocol):
    prompt_tokens: int | None
    completion_tokens: int | None
    completion_tokens_details: _LiteLLMUsageDetails | None


class _LiteLLMFunction(Protocol):
    name: str
    arguments: str


class _LiteLLMToolCall(Protocol):
    id: str
    function: _LiteLLMFunction


class _LiteLLMMessage(Protocol):
    content: str | None
    reasoning_content: str | None
    tool_calls: list[_LiteLLMToolCall] | None


class _LiteLLMChoice(Protocol):
    message: _LiteLLMMessage
    finish_reason: str | None


class _LiteLLMStreamFunction(Protocol):
    name: str | None
    arguments: str | None


class _LiteLLMStreamToolCall(Protocol):
    index: int
    id: str | None
    function: _LiteLLMStreamFunction | None


class _LiteLLMDelta(Protocol):
    content: str | None
    reasoning_content: str | None
    tool_calls: list[_LiteLLMStreamToolCall] | None


class _LiteLLMStreamChoice(Protocol):
    delta: _LiteLLMDelta
    finish_reason: str | None


class _LiteLLMResponse(Protocol):
    usage: _LiteLLMUsage | None
    choices: list[_LiteLLMChoice]


class _LiteLLMStreamChunk(Protocol):
    usage: _LiteLLMUsage | None
    choices: list[_LiteLLMStreamChoice]


class _LiteLLMHasUsage(Protocol):
    usage: _LiteLLMUsage | None


class _AccumulatedToolFunction(TypedDict):
    name: str
    arguments: str


class _AccumulatedToolCall(TypedDict):
    id: str | None
    type: Literal["function"]
    function: _AccumulatedToolFunction


def _get_supported_openai_params(model: str) -> list[str] | None:
    return cast(
        list[str] | None, getattr(litellm, "get_supported_openai_params")(model=model)
    )


def _acompletion_call(**kwargs: Any) -> Any:
    return cast(Callable[..., Any], getattr(litellm, "acompletion"))(**kwargs)


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return chain


def _is_provider_unavailable_error(exc: BaseException) -> bool:
    for chained in _exception_chain(exc):
        if isinstance(chained, _PROVIDER_UNAVAILABLE_EXCEPTIONS):
            return True
        error_text = str(chained).lower()
        if any(marker in error_text for marker in _PROVIDER_UNAVAILABLE_TEXT):
            return True
    return False


def _tool_metadata_arguments(tool: ToolCallMetadata) -> dict[str, Any] | None:
    return cast(dict[str, Any] | None, cast(Any, tool).arguments)


if TYPE_CHECKING:
    from intric.ai_models.completion_models.completion_model import (
        CompletionModel,
        Context,
    )
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

    def _record_provider_unavailable(self, *, phase: str, exc: BaseException) -> None:
        span = trace.get_current_span()
        if span.is_recording():
            is_streaming = phase in {"stream_preparation", "stream_iteration"}
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.provider.name", self.provider_type)
            span.set_attribute("gen_ai.request.model", self.model.name)
            span.set_attribute("gen_ai.request.stream", is_streaming)
            span.set_attribute("error.type", PROVIDER_UNAVAILABLE_CODE)
            span.set_attribute("eneo.ai.provider_unavailable", True)
            span.set_attribute("eneo.ai.provider_type", self.provider_type)
            span.set_attribute("eneo.ai.model", self.litellm_model)
            span.set_attribute("eneo.ai.operation", phase)
            span.set_attribute("eneo.ai.error_type", exc.__class__.__name__)
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, PROVIDER_UNAVAILABLE_MESSAGE))

        logger.exception(
            f"[TenantModelAdapter] Provider unavailable for {self.litellm_model} during {phase}",
            extra={
                "provider_type": self.provider_type,
                "model": self.litellm_model,
                "operation": phase,
                "error_type": exc.__class__.__name__,
                "error_code": PROVIDER_UNAVAILABLE_CODE,
            },
        )

    def _raise_provider_unavailable(
        self, *, phase: str, exc: BaseException
    ) -> NoReturn:
        self._record_provider_unavailable(phase=phase, exc=exc)
        raise OpenAIException(
            PROVIDER_UNAVAILABLE_MESSAGE,
            code=PROVIDER_UNAVAILABLE_CODE,
            details={"reason": PROVIDER_UNAVAILABLE_CODE, "retryable": True},
        ) from exc

    def _mask_sensitive_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return copy of params with masked API key for safe logging."""
        safe_params = params.copy()
        if "api_key" in safe_params:
            key = safe_params["api_key"]
            safe_params["api_key"] = f"...{key[-4:]}" if len(key) > 4 else "***"
        return safe_params

    def _get_dropped_params(self, litellm_kwargs: dict[str, Any]) -> set[str]:
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
            supported = _get_supported_openai_params(self.litellm_model)
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

    def _get_effective_params(
        self, litellm_kwargs: dict[str, Any], dropped: set[str]
    ) -> dict[str, Any]:
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

    def _extract_usage(self, response: _LiteLLMHasUsage) -> TokenUsage | None:
        """Extract token usage from a LiteLLM response."""
        usage = getattr(response, "usage", None)
        if not usage:
            return None

        reasoning_tokens = None
        # Check for reasoning tokens in completion_tokens_details (OpenAI/Anthropic)
        details = getattr(usage, "completion_tokens_details", None)
        if details:
            reasoning_tokens = getattr(details, "reasoning_tokens", None)

        return TokenUsage(
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            reasoning_tokens=reasoning_tokens,
        )

    def _accumulate_usage(
        self, existing: TokenUsage | None, response: _LiteLLMHasUsage
    ) -> TokenUsage:
        """Accumulate token usage from a follow-up LiteLLM response."""
        new = self._extract_usage(response)
        if not existing:
            return new or TokenUsage()
        if not new:
            return existing

        def _add(a: int | None, b: int | None) -> int | None:
            if a is None and b is None:
                return None
            return (a or 0) + (b or 0)

        return TokenUsage(
            prompt_tokens=_add(existing.prompt_tokens, new.prompt_tokens),
            completion_tokens=_add(existing.completion_tokens, new.completion_tokens),
            reasoning_tokens=_add(existing.reasoning_tokens, new.reasoning_tokens),
        )

    def _build_tools_from_context(self, context: "Context") -> list[dict[str, Any]]:
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
        tools: list[dict[str, Any]] = []
        for func_def in context.function_definitions:
            func_def_any = cast(Any, func_def)
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": func_def_any.name,
                        "description": func_def_any.description,
                        "parameters": cast(dict[str, Any], func_def_any.schema),
                        "strict": True,
                    },
                }
            )
        return tools

    def _merge_mcp_tools(
        self,
        intric_tools: list[dict[str, Any]],
        mcp_proxy: "MCPProxySession | None",
    ) -> list[dict[str, Any]]:
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

    def _create_messages_from_context(self, context: "Context") -> list[dict[str, Any]]:
        """
        Convert Intric context to OpenAI message format with vision support.

        Args:
            context: Intric context with messages in question/answer format

        Returns:
            list: Messages in OpenAI format with role/content (including images)
        """
        messages: list[dict[str, Any]] = []

        # Add system message if prompt exists
        if context.prompt:
            messages.append({"role": "system", "content": context.prompt})

        # Convert previous Q&A pairs to canonical replay messages (with images
        # and tool calls) — the same shape token counting uses.
        for msg in context.messages:
            messages.extend(
                build_turn_messages(
                    question=msg.question,
                    answer=msg.answer,
                    images=msg.images + msg.generated_images,
                    tool_calls=msg.tool_calls,
                )
            )

        # Add current question with images
        messages.append(
            {
                "role": "user",
                "content": build_content(context.input, context.images),
            }
        )

        return messages

    def _prepare_kwargs(
        self,
        model_kwargs: ModelKwargs | dict[str, Any] | None = None,
        **additional_kwargs: Any,
    ) -> dict[str, Any]:
        """
        Prepare kwargs for LiteLLM call with credentials and provider-specific handling.

        Args:
            model_kwargs: Model parameters (temperature, etc.)
            **additional_kwargs: Additional parameters to pass to LiteLLM

        Returns:
            dict: LiteLLM kwargs with api_key, api_base, and config fields
        """
        kwargs: dict[str, Any] = {}

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
            # Convert Pydantic ModelKwargs to dict if needed.
            if isinstance(model_kwargs, dict):
                model_kwargs_dict: dict[str, Any] = model_kwargs
            else:
                model_kwargs_dict = model_kwargs.model_dump(exclude_none=True)

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
                supported_params = (
                    _get_supported_openai_params(self.litellm_model) or []
                )
                if "reasoning_effort" not in supported_params or model_kwargs_dict[
                    "reasoning_effort"
                ] in (None, "none", ""):
                    del model_kwargs_dict["reasoning_effort"]

            # Ensure max_tokens is set - some APIs (e.g., vLLM, OpenAI-compatible)
            # require it explicitly or return empty responses
            if (
                "max_tokens" not in model_kwargs_dict
                and "max_completion_tokens" not in model_kwargs_dict
            ):
                model_kwargs_dict["max_tokens"] = self.model.max_output_tokens
                logger.debug(f"Added default max_tokens={self.model.max_output_tokens}")

            kwargs.update(model_kwargs_dict)

        # Remove non-serializable params that must not reach litellm
        for key in ("mcp_proxy", "require_tool_approval", "approval_manager"):
            additional_kwargs.pop(key, None)

        # Merge with additional kwargs
        kwargs.update(additional_kwargs)

        return kwargs

    @override
    async def get_response(
        self,
        context: "Context",
        model_kwargs: ModelKwargs | dict[str, Any] | None,
        mcp_proxy: "MCPProxySession | None" = None,
        **kwargs: Any,
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
            response = cast(
                _LiteLLMResponse,
                await _acompletion_call(
                    model=self.litellm_model,
                    messages=messages,
                    stream=False,
                    drop_params=True,
                    **litellm_kwargs,
                ),
            )

            # Extract token usage from provider response
            usage = self._extract_usage(response)

            # Parse response
            completion = Completion()
            if response.choices:
                choice = response.choices[0]
                msg = choice.message

                # DEBUG: Log message details
                logger.debug(f"[DEBUG] Message: {msg}")
                reasoning = getattr(msg, "reasoning_content", None)
                if reasoning:
                    logger.debug(f"[DEBUG] reasoning_content: {reasoning}")

                # Check if model wants to call MCP tools
                if msg.tool_calls and mcp_proxy:
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
                    proxy_calls: list[tuple[str, dict[str, Any]]] = []
                    for tc in msg.tool_calls:
                        arguments = (
                            cast(dict[str, Any], json.loads(tc.function.arguments))
                            if tc.function.arguments
                            else {}
                        )
                        proxy_calls.append((tc.function.name, arguments))
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
                    response = cast(
                        _LiteLLMResponse,
                        await _acompletion_call(
                            model=self.litellm_model,
                            messages=messages,
                            stream=False,
                            drop_params=True,
                            **follow_up_kwargs,
                        ),
                    )
                    usage = self._accumulate_usage(usage, response)
                    msg = response.choices[0].message

                if msg.content:
                    completion.text = self._strip_thinking_content(msg.content)
                completion.stop = choice.finish_reason == "stop"

            completion.usage = usage
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

        except (
            APIConnectionError,
            Timeout,
            ServiceUnavailableError,
            InternalServerError,
        ) as exc:
            self._raise_provider_unavailable(phase="completion", exc=exc)

        except APIError as exc:
            if _is_provider_unavailable_error(exc):
                self._raise_provider_unavailable(phase="completion", exc=exc)

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
            if _is_provider_unavailable_error(exc):
                self._raise_provider_unavailable(phase="completion", exc=exc)

            logger.exception(
                f"[TenantModelAdapter] Unexpected error for {self.litellm_model}"
            )
            raise OpenAIException("Unknown error occurred") from exc

    @override
    async def prepare_streaming(
        self,
        context: "Context",
        model_kwargs: ModelKwargs | dict[str, Any] | None = None,
        mcp_proxy: "MCPProxySession | None" = None,
        **kwargs: Any,
    ) -> AsyncIterator[_LiteLLMStreamChunk]:
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
            # Create stream with drop_params=True to handle unsupported params gracefully
            # Request usage info on the final chunk (providers that don't support it
            # will silently ignore this thanks to drop_params=True)
            stream = cast(
                AsyncIterator[_LiteLLMStreamChunk],
                await _acompletion_call(
                    model=self.litellm_model,
                    messages=messages,
                    stream=True,
                    drop_params=True,
                    stream_options={"include_usage": True},
                    **litellm_kwargs,
                ),
            )

            # Store context for MCP tool execution in iterate_stream
            stream_with_ctx = cast(Any, stream)
            setattr(
                stream_with_ctx,
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

        except (
            APIConnectionError,
            Timeout,
            ServiceUnavailableError,
            InternalServerError,
        ) as exc:
            self._raise_provider_unavailable(phase="stream_preparation", exc=exc)

        except APIError as exc:
            if _is_provider_unavailable_error(exc):
                self._raise_provider_unavailable(phase="stream_preparation", exc=exc)

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
            if _is_provider_unavailable_error(exc):
                self._raise_provider_unavailable(phase="stream_preparation", exc=exc)

            logger.exception(
                f"[TenantModelAdapter] Unexpected error creating stream for {self.litellm_model}"
            )
            raise OpenAIException("Unknown error occurred") from exc

    @override
    async def iterate_stream(
        self,
        stream: AsyncIterator[_LiteLLMStreamChunk],
        context: Optional["Context"] = None,
        model_kwargs: ModelKwargs | dict[str, Any] | None = None,
        require_tool_approval: bool = False,
        approval_manager: "ToolApprovalManager | None" = None,
        approval_context: dict[str, Any] | None = None,
        pending_approval_ids: set[str] | None = None,
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
            approval_context: Context map with tenant_id, user_id, session_id, assistant_id
            pending_approval_ids: Mutable set to track approvals for disconnect cleanup

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
            mcp_tools_active = bool(
                mcp_proxy and eneo_ctx and eneo_ctx.get("has_tools")
            )
            pending_allowed_tools: set[str] = (
                mcp_proxy.get_allowed_tool_names()
                if mcp_proxy is not None and mcp_tools_active
                else set()
            )

            def _resolve_tool_names(name: str) -> tuple[str, str]:
                info = mcp_proxy.get_tool_info(name) if mcp_proxy else None
                if info:
                    return info
                if "__" in name:
                    server_name, tool_name = name.split("__", 1)
                    return server_name, tool_name
                return "", name

            # Shared state for tool call accumulation and usage across stream draining
            class _StreamResult:
                def __init__(self) -> None:
                    super().__init__()
                    self.has_tool_calls: bool = False
                    self.tool_calls_acc: dict[int, _AccumulatedToolCall] = {}
                    self.usage: TokenUsage | None = None

            result = _StreamResult()

            async def _drain_stream(
                s: AsyncIterator[_LiteLLMStreamChunk], res: _StreamResult
            ) -> AsyncIterator[Completion]:
                """Drain a stream: yield text Completions, accumulate tool calls into res."""
                buffer = ""
                inside_thinking = False
                thinking_stripped = False
                pending_emitted: set[int] = set()
                res.has_tool_calls = False
                res.tool_calls_acc = {}

                async for chunk in s:
                    logger.debug(f"[DEBUG] Raw chunk: {chunk}")

                    # Capture usage from final chunk (when stream_options include_usage is set)
                    chunk_usage_obj = getattr(chunk, "usage", None)
                    if chunk_usage_obj:
                        chunk_usage = self._extract_usage(chunk)
                        if chunk_usage:
                            res.usage = (
                                self._accumulate_usage(res.usage, chunk)
                                if res.usage
                                else chunk_usage
                            )

                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason
                    logger.debug(f"[DEBUG] Delta: {delta}")

                    # Forward provider reasoning/thinking deltas (e.g. Anthropic
                    # extended thinking surfaced by LiteLLM as reasoning_content)
                    # as REASONING chunks. Kept separate from text so it never
                    # pollutes the persisted answer.
                    reasoning_delta = getattr(delta, "reasoning_content", None)
                    if reasoning_delta:
                        yield Completion(
                            reasoning_content=reasoning_delta,
                            response_type=ResponseType.REASONING,
                        )

                    # Accumulate tool call deltas
                    if delta.tool_calls:
                        res.has_tool_calls = True
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in res.tool_calls_acc:
                                res.tool_calls_acc[idx] = {
                                    "id": tc_delta.id,
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }
                            if tc_delta.id:
                                res.tool_calls_acc[idx]["id"] = tc_delta.id
                            if tc_delta.function:
                                fn = tc_delta.function
                                if fn.name:
                                    res.tool_calls_acc[idx]["function"]["name"] = (
                                        fn.name
                                    )
                                if fn.arguments:
                                    res.tool_calls_acc[idx]["function"][
                                        "arguments"
                                    ] += fn.arguments

                        # Surface each call as a "pending" step as soon as its
                        # name and id are known — argument JSON for many parallel
                        # calls can take tens of seconds to generate, and the
                        # stream is otherwise silent for that whole window.
                        if mcp_tools_active:
                            for idx, acc in res.tool_calls_acc.items():
                                if idx in pending_emitted:
                                    continue
                                call_id = acc["id"]
                                name = acc["function"]["name"]
                                if (
                                    not call_id
                                    or not name
                                    or name not in pending_allowed_tools
                                ):
                                    continue
                                server_name, tool_name = _resolve_tool_names(name)
                                pending_emitted.add(idx)
                                yield Completion(
                                    response_type=ResponseType.TOOL_CALL,
                                    tool_calls_metadata=[
                                        ToolCallMetadata(
                                            server_name=server_name,
                                            tool_name=tool_name,
                                            arguments=None,
                                            tool_call_id=call_id,
                                            result_status="pending",
                                            mcp_tool_name=name,
                                        )
                                    ],
                                )

                    # Handle text content with thinking-block stripping
                    content = delta.content or ""

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
                    tool_calls: list[_AccumulatedToolCall] = [
                        result.tool_calls_acc[idx]
                        for idx in sorted(result.tool_calls_acc.keys())
                    ]

                    # Security validation
                    for tc in tool_calls:
                        name = tc["function"]["name"]
                        if name not in allowed_tools:
                            raise OpenAIException(f"Unauthorized MCP tool: {name}")

                    # Build tool metadata for frontend
                    tool_metadata: list[ToolCallMetadata] = []
                    for tc in tool_calls:
                        name = tc["function"]["name"]
                        try:
                            args = (
                                cast(
                                    dict[str, Any],
                                    json.loads(tc["function"]["arguments"]),
                                )
                                if tc["function"]["arguments"]
                                else None
                            )
                        except json.JSONDecodeError:
                            args = None
                        sname, tname = _resolve_tool_names(name)
                        tool_metadata.append(
                            ToolCallMetadata(
                                server_name=sname,
                                tool_name=tname,
                                arguments=args,
                                tool_call_id=tc["id"],
                                mcp_tool_name=name,
                            )
                        )
                    tool_args_by_call_id: dict[str, dict[str, Any] | None] = {}
                    for tm in tool_metadata:
                        if tm.tool_call_id is not None:
                            tool_args_by_call_id[tm.tool_call_id] = (
                                _tool_metadata_arguments(tm)
                            )

                    # Approval flow
                    decision_map: dict[str, tuple[bool, str | None]] = {}
                    timed_out = False
                    if require_tool_approval and approval_manager:
                        if approval_context is None:
                            raise OpenAIException(
                                "Missing approval context for tool approval flow"
                            )

                        approval_id = str(uuid.uuid4())
                        tool_call_ids = [tc["id"] for tc in tool_calls if tc["id"]]
                        if pending_approval_ids is not None:
                            pending_approval_ids.add(approval_id)

                        await approval_manager.request_approval(
                            approval_id=approval_id,
                            tool_call_ids=tool_call_ids,
                            tenant_id=approval_context["tenant_id"],
                            user_id=approval_context["user_id"],
                            session_id=approval_context["session_id"],
                            assistant_id=approval_context.get("assistant_id"),
                        )

                        yield Completion(
                            response_type=ResponseType.TOOL_APPROVAL_REQUIRED,
                            tool_calls_metadata=tool_metadata,
                            approval_id=approval_id,
                        )

                        wait_result = await approval_manager.wait_for_approval(
                            approval_id
                        )
                        if pending_approval_ids is not None:
                            pending_approval_ids.discard(approval_id)
                        timed_out = wait_result.timed_out
                        decision_map = {
                            d.tool_call_id: (d.approved, d.reason)
                            for d in wait_result.decisions
                        }

                        if timed_out:
                            yield Completion(
                                response_type=ResponseType.TOOL_APPROVAL_TIMEOUT,
                                approval_id=approval_id,
                                tool_calls_metadata=[
                                    ToolCallMetadata(
                                        server_name=tm.server_name,
                                        tool_name=tm.tool_name,
                                        arguments=_tool_metadata_arguments(tm),
                                        tool_call_id=tm.tool_call_id,
                                        approved=False,
                                        result_status="timeout_denied",
                                        mcp_tool_name=tm.mcp_tool_name,
                                    )
                                    for tm in tool_metadata
                                ],
                            )

                        yield Completion(
                            response_type=ResponseType.TOOL_CALL,
                            tool_calls_metadata=[
                                ToolCallMetadata(
                                    server_name=tm.server_name,
                                    tool_name=tm.tool_name,
                                    arguments=_tool_metadata_arguments(tm),
                                    tool_call_id=tm.tool_call_id,
                                    approved=decision_map.get(
                                        tm.tool_call_id or "", (False, None)
                                    )[0],
                                    result_status=(
                                        "approved"
                                        if decision_map.get(
                                            tm.tool_call_id or "", (False, None)
                                        )[0]
                                        else (
                                            "timeout_denied" if timed_out else "denied"
                                        )
                                    ),
                                    mcp_tool_name=tm.mcp_tool_name,
                                )
                                for tm in tool_metadata
                            ],
                        )

                        approved_tcs: list[_AccumulatedToolCall] = [
                            tc
                            for tc in tool_calls
                            if decision_map.get(tc["id"] or "", (False, None))[0]
                        ]
                        denied_tcs: list[_AccumulatedToolCall] = [
                            tc
                            for tc in tool_calls
                            if not decision_map.get(tc["id"] or "", (False, None))[0]
                        ]
                    else:
                        yield Completion(
                            response_type=ResponseType.TOOL_CALL,
                            tool_calls_metadata=[
                                ToolCallMetadata(
                                    server_name=tm.server_name,
                                    tool_name=tm.tool_name,
                                    arguments=_tool_metadata_arguments(tm),
                                    tool_call_id=tm.tool_call_id,
                                    approved=tm.approved,
                                    result_status="approved",
                                    mcp_tool_name=tm.mcp_tool_name,
                                )
                                for tm in tool_metadata
                            ],
                        )
                        approved_tcs = tool_calls
                        denied_tcs: list[_AccumulatedToolCall] = []

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
                        proxy_calls: list[tuple[str, dict[str, Any]]] = [
                            (
                                tc["function"]["name"],
                                cast(
                                    dict[str, Any],
                                    json.loads(tc["function"]["arguments"]),
                                )
                                if tc["function"]["arguments"]
                                else {},
                            )
                            for tc in approved_tcs
                        ]
                        results = cast(
                            list[dict[str, Any]],
                            await mcp_proxy.call_tools_parallel(proxy_calls),
                        )
                        execution_metadata: list[ToolCallMetadata] = []
                        for tc, res in zip(approved_tcs, results):
                            result_data = res
                            text = ""
                            if result_data.get("content"):
                                for ci in result_data["content"]:
                                    if ci.get("type") == "text":
                                        text += ci.get("text", "")
                            result_status = "succeeded"
                            if result_data.get("is_error"):
                                text = json.dumps(
                                    {"error": text or "Tool execution failed"}
                                )
                                result_status = "failed"
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tc["id"],
                                    "content": text,
                                }
                            )
                            server_name, tool_name = _resolve_tool_names(
                                tc["function"]["name"]
                            )
                            execution_metadata.append(
                                ToolCallMetadata(
                                    server_name=server_name,
                                    tool_name=tool_name,
                                    arguments=tool_args_by_call_id.get(tc["id"] or ""),
                                    tool_call_id=tc["id"],
                                    approved=True,
                                    result_status=result_status,
                                    result=text,
                                    mcp_tool_name=tc["function"]["name"],
                                )
                            )

                        if execution_metadata:
                            yield Completion(
                                response_type=ResponseType.TOOL_CALL,
                                tool_calls_metadata=execution_metadata,
                            )

                    # Add denied tool results
                    denied_metadata: list[ToolCallMetadata] = []
                    for tc in denied_tcs:
                        denial_reason = decision_map.get(tc["id"] or "", (False, None))[
                            1
                        ]
                        denial_payload: dict[str, Any] = {"denied": True}
                        if denial_reason:
                            denial_payload["user_reason"] = denial_reason
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": json.dumps(denial_payload),
                            }
                        )
                        server_name, tool_name = _resolve_tool_names(
                            tc["function"]["name"]
                        )
                        denied_metadata.append(
                            ToolCallMetadata(
                                server_name=server_name,
                                tool_name=tool_name,
                                arguments=tool_args_by_call_id.get(tc["id"] or ""),
                                tool_call_id=tc["id"],
                                approved=False,
                                result_status=(
                                    "timeout_denied" if timed_out else "denied"
                                ),
                                result=json.dumps(denial_payload),
                                mcp_tool_name=tc["function"]["name"],
                            )
                        )

                    if denied_metadata:
                        yield Completion(
                            response_type=ResponseType.TOOL_CALL,
                            tool_calls_metadata=denied_metadata,
                        )

                    # Follow-up streaming request (keep tools for next round)
                    follow_up = cast(
                        AsyncIterator[_LiteLLMStreamChunk],
                        await _acompletion_call(
                            model=self.litellm_model,
                            messages=messages,
                            stream=True,
                            drop_params=True,
                            stream_options={"include_usage": True},
                            **litellm_kwargs,
                        ),
                    )

                    # Drain follow-up stream
                    async for comp in _drain_stream(follow_up, result):
                        yield comp

                if tool_round >= max_rounds:
                    logger.warning(f"[MCP] Reached max tool rounds ({max_rounds})")

            # Final stop — attach accumulated usage
            yield Completion(text="", stop=True, usage=result.usage)

            logger.info(
                f"[TenantModelAdapter] {self.litellm_model}: Stream iteration completed"
            )

        except Exception as exc:
            # Mid-stream errors: yield error event instead of raising
            if _is_provider_unavailable_error(exc):
                self._record_provider_unavailable(phase="stream_iteration", exc=exc)
                # Streaming Completion events expose numeric error_code, not JSON details.
                error = PROVIDER_UNAVAILABLE_MESSAGE
                error_code = 503
            else:
                logger.error(
                    f"[TenantModelAdapter] {self.litellm_model}: Error during stream iteration: {exc}",
                    exc_info=True,
                )
                error = f"Stream error: {str(exc)}"
                error_code = 500

            yield Completion(
                text="",
                error=error,
                error_code=error_code,
                response_type=ResponseType.ERROR,
                stop=True,
            )

    @override
    def get_litellm_model_name(self) -> str:
        return self.litellm_model

    @override
    def get_token_limit_of_model(self) -> int:
        """
        Get token limit for tenant model.

        Returns max_input_tokens directly, as admins configure this value
        to represent the actual input budget at model setup time.

        Returns:
            int: Maximum tokens available for input context
        """
        return self.model.max_input_tokens

    @override
    def get_logging_details(
        self,
        context: "Context",
        model_kwargs: ModelKwargs | dict[str, Any] | None,
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
        if isinstance(model_kwargs, dict):
            kwargs_dict = model_kwargs
        else:
            kwargs_dict = (
                model_kwargs.model_dump(exclude_none=True)
                if model_kwargs is not None
                else {}
            )

        return LoggingDetails(
            model_kwargs=kwargs_dict,
            json_body=json.dumps(messages),
        )
