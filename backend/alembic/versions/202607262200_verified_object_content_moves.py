"""add verified object-content moves

Revision ID: 202607262200
Revises: 202607261700
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607262200"
down_revision: str | None = "202607261700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MOVE_CANDIDATE_INDEX = "ix_object_contents_move_candidates"
_AUDIT_ACTOR_FK = "fk_object_content_audit_events_actor_user_id"
_AUDIT_EVENT_TYPE_CONSTRAINT = "ck_object_content_audit_events_type"
_AUDIT_EVENT_TYPE_WITH_MOVES = "ck_object_content_audit_events_type_with_storage_moves"
_AUDIT_EVENT_TYPE_WITHOUT_MOVES = (
    "ck_object_content_audit_events_type_without_storage_moves"
)


def _create_move_candidate_index() -> None:
    invalid_index = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT NOT catalog.indisvalid
            FROM pg_index AS catalog
            JOIN pg_class AS index_relation
              ON index_relation.oid = catalog.indexrelid
            WHERE index_relation.relname = :index_name
              AND pg_table_is_visible(index_relation.oid)
            """
            ),
            {"index_name": _MOVE_CANDIDATE_INDEX},
        )
        .scalar_one_or_none()
    )
    if invalid_index:
        op.execute(f"DROP INDEX CONCURRENTLY {_MOVE_CANDIDATE_INDEX}")
    op.execute(f"""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS {_MOVE_CANDIDATE_INDEX}
        ON object_contents (storage_kind, created_at, id)
        WHERE state = 'available'
          AND reference_count > 0
          AND delete_requested_at IS NULL
    """)


def _audit_constraint_state(name: str) -> tuple[str, bool] | None:
    row = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT pg_get_constraintdef(oid), convalidated
                FROM pg_constraint
                WHERE conname = :constraint_name
                  AND conrelid = 'object_content_audit_events'::regclass
                """
            ),
            {"constraint_name": name},
        )
        .one_or_none()
    )
    if row is None:
        return None
    return str(row[0]), bool(row[1])


def _validate_constraint_if_needed(name: str) -> None:
    state = _audit_constraint_state(name)
    if state is not None and not state[1]:
        op.execute(
            f"ALTER TABLE object_content_audit_events VALIDATE CONSTRAINT {name}"
        )


def _prepare_audit_upgrade() -> None:
    op.execute(
        "ALTER TABLE object_content_audit_events "
        "ADD COLUMN IF NOT EXISTS actor_user_id UUID"
    )
    if _audit_constraint_state(_AUDIT_ACTOR_FK) is None:
        op.create_foreign_key(
            _AUDIT_ACTOR_FK,
            "object_content_audit_events",
            "users",
            ["actor_user_id"],
            ["id"],
            ondelete="SET NULL",
            postgresql_not_valid=True,
        )
    current = _audit_constraint_state(_AUDIT_EVENT_TYPE_CONSTRAINT)
    if (
        current is not None
        and "storage_moved" not in current[0]
        and _audit_constraint_state(_AUDIT_EVENT_TYPE_WITH_MOVES) is None
    ):
        op.create_check_constraint(
            _AUDIT_EVENT_TYPE_WITH_MOVES,
            "object_content_audit_events",
            "event_type IN ('prepared', 'available', 'retained', 'failed', "
            "'delete_pending', 'tombstoned', 'reference_changed', "
            "'hold_changed', 'storage_moved')",
            postgresql_not_valid=True,
        )
    _validate_constraint_if_needed(_AUDIT_ACTOR_FK)
    _validate_constraint_if_needed(_AUDIT_EVENT_TYPE_WITH_MOVES)


def _adopt_audit_event_type_constraint(staged_name: str) -> None:
    if _audit_constraint_state(staged_name) is None:
        return
    op.drop_constraint(
        _AUDIT_EVENT_TYPE_CONSTRAINT,
        "object_content_audit_events",
        type_="check",
    )
    op.execute(
        "ALTER TABLE object_content_audit_events "
        f"RENAME CONSTRAINT {staged_name} TO {_AUDIT_EVENT_TYPE_CONSTRAINT}"
    )


def _prepare_audit_downgrade() -> None:
    if _audit_constraint_state(_AUDIT_EVENT_TYPE_WITHOUT_MOVES) is None:
        op.create_check_constraint(
            _AUDIT_EVENT_TYPE_WITHOUT_MOVES,
            "object_content_audit_events",
            "event_type IN ('prepared', 'available', 'retained', 'failed', "
            "'delete_pending', 'tombstoned', 'reference_changed', 'hold_changed')",
            postgresql_not_valid=True,
        )
    _validate_constraint_if_needed(_AUDIT_EVENT_TYPE_WITHOUT_MOVES)


def _drop_staged_audit_downgrade() -> None:
    if _audit_constraint_state(_AUDIT_EVENT_TYPE_WITHOUT_MOVES) is not None:
        op.drop_constraint(
            _AUDIT_EVENT_TYPE_WITHOUT_MOVES,
            "object_content_audit_events",
            type_="check",
        )


def _assert_no_move_evidence() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM object_content_moves)
                OR EXISTS (
                    SELECT 1
                    FROM object_content_audit_events
                    WHERE event_type = 'storage_moved'
                ) THEN
                RAISE EXCEPTION
                    'cannot downgrade object-content moves after durable evidence exists'
                    USING ERRCODE = '23514';
            END IF;
        END;
        $$
    """)


