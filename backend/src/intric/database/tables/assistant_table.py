from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.ai_models_table import CompletionModels
from intric.database.tables.assistant_template_table import AssistantTemplates
from intric.database.tables.base_class import BaseCrossReference, BasePublic
from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.files_table import Files
from intric.database.tables.integration_table import IntegrationKnowledge
from intric.database.tables.mcp_server_table import MCPServers
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.users_table import Users
from intric.database.tables.websites_table import Websites


class Assistants(BasePublic):
    name: Mapped[str] = mapped_column()
    completion_model_kwargs: Mapped[Optional[dict]] = mapped_column(JSONB)
    guardrail_active: Mapped[Optional[bool]] = mapped_column()
    logging_enabled: Mapped[bool] = mapped_column()
    is_default: Mapped[bool] = mapped_column()
    published: Mapped[bool] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column()
    insight_enabled: Mapped[bool] = mapped_column(default=False)
    data_retention_days: Mapped[Optional[int]] = mapped_column()
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    # TODO: refactor since this is a somewhat weird solution having a
    # type column. The reason is bc front-end wants a non-nullable
    # "type" field in a bunch of models. Thus a field with a default
    # value cannot be used. Just adding it to all constructors and
    # factories => issues with model validation.
    # This was quickest, simplest solution.
    type: Mapped[str] = mapped_column(default="assistant")

    # Foreign keys
    user_id: Mapped[UUID] = mapped_column(ForeignKey(Users.id, ondelete="CASCADE"))
    completion_model_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(CompletionModels.id),
    )
    space_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"),
    )
    template_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(AssistantTemplates.id, ondelete="SET NULL")
    )

    # relationships
    groups: Mapped[list[CollectionsTable]] = relationship(
        secondary="assistants_groups", order_by=CollectionsTable.created_at
    )
    websites: Mapped[list[Websites]] = relationship(
        secondary="assistants_websites", order_by=Websites.created_at
    )
    integration_knowledge_list: Mapped[list[IntegrationKnowledge]] = relationship(
        secondary="assistant_integration_knowledge",
        order_by=IntegrationKnowledge.created_at,
    )
    mcp_servers: Mapped[list[MCPServers]] = relationship(
        secondary="assistant_mcp_servers", order_by=MCPServers.created_at
    )
    user: Mapped[Users] = relationship()
    completion_model: Mapped[Optional[CompletionModels]] = relationship()
    attachments: Mapped[list["AssistantsFiles"]] = relationship(
        order_by="AssistantsFiles.created_at", viewonly=True
    )
    template: Mapped[Optional[AssistantTemplates]] = relationship(viewonly=True)

    assistant_groups: Mapped[list["AssistantsGroups"]] = relationship(viewonly=True)
    assistant_integration_knowledge: Mapped[list["AssistantIntegrationKnowledge"]] = relationship(
        viewonly=True
    )
    assistant_websites: Mapped[list["AssistantsWebsites"]] = relationship(viewonly=True)
    assistant_mcp_servers: Mapped[list["AssistantMCPServers"]] = relationship(viewonly=True)
    assistant_mcp_server_tools: Mapped[list["AssistantMCPServerTools"]] = relationship(viewonly=True)

    __table_args__ = {"extend_existing": True}  # Temporary


class AssistantsGroups(BaseCrossReference):
    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Assistants.id, ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[UUID] = mapped_column(
        ForeignKey(CollectionsTable.id, ondelete="CASCADE"), primary_key=True
    )


class AssistantsWebsites(BaseCrossReference):
    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Assistants.id, ondelete="CASCADE"), primary_key=True
    )
    website_id: Mapped[UUID] = mapped_column(
        ForeignKey(Websites.id, ondelete="CASCADE"), primary_key=True
    )


class AssistantsFiles(BaseCrossReference):
    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Assistants.id, ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey(Files.id, ondelete="CASCADE"), primary_key=True
    )

    # Relationships
    file: Mapped[Files] = relationship()


class AssistantIntegrationKnowledge(BasePublic):
    __tablename__ = "assistant_integration_knowledge"

    assistant_id: Mapped[UUID] = mapped_column(ForeignKey(Assistants.id, ondelete="CASCADE"))
    integration_knowledge_id: Mapped[UUID] = mapped_column(
        ForeignKey(IntegrationKnowledge.id, ondelete="CASCADE")
    )


class AssistantMCPServers(BaseCrossReference):
    """Assistant-level MCP server selection.

    Note: MCP servers are accessed via `Assistants.mcp_servers` (direct many-to-many).
    This association table follows the same pattern as AssistantsGroups/AssistantsWebsites.
    """
    __tablename__ = "assistant_mcp_servers"

    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Assistants.id, ondelete="CASCADE"), primary_key=True
    )
    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServers.id, ondelete="CASCADE"), primary_key=True
    )


class AssistantMCPServerTools(BaseCrossReference):
    """Assistant-level tool permissions."""
    __tablename__ = "assistant_mcp_server_tools"

    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Assistants.id, ondelete="CASCADE"), primary_key=True
    )
    mcp_server_tool_id: Mapped[UUID] = mapped_column(
        ForeignKey("mcp_server_tools.id", ondelete="CASCADE"), primary_key=True
    )

    is_enabled: Mapped[bool] = mapped_column(server_default="True", nullable=False)
