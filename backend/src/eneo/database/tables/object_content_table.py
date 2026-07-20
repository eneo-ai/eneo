from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BaseCrossReference, BasePublic
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users


class ObjectContents(BasePublic):
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_object_contents_tenant_id_idempotency_key",
        ),
        CheckConstraint(
            "state IN ('pending', 'available', 'retained', 'failed', "
            "'delete_pending', 'tombstoned')",
            name="ck_object_contents_state",
        ),
        CheckConstraint(
            "access_class IN ('private_resource', 'public_immutable')",
            name="ck_object_contents_access_class",
        ),
        CheckConstraint(
            "octet_length(sha256) = 32",
            name="ck_object_contents_sha256_length",
        ),
        CheckConstraint(
            "octet_length(request_fingerprint) = 32",
            name="ck_object_contents_request_fingerprint_length",
        ),
        CheckConstraint(
            "char_length(idempotency_key) BETWEEN 1 AND 255",
            name="ck_object_contents_idempotency_key_length",
        ),
        CheckConstraint("size_bytes >= 0", name="ck_object_contents_size_bytes"),
        CheckConstraint(
            "reference_count >= 0", name="ck_object_contents_reference_count"
        ),
        CheckConstraint("attempt_count >= 0", name="ck_object_contents_attempt_count"),
        CheckConstraint(
            "state <> 'available' OR available_at IS NOT NULL",
            name="ck_object_contents_available_at",
        ),
        CheckConstraint(
            "state NOT IN ('retained', 'delete_pending', 'tombstoned') OR "
            "(reference_count = 0 AND delete_requested_at IS NOT NULL)",
            name="ck_object_contents_delete_intent",
        ),
        CheckConstraint(
            "state <> 'tombstoned' OR remote_deleted_at IS NOT NULL",
            name="ck_object_contents_remote_deleted_at",
        ),
        CheckConstraint(
            "state <> 'failed' OR failure_code IS NOT NULL",
            name="ck_object_contents_failure_code",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code IN ("
            "'owner_detached', 'upload_retryable', 'upload_rejected', "
            "'verification_mismatch', 'remote_missing', 'remote_corrupt', "
            "'reference_drift', 'delete_retryable')",
            name="ck_object_contents_failure_code_value",
        ),
        CheckConstraint(
            "(lease_owner IS NULL) = (lease_until IS NULL)",
            name="ck_object_contents_lease_pair",
        ),
        CheckConstraint(
            "(multipart_upload_id IS NULL) = (multipart_initiated_at IS NULL)",
            name="ck_object_contents_multipart_pair",
        ),
        CheckConstraint(
            "failure_detail IS NULL OR char_length(failure_detail) <= 512",
            name="ck_object_contents_failure_detail_length",
        ),
        CheckConstraint(
            "multipart_upload_id IS NULL OR char_length(multipart_upload_id) <= 1024",
            name="ck_object_contents_multipart_upload_id_length",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="RESTRICT"), nullable=False
    )
    created_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"), nullable=True
    )
    object_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    access_class: Mapped[str] = mapped_column(String(32), nullable=False)
    sha256: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    declared_media_type: Mapped[Optional[str]] = mapped_column(String(255))
    verified_media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_fingerprint: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    reference_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    creation_transaction_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("txid_current()")
    )

    minimum_retain_until: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    delete_requested_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    available_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    remote_deleted_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    tombstone_purge_after: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )

    failure_code: Mapped[Optional[str]] = mapped_column(String(64))
    failure_detail: Mapped[Optional[str]] = mapped_column(String(512))
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    reference_audited_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    remote_observed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    lease_owner: Mapped[Optional[str]] = mapped_column(String(128))
    lease_until: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    multipart_upload_id: Mapped[Optional[str]] = mapped_column(Text)
    multipart_initiated_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )


class ObjectContentHolds(BasePublic):
    __table_args__ = (
        CheckConstraint(
            "kind IN ('legal', 'recovery')",
            name="ck_object_content_holds_kind",
        ),
        CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 512",
            name="ck_object_content_holds_reason_length",
        ),
        CheckConstraint(
            "released_at IS NULL OR released_at >= created_at",
            name="ck_object_content_holds_release_order",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at >= created_at",
            name="ck_object_content_holds_expires_at_order",
        ),
    )

    content_id: Mapped[UUID] = mapped_column(
        ForeignKey(ObjectContents.id, ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    actor_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL")
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    released_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))


