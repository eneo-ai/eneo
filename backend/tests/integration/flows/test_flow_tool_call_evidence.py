"""The record of a tool step's call on its attempt, on real sessions: the
start is committed before the request, the result before the step goes on,
a closed attempt is never written again, and the write waits for a
terminalization that holds the run."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.authentication.principal_types import PrincipalType
from eneo.database.database import sessionmanager
from eneo.database.tables.flow_tables import (
    FlowRuns,
    FlowStepAttemptResolvedInputs,
    FlowStepAttempts,
)
from eneo.database.tables.mcp_server_table import SpacesMCPServers
from eneo.flows.application.flow_run_terminalization import FlowRunTerminalizer
from eneo.flows.domain.canonical_json_hash import canonical_json_hash
from eneo.flows.domain.flow import FlowRun, FlowRunStatus, FlowStep
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.flow_run_provenance import FlowResolvedInputEdges
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunExecutionOwner,
    FlowRunRepository,
    flow_run_execution_owner,
)
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.runtime import tasks as flow_runtime_tasks
from eneo.flows.runtime import tool_input
from eneo.mcp_servers.application.unattended_tool_call import UnattendedToolCaller
from eneo.mcp_servers.infrastructure.client.mcp_client import MCPToolAnswer
from tests.integration.flows.test_flow_terminalization_contract import (
    _create_running_run,
)
from tests.integration.flows.test_flow_tool_step_sessions import (
    _SCHEMA,
    ToolFlow,
    tool_flow,  # noqa: F401  (registers the fixture)
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_ANSWER = "Ärende A-17 är öppet."


async def _attempt_input(run_id: UUID, step_order: int = 1) -> Any:
    """The stored input of the run's attempt, read on a session of its own:
    only what is committed is visible."""
    async with sessionmanager.session() as session, session.begin():
        return await session.scalar(
            sa.select(FlowStepAttempts.input_payload_json).where(
                FlowStepAttempts.flow_run_id == run_id,
                FlowStepAttempts.step_order == step_order,
            )
        )


@dataclass
class ToolCalls:
    """The calls the fixture tool received, and what it does during one."""

    run_id: UUID | None = None
    received: list[dict[str, object]] = field(default_factory=list)
    stored_when_called: list[Any] = field(default_factory=list)
    during_call: Any = None
    before_call: Any = None


@pytest.fixture
async def tool_calls(monkeypatch) -> AsyncIterator[ToolCalls]:
    """The tool answers without a server. Everything else of the read and
    the run is the product's."""
    calls = ToolCalls()

    async def call(
        self: UnattendedToolCaller,
        server: object,
        tool_name: str,
        arguments: dict[str, object],
        **_: object,
    ) -> MCPToolAnswer:
        calls.received.append(arguments)
        assert calls.run_id is not None
        calls.stored_when_called.append(await _attempt_input(calls.run_id))
        if calls.during_call is not None:
            await calls.during_call()
        return MCPToolAnswer((_ANSWER,), 0, None, is_error=False)

    async def vetted(*_: object) -> None:
        if calls.before_call is not None:
            await calls.before_call()

    monkeypatch.setattr(UnattendedToolCaller, "call", call)
    monkeypatch.setattr(tool_input, "_vet_server_address", vetted)
    yield calls


async def _published_run(db_container, flow: ToolFlow) -> FlowRun:
    """The flow published as one step that composes the tool's answer, with
    no model, and one run of it."""
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
                        "input_source": "tool",
                        "input_type": "text",
                        "input_config": {"tool": flow.tool_config},
                        "output_mode": "compose_text",
                        "output_type": "text",
                    }
                )
            ],
        )
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
                idempotency_key=f"tool-call-evidence-{uuid4()}",
            )
        ).run


async def _execute(run: FlowRun, admin_user) -> dict[str, object]:
    try:
        return await flow_runtime_tasks._execute_flow_run_async(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            run_revision=run.revision,
            principal_type=PrincipalType.USER,
            principal_user_id=admin_user.id,
            principal_service_id=None,
            task_id=None,
            retry_count=0,
            invocation_deadline=None,
        )
    finally:
        await flow_runtime_tasks.execution_heartbeats().stop()


