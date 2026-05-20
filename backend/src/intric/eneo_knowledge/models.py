from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from intric.mcp_servers.presentation.models import MCPServerPublic


class KnowledgeSourceCreate(BaseModel):
    """Body for proxied knowledge-source creation.

    Plug-and-play: only the user-visible display name is required.
    Eneo derives the upstream slug and selects the configured default
    embedding model.
    """

    name: str = Field(min_length=1, max_length=200)


class KnowledgeSourceCreateResponse(BaseModel):
    knowledge_source_id: UUID
    eneo_knowledge_slug: str
    mcp_server: MCPServerPublic
    description: Optional[str] = None


class KnowledgeSourceSparse(BaseModel):
    """Listing entry — just enough for the UI to map MCP servers to ownership rows."""

    id: UUID
    eneo_knowledge_slug: str
    mcp_server_id: UUID
