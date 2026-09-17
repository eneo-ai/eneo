from uuid import uuid4

import pytest


def test_repair_cli_requires_scope_and_defaults_to_dry_run():
    from eneo.cli.flow_step_config_repair import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    tenant_id = uuid4()
    args = parser.parse_args(["--tenant", str(tenant_id)])
    assert args.tenant == tenant_id
    assert args.apply is False
    assert 0 < args.limit <= 1000
    assert args.after is None
    with pytest.raises(SystemExit):
        parser.parse_args(["--tenant", str(tenant_id), "--all-tenants"])
    for limit in ("0", "1001", "bad"):
        with pytest.raises(SystemExit):
            parser.parse_args(["--all-tenants", "--limit", limit])
    with pytest.raises(SystemExit):
        parser.parse_args(["--all-tenants", "--after", "not-a-uuid"])
    help_text = parser.format_help()
    assert "current" in help_text
    assert "snapshots" in help_text


@pytest.mark.asyncio
async def test_repair_cli_bounds_scan_reports_cursor_and_redacts_failure(
    monkeypatch, capsys
):
    import json
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    from eneo.cli import flow_step_config_repair as cli
    from eneo.database.database import sessionmanager
    from eneo.flows.application import flow_step_config_repair as application
    from eneo.flows.infrastructure.flow_repo import FlowRepository

    tenant_id = uuid4()
    ids = sorted([uuid4(), uuid4(), uuid4()])
    session = MagicMock()

    @asynccontextmanager
    async def session_context():
        yield session

    async def next_flow(self, *, tenant_id, after):
        return next(
            (
                (tenant_id, flow_id)
                for flow_id in ids
                if after is None or flow_id > after
            ),
            None,
        )

    repair = AsyncMock(
        side_effect=["repaired", RuntimeError("private-url-and-credential")]
    )
    monkeypatch.setenv("ENEO_OPERATOR_IDENTITY", "test-operator")
    monkeypatch.setattr(sessionmanager, "session", session_context)
    monkeypatch.setattr(FlowRepository, "next_step_config_repair_flow", next_flow)
    monkeypatch.setattr(application, "repair_flow_step_config", repair)
    args = cli.build_parser().parse_args(
        ["--tenant", str(tenant_id), "--apply", "--limit", "2"]
    )
    assert await cli._run_command(args) == 1
    output = capsys.readouterr().out
    assert "private-url-and-credential" not in output
    records = [json.loads(line) for line in output.splitlines()]
    assert records[:2] == [
        {"tenant_id": str(tenant_id), "flow_id": str(ids[0]), "outcome": "repaired"},
        {"tenant_id": str(tenant_id), "flow_id": str(ids[1]), "outcome": "failed"},
    ]
    assert records[-1]["counts"] == {
        "would_change": 0,
        "unchanged": 0,
        "repaired": 1,
        "conflict": 0,
        "invalid": 0,
        "failed": 1,
    }
    assert records[-1]["next_cursor"] == str(ids[1])
    assert records[-1]["scope"] == "current_rows"
    assert "inactive credentials" in records[-1]["published_snapshots"]
    assert repair.await_count == 2

    repair.side_effect = ["would_change"]
    args = cli.build_parser().parse_args(
        ["--tenant", str(tenant_id), "--after", str(ids[1])]
    )
    assert await cli._run_command(args) == 0
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records[0]["flow_id"] == str(ids[2])
    assert records[-1]["next_cursor"] is None
    assert repair.await_args.kwargs["apply"] is False


def test_repair_cli_bootstrap_failure_does_not_expose_exception(monkeypatch, capsys):
    from eneo.cli import flow_step_config_repair as cli
    from eneo.database.database import sessionmanager

    def fail_init(*args, **kwargs):
        raise RuntimeError("database-password-must-not-leak")

    monkeypatch.setattr(sessionmanager, "init", fail_init)
    assert cli.main(["--all-tenants"]) == 1
    output = capsys.readouterr()
    assert '"outcome": "failed"' in output.out
    assert "database-password-must-not-leak" not in output.out + output.err