def _raise_move_evidence_error() -> None:
    op.execute("""
        DO $$
        BEGIN
            RAISE EXCEPTION
                'cannot downgrade object-content moves after durable evidence exists'
                USING ERRCODE = '23514';
        END;
        $$
    """)


def _replace_guard(*, allow_moves: bool) -> None:
    storage_guard = (
        """
            IF NEW.storage_kind IS DISTINCT FROM OLD.storage_kind
                AND NOT EXISTS (
                    SELECT 1
                    FROM object_content_moves move
                    WHERE move.content_id = NEW.id
                      AND move.target_kind = NEW.storage_kind
                      AND move.state = 'target_verified'
                ) THEN
                RAISE EXCEPTION
                    'object content storage authority requires an active move';
            END IF;
    """
        if allow_moves
        else """
            IF NEW.storage_kind IS DISTINCT FROM OLD.storage_kind THEN
                RAISE EXCEPTION
                    'object content identity and integrity facts are immutable';
            END IF;
    """
    )
    op.execute(f"""
        CREATE OR REPLACE FUNCTION object_content_guard_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (
                NEW.id,
                NEW.tenant_id,
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

            {storage_guard}

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
            RETURN NEW;
        END;
        $$
    """)


def upgrade() -> None:
    # The committed prefix makes interruption rerunnable and releases brief
    # audit-table metadata locks before either populated-table validation.
    with op.get_context().autocommit_block():
        _create_move_candidate_index()
        _prepare_audit_upgrade()

    op.add_column(
        "object_content_deployment_policy",
        sa.Column(
            "moves_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "object_content_moves",
        sa.Column("content_id", sa.UUID(), nullable=False),
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=True),
        sa.Column("verification_chunk_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("verification_chunk_sha256", sa.LargeBinary(), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_detail", sa.String(length=512), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("next_attempt_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("requested_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "target_kind IN ('postgres_inline', 'object_store')",
            name="ck_object_content_moves_target_kind",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'target_verified', 'failed')",
            name="ck_object_content_moves_state",
        ),
        sa.CheckConstraint(
            "(verification_chunk_size_bytes IS NULL) = "
            "(verification_chunk_sha256 IS NULL)",
            name="ck_object_content_moves_verification_pair",
        ),
        sa.CheckConstraint(
            "verification_chunk_size_bytes IS NULL "
            "OR verification_chunk_size_bytes > 0",
            name="ck_object_content_moves_verification_size",
        ),
        sa.CheckConstraint(
            "verification_chunk_sha256 IS NULL OR "
            "(octet_length(verification_chunk_sha256) BETWEEN 32 AND 320000 "
            "AND octet_length(verification_chunk_sha256) % 32 = 0)",
            name="ck_object_content_moves_verification_sha256",
        ),
        sa.CheckConstraint(
            "target_kind = 'object_store' OR "
            "(object_key IS NULL AND verification_chunk_size_bytes IS NULL)",
            name="ck_object_content_moves_object_target",
        ),
        sa.CheckConstraint(
            "state <> 'target_verified' OR target_kind = 'postgres_inline' OR "
            "(object_key IS NOT NULL AND verification_chunk_size_bytes IS NOT NULL)",
            name="ck_object_content_moves_verified_target",
        ),
        sa.CheckConstraint(
            "state <> 'failed' OR failure_code IS NOT NULL",
            name="ck_object_content_moves_failed_code",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code IN ("
            "'store_unavailable', 'target_too_large', 'source_missing', "
            "'source_corrupt', 'target_corrupt', 'content_ineligible')",
            name="ck_object_content_moves_failure_code",
        ),
        sa.CheckConstraint(
            "failure_detail IS NULL OR char_length(failure_detail) <= 512",
            name="ck_object_content_moves_failure_detail",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_object_content_moves_attempt_count",
        ),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["object_contents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("content_id"),
        sa.UniqueConstraint("object_key", name="uq_object_content_moves_object_key"),
    )
    op.create_index(
        "ix_object_content_moves_due",
        "object_content_moves",
        ["state", "next_attempt_at", "updated_at", "content_id"],
    )
    op.create_index(
        "ix_object_content_moves_target_state",
        "object_content_moves",
        ["target_kind", "state"],
    )
    _adopt_audit_event_type_constraint(_AUDIT_EVENT_TYPE_WITH_MOVES)
    _replace_guard(allow_moves=True)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        try:
            _assert_no_move_evidence()
            _prepare_audit_downgrade()
        except Exception:
            _drop_staged_audit_downgrade()
            raise

    op.execute("LOCK TABLE object_content_moves IN ACCESS EXCLUSIVE MODE")
    move_evidence_exists = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT EXISTS (SELECT 1 FROM object_content_moves)
                OR EXISTS (
                    SELECT 1
                    FROM object_content_audit_events
                    WHERE event_type = 'storage_moved'
                )
            """
            )
        )
        .scalar_one()
    )
    if move_evidence_exists:
        with op.get_context().autocommit_block():
            _drop_staged_audit_downgrade()
        _raise_move_evidence_error()

    op.drop_index(_MOVE_CANDIDATE_INDEX, table_name="object_contents")
    _replace_guard(allow_moves=False)
    _adopt_audit_event_type_constraint(_AUDIT_EVENT_TYPE_WITHOUT_MOVES)
    op.drop_constraint(
        _AUDIT_ACTOR_FK,
        "object_content_audit_events",
        type_="foreignkey",
    )
    op.drop_column("object_content_audit_events", "actor_user_id")
    op.drop_table("object_content_moves")
    op.drop_column("object_content_deployment_policy", "moves_paused")
