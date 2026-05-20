from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from intric.eneo_knowledge.client import UploadedFileInfo
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


class KnowledgeSourceFile(BaseModel):
    """File metadata as surfaced to the SpaceMCPServers UI.

    Status is passed through from eneo-knowledge verbatim:
    ``queued`` -> ``processing`` -> ``ready`` (or ``failed``).
    """

    id: str
    name: str
    mime_type: str
    size_bytes: int
    status: str
    error: Optional[str] = None
    page_count: Optional[int] = None
    created_at: str
    processed_at: Optional[str] = None

    @classmethod
    def from_upstream(cls, info: UploadedFileInfo) -> "KnowledgeSourceFile":
        return cls(
            id=info.id,
            name=info.name,
            mime_type=info.mime_type,
            size_bytes=info.size_bytes,
            status=info.status,
            error=info.error,
            page_count=info.page_count,
            created_at=info.created_at,
            processed_at=info.processed_at,
        )
