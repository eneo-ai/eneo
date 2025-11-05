from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BaseCrossReference

from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.spaces_table import Spaces


class GroupsSpaces(BaseCrossReference):
    __tablename__ = "groups_spaces" 

    collection_id: Mapped[UUID] = mapped_column(
        "group_id",
        ForeignKey(CollectionsTable.id
        , ondelete="CASCADE")
        , primary_key=True
        , index=True
    )
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"), primary_key=True, index=True
    )

    collection: Mapped["CollectionsTable"] = relationship(
        "CollectionsTable",
        viewonly=True,
        lazy="joined",
    )
    space: Mapped["Spaces"] = relationship(
        "Spaces",
        viewonly=True,
        lazy="joined",
    )
