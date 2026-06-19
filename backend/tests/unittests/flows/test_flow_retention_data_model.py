from __future__ import annotations

from pathlib import Path
from runpy import run_path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from intric.database.tables.flow_classification_retention_policy_table import (
    FlowClassificationRetentionPolicies,
)
from intric.database.tables.flow_tables import FlowRuns, Flows
from intric.database.tables.security_classifications_table import SecurityClassification
from intric.database.tables.spaces_table import Spaces
from intric.flows.enums import TERMINAL_FLOW_RUN_STATUS_VALUES

FLOW_RETENTION_CONSTRAINT_NAME = "ck_flows_data_retention_days_range"
SPACE_RETENTION_CONSTRAINT_NAME = "ck_spaces_data_retention_days_range"
CLASSIFICATION_RETENTION_CONSTRAINT_NAME = (
    "ck_flow_classification_retention_policy_days_range"
)
CLASSIFICATION_RETENTION_POLICY_TABLE_NAME = "flow_classification_retention_policies"
FLOW_RUN_RETENTION_ANCHOR_INDEX_NAME = "ix_flow_runs_terminal_retention_anchor"


def _check_constraint_sql(table: object, constraint_name: str) -> str:
    for constraint in table.__table__.constraints:
        if (
            isinstance(constraint, CheckConstraint)
            and constraint.name == constraint_name
        ):
            return str(constraint.sqltext)
    raise AssertionError(f"Check constraint {constraint_name} was not found.")


def _index_by_name(table: object, index_name: str) -> Index:
    for index in table.__table__.indexes:
        if index.name == index_name:
            return index
    raise AssertionError(f"Index {index_name} was not found.")


def _unique_constraint_by_name(table: object, constraint_name: str) -> UniqueConstraint:
    for constraint in table.__table__.constraints:
        if (
            isinstance(constraint, UniqueConstraint)
            and constraint.name == constraint_name
        ):
            return constraint
    raise AssertionError(f"Unique constraint {constraint_name} was not found.")


def _foreign_key_constraint_by_name(
    table: object, constraint_name: str
) -> ForeignKeyConstraint:
    for constraint in table.__table__.constraints:
        if (
            isinstance(constraint, ForeignKeyConstraint)
            and constraint.name == constraint_name
        ):
            return constraint
    raise AssertionError(f"Foreign key constraint {constraint_name} was not found.")


def test_flows_data_retention_days_has_public_range_constraint() -> None:
    constraint_sql = _check_constraint_sql(Flows, FLOW_RETENTION_CONSTRAINT_NAME)

    assert "data_retention_days IS NULL" in constraint_sql
    assert "data_retention_days >= 1" in constraint_sql
    assert "data_retention_days <= 2555" in constraint_sql


def test_spaces_data_retention_days_metadata_matches_existing_range_constraint() -> (
    None
):
    constraint_sql = _check_constraint_sql(Spaces, SPACE_RETENTION_CONSTRAINT_NAME)

    assert "data_retention_days IS NULL" in constraint_sql
    assert "data_retention_days >= 1" in constraint_sql
    assert "data_retention_days <= 2555" in constraint_sql


def test_classification_retention_policy_table_has_tenant_paired_contract() -> None:
    table = FlowClassificationRetentionPolicies.__table__

    assert table.name == CLASSIFICATION_RETENTION_POLICY_TABLE_NAME
    assert [column.name for column in table.primary_key.columns] == [
        "tenant_id",
        "security_classification_id",
    ]

    constraint_sql = _check_constraint_sql(
        FlowClassificationRetentionPolicies,
        CLASSIFICATION_RETENTION_CONSTRAINT_NAME,
    )
    assert "data_retention_days >= 1" in constraint_sql
    assert "data_retention_days <= 2555" in constraint_sql

    composite_fk = _foreign_key_constraint_by_name(
        FlowClassificationRetentionPolicies,
        "fk_flow_classification_retention_policies_classification_tenant",
    )
    assert [element.parent.name for element in composite_fk.elements] == [
        "security_classification_id",
        "tenant_id",
    ]
    assert [element.target_fullname for element in composite_fk.elements] == [
        "security_classifications.id",
        "security_classifications.tenant_id",
    ]
    assert composite_fk.ondelete == "CASCADE"