async def _public_attempt(db_container, run: FlowRun) -> Any:
    from eneo.flows.api.flow_models import FlowStepAttemptPublic

    async with db_container() as container:
        repo = container.flow_run_repo()
        (attempt,) = (
            await repo.list_step_attempts(run_id=run.id, tenant_id=run.tenant_id)
        ).attempts
        edges = await repo.get_resolved_input_edges(
            attempt_id=attempt.id, tenant_id=run.tenant_id
        )
    return FlowStepAttemptPublic.model_validate(
        {**attempt.model_dump(), "resolved_input_lineage": {"status": "not_tracked"}}
    ), edges


async def test_the_start_is_committed_before_the_call_and_the_result_with_the_answer(
    db_container,
    admin_user,
    tool_flow: ToolFlow,  # noqa: F811
    tool_calls: ToolCalls,
) -> None:
    # Kills the mutants that write the start after the call, or write it and
    # leave it to a later commit (another session would not see it when the
    # request is sent), that store no result or one that is not the answer
    # the step read, and that let the attempt's activation drop the record.
    run = await _published_run(db_container, tool_flow)
    tool_calls.run_id = run.id

    result = await _execute(run, admin_user)

    assert result["status"] == "completed"
    assert tool_calls.received == [{"case_id": "A-17"}]
    (stored_when_called,) = tool_calls.stored_when_called
    assert stored_when_called == {
        "schema_version": "flow-step-attempt-input.v1",
        "tool_call_start": {
            "mcp_server_id": str(tool_flow.server_id),
            "tool_id": str(tool_flow.tool_id),
            "tool_name": "lookup_case",
            "published_input_schema_sha256": canonical_json_hash(_SCHEMA),
            "current_input_schema_sha256": canonical_json_hash(_SCHEMA),
            "arguments": {"case_id": "A-17"},
        },
    }
    public, edges = await _public_attempt(db_container, run)
    assert public.tool_call_state == "answered"
    stored = public.input_payload_json
    assert stored.start is not None and stored.resolved_input is not None
    assert (
        stored.tool_call_start.model_dump(mode="json")
        == (stored_when_called["tool_call_start"])
    )
    answer_edge = next(
        edge for edge in edges.aggregate.edges if edge.binding_ref == "tool.answer"
    )
    assert stored.tool_call_result.outcome == "answered"
    assert (
        stored.tool_call_result.answer_sha256,
        stored.tool_call_result.answer_byte_size,
    ) == (answer_edge.selection.sha256, answer_edge.selection.byte_size)


async def _cancel(db_container, run: FlowRun) -> None:
    async with db_container() as container:
        await container.flow_run_service().cancel_run(
            run_id=run.id, flow_id=run.flow_id
        )


@pytest.mark.parametrize("cancelled", ["before_the_start", "during_the_call"])
async def test_a_run_cancelled_around_the_call_keeps_only_what_was_stored(
    db_container,
    admin_user,
    tool_flow: ToolFlow,  # noqa: F811
    tool_calls: ToolCalls,
    cancelled: str,
) -> None:
    # Kills the mutants that send the call although the start found the
    # attempt closed, that write a result on (or reopen) the closed attempt,
    # and that end the run as a failed step instead of following the
    # cancellation it already has. A start without a result on the closed
    # attempt reads as interrupted, never as an answer.
    run = await _published_run(db_container, tool_flow)
    tool_calls.run_id = run.id

    async def cancel() -> None:
        await _cancel(db_container, run)

    if cancelled == "before_the_start":
        tool_calls.before_call = cancel
    else:
        tool_calls.during_call = cancel

    result = await _execute(run, admin_user)

    assert result == {"status": "skipped", "reason": "run_cancelled"}
    async with db_container() as container:
        ended = await container.flow_run_repo().get(
            run_id=run.id, tenant_id=run.tenant_id
        )
    assert ended.status == FlowRunStatus.CANCELLED
    public, _ = await _public_attempt(db_container, run)
    assert public.status.value == "cancelled"
    if cancelled == "before_the_start":
        assert tool_calls.received == []
        assert public.input_payload_json is None
        assert public.tool_call_state is None
        return
    assert tool_calls.received == [{"case_id": "A-17"}]
    stored = await _attempt_input(run.id)
    assert stored == tool_calls.stored_when_called[0]
    assert public.tool_call_state == "interrupted"


