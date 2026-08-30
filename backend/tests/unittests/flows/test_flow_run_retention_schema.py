from __future__ import annotations

from sqlalchemy import CheckConstraint

from eneo.database.tables.flow_tables import Flows
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants


def _check_constraint_sql(table: type[object]) -> dict[str, str]:
    sqlalchemy_table = getattr(table, "__table__")
    return {
        constraint.name: str(constraint.sqltext)
        for constraint in sqlalchemy_table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name is not None
    }


def test_each_scope_persists_a_dedicated_complete_flow_policy() -> None:
    assert hasattr(Tenants, "flow_run_history_retention_mode")
    assert hasattr(Tenants, "flow_run_history_retention_days")

    assert hasattr(Spaces, "flow_run_history_retention_mode")
    assert hasattr(Spaces, "flow_run_history_retention_days")
    assert hasattr(Spaces, "data_retention_days")

    assert hasattr(Flows, "flow_run_history_retention_mode")
    assert hasattr(Flows, "flow_run_history_retention_days")
    assert not hasattr(Flows, "data_retention_days")


def test_database_constraints_reject_partial_and_unsupported_policies() -> None:
    expected_constraints = {
        Tenants: (
            "ck_tenants_flow_run_history_retention_complete",
            "ck_tenants_flow_run_history_retention_mode",
        ),
        Spaces: (
            "ck_spaces_flow_run_history_retention_complete",
            "ck_spaces_flow_run_history_retention_mode",
        ),
        Flows: (
            "ck_flows_flow_run_history_retention_complete",
            "ck_flows_flow_run_history_retention_mode",
        ),
    }

    for table, names in expected_constraints.items():
        constraints = _check_constraint_sql(table)
        complete_sql = constraints[names[0]]
        mode_sql = constraints[names[1]]

        assert "flow_run_history_retention_mode IS NULL" in complete_sql
        assert "flow_run_history_retention_days IS NULL" in complete_sql
        assert "flow_run_history_retention_mode IS NOT NULL" in complete_sql
        assert "flow_run_history_retention_days IS NOT NULL" in complete_sql
        assert "'preserve'" in mode_sql
        assert "'review_required'" in mode_sql
        assert "'automatic'" not in mode_sql
