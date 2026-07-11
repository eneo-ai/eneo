"""Enforce tenant identity on Flow file relationships.

The two supporting indexes are built concurrently before transactional
constraint work begins. Attach, add, validate, and handoff use separate
autocommit phases so PostgreSQL releases DDL locks between the bounded table
scans. Named-state guards make an interrupted phase resumable; an invalid or
unexpected index/constraint fails closed for operator inspection instead of
being silently reused.

PostgreSQL renames and takes ownership of the temporary unique index when it is
attached to ``uq_files_id_tenant_id``. Downgrade drops that owned backing index
with the unique constraint; its explicit concurrent drop only cleans an
unattached index left by an interrupted upgrade.

Revision ID: 202607111200_file_tenant_fks
Revises: 202607081035_compose_text
Create Date: 2026-07-11 12:00:00.000000
"""

from __future__ import annotations

from typing import NamedTuple

import sqlalchemy as sa

from alembic import op

revision = "202607111200_file_tenant_fks"
down_revision = "202607081035_compose_text"
branch_labels = None
depends_on = None

_FILES_TENANT_UNIQUE = "uq_files_id_tenant_id"
_FILES_TENANT_UNIQUE_INDEX = "ix_files_id_tenant_id_unique"
_BUILDER_FILE_INDEX = "ix_builder_session_files_file_id"
_RELATIONSHIP_CONSTRAINTS = (
    (
        "flow_template_assets",
        "fk_flow_template_assets_file_tenant",
        "flow_template_assets_file_id_fkey",
        "RESTRICT",
    ),
    (
        "flow_runtime_uploaded_files",
        "fk_flow_runtime_uploaded_files_file_tenant",
        "fk_flow_runtime_uploaded_files_file_id_files",
        "CASCADE",
    ),
    (
        "flow_run_step_result_files",
        "fk_flow_run_step_result_files_file_tenant",
        "fk_flow_run_step_result_files_file_id_files",
        "RESTRICT",
    ),
    (
        "builder_session_files",
        "fk_builder_session_files_file_tenant",
        "builder_session_files_file_id_fkey",
        "CASCADE",
    ),
)


class _IndexState(NamedTuple):
    table: str
    columns: tuple[str, ...]
    access_method: str
    unique: bool
    valid: bool
    ready: bool
    live: bool
    partial: bool
    expression: bool


def _constraint_definition(table: str, constraint: str) -> str | None:
    result = op.get_bind().execute(
        sa.text(
            """
            SELECT pg_get_constraintdef(constraint_row.oid)
            FROM pg_constraint AS constraint_row
            WHERE constraint_row.conrelid = to_regclass(:table_name)
              AND constraint_row.conname = :constraint_name
            """
        ),
        {"table_name": table, "constraint_name": constraint},
    )
    value = result.scalar_one_or_none()
    return str(value) if value is not None else None


def _constraint_is_validated(table: str, constraint: str) -> bool:
    result = op.get_bind().execute(
        sa.text(
            """
            SELECT constraint_row.convalidated
            FROM pg_constraint AS constraint_row
            WHERE constraint_row.conrelid = to_regclass(:table_name)
              AND constraint_row.conname = :constraint_name
            """
        ),
        {"table_name": table, "constraint_name": constraint},
    )
    value = result.scalar_one_or_none()
    if value is None:
        raise RuntimeError(
            f"Cannot continue file-tenant migration: {constraint} is missing "
            f"from {table}."
        )
    return bool(value)


