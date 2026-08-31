from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from uuid import UUID, uuid4

import pytest

from eneo.cli.flow_audit_outbox import (
    EXIT_BOOTSTRAP_FAILURE,
    EXIT_NOT_FOUND,
    EXIT_OK,
    _dry_run,
    _list_dead_letters,
    _redrive,
    _run_command,
    _run_database,
    _trusted_operator_identity,
    build_parser,
    main,
)


def test_parser_requires_one_bounded_operator_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["list", "--limit", "200"])

    assert args.command == "list"
    assert args.limit == 200


def test_parser_requires_generation_and_reason_for_redrive() -> None:
    parser = build_parser()
    outbox_id = str(uuid4())
    generation = "2026-08-31T10:00:00+00:00"

    args = parser.parse_args(
        [
            "redrive",
            outbox_id,
            "--expected-dead-lettered-at",
            generation,
            "--reason",
            "  audit sink recovered  ",
        ]
    )

    assert args.outbox_id == UUID(outbox_id)
    assert args.reason == "audit sink recovered"


def test_bootstrap_failure_is_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "eneo.cli.flow_audit_outbox._run_with_database",
        lambda _args: EXIT_BOOTSTRAP_FAILURE,
    )

    assert main(["list"]) == EXIT_BOOTSTRAP_FAILURE


def test_database_bootstrap_failure_closes_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Manager:
        close_calls = 0

        def init(self, _url: str) -> None:
            raise RuntimeError("bad settings")

        async def close(self) -> None:
            self.close_calls += 1

    manager = Manager()
    config = ModuleType("eneo.main.config")
    config.get_settings = lambda: SimpleNamespace(database_url="db")
    database = ModuleType("eneo.database.database")
    database.sessionmanager = manager
    monkeypatch.setitem(sys.modules, "eneo.main.config", config)
    monkeypatch.setitem(sys.modules, "eneo.database.database", database)

    assert (
        asyncio.run(_run_database(SimpleNamespace(command="list")))
        == EXIT_BOOTSTRAP_FAILURE
    )
    assert manager.close_calls == 1


def test_database_cleanup_failure_is_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Manager:
        async def close(self) -> None:
            raise RuntimeError("close failed")

        def init(self, _url: str) -> None:
            return None

    manager = Manager()
    config = ModuleType("eneo.main.config")
    config.get_settings = lambda: SimpleNamespace(database_url="db")
    database = ModuleType("eneo.database.database")
    database.sessionmanager = manager
    monkeypatch.setitem(sys.modules, "eneo.main.config", config)
    monkeypatch.setitem(sys.modules, "eneo.database.database", database)
    monkeypatch.setattr(
        "eneo.cli.flow_audit_outbox._run_command",
        lambda _args: asyncio.sleep(0, result=EXIT_OK),
    )

    assert (
        asyncio.run(_run_database(SimpleNamespace(command="list")))
        == EXIT_BOOTSTRAP_FAILURE
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_exit"),
    [
        ("not_found", EXIT_NOT_FOUND),
        ("state", 11),
        ("generation", 12),
        ("value", EXIT_BOOTSTRAP_FAILURE),
        ("sink", 21),
    ],
)
async def test_command_maps_operator_failures_to_distinct_exits(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    expected_exit: int,
) -> None:
    class NotFound(Exception):
        pass

    class StateConflict(Exception):
        pass

    class GenerationConflict(Exception):
        pass

    exception_module = ModuleType(
        "eneo.flows.application.flow_run_audit_outbox_delivery"
    )
    exception_module.FlowRunAuditOutboxNotFoundError = NotFound
    exception_module.FlowRunAuditOutboxStateConflictError = StateConflict
    exception_module.FlowRunAuditOutboxGenerationConflictError = GenerationConflict
    monkeypatch.setitem(
        sys.modules,
        "eneo.flows.application.flow_run_audit_outbox_delivery",
        exception_module,
    )

    failures: dict[str, Exception] = {
        "not_found": NotFound(),
        "state": StateConflict(),
        "generation": GenerationConflict(),
        "value": ValueError("invalid operator input"),
        "sink": RuntimeError("audit sink unavailable"),
    }

    class Service:
        async def list_dead_letters(self, **_kwargs: object) -> object:
            raise failures[failure]

    class Container:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def flow_run_audit_outbox_delivery_service(self) -> Service:
            return Service()

    container_module = ModuleType("eneo.main.container.container")
    container_module.Container = Container
    monkeypatch.setitem(sys.modules, "eneo.main.container.container", container_module)

    class Session:
        def begin(self) -> object:
            return self

        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class Manager:
        def session(self) -> Session:
            return Session()

    database_module = ModuleType("eneo.database.database")
    database_module.sessionmanager = Manager()
    monkeypatch.setitem(sys.modules, "eneo.database.database", database_module)

    args = SimpleNamespace(command="list", limit=1)
    assert await _run_command(args) == expected_exit


