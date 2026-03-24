from typing import TYPE_CHECKING, Optional

from intric.ai_models.completion_models.completion_model import FunctionDefinition
from intric.info_blobs.info_blob import InfoBlobChunkInDBWithScore

if TYPE_CHECKING:
    from intric.collections.domain.collection import Collection
    from intric.embedding_models.domain.embedding_model import EmbeddingModel
    from intric.embedding_models.infrastructure.datastore import Datastore
    from intric.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from intric.websites.domain.website import Website

# Use the same defaults as v1 system-prompt injection:
# autocut_cutoff=3 filters out low-relevance results,
# num_chunks=30 caps the DB query.
_DEFAULT_AUTOCUT_CUTOFF = 3
_DEFAULT_NUM_CHUNKS = 30


def _build_sources_description(
    collections: list["Collection"],
    websites: list["Website"],
    integration_knowledge_list: list["IntegrationKnowledge"],
) -> str:
    """Build a dynamic description listing available knowledge sources."""
    lines = []
    for c in collections:
        desc = f"- {c.name}"
        if c.description:
            desc += f": {c.description}"
        lines.append(desc)
    for w in websites:
        label = w.name or w.url
        desc = f"- {label}"
        if hasattr(w, "description") and w.description:
            desc += f": {w.description}"
        lines.append(desc)
    for ik in integration_knowledge_list:
        desc = f"- {ik.name}"
        if hasattr(ik, "description") and ik.description:
            desc += f": {ik.description}"
        lines.append(desc)

    sources_text = "\n".join(lines) if lines else "No sources configured."
    return (
        "Search the knowledge base for information relevant to a query. "
        "Only use this tool when the user's question is related to the available sources. "
        "Do NOT use this tool for greetings, small talk, or questions unrelated to the sources below.\n"
        "Available sources:\n" + sources_text
    )


def _format_chunks(chunks: list[InfoBlobChunkInDBWithScore]) -> str:
    """Format retrieved chunks as text for the tool result.

    Uses the v2 format with source_title and source_id for reference support.
    """
    if not chunks:
        return "No relevant information found."

    parts = []
    for chunk in chunks:
        parts.append(
            '"""source_title: {}, source_id: {}\n{}"""'.format(
                chunk.info_blob_title,
                str(chunk.info_blob_id)[:8],
                chunk.text,
            )
        )
    return "\n".join(parts)


class SearchKnowledgeTool:
    """A local tool that searches the knowledge base via semantic search.

    One instance is created per assistant that has knowledge and tool_based_knowledge=True.
    The tool description is dynamically generated from the assistant's knowledge sources.
    """

    def __init__(
        self,
        datastore: "Datastore",
        embedding_model: "EmbeddingModel",
        collections: list["Collection"],
        websites: list["Website"],
        integration_knowledge_list: list["IntegrationKnowledge"],
        num_chunks: int = _DEFAULT_NUM_CHUNKS,
        autocut_cutoff: Optional[int] = _DEFAULT_AUTOCUT_CUTOFF,
    ):
        self._datastore = datastore
        self._embedding_model = embedding_model
        self._collections = collections
        self._websites = websites
        self._integration_knowledge_list = integration_knowledge_list
        self._num_chunks = num_chunks
        self._autocut_cutoff = autocut_cutoff

        # Accumulate chunks from all calls for reference persistence
        self._accumulated_chunks: list[InfoBlobChunkInDBWithScore] = []

    @property
    def name(self) -> str:
        return "search_knowledge"

    def get_definition(self) -> FunctionDefinition:
        description = _build_sources_description(
            self._collections,
            self._websites,
            self._integration_knowledge_list,
        )
        return FunctionDefinition(
            name=self.name,
            description=description,
            schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to find relevant information",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        )

    async def execute(self, arguments: dict) -> str:
        """Execute semantic search and return formatted results."""
        query = arguments.get("query", "")

        chunks = await self._datastore.semantic_search(
            search_string=query,
            embedding_model=self._embedding_model,
            collections=self._collections,
            websites=self._websites,
            integration_knowledge_list=self._integration_knowledge_list,
            num_chunks=self._num_chunks,
            autocut_cutoff=self._autocut_cutoff,
        )

        self._accumulated_chunks.extend(chunks)
        return _format_chunks(chunks)

    def get_accumulated_chunks(self) -> list[InfoBlobChunkInDBWithScore]:
        """Return all chunks retrieved across all calls for reference persistence."""
        return self._accumulated_chunks
