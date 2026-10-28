from enum import StrEnum
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    and_,
    case,
    func,
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
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
        # Serves active_document_counts; its predicate must stay identical.
        Index(
            "ix_info_blobs_active_integration_knowledge",
            "integration_knowledge_id",
            postgresql_where=text("version_state = 'active'"),
        ),
        # Per-file lookups and deletes of a SharePoint sync, all versions.
        Index(
            "ix_info_blobs_integration_knowledge_sharepoint_item",
            "integration_knowledge_id",
            "sharepoint_item_id",
            postgresql_where=text("sharepoint_item_id IS NOT NULL"),
        ),
        Index(
            "ix_info_blobs_active_website_source_url",
            "website_id",
            text("md5(website_source_url)"),
            postgresql_where=text(
                "version_state = 'active' AND website_source_url IS NOT NULL"
            ),
        ),
        # Serves a user's active-size sum (`/users/me` quota) as an
        # index-only scan instead of a bitmap scan over every version.
        Index(
            "ix_info_blobs_active_user_size",
            "user_id",
            postgresql_include=["size"],
            postgresql_where=text("version_state = 'active'"),
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
    # Ordered [{name, label, value, kind}] entries from the source system's own
    # document properties (SharePoint library columns). NULL when the source has
    # none. Kept as a list, not an object, because JSONB does not preserve key
    # order and the column order is meaningful to the people who defined it.
    source_metadata: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True
    )

    # relationships
    group: Mapped[CollectionsTable] = relationship()
    website: Mapped[Websites] = relationship()
    embedding_model: Mapped[Optional[EmbeddingModels]] = relationship()
    integration_knowledge: Mapped[Optional[IntegrationKnowledge]] = relationship()


def active_info_blob_version() -> ColumnElement[bool]:
    # A constant in the SQL text, not a bound parameter: PostgreSQL can then
    # prove the partial indexes' predicate even in generic prepared plans.
    return InfoBlobs.version_state == literal_column(
        f"'{InfoBlobVersionState.ACTIVE.value}'", String(16)
    )


def website_source_url_equals(url: str | ColumnElement[str]) -> ColumnElement[bool]:
    # The digest bounds index entries for long URLs. Equality always checks the
    # full URL too, so a digest collision cannot merge different sources.
    return and_(
        func.md5(InfoBlobs.website_source_url) == func.md5(url),
        InfoBlobs.website_source_url == url,
    )


def website_navigation_path() -> ColumnElement[str]:
    """A website resource's address as URL directories see it.

    Query and fragment are dropped and a bare origin gets its slash; rows from
    before ``website_source_url`` use their public URL. The migration of
    ``ix_info_blobs_active_website_path`` freezes this expression, and the
    planner uses that index only for an identical one. Its constants are
    literals, as in the index, rather than bound parameters.
    """
    address = func.split_part(
        func.split_part(
            func.coalesce(InfoBlobs.website_source_url, InfoBlobs.url),
            literal_column("'?'"),
            literal_column("1"),
            type_=Text,
        ),
        literal_column("'#'"),
        literal_column("1"),
        type_=Text,
    )
    return case(
        (
            address.op("~")(literal_column("'^https?://[^/]+$'")),
            address.concat(literal_column("'/'")),
        ),
        else_=address,
    )


def website_path_below(prefix: str) -> ColumnElement[bool]:
    """The navigation path starts with ``prefix``, as an index range.

    In byte order every string that starts with ``prefix`` sorts from it up to
    its last character's successor, so the range is exact and needs no LIKE
    escaping.
    """
    path = website_navigation_path().collate("C")
    return and_(path >= prefix, path < prefix[:-1] + chr(ord(prefix[-1]) + 1))


# Directory listings and prefix filters range over one website's active paths.
Index(
    "ix_info_blobs_active_website_path",
    InfoBlobs.website_id,
    website_navigation_path().collate("C"),
    postgresql_where=text("version_state = 'active'"),
)
