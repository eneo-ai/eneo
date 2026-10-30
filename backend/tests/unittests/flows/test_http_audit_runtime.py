from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.domain.outcome import Outcome
from eneo.flows.runtime.flow_run_actor import FlowRunActor
from eneo.flows.runtime.http_audit import HttpAuditDeps, audit_http_outbound
from eneo.users.user import UserInDB
from tests.unittests.flows.async_test_support import until_task_reaches


@dataclass
class _Run:
    id: str
    flow_id: str
    tenant_id: str


@dataclass
class _Step:
    step_order: int
    step_id: str
    user_description: str | None = None


def _actor() -> FlowRunActor:
    user_id = UUID(int=1)
    tenant_id = UUID(int=2)
    user = cast(
        UserInDB,
        SimpleNamespace(
            id=user_id,
            tenant_id=tenant_id,
            username="Test User",
            email="test@example.org",
            active_api_key=None,
        ),
    )
    return FlowRunActor.from_user(user=user)


@pytest.mark.asyncio
async def test_audit_http_outbound_logs_sanitized_metadata() -> None:
    audit_service = SimpleNamespace(log_async=AsyncMock())
    deps = HttpAuditDeps(
        audit_service=audit_service,
        actor=_actor(),
        logger=MagicMock(),
    )
    run = _Run(id="run-1", flow_id="flow-1", tenant_id="tenant-1")
    step = _Step(step_order=2, step_id="step-2", user_description="Webhook step")

    await audit_http_outbound(
        run=run,
        step=step,
        url="https://alice:secret@example.org/hook?token=abc",
        method="POST",
        call_type="webhook_delivery",
        outcome=Outcome.SUCCESS,
        status_code=204,
        duration_ms=123.456,
        deps=deps,
    )

    audit_service.log_async.assert_awaited_once()
    kwargs = audit_service.log_async.await_args.kwargs
    assert kwargs["action"] == ActionType.FLOW_HTTP_OUTBOUND_CALL
    assert kwargs["entity_type"] == EntityType.FLOW_RUN
    assert kwargs["actor_id"] == UUID(int=1)
    assert kwargs["actor_type"] == ActorType.USER
    assert kwargs["actor_api_key_id"] is None
    extra = kwargs["metadata"]["extra"]
    assert extra["url_host"] == "https://example.org"
    assert extra["url_path"] == "/hook"
    assert extra["status_code"] == 204
    assert extra["duration_ms"] == 123.46
    assert extra["step_description"] == "Webhook step"
    assert kwargs["error_message"] is None


@pytest.mark.asyncio
async def test_audit_http_outbound_noop_without_service() -> None:
    deps = HttpAuditDeps(
        audit_service=None,
        actor=_actor(),
        logger=MagicMock(),
    )
    run = _Run(id="run-1", flow_id="flow-1", tenant_id="tenant-1")
    step = _Step(step_order=1, step_id="step-1")

    await audit_http_outbound(
        run=run,
        step=step,
        url="https://example.org/hook",
        method="POST",
        call_type="webhook_delivery",
        outcome=Outcome.FAILURE,
        deps=deps,
    )


@pytest.mark.asyncio
async def test_audit_http_outbound_never_breaks_flow_on_logger_failure() -> None:
    audit_service = SimpleNamespace(
        log_async=AsyncMock(side_effect=RuntimeError("audit down"))
    )
    fake_logger = MagicMock()
    deps = HttpAuditDeps(
        audit_service=audit_service,
        actor=_actor(),
        logger=fake_logger,
    )
    run = _Run(id="run-1", flow_id="flow-1", tenant_id="tenant-1")
    step = _Step(step_order=9, step_id="step-9")

    await audit_http_outbound(
        run=run,
        step=step,
        url="https://example.org/hook",
        method="POST",
        call_type="webhook_delivery",
        outcome=Outcome.FAILURE,
        error_message="failed",
        deps=deps,
    )

    fake_logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_audit_http_outbound_handles_url_without_hostname() -> None:
    audit_service = SimpleNamespace(log_async=AsyncMock())
    deps = HttpAuditDeps(
        audit_service=audit_service,
        actor=_actor(),
        logger=MagicMock(),
    )
    run = _Run(id="run-2", flow_id="flow-2", tenant_id="tenant-2")
    step = _Step(step_order=3, step_id="step-3")

    await audit_http_outbound(
        run=run,
        step=step,
        url="/relative/path?token=secret",
        method="GET",
        call_type="http_input",
        outcome=Outcome.FAILURE,
        error_message="network error",
        deps=deps,
    )

    kwargs = audit_service.log_async.await_args.kwargs
    extra = kwargs["metadata"]["extra"]
    assert extra["url_host"] == ""
    assert extra["url_path"] == "/relative/path"
    assert kwargs["error_message"] == "network error"


