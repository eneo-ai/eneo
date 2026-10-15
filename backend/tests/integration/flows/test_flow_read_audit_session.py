"""A read's audit record, on real sessions: a tool read and an HTTP input read
each queue exactly one, with an audit service on a short database session of
its own, never on the run's session.

Intended semantics: the record goes to the audit queue when the read ends,
outside the run's transaction, so neither the run's commit nor its rollback
adds or withdraws it; the audit worker then writes it to audit_logs."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session

from eneo.audit.application.audit_worker_task import log_audit_event_task
from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.feature_flag_table import GlobalFeatureFlag
from eneo.database.tables.mcp_server_table import SpacesMCPServers
from eneo.flows.domain.flow import FlowRun, FlowStep
from eneo.flows.runtime.http_runtime import FlowHttpRuntimeHelper
from eneo.main.container.container import _active_session_ctx
from tests.integration.flows.test_flow_tool_call_evidence import (
    _execute,
    tool_calls,  # noqa: F401  (registers the fixture)
)
from tests.integration.flows.test_flow_tool_step_sessions import (
    ToolFlow,
    tool_flow,  # noqa: F401  (registers the fixture)
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _published_run(db_container, flow: ToolFlow, source: str) -> FlowRun:
    """The flow published as one step that reads the tool or an HTTP GET and
    composes its answer without a model, and one run of it."""
    input_config: dict[str, object] = (
        {"tool": flow.tool_config}
        if source == "tool"
        else {"url": "https://example.org/case", "auth": {"mode": "none"}}
    )
    async with db_container() as container:
        service = container.flow_service()
        await service.update_flow(
            flow_id=flow.flow_id,
            steps=[
                FlowStep.model_validate(
                    {
                        "assistant_id": flow.assistant_id,
                        "step_order": 1,
                        "user_description": "Hämta ärendet",
                        "input_source": "tool" if source == "tool" else "http_get",
                        "input_type": "text",
                        "input_config": input_config,
                        "output_mode": "compose_text",
                        "output_type": "text",
                    }
                )
            ],
        )
        if source == "tool":
            container.session().add(
                SpacesMCPServers(space_id=flow.space_id, mcp_server_id=flow.server_id)
            )
            await container.session().flush()
        await service.publish_flow(flow_id=flow.flow_id)
        return (
            await container.flow_run_service().create_run(
                flow_id=flow.flow_id,
                input_payload_json={"text": "A-17"},
                expected_flow_version=1,
                idempotency_key=f"read-audit-session-{uuid4()}",
            )
        ).run


@pytest.fixture
def feature_flag_reads() -> Iterator[list[Session]]:
    """The session of every read of a global feature flag, in order: the
    audit service reads one before it queues each record."""
    sessions: list[Session] = []

    def keep(state: ORMExecuteState) -> None:
        if any(mapper.class_ is GlobalFeatureFlag for mapper in state.all_mappers):
            sessions.append(state.session)

    event.listen(Session, "do_orm_execute", keep)
    yield sessions
    event.remove(Session, "do_orm_execute", keep)


@pytest.mark.parametrize("source", ["tool", "http"])
async def test_a_read_queues_one_audit_record_on_a_session_of_its_own(
    db_container,
    admin_user,
    tool_flow: ToolFlow,  # noqa: F811
    tool_calls,  # noqa: F811
    feature_flag_reads: list[Session],
    monkeypatch,
    source: str,
) -> None:
    # Kills the mutants that queue a read's audit record with an audit service
    # on the run's session (the executor ignores read_audit_service, or the
    # worker builds it on the run's container), and that queue no record, or
    # two, for a tool read or an HTTP input read.
    async def send_request(self: FlowHttpRuntimeHelper, **_: object) -> httpx.Response:
        return httpx.Response(
            200,
            request=httpx.Request("GET", "https://example.org/case"),
            text="Ärende A-17 är öppet.",
        )

    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", send_request)
    run = await _published_run(db_container, tool_flow, source)
    tool_calls.run_id = run.id
    queued: list[tuple[dict[str, Any], Session | None, Session | None]] = []

    async def enqueue(task: object, job_id: object, params: dict[str, Any]) -> None:
        scoped = _active_session_ctx.get()
        queued.append(
            (
                params,
                None if scoped is None else scoped.sync_session,
                feature_flag_reads[-1] if feature_flag_reads else None,
            )
        )

    with patch("eneo.audit.application.audit_service.job_manager") as job_manager:
        job_manager.enqueue = AsyncMock(side_effect=enqueue)
        await _execute(run, admin_user)

    reads = [
        entry
        for entry in queued
        if entry[0]["action"] == ActionType.FLOW_HTTP_OUTBOUND_CALL.value
    ]
    assert len(reads) == 1
    params, scoped, flag_read_on = reads[0]
    assert params["metadata"]["extra"]["call_type"] == (
        "tool_input" if source == "tool" else "http_input"
    )
    assert scoped is not None
    assert flag_read_on is scoped

    async with db_container() as container:
        await log_audit_event_task(
            job_id=uuid4(), params=params, session=container.session()
        )
    async with db_container() as container:
        stored = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.entity_id == run.id,
                AuditLog.action == ActionType.FLOW_HTTP_OUTBOUND_CALL.value,
            )
        )
    assert stored == 1