_START = {
    "mcp_server_id": str(uuid4()),
    "tool_id": str(uuid4()),
    "tool_name": "lookup_case",
    "published_input_schema_sha256": "a" * 64,
    "current_input_schema_sha256": "a" * 64,
    "arguments": {"case_id": "A-17"},
}


def _record(**result: object) -> dict[str, Any]:
    from eneo.flows.domain.flow_step_attempt_input import (
        FlowStepAttemptToolCallResult,
        FlowStepAttemptToolCallStart,
    )

    return {
        "start": FlowStepAttemptToolCallStart.model_validate_json(json.dumps(_START)),
        "result": (
            FlowStepAttemptToolCallResult.model_validate(result) if result else None
        ),
    }


async def _running_attempt(admin_user, factories: tuple[Any, ...]) -> tuple[Any, Any]:
    completion_model_factory, space_factory, assistant_factory = factories
    async with sessionmanager.session() as session, session.begin():
        run, flow, _ = await _create_running_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
    return run, flow.steps[0].id


async def _write(run: FlowRun, step_id: UUID, attempt_no: int = 1, **result: Any):
    async with sessionmanager.session() as session, session.begin():
        return await FlowRunRepository(
            session=session
        ).write_attempt_tool_call_evidence(
            run_id=run.id,
            step_id=step_id,
            attempt_no=attempt_no,
            tenant_id=run.tenant_id,
            **_record(**result),
        )


_ANSWERED = {
    "outcome": "answered",
    "duration_ms": 5,
    "answer_byte_size": 3,
    "answer_sha256": "b" * 64,
}


async def test_the_call_record_changes_only_its_fields_on_an_open_attempt_it_owns(
    setup_database,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
) -> None:
    # Kills the mutants that let the write freeze resolved-input edges, that
    # let a later activation drop the record, that let a stored result be
    # replaced, that write for a worker whose lease is gone, and that read a
    # missing attempt as a closed one.
    from eneo.flows.domain.flow_run_exceptions import (
        FlowExecutionOwnershipLost,
        FlowRunPersistenceInvariantError,
    )
    from eneo.flows.domain.flow_step_attempt_input import (
        FlowStepAttemptInputConflictError,
        FlowStepAttemptStart,
    )
    from eneo.flows.runtime.step_result_builder import build_activated_attempt_input

    run, step_id = await _running_attempt(
        admin_user, (completion_model_factory, space_factory, assistant_factory)
    )
    owner = FlowRunExecutionOwner(run.id, run.tenant_id, run.revision)
    token = flow_run_execution_owner.set(owner)
    try:
        assert await _write(run, step_id) == "written"
        assert await _attempt_input(run.id) == {
            "schema_version": "flow-step-attempt-input.v1",
            "tool_call_start": _START,
        }
        async with sessionmanager.session() as session, session.begin():
            edge_rows = await session.scalar(
                sa.select(sa.func.count()).select_from(FlowStepAttemptResolvedInputs)
            )
        assert edge_rows == 0
        start = FlowStepAttemptStart(resolved_timeout_seconds=60, input_text_length=3)
        async with sessionmanager.session() as session, session.begin():
            activated = await FlowRunRepository(session=session).activate_step_attempt(
                run_id=run.id,
                step_id=step_id,
                attempt_no=1,
                tenant_id=run.tenant_id,
                resolved_input_edges=FlowResolvedInputEdges.model_validate(
                    {"schema_version": 1, "edges": []}
                ),
                attempt_input=build_activated_attempt_input(start=start),
            )
        assert activated is not None
        assert await _write(run, step_id, **_ANSWERED) == "written"
        with pytest.raises(FlowStepAttemptInputConflictError):
            await _write(run, step_id, **{**_ANSWERED, "duration_ms": 6})
        with pytest.raises(FlowRunPersistenceInvariantError):
            await _write(run, step_id, attempt_no=2)
        flow_run_execution_owner.set(
            FlowRunExecutionOwner(run.id, run.tenant_id, run.revision - 1)
        )
        with pytest.raises(FlowExecutionOwnershipLost):
            await _write(run, step_id, **{**_ANSWERED, "duration_ms": 7})
    finally:
        flow_run_execution_owner.reset(token)

    stored = await _attempt_input(run.id)
    assert stored == {
        "schema_version": "flow-step-attempt-input.v1",
        "start": start.model_dump(mode="json", exclude_none=True),
        "tool_call_start": _START,
        "tool_call_result": _ANSWERED,
    }


