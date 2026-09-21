from __future__ import annotations

import ast
import importlib.util
import io
import runpy
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest
import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations
from eneo.database.tables.flow_tables import (
    FLOW_RUN_LIFECYCLE_SOURCE_VALUES,
    FlowProviderCalls,
)
from eneo.object_content.configuration import (
    DEFAULT_FILE_UPLOAD_LIMIT_BYTES,
    ObjectContentCoreSettings,
)

_ALEMBIC_VERSION_NUM_LIMIT = 32


def _abandonment_migration():
    return runpy.run_path(
        str(
            Path(__file__).parents[2]
            / "alembic"
            / "versions"
            / "202609211000_flow_abandonment_indexes.py"
        )
    )


def test_abandonment_audit_source_literals_match_model():
    migration = _abandonment_migration()
    actual = set(migration["_NEW_SOURCES"])
    expected = set(FLOW_RUN_LIFECYCLE_SOURCE_VALUES)
    assert actual == expected, (
        "ck_flow_run_audit_outbox_source migration literals differ from the ORM: "
        f"missing={sorted(expected - actual)}, unexpected={sorted(actual - expected)}. "
        "Update the migration when lifecycle sources change."
    )
    assert set(migration["_OLD_SOURCES"]) == expected - {"abandonment_reconciler"}


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
@pytest.mark.parametrize("existing", ["absent", "previous", "unvalidated", "validated"])
def test_abandonment_audit_constraint_resumes_each_phase(
    monkeypatch, direction, existing
):
    from eneo.database.tables.flow_tables import FlowRunAuditOutbox

    migration = _abandonment_migration()
    sources = migration["_NEW_SOURCES" if direction == "upgrade" else "_OLD_SOURCES"]
    other = migration["_OLD_SOURCES" if direction == "upgrade" else "_NEW_SOURCES"]
    values = ",".join(f"'{source}'" for source in sources)
    definition = f"CHECK (source IN ({values}))"
    operations = MagicMock()
    result = operations.get_bind.return_value.execute.return_value
    result.scalar.return_value = None
    result.scalar_one.return_value = False
    result.mappings.return_value.one_or_none.return_value = (
        None
        if existing == "absent"
        else {
            "convalidated": existing != "unvalidated",
            "definition": (
                f"CHECK (source IN ({','.join(repr(source) for source in other)}))"
                if existing == "previous"
                else definition
            ),
        }
    )
    monkeypatch.setitem(migration[direction].__globals__, "op", operations)
    migration[direction]()
    queries = [
        str(c.args[0]) for c in operations.get_bind.return_value.execute.call_args_list
    ]
    assert any(
        "pg_constraint" in sql and "pg_get_constraintdef" in sql for sql in queries
    )
    statements = [str(c.args[0]) for c in operations.execute.call_args_list]
    additions = [sql for sql in statements if "ADD CONSTRAINT" in sql]
    validations = [sql for sql in statements if "VALIDATE CONSTRAINT" in sql]
    if existing in {"absent", "previous"}:
        assert additions == [
            "ALTER TABLE flow_run_audit_outbox ADD CONSTRAINT "
            f"ck_flow_run_audit_outbox_source CHECK (source IN ({values})) NOT VALID"
        ]
        if direction == "upgrade":
            constraint = next(
                item
                for item in FlowRunAuditOutbox.__table__.constraints
                if item.name == "ck_flow_run_audit_outbox_source"
            )
            assert f"CHECK ({constraint.sqltext}) NOT VALID" in additions[0]
        calls = operations.mock_calls
        assert calls.index(call.execute(additions[0])) < calls.index(
            call.get_context().autocommit_block().__enter__()
        )
    else:
        assert additions == []
    if existing == "previous":
        operations.drop_constraint.assert_called_once_with(
            "ck_flow_run_audit_outbox_source", "flow_run_audit_outbox", type_="check"
        )
    else:
        operations.drop_constraint.assert_not_called()
    assert len(validations) == (0 if existing == "validated" else 1)
    operations.execute.assert_called_with("RESET lock_timeout")


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_abandonment_audit_validation_failure_resets_lock_timeout(
    monkeypatch, direction
):
    migration = _abandonment_migration()
    operations = MagicMock()
    result = operations.get_bind.return_value.execute.return_value
    result.mappings.return_value.one_or_none.return_value = None
    result.scalar_one.return_value = False

    def execute(sql):
        if "VALIDATE CONSTRAINT" in str(sql):
            raise RuntimeError("lock unavailable")

    operations.execute.side_effect = execute
    monkeypatch.setitem(migration[direction].__globals__, "op", operations)
    with pytest.raises(RuntimeError, match="lock unavailable"):
        migration[direction]()
    operations.execute.assert_called_with("RESET lock_timeout")


