"""A run that completed a tool step, failed at a later step and was retried
from its first unfinished step, on real sessions: how the run it creates
counts the tool step it took over, and what it says when its dispatch is
exhausted."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.authentication.principal_types import PrincipalType
from eneo.database.tables.flow_tables import FlowRuns
from eneo.database.tables.mcp_server_table import MCPServers, SpacesMCPServers
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassifications,
)
from eneo.flows.application.flow_dispatch import (
    dispatch_flow_run_recoverably_after_commit,
)
from eneo.flows.application.flow_run_retry_service import FlowRunRetryService
from eneo.flows.domain.flow import FlowRun, FlowStep
from eneo.flows.domain.flow_run_recovery_policy import FLOW_DISPATCH_MAX_ATTEMPTS
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import (
    FlowRunDispatchError,
    FlowRunDispatchErrorKind,
    FlowRunError,
    dump_flow_run_dispatch_error,
)
from eneo.flows.runtime import tasks as flow_runtime_tasks
from eneo.flows.runtime import tool_input
from eneo.flows.runtime.step_handlers.compose_text import ComposeTextStepHandler
from eneo.main.exceptions import TypedIOValidationException
from eneo.mcp_servers.application.unattended_tool_call import UnattendedToolCaller
from eneo.mcp_servers.infrastructure.client.mcp_client import MCPToolAnswer
from eneo.prompts.api.prompt_models import PromptCreate
from eneo.server.dependencies.container import load_container_upload_admission
from tests.integration.flows.test_flow_tool_step_sessions import (
    ToolFlow,
    _classify_the_server,
    tool_flow,  # noqa: F401  (registers the fixture)
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@dataclass
class ToolCalls:
    """The tool calls the runs made, and whether step 2 fails."""

    arguments: list[dict[str, object]]
    fail_step_two: bool = True


@pytest.fixture
async def tool_calls(monkeypatch) -> AsyncIterator[ToolCalls]:
    """The tool answers without a server, and step 2 fails until told not
    to. Everything else of the read and the run is the product's."""
    calls = ToolCalls(arguments=[])
    compose = ComposeTextStepHandler.execute

    async def call(
        self: UnattendedToolCaller,
        server: object,
        tool_name: str,
        arguments: dict[str, object],
        **_: object,
    ) -> MCPToolAnswer:
        calls.arguments.append(arguments)
        return MCPToolAnswer(("Ärende A-17 är öppet.",), 0, None, is_error=False)

    async def vetted(*_: object) -> None:
        return None

    async def execute(self: ComposeTextStepHandler, **kwargs: Any):
        if kwargs["step"].step_order == 2 and calls.fail_step_two:
            raise TypedIOValidationException(
                "Step 2: failed for the test.",
                code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
            )
        return await compose(self, **kwargs)

    monkeypatch.setattr(UnattendedToolCaller, "call", call)
    monkeypatch.setattr(tool_input, "_vet_server_address", vetted)
    monkeypatch.setattr(ComposeTextStepHandler, "execute", execute)
    yield calls


def _composing_step(assistant_id: UUID, step_order: int, **source: object) -> FlowStep:
    return FlowStep.model_validate(
        {
            "assistant_id": assistant_id,
            "step_order": step_order,
            "user_description": f"Steg {step_order}",
            "input_type": "text",
            "output_mode": "compose_text",
            "output_type": "text",
            **source,
        }
    )


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


async def _publish_and_fail_after_the_tool_step(
    db_container, admin_user, flow: ToolFlow, *, level: int | None = None
) -> FlowRun:
    """Publish the flow as a tool step and a step that reads it, with the
    tool's server activated in the flow's space (classifications on and the
    server at ``level`` when one is given), and run it: the tool step
    completes and step 2 fails."""
    if level is not None:
        await _classify_the_server(db_container, flow, level)
    async with db_container() as container:
        service = container.flow_service()
        second, _ = await service.create_flow_assistant(
            flow_id=flow.flow_id, name="steg2"
        )
        await service.update_flow_assistant(
            flow_id=flow.flow_id,
            assistant_id=second.id,
            update=AssistantUpdateCommand(prompt=PromptCreate(text="Läs svaret.")),
        )
        await service.update_flow(
            flow_id=flow.flow_id,
            steps=[
                _composing_step(
                    flow.assistant_id,
                    1,
                    input_source="tool",
                    input_config={"tool": flow.tool_config},
                ),
                _composing_step(second.id, 2, input_source="previous_step"),
            ],
        )
        if level is None:
            container.session().add(
                SpacesMCPServers(space_id=flow.space_id, mcp_server_id=flow.server_id)
            )
            await container.session().flush()
        await service.publish_flow(flow_id=flow.flow_id)
        source = (
            await container.flow_run_service().create_run(
                flow_id=flow.flow_id,
                input_payload_json={"text": "A-17"},
                expected_flow_version=1,
                idempotency_key=f"tool-step-retry-{uuid4()}",
            )
        ).run
    result = await _execute(source, admin_user)
    assert result["status"] == "failed"
    return source