class FileContentReferences(BaseCrossReference):
    __table_args__ = (
        PrimaryKeyConstraint(
            "file_id", "variant", "ordinal", name="pk_file_content_references"
        ),
        CheckConstraint(
            "variant IN ('original', 'extracted_text', 'transcription', "
            "'derived_page', 'model_input', 'generated_artifact', 'preview')",
            name="ck_file_content_references_variant",
        ),
        CheckConstraint("ordinal >= 0", name="ck_file_content_references_ordinal"),
        CheckConstraint(
            "page_number IS NULL OR page_number >= 1",
            name="ck_file_content_references_page_number",
        ),
        CheckConstraint(
            "width IS NULL OR width > 0", name="ck_file_content_references_width"
        ),
        CheckConstraint(
            "height IS NULL OR height > 0", name="ck_file_content_references_height"
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_file_content_references_duration",
        ),
    )

    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    content_id: Mapped[UUID] = mapped_column(
        ForeignKey(ObjectContents.id, ondelete="RESTRICT"), nullable=False
    )
    variant: Mapped[str] = mapped_column(String(32), nullable=False)
    ordinal: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    page_number: Mapped[Optional[int]]
    width: Mapped[Optional[int]]
    height: Mapped[Optional[int]]
    duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger)


class InfoBlobContentReferences(BaseCrossReference):
    __table_args__ = (
        PrimaryKeyConstraint(
            "info_blob_id", "variant", name="pk_info_blob_content_references"
        ),
        CheckConstraint(
            "variant = 'extracted_text'",
            name="ck_info_blob_content_references_variant",
        ),
    )

    info_blob_id: Mapped[UUID] = mapped_column(
        ForeignKey("info_blobs.id", ondelete="CASCADE"), nullable=False
    )
    content_id: Mapped[UUID] = mapped_column(
        ForeignKey(ObjectContents.id, ondelete="RESTRICT"), nullable=False
    )
    variant: Mapped[str] = mapped_column(String(32), nullable=False)


class IconContentReferences(BaseCrossReference):
    __table_args__ = (
        PrimaryKeyConstraint("icon_id", "variant", name="pk_icon_content_references"),
        CheckConstraint(
            "variant = 'primary'", name="ck_icon_content_references_variant"
        ),
    )

    icon_id: Mapped[UUID] = mapped_column(
        ForeignKey("icons.id", ondelete="CASCADE"), nullable=False
    )
    content_id: Mapped[UUID] = mapped_column(
        ForeignKey(ObjectContents.id, ondelete="RESTRICT"), nullable=False
    )
    variant: Mapped[str] = mapped_column(String(32), nullable=False)


class ObjectContentAuditEvents(BasePublic):
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('prepared', 'available', 'retained', 'failed', "
            "'delete_pending', 'tombstoned', 'reference_changed', "
            "'hold_changed')",
            name="ck_object_content_audit_events_type",
        ),
        CheckConstraint(
            "detail IS NULL OR char_length(detail) <= 512",
            name="ck_object_content_audit_events_detail_length",
        ),
    )

    content_id: Mapped[UUID] = mapped_column(
        ForeignKey(ObjectContents.id, ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(String(512))
    correlation_id: Mapped[Optional[UUID]]


class ObjectContentOrphanCandidates(BaseCrossReference):
    __table_args__ = (
        CheckConstraint(
            "size_bytes >= 0", name="ck_object_content_orphan_candidates_size"
        ),
        CheckConstraint(
            "completed_observations >= 0",
            name="ck_object_content_orphan_candidates_observations",
        ),
        CheckConstraint(
            "(lease_owner IS NULL) = (lease_until IS NULL)",
            name="ck_object_content_orphan_candidates_lease_pair",
        ),
    )

    object_key: Mapped[str] = mapped_column(Text, primary_key=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observed_cycle_id: Mapped[UUID] = mapped_column(nullable=False)
    eligible_after: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    completed_observations: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    lease_owner: Mapped[Optional[str]] = mapped_column(String(128))
    lease_until: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))


class ObjectContentMultipartCandidates(BaseCrossReference):
    __table_args__ = (
        PrimaryKeyConstraint(
            "object_key",
            "upload_id",
            name="pk_object_content_multipart_candidates",
        ),
        CheckConstraint(
            "char_length(upload_id) BETWEEN 1 AND 1024",
            name="ck_object_content_multipart_candidates_upload_id_length",
        ),
        CheckConstraint(
            "completed_observations >= 0",
            name="ck_object_content_multipart_candidates_observations",
        ),
        CheckConstraint(
            "(lease_owner IS NULL) = (lease_until IS NULL)",
            name="ck_object_content_multipart_candidates_lease_pair",
        ),
    )

    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    upload_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_initiated_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    observed_cycle_id: Mapped[UUID] = mapped_column(nullable=False)
    eligible_after: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    completed_observations: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    lease_owner: Mapped[Optional[str]] = mapped_column(String(128))
    lease_until: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))


