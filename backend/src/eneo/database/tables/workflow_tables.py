from typing import Optional
from uuid import UUID

from sqlalchemy import Column, ForeignKey, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.base_class import Base, BasePublic
from eneo.database.tables.service_table import Services
from eneo.database.tables.users_table import Users


class Workflows(BasePublic):
    name: Mapped[str] = mapped_column()
    user_id: Mapped[UUID] = mapped_column(ForeignKey(Users.id, ondelete="CASCADE"))

    steps: Mapped[list["Steps"]] = relationship(order_by="Steps.order")


class Filters(BasePublic):
    type: Mapped[str] = mapped_column()
    chain_breaker_message: Mapped[str] = mapped_column()


class Steps(BasePublic):
    order: Mapped[Optional[int]] = mapped_column()
    workflow_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Workflows.id, ondelete="CASCADE")
    )
    service_id: Mapped[UUID] = mapped_column(
        ForeignKey(Services.id, ondelete="CASCADE")
    )
    filter_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Filters.id, ondelete="CASCADE")
    )

    filter: Mapped[Filters] = relationship()
    service: Mapped[Services] = relationship()


assistants_steps_guardrails_table = Table(
    "assistants_steps_guardrails",
    Base.metadata,  # type: ignore[attr-defined]
    Column(
        "assistant_id", ForeignKey(Assistants.id, ondelete="CASCADE"), primary_key=True
    ),  # pyright: ignore[reportUnknownArgumentType]  # untyped Column in Table constructor
    Column("step_id", ForeignKey(Steps.id, ondelete="CASCADE"), primary_key=True),  # pyright: ignore[reportUnknownArgumentType]  # untyped Column in Table constructor
)
