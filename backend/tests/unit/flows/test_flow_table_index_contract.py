"""Index contract for the flows-owned tables (gallring path and principal deletion).

The ORM metadata is the declaration owner; the migration test proves the database
matches it. These checks fail when a flows-owned table gains a foreign key to a
principal, or a retention query loses its supporting index, without an index.
"""

from __future__ import annotations

import inspect

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

import eneo.database.tables as _tables  # noqa: F401  (registers every table)
from eneo.database.tables import flow_tables
from eneo.database.tables.base_class import Base

PRINCIPAL_TABLES = frozenset({"users", "service_principals", "api_keys_v2"})


def _flow_owned_tables() -> list[sa.Table]:
    return sorted(
        {
            cls.__table__
            for _, cls in inspect.getmembers(flow_tables, inspect.isclass)
            if cls.__module__ == flow_tables.__name__
            and issubclass(cls, Base)
            and hasattr(cls, "__table__")
        },
        key=lambda table: table.name,
    )


def _index_named(table: sa.Table, name: str) -> sa.Index:
    matches = [index for index in table.indexes if index.name == name]
    assert len(matches) == 1, f"{table.name} must declare index {name}"
    return matches[0]


def _ddl(index: sa.Index) -> str:
    return str(
        CreateIndex(index).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def _principal_foreign_keys() -> list[tuple[sa.Table, sa.Column]]:
    # foreign_keys is a set: sort, or xdist workers collect different parameter orders.
    return sorted(
        (
            (table, fk.parent)
            for table in _flow_owned_tables()
            for fk in table.foreign_keys
            if fk.column.table.name in PRINCIPAL_TABLES
        ),
        key=lambda pair: (pair[0].name, pair[1].name),
    )


# Indexed by the audit-actor revision (another lane); drop this entry when it lands.
INDEXED_ELSEWHERE = frozenset(
    {
        ("flow_run_audit_outbox", "actor_id"),
        ("flow_run_audit_outbox", "actor_api_key_id"),
    }
)


def _leads_an_index(table: sa.Table, column: sa.Column) -> bool:
    return any(
        index.expressions and index.expressions[0] is column for index in table.indexes
    )


def _guarded_principal_foreign_keys() -> list[tuple[sa.Table, sa.Column]]:
    return [
        (table, column)
        for table, column in _principal_foreign_keys()
        if (table.name, column.name) not in INDEXED_ELSEWHERE
    ]


def test_the_metadata_walk_sees_the_principal_columns_it_guards() -> None:
    names = {(table.name, column.name) for table, column in _principal_foreign_keys()}
    assert {
        ("flow_runs", "principal_user_id"),
        ("flow_runs", "principal_service_id"),
        ("flow_runs", "created_by_api_key_id"),
        ("flow_runtime_uploaded_files", "owner_user_id"),
        ("flow_run_audit_outbox", "actor_api_key_id"),
        ("flow_run_review_checkpoints", "decided_by_service_id"),
        ("flow_transcript_correction_revisions", "edited_by_user_id"),
    } <= names


@pytest.mark.parametrize(
    ("table", "column"),
    _guarded_principal_foreign_keys(),
    ids=lambda value: getattr(value, "name", str(value)),
)
def test_every_principal_foreign_key_leads_an_index(
    table: sa.Table, column: sa.Column
) -> None:
    """Deleting a user, service principal or API key probes each referencing
    column by equality; without a leading-column index that is a table scan per
    deleted principal."""
    assert _leads_an_index(table, column), (
        f"{table.name}.{column.name} has no index leading with it"
    )


def test_exemptions_are_removed_once_the_column_is_indexed() -> None:
    by_name = {
        (table.name, column.name): (table, column)
        for table, column in _principal_foreign_keys()
    }
    for key in sorted(INDEXED_ELSEWHERE):
        table, column = by_name[key]
        assert not _leads_an_index(table, column), (
            f"{key[0]}.{key[1]} is indexed now: remove it from INDEXED_ELSEWHERE"
        )


def test_nullable_principal_indexes_skip_the_null_rows() -> None:
    for table, column in _guarded_principal_foreign_keys():
        if not column.nullable:
            continue
        index = next(index for index in table.indexes if index.expressions[0] is column)
        where = index.dialect_options["postgresql"]["where"]
        assert where is not None, f"{index.name} must be partial"
        assert str(where) == f"{column.name} IS NOT NULL", index.name


def test_resolved_input_foreign_key_check_has_a_provider_call_index() -> None:
    table = flow_tables.FlowProviderCalls.__table__
    index = _index_named(table, "ix_flow_provider_calls_resolved_inputs_attempt_id")
    assert _ddl(index).endswith(
        "(resolved_inputs_attempt_id) WHERE resolved_inputs_attempt_id IS NOT NULL"
    )


def test_abandoned_upload_selection_has_a_created_at_file_id_index() -> None:
    table = flow_tables.FlowRuntimeUploadedFiles.__table__
    index = _index_named(table, "ix_flow_runtime_uploaded_files_created_at_file_id")
    assert _ddl(index).endswith("(created_at, file_id)")
