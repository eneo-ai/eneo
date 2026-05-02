from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.authentication.principal_types import PrincipalType
from intric.database.database import sessionmanager
from intric.database.tables.flow_tables import (
    FlowRunRerunInvalidatedSteps,
    FlowRunRerunOperations,
    FlowRuns,
    FlowStepResults,
)
from intric.flows import (
    Flow,
    FlowFactory,
    FlowRepository,
    FlowStep,
    FlowVersionRepository,
)
from intric.flows.enums import (
    FlowRunRerunInvalidationRole,
    FlowRunRerunOperationStatus,
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
    RerunDependencyKind,
)
from intric.flows.flow_run_rerun_graph import (
    RerunInvalidatedStep,
    build_rerun_invalidation_graph,
)
from intric.flows.infrastructure.flow_run_repo import (
    _RERUN_STEP_RESULT_RESET_VALUES,
    FlowRunRepository,
)
from intric.flows.published_definition import (
    build_published_definition_json,
    parse_published_runtime_steps,
)
from intric.main.exceptions import BadRequestException, NotFoundException


@dataclass(frozen=True, slots=True)
class RerunRepositoryScenario:
    tenant_id: UUID
    flow_id: UUID
    flow_run_id: UUID
    requested_by_user_id: UUID
    root_step_id: UUID
    step_ids: tuple[UUID, UUID, UUID]
    invalidated_steps: tuple[RerunInvalidatedStep, ...]


class _RollbackMarker(Exception):
    pass


def _require_uuid(value: UUID | None) -> UUID:
    assert value is not None
    return value


def _build_flow(
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    assistant_id: UUID,
) -> Flow:
    return Flow(
        id=None,
        tenant_id=tenant_id,
        space_id=space_id,
        name=f"Rerun repository flow {uuid4()}",
        description="Flow used for rerun repository command tests.",
        created_by_user_id=user_id,
        owner_user_id=user_id,
        published_version=None,
        metadata_json=None,
        data_retention_days=30,
        created_at=None,
        updated_at=None,
        steps=[
            FlowStep(
                id=None,
                flow_id=uuid4(),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                step_order=1,
                user_description="Source",
                input_source="flow_input",
                input_type="text",
                input_contract=None,
                output_mode="pass_through",
                output_type="json",
                output_contract={"type": "object"},
                input_bindings={"question": "{{flow.input.case_id}}"},
                output_classification_override=None,
                mcp_policy="inherit",
                input_config=None,
                output_config=None,
            ),
            FlowStep(
                id=None,
                flow_id=uuid4(),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                step_order=2,
                user_description="Normalize source",
                input_source="previous_step",
                input_type="json",
                input_contract=None,
                output_mode="pass_through",
                output_type="text",
                output_contract=None,
                input_bindings=None,
                output_classification_override=None,
                mcp_policy="inherit",
                input_config=None,
                output_config=None,
            ),
            FlowStep(
                id=None,
                flow_id=uuid4(),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                step_order=3,
                user_description="Summarize",
                input_source="previous_step",
                input_type="text",
                input_contract=None,
                output_mode="pass_through",
                output_type="text",
                output_contract=None,
                input_bindings=None,
                output_classification_override=None,
                mcp_policy="inherit",
                input_config=None,
                output_config=None,
            ),
        ],
    )


def _published_definition_for_flow(flow: Flow) -> dict[str, object]:
    first_step, second_step, third_step = flow.steps
    return build_published_definition_json(
        flow_id=_require_uuid(flow.id),
        name=flow.name,
        description=flow.description,
        metadata_json=flow.metadata_json,
        steps=[
            _published_step(first_step),
            _published_step(second_step),
            {
                **_published_step(third_step),
                "assistant_snapshot": {"instructions": "Use {{föregående_steg}}."},
            },
        ],
    )


