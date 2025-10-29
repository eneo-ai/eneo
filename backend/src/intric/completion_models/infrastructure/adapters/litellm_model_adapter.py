import json
from typing import AsyncGenerator, Optional

import litellm
from litellm import AuthenticationError, APIError, RateLimitError
from litellm.experimental_mcp_client import load_mcp_tools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from intric.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModel,
    Context,
    ModelKwargs,
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

logger = get_logger(__name__)

TOKENS_RESERVED_FOR_COMPLETION = 1000


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

    async def setup_mcp_tools(self, mcp_servers: list):
        """Setup MCP tools from configured MCP servers.

        Args:
            mcp_servers: List of MCPServer domain entities from assistant

        Returns:
            Tuple of (tools, server_params_list) where server_params_list contains
            connection info for each server for later tool execution
        """
        tools = []
        server_params_list = []

        for mcp_server in mcp_servers:
            try:
                # Determine command and args based on server type
                # Get package values with fallback for None
                npm_pkg = getattr(mcp_server, 'npm_package', None)
                uvx_pkg = getattr(mcp_server, 'uvx_package', None)
                docker_img = getattr(mcp_server, 'docker_image', None)

                logger.debug(f"[MCP] Processing server: {mcp_server.name}, type={mcp_server.server_type}, npm={npm_pkg}, uvx={uvx_pkg}, docker={docker_img}")

                if mcp_server.server_type == "npm" and npm_pkg:
                    command = "npx"
                    args = ["-y", npm_pkg]
                elif mcp_server.server_type == "uvx" and uvx_pkg:
                    command = "uvx"
                    args = [uvx_pkg]
                elif mcp_server.server_type == "docker" and docker_img:
                    command = "docker"
                    args = ["run", "-i", "--rm", docker_img]
                elif mcp_server.server_type == "http":
                    logger.warning(f"[MCP] HTTP MCP servers not yet supported: {mcp_server.name}")
                    continue
                else:
                    logger.warning(f"[MCP] Invalid MCP server configuration: {mcp_server.name} - server_type={mcp_server.server_type}, has packages: npm={bool(npm_pkg)}, uvx={bool(uvx_pkg)}, docker={bool(docker_img)}")
                    continue

                logger.info(f"[MCP] Connecting to {mcp_server.name} ({mcp_server.server_type}) via stdio")

                server_params = StdioServerParameters(
                    command=command,
                    args=args,
                    # TODO: Add env_vars from tenant settings
                )

                # Connect and load tools
                async with stdio_client(server_params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        logger.info(f"[MCP] Successfully connected to {mcp_server.name}")

                        # Load tools in OpenAI format
                        mcp_tools = await load_mcp_tools(session=session, format="openai")

                        # Add metadata to each tool for display purposes
                        for tool in mcp_tools:
                            tool['mcp_server_name'] = mcp_server.name
                            tool['original_tool_name'] = tool['function']['name']

                        tools.extend(mcp_tools)
                        logger.info(f"[MCP] Loaded {len(mcp_tools)} tools from {mcp_server.name}")

                        # Store server params for tool execution later
                        server_params_list.append(server_params)

            except Exception as e:
                logger.exception(f"[MCP] Failed to connect to {mcp_server.name}: {e}")
                # Continue with other servers rather than failing completely

        return tools, server_params_list

    async def get_response(
        self, context: Context, model_kwargs: ModelKwargs | None = None, mcp_servers: list = []
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

        # Load MCP tools from configured servers
        tools = []
        server_params_list = []
        if mcp_servers:
            tools, server_params_list = await self.setup_mcp_tools(mcp_servers)

        if tools:
            kwargs['tools'] = tools
            logger.info(f"[LiteLLM] {self.litellm_model}: Added {len(tools)} MCP tools from {len(server_params_list)} server(s)")

        mcp_session = (server_params_list, tools) if server_params_list else None

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
            if hasattr(message, 'tool_calls') and message.tool_calls and mcp_session:
                logger.info(f"[LiteLLM] {self.litellm_model}: Model requested {len(message.tool_calls)} tool call(s), executing...")

                # Extract tools metadata from mcp_session
                _, tools_metadata = mcp_session

                # Create a lookup map for tool metadata by tool name
                tool_lookup = {}
                for tool in tools_metadata:
                    tool_name = tool['function']['name']
                    # The tool metadata includes mcp_server_name from MCPManager
                    tool_lookup[tool_name] = tool

                # Collect unique server names for the header
                server_names = set()
                for tc in message.tool_calls:
                    tool_meta = tool_lookup.get(tc.function.name, {})
                    if 'mcp_server_name' in tool_meta:
                        server_names.add(tool_meta['mcp_server_name'])

                # Build header with server names
                if len(server_names) == 1:
                    server_list = next(iter(server_names))
                    tool_info = f"\n\n🔧 **Using {server_list} MCP server**\n"
                elif len(server_names) > 1:
                    server_list = ", ".join(sorted(server_names))
                    tool_info = f"\n\n🔧 **Using MCP servers: {server_list}**\n"
                else:
                    tool_info = "\n\n🔧 **Executing MCP tools...**\n"

                # Build informational message about each tool execution
                for i, tc in enumerate(message.tool_calls, 1):
                    tool_meta = tool_lookup.get(tc.function.name, {})
                    server_display = tool_meta.get('mcp_server_name', 'Unknown')
                    original_tool_name = tool_meta.get('original_tool_name', tc.function.name)
                    tool_display = original_tool_name.replace('-', ' ').replace('_', ' ').title()

                    try:
                        args = json.loads(tc.function.arguments)
                        # Special formatting for context7 documentation tools
                        if 'libraryName' in args:
                            tool_info += f"{i}. **{server_display}**: Searching for library **{args['libraryName']}**\n"
                        elif 'context7CompatibleLibraryID' in args:
                            lib_id = args['context7CompatibleLibraryID'].split('/')[-1]
                            topic = args.get('topic', 'documentation')
                            tool_info += f"{i}. **{server_display}**: Fetching **{lib_id}** docs (topic: {topic})\n"
                        else:
                            tool_info += f"{i}. **{server_display}**: {tool_display}\n"
                    except Exception:
                        tool_info += f"{i}. **{server_display}**: {tool_display}\n"

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

                # Execute each tool call
                # Try each MCP server in sequence until tool executes successfully
                server_params_list, _ = mcp_session

                for tool_call in message.tool_calls:
                    logger.info(f"[MCP] Executing tool: {tool_call.function.name}")
                    tool_executed = False

                    # Try each MCP server
                    for server_params in server_params_list:
                        try:
                            async with stdio_client(server_params) as (read, write):
                                async with ClientSession(read, write) as session:
                                    await session.initialize()

                                    # Parse tool arguments from JSON string
                                    tool_name = tool_call.function.name
                                    arguments = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}

                                    # Execute the tool using native MCP method
                                    result = await session.call_tool(tool_name, arguments=arguments)

                                    # Extract text content from MCP result
                                    # MCP returns CallToolResult with content list
                                    result_text = ""
                                    if hasattr(result, 'content') and result.content:
                                        for content_item in result.content:
                                            if hasattr(content_item, 'text'):
                                                result_text += content_item.text

                                    logger.info(f"[MCP] Tool {tool_name} executed successfully. Result: {result_text}")

                                    # Add tool result to messages
                                    tool_message = {
                                        "role": "tool",
                                        "tool_call_id": tool_call.id,
                                        "content": result_text
                                    }
                                    logger.info(f"[MCP] Adding tool result to messages: {tool_message}")
                                    messages.append(tool_message)
                                    tool_executed = True
                                    break  # Success, don't try other servers
                        except Exception as e:
                            logger.error(f"[MCP] Server {server_params.command} couldn't execute tool {tool_call.function.name}: {e}")
                            continue  # Try next server

                    if not tool_executed:
                        # No server could execute the tool
                        logger.error(f"[MCP] No MCP server could execute tool: {tool_call.function.name}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps({"error": f"Tool {tool_call.function.name} not available"})
                        })

                # Make second completion request with tool results
                logger.info(f"[LiteLLM] {self.litellm_model}: Making follow-up request with tool results")
                logger.debug(f"[MCP] Follow-up messages: {json.dumps(messages, indent=2)}")
                # Remove tools from kwargs for follow-up request
                follow_up_kwargs = {k: v for k, v in kwargs.items() if k != 'tools'}
                response = await litellm.acompletion(
                    model=self.litellm_model,
                    messages=messages,
                    **follow_up_kwargs
                )
                message = response.choices[0].message
                logger.info(f"[MCP] Follow-up response: {message.content}")

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

    async def prepare_streaming(self, context: Context, model_kwargs: ModelKwargs | None = None, mcp_servers: list = []):
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

        # Load MCP tools from configured servers
        tools = []
        server_params_list = []
        if mcp_servers:
            tools, server_params_list = await self.setup_mcp_tools(mcp_servers)

        if tools:
            kwargs['tools'] = tools
            logger.info(f"[LiteLLM] {self.litellm_model}: Added {len(tools)} MCP tools to streaming request")

        logger.info(
            f"[LiteLLM] {self.litellm_model}: Creating streaming connection with {len(messages)} messages and kwargs: {self._mask_sensitive_kwargs(kwargs)}"
        )

        # Create stream connection - can raise exceptions
        try:
            stream = await litellm.acompletion(
                model=self.litellm_model, messages=messages, stream=True, **kwargs
            )
            logger.info(f"[LiteLLM] {self.litellm_model}: Stream connection created successfully")
            # Store messages, kwargs, and MCP server params for potential tool execution
            stream._eneo_context = {
                'messages': messages,
                'kwargs': kwargs,
                'has_tools': bool(tools),
                'server_params_list': server_params_list,  # Store MCP server params for tool execution
                'tools_metadata': tools  # Store tool metadata for display purposes
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
        from intric.ai_models.completion_models.completion_model import ResponseType

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

            # If tool calls were detected, execute them
            if has_tool_calls and hasattr(stream, '_eneo_context') and stream._eneo_context['has_tools']:
                logger.info(f"[LiteLLM] {self.litellm_model}: Model requested {len(tool_calls_accumulator)} tool call(s), executing...")

                # Reconstruct tool calls
                tool_calls = []
                for idx in sorted(tool_calls_accumulator.keys()):
                    tc = tool_calls_accumulator[idx]
                    # Create a simple object to match the expected interface
                    class ToolCall:
                        def __init__(self, id, function_name, function_args):
                            self.id = id
                            self.type = 'function'
                            self.function = type('Function', (), {
                                'name': function_name,
                                'arguments': function_args
                            })()
                    tool_calls.append(ToolCall(tc['id'], tc['function']['name'], tc['function']['arguments']))

                # Get tool metadata from context
                tools_metadata = stream._eneo_context.get('tools_metadata', [])

                # Create a lookup map for tool metadata by tool name
                tool_lookup = {}
                for tool in tools_metadata:
                    tool_name = tool['function']['name']
                    tool_lookup[tool_name] = tool

                # Collect unique server names for the header
                server_names = set()
                for tc in tool_calls:
                    tool_meta = tool_lookup.get(tc.function.name, {})
                    if 'mcp_server_name' in tool_meta:
                        server_names.add(tool_meta['mcp_server_name'])

                # Build header with server names
                if len(server_names) == 1:
                    server_list = next(iter(server_names))
                    tool_info = f"\n\n🔧 **Using {server_list} MCP server**\n"
                elif len(server_names) > 1:
                    server_list = ", ".join(sorted(server_names))
                    tool_info = f"\n\n🔧 **Using MCP servers: {server_list}**\n"
                else:
                    tool_info = "\n\n🔧 **Executing MCP tools...**\n"

                # Build informational message about each tool execution
                for i, tc in enumerate(tool_calls, 1):
                    tool_meta = tool_lookup.get(tc.function.name, {})
                    server_display = tool_meta.get('mcp_server_name', 'Unknown')
                    original_tool_name = tool_meta.get('original_tool_name', tc.function.name)
                    tool_display = original_tool_name.replace('-', ' ').replace('_', ' ').title()

                    try:
                        args = json.loads(tc.function.arguments)
                        # Special formatting for context7 documentation tools
                        if 'libraryName' in args:
                            tool_info += f"{i}. **{server_display}**: Searching for library **{args['libraryName']}**\n"
                        elif 'context7CompatibleLibraryID' in args:
                            lib_id = args['context7CompatibleLibraryID'].split('/')[-1]
                            topic = args.get('topic', 'documentation')
                            tool_info += f"{i}. **{server_display}**: Fetching **{lib_id}** docs (topic: {topic})\n"
                        else:
                            tool_info += f"{i}. **{server_display}**: {tool_display}\n"
                    except Exception:
                        tool_info += f"{i}. **{server_display}**: {tool_display}\n"

                yield Completion(text=tool_info)

                # Get context from stream
                messages = stream._eneo_context['messages']
                kwargs = stream._eneo_context['kwargs']

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

                # Execute tools using dynamic MCP servers
                server_params_list = stream._eneo_context.get('server_params_list', [])

                for tool_call in tool_calls:
                    logger.info(f"[MCP] Executing tool: {tool_call.function.name}")
                    tool_executed = False

                    # Try each MCP server until one successfully executes the tool
                    for server_params in server_params_list:
                        try:
                            async with stdio_client(server_params) as (read, write):
                                async with ClientSession(read, write) as session:
                                    await session.initialize()

                                    # Parse tool arguments from JSON string
                                    tool_name = tool_call.function.name
                                    arguments = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}

                                    # Execute the tool using native MCP method
                                    result = await session.call_tool(tool_name, arguments=arguments)

                                    # Extract text content from MCP result
                                    result_text = ""
                                    if hasattr(result, 'content') and result.content:
                                        for content_item in result.content:
                                            if hasattr(content_item, 'text'):
                                                result_text += content_item.text

                                    logger.info(f"[MCP] Tool {tool_name} executed successfully. Result: {result_text}")

                                    # Add tool result to messages
                                    messages.append({
                                        "role": "tool",
                                        "tool_call_id": tool_call.id,
                                        "content": result_text
                                    })
                                    tool_executed = True
                                    break  # Success, don't try other servers
                        except Exception as e:
                            logger.error(f"[MCP] Server {server_params.command} couldn't execute tool {tool_call.function.name}: {e}")
                            continue  # Try next server

                    if not tool_executed:
                        # No server could execute the tool
                        logger.error(f"[MCP] No MCP server could execute tool: {tool_call.function.name}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps({"error": f"Tool {tool_call.function.name} not available"})
                        })

                # Make follow-up streaming request with tool results
                logger.info(f"[LiteLLM] {self.litellm_model}: Making follow-up streaming request with tool results")
                follow_up_kwargs = {k: v for k, v in kwargs.items() if k != 'tools'}
                response = await litellm.acompletion(
                    model=self.litellm_model,
                    messages=messages,
                    stream=True,
                    **follow_up_kwargs
                )

                async for chunk in response:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if delta and delta.content:
                            yield Completion(text=delta.content)

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
