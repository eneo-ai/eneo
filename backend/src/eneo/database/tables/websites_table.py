from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.job_table import Jobs
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.main.models import Status
from eneo.websites.domain.crawl_run import CrawlType, project_crawl_status


class CrawlRuns(BasePublic):
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_crawl_runs_job_id"),
        CheckConstraint(
            "phase IN ('pending_dispatch', 'queued', 'running', 'finalizing', "
            "'stopping', 'terminal')",
            name="ck_crawl_runs_phase",
        ),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('succeeded', 'unchanged', 'empty', "
            "'partial', 'failed', 'cancelled', 'interrupted')",
            name="ck_crawl_runs_outcome",
        ),
        CheckConstraint(
            "origin IN ('manual', 'scheduled', 'legacy')",
            name="ck_crawl_runs_origin",
        ),
        CheckConstraint(
            "(phase = 'terminal') = (outcome IS NOT NULL)",
            name="ck_crawl_runs_terminal_outcome",
        ),
        CheckConstraint(
            "phase = 'terminal' OR finished_at IS NULL",
            name="ck_crawl_runs_nonterminal_unfinished",
        ),
        CheckConstraint(
            "phase <> 'terminal' OR origin = 'legacy' OR finished_at IS NOT NULL",
            name="ck_crawl_runs_terminal_finished_at",
        ),
        CheckConstraint(
            "(outcome IS NULL AND failure_code IS NULL AND failure_detail IS NULL) OR "
            "(outcome IN ('succeeded', 'unchanged', 'empty') "
            "AND failure_code IS NULL AND failure_detail IS NULL) OR "
            "(outcome IN ('partial', 'failed', 'cancelled', 'interrupted') "
            "AND failure_code IS NOT NULL)",
            name="ck_crawl_runs_outcome_failure",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_crawl_runs_attempt_count"),
        CheckConstraint(
            "pages_crawled IS NULL OR pages_crawled >= 0",
            name="ck_crawl_runs_pages_crawled",
        ),
        CheckConstraint(
            "files_downloaded IS NULL OR files_downloaded >= 0",
            name="ck_crawl_runs_files_downloaded",
        ),
        CheckConstraint(
            "pages_failed IS NULL OR pages_failed >= 0",
            name="ck_crawl_runs_pages_failed",
        ),
        CheckConstraint(
            "files_failed IS NULL OR files_failed >= 0",
            name="ck_crawl_runs_files_failed",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code IN ("
            "'dispatch_failed', 'invalid_dispatch', 'worker_interrupted', "
            "'lease_expired', 'remote_unreachable', 'remote_blocked', "
            "'timed_out', 'processing_failed', 'cancelled')",
            name="ck_crawl_runs_failure_code",
        ),
        CheckConstraint(
            "failure_detail IS NULL OR char_length(failure_detail) <= 512",
            name="ck_crawl_runs_failure_detail_length",
        ),
        Index(
            "uq_crawl_runs_active_website",
            "website_id",
            unique=True,
            postgresql_where=text("phase <> 'terminal'"),
        ),
        Index(
            "ix_crawl_runs_pending_dispatch",
            "created_at",
            "id",
            postgresql_where=text("phase = 'pending_dispatch'"),
        ),
        Index(
            "ix_crawl_runs_website_created",
            "website_id",
            "created_at",
            "id",
        ),
        Index("ix_crawl_runs_tenant_phase", "tenant_id", "phase"),
    )

    pages_crawled: Mapped[Optional[int]] = mapped_column()
    files_downloaded: Mapped[Optional[int]] = mapped_column()
    pages_failed: Mapped[Optional[int]] = mapped_column()
    files_failed: Mapped[Optional[int]] = mapped_column()
    failure_summary: Mapped[Optional[dict[str, int]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="JSONB dict mapping failure reason codes to counts",
    )
    phase: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending_dispatch"
    )
    outcome: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    origin: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="manual"
    )
    result_location: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    failure_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    failure_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancel_requested_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    # Foreign keys
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    website_id: Mapped[UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE")
    )
    job_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Jobs.id, ondelete="SET NULL")
    )

    @property
    def status(self) -> Status:
        return project_crawl_status(self.phase, self.outcome)


