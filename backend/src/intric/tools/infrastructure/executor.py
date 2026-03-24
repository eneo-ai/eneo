from intric.ai_models.completion_models.completion_model import FunctionDefinition
from intric.info_blobs.info_blob import InfoBlobChunkInDBWithScore
from intric.services.service import DatastoreResult
from intric.tools.infrastructure.search_knowledge import SearchKnowledgeTool


class LocalToolExecutor:
    """Routes and executes local (non-MCP) tools.

    Holds a registry of local tools and dispatches calls to the correct tool.
    Also collects side-effects (e.g. retrieved chunks) for persistence.
    """

    def __init__(self, tools: list):
        self._tools: dict[str, object] = {}
        for tool in tools:
            self._tools[tool.name] = tool

    def get_tool_definitions(self) -> list[FunctionDefinition]:
        return [tool.get_definition() for tool in self._tools.values()]

    def get_allowed_tool_names(self) -> set[str]:
        return set(self._tools.keys())

    def is_local_tool(self, name: str) -> bool:
        return name in self._tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Execute a local tool by name and return the result text."""
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown local tool: {name}")
        return await tool.execute(arguments)

    def get_accumulated_datastore_result(self) -> DatastoreResult:
        """Collect results from all SearchKnowledgeTool instances."""
        all_chunks: list[InfoBlobChunkInDBWithScore] = []
        for tool in self._tools.values():
            if isinstance(tool, SearchKnowledgeTool):
                all_chunks.extend(tool.get_accumulated_chunks())

        # Deduplicate by info_blob_id (keep highest score per blob)
        seen: dict = {}
        for chunk in all_chunks:
            if chunk.info_blob_id not in seen or chunk.score > seen[chunk.info_blob_id].score:
                seen[chunk.info_blob_id] = chunk

        no_duplicate_chunks = list(seen.values())

        return DatastoreResult(
            chunks=all_chunks,
            no_duplicate_chunks=no_duplicate_chunks,
            info_blobs=[],  # Full info_blobs are loaded separately if needed
        )
