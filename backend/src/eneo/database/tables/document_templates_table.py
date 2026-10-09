"""Word templates an organisation's generated documents are rendered into.

A template belongs to the tenant (a nullable ``space_id`` is reserved for
space-owned templates later). Its bytes live in the row: templates are small,
few, and read only by the tool runtime through a signed link. Rows are soft
deleted so an assistant's choice stays resolvable until it is reset.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import BYTEA, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BaseCrossReference, BasePublic
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users


class DocumentTemplates(BasePublic):
    def __init__(
        self,
        *,
        tenant_id: UUID,
        name: str,
        filename: str,
        content: bytes,
        sha256: str,
        size_bytes: int,
        syntax: str,
        placeholders: list[dict[str, Any]],
        checks: dict[str, Any],
        status: str,
        is_default: bool,
        created_by: UUID | None = None,
        updated_by: UUID | None = None,
        space_id: UUID | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.space_id = space_id
        self.name = name
        self.filename = filename
        self.content = content
        self.sha256 = sha256
        self.size_bytes = size_bytes
        self.syntax = syntax
        self.placeholders = placeholders
        self.checks = checks
        self.status = status
        self.is_default = is_default
        self.created_by = created_by
        self.updated_by = updated_by

    __table_args__ = (
        CheckConstraint(
            "syntax IN ('controls', 'braces', 'mixed', 'none', 'unknown')",
            name="ck_document_templates_syntax",
        ),
        CheckConstraint(
            "status IN ('ready', 'invalid', 'unchecked')",
            name="ck_document_templates_status",
        ),
        CheckConstraint("size_bytes >= 0", name="ck_document_templates_size_bytes"),
        Index(
            "ix_document_templates_tenant_default",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_default AND deleted_at IS NULL"),
        ),
        Index(
            "ix_document_templates_tenant_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False, index=True
    )
    space_id: Mapped[Optional[UUID]] = mapped_column(
        # By name: spaces_table imports the capability rows, which point back here.
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Loaded only when the bytes are asked for; listings never detoast them.
    content: Mapped[bytes] = mapped_column(BYTEA, nullable=False, deferred=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    syntax: Mapped[str] = mapped_column(
        String, nullable=False, server_default="unknown"
    )
    placeholders: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    checks: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="unchecked"
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )


class AssistantDocumentTemplates(BaseCrossReference):
    """An assistant's choice for its file-creation capability.

    A row exists only when the assistant departs from the organisation's
    default: a selected template, or Eneo's built-in. It outlives toggling the
    capability, and a removed template takes its rows with it (the default).
    """

    __table_args__ = (
        CheckConstraint(
            "mode IN ('default', 'selected', 'builtin')",
            name="ck_assistant_document_templates_mode",
        ),
        CheckConstraint(
            "(mode = 'selected') = (document_template_id IS NOT NULL)",
            name="ck_assistant_document_templates_pair",
        ),
    )

    def __init__(
        self,
        *,
        mode: str,
        document_template_id: UUID | None = None,
        assistant_id: UUID | None = None,
    ) -> None:
        self.mode = mode
        self.document_template_id = document_template_id
        if assistant_id is not None:
            self.assistant_id = assistant_id

    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey("assistants.id", ondelete="CASCADE"), primary_key=True
    )
    mode: Mapped[str] = mapped_column(String, nullable=False)
    document_template_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(DocumentTemplates.id, ondelete="SET NULL"), nullable=True, index=True
    )