def _published_step(step: FlowStep) -> dict[str, object]:
    return {
        "step_id": str(_require_uuid(step.id)),
        "assistant_id": str(step.assistant_id),
        "step_order": step.step_order,
        "user_description": step.user_description,
        "input_source": step.input_source.value,
        "input_type": step.input_type.value,
        "input_contract": step.input_contract,
        "input_bindings": step.input_bindings,
        "input_config": step.input_config,
        "output_mode": step.output_mode.value,
        "output_type": step.output_type.value,
        "output_contract": step.output_contract,
        "output_config": step.output_config,
        "output_classification_override": step.output_classification_override,
        "mcp_policy": step.mcp_policy.value,
    }


async def _create_completed_rerun_scenario(
    *,
    session: AsyncSession,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> RerunRepositoryScenario:
    model = await completion_model_factory(session, "gpt-4o-mini")
    space = await space_factory(session, f"Rerun repo space {uuid4()}", [model.id])
    assistant = await assistant_factory(
        session,
        f"Rerun repo assistant {uuid4()}",
        model.id,
        space_id=space.id,
    )

    flow_repo = FlowRepository(session=session, factory=FlowFactory())
    flow = await flow_repo.create(
        flow=_build_flow(
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=admin_user.id,
            assistant_id=assistant.id,
        ),
        tenant_id=admin_user.tenant_id,
    )
    flow = await flow_repo.update(
        flow=flow.model_copy(update={"published_version": 1}),
        tenant_id=admin_user.tenant_id,
    )

    definition_json = _published_definition_for_flow(flow)
    await FlowVersionRepository(session=session, factory=FlowFactory()).create(
        flow_id=_require_uuid(flow.id),
        version=1,
        definition_checksum=f"checksum-rerun-{uuid4()}",
        definition_json=definition_json,
        tenant_id=admin_user.tenant_id,
    )

    run_repo = FlowRunRepository(session=session, factory=FlowFactory())
    run = await run_repo.create(
        flow_id=_require_uuid(flow.id),
        flow_version=1,
        user_id=admin_user.id,
        principal_type=PrincipalType.USER.value,
        principal_user_id=admin_user.id,
        tenant_id=admin_user.tenant_id,
        input_payload_json={"case_id": "case-123"},
        preseed_steps=[
            {
                "step_id": _require_uuid(step.id),
                "assistant_id": step.assistant_id,
                "step_order": step.step_order,
            }
            for step in flow.steps
        ],
        idempotency_key="create-run-key",
        request_fingerprint="create-run-fingerprint",
    )
    await _mark_run_completed(
        session=session,
        run_repo=run_repo,
        flow=flow,
        flow_run_id=run.id,
        tenant_id=admin_user.tenant_id,
    )
    runtime_steps = parse_published_runtime_steps(definition_json)
    graph = build_rerun_invalidation_graph(
        steps=runtime_steps,
        root_step_id=_require_uuid(flow.steps[0].id),
    )
    return RerunRepositoryScenario(
        tenant_id=admin_user.tenant_id,
        flow_id=_require_uuid(flow.id),
        flow_run_id=run.id,
        requested_by_user_id=admin_user.id,
        root_step_id=_require_uuid(flow.steps[0].id),
        step_ids=tuple(_require_uuid(step.id) for step in flow.steps),
        invalidated_steps=graph.invalidated_steps,
    )


async def _mark_run_completed(
    *,
    session: AsyncSession,
    run_repo: FlowRunRepository,
    flow: Flow,
    flow_run_id: UUID,
    tenant_id: UUID,
) -> None:
    now = datetime.now(timezone.utc)
    await session.execute(
        sa.update(FlowRuns)
        .where(FlowRuns.id == flow_run_id)
        .where(FlowRuns.tenant_id == tenant_id)
        .values(
            status=FlowRunStatus.COMPLETED.value,
            revision=1,
            output_payload_json={"answer": "complete"},
            error_message="previous error is cleared by completion",
            started_at=now,
            finished_at=now,
            cancelled_at=now,
        )
    )
    for step in flow.steps:
        step_id = _require_uuid(step.id)
        attempt = await run_repo.create_or_get_attempt_started(
            run_id=flow_run_id,
            flow_id=_require_uuid(flow.id),
            tenant_id=tenant_id,
            step_id=step_id,
            step_order=step.step_order,
            attempt_no=1,
            celery_task_id=f"task-{step.step_order}",
        )
        finished_attempt = await run_repo.finish_attempt(
            run_id=flow_run_id,
            step_id=step_id,
            attempt_no=1,
            tenant_id=tenant_id,
            status=FlowStepAttemptStatus.COMPLETED,
        )
        assert finished_attempt is not None
        await session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == flow_run_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .where(FlowStepResults.step_id == step_id)
            .values(
                status=FlowStepResultStatus.COMPLETED.value,
                current_attempt_no=attempt.attempt_no,
                input_payload_json={"input": f"step-{step.step_order}"},
                output_payload_json={"text": f"output-{step.step_order}"},
                effective_prompt=f"prompt-{step.step_order}",
                model_parameters_json={"temperature": 0},
                num_tokens_input=step.step_order,
                num_tokens_output=step.step_order + 10,
                error_message=f"old-error-{step.step_order}",
                flow_step_execution_hash=f"hash-{step.step_order}",
                tool_calls_metadata={"calls": []},
                started_at=now,
                finished_at=now,
            )
        )


