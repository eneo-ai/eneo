"""split object-content control and byte backends

Revision ID: 202607231200
Revises: 202607221700
Create Date: 2026-07-23 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607231200"
down_revision: str | None = "202607221700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_backend_tables() -> None:
    op.create_table(
        "inline_content_payloads",
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "storage_kind",
            sa.String(length=32),
            server_default="postgres_inline",
            nullable=False,
        ),
        sa.Column("payload", postgresql.BYTEA(), nullable=False),
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
            "storage_kind = 'postgres_inline'",
            name="ck_inline_content_payloads_storage_kind",
        ),
        sa.ForeignKeyConstraint(
            ["content_id", "storage_kind"],
            ["object_contents.id", "object_contents.storage_kind"],
            name="fk_inline_content_payloads_content_kind",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("content_id", name="pk_inline_content_payloads"),
    )
    op.create_table(
        "object_store_objects",
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "storage_kind",
            sa.String(length=32),
            server_default="object_store",
            nullable=False,
        ),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("remote_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("multipart_upload_id", sa.Text(), nullable=True),
        sa.Column("multipart_initiated_at", sa.DateTime(timezone=True), nullable=True),
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
            "storage_kind = 'object_store'",
            name="ck_object_store_objects_storage_kind",
        ),
        sa.CheckConstraint(
            "(multipart_upload_id IS NULL) = (multipart_initiated_at IS NULL)",
            name="ck_object_store_objects_multipart_pair",
        ),
        sa.CheckConstraint(
            "multipart_upload_id IS NULL OR char_length(multipart_upload_id) <= 1024",
            name="ck_object_store_objects_multipart_upload_id_length",
        ),
        sa.ForeignKeyConstraint(
            ["content_id", "storage_kind"],
            ["object_contents.id", "object_contents.storage_kind"],
            name="fk_object_store_objects_content_kind",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("content_id", name="pk_object_store_objects"),
        sa.UniqueConstraint(
            "object_key",
            name="uq_object_store_objects_object_key",
        ),
    )
    op.create_index(
        "ix_object_store_objects_remote_inventory",
        "object_store_objects",
        ["remote_observed_at", "content_id"],
        unique=False,
    )


def _replace_guard_update_for_split_schema() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION object_content_guard_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (
                NEW.id,
                NEW.tenant_id,
                NEW.storage_kind,
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
                OLD.storage_kind,
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

            IF OLD.payload_deleted_at IS NOT NULL
                AND NEW.payload_deleted_at
                    IS DISTINCT FROM OLD.payload_deleted_at THEN
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
                RAISE EXCEPTION
                    'minimum retention cannot change after physical delete intent';
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


def _replace_reference_insert_fence(*, initial_reference_condition: str) -> None:
    op.execute(f"""
        CREATE OR REPLACE FUNCTION object_content_reference_insert_fence()
        RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            content object_contents%ROWTYPE;
            expected_access_class text;
            owner_missing boolean;
            reference_delta integer;
            target_content_id uuid;
            tenant_mismatch boolean;
        BEGIN
            expected_access_class := CASE
                WHEN TG_TABLE_NAME = 'icon_content_references'
                    THEN 'public_immutable'
                ELSE 'private_resource'
            END;

            FOR target_content_id IN
                SELECT DISTINCT content_id
                FROM new_references
                ORDER BY content_id
            LOOP
                SELECT * INTO content
                FROM object_contents
                WHERE id = target_content_id
                FOR UPDATE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'referenced object content does not exist';
                END IF;

                IF TG_TABLE_NAME = 'file_content_references' THEN
                    SELECT
                        count(*)::integer,
                        bool_or(owner.id IS NULL),
                        bool_or(owner.tenant_id IS DISTINCT FROM content.tenant_id)
                    INTO reference_delta, owner_missing, tenant_mismatch
                    FROM new_references AS reference
                    LEFT JOIN files AS owner ON owner.id = reference.file_id
                    WHERE reference.content_id = target_content_id;
                ELSIF TG_TABLE_NAME = 'info_blob_content_references' THEN
                    SELECT
                        count(*)::integer,
                        bool_or(owner.id IS NULL),
                        bool_or(owner.tenant_id IS DISTINCT FROM content.tenant_id)
                    INTO reference_delta, owner_missing, tenant_mismatch
                    FROM new_references AS reference
                    LEFT JOIN info_blobs AS owner
                        ON owner.id = reference.info_blob_id
                    WHERE reference.content_id = target_content_id;
                ELSE
                    SELECT
                        count(*)::integer,
                        bool_or(owner.id IS NULL),
                        bool_or(owner.tenant_id IS DISTINCT FROM content.tenant_id)
                    INTO reference_delta, owner_missing, tenant_mismatch
                    FROM new_references AS reference
                    LEFT JOIN icons AS owner ON owner.id = reference.icon_id
                    WHERE reference.content_id = target_content_id;
                END IF;

                IF owner_missing THEN
                    RAISE EXCEPTION
                        'object content reference owner does not exist';
                END IF;
                IF tenant_mismatch THEN
                    RAISE EXCEPTION 'object content reference tenant mismatch';
                END IF;
                IF content.access_class <> expected_access_class THEN
                    RAISE EXCEPTION 'object content access class mismatch';
                END IF;
                IF content.delete_requested_at IS NOT NULL THEN
                    RAISE EXCEPTION
                        'object content with delete intent cannot be attached';
                END IF;
                IF {initial_reference_condition} THEN
                    IF content.reference_count <> 0
                        OR reference_delta <> 1
                        OR content.creation_transaction_id <> txid_current()
                    THEN
                        RAISE EXCEPTION
                            'new object content may only receive one first '
                            'reference in its creation transaction';
                    END IF;
                ELSIF content.state <> 'available' THEN
                    RAISE EXCEPTION
                        'only available object content can receive a later reference';
                END IF;

                UPDATE object_contents
                SET reference_count = reference_count + reference_delta,
                    reference_audited_at = NULL,
                    updated_at = now()
                WHERE id = content.id;
            END LOOP;
            RETURN NULL;
        END;
        $$
    """)


def _replace_creation_fences_for_split_schema() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION object_content_pending_owner_fence()
        RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT (
                (NEW.storage_kind = 'postgres_inline' AND NEW.state = 'available')
                OR (NEW.storage_kind = 'object_store' AND NEW.state = 'pending')
            ) THEN
                RAISE EXCEPTION
                    'object content has an invalid initial storage state'
                    USING ERRCODE = '23514';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM object_contents content
                WHERE content.id = NEW.id
                  AND (
                      content.state = 'pending'
                      OR (
                          content.storage_kind = 'postgres_inline'
                          AND content.state = 'available'
                      )
                  )
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
                RAISE EXCEPTION
                    'new object content requires an initial owner'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    _replace_reference_insert_fence(
        initial_reference_condition=(
            "content.state = 'pending' OR ("
            "content.storage_kind = 'postgres_inline' "
            "AND content.state = 'available' "
            "AND content.creation_transaction_id = txid_current())"
        )
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION object_content_audit_transition()
        RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                INSERT INTO object_content_audit_events
                    (content_id, event_type)
                VALUES (NEW.id, 'prepared');
                IF NEW.state = 'available' THEN
                    INSERT INTO object_content_audit_events
                        (content_id, event_type)
                    VALUES (NEW.id, 'available');
                END IF;
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


def _create_backend_fences() -> None:
    op.execute("""
        CREATE FUNCTION object_content_storage_owner_fence() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            content object_contents%ROWTYPE;
            inline_count integer;
            object_store_count integer;
            payload_size bigint;
            target_content_id uuid;
        BEGIN
            IF TG_TABLE_NAME = 'object_contents' THEN
                target_content_id := NEW.id;
            ELSIF TG_OP = 'DELETE' THEN
                target_content_id := OLD.content_id;
            ELSE
                target_content_id := NEW.content_id;
            END IF;

            SELECT * INTO content
            FROM object_contents
            WHERE id = target_content_id;
            IF NOT FOUND THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END IF;

            SELECT count(*)::integer, max(octet_length(payload))
            INTO inline_count, payload_size
            FROM inline_content_payloads
            WHERE content_id = target_content_id;

            SELECT count(*)::integer INTO object_store_count
            FROM object_store_objects
            WHERE content_id = target_content_id;

            IF content.storage_kind = 'postgres_inline' THEN
                IF content.state = 'tombstoned' THEN
                    IF inline_count <> 0 OR object_store_count <> 0 THEN
                        RAISE EXCEPTION
                            'inline tombstone must not retain a byte backend';
                    END IF;
                ELSIF inline_count <> 1 OR object_store_count <> 0 THEN
                    RAISE EXCEPTION
                        'object content requires exactly one matching byte backend';
                ELSIF payload_size IS DISTINCT FROM content.size_bytes THEN
                    RAISE EXCEPTION
                        'inline payload size does not match object content';
                END IF;
            ELSIF content.storage_kind = 'object_store' THEN
                IF inline_count <> 0 OR object_store_count <> 1 THEN
                    RAISE EXCEPTION
                        'object content requires exactly one matching byte backend';
                END IF;
            ELSE
                RAISE EXCEPTION 'object content has an unsupported storage kind';
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE FUNCTION inline_content_payload_identity_fence() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (NEW.content_id, NEW.storage_kind, NEW.payload, NEW.created_at)
                IS DISTINCT FROM
                (OLD.content_id, OLD.storage_kind, OLD.payload, OLD.created_at) THEN
                RAISE EXCEPTION 'inline content payload is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE FUNCTION object_store_object_identity_fence() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (NEW.content_id, NEW.storage_kind, NEW.object_key, NEW.created_at)
                IS DISTINCT FROM
                (OLD.content_id, OLD.storage_kind, OLD.object_key, OLD.created_at) THEN
                RAISE EXCEPTION 'object-store descriptor identity is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER object_contents_storage_owner_fence
        AFTER INSERT OR UPDATE ON object_contents
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION object_content_storage_owner_fence()
    """)
    for table in ("inline_content_payloads", "object_store_objects"):
        op.execute(f"""
            CREATE CONSTRAINT TRIGGER {table}_storage_owner_fence
            AFTER INSERT OR UPDATE OR DELETE ON {table}
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION object_content_storage_owner_fence()
        """)
    op.execute("""
        CREATE TRIGGER inline_content_payloads_identity_fence
        BEFORE UPDATE ON inline_content_payloads
        FOR EACH ROW EXECUTE FUNCTION inline_content_payload_identity_fence()
    """)
    op.execute("""
        CREATE TRIGGER object_store_objects_identity_fence
        BEFORE UPDATE ON object_store_objects
        FOR EACH ROW EXECUTE FUNCTION object_store_object_identity_fence()
    """)


def upgrade() -> None:
    op.add_column(
        "object_contents",
        sa.Column("storage_kind", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "object_contents",
        sa.Column("payload_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_object_contents_id_storage_kind",
        "object_contents",
        ["id", "storage_kind"],
    )
    _create_backend_tables()

    op.execute(
        "UPDATE object_contents "
        "SET storage_kind = 'object_store', "
        "payload_deleted_at = remote_deleted_at"
    )
    op.execute("""
        INSERT INTO object_store_objects (
            content_id,
            storage_kind,
            object_key,
            remote_observed_at,
            multipart_upload_id,
            multipart_initiated_at,
            created_at,
            updated_at
        )
        SELECT
            id,
            'object_store',
            object_key,
            remote_observed_at,
            multipart_upload_id,
            multipart_initiated_at,
            created_at,
            updated_at
        FROM object_contents
    """)
    op.execute("""
        DO $$
        DECLARE
            content_count bigint;
            descriptor_count bigint;
        BEGIN
            SELECT count(*) INTO content_count FROM object_contents;
            SELECT count(*) INTO descriptor_count FROM object_store_objects;
            IF content_count <> descriptor_count
                OR EXISTS (
                    SELECT 1
                    FROM object_contents content
                    LEFT JOIN object_store_objects descriptor
                        ON descriptor.content_id = content.id
                    WHERE content.storage_kind <> 'object_store'
                       OR descriptor.content_id IS NULL
                       OR descriptor.object_key IS DISTINCT FROM content.object_key
                       OR descriptor.remote_observed_at
                            IS DISTINCT FROM content.remote_observed_at
                       OR descriptor.multipart_upload_id
                            IS DISTINCT FROM content.multipart_upload_id
                       OR descriptor.multipart_initiated_at
                            IS DISTINCT FROM content.multipart_initiated_at
                       OR content.payload_deleted_at
                            IS DISTINCT FROM content.remote_deleted_at
                )
            THEN
                RAISE EXCEPTION
                    'object-content backend split verification failed';
            END IF;
        END;
        $$
    """)
    op.alter_column("object_contents", "storage_kind", nullable=False)

    op.create_index(
        "ix_object_contents_object_store_state",
        "object_contents",
        ["state"],
        unique=False,
        postgresql_where=sa.text("storage_kind = 'object_store'"),
    )
    op.drop_index("ix_object_contents_remote_inventory", table_name="object_contents")
    op.drop_constraint(
        "ck_object_contents_remote_deleted_at",
        "object_contents",
        type_="check",
    )
    op.drop_constraint(
        "ck_object_contents_multipart_pair",
        "object_contents",
        type_="check",
    )
    op.drop_constraint(
        "ck_object_contents_multipart_upload_id_length",
        "object_contents",
        type_="check",
    )
    op.drop_constraint(
        "ck_object_contents_failure_code_value",
        "object_contents",
        type_="check",
    )
    op.drop_constraint(
        "uq_object_contents_object_key",
        "object_contents",
        type_="unique",
    )
    op.execute("""
        UPDATE object_contents
        SET failure_code = CASE failure_code
            WHEN 'remote_missing' THEN 'backend_missing'
            WHEN 'remote_corrupt' THEN 'backend_corrupt'
            ELSE failure_code
        END
    """)
    op.create_check_constraint(
        "ck_object_contents_storage_kind",
        "object_contents",
        "storage_kind IN ('postgres_inline', 'object_store')",
    )
    op.create_check_constraint(
        "ck_object_contents_inline_state",
        "object_contents",
        "storage_kind <> 'postgres_inline' OR state <> 'pending'",
    )
    op.create_check_constraint(
        "ck_object_contents_payload_deleted_at",
        "object_contents",
        "(state = 'tombstoned') = (payload_deleted_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_object_contents_failure_code_value",
        "object_contents",
        "failure_code IS NULL OR failure_code IN ("
        "'owner_detached', 'upload_retryable', 'upload_rejected', "
        "'verification_mismatch', 'backend_missing', 'backend_corrupt', "
        "'reference_drift', 'delete_retryable')",
    )

    _replace_guard_update_for_split_schema()
    op.drop_column("object_contents", "multipart_initiated_at")
    op.drop_column("object_contents", "multipart_upload_id")
    op.drop_column("object_contents", "remote_observed_at")
    op.drop_column("object_contents", "remote_deleted_at")
    op.drop_column("object_contents", "object_key")
    _replace_creation_fences_for_split_schema()
    _create_backend_fences()


def _replace_creation_fences_for_legacy_schema() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION object_content_pending_owner_fence()
        RETURNS trigger
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
    _replace_reference_insert_fence(
        initial_reference_condition="content.state = 'pending'"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION object_content_audit_transition()
        RETURNS trigger
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


def _replace_guard_update_for_legacy_schema() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION object_content_guard_update() RETURNS trigger
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
                AND NEW.remote_deleted_at
                    IS DISTINCT FROM OLD.remote_deleted_at THEN
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
                RAISE EXCEPTION
                    'minimum retention cannot change after physical delete intent';
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


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM object_contents
                WHERE storage_kind = 'postgres_inline'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade object-content schema while inline content exists';
            END IF;
        END;
        $$
    """)

    op.drop_index(
        "ix_object_contents_object_store_state",
        table_name="object_contents",
    )
    op.execute(
        "DROP TRIGGER IF EXISTS "
        "inline_content_payloads_identity_fence ON inline_content_payloads"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS "
        "object_store_objects_identity_fence ON object_store_objects"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS "
        "inline_content_payloads_storage_owner_fence ON inline_content_payloads"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS "
        "object_store_objects_storage_owner_fence ON object_store_objects"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS object_contents_storage_owner_fence ON object_contents"
    )
    op.execute("DROP FUNCTION IF EXISTS inline_content_payload_identity_fence()")
    op.execute("DROP FUNCTION IF EXISTS object_store_object_identity_fence()")
    op.execute("DROP FUNCTION IF EXISTS object_content_storage_owner_fence()")

    op.add_column(
        "object_contents",
        sa.Column("object_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "object_contents",
        sa.Column("remote_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "object_contents",
        sa.Column("remote_observed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "object_contents",
        sa.Column("multipart_upload_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "object_contents",
        sa.Column(
            "multipart_initiated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute("""
        UPDATE object_contents content
        SET object_key = descriptor.object_key,
            remote_deleted_at = content.payload_deleted_at,
            remote_observed_at = descriptor.remote_observed_at,
            multipart_upload_id = descriptor.multipart_upload_id,
            multipart_initiated_at = descriptor.multipart_initiated_at
        FROM object_store_objects descriptor
        WHERE descriptor.content_id = content.id
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM object_contents content
                LEFT JOIN object_store_objects descriptor
                    ON descriptor.content_id = content.id
                WHERE content.storage_kind <> 'object_store'
                   OR descriptor.content_id IS NULL
                   OR content.object_key IS DISTINCT FROM descriptor.object_key
                   OR content.remote_observed_at
                        IS DISTINCT FROM descriptor.remote_observed_at
                   OR content.multipart_upload_id
                        IS DISTINCT FROM descriptor.multipart_upload_id
                   OR content.multipart_initiated_at
                        IS DISTINCT FROM descriptor.multipart_initiated_at
                   OR content.remote_deleted_at
                        IS DISTINCT FROM content.payload_deleted_at
            ) THEN
                RAISE EXCEPTION
                    'object-content legacy join verification failed';
            END IF;
        END;
        $$
    """)
    op.alter_column("object_contents", "object_key", nullable=False)

    op.drop_constraint(
        "ck_object_contents_failure_code_value",
        "object_contents",
        type_="check",
    )
    op.execute("""
        UPDATE object_contents
        SET failure_code = CASE failure_code
            WHEN 'backend_missing' THEN 'remote_missing'
            WHEN 'backend_corrupt' THEN 'remote_corrupt'
            ELSE failure_code
        END
    """)
    op.create_check_constraint(
        "ck_object_contents_remote_deleted_at",
        "object_contents",
        "state <> 'tombstoned' OR remote_deleted_at IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_object_contents_failure_code_value",
        "object_contents",
        "failure_code IS NULL OR failure_code IN ("
        "'owner_detached', 'upload_retryable', 'upload_rejected', "
        "'verification_mismatch', 'remote_missing', 'remote_corrupt', "
        "'reference_drift', 'delete_retryable')",
    )
    op.create_check_constraint(
        "ck_object_contents_multipart_pair",
        "object_contents",
        "(multipart_upload_id IS NULL) = (multipart_initiated_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_object_contents_multipart_upload_id_length",
        "object_contents",
        "multipart_upload_id IS NULL OR char_length(multipart_upload_id) <= 1024",
    )
    op.create_unique_constraint(
        "uq_object_contents_object_key",
        "object_contents",
        ["object_key"],
    )
    op.create_index(
        "ix_object_contents_remote_inventory",
        "object_contents",
        ["state", "remote_observed_at", "available_at"],
        unique=False,
    )

    _replace_guard_update_for_legacy_schema()
    _replace_creation_fences_for_legacy_schema()
    op.drop_index(
        "ix_object_store_objects_remote_inventory",
        table_name="object_store_objects",
    )
    op.drop_table("inline_content_payloads")
    op.drop_table("object_store_objects")
    op.drop_constraint(
        "ck_object_contents_payload_deleted_at",
        "object_contents",
        type_="check",
    )
    op.drop_constraint(
        "ck_object_contents_storage_kind",
        "object_contents",
        type_="check",
    )
    op.drop_constraint(
        "ck_object_contents_inline_state",
        "object_contents",
        type_="check",
    )
    op.drop_constraint(
        "uq_object_contents_id_storage_kind",
        "object_contents",
        type_="unique",
    )
    op.drop_column("object_contents", "payload_deleted_at")
    op.drop_column("object_contents", "storage_kind")
