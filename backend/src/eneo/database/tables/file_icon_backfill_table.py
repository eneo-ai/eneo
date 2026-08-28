from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BaseWithTableName


class FileIconBackfillItems(BaseWithTableName):
    """Temporary Release A ledger; removed by the Release B contract."""

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(nullable=False)
    variant: Mapped[str] = mapped_column(String(32), nullable=False)
    ordinal: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    payload_size_estimate: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), server_default=text("'pending'"), nullable=False
    )
    attempts: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), nullable=False
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_detail: Mapped[str | None] = mapped_column(String(512))
    failure_revision: Mapped[int | None] = mapped_column(BigInteger)
    content_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("object_contents.id", ondelete="RESTRICT")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "owner_kind IN ('file', 'icon')",
            name="ck_file_icon_backfill_items_owner_kind",
        ),
        CheckConstraint(
            "variant IN ('original', 'extracted_text', 'transcription', "
            "'derived_page', 'model_input', 'generated_artifact', "
            "'legacy_image', 'preview', 'primary')",
            name="ck_file_icon_backfill_items_variant",
        ),
        CheckConstraint("ordinal >= 0", name="ck_file_icon_backfill_items_ordinal"),
        CheckConstraint(
            "payload_size_estimate >= 0",
            name="ck_file_icon_backfill_items_payload_size",
        ),
        CheckConstraint(
            "state IN ('pending', 'ready', 'leased', 'failed', 'done', 'cancelled')",
            name="ck_file_icon_backfill_items_state",
        ),
        CheckConstraint("attempts >= 0", name="ck_file_icon_backfill_items_attempts"),
        CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
            name="ck_file_icon_backfill_items_lease_pair",
        ),
        CheckConstraint(
            "(state = 'done') = (content_id IS NOT NULL)",
            name="ck_file_icon_backfill_items_done_content",
        ),
        CheckConstraint(
            "(state = 'failed') = (failure_revision IS NOT NULL) AND "
            "(failure_revision IS NULL OR failure_revision >= 0)",
            name="ck_file_icon_backfill_items_failure_revision",
        ),
        CheckConstraint(
            "last_error_detail IS NULL OR char_length(last_error_detail) <= 512",
            name="ck_file_icon_backfill_items_error_detail",
        ),
        UniqueConstraint(
            "owner_kind",
            "owner_id",
            "variant",
            "ordinal",
            name="uq_file_icon_backfill_items_owner_variant",
        ),
        Index(
            "ix_file_icon_backfill_items_claim",
            "state",
            "lease_expires_at",
            "id",
        ),
    )


class FileIconBackfillAdmissionState(BaseWithTableName):
    """Transactional invalidation token for pre-campaign capacity decisions."""

    singleton: Mapped[bool] = mapped_column(
        Boolean,
        primary_key=True,
        server_default=text("true"),
    )
    generation: Mapped[int] = mapped_column(
        BigInteger,
        server_default=text("0"),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "singleton",
            name="ck_file_icon_backfill_admission_singleton",
        ),
        CheckConstraint(
            "generation >= 0",
            name="ck_file_icon_backfill_admission_generation",
        ),
    )


class FileIconBackfillCampaign(BaseWithTableName):
    """Frozen destination contract for the one Release A campaign."""

    id: Mapped[UUID] = mapped_column(primary_key=True)
    target_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    destination_revision: Mapped[int | None] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
    )
    halt_reason: Mapped[str | None] = mapped_column(String(512))
    resume_revision: Mapped[int] = mapped_column(
        BigInteger,
        server_default=text("0"),
        nullable=False,
    )
    resume_cursor_id: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        CheckConstraint(
            "target_kind IN ('postgres_inline', 'object_store')",
            name="ck_file_icon_backfill_campaign_target",
        ),
        CheckConstraint(
            "state IN ('active', 'halted', 'complete')",
            name="ck_file_icon_backfill_campaign_state",
        ),
        CheckConstraint(
            "(target_kind = 'postgres_inline' AND destination_revision IS NULL) "
            "OR (target_kind = 'object_store' AND destination_revision IS NOT NULL)",
            name="ck_file_icon_backfill_campaign_destination",
        ),
        CheckConstraint(
            "halt_reason IS NULL OR char_length(halt_reason) <= 512",
            name="ck_file_icon_backfill_campaign_halt_reason",
        ),
        CheckConstraint(
            "resume_revision >= 0",
            name="ck_file_icon_backfill_campaign_resume_revision",
        ),
        CheckConstraint(
            "resume_cursor_id IS NULL OR (resume_cursor_id >= 0 AND state = 'active')",
            name="ck_file_icon_backfill_campaign_resume_cursor",
        ),
        Index(
            "uq_file_icon_backfill_campaign_singleton",
            text("(true)"),
            unique=True,
        ),
    )
