from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BaseCrossReference
from intric.database.tables.integration_table import IntegrationKnowledge
from intric.database.tables.spaces_table import Spaces


class IntegrationKnowledgesSpaces(BaseCrossReference):
    """Junction table for distributing integration knowledge to child spaces.

    When integration knowledge is created on an org space (tenant_space_id IS NULL),
    it can be distributed to all child spaces (tenant_space_id = org_space_id)
    via this many-to-many relationship, similar to GroupsSpaces and WebsitesSpaces.
    """
    __tablename__ = "integration_knowledge_spaces"

    integration_knowledge_id: Mapped[UUID] = mapped_column(
        ForeignKey(IntegrationKnowledge.id, ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    integration_knowledge: Mapped["IntegrationKnowledge"] = relationship(
        viewonly=True, lazy="joined"
    )
    space: Mapped["Spaces"] = relationship(viewonly=True, lazy="joined")
