from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.users_table import Users


class Jobs(BasePublic):
    # A job belongs to the person who queued it (user_id), or to the service
    # principal behind the service key that queued it. api_key_id is that key:
    # a trace, and what lets the worker sign the caller in again.
    user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), nullable=True
    )
    service_principal_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            "service_principals.id",
            ondelete="RESTRICT",
            name="fk_jobs_service_principal",
        ),
        nullable=True,
    )
    api_key_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("api_keys_v2.id", ondelete="SET NULL", name="fk_jobs_api_key"),
        nullable=True,
    )
    task: Mapped[str] = mapped_column()
    status: Mapped[str] = mapped_column()
    result_location: Mapped[Optional[str]] = mapped_column()
    failure_code: Mapped[Optional[str]] = mapped_column(String(64))
    name: Mapped[Optional[str]] = mapped_column()
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dispatch_envelope: Mapped[Optional[dict[str, object]]] = mapped_column(
        JSONB(none_as_null=True)
    )
    dispatch_attempted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    staging_cleaned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    __table_args__ = (
        CheckConstraint(
            "user_id IS NULL OR service_principal_id IS NULL",
            name="ck_jobs_single_owner",
        ),
        CheckConstraint(
            "api_key_id IS NULL OR service_principal_id IS NOT NULL",
            name="ck_jobs_api_key_requires_service_principal",
        ),
        Index(
            "ix_jobs_service_principal_created",
            "service_principal_id",
            "created_at",
            postgresql_where=text("service_principal_id IS NOT NULL"),
        ),
    )