def test_abandonment_downgrade_preserves_audit_evidence(monkeypatch):
    migration = _abandonment_migration()
    operations = MagicMock()
    operations.get_bind.return_value.execute.return_value.scalar_one.return_value = True
    monkeypatch.setitem(migration["downgrade"].__globals__, "op", operations)
    with pytest.raises(RuntimeError, match="Refusing to downgrade.*abandonment"):
        migration["downgrade"]()
    operations.drop_constraint.assert_not_called()
    operations.drop_index.assert_not_called()


def test_abandonment_indexes_match_models_and_downgrade_without_data_changes(
    monkeypatch,
):
    from eneo.database.tables.flow_tables import FlowRunReviewCheckpoints, FlowRuns

    migration = _abandonment_migration()
    assert migration["down_revision"] == "202609201300"
    operations = MagicMock()
    result = operations.get_bind.return_value.execute.return_value
    result.scalar.return_value = None
    result.scalar_one.return_value = False
    result.mappings.return_value.one_or_none.return_value = None
    monkeypatch.setitem(migration["upgrade"].__globals__, "op", operations)
    migration["upgrade"]()
    expected_names = {
        "ix_flow_runs_exhausted_dispatch_wait",
        "ix_flow_runs_awaiting_review_created",
        "ix_flow_review_approved_wait",
    }
    assert {c.args[0] for c in operations.create_index.call_args_list} == expected_names
    models = {
        i.name: i
        for table in (FlowRuns, FlowRunReviewCheckpoints)
        for i in table.__table__.indexes
    }
    for invocation in operations.create_index.call_args_list:
        name, table, columns = invocation.args
        index = models[name]
        assert index.table.name == table
        assert [c.name for c in index.columns] == columns
        assert str(index.dialect_options["postgresql"]["where"]) == str(
            invocation.kwargs["postgresql_where"]
        )
        assert tuple(index.dialect_options["postgresql"]["include"]) == tuple(
            invocation.kwargs["postgresql_include"]
        )
        assert invocation.kwargs["postgresql_concurrently"] is True
    operations.execute.assert_called_with("RESET lock_timeout")
    operations.reset_mock()
    migration["downgrade"]()
    assert {c.args[0] for c in operations.drop_index.call_args_list} == expected_names
    operations.drop_table.assert_not_called()
    operations.drop_column.assert_not_called()


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
        "SET lock_timeout = '5s'",
        "ALTER TABLE flow_provider_calls VALIDATE CONSTRAINT ck_flow_provider_calls_lifecycle_shape",
        "RESET lock_timeout",
    ]
    operations.get_context.return_value.autocommit_block.assert_called_once()
    calls = operations.mock_calls
    assert calls.index(call.get_context().autocommit_block().__enter__()) < calls.index(
        call.execute("SET lock_timeout = '5s'")
    )
    assert calls.index(call.execute("RESET lock_timeout")) < calls.index(
        call.get_context().autocommit_block().__exit__(None, None, None)
    )


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_accepted_job_validation_failure_resets_lock_timeout(monkeypatch, direction):
    migration = _accepted_job_migration()
    operations = MagicMock()
    operations.get_bind.return_value.execute.return_value.scalar_one.return_value = 0

    def execute(sql):
        if "VALIDATE CONSTRAINT" in str(sql):
            raise RuntimeError("lock unavailable")

    operations.execute.side_effect = execute
    for name in ("execute", "drop_constraint", "get_context", "get_bind"):
        monkeypatch.setattr(
            migration[direction].__globals__["op"], name, getattr(operations, name)
        )
    with pytest.raises(RuntimeError, match="lock unavailable"):
        migration[direction]()
    operations.execute.assert_called_with("RESET lock_timeout")


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


