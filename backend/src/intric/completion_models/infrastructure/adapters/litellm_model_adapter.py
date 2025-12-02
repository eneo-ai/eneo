import json
import re
from typing import TYPE_CHECKING, AsyncGenerator, Optional

import litellm
from litellm import AuthenticationError, APIError, RateLimitError

from intric.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModel,
    Context,
    ModelKwargs,
    ResponseType,
    ToolCallMetadata,
)
from intric.completion_models.infrastructure.adapters.base_adapter import (
    CompletionModelAdapter,
)
from intric.ai_models.litellm_providers.provider_registry import LiteLLMProviderRegistry
from intric.logging.logging import LoggingDetails
from intric.main.config import get_settings
from intric.main.exceptions import APIKeyNotConfiguredException, OpenAIException
from intric.main.logging import get_logger
from intric.settings.credential_resolver import CredentialResolver

if TYPE_CHECKING:
    from intric.mcp_servers.infrastructure.proxy import MCPProxySession

logger = get_logger(__name__)

TOKENS_RESERVED_FOR_COMPLETION = 1000


class SecurityError(Exception):
    """Raised when a security violation is detected."""
    pass


class MCPToolExecutionGuard:
    """Security boundary for MCP tool execution.

    This class provides explicit validation that tool calls are authorized
    before execution, acting as a defense-in-depth measure alongside
    database-level filtering.
    """

    def __init__(self, allowed_tool_map: dict[str, tuple]):
        """Initialize the guard with allowed tools.

        Args:
            allowed_tool_map: Dictionary mapping tool names to (MCPServer, original_tool_name) tuples
        """
        self.allowed_tool_map = allowed_tool_map
        self.allowed_tools = set(allowed_tool_map.keys())

    def validate_and_route(self, tool_name: str) -> tuple:
        """Validates tool is allowed and returns routing information.

        Args:
            tool_name: The tool name to validate

        Returns:
            Tuple of (MCPServer, original_tool_name) for routing

        Raises:
            SecurityError: If tool is not in the allowed list
        """
        if tool_name not in self.allowed_tools:
            logger.warning(
                f"[SECURITY] Blocked unauthorized tool call attempt: {tool_name}",
                extra={
                    "tool_name": tool_name,
                    "allowed_tools": list(self.allowed_tools),
                    "alert_type": "unauthorized_tool_access"
                }
            )
            raise SecurityError(
                f"Tool '{tool_name}' is not in the allowed tool list. "
                f"Please contact your administrator to enable this tool."
            )

        return self.allowed_tool_map[tool_name]