def test_list_limit_is_bounded() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["list", "--limit", "201"])


def test_redrive_reason_is_required_and_bounded() -> None:
    parser = build_parser()
    outbox_id = str(uuid4())
    timestamp = "2026-08-31T10:00:00+00:00"

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "redrive",
                outbox_id,
                "--expected-dead-lettered-at",
                timestamp,
                "--reason",
                " ",
            ]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "redrive",
                outbox_id,
                "--expected-dead-lettered-at",
                timestamp,
                "--reason",
                "x" * 501,
            ]
        )


def test_missing_operator_identity_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ENEO_OPERATOR_IDENTITY", raising=False)

    with pytest.raises(ValueError, match="must be configured"):
        _trusted_operator_identity()


@pytest.mark.asyncio
async def test_redrive_uses_trusted_environment_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outbox_id = uuid4()
    generation = datetime(2026, 8, 31, tzinfo=timezone.utc)
    captured: dict[str, object] = {}

    class Service:
        async def redrive_dead_lettered(self, **kwargs: object):
            captured.update(kwargs)
            return SimpleNamespace(
                outbox_id=outbox_id,
                flow_run_id=uuid4(),
                delivery_status="pending",
                delivery_attempts=0,
                next_delivery_at=generation,
                operator_audit_id=uuid4(),
            )

    monkeypatch.setenv("ENEO_OPERATOR_IDENTITY", "on-call@example.test")
    result = await _redrive(
        Service(),
        SimpleNamespace(
            outbox_id=outbox_id,
            expected_dead_lettered_at=generation,
            reason="storage recovered",
        ),
    )

    assert result == 0
    assert captured["operator_identity"] == "on-call@example.test"


@pytest.mark.asyncio
async def test_dry_run_reports_current_dead_letter_without_mutating() -> None:
    outbox_id = uuid4()
    generation = datetime(2026, 8, 31, tzinfo=timezone.utc)
    calls = 0

    class Service:
        async def inspect_redrive(self, **_kwargs: object) -> object:
            nonlocal calls
            calls += 1
            return SimpleNamespace(
                outbox_id=outbox_id,
                delivery_status="dead_lettered",
                dead_lettered_at=generation,
            )

    result = await _dry_run(
        Service(),
        SimpleNamespace(
            outbox_id=outbox_id,
            expected_dead_lettered_at=generation,
        ),
    )

    assert result == EXIT_OK
    assert calls == 1


@pytest.mark.asyncio
async def test_list_writes_only_sanitized_dead_letter_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Service:
        async def list_dead_letters(self, **_kwargs: object) -> object:
            return SimpleNamespace(
                items=(
                    SimpleNamespace(
                        outbox_id=uuid4(),
                        tenant_id=uuid4(),
                        flow_id=uuid4(),
                        flow_run_id=uuid4(),
                        action="flow_run.failed",
                        source="runtime",
                        delivery_attempts=5,
                        dead_lettered_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
                        delivery_last_error="StorageError: password=[REDACTED]",
                        created_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
                        payload={"secret": "must-not-be-printed"},
                    ),
                ),
                has_more=False,
            )

    result = await _list_dead_letters(Service(), SimpleNamespace(limit=1))

    assert result == EXIT_OK
    output = capsys.readouterr().out
    assert "must-not-be-printed" not in output
    assert '"delivery_attempts":5' in output
    assert '"has_more":false' in output