def test_heartbeat_migration_backfills_running_rows_and_reverses_schema() -> None:
    migration_path = (
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "202609201200_flow_execution_heartbeat.py"
    )
    spec = importlib.util.spec_from_file_location("heartbeat_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration.upgrade()
    sql = output.getvalue()
    assert "execution_heartbeat_at = updated_at WHERE status = 'running'" in sql
    assert "status <> 'running' OR execution_heartbeat_at IS NOT NULL" in sql
    assert "ix_flow_runs_running_execution_heartbeat" in sql
    assert "DROP INDEX CONCURRENTLY IF EXISTS ix_flow_runs_running_updated_at" in sql
    column = sql.index("ADD COLUMN IF NOT EXISTS execution_heartbeat_at")
    backfill = sql.index("UPDATE flow_runs SET execution_heartbeat_at")
    constraint = sql.index("ADD CONSTRAINT ck_flow_runs_running_execution_heartbeat")
    validate = sql.index("VALIDATE CONSTRAINT ck_flow_runs_running_execution_heartbeat")
    index = sql.index(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_flow_runs_running_execution_heartbeat"
    )
    assert "COMMIT;" in sql[column:backfill]
    assert "NOT VALID" in sql[constraint:validate]
    assert "COMMIT;" in sql[constraint:validate]
    assert "SET lock_timeout = '5s'" in sql[constraint:validate]
    assert "RESET lock_timeout" in sql[validate:]
    assert backfill < validate < index
    assert "execution_heartbeat_at IS NULL" in sql[backfill:validate]
    assert "IF NOT EXISTS" in sql[:constraint]
    assert "NOT convalidated" in sql[backfill:validate]
    assert "NOT indisvalid" in sql[:index]
    assert "DROP INDEX ix_flow_runs_running_execution_heartbeat" in sql[:index]
    output.truncate(0)
    output.seek(0)
    with Operations.context(context):
        migration.downgrade()
    sql = output.getvalue()
    assert "DROP COLUMN execution_heartbeat_at" in sql
    assert "CREATE INDEX CONCURRENTLY ix_flow_runs_running_updated_at" in sql


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


def test_upload_default_migration_literals_match_runtime_defaults() -> None:
    versions = Path(__file__).parents[2] / "alembic/versions"
    path = versions / "202609201300_raise_upload_policy_defaults.py"
    module = ast.parse(path.read_text())
    limits = next(
        node.value
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_LIMITS"
            for target in node.targets
        )
    )
    assert ast.literal_eval(limits) == {
        "session_file_limit_bytes": (10485760, DEFAULT_FILE_UPLOAD_LIMIT_BYTES),
        "knowledge_file_limit_bytes": (10485760, DEFAULT_FILE_UPLOAD_LIMIT_BYTES),
        "transcription_audio_limit_bytes": (
            209715200,
            ObjectContentCoreSettings.model_fields["inline_maximum_bytes"].default,
        ),
    }
    for filename in ("202607251700_add_object_content_deployment_policy.py", path.name):
        tree = ast.parse((versions / filename).read_text())
        assert not any(
            (
                isinstance(node, ast.ImportFrom)
                and (node.module or "").split(".")[0] == "eneo"
            )
            or (
                isinstance(node, ast.Import)
                and any(alias.name.split(".")[0] == "eneo" for alias in node.names)
            )
            for node in ast.walk(tree)
        )


@pytest.mark.parametrize(
    ("stored", "raised"),
    [
        (None, (268435456, 268435456, 402653184)),
        ((268435456, 268435456, 402653184), (268435456, 268435456, 402653184)),
        ((1024, 2048, 4096), (1024, 2048, 4096)),
        ((536870912, 536870912, 2147483648), (536870912, 536870912, 2147483648)),
        ((10485760, 2048, 209715200), (268435456, 2048, 402653184)),
    ],
)
def test_upload_default_migration_preserves_policy_on_downgrade(
    monkeypatch, stored, raised
):
    path = (
        Path(__file__).parents[2]
        / "alembic/versions/202609201300_raise_upload_policy_defaults.py"
    )
    assert path.exists()
    spec = importlib.util.spec_from_file_location("raise_upload_defaults", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "202609201300"
    assert migration.down_revision == "202609201200"
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    table = sa.Table(
        "object_content_deployment_policy",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("revision", sa.Integer),
        sa.Column("session_file_limit_bytes", sa.BigInteger),
        sa.Column("knowledge_file_limit_bytes", sa.BigInteger),
        sa.Column("transcription_audio_limit_bytes", sa.BigInteger),
        sa.Column("session_image_limit_bytes", sa.BigInteger),
        sa.Column("updated_at", sa.DateTime),
        sa.Column("updated_by_actor", sa.String),
        sa.Column("updated_by_user_id", sa.String),
    )
    columns = (
        "session_file_limit_bytes",
        "knowledge_file_limit_bytes",
        "transcription_audio_limit_bytes",
    )
    if stored is None:
        seed_path = path.with_name(
            "202607251700_add_object_content_deployment_policy.py"
        )
        seed_spec = importlib.util.spec_from_file_location(
            "upload_policy_seed", seed_path
        )
        assert seed_spec is not None and seed_spec.loader is not None
        seed_migration = importlib.util.module_from_spec(seed_spec)
        seed_spec.loader.exec_module(seed_migration)
        seeds = seed_migration.resolve_seed_limits({})
        stored = tuple(seeds[name] for name in columns)
    try:
        with engine.begin() as connection:
            metadata.create_all(connection)
            connection.execute(
                table.insert().values(
                    id=1,
                    revision=7,
                    session_image_limit_bytes=1234,
                    updated_by_actor="storage_admin",
                    updated_by_user_id="admin",
                    **dict(zip(columns, stored)),
                )
            )
            monkeypatch.setattr(migration.op, "execute", connection.execute)
            original = dict(connection.execute(sa.select(table)).mappings().one())
            migration.upgrade()
            row = connection.execute(sa.select(table)).mappings().one()
            if stored == raised:
                assert dict(row) == original
            assert tuple(row[name] for name in columns) == raised
            assert row["session_image_limit_bytes"] == 1234
            assert row["revision"] == 7 + (stored != raised)
            migration.upgrade()
            assert (
                connection.execute(sa.select(table.c.revision)).scalar_one()
                == row["revision"]
            )
            upgraded = dict(row)
            migration.downgrade()
            row = connection.execute(sa.select(table)).mappings().one()
            assert dict(row) == upgraded
    finally:
        engine.dispose()