class CrawlAttempts(BasePublic):
    __table_args__ = (
        UniqueConstraint(
            "crawl_run_id",
            "attempt_number",
            name="uq_crawl_attempts_run_number",
        ),
        UniqueConstraint("dispatch_id", name="uq_crawl_attempts_dispatch_id"),
        CheckConstraint(
            "attempt_number >= 1",
            name="ck_crawl_attempts_attempt_number",
        ),
        CheckConstraint(
            "jsonb_typeof(dispatch_payload) = 'object'",
            name="ck_crawl_attempts_dispatch_payload_object",
        ),
        CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
            name="ck_crawl_attempts_lease_pair",
        ),
        CheckConstraint(
            "finished_at IS NULL OR lease_owner IS NULL",
            name="ck_crawl_attempts_finished_without_lease",
        ),
        CheckConstraint(
            "lease_owner IS NULL OR started_at IS NOT NULL",
            name="ck_crawl_attempts_lease_requires_start",
        ),
        CheckConstraint(
            "dispatched_at IS NULL OR dispatch_attempted_at IS NOT NULL",
            name="ck_crawl_attempts_dispatch_order",
        ),
        CheckConstraint(
            "started_at IS NULL OR dispatched_at IS NOT NULL",
            name="ck_crawl_attempts_start_requires_dispatch",
        ),
        CheckConstraint(
            "finished_at IS NOT NULL OR "
            "(failure_code IS NULL AND failure_detail IS NULL)",
            name="ck_crawl_attempts_terminal_failure",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code IN ("
            "'dispatch_failed', 'invalid_dispatch', 'worker_interrupted', "
            "'lease_expired', 'remote_unreachable', 'remote_blocked', "
            "'timed_out', 'processing_failed', 'cancelled')",
            name="ck_crawl_attempts_failure_code",
        ),
        CheckConstraint(
            "failure_detail IS NULL OR char_length(failure_detail) <= 512",
            name="ck_crawl_attempts_failure_detail_length",
        ),
        Index(
            "uq_crawl_attempts_active_run",
            "crawl_run_id",
            unique=True,
            postgresql_where=text("finished_at IS NULL"),
        ),
        Index(
            "ix_crawl_attempts_dispatch_candidates",
            "dispatch_attempted_at",
            "created_at",
            "id",
            postgresql_where=text("dispatched_at IS NULL AND finished_at IS NULL"),
        ),
        Index(
            "ix_crawl_attempts_redelivery_candidates",
            "dispatched_at",
            "dispatch_attempted_at",
            "created_at",
            "id",
            postgresql_where=text(
                "dispatched_at IS NOT NULL AND started_at IS NULL "
                "AND finished_at IS NULL"
            ),
        ),
        Index(
            "ix_crawl_attempts_expired_lease",
            "lease_expires_at",
            postgresql_where=text(
                "lease_expires_at IS NOT NULL AND finished_at IS NULL"
            ),
        ),
    )

    crawl_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(CrawlRuns.id, ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    dispatch_id: Mapped[UUID] = mapped_column(nullable=False)
    dispatch_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    dispatch_attempted_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    dispatched_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    lease_owner: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    failure_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    failure_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Websites(BasePublic):
    name: Mapped[Optional[str]] = mapped_column()
    url: Mapped[str] = mapped_column()
    download_files: Mapped[bool] = mapped_column()
    crawl_type: Mapped[CrawlType] = mapped_column()
    update_interval: Mapped[str] = mapped_column()
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_crawled_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # HTTP Basic Auth fields (all nullable - feature is optional)
    http_auth_username: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, comment="HTTP Basic Auth username"
    )
    encrypted_auth_password: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, comment="Fernet-encrypted password (base64 encoded)"
    )
    http_auth_domain: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, comment="Domain for auth (from URL netloc)"
    )

    # Circuit breaker fields for failure handling
    consecutive_failures: Mapped[int] = mapped_column(
        default=0,
        server_default="0",
        comment="Number of consecutive crawl failures for exponential backoff",
    )
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        comment="Timestamp when website should be retried after failures",
    )
    sitemap_state: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Fingerprint and timestamp of the last complete sitemap crawl",
    )

    # Foreign keys
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey(Users.id, ondelete="CASCADE"))
    embedding_model_id: Mapped[UUID] = mapped_column(ForeignKey(EmbeddingModels.id))
    group_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(CollectionsTable.id, ondelete="SET NULL")
    )
    space_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE")
    )

    # Relationships
    group: Mapped[CollectionsTable] = relationship()
    embedding_model: Mapped[EmbeddingModels] = relationship()

    @declared_attr  # pyright: ignore[reportArgumentType]  # dict return is valid for __mapper_args__ declared_attr
    def __mapper_args__(cls):  # type: ignore[override]
        most_recent_crawl = (
            select(CrawlRuns.id)
            .where(CrawlRuns.website_id == cls.id)
            .order_by(CrawlRuns.created_at.desc())
            .limit(1)
            .correlate(cls.__table__)  # type: ignore[attr-defined]
            .scalar_subquery()
        )

        latest_crawl_relationship = relationship(
            CrawlRuns,
            primaryjoin=and_(
                CrawlRuns.id == most_recent_crawl, CrawlRuns.website_id == cls.id
            ),
            uselist=False,
            viewonly=True,
        )
        return {"properties": {"latest_crawl": latest_crawl_relationship}}