class ObjectContentReconciliationState(BaseCrossReference):
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_object_content_reconciliation_state_id"),
        CheckConstraint(
            "object_completed_cycles >= 0",
            name="ck_object_content_reconciliation_state_cycles",
        ),
        CheckConstraint(
            "(store_deployment_id IS NULL) = (store_binding_id IS NULL)",
            name="ck_object_content_reconciliation_state_binding_pair",
        ),
        CheckConstraint(
            "store_binding_confirmed_at IS NULL OR store_binding_id IS NOT NULL",
            name="ck_object_content_reconciliation_state_binding_confirmation",
        ),
        CheckConstraint(
            "(store_binding_claim_id IS NULL) = (store_binding_claim_until IS NULL)",
            name="ck_object_content_reconciliation_state_binding_claim_pair",
        ),
        CheckConstraint(
            "store_binding_claim_id IS NULL OR "
            "(store_binding_id IS NOT NULL AND store_binding_confirmed_at IS NULL)",
            name="ck_object_content_reconciliation_state_binding_claim_state",
        ),
        CheckConstraint(
            "store_binding_create_started_at IS NULL OR store_binding_id IS NOT NULL",
            name="ck_object_content_reconciliation_state_binding_create_state",
        ),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, server_default=text("1")
    )
    object_cycle_id: Mapped[UUID] = mapped_column(
        server_default=text("gen_random_uuid()"), nullable=False
    )
    object_continuation_token: Mapped[Optional[str]] = mapped_column(Text)
    object_cycle_started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
    )
    object_completed_cycles: Mapped[int] = mapped_column(
        BigInteger, server_default=text("0"), nullable=False
    )
    last_object_cycle_completed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    last_completed_object_cycle_started_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    multipart_key_marker: Mapped[Optional[str]] = mapped_column(Text)
    multipart_upload_id_marker: Mapped[Optional[str]] = mapped_column(Text)
    multipart_cycle_id: Mapped[UUID] = mapped_column(
        server_default=text("gen_random_uuid()"), nullable=False
    )
    multipart_cycle_started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
    )
    last_multipart_cycle_completed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    store_deployment_id: Mapped[Optional[UUID]]
    store_binding_id: Mapped[Optional[UUID]]
    store_binding_confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    store_binding_claim_id: Mapped[Optional[UUID]]
    store_binding_claim_until: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    store_binding_create_started_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )


Index(
    "ix_object_contents_reconcile", ObjectContents.state, ObjectContents.next_attempt_at
)
Index("ix_object_contents_lease", ObjectContents.lease_until)
Index(
    "ix_object_contents_reference_audit",
    ObjectContents.reference_audited_at,
    ObjectContents.id,
)
Index(
    "ix_object_contents_remote_inventory",
    ObjectContents.state,
    ObjectContents.remote_observed_at,
    ObjectContents.available_at,
)
Index("ix_object_content_holds_content", ObjectContentHolds.content_id)
Index("ix_file_content_references_content", FileContentReferences.content_id)
Index(
    "ix_info_blob_content_references_content",
    InfoBlobContentReferences.content_id,
)
Index("ix_icon_content_references_content", IconContentReferences.content_id)
Index(
    "ix_object_content_audit_events_content_created",
    ObjectContentAuditEvents.content_id,
    ObjectContentAuditEvents.created_at,
)
Index(
    "ix_object_content_orphan_candidates_ready",
    ObjectContentOrphanCandidates.completed_observations,
    ObjectContentOrphanCandidates.eligible_after,
    ObjectContentOrphanCandidates.last_observed_at,
)
Index(
    "ix_object_content_multipart_candidates_ready",
    ObjectContentMultipartCandidates.completed_observations,
    ObjectContentMultipartCandidates.eligible_after,
    ObjectContentMultipartCandidates.last_observed_at,
)
