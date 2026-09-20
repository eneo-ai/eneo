from __future__ import annotations

import ast
import runpy
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from eneo.database.tables.flow_tables import FlowProviderCalls

_ALEMBIC_VERSION_NUM_LIMIT = 32


def _accepted_job_migration():
    return runpy.run_path(
        str(
            Path(__file__).parents[2]
            / "alembic"
            / "versions"
            / "202609201100_provider_call_accepted_job.py"
        )
    )


def test_accepted_job_migration_upgrade_matches_model(monkeypatch):
    migration = _accepted_job_migration()
    operations = MagicMock()
    monkeypatch.setattr(
        migration["upgrade"].__globals__["op"], "execute", operations.execute
    )
    monkeypatch.setattr(
        migration["upgrade"].__globals__["op"],
        "drop_constraint",
        operations.drop_constraint,
    )
    monkeypatch.setattr(
        migration["upgrade"].__globals__["op"], "get_context", operations.get_context
    )
    migration["upgrade"]()
    sql = [str(call.args[0]) for call in operations.execute.call_args_list]
    constraint = next(
        item
        for item in FlowProviderCalls.__table__.constraints
        if item.name == "ck_flow_provider_calls_lifecycle_shape"
    )
    assert sql == [
        "SET LOCAL lock_timeout = '5s'",
        f"ALTER TABLE flow_provider_calls ADD CONSTRAINT ck_flow_provider_calls_lifecycle_shape CHECK ({constraint.sqltext}) NOT VALID",
        "ALTER TABLE flow_provider_calls VALIDATE CONSTRAINT ck_flow_provider_calls_lifecycle_shape",
    ]
    operations.get_context.return_value.autocommit_block.assert_called_once()


@pytest.mark.parametrize("retained", [0, 2])
def test_accepted_job_migration_downgrade_preserves_evidence(monkeypatch, retained):
    migration = _accepted_job_migration()
    operations = MagicMock()
    operations.get_bind.return_value.execute.return_value.scalar_one.return_value = (
        retained
    )
    for name in ("execute", "drop_constraint", "get_context", "get_bind"):
        monkeypatch.setattr(
            migration["downgrade"].__globals__["op"], name, getattr(operations, name)
        )
    if retained:
        with pytest.raises(RuntimeError, match="Refusing to downgrade"):
            migration["downgrade"]()
        operations.drop_constraint.assert_not_called()
    else:
        migration["downgrade"]()
        old = runpy.run_path(
            str(
                Path(__file__).parents[2]
                / "alembic"
                / "versions"
                / "202609201000_provider_call_budget_exhausted_rejection.py"
            )
        )
        installed = next(
            str(call.args[0])
            for call in operations.execute.call_args_list
            if "ADD CONSTRAINT" in str(call.args[0])
        )
        assert (
            f"CHECK ({old['_lifecycle_shape'](old['_NEW_REASONS'])}) NOT VALID"
            in installed
        )
        operations.get_context.return_value.autocommit_block.assert_called_once()


@pytest.mark.parametrize(
    "status", ["started", "completed", "rejected", "outcome_unknown"]
)
def test_provider_call_lifecycle_retains_accepted_job_id(status):
    constraint = next(
        item
        for item in FlowProviderCalls.__table__.constraints
        if item.name == "ck_flow_provider_calls_lifecycle_shape"
    )
    values = {
        "status": status,
        "finished_at": None if status == "started" else "2026-09-20",
        "outcome_reason": {
            "rejected": "provider_rejected",
            "outcome_unknown": "provider_error",
        }.get(status),
        "response_model": None,
        "provider_response_id": "accepted-job",
        "num_tokens_input": None,
        "num_tokens_output": None,
        "input_source": "not_applicable" if status == "completed" else None,
        "output_source": "not_applicable" if status == "completed" else None,
    }
    with sqlite3.connect(":memory:") as connection:
        select = ", ".join(f":{name} AS {name}" for name in values)
        assert connection.execute(
            f"SELECT ({constraint.sqltext}) FROM (SELECT {select})", values
        ).fetchone() == (1,)


def test_alembic_revision_ids_fit_default_version_table() -> None:
    versions_dir = Path(__file__).parents[2] / "alembic" / "versions"

    overlong_revisions: list[str] = []
    for migration_path in sorted(versions_dir.glob("*.py")):
        revision = _assigned_string(migration_path, "revision")
        if revision is not None and len(revision) > _ALEMBIC_VERSION_NUM_LIMIT:
            overlong_revisions.append(
                f"{migration_path.name}: {revision!r} ({len(revision)} chars)"
            )

    assert overlong_revisions == []


def _assigned_string(path: Path, name: str) -> str | None:
    module = ast.parse(path.read_text(), filename=str(path))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return _string_constant(node.value)
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            return _string_constant(node.value)
    return None


def _string_constant(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None