async def _accept_rerun(
    *,
    session: AsyncSession,
    scenario: RerunRepositoryScenario,
    fingerprint: str = "rerun-fingerprint",
    expected_run_revision: int = 1,
    invalidated_steps: tuple[RerunInvalidatedStep, ...] | None = None,
):
    return await FlowRunRepository(
        session=session,
        factory=FlowFactory(),
    ).accept_or_replay_rerun_operation(
        tenant_id=scenario.tenant_id,
        flow_id=scenario.flow_id,
        flow_run_id=scenario.flow_run_id,
        rerun_step_id=scenario.root_step_id,
        rerun_step_order=1,
        request_fingerprint=fingerprint,
        expected_run_revision=expected_run_revision,
        reason="Regenerate source output after reviewer edit.",
        input_payload_json={"case_id": "case-456"},
        step_inputs_json={"1": {"case_id": "case-456"}},
        requested_by_user_id=scenario.requested_by_user_id,
        invalidated_steps=(
            scenario.invalidated_steps
            if invalidated_steps is None
            else invalidated_steps
        ),
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_accept_rerun_operation_resets_run_results_and_records_invalidation(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_completed_rerun_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        run_before = await session.scalar(
            sa.select(FlowRuns).where(FlowRuns.id == scenario.flow_run_id)
        )
        assert run_before is not None

        accepted = await _accept_rerun(session=session, scenario=scenario)
        replayed = await _accept_rerun(session=session, scenario=scenario)

        assert accepted.created is True
        assert replayed.created is False
        assert accepted.operation.id == replayed.operation.id
        assert accepted.operation.status == FlowRunRerunOperationStatus.QUEUED
        assert accepted.operation.expected_run_revision == 1
        assert accepted.operation.accepted_run_revision == 1
        assert accepted.operation.root_attempt_no == 2
        assert accepted.operation.root_attempt_id is None
        assert accepted.run.status == FlowRunStatus.QUEUED
        assert accepted.run.revision == 2
        assert accepted.run.trace_id == run_before.trace_id
        assert accepted.run.input_payload_json == {"case_id": "case-123"}
        assert accepted.run.output_payload_json is None
        assert accepted.run.error_message is None
        assert accepted.run.started_at is None
        assert accepted.run.finished_at is None
        assert accepted.run.cancelled_at is None

        invalidated = accepted.invalidated_steps
        assert [row.step_id for row in invalidated] == list(scenario.step_ids)
        assert [row.invalidation_order for row in invalidated] == [1, 2, 3]
        assert invalidated[0].role == FlowRunRerunInvalidationRole.ROOT
        assert invalidated[0].dependency_sources_json == []
        assert invalidated[1].role == FlowRunRerunInvalidationRole.DOWNSTREAM
        assert invalidated[1].dependency_sources_json == [
            RerunDependencyKind.INPUT_SOURCE_PREVIOUS_STEP
        ]
        assert invalidated[2].dependency_sources_json == [
            RerunDependencyKind.INPUT_SOURCE_PREVIOUS_STEP,
            RerunDependencyKind.RUNTIME_ALIAS_PREVIOUS_STEP,
        ]
        assert all(row.prior_step_result_id is not None for row in invalidated)
        assert all(row.prior_attempt_id is not None for row in invalidated)
        assert all(row.new_attempt_no is None for row in invalidated)
        assert all(row.new_attempt_id is None for row in invalidated)

        result_rows = (
            (
                await session.execute(
                    sa.select(FlowStepResults)
                    .where(FlowStepResults.flow_run_id == scenario.flow_run_id)
                    .order_by(FlowStepResults.step_order.asc())
                )
            )
            .scalars()
            .all()
        )
        assert [row.step_id for row in result_rows] == list(scenario.step_ids)
        for row in result_rows:
            assert {
                column_name: getattr(row, column_name)
                for column_name in _RERUN_STEP_RESULT_RESET_VALUES
            } == _RERUN_STEP_RESULT_RESET_VALUES

        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == scenario.flow_run_id)
            .values(status=FlowRunStatus.RUNNING.value)
        )
        replayed_after_run_update = await _accept_rerun(
            session=session,
            scenario=scenario,
        )

        assert replayed_after_run_update.created is False
        assert replayed_after_run_update.operation.id == accepted.operation.id
        assert replayed_after_run_update.run.status == FlowRunStatus.RUNNING
        assert replayed_after_run_update.run.revision == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_accept_rerun_operation_rolls_back_with_caller_transaction(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session, session.begin():
        scenario = await _create_completed_rerun_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )

    with pytest.raises(_RollbackMarker):
        async with sessionmanager.session() as session, session.begin():
            await _accept_rerun(session=session, scenario=scenario)
            raise _RollbackMarker

    async with sessionmanager.session() as session, session.begin():
        operation_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.flow_run_id == scenario.flow_run_id)
        )
        run_state = (
            await session.execute(
                sa.select(FlowRuns.status, FlowRuns.revision).where(
                    FlowRuns.id == scenario.flow_run_id
                )
            )
        ).one()
        result_statuses = (
            (
                await session.execute(
                    sa.select(FlowStepResults.status)
                    .where(FlowStepResults.flow_run_id == scenario.flow_run_id)
                    .order_by(FlowStepResults.step_order.asc())
                )
            )
            .scalars()
            .all()
        )

    assert operation_count == 0
    assert run_state == (FlowRunStatus.COMPLETED.value, 1)
    assert result_statuses == [FlowStepResultStatus.COMPLETED.value] * 3