def _index_state(index: str) -> _IndexState | None:
    row = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT
                table_row.relname,
                array_agg(attribute_row.attname ORDER BY index_key.ordinality),
                access_method.amname,
                index_metadata.indisunique,
                index_metadata.indisvalid,
                index_metadata.indisready,
                index_metadata.indislive,
                index_metadata.indpred IS NOT NULL,
                index_metadata.indexprs IS NOT NULL
            FROM pg_class AS index_row
            JOIN pg_index AS index_metadata
              ON index_metadata.indexrelid = index_row.oid
            JOIN pg_am AS access_method
              ON access_method.oid = index_row.relam
            JOIN pg_class AS table_row
              ON table_row.oid = index_metadata.indrelid
            JOIN unnest(index_metadata.indkey)
              WITH ORDINALITY AS index_key(attnum, ordinality)
              ON true
            JOIN pg_attribute AS attribute_row
              ON attribute_row.attrelid = table_row.oid
             AND attribute_row.attnum = index_key.attnum
            WHERE index_row.relnamespace = current_schema()::regnamespace
              AND index_row.relname = :index_name
            GROUP BY
                table_row.relname,
                access_method.amname,
                index_metadata.indisunique,
                index_metadata.indisvalid,
                index_metadata.indisready,
                index_metadata.indislive,
                (index_metadata.indpred IS NOT NULL),
                (index_metadata.indexprs IS NOT NULL)
            """
            ),
            {"index_name": index},
        )
        .one_or_none()
    )
    if row is None:
        return None
    return _IndexState(
        table=str(row[0]),
        columns=tuple(row[1]),
        access_method=str(row[2]),
        unique=bool(row[3]),
        valid=bool(row[4]),
        ready=bool(row[5]),
        live=bool(row[6]),
        partial=bool(row[7]),
        expression=bool(row[8]),
    )


def _require_index_state(
    index: str,
    *,
    table: str,
    columns: tuple[str, ...],
    unique: bool,
) -> None:
    expected = _IndexState(
        table=table,
        columns=columns,
        access_method="btree",
        unique=unique,
        valid=True,
        ready=True,
        live=True,
        partial=False,
        expression=False,
    )
    actual = _index_state(index)
    if actual != expected:
        raise RuntimeError(
            f"Cannot continue file-tenant migration: index {index} has state "
            f"{actual!r}, expected {expected!r}. Inspect pg_index, drop an "
            "invalid or unexpected index concurrently, and rerun."
        )


def _require_constraint_definition(
    table: str,
    constraint: str,
    expected: str,
) -> None:
    actual = _constraint_definition(table, constraint)
    if actual not in {expected, f"{expected} NOT VALID"}:
        raise RuntimeError(
            f"Cannot continue file-tenant migration: constraint {constraint} "
            f"on {table} has definition {actual!r}, expected {expected!r}."
        )


def _mismatched_relationship_count(table: str) -> int:
    result = op.get_bind().execute(
        sa.text(
            f"""
            SELECT count(*)
            FROM {table} AS relationship
            LEFT JOIN files AS file_row ON file_row.id = relationship.file_id
            WHERE file_row.id IS NULL
               OR file_row.tenant_id IS DISTINCT FROM relationship.tenant_id
            """
        )
    )
    return int(result.scalar_one())


def _mismatched_relationship_samples(table: str) -> tuple[str, ...]:
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                f"""
            SELECT
                relationship.file_id::text AS file_id,
                relationship.tenant_id::text AS relationship_tenant_id,
                file_row.tenant_id::text AS file_tenant_id
            FROM {table} AS relationship
            LEFT JOIN files AS file_row ON file_row.id = relationship.file_id
            WHERE file_row.id IS NULL
               OR file_row.tenant_id IS DISTINCT FROM relationship.tenant_id
            ORDER BY relationship.file_id
            LIMIT 5
            """
            )
        )
        .mappings()
    )
    return tuple(
        "file_id={file_id}, relationship_tenant_id={relationship_tenant_id}, "
        "file_tenant_id={file_tenant_id}".format(**row)
        for row in rows
    )


def _assert_existing_relationships_are_tenant_consistent() -> None:
    mismatches: list[str] = []
    for table, _, _, _ in _RELATIONSHIP_CONSTRAINTS:
        mismatch_count = _mismatched_relationship_count(table)
        if mismatch_count == 0:
            continue
        samples = "; ".join(_mismatched_relationship_samples(table))
        relationship_label = "relationship" if mismatch_count == 1 else "relationships"
        mismatches.append(
            f"{mismatch_count} "
            f"tenant-mismatched file {relationship_label} in {table}. "
            f"Samples: {samples}."
        )
    if mismatches:
        details = " ".join(mismatches)
        raise RuntimeError(
            f"Cannot add tenant-scoped file identity: {details} "
            "Repair or delete the mismatched rows, then rerun the upgrade."
        )


def upgrade() -> None:
    _assert_existing_relationships_are_tenant_consistent()

    with op.get_context().autocommit_block():
        parent_constraint = _constraint_definition("files", _FILES_TENANT_UNIQUE)
        if parent_constraint is None:
            if _index_state(_FILES_TENANT_UNIQUE_INDEX) is None:
                op.execute(
                    f"""
                    CREATE UNIQUE INDEX CONCURRENTLY {_FILES_TENANT_UNIQUE_INDEX}
                    ON files (id, tenant_id)
                    """
                )
            _require_index_state(
                _FILES_TENANT_UNIQUE_INDEX,
                table="files",
                columns=("id", "tenant_id"),
                unique=True,
            )
        else:
            _require_constraint_definition(
                "files",
                _FILES_TENANT_UNIQUE,
                "UNIQUE (id, tenant_id)",
            )
            _require_index_state(
                _FILES_TENANT_UNIQUE,
                table="files",
                columns=("id", "tenant_id"),
                unique=True,
            )

        if _index_state(_BUILDER_FILE_INDEX) is None:
            op.execute(
                f"""
                CREATE INDEX CONCURRENTLY {_BUILDER_FILE_INDEX}
                ON builder_session_files (file_id)
                """
            )
        _require_index_state(
            _BUILDER_FILE_INDEX,
            table="builder_session_files",
            columns=("file_id",),
            unique=False,
        )

    with op.get_context().autocommit_block():
        if _constraint_definition("files", _FILES_TENANT_UNIQUE) is None:
            op.execute(
                f"""
                ALTER TABLE files
                ADD CONSTRAINT {_FILES_TENANT_UNIQUE}
                UNIQUE USING INDEX {_FILES_TENANT_UNIQUE_INDEX}
                """
            )
        _require_constraint_definition(
            "files",
            _FILES_TENANT_UNIQUE,
            "UNIQUE (id, tenant_id)",
        )
        _require_index_state(
            _FILES_TENANT_UNIQUE,
            table="files",
            columns=("id", "tenant_id"),
            unique=True,
        )

    with op.get_context().autocommit_block():
        for table, composite_constraint, _, ondelete in _RELATIONSHIP_CONSTRAINTS:
            expected = (
                "FOREIGN KEY (file_id, tenant_id) "
                f"REFERENCES files(id, tenant_id) ON DELETE {ondelete}"
            )
            if _constraint_definition(table, composite_constraint) is None:
                op.execute(
                    f"""
                    ALTER TABLE {table}
                    ADD CONSTRAINT {composite_constraint}
                    FOREIGN KEY (file_id, tenant_id)
                    REFERENCES files (id, tenant_id)
                    ON DELETE {ondelete}
                    NOT VALID
                    """
                )
            _require_constraint_definition(table, composite_constraint, expected)

    with op.get_context().autocommit_block():
        for table, composite_constraint, _, _ in _RELATIONSHIP_CONSTRAINTS:
            if not _constraint_is_validated(table, composite_constraint):
                op.execute(
                    f"ALTER TABLE {table} VALIDATE CONSTRAINT {composite_constraint}"
                )

    for table, composite_constraint, _, _ in _RELATIONSHIP_CONSTRAINTS:
        if not _constraint_is_validated(table, composite_constraint):
            raise RuntimeError(
                f"Cannot remove legacy file identity: {composite_constraint} "
                f"on {table} is not validated."
            )

    with op.get_context().autocommit_block():
        for table, _, legacy_constraint, _ in _RELATIONSHIP_CONSTRAINTS:
            op.execute(
                f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {legacy_constraint}"
            )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for table, _, legacy_constraint, ondelete in _RELATIONSHIP_CONSTRAINTS:
            expected = (
                f"FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE {ondelete}"
            )
            if _constraint_definition(table, legacy_constraint) is None:
                op.execute(
                    f"""
                    ALTER TABLE {table}
                    ADD CONSTRAINT {legacy_constraint}
                    FOREIGN KEY (file_id)
                    REFERENCES files (id)
                    ON DELETE {ondelete}
                    NOT VALID
                    """
                )
            _require_constraint_definition(table, legacy_constraint, expected)

    with op.get_context().autocommit_block():
        for table, _, legacy_constraint, _ in _RELATIONSHIP_CONSTRAINTS:
            if not _constraint_is_validated(table, legacy_constraint):
                op.execute(
                    f"ALTER TABLE {table} VALIDATE CONSTRAINT {legacy_constraint}"
                )

    for table, _, legacy_constraint, _ in _RELATIONSHIP_CONSTRAINTS:
        if not _constraint_is_validated(table, legacy_constraint):
            raise RuntimeError(
                f"Cannot remove composite file identity: {legacy_constraint} "
                f"on {table} is not validated."
            )

    with op.get_context().autocommit_block():
        for table, composite_constraint, _, _ in _RELATIONSHIP_CONSTRAINTS:
            op.execute(
                f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {composite_constraint}"
            )

    with op.get_context().autocommit_block():
        op.execute(
            f"ALTER TABLE files DROP CONSTRAINT IF EXISTS {_FILES_TENANT_UNIQUE}"
        )

    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_BUILDER_FILE_INDEX}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_FILES_TENANT_UNIQUE_INDEX}")
