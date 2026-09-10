from enum import StrEnum
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    and_,
    func,
    text,
)
from sqlalchemy.engine.default import DefaultExecutionContext
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.elements import ColumnElement

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.database.tables.websites_table import Websites
from eneo.websites.domain.source_url import normalize_url


def _website_source_url_default(context: DefaultExecutionContext) -> str | None:
    values = context.get_current_parameters()
    url = values.get("url")
    if values.get("website_id") is not None and isinstance(url, str):
        return normalize_url(url)
    return None


class InfoBlobVersionState(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class InfoBlobs(BasePublic):
    __table_args__ = (
        CheckConstraint(
            "version_state IN ('active', 'superseded')",
            name="ck_info_blobs_version_state",
        ),
        Index(
            "uq_info_blobs_active_source",
            "source_id",
            unique=True,
            postgresql_where=text("version_state = 'active'"),
        ),
        Index("ix_info_blobs_source_id", "source_id"),
        Index(
            "ix_info_blobs_active_website_cursor",
            "website_id",
            "id",
            postgresql_where=text("version_state = 'active'"),
        ),
        Index(
            "ix_info_blobs_active_website_source_url",
            "website_id",
            text("md5(website_source_url)"),
            postgresql_where=text(
                "version_state = 'active' AND website_source_url IS NOT NULL"
            ),
        ),
    )

    text: Mapped[str] = mapped_column()
    title: Mapped[Optional[str]] = mapped_column()
    url: Mapped[Optional[str]] = mapped_column()
    website_source_url: Mapped[Optional[str]] = mapped_column(
        default=_website_source_url_default,
        comment="Normalized website publication identity; null for unresolved legacy URLs",
    )
    size: Mapped[int] = mapped_column()
    content_hash: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary(length=32),
        comment="SHA-256 hash of normalized content for change detection",
    )
    http_etag: Mapped[Optional[str]] = mapped_column(
        comment="ETag sent as If-None-Match on the next crawl",
    )
    http_last_modified: Mapped[Optional[str]] = mapped_column(
        comment="Last-Modified sent as If-Modified-Since on the next crawl",
    )
    source_id: Mapped[UUID] = mapped_column(nullable=False)
    version_state: Mapped[str] = mapped_column(String(16), nullable=False)

    # Foreign keys
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    group_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(CollectionsTable.id, ondelete="CASCADE"), index=True
    )
    website_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Websites.id, ondelete="CASCADE"), index=True
    )
    embedding_model_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(EmbeddingModels.id, ondelete="SET NULL"),
    )
    integration_knowledge_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(IntegrationKnowledge.id, ondelete="CASCADE"), index=True
    )
    sharepoint_item_id: Mapped[Optional[str]] = mapped_column()

    # relationships
    group: Mapped[CollectionsTable] = relationship()
    website: Mapped[Websites] = relationship()
    embedding_model: Mapped[Optional[EmbeddingModels]] = relationship()
    integration_knowledge: Mapped[Optional[IntegrationKnowledge]] = relationship()


def active_info_blob_version() -> ColumnElement[bool]:
    return InfoBlobs.version_state == InfoBlobVersionState.ACTIVE.value


def website_source_url_equals(url: str | ColumnElement[str]) -> ColumnElement[bool]:
    # The digest bounds index entries for long URLs. Equality always checks the
    # full URL too, so a digest collision cannot merge different sources.
    return and_(
        func.md5(InfoBlobs.website_source_url) == func.md5(url),
        InfoBlobs.website_source_url == url,
    )
