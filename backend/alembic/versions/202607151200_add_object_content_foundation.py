"""add platform object content foundation

Revision ID: 202607151200
Revises: 202607071200
Create Date: 2026-07-15 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607151200"
down_revision: str | None = "202607071200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_tables() -> None:
    op.create_table(
        "object_contents",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("access_class", sa.String(length=32), nullable=False),
        sa.Column("sha256", postgresql.BYTEA(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("declared_media_type", sa.String(length=255), nullable=True),
        sa.Column("verified_media_type", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", postgresql.BYTEA(), nullable=False),
        sa.Column("reference_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "creation_transaction_id",
            sa.BigInteger(),
            server_default=sa.text("txid_current()"),
            nullable=False,
        ),
        sa.Column("minimum_retain_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delete_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remote_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tombstone_purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_detail", sa.String(length=512), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reference_audited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remote_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("multipart_upload_id", sa.Text(), nullable=True),
        sa.Column("multipart_initiated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'available', 'retained', 'failed', "
            "'delete_pending', 'tombstoned')",
            name="ck_object_contents_state",
        ),
        sa.CheckConstraint(
            "access_class IN ('private_resource', 'public_immutable')",
            name="ck_object_contents_access_class",
        ),
        sa.CheckConstraint(
            "octet_length(sha256) = 32", name="ck_object_contents_sha256_length"
        ),
        sa.CheckConstraint(
            "octet_length(request_fingerprint) = 32",
            name="ck_object_contents_request_fingerprint_length",
        ),
        sa.CheckConstraint(
            "char_length(idempotency_key) BETWEEN 1 AND 255",
            name="ck_object_contents_idempotency_key_length",
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_object_contents_size_bytes"),
        sa.CheckConstraint(
            "reference_count >= 0", name="ck_object_contents_reference_count"
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_object_contents_attempt_count"
        ),
        sa.CheckConstraint(
            "state <> 'available' OR available_at IS NOT NULL",
            name="ck_object_contents_available_at",
        ),
        sa.CheckConstraint(
            "state NOT IN ('retained', 'delete_pending', 'tombstoned') OR "
            "(reference_count = 0 AND delete_requested_at IS NOT NULL)",
            name="ck_object_contents_delete_intent",
        ),
        sa.CheckConstraint(
            "state <> 'tombstoned' OR remote_deleted_at IS NOT NULL",
            name="ck_object_contents_remote_deleted_at",
        ),
        sa.CheckConstraint(
            "state <> 'failed' OR failure_code IS NOT NULL",
            name="ck_object_contents_failure_code",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code IN ("
            "'owner_detached', 'upload_retryable', 'upload_rejected', "
            "'verification_mismatch', 'remote_missing', 'remote_corrupt', "
            "'reference_drift', 'delete_retryable')",
            name="ck_object_contents_failure_code_value",
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL) = (lease_until IS NULL)",
            name="ck_object_contents_lease_pair",
        ),
        sa.CheckConstraint(
            "(multipart_upload_id IS NULL) = (multipart_initiated_at IS NULL)",
            name="ck_object_contents_multipart_pair",
        ),
        sa.CheckConstraint(
            "failure_detail IS NULL OR char_length(failure_detail) <= 512",
            name="ck_object_contents_failure_detail_length",
        ),
        sa.CheckConstraint(
            "multipart_upload_id IS NULL OR char_length(multipart_upload_id) <= 1024",
            name="ck_object_contents_multipart_upload_id_length",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key", name="uq_object_contents_object_key"),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_object_contents_tenant_id_idempotency_key",
        ),
    )

    op.create_table(
        "object_content_holds",
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('legal', 'recovery')", name="ck_object_content_holds_kind"
        ),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 512",
            name="ck_object_content_holds_reason_length",
        ),
        sa.CheckConstraint(
            "released_at IS NULL OR released_at >= created_at",
            name="ck_object_content_holds_release_order",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at >= created_at",
            name="ck_object_content_holds_expires_at_order",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["object_contents.id"],
            name="fk_object_content_holds_content",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    _create_reference_tables()

    op.create_table(
        "object_content_audit_events",
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.String(length=512), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('prepared', 'available', 'retained', 'failed', "
            "'delete_pending', 'tombstoned', 'reference_changed', "
            "'hold_changed')",
            name="ck_object_content_audit_events_type",
        ),
        sa.CheckConstraint(
            "detail IS NULL OR char_length(detail) <= 512",
            name="ck_object_content_audit_events_detail_length",
        ),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["object_contents.id"],
            name="fk_object_content_audit_events_content",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "object_content_orphan_candidates",
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("observed_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("eligible_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "completed_observations", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "size_bytes >= 0", name="ck_object_content_orphan_candidates_size"
        ),
        sa.CheckConstraint(
            "completed_observations >= 0",
            name="ck_object_content_orphan_candidates_observations",
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL) = (lease_until IS NULL)",
            name="ck_object_content_orphan_candidates_lease_pair",
        ),
        sa.PrimaryKeyConstraint("object_key"),
    )

    op.create_table(
        "object_content_reconciliation_state",
        sa.Column("id", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column(
            "object_cycle_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("object_continuation_token", sa.Text(), nullable=True),
        sa.Column(
            "object_cycle_started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "object_completed_cycles",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "last_object_cycle_completed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "last_completed_object_cycle_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("multipart_key_marker", sa.Text(), nullable=True),
        sa.Column("multipart_upload_id_marker", sa.Text(), nullable=True),
        sa.Column(
            "multipart_cycle_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "multipart_cycle_started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_multipart_cycle_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "store_deployment_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "store_binding_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "store_binding_confirmed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "store_binding_claim_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "store_binding_claim_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "store_binding_create_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_object_content_reconciliation_state_id"),
        sa.CheckConstraint(
            "object_completed_cycles >= 0",
            name="ck_object_content_reconciliation_state_cycles",
        ),
        sa.CheckConstraint(
            "(store_deployment_id IS NULL) = (store_binding_id IS NULL)",
            name="ck_object_content_reconciliation_state_binding_pair",
        ),
        sa.CheckConstraint(
            "store_binding_confirmed_at IS NULL OR store_binding_id IS NOT NULL",
            name="ck_object_content_reconciliation_state_binding_confirmation",
        ),
        sa.CheckConstraint(
            "(store_binding_claim_id IS NULL) = (store_binding_claim_until IS NULL)",
            name="ck_object_content_reconciliation_state_binding_claim_pair",
        ),
        sa.CheckConstraint(
            "store_binding_claim_id IS NULL OR "
            "(store_binding_id IS NOT NULL AND store_binding_confirmed_at IS NULL)",
            name="ck_object_content_reconciliation_state_binding_claim_state",
        ),
        sa.CheckConstraint(
            "store_binding_create_started_at IS NULL OR store_binding_id IS NOT NULL",
            name="ck_object_content_reconciliation_state_binding_create_state",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO object_content_reconciliation_state (id) VALUES (1)")

    op.create_table(
        "object_content_multipart_candidates",
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("upload_id", sa.Text(), nullable=False),
        sa.Column("provider_initiated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("eligible_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "completed_observations", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(upload_id) BETWEEN 1 AND 1024",
            name="ck_object_content_multipart_candidates_upload_id_length",
        ),
        sa.CheckConstraint(
            "completed_observations >= 0",
            name="ck_object_content_multipart_candidates_observations",
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL) = (lease_until IS NULL)",
            name="ck_object_content_multipart_candidates_lease_pair",
        ),
        sa.PrimaryKeyConstraint(
            "object_key",
            "upload_id",
            name="pk_object_content_multipart_candidates",
        ),
    )


def _create_reference_tables() -> None:
    timestamp_columns = (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_table(
        "file_content_references",
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variant", sa.String(length=32), nullable=False),
        sa.Column("ordinal", sa.Integer(), server_default="0", nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        *timestamp_columns,
        sa.CheckConstraint(
            "variant IN ('original', 'extracted_text', 'transcription', "
            "'derived_page', 'model_input', 'generated_artifact', 'preview')",
            name="ck_file_content_references_variant",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_file_content_references_ordinal"),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number >= 1",
            name="ck_file_content_references_page_number",
        ),
        sa.CheckConstraint(
            "width IS NULL OR width > 0", name="ck_file_content_references_width"
        ),
        sa.CheckConstraint(
            "height IS NULL OR height > 0", name="ck_file_content_references_height"
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_file_content_references_duration",
        ),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["object_contents.id"],
            name="fk_file_content_references_content",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name="fk_file_content_references_file",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "file_id", "variant", "ordinal", name="pk_file_content_references"
        ),
    )

    op.create_table(
        "info_blob_content_references",
        sa.Column("info_blob_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variant", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "variant = 'extracted_text'",
            name="ck_info_blob_content_references_variant",
        ),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["object_contents.id"],
            name="fk_info_blob_content_references_content",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["info_blob_id"],
            ["info_blobs.id"],
            name="fk_info_blob_content_references_info_blob",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "info_blob_id", "variant", name="pk_info_blob_content_references"
        ),
    )

    op.create_table(
        "icon_content_references",
        sa.Column("icon_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variant", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "variant = 'primary'", name="ck_icon_content_references_variant"
        ),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["object_contents.id"],
            name="fk_icon_content_references_content",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["icon_id"],
            ["icons.id"],
            name="fk_icon_content_references_icon",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "icon_id", "variant", name="pk_icon_content_references"
        ),
    )


def _create_indexes() -> None:
    indexes = (
        (
            "ix_object_contents_reconcile",
            "object_contents",
            ["state", "next_attempt_at"],
        ),
        ("ix_object_contents_lease", "object_contents", ["lease_until"]),
        (
            "ix_object_contents_reference_audit",
            "object_contents",
            ["reference_audited_at", "id"],
        ),
        (
            "ix_object_contents_remote_inventory",
            "object_contents",
            ["state", "remote_observed_at", "available_at"],
        ),
        ("ix_object_content_holds_content", "object_content_holds", ["content_id"]),
        (
            "ix_file_content_references_content",
            "file_content_references",
            ["content_id"],
        ),
        (
            "ix_info_blob_content_references_content",
            "info_blob_content_references",
            ["content_id"],
        ),
        (
            "ix_icon_content_references_content",
            "icon_content_references",
            ["content_id"],
        ),
        (
            "ix_object_content_audit_events_content_created",
            "object_content_audit_events",
            ["content_id", "created_at"],
        ),
        (
            "ix_object_content_orphan_candidates_ready",
            "object_content_orphan_candidates",
            ["completed_observations", "eligible_after", "last_observed_at"],
        ),
        (
            "ix_object_content_multipart_candidates_ready",
            "object_content_multipart_candidates",
            ["completed_observations", "eligible_after", "last_observed_at"],
        ),
    )
    for name, table, columns in indexes:
        op.create_index(name, table, columns, unique=False)


def _create_trigger_functions() -> None:
    op.execute("""
        CREATE FUNCTION object_content_guard_delete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.state <> 'tombstoned'
                OR OLD.tombstone_purge_after IS NULL
                OR OLD.tombstone_purge_after > now() THEN
                RAISE EXCEPTION
                    'object content cannot be hard-deleted before its purge horizon';
            END IF;
            RETURN OLD;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION object_content_pending_owner_fence() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM object_contents content
                WHERE content.id = NEW.id
                  AND content.state = 'pending'
                  AND NOT EXISTS (
                      SELECT 1 FROM file_content_references
                      WHERE content_id = content.id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM info_blob_content_references
                      WHERE content_id = content.id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM icon_content_references
                      WHERE content_id = content.id
                  )
            ) THEN
                RAISE EXCEPTION 'pending content requires an initial owner'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION object_content_guard_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (
                NEW.id,
                NEW.tenant_id,
                NEW.object_key,
                NEW.access_class,
                NEW.sha256,
                NEW.size_bytes,
                NEW.declared_media_type,
                NEW.verified_media_type,
                NEW.idempotency_key,
                NEW.request_fingerprint,
                NEW.creation_transaction_id,
                NEW.created_at
            ) IS DISTINCT FROM (
                OLD.id,
                OLD.tenant_id,
                OLD.object_key,
                OLD.access_class,
                OLD.sha256,
                OLD.size_bytes,
                OLD.declared_media_type,
                OLD.verified_media_type,
                OLD.idempotency_key,
                OLD.request_fingerprint,
                OLD.creation_transaction_id,
                OLD.created_at
            ) THEN
                RAISE EXCEPTION
                    'object content identity and integrity facts are immutable';
            END IF;

            IF NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
                AND NEW.created_by_user_id IS NOT NULL THEN
                RAISE EXCEPTION 'object content creator is immutable';
            END IF;

            IF NEW.reference_count IS DISTINCT FROM OLD.reference_count
                AND pg_trigger_depth() < 2 THEN
                RAISE EXCEPTION 'object content reference count is trigger-owned';
            END IF;

            IF OLD.delete_requested_at IS NOT NULL
                AND NEW.delete_requested_at
                    IS DISTINCT FROM OLD.delete_requested_at THEN
                RAISE EXCEPTION 'object content delete intent is irreversible';
            END IF;

            IF OLD.available_at IS NOT NULL
                AND NEW.available_at IS DISTINCT FROM OLD.available_at THEN
                RAISE EXCEPTION 'object content availability time is immutable';
            END IF;

            IF OLD.remote_deleted_at IS NOT NULL
                AND NEW.remote_deleted_at IS DISTINCT FROM OLD.remote_deleted_at THEN
                RAISE EXCEPTION 'object content deletion time is immutable';
            END IF;

            IF NEW.attempt_count < OLD.attempt_count THEN
                RAISE EXCEPTION 'object content attempt count is monotonic';
            END IF;

            IF OLD.minimum_retain_until IS NOT NULL
                AND (NEW.minimum_retain_until IS NULL
                    OR NEW.minimum_retain_until < OLD.minimum_retain_until) THEN
                RAISE EXCEPTION 'minimum retention may only be extended';
            END IF;

            IF OLD.state IN ('delete_pending', 'tombstoned')
                AND NEW.minimum_retain_until
                    IS DISTINCT FROM OLD.minimum_retain_until THEN
                RAISE EXCEPTION 'minimum retention cannot change after physical delete intent';
            END IF;

            IF NEW.state <> OLD.state AND NOT (
                (OLD.state = 'pending' AND NEW.state IN ('available', 'failed')) OR
                (OLD.state = 'available' AND NEW.state IN
                    ('retained', 'failed', 'delete_pending')) OR
                (OLD.state = 'retained' AND NEW.state = 'delete_pending') OR
                (OLD.state = 'failed' AND NEW.state = 'delete_pending') OR
                (OLD.state = 'delete_pending' AND NEW.state = 'tombstoned')
            ) THEN
                RAISE EXCEPTION 'illegal object content transition: % -> %',
                    OLD.state, NEW.state;
            END IF;
            RETURN NEW;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION object_content_reference_fence() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            content object_contents%ROWTYPE;
            next_reference_count integer;
            has_blocker boolean;
            expected_access_class text;
            owner_tenant_id uuid;
            target_content_id uuid;
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF TG_TABLE_NAME = 'file_content_references'
                    AND (NEW.file_id, NEW.content_id, NEW.variant, NEW.ordinal)
                        IS DISTINCT FROM
                        (OLD.file_id, OLD.content_id, OLD.variant, OLD.ordinal) THEN
                    RAISE EXCEPTION 'object content reference identity is immutable';
                ELSIF TG_TABLE_NAME = 'info_blob_content_references'
                    AND (NEW.info_blob_id, NEW.content_id, NEW.variant)
                        IS DISTINCT FROM
                        (OLD.info_blob_id, OLD.content_id, OLD.variant) THEN
                    RAISE EXCEPTION 'object content reference identity is immutable';
                ELSIF TG_TABLE_NAME = 'icon_content_references'
                    AND (NEW.icon_id, NEW.content_id, NEW.variant)
                        IS DISTINCT FROM
                        (OLD.icon_id, OLD.content_id, OLD.variant) THEN
                    RAISE EXCEPTION 'object content reference identity is immutable';
                END IF;
                RETURN NEW;
            END IF;

            target_content_id := CASE WHEN TG_OP = 'INSERT'
                THEN NEW.content_id ELSE OLD.content_id END;

            IF TG_OP = 'INSERT' AND TG_TABLE_NAME = 'file_content_references' THEN
                SELECT tenant_id INTO owner_tenant_id
                FROM files WHERE id = NEW.file_id
                FOR KEY SHARE;
            ELSIF TG_OP = 'INSERT'
                AND TG_TABLE_NAME = 'info_blob_content_references' THEN
                SELECT tenant_id INTO owner_tenant_id
                FROM info_blobs WHERE id = NEW.info_blob_id
                FOR KEY SHARE;
            ELSIF TG_OP = 'INSERT'
                AND TG_TABLE_NAME = 'icon_content_references' THEN
                SELECT tenant_id INTO owner_tenant_id
                FROM icons WHERE id = NEW.icon_id
                FOR KEY SHARE;
            END IF;

            IF TG_OP = 'INSERT' AND owner_tenant_id IS NULL THEN
                RAISE EXCEPTION 'object content reference owner does not exist';
            END IF;

            IF TG_TABLE_NAME = 'icon_content_references' THEN
                expected_access_class := 'public_immutable';
            ELSE
                expected_access_class := 'private_resource';
            END IF;

            SELECT * INTO content
            FROM object_contents
            WHERE id = target_content_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'referenced object content does not exist';
            END IF;

            IF TG_OP = 'INSERT' AND content.tenant_id <> owner_tenant_id THEN
                RAISE EXCEPTION 'object content reference tenant mismatch';
            END IF;

            IF TG_OP = 'INSERT' THEN
                IF content.access_class <> expected_access_class THEN
                    RAISE EXCEPTION 'object content access class mismatch';
                END IF;
                IF content.delete_requested_at IS NOT NULL THEN
                    RAISE EXCEPTION 'object content with delete intent cannot be attached';
                END IF;
                IF content.state = 'pending' THEN
                    IF content.reference_count <> 0
                        OR content.creation_transaction_id <> txid_current() THEN
                        RAISE EXCEPTION
                            'pending content may only receive its first reference in its creation transaction';
                    END IF;
                ELSIF content.state <> 'available' THEN
                    RAISE EXCEPTION 'only available object content can receive a later reference';
                END IF;

                UPDATE object_contents
                SET reference_count = reference_count + 1,
                    reference_audited_at = NULL,
                    updated_at = now()
                WHERE id = content.id;
                RETURN NEW;
            END IF;

            next_reference_count := content.reference_count - 1;
            IF next_reference_count < 0 THEN
                RAISE EXCEPTION 'object content reference count underflow';
            END IF;

            IF next_reference_count > 0 THEN
                UPDATE object_contents
                SET reference_count = next_reference_count,
                    reference_audited_at = NULL,
                    updated_at = now()
                WHERE id = content.id;
            ELSIF content.state = 'pending' THEN
                UPDATE object_contents
                SET reference_count = 0,
                    reference_audited_at = NULL,
                    state = 'failed',
                    failure_code = 'owner_detached',
                    failure_detail = 'initial owner detached before availability',
                    delete_requested_at = COALESCE(delete_requested_at, now()),
                    next_attempt_at = now(),
                    updated_at = now()
                WHERE id = content.id;
            ELSIF content.state = 'available' THEN
                SELECT
                    COALESCE(content.minimum_retain_until > now(), false)
                    OR EXISTS (
                        SELECT 1 FROM object_content_holds
                        WHERE content_id = content.id
                          AND released_at IS NULL
                          AND (expires_at IS NULL OR expires_at > now())
                    )
                INTO has_blocker;
                UPDATE object_contents
                SET reference_count = 0,
                    reference_audited_at = NULL,
                    state = CASE WHEN has_blocker THEN 'retained'
                                 ELSE 'delete_pending' END,
                    delete_requested_at = COALESCE(delete_requested_at, now()),
                    next_attempt_at = CASE WHEN has_blocker THEN NULL ELSE now() END,
                    updated_at = now()
                WHERE id = content.id;
            ELSE
                UPDATE object_contents
                SET reference_count = 0,
                    reference_audited_at = NULL,
                    delete_requested_at = COALESCE(delete_requested_at, now()),
                    next_attempt_at = now(),
                    updated_at = now()
                WHERE id = content.id;
            END IF;
            RETURN OLD;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION object_content_hold_guard_delete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM object_contents WHERE id = OLD.content_id
            ) THEN
                RAISE EXCEPTION
                    'an object content hold cannot be hard-deleted';
            END IF;
            RETURN OLD;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION object_content_hold_fence() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            content object_contents%ROWTYPE;
            has_other_blocker boolean;
        BEGIN
            SELECT * INTO content
            FROM object_contents
            WHERE id = COALESCE(NEW.content_id, OLD.content_id)
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'held object content does not exist';
            END IF;

            IF TG_OP = 'INSERT' THEN
                IF content.delete_requested_at IS NOT NULL
                    OR content.state IN ('delete_pending', 'tombstoned') THEN
                    RAISE EXCEPTION 'a hold cannot cross committed delete intent';
                END IF;
                INSERT INTO object_content_audit_events
                    (content_id, event_type)
                VALUES (content.id, 'hold_changed');
                RETURN NEW;
            END IF;

            IF OLD.released_at IS NOT NULL AND NEW.released_at IS NULL THEN
                RAISE EXCEPTION 'an object content hold cannot be reopened';
            END IF;
            IF (
                NEW.id,
                NEW.content_id,
                NEW.kind,
                NEW.reason,
                NEW.expires_at,
                NEW.created_at
            ) IS DISTINCT FROM (
                OLD.id,
                OLD.content_id,
                OLD.kind,
                OLD.reason,
                OLD.expires_at,
                OLD.created_at
            ) THEN
                RAISE EXCEPTION 'object content hold identity is immutable';
            END IF;
            IF NEW.actor_user_id IS DISTINCT FROM OLD.actor_user_id
                AND NOT (
                    OLD.actor_user_id IS NOT NULL
                    AND NEW.actor_user_id IS NULL
                    -- FK-driven SET NULL is nested; direct hold updates are depth 1.
                    AND pg_trigger_depth() > 1
                ) THEN
                RAISE EXCEPTION 'object content hold identity is immutable';
            END IF;

            IF OLD.released_at IS NULL AND NEW.released_at IS NOT NULL
                AND content.state = 'retained'
                AND content.reference_count = 0 THEN
                SELECT
                    COALESCE(content.minimum_retain_until > now(), false)
                    OR EXISTS (
                        SELECT 1 FROM object_content_holds
                        WHERE content_id = content.id
                          AND id <> OLD.id
                          AND released_at IS NULL
                          AND (expires_at IS NULL OR expires_at > now())
                    )
                INTO has_other_blocker;
                IF NOT has_other_blocker THEN
                    UPDATE object_contents
                    SET state = 'delete_pending',
                        next_attempt_at = now(),
                        updated_at = now()
                    WHERE id = content.id;
                END IF;
            END IF;
            IF NEW.released_at IS DISTINCT FROM OLD.released_at THEN
                INSERT INTO object_content_audit_events
                    (content_id, event_type)
                VALUES (content.id, 'hold_changed');
            END IF;
            RETURN NEW;
        END;
        $$
    """)

    op.execute("""
        CREATE FUNCTION object_content_audit_transition() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                INSERT INTO object_content_audit_events
                    (content_id, event_type)
                VALUES (NEW.id, 'prepared');
            ELSE
                IF NEW.state <> OLD.state THEN
                    INSERT INTO object_content_audit_events
                        (content_id, event_type)
                    VALUES (NEW.id, NEW.state);
                END IF;
                IF NEW.reference_count <> OLD.reference_count THEN
                    INSERT INTO object_content_audit_events
                        (content_id, event_type)
                    VALUES (NEW.id, 'reference_changed');
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
    """)


def _create_triggers() -> None:
    op.execute("""
        CREATE TRIGGER object_contents_10_guard_delete
        BEFORE DELETE ON object_contents
        FOR EACH ROW EXECUTE FUNCTION object_content_guard_delete()
    """)
    op.execute("""
        CREATE TRIGGER object_contents_10_guard_update
        BEFORE UPDATE ON object_contents
        FOR EACH ROW EXECUTE FUNCTION object_content_guard_update()
    """)
    op.execute("""
        CREATE TRIGGER object_contents_90_audit_transition
        AFTER INSERT OR UPDATE ON object_contents
        FOR EACH ROW EXECUTE FUNCTION object_content_audit_transition()
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER object_contents_pending_owner_fence
        AFTER INSERT ON object_contents
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION object_content_pending_owner_fence()
    """)
    for table in (
        "file_content_references",
        "info_blob_content_references",
        "icon_content_references",
    ):
        op.execute(f"""
            CREATE TRIGGER {table}_reference_fence
            BEFORE INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION object_content_reference_fence()
        """)
    op.execute("""
        CREATE TRIGGER object_content_holds_delete_fence
        BEFORE DELETE ON object_content_holds
        FOR EACH ROW EXECUTE FUNCTION object_content_hold_guard_delete()
    """)
    op.execute("""
        CREATE TRIGGER object_content_holds_fence
        BEFORE INSERT OR UPDATE ON object_content_holds
        FOR EACH ROW EXECUTE FUNCTION object_content_hold_fence()
    """)


def upgrade() -> None:
    _create_tables()
    _create_indexes()
    _create_trigger_functions()
    _create_triggers()


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS object_content_holds_fence ON object_content_holds"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS object_content_holds_delete_fence "
        "ON object_content_holds"
    )
    for table in (
        "file_content_references",
        "info_blob_content_references",
        "icon_content_references",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_reference_fence ON {table}")
    op.execute(
        "DROP TRIGGER IF EXISTS object_contents_90_audit_transition ON object_contents"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS object_contents_pending_owner_fence ON object_contents"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS object_contents_10_guard_update ON object_contents"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS object_contents_10_guard_delete ON object_contents"
    )
    op.execute("DROP FUNCTION IF EXISTS object_content_audit_transition()")
    op.execute("DROP FUNCTION IF EXISTS object_content_pending_owner_fence()")
    op.execute("DROP FUNCTION IF EXISTS object_content_hold_fence()")
    op.execute("DROP FUNCTION IF EXISTS object_content_hold_guard_delete()")
    op.execute("DROP FUNCTION IF EXISTS object_content_reference_fence()")
    op.execute("DROP FUNCTION IF EXISTS object_content_guard_update()")
    op.execute("DROP FUNCTION IF EXISTS object_content_guard_delete()")

    op.drop_table("object_content_multipart_candidates")
    op.drop_table("object_content_reconciliation_state")
    op.drop_table("object_content_orphan_candidates")
    op.drop_table("object_content_audit_events")
    op.drop_table("icon_content_references")
    op.drop_table("info_blob_content_references")
    op.drop_table("file_content_references")
    op.drop_table("object_content_holds")
    op.drop_table("object_contents")
