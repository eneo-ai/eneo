from uuid import UUID
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from intric.database.tables.base_class import BaseCrossReference
from intric.database.tables.websites_table import Websites
from intric.database.tables.spaces_table import Spaces

class WebsitesSpaces(BaseCrossReference):
    __tablename__ = "websites_spaces"

    website_id: Mapped[UUID] = mapped_column(
        ForeignKey(Websites.id, ondelete="CASCADE"),
        primary_key=True, index=True
    )
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"),
        primary_key=True, index=True
    )

    website: Mapped["Websites"] = relationship(viewonly=True, lazy="joined")
    space:   Mapped["Spaces"]   = relationship(viewonly=True, lazy="joined")