class LiteLLMModelAdapter(CompletionModelAdapter):
    def _mask_sensitive_kwargs(self, kwargs: dict) -> dict:
        """Return copy of kwargs with masked API key for safe logging."""
        safe_kwargs = kwargs.copy()
        if "api_key" in safe_kwargs:
            key = safe_kwargs["api_key"]
            safe_kwargs["api_key"] = f"...{key[-4:]}" if len(key) > 4 else "***"
        return safe_kwargs

    def __init__(
        self,
        model: CompletionModel,
        credential_resolver: Optional[CredentialResolver] = None,
    ):
        super().__init__(model)
        self.credential_resolver = credential_resolver

        # Get provider configuration based on litellm_model_name
        provider_registry = LiteLLMProviderRegistry.get_provider_for_model(
            model.litellm_model_name
        )

        # Only apply custom configuration if needed
        if provider_registry.needs_custom_config():
            self.litellm_model = provider_registry.get_litellm_model(model.litellm_model_name)
            self.api_config = provider_registry.get_api_config()
            logger.info(
                f"[LiteLLM] Using custom provider config for {model.name}: {list(self.api_config.keys())}"
            )
        else:
            # Standard LiteLLM behavior for supported providers
            self.litellm_model = model.litellm_model_name
            self.api_config = {}

        # Validate credentials early if credential_resolver is provided
        # This ensures errors are raised before streaming starts
        if credential_resolver is not None:
            provider = self._detect_provider(self.litellm_model)
            try:
                # Pre-validate that credential exists
                # Don't store it yet - will get it per-request for security
                _ = credential_resolver.get_api_key(provider)
                logger.info(
                    f"[LiteLLM] Validated credential for provider {provider}",
                    extra={
                        "model": model.name,
                        "provider": provider,
                    },
                )
            except ValueError as e:
                logger.error(
                    "[LiteLLM] Credential validation failed during initialization",
                    extra={
                        "model": model.name,
                        "provider": provider,
                        "error": str(e),
                    },
                )
                raise APIKeyNotConfiguredException(str(e))

        logger.info(
            f"[LiteLLM] Initializing adapter for model: {model.name} -> {self.litellm_model}"
        )

    def _detect_provider(self, litellm_model_name: str) -> str:
        """
        Detect provider from model name.

        Args:
            litellm_model_name: The LiteLLM model name (e.g., 'azure/gpt-4', 'anthropic/claude-3')

        Returns:
            Provider name (openai, azure, anthropic, berget, mistral, ovhcloud, vllm)
        """
        if litellm_model_name.startswith("azure/"):
            return "azure"
        elif litellm_model_name.startswith("anthropic/"):
            return "anthropic"
        elif litellm_model_name.startswith("berget/"):
            return "berget"
        elif litellm_model_name.startswith("mistral/"):
            return "mistral"
        elif litellm_model_name.startswith("ovhcloud/"):
            return "ovhcloud"
        elif litellm_model_name.startswith("vllm/"):
            return "vllm"
        else:
            # Default to OpenAI for unprefixed models
            return "openai"

    def _get_kwargs(self, kwargs: ModelKwargs | None):
        if kwargs is None:
            logger.info(f"[LiteLLM] {self.litellm_model}: No kwargs provided")
            return {}

        # Get all kwargs from the model
        all_kwargs = kwargs.model_dump(exclude_none=True)
        logger.info(
            f"[LiteLLM] {self.litellm_model}: Parameters being sent: {all_kwargs}"
        )

        # Pass all parameters directly to LiteLLM
        # Let the API handle parameter validation
        return all_kwargs

    def get_token_limit_of_model(self):
        return self.model.token_limit - TOKENS_RESERVED_FOR_COMPLETION

    def get_logging_details(self, context: Context, model_kwargs: ModelKwargs):
        query = self.create_query_from_context(context=context)
        processed_kwargs = self._get_kwargs(model_kwargs)

        logger.info(
            f"[LiteLLM] {self.litellm_model}: Logging request with {len(query)} messages and processed kwargs: {self._mask_sensitive_kwargs(processed_kwargs)}"
        )

        return LoggingDetails(
            json_body=json.dumps(query), model_kwargs=processed_kwargs
        )

    def create_query_from_context(self, context: Context):
        messages = []

        # Add system prompt if present
        if context.prompt:
            messages.append({"role": "system", "content": context.prompt})

        # Add conversation history
        for message in context.messages:
            # Add user message
            user_content = []
            user_content.append({"type": "text", "text": message.question})

            # Add images if present
            for image in message.images:
                if hasattr(image, "base64_content") and image.base64_content:
                    user_content.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image.base64_content}"
                            },
                        }
                    )

            messages.append(
                {
                    "role": "user",
                    "content": user_content
                    if len(user_content) > 1
                    else message.question,
                }
            )

            # Add assistant response
            messages.append({"role": "assistant", "content": message.answer})

        # Add current input
        current_content = []
        current_content.append({"type": "text", "text": context.input})

        # Add current images
        for image in context.images:
            if hasattr(image, "base64_content") and image.base64_content:
                current_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image.base64_content}"
                        },
                    }
                )

        messages.append(
            {
                "role": "user",
                "content": current_content
                if len(current_content) > 1
                else context.input,
            }
        )

        return messages

    def _sanitize_tool_name(self, name: str) -> str:
        """
        Sanitize tool/server name to match OpenAI pattern ^[a-zA-Z0-9_-]+$

        Args:
            name: Raw name that may contain invalid characters

        Returns:
            Sanitized name with only alphanumeric, underscore, and hyphen characters
        """
        # Replace invalid characters with underscores
        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
        # Ensure it's not empty
        return sanitized if sanitized else "tool"

    def _strip_server_prefix(self, tool_name: str) -> str:
        """
        Remove server prefix from tool name.

        Args:
            tool_name: Tool name (may be prefixed like 'context7__resolve_library_id')

        Returns:
            Original tool name without prefix ('resolve_library_id')
        """
        if "__" in tool_name:
            parts = tool_name.split("__", 1)
            if len(parts) == 2:
                return parts[1]
        return tool_name

    def _add_server_prefix(self, tool_name: str, server_name: str) -> str:
        """
        Add server prefix to tool name to avoid collisions.

        Args:
            tool_name: Original tool name ('resolve-library-id')
            server_name: MCP server name ('context7')

        Returns:
            Prefixed tool name ('context7__resolve_library_id')
        """
        # Sanitize both names to ensure they match OpenAI pattern
        sanitized_server = self._sanitize_tool_name(server_name)
        sanitized_tool = self._sanitize_tool_name(tool_name)
        # Use double underscore as separator (less likely to conflict than single hyphen)
        return f"{sanitized_server}__{sanitized_tool}"

    async def setup_mcp_tools(self, mcp_servers: list):
        """Setup MCP tools from database (no server connections during setup).

        Args:
            mcp_servers: List of MCPServer domain entities from assistant
                        (already filtered by tenant→space→assistant hierarchy)

        Returns:
            Tuple of (tools, tool_to_server_map, execution_guard) where:
                - tools: List of OpenAI-formatted tool definitions
                - tool_to_server_map: Dict mapping sanitized tool names to (server, original_tool_name) tuples
                - execution_guard: MCPToolExecutionGuard instance for validating tool calls
        """
        tools = []
        tool_to_server_map = {}

        for mcp_server in mcp_servers:
            # Validate required fields
            if not hasattr(mcp_server, 'http_url') or not mcp_server.http_url:
                logger.warning(f"[MCP] Server {mcp_server.name} missing http_url - skipping")
                continue

            # Use DB tools (already filtered and enabled by hierarchy)
            if not hasattr(mcp_server, 'tools') or not mcp_server.tools:
                logger.debug(f"[MCP] Server {mcp_server.name} has no tools configured")
                continue

            enabled_count = 0
            for db_tool in mcp_server.tools:
                # Only include enabled tools
                if not db_tool.is_enabled_by_default:
                    continue

                # Prefix tool name to avoid collisions between servers
                prefixed_name = self._add_server_prefix(db_tool.name, mcp_server.name)

                # Convert DB tool to OpenAI format
                openai_tool = {
                    "type": "function",
                    "function": {
                        "name": prefixed_name,
                        "description": db_tool.description or "",
                        "parameters": db_tool.input_schema or {}
                    }
                }
                tools.append(openai_tool)
                enabled_count += 1

                # Build routing map: store (server, original_tool_name) tuple
                # Map prefixed name to (server, original_tool_name) so we can call the server with the correct name
                tool_to_server_map[prefixed_name] = (mcp_server, db_tool.name)

            logger.info(f"[MCP] Loaded {enabled_count} enabled tools from {mcp_server.name} (from DB)")

        logger.info(f"[MCP] Setup complete: {len(tools)} total tools from {len(mcp_servers)} server(s)")

        # Create execution guard for security validation
        execution_guard = MCPToolExecutionGuard(tool_to_server_map) if tool_to_server_map else None

        return tools, tool_to_server_map, execution_guard

    async def get_response(
        self, context: Context, model_kwargs: ModelKwargs | None = None, mcp_proxy: "MCPProxySession | None" = None
    ):
        messages = self.create_query_from_context(context=context)
        kwargs = self._get_kwargs(model_kwargs)

        # Add provider-specific API configuration
        if self.api_config:
            kwargs.update(self.api_config)
            logger.info(
                f"[LiteLLM] {self.litellm_model}: Adding provider config: {list(self.api_config.keys())}"
            )

        # Inject tenant-specific API key if credential_resolver is provided
        if self.credential_resolver:
            provider = self._detect_provider(self.litellm_model)
            try:
                api_key = self.credential_resolver.get_api_key(provider)
                kwargs["api_key"] = api_key
                logger.info(
                    f"[LiteLLM] {self.litellm_model}: Injecting tenant API key for {provider}"
                )
            except ValueError as e:
                logger.error(
                    f"[LiteLLM] {self.litellm_model}: Credential resolution failed: {e}"
                )
                raise APIKeyNotConfiguredException(str(e))

            # Inject api_base for VLLM and other providers with custom endpoints
            # VLLM requires endpoint - fallback to global VLLM_MODEL_URL for single-tenant deployments
            settings = get_settings()
            endpoint_fallback = settings.vllm_model_url if provider == "vllm" else None
            endpoint = self.credential_resolver.get_credential_field(
                provider=provider,
                field="endpoint",
                fallback=endpoint_fallback,
                required=(provider in {"vllm", "azure"})  # endpoint is required for vLLM and Azure
            )

            if endpoint:
                kwargs["api_base"] = endpoint
                logger.info(
                    f"[LiteLLM] {self.litellm_model}: Injecting endpoint for {provider}: {endpoint}"
                )

        # Get MCP tools from proxy (no server connections during setup - lazy)
        tools = []
        if mcp_proxy:
            tools = mcp_proxy.get_tools_for_llm()
            if tools:
                kwargs['tools'] = tools
                logger.debug(f"[MCP] Added {len(tools)} tools to request")

        logger.info(
            f"[LiteLLM] {self.litellm_model}: Making completion request with {len(messages)} messages and kwargs: {self._mask_sensitive_kwargs(kwargs)}"
        )

        try:
            # Initial completion request
            response = await litellm.acompletion(
                model=self.litellm_model, messages=messages, **kwargs
            )

            logger.info(
                f"[LiteLLM] {self.litellm_model}: Completion successful, response received"
            )

            # Check if model wants to call tools
            message = response.choices[0].message
            if hasattr(message, 'tool_calls') and message.tool_calls and mcp_proxy:
                logger.debug(f"[MCP] LLM requested {len(message.tool_calls)} tool call(s)")

                # Validate all tools are allowed
                allowed_tools = mcp_proxy.get_allowed_tool_names()
                for tc in message.tool_calls:
                    if tc.function.name not in allowed_tools:
                        logger.warning(
                            f"[SECURITY] Blocked unauthorized tool call: {tc.function.name}",
                            extra={"allowed_tools": list(allowed_tools)}
                        )
                        raise SecurityError(f"Tool '{tc.function.name}' is not authorized")

                # Build tool info header
                tool_info = "\n\n🔧 **Executing MCP tools...**\n"
                for i, tc in enumerate(message.tool_calls, 1):
                    tool_display = tc.function.name.replace('__', ': ').replace('_', ' ').title()
                    tool_info += f"{i}. {tool_display}\n"

                # Add assistant message with tool calls to conversation
                messages.append({
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        } for tc in message.tool_calls
                    ]
                })

                # Execute tools via proxy (parallel, lazy connections)
                tool_calls = [
                    (tc.function.name, json.loads(tc.function.arguments) if tc.function.arguments else {})
                    for tc in message.tool_calls
                ]
                results = await mcp_proxy.call_tools_parallel(tool_calls)

                # Add results to messages
                for tc, result in zip(message.tool_calls, results):
                    # Extract text content from result
                    result_text = ""
                    if result.get("content"):
                        for content_item in result["content"]:
                            if content_item.get("type") == "text":
                                result_text += content_item.get("text", "")
                    if result.get("is_error"):
                        result_text = json.dumps({"error": result_text or "Tool execution failed"})

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_text
                    })

                # Make follow-up completion request with tool results
                logger.debug("[MCP] Making follow-up request with tool results")
                follow_up_kwargs = {k: v for k, v in kwargs.items() if k != 'tools'}
                response = await litellm.acompletion(
                    model=self.litellm_model,
                    messages=messages,
                    **follow_up_kwargs
                )
                message = response.choices[0].message
                logger.debug("[MCP] Follow-up response received")

                # Prepend tool info to the response
                content = tool_info + (message.content or "")
            else:
                content = message.content or ""

            return Completion(text=content, stop=True)

        except AuthenticationError as exc:
            # Invalid API credentials
            provider = self._detect_provider(self.litellm_model)
            logger.error(
                "Authentication failed",
                extra={
                    "tenant_id": str(self.credential_resolver.tenant.id) if self.credential_resolver and self.credential_resolver.tenant else None,
                    "tenant_name": self.credential_resolver.tenant.name if self.credential_resolver and self.credential_resolver.tenant else None,
                    "provider": provider,
                    "error_type": "AuthenticationError",
                    "model": self.litellm_model,
                },
            )
            raise APIKeyNotConfiguredException(
                f"Invalid API credentials for provider '{provider}'. "
                f"Please verify your API key configuration."
            ) from exc

        except RateLimitError as exc:
            provider = self._detect_provider(self.litellm_model)
            logger.error(
                "Rate limit error",
                extra={
                    "provider": provider,
                    "model": self.litellm_model,
                },
            )
            raise OpenAIException(
                f"Rate limit exceeded for {provider}. Please try again later."
            ) from exc

        except APIError as exc:
            # API errors including Azure firewall/network issues
            error_message = str(exc)
            provider = self._detect_provider(self.litellm_model)
            logger.error(
                f"API error: {error_message}",
                extra={
                    "tenant_id": str(self.credential_resolver.tenant.id) if self.credential_resolver and self.credential_resolver.tenant else None,
                    "provider": provider,
                    "model": self.litellm_model,
                },
            )

            # Check for Azure firewall/network errors in the error message
            if "Virtual Network/Firewall" in error_message or "Firewall rules" in error_message or "Access denied" in error_message:
                raise OpenAIException(
                    "Azure access denied: Virtual Network/Firewall rules. "
                    "Please check your Azure network configuration or contact your administrator."
                ) from exc
            elif "rate limit" in error_message.lower():
                raise OpenAIException(
                    f"Rate limit exceeded for {provider}. Please try again later."
                ) from exc
            else:
                raise OpenAIException(f"API error: {error_message}") from exc

        except Exception as exc:
            logger.exception(f"[LiteLLM] {self.litellm_model}: Unexpected error")
            raise OpenAIException("Unknown error occurred") from exc

    async def prepare_streaming(self, context: Context, model_kwargs: ModelKwargs | None = None, mcp_proxy: "MCPProxySession | None" = None):
        """
        Phase 1: Create stream connection before EventSourceResponse.
        Can raise exceptions for authentication, firewall, rate limit errors.
        """
        messages = self.create_query_from_context(context=context)
        kwargs = self._get_kwargs(model_kwargs)

        # Add provider-specific API configuration
        if self.api_config:
            kwargs.update(self.api_config)
            logger.info(
                f"[LiteLLM] {self.litellm_model}: Adding provider config for streaming: {list(self.api_config.keys())}"
            )

        # Inject tenant-specific API key - raises APIKeyNotConfiguredException if missing
        if self.credential_resolver:
            provider = self._detect_provider(self.litellm_model)
            try:
                api_key = self.credential_resolver.get_api_key(provider)
                kwargs["api_key"] = api_key
                logger.info(
                    f"[LiteLLM] {self.litellm_model}: Injecting tenant API key for streaming {provider}"
                )
            except ValueError as e:
                logger.error(
                    f"[LiteLLM] {self.litellm_model}: Credential resolution failed for streaming: {e}"
                )
                raise APIKeyNotConfiguredException(str(e))

            # Inject api_base for streaming
            # VLLM requires endpoint - fallback to global VLLM_MODEL_URL for single-tenant deployments
            settings = get_settings()
            endpoint_fallback = settings.vllm_model_url if provider == "vllm" else None
            endpoint = self.credential_resolver.get_credential_field(
                provider=provider,
                field="endpoint",
                fallback=endpoint_fallback,
                required=(provider in {"vllm", "azure"})  # endpoint is required for vLLM and Azure
            )

            if endpoint:
                kwargs["api_base"] = endpoint
                logger.info(
                    f"[LiteLLM] {self.litellm_model}: Injecting endpoint for streaming {provider}: {endpoint}"
                )

        # Get MCP tools from proxy (no server connections during setup - lazy)
        tools = []
        if mcp_proxy:
            tools = mcp_proxy.get_tools_for_llm()
            if tools:
                kwargs['tools'] = tools
                logger.debug(f"[MCP] Added {len(tools)} tools to streaming request")

        logger.info(
            f"[LiteLLM] {self.litellm_model}: Creating streaming connection with {len(messages)} messages and kwargs: {self._mask_sensitive_kwargs(kwargs)}"
        )

        # Create stream connection - can raise exceptions
        try:
            stream = await litellm.acompletion(
                model=self.litellm_model, messages=messages, stream=True, **kwargs
            )
            logger.info(f"[LiteLLM] {self.litellm_model}: Stream connection created successfully")
            # Store messages, kwargs, and MCP proxy for potential tool execution
            stream._eneo_context = {
                'messages': messages,
                'kwargs': kwargs,
                'has_tools': bool(tools),
                'mcp_proxy': mcp_proxy,  # Store proxy for tool execution
            }
            return stream

        except AuthenticationError as exc:
            provider = self._detect_provider(self.litellm_model)
            logger.error(
                "Authentication failed (streaming)",
                extra={
                    "tenant_id": str(self.credential_resolver.tenant.id) if self.credential_resolver and self.credential_resolver.tenant else None,
                    "tenant_name": self.credential_resolver.tenant.name if self.credential_resolver and self.credential_resolver.tenant else None,
                    "provider": provider,
                    "error_type": "AuthenticationError",
                    "model": self.litellm_model,
                },
            )
            raise APIKeyNotConfiguredException(
                f"Invalid API credentials for provider '{provider}'. "
                f"Please verify your API key configuration."
            ) from exc

        except RateLimitError as exc:
            provider = self._detect_provider(self.litellm_model)
            logger.error(
                "Rate limit error (streaming)",
                extra={
                    "provider": provider,
                    "model": self.litellm_model,
                },
            )
            raise OpenAIException(
                f"Rate limit exceeded for {provider}. Please try again later."
            ) from exc

        except APIError as exc:
            error_message = str(exc)
            provider = self._detect_provider(self.litellm_model)
            logger.error(
                f"API error (streaming): {error_message}",
                extra={
                    "tenant_id": str(self.credential_resolver.tenant.id) if self.credential_resolver and self.credential_resolver.tenant else None,
                    "provider": provider,
                    "model": self.litellm_model,
                },
            )

            # Check for Azure firewall/network errors in the error message
            if "Virtual Network/Firewall" in error_message or "Firewall rules" in error_message or "Access denied" in error_message:
                raise OpenAIException(
                    "Azure access denied: Virtual Network/Firewall rules. "
                    "Please check your Azure network configuration or contact your administrator."
                ) from exc
            elif "rate limit" in error_message.lower():
                raise OpenAIException(
                    f"Rate limit exceeded for {provider}. Please try again later."
                ) from exc
            else:
                raise OpenAIException(f"API error: {error_message}") from exc

        except Exception as exc:
            logger.exception(f"[LiteLLM] {self.litellm_model}: Unexpected error creating stream")
            raise OpenAIException("Unknown error occurred") from exc

    async def iterate_stream(self, stream, context: Context = None, model_kwargs: ModelKwargs | None = None):
        """
        Phase 2: Iterate pre-created stream inside EventSourceResponse.
        Yields error events for mid-stream failures.
        """
        try:
            logger.info(f"[LiteLLM] {self.litellm_model}: Starting stream iteration")

            # Collect tool calls from stream
            tool_calls_accumulator = {}
            has_tool_calls = False

            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta

                    # Accumulate tool calls
                    if delta and hasattr(delta, 'tool_calls') and delta.tool_calls:
                        has_tool_calls = True
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in tool_calls_accumulator:
                                tool_calls_accumulator[idx] = {
                                    'id': tc_delta.id if hasattr(tc_delta, 'id') else None,
                                    'type': 'function',
                                    'function': {
                                        'name': '',
                                        'arguments': ''
                                    }
                                }
                            if hasattr(tc_delta, 'id') and tc_delta.id:
                                tool_calls_accumulator[idx]['id'] = tc_delta.id
                            if hasattr(tc_delta, 'function'):
                                if hasattr(tc_delta.function, 'name') and tc_delta.function.name:
                                    tool_calls_accumulator[idx]['function']['name'] = tc_delta.function.name
                                if hasattr(tc_delta.function, 'arguments') and tc_delta.function.arguments:
                                    tool_calls_accumulator[idx]['function']['arguments'] += tc_delta.function.arguments

                    if delta and delta.content:
                        yield Completion(text=delta.content)

            # If tool calls were detected, execute them via proxy (with loop for multi-turn)
            mcp_proxy = stream._eneo_context.get('mcp_proxy') if hasattr(stream, '_eneo_context') else None
            if has_tool_calls and mcp_proxy and stream._eneo_context.get('has_tools'):
                # Get context from stream
                messages = stream._eneo_context['messages']
                kwargs = stream._eneo_context['kwargs']
                allowed_tools = mcp_proxy.get_allowed_tool_names()

                # Loop to handle multiple rounds of tool calls
                max_tool_rounds = 10  # Safety limit
                tool_round = 0

                while has_tool_calls and tool_round < max_tool_rounds:
                    tool_round += 1
                    logger.debug(f"[MCP] Tool round {tool_round}: LLM requested {len(tool_calls_accumulator)} tool call(s)")

                    # Reconstruct tool calls as simple objects
                    tool_calls = []
                    for idx in sorted(tool_calls_accumulator.keys()):
                        tc = tool_calls_accumulator[idx]
                        class ToolCall:
                            def __init__(self, id, function_name, function_args):
                                self.id = id
                                self.type = 'function'
                                self.function = type('Function', (), {
                                    'name': function_name,
                                    'arguments': function_args
                                })()
                        tool_calls.append(ToolCall(tc['id'], tc['function']['name'], tc['function']['arguments']))

                    # Validate all tools are allowed
                    for tc in tool_calls:
                        if tc.function.name not in allowed_tools:
                            logger.warning(f"[SECURITY] Blocked unauthorized tool call (streaming): {tc.function.name}")
                            raise SecurityError(f"Tool '{tc.function.name}' is not authorized")

                    # Emit structured tool call event for frontend i18n
                    tool_metadata = []
                    for tc in tool_calls:
                        # Use proxy to get display-friendly names
                        tool_info = mcp_proxy.get_tool_info(tc.function.name) if mcp_proxy else None
                        if tool_info:
                            server_name, tool_name = tool_info
                            tool_metadata.append(ToolCallMetadata(server_name=server_name, tool_name=tool_name))
                        elif "__" in tc.function.name:
                            # Fallback to parsing if proxy lookup fails
                            server, tool = tc.function.name.split("__", 1)
                            tool_metadata.append(ToolCallMetadata(server_name=server, tool_name=tool))
                        else:
                            tool_metadata.append(ToolCallMetadata(server_name="", tool_name=tc.function.name))

                    yield Completion(
                        response_type=ResponseType.TOOL_CALL,
                        tool_calls_metadata=tool_metadata,
                    )

                    # Add assistant message with tool calls
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments
                                }
                            } for tc in tool_calls
                        ]
                    })

                    # Execute tools via proxy (parallel, lazy connections)
                    proxy_tool_calls = [
                        (tc.function.name, json.loads(tc.function.arguments) if tc.function.arguments else {})
                        for tc in tool_calls
                    ]
                    results = await mcp_proxy.call_tools_parallel(proxy_tool_calls)

                    # Add results to messages
                    for tc, result in zip(tool_calls, results):
                        result_text = ""
                        if result.get("content"):
                            for content_item in result["content"]:
                                if content_item.get("type") == "text":
                                    result_text += content_item.get("text", "")
                        if result.get("is_error"):
                            result_text = json.dumps({"error": result_text or "Tool execution failed"})

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result_text
                        })

                    # Make follow-up streaming request (keep tools for potential next round)
                    logger.debug(f"[MCP] Making follow-up streaming request (round {tool_round})")
                    response = await litellm.acompletion(
                        model=self.litellm_model,
                        messages=messages,
                        stream=True,
                        **kwargs  # Keep tools for multi-turn
                    )

                    # Process follow-up stream, check for more tool calls
                    tool_calls_accumulator = {}
                    has_tool_calls = False

                    async for chunk in response:
                        if chunk.choices and len(chunk.choices) > 0:
                            delta = chunk.choices[0].delta

                            # Accumulate any new tool calls
                            if delta and hasattr(delta, 'tool_calls') and delta.tool_calls:
                                has_tool_calls = True
                                for tc_delta in delta.tool_calls:
                                    idx = tc_delta.index
                                    if idx not in tool_calls_accumulator:
                                        tool_calls_accumulator[idx] = {
                                            'id': tc_delta.id if hasattr(tc_delta, 'id') else None,
                                            'type': 'function',
                                            'function': {'name': '', 'arguments': ''}
                                        }
                                    if hasattr(tc_delta, 'id') and tc_delta.id:
                                        tool_calls_accumulator[idx]['id'] = tc_delta.id
                                    if hasattr(tc_delta, 'function'):
                                        if hasattr(tc_delta.function, 'name') and tc_delta.function.name:
                                            tool_calls_accumulator[idx]['function']['name'] = tc_delta.function.name
                                        if hasattr(tc_delta.function, 'arguments') and tc_delta.function.arguments:
                                            tool_calls_accumulator[idx]['function']['arguments'] += tc_delta.function.arguments

                            # Yield text content
                            if delta and delta.content:
                                yield Completion(text=delta.content)

                if tool_round >= max_tool_rounds:
                    logger.warning(f"[MCP] Reached max tool rounds ({max_tool_rounds}), stopping")

            # Send final stop chunk
            logger.info(f"[LiteLLM] {self.litellm_model}: Stream iteration completed")
            yield Completion(stop=True)

        except Exception as exc:
            # Mid-stream errors: yield error event instead of raising
            logger.error(f"[LiteLLM] {self.litellm_model}: Error during stream iteration: {exc}")
            yield Completion(
                text="",
                error=f"Stream error: {str(exc)}",
                error_code=500,
                response_type=ResponseType.ERROR,
                stop=True
            )

    def get_response_streaming(
        self, context: Context, model_kwargs: ModelKwargs | None = None
    ):
        """
        Legacy method for backward compatibility.
        Uses two-phase pattern internally.
        """
        return self._get_response_streaming(context, model_kwargs)

    async def _get_response_streaming(
        self, context: Context, model_kwargs: ModelKwargs | None = None
    ) -> AsyncGenerator[Completion, None]:
        """
        Legacy implementation using two-phase pattern internally.
        """
        # Phase 1: Create stream (can raise exceptions)
        stream = await self.prepare_streaming(context, model_kwargs)

        # Phase 2: Iterate stream (yields error events for failures)
        async for chunk in self.iterate_stream(stream, context, model_kwargs):
            yield chunk
