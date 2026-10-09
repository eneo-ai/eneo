from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eneo.database.tables.base_class import BaseCrossReference, BasePublic
from eneo.database.tables.security_classifications_table import (
    SecurityClassification,
)
from eneo.database.tables.tenant_table import Tenants


class TranscriptionServiceConnections(BasePublic):
    """An organisation's connection to a native transcription service.

    ``endpoint_url`` is the normalised base the ``/v1`` paths are built on;
    ``api_key_encrypted`` holds the EncryptionService token and is never
    returned.
    """

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    security_classification_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(SecurityClassification.id, ondelete="SET NULL"), nullable=True
    )
    security_classification: Mapped[Optional[SecurityClassification]] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "name", name="uq_transcription_service_connections_name"
        ),
    )


class SpacesTranscriptionServiceConnections(BaseCrossReference):
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True
    )
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey(TranscriptionServiceConnections.id, ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