@pytest.mark.asyncio
async def test_audit_http_outbound_uses_step_label_when_description_missing() -> None:
    audit_service = SimpleNamespace(log_async=AsyncMock())
    deps = HttpAuditDeps(
        audit_service=audit_service,
        actor=_actor(),
        logger=MagicMock(),
    )
    run = _Run(id="run-3", flow_id="flow-3", tenant_id="tenant-3")
    step = _Step(step_order=7, step_id="step-7", user_description=None)

    await audit_http_outbound(
        run=run,
        step=step,
        url="https://example.org/no-description",
        method="GET",
        call_type="http_input",
        outcome=Outcome.SUCCESS,
        duration_ms=None,
        deps=deps,
    )

    kwargs = audit_service.log_async.await_args.kwargs
    extra = kwargs["metadata"]["extra"]
    assert "step_description" not in extra
    assert "duration_ms" not in extra


@pytest.mark.asyncio
@pytest.mark.parametrize("stopped", [False, True], ids=["expired", "stopped"])
async def test_a_read_audit_whose_write_will_not_unwind_ends_within_its_limit(
    monkeypatch, stopped: bool
) -> None:
    # Kills the mutants that wait, after the limit, for the cancelled write to
    # unwind (this write's cleanup does not end while the read waits, so that
    # wait would hold the read, stopped or not), that leave the write running
    # uncancelled, and that drop or keep holding the write while it unwinds
    # (the event loop holds a task only weakly).
    import asyncio

    from eneo.flows.runtime import http_audit

    monkeypatch.setattr(http_audit, "READ_AUDIT_TIMEOUT_SECONDS", 0.05)
    queueing, unwound = asyncio.Event(), asyncio.Event()
    cancelled: list[bool] = []

    async def write() -> None:
        try:
            queueing.set()
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
        finally:
            await unwound.wait()

    read = asyncio.create_task(http_audit.await_read_audit(write()))
    await until_task_reaches(queueing, read)
    if stopped:
        read.cancel()

    done, _ = await asyncio.wait({read}, timeout=2)

    await asyncio.sleep(0)
    assert done == {read}
    assert read.cancelled() == stopped
    assert cancelled == [True]
    assert len(http_audit._UNWINDING_WRITES) == 1
    unwound.set()
    for _ in range(3):
        await asyncio.sleep(0)
    assert not http_audit._UNWINDING_WRITES


@pytest.mark.asyncio
async def test_a_read_audit_service_has_a_database_session_of_its_own(
    monkeypatch,
) -> None:
    # Kills the mutants that give the read audit service no session of its
    # own (its repositories reach no scoped session), that open no
    # transaction on it, and that leave it reachable after the scope.
    from contextlib import asynccontextmanager

    from dependency_injector import providers

    from eneo.database import database
    from eneo.flows.runtime import tasks
    from eneo.main.container.container import Container, SessionProxy

    own = MagicMock(name="own")

    @asynccontextmanager
    async def session():
        yield own

    monkeypatch.setattr(database, "sessionmanager", SimpleNamespace(session=session))
    sessionless = Container(session=providers.Object(SessionProxy()))

    async with tasks.audit_service_on_own_session(sessionless) as audit_service:
        sessions = [
            audit_service.repository.session,
            audit_service.audit_config_service.repository.session,
            audit_service.feature_flag_service.feature_flag_repo.db_session,
        ]
        assert all(session.execute is own.execute for session in sessions)

    own.begin.assert_called_once_with()
    with pytest.raises(RuntimeError):
        _ = sessions[0].execute