async def _retry(db_container, source: FlowRun) -> FlowRun:
    async with db_container() as container:
        await load_container_upload_admission(container)
        result = await FlowRunRetryService(
            user=container.user(),
            run_service=container.flow_run_service(),
            access_policy=container.flow_run_access_policy(),
            run_repo=container.flow_run_repo(),
            flow_repo=container.flow_repo(),
            checkpoint_repo=container.flow_run_review_checkpoint_repo(),
            audit_service=container.audit_service(),
        ).retry_from_failed_step(
            flow_id=source.flow_id,
            run_id=source.id,
            idempotency_key=f"tool-step-retry-{uuid4()}",
        )
    assert result.reused_step_orders == (1,)
    return result.run_result.run


async def _exhaust_dispatch(db_container, run: FlowRun) -> FlowRunError:
    """The run's error after its last dispatch was refused and its epoch is
    due: the dispatcher ends the run."""
    due = datetime.now(timezone.utc) - timedelta(minutes=1)
    async with db_container() as container:
        await container.session().execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run.id)
            .values(
                dispatch_attempt_count=FLOW_DISPATCH_MAX_ATTEMPTS,
                dispatch_last_attempt_at=due,
                dispatch_next_attempt_at=due,
                dispatch_last_error=dump_flow_run_dispatch_error(
                    FlowRunDispatchError.from_kind(
                        FlowRunDispatchErrorKind.EXECUTION_BACKEND_FAILURE
                    )
                ),
            )
        )
    await dispatch_flow_run_recoverably_after_commit(
        run_id=run.id, tenant_id=run.tenant_id, expected_revision=run.revision
    )
    async with db_container() as container:
        ended = await container.flow_run_repo().get(
            run_id=run.id, tenant_id=run.tenant_id
        )
    assert ended.error is not None
    assert ended.error.code is FlowApiErrorCode.RUN_DISPATCH_FAILED
    return ended.error


async def test_a_retried_runs_dispatch_failure_is_not_retryable_after_its_tool_step(
    db_container,
    admin_user,
    tool_flow: ToolFlow,  # noqa: F811
    tool_calls: ToolCalls,
) -> None:
    # Kills the mutants that decide from the evidence of the run's attempts
    # (the run a retry creates holds the tool step it took over without the
    # read's evidence, so the error said a new run would repeat nothing), or
    # that count every tool step of the definition (a run of the same flow
    # that has completed none stays retryable).
    source = await _publish_and_fail_after_the_tool_step(
        db_container, admin_user, tool_flow
    )
    child = await _retry(db_container, source)
    async with db_container() as container:
        fresh = (
            await container.flow_run_service().create_run(
                flow_id=tool_flow.flow_id,
                input_payload_json={"text": "A-18"},
                expected_flow_version=1,
                idempotency_key=f"tool-step-retry-{uuid4()}",
            )
        ).run

    after_the_tool_step = await _exhaust_dispatch(db_container, child)
    before_it = await _exhaust_dispatch(db_container, fresh)

    assert len(tool_calls.arguments) == 1
    assert after_the_tool_step.retryable is False
    assert after_the_tool_step.details is not None
    assert after_the_tool_step.details.tool_call_possible is True
    assert before_it.retryable is True
    assert before_it.details is None


@pytest.mark.parametrize("level", [2, None], ids=["classified", "unclassified"])
async def test_a_retried_run_counts_its_tool_step_at_the_recorded_level_without_a_call(
    db_container,
    admin_user,
    tool_flow: ToolFlow,  # noqa: F811
    tool_calls: ToolCalls,
    level: int | None,
) -> None:
    # Kills the mutants where the import of the completed steps leaves the
    # tool step without its tool_answer edge (the run fails before its steps
    # on the preflight's invariant), copies an edge from an earlier step
    # with the attempt number it had in the source run, or where the run
    # counts the server at its level now (raised to 3 after the source run)
    # or reads the tool again.
    source = await _publish_and_fail_after_the_tool_step(
        db_container, admin_user, tool_flow, level=level
    )
    if level is not None:
        async with db_container() as container:
            await container.session().execute(
                sa.update(SecurityClassifications)
                .where(
                    SecurityClassifications.id
                    == sa.select(MCPServers.security_classification_id)
                    .where(MCPServers.id == tool_flow.server_id)
                    .scalar_subquery()
                )
                .values(security_level=3)
            )
    child = await _retry(db_container, source)
    tool_calls.fail_step_two = False

    result = await _execute(child, admin_user)

    assert result["status"] == "completed"
    assert len(tool_calls.arguments) == 1
    async with db_container() as container:
        run_repo = container.flow_run_repo()
        answers = await run_repo.list_completed_tool_answers(
            run_id=child.id, tenant_id=child.tenant_id
        )
        levels = await container.session().execute(
            sa.select(FlowRuns.id, FlowRuns.evidence_classification_level).where(
                FlowRuns.id.in_([source.id, child.id])
            )
        )
    assert answers[1].server_classification_level == level
    # Off, a run's evidence is at level 0.
    evidence_level = 0 if level is None else level
    assert dict(levels.tuples().all()) == {
        source.id: evidence_level,
        child.id: evidence_level,
    }