@pytest.mark.asyncio
@pytest.mark.integration
async def test_same_fingerprint_concurrent_reruns_share_one_operation(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session, session.begin():
        scenario = await _create_completed_rerun_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )

    async def _accept_from_worker() -> UUID:
        async with sessionmanager.session() as session, session.begin():
            result = await _accept_rerun(session=session, scenario=scenario)
            return result.operation.id

    operation_ids = await asyncio.gather(*[_accept_from_worker() for _ in range(6)])

    assert len(set(operation_ids)) == 1
    async with sessionmanager.session() as session, session.begin():
        operation_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.flow_run_id == scenario.flow_run_id)
        )
        invalidated_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunRerunInvalidatedSteps)
            .where(
                FlowRunRerunInvalidatedSteps.operation_id == operation_ids[0],
            )
        )
        run_revision = await session.scalar(
            sa.select(FlowRuns.revision).where(FlowRuns.id == scenario.flow_run_id)
        )

    assert operation_count == 1
    assert invalidated_count == 3
    assert run_revision == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_stale_revision_rejects_without_mutation(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_completed_rerun_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )

        with pytest.raises(BadRequestException) as exc_info:
            await _accept_rerun(
                session=session,
                scenario=scenario,
                expected_run_revision=0,
            )

        operation_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.flow_run_id == scenario.flow_run_id)
        )
        run_state = (
            await session.execute(
                sa.select(FlowRuns.status, FlowRuns.revision).where(
                    FlowRuns.id == scenario.flow_run_id
                )
            )
        ).one()

    assert exc_info.value.code == "flow_run_rerun_stale_revision"
    assert operation_count == 0
    assert run_state == (FlowRunStatus.COMPLETED.value, 1)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "run_status",
    [
        FlowRunStatus.QUEUED,
        FlowRunStatus.RUNNING,
        FlowRunStatus.CANCELLED,
    ],
)
async def test_active_or_cancelled_run_rejects_without_mutation(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    run_status: FlowRunStatus,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_completed_rerun_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == scenario.flow_run_id)
            .values(status=run_status.value)
        )

        with pytest.raises(BadRequestException) as exc_info:
            await _accept_rerun(session=session, scenario=scenario)

        operation_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.flow_run_id == scenario.flow_run_id)
        )

    assert exc_info.value.code == "flow_run_rerun_invalid_transition"
    assert operation_count == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_failed_root_step_result_rejects_without_mutation(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_completed_rerun_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == scenario.flow_run_id)
            .values(status=FlowRunStatus.FAILED.value)
        )
        await session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == scenario.flow_run_id)
            .where(FlowStepResults.step_id == scenario.root_step_id)
            .values(status=FlowStepResultStatus.FAILED.value)
        )

        with pytest.raises(BadRequestException) as exc_info:
            await _accept_rerun(session=session, scenario=scenario)

        operation_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.flow_run_id == scenario.flow_run_id)
        )

    assert exc_info.value.code == "flow_run_rerun_step_incomplete"
    assert operation_count == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_missing_downstream_current_result_rejects_without_mutation(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_completed_rerun_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        await session.execute(
            sa.delete(FlowStepResults)
            .where(FlowStepResults.flow_run_id == scenario.flow_run_id)
            .where(FlowStepResults.step_id == scenario.step_ids[2])
        )

        with pytest.raises(BadRequestException) as exc_info:
            await _accept_rerun(session=session, scenario=scenario)

        operation_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.flow_run_id == scenario.flow_run_id)
        )
        run_state = (
            await session.execute(
                sa.select(FlowRuns.status, FlowRuns.revision).where(
                    FlowRuns.id == scenario.flow_run_id
                )
            )
        ).one()

    assert exc_info.value.code == "flow_run_rerun_step_incomplete"
    assert operation_count == 0
    assert run_state == (FlowRunStatus.COMPLETED.value, 1)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_missing_step_from_invalidation_graph_rejects_without_mutation(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_completed_rerun_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )

        with pytest.raises(BadRequestException) as exc_info:
            await _accept_rerun(
                session=session,
                scenario=scenario,
                invalidated_steps=(),
            )

        operation_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.flow_run_id == scenario.flow_run_id)
        )

    assert exc_info.value.code == "flow_run_rerun_step_not_found"
    assert operation_count == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_wrong_tenant_cannot_accept_rerun(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_completed_rerun_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        wrong_tenant = scenario.__class__(
            tenant_id=uuid4(),
            flow_id=scenario.flow_id,
            flow_run_id=scenario.flow_run_id,
            requested_by_user_id=scenario.requested_by_user_id,
            root_step_id=scenario.root_step_id,
            step_ids=scenario.step_ids,
            invalidated_steps=scenario.invalidated_steps,
        )

        with pytest.raises(NotFoundException):
            await _accept_rerun(session=session, scenario=wrong_tenant)

        operation_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.flow_run_id == scenario.flow_run_id)
        )

    assert operation_count == 0
