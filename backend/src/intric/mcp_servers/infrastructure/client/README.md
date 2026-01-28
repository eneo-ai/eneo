# MCP Client Integration - TODO

## Completed
- ✅ MCPClient - connects to npm/uvx/docker/http MCP servers
- ✅ MCPManager - manages multiple MCP connections and aggregates tools
- ✅ Context builder accepts mcp_tools parameter
- ✅ Assistant passes mcp_servers to completion service

## Remaining Work

### 1. Wire up MCP in completion_service.get_response()

Add this logic at the beginning of the method (after line 200):

```python
# Import at top of file
from intric.mcp_servers.infrastructure.client import MCPManager
from intric.ai_models.completion_models.completion_model import FunctionDefinition

# In get_response() method:
mcp_manager = None
mcp_tools = []

if mcp_servers:
    try:
        mcp_manager = MCPManager()

        # Get tenant env vars for each MCP server
        env_vars_map = {}
        # TODO: Fetch from mcp_server_settings for current tenant

        # Connect to all MCP servers
        await mcp_manager.connect_servers(mcp_servers, env_vars_map)

        # Get tools and convert to FunctionDefinition format
        for tool_dict in mcp_manager.get_tools_for_llm():
            func = tool_dict["function"]
            mcp_tools.append(FunctionDefinition(
                name=func["name"],
                description=func["description"],
                schema=func["parameters"]
            ))
    except Exception as e:
        logger.error(f"Failed to initialize MCP tools: {e}")
```

### 2. Pass mcp_tools to context builder

Update the build_context call (around line 210):

```python
context = self.context_builder.build_context(
    input_str=text_input,
    max_tokens=max_tokens,
    files=files,
    prompt=prompt,
    session=session,
    info_blob_chunks=info_blob_chunks,
    prompt_files=prompt_files,
    transcription_inputs=transcription_inputs,
    version=version,
    use_image_generation=use_image_generation,
    web_search_results=web_search_results,
    mcp_tools=mcp_tools,  # ADD THIS
)
```

### 3. Update _handle_tool_call() to execute MCP tools

Modify the method to:
1. Check if tool_name matches an MCP tool
2. If yes, call mcp_manager.call_tool()
3. Feed result back to LLM for continued processing

```python
async def _handle_tool_call(self, completion: AsyncGenerator[Completion], mcp_manager: Optional[MCPManager] = None):
    # ... existing code ...

    elif not function_called:
        call_args = json.loads(arguments)

        if name == "generate_image":
            # ... existing image generation code ...
        elif mcp_manager and name in mcp_manager.tools:
            # Execute MCP tool
            result = await mcp_manager.call_tool(name, call_args)

            # Convert result to completion format
            # TODO: Need to feed this back to LLM for multi-turn tool use
            chunk.text = self._format_mcp_result(result)
            chunk.response_type = ResponseType.TEXT
            yield chunk

        function_called = True
```

### 4. Cleanup MCP connections

Add cleanup logic at the end of get_response():

```python
# At the end, before return
if mcp_manager:
    await mcp_manager.disconnect_all()
```

### 5. Fetch tenant MCP settings

Create a method to fetch env_vars for each MCP server from the tenant's mcp_server_settings:

```python
async def _get_mcp_env_vars(self, mcp_servers: list[MCPServer], tenant_id: UUID) -> dict[str, dict[str, str]]:
    """Fetch environment variables for MCP servers from tenant settings."""
    # Query mcp_server_settings table
    # Return dict mapping server_id to env_vars
    pass
```

## Notes

- MCP tool execution is currently one-shot (tool -> response)
- Full tool calling loop (tool -> LLM -> tool -> LLM) requires more work
- HTTP MCP servers not yet implemented (need SSE transport)
- Error handling and timeouts need to be added
- Tool results should be formatted properly for the LLM