async def _wait_until_blocked_by(pid: int) -> None:
    """Until a session of the database waits for a lock that ``pid`` holds."""
    for _ in range(200):
        async with sessionmanager.session() as session, session.begin():
            waiting = await session.scalar(
                sa.text(
                    "select count(*) from pg_stat_activity "
                    "where :pid = any(pg_blocking_pids(pid))"
                ),
                {"pid": pid},
            )
        if waiting:
            return
        await asyncio.sleep(0.025)
    raise AssertionError("no session waited for the terminalization's lock")


async def test_a_result_waits_for_the_terminalization_holding_the_run_and_changes_nothing(
    setup_database,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
) -> None:
    # Kills the mutants that lock the attempt before the run (against the
    # terminalization's order, the two sessions deadlock), that assert the
    # lease before reading the closed attempt (the worker would see its
    # ownership lost instead of the run's outcome), and that write the result
    # onto the attempt the terminalization closed.
    run, step_id = await _running_attempt(
        admin_user, (completion_model_factory, space_factory, assistant_factory)
    )
    token = flow_run_execution_owner.set(
        FlowRunExecutionOwner(run.id, run.tenant_id, run.revision)
    )
    try:
        assert await _write(run, step_id) == "written"
        async with sessionmanager.session() as terminal_session:
            async with terminal_session.begin():
                await terminal_session.scalar(
                    sa.select(FlowRuns.id)
                    .where(FlowRuns.id == run.id)
                    .with_for_update()
                )
                terminal_pid = await terminal_session.scalar(
                    sa.text("select pg_backend_pid()")
                )
                write = asyncio.create_task(_write(run, step_id, **_ANSWERED))
                await _wait_until_blocked_by(terminal_pid)
                terminal_repo = FlowRunRepository(session=terminal_session)
                terminalized = await FlowRunTerminalizer(
                    terminal_repo,
                    terminal_repo.audit_outbox_repo,
                    FlowRunReviewCheckpointRepository(
                        session=terminal_session,
                        audit_outbox_repo=terminal_repo.audit_outbox_repo,
                    ),
                ).terminalize_run(
                    run_id=run.id,
                    tenant_id=run.tenant_id,
                    target_status=FlowRunStatus.FAILED,
                    source=FlowRunLifecycleSource.EXECUTOR_FAILED,
                    error=FlowRunError.from_source(
                        FlowRunLifecycleSource.EXECUTOR_FAILED,
                        code=FlowApiErrorCode.STEP_ATTEMPT_START_FAILED,
                        message="Terminalization won the race.",
                    ),
                )
                assert terminalized.did_transition is True
                blocked_until_the_terminal_commit = not write.done()
        written = await asyncio.wait_for(write, timeout=10)
    finally:
        flow_run_execution_owner.reset(token)

    assert blocked_until_the_terminal_commit is True
    assert written == "attempt_closed"
    assert await _attempt_input(run.id) == {
        "schema_version": "flow-step-attempt-input.v1",
        "tool_call_start": _START,
    }
