from datetime import datetime
from uuid import UUID

from sqlalchemy import TIMESTAMP, CheckConstraint, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BaseWithTableName, TimestampMixin


class ObjectStoreBindings(TimestampMixin, BaseWithTableName):
    """Durable database-to-bucket pairing facts for one destination slot.

    Slot 1 is the deployment's active destination (admin-managed or legacy
    environment-managed); slot 2 exists only while a destination migration
    holds a candidate or retiring destination. A row exists once binding
    initialization has durably chosen a binding identity, before the bucket
    marker is confirmed.
    """

    slot: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    deployment_id: Mapped[UUID] = mapped_column(nullable=False)
    binding_id: Mapped[UUID] = mapped_column(nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    claim_id: Mapped[UUID | None] = mapped_column(nullable=True)
    claim_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    create_started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    __table_args__ = (
        CheckConstraint("slot IN (1, 2)", name="ck_object_store_bindings_slot"),
        CheckConstraint(
            "(claim_id IS NULL) = (claim_until IS NULL)",
            name="ck_object_store_bindings_claim_pair",
        ),
        CheckConstraint(
            "claim_id IS NULL OR confirmed_at IS NULL",
            name="ck_object_store_bindings_claim_state",
        ),
    )
