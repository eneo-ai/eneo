from typing import Protocol, runtime_checkable

from intric.ai_models.completion_models.completion_model import FunctionDefinition


@runtime_checkable
class LocalTool(Protocol):
    """Base protocol for all local (non-MCP) tools.

    Any tool that should be available to the LLM alongside MCP tools
    implements this protocol and is registered with the LocalToolExecutor.
    """

    @property
    def name(self) -> str:
        """Unique tool name used in the LLM function call."""
        ...

    def get_definition(self) -> FunctionDefinition:
        """Return the tool definition for the LLM."""
        ...

    async def execute(self, arguments: dict) -> str:
        """Execute the tool with the given arguments and return the result text."""
        ...
