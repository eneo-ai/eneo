"""add the indexes the Flow run purge and principal deletion need

Revision ID: 202610021030
Revises: 202610021000
Create Date: 2026-10-02 10:30:00.000000

Three query families scan flows-owned history tables without an index:

* run purge deletes resolved-input rows, and the NO ACTION foreign key from
  flow_provider_calls probes resolved_inputs_attempt_id for every one;
* abandoned runtime uploads are selected oldest-first by created_at, file_id;
* deleting a user, service principal or API key probes every referencing column
  on the flows-owned tables (the FK check, or the SET NULL update).

Lock impact: every index is built CONCURRENTLY outside a transaction (the repo's
pattern for large tables, e.g. 202608281200 and 202610021000). That takes a SHARE
UPDATE EXCLUSIVE lock: normal reads and writes continue, but the build conflicts
with VACUUM and some schema changes on the same table. lock_timeout (5 s) bounds
each lock wait, not the build duration. A failed build leaves an INVALID index;
a re-run drops only invalid leftovers and creates the missing indexes, so valid
ones are untouched. Nullable principal columns get
a partial IS NOT NULL index: the equality probe still uses it and the NULL half
of the user/service XOR columns stays out. The downgrade drops them all. No data
changes. flow_run_audit_outbox actor columns are indexed by 202610021000.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610021030"
down_revision: str | None = "202610021000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, nullable principal columns): index ix_<table>_<column>, WHERE <column> IS NOT NULL.
_PRINCIPAL_COLUMNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("flows", ("created_by_user_id", "owner_user_id")),
    ("flow_template_assets", ("created_by_user_id", "updated_by_user_id")),
    ("flow_package_imports", ("created_by_user_id",)),
    ("flow_runtime_uploaded_files", ("owner_user_id", "owner_service_id")),
    (
        "flow_runs",
        ("principal_user_id", "principal_service_id", "created_by_api_key_id"),
    ),
    (
        "flow_run_review_checkpoints",
        (
            "requester_user_id",
            "requester_service_id",
            "decided_by_user_id",
            "decided_by_service_id",
        ),
    ),
    (
        "flow_transcript_corrections",
        ("edited_by_user_id", "edited_by_service_id"),
    ),
    (
        "flow_transcript_correction_revisions",
        ("edited_by_user_id", "edited_by_service_id"),
    ),
    (
        "flow_run_review_checkpoint_edits",
        ("edited_by_user_id", "edited_by_service_id"),
    ),
    ("builder_client_errors", ("user_id",)),
)

# (index name, table, columns or expressions, partial predicate or None)
_QUERY_INDEXES: tuple[tuple[str, str, tuple[str, ...], str | None], ...] = (
    (
        "ix_flow_provider_calls_resolved_inputs_attempt_id",
        "flow_provider_calls",
        ("resolved_inputs_attempt_id",),
        "resolved_inputs_attempt_id IS NOT NULL",
    ),
    (
        "ix_flow_runtime_uploaded_files_created_at_file_id",
        "flow_runtime_uploaded_files",
        ("created_at", "file_id"),
        None,
    ),
)


def _all_indexes() -> list[tuple[str, str, tuple[str, ...], str | None]]:
    principal = [
        (
            f"ix_{table}_{column}",
            table,
            (column,),
            f"{column} IS NOT NULL",
        )
        for table, columns in _PRINCIPAL_COLUMNS
        for column in columns
    ]
    return [*_QUERY_INDEXES, *principal]


def _is_invalid(name: str) -> bool:
    # Offline (`alembic upgrade --sql`) has no connection to inspect: it emits the
    # static IF NOT EXISTS statements and leaves repairing leftovers to an online run.
    if op.get_context().as_sql:
        return False
    valid = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)"
            ),
            {"name": name},
        )
        .scalar()
    )
    return valid is False


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            for name, table, columns, where in _all_indexes():
                # A failed concurrent build leaves an invalid index behind.
                if _is_invalid(name):
                    op.drop_index(name, table_name=table, postgresql_concurrently=True)
                op.create_index(
                    name,
                    table,
                    [sa.literal_column(column) for column in columns],
                    postgresql_where=sa.text(where) if where else None,
                    postgresql_concurrently=True,
                    if_not_exists=True,
                )
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            for name, table, _, _ in _all_indexes():
                op.drop_index(
                    name,
                    table_name=table,
                    if_exists=True,
                    postgresql_concurrently=True,
                )
        finally:
            op.execute("RESET lock_timeout")