def test_security_classifications_has_tenant_pair_unique_constraint() -> None:
    constraint = _unique_constraint_by_name(
        SecurityClassification,
        "uq_security_classifications_id_tenant_id",
    )

    assert [column.name for column in constraint.columns] == ["id", "tenant_id"]


def test_flow_runs_have_terminal_retention_anchor_index() -> None:
    index = _index_by_name(FlowRuns, FLOW_RUN_RETENTION_ANCHOR_INDEX_NAME)

    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))

    assert (
        "CREATE INDEX ix_flow_runs_terminal_retention_anchor ON flow_runs "
        "(coalesce(finished_at, created_at), id)" in ddl
    )
    assert "INCLUDE (flow_id)" in ddl
    assert "WHERE status IN ('completed', 'failed', 'cancelled')" in ddl
    assert TERMINAL_FLOW_RUN_STATUS_VALUES == ("completed", "failed", "cancelled")


def test_flow_retention_range_migration_matches_table_constraint() -> None:
    migration_path = (
        Path(__file__).parents[3]
        / "alembic"
        / "versions"
        / "20260610_flow_retention_window_range.py"
    )
    migration = run_path(str(migration_path))

    assert migration["revision"] == "20260610_flow_retention_range"
    assert migration["_CONSTRAINT_NAME"] == FLOW_RETENTION_CONSTRAINT_NAME
    assert migration["_MIN_RETENTION_DAYS"] == 1
    assert migration["_MAX_RETENTION_DAYS"] == 2555
    assert migration["_CONSTRAINT_SQL"] == (
        "data_retention_days IS NULL OR "
        "(data_retention_days >= 1 AND data_retention_days <= 2555)"
    )


def test_flow_run_retention_anchor_index_migration_matches_metadata() -> None:
    migration_path = (
        Path(__file__).parents[3]
        / "alembic"
        / "versions"
        / "20260610_flow_run_retention_anchor_index.py"
    )
    migration = run_path(str(migration_path))
    migration_source = migration_path.read_text()

    assert migration["revision"] == "20260610_flow_retention_anchor"
    assert migration["_INDEX_NAME"] == FLOW_RUN_RETENTION_ANCHOR_INDEX_NAME
    assert migration["_INDEX_PREDICATE_SQL"] == (
        "status IN ('completed', 'failed', 'cancelled')"
    )
    assert migration["_TERMINAL_FLOW_RUN_STATUS_VALUES"] == (
        "completed",
        "failed",
        "cancelled",
    )
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS" in migration_source
    assert "INCLUDE (flow_id)" in migration_source
    assert "DROP INDEX CONCURRENTLY IF EXISTS" in migration_source


def test_classification_retention_policy_migration_matches_metadata() -> None:
    migration_path = (
        Path(__file__).parents[3]
        / "alembic"
        / "versions"
        / "20260611_flow_classification_retention_policy.py"
    )
    migration = run_path(str(migration_path))

    assert migration["revision"] == "20260611_flow_class_retention"
    assert migration["_POLICY_TABLE"] == CLASSIFICATION_RETENTION_POLICY_TABLE_NAME
    assert migration["_SECURITY_CLASSIFICATIONS_TENANT_UNIQUE"] == (
        "uq_security_classifications_id_tenant_id"
    )
    assert migration["_SECURITY_CLASSIFICATIONS_TENANT_UNIQUE_INDEX"] == (
        "ix_security_classifications_id_tenant_id_unique"
    )
    assert migration["_POLICY_DAYS_CHECK"] == (CLASSIFICATION_RETENTION_CONSTRAINT_NAME)
    migration_source = migration_path.read_text()
    assert "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS" in migration_source
    assert "UNIQUE USING INDEX" in migration_source
    assert "DROP INDEX CONCURRENTLY IF EXISTS" in migration_source
