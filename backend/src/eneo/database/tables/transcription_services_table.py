from datetime import datetime
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import (
    Mapped,
    column_property,
    declared_attr,
    mapped_column,
    relationship,
)

from eneo.database.tables.base_class import BaseCrossReference, BasePublic
from eneo.database.tables.security_classifications_table import (
    SecurityClassification,
)
from eneo.database.tables.tenant_table import Tenants


class SpacesTranscriptionServiceConnections(BaseCrossReference):
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True
    )
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("transcription_service_connections.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )


class TranscriptionServiceConnections(BasePublic):
    """An organisation's connection to a native transcription service.

    ``endpoint_url`` is the normalised base the ``/v1`` paths are built on;
    ``api_key_encrypted`` holds the EncryptionService token and is never
    returned. The ``last_check_*`` columns hold the latest connection check of
    the current endpoint and key; changing either clears them. ``is_default``
    marks the one connection an administrator made the organisation's default.
    """

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    is_default: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    security_classification_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(SecurityClassification.id, ondelete="SET NULL"), nullable=True
    )
    security_classification: Mapped[Optional[SecurityClassification]] = relationship()
    last_check_outcome: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    last_check_identifies_speakers: Mapped[Optional[bool]] = mapped_column(
        nullable=True
    )
    last_check_times_words: Mapped[Optional[bool]] = mapped_column(nullable=True)
    last_check_service_version: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    # Why the check got no usable answer, and the status of an http_status one.
    last_check_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    last_check_status_code: Mapped[Optional[int]] = mapped_column(nullable=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    @declared_attr
    def space_count(cls) -> Mapped[int]:
        """How many spaces may use the connection, read with it."""
        grants = SpacesTranscriptionServiceConnections
        return column_property(
            sa.select(sa.func.count())
            .where(grants.connection_id == cls.id)
            .correlate_except(grants)
            .scalar_subquery()
        )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "name", name="uq_transcription_service_connections_name"
        ),
        # The backstop of "one default per organisation"; the repository
        # unmarks the previous default before a new one is marked.
        Index(
            "uq_transcription_service_connections_default",
            "tenant_id",
            unique=True,
            postgresql_where=sa.text("is_default"),
        ),
    )
