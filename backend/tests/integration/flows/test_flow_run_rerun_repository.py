from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.authentication.principal_types import PrincipalType
from eneo.database.database import sessionmanager
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    FlowRunRerunInvalidatedSteps,
    FlowRunRerunOperations,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRuntimeUploadedFiles,
    FlowStepAttempts,
    FlowStepResults,
)
from eneo.flows import FlowFactory, FlowRepository, FlowVersionRepository
from eneo.flows.application.flow_run_terminalization import FlowRunTerminalizer
from eneo.flows.domain.flow import Flow, FlowStep, RerunStepInputOverride
from eneo.flows.domain.flow_run_exceptions import FlowRunNotFoundError
from eneo.flows.domain.rerun_exceptions import (
    FlowRunRerunAttemptLineageConflictError,
    FlowRunRerunInvalidTransitionError,
    FlowRunRerunMissingCurrentResultsError,
    FlowRunRerunRootStepIncompleteError,
    FlowRunRerunStaleRevisionError,
    FlowRunRerunStepInputsInvalidError,
    FlowRunRerunStepNotFoundError,
)
from eneo.flows.enums import (
    FlowRunLifecycleSource,
    FlowRunRerunInvalidationRole,
    FlowRunRerunOperationStatus,
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
    RerunDependencyKind,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.flow_run_input_envelope import (
    RerunInputOverride,
)
from eneo.flows.flow_run_rerun_graph import (
    RerunInvalidatedStep,
    build_rerun_invalidation_graph,
)
from eneo.flows.flow_run_rerun_request import (
    FlowRunRerunRequestFingerprintInput,
    build_rerun_request_fingerprint,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_run_rerun_repo import FlowRunRerunRepository
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.principal import FlowPrincipal
from eneo.flows.published_definition import (
    build_published_definition_json,
    parse_published_runtime_steps,
)

_DEFAULT_RERUN_FILE_IDS = object()
_EXPECTED_RERUN_STEP_RESULT_RESET_VALUES: dict[str, object] = {
    "status": FlowStepResultStatus.PENDING.value,
    "current_attempt_no": None,
    "input_payload_json": None,
    "output_payload_json": None,
    "effective_prompt": None,
    "model_parameters_json": None,
    "num_tokens_input": None,
    "num_tokens_output": None,
    "error_message": None,
    "flow_step_execution_hash": None,
    "started_at": None,
    "finished_at": None,
}


@dataclass(frozen=True, slots=True)
class RerunRepositoryScenario:
    tenant_id: UUID
    flow_id: UUID
    flow_run_id: UUID
    requested_by_user_id: UUID
    root_step_id: UUID
    rerun_file_ids: tuple[UUID, UUID]
    step_ids: tuple[UUID, UUID, UUID]
    invalidated_steps: tuple[RerunInvalidatedStep, ...]


class _RollbackMarker(Exception):
    pass


def _flow_run_terminalizer(run_repo: FlowRunRepository) -> FlowRunTerminalizer:
    return FlowRunTerminalizer(
        run_repo,
        FlowRunRerunRepository(
            session=run_repo.session,
            factory=run_repo.factory,
        ),
        run_repo.audit_outbox_repo,
        FlowRunReviewCheckpointRepository(
            session=run_repo.session,
            factory=run_repo.factory,
            audit_outbox_repo=run_repo.audit_outbox_repo,
        ),
    )


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


def _file(*, user_id: UUID, tenant_id: UUID, name: str) -> Files:
    return Files(
        name=name,
        text="rerun input file",
        blob=None,
        checksum=f"checksum-{name}",
        size=128,
        mimetype="application/pdf",
        file_type="document",
        transcription=None,
        owner_type="user",
        owner_user_id=user_id,
        owner_service_id=None,
        tenant_id=tenant_id,
    )


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
    rerun_file_a = _file(
        user_id=admin_user.id,
        tenant_id=admin_user.tenant_id,
        name=f"rerun-a-{uuid4()}.pdf",
    )
    rerun_file_b = _file(
        user_id=admin_user.id,
        tenant_id=admin_user.tenant_id,
        name=f"rerun-b-{uuid4()}.pdf",
    )
    session.add_all([rerun_file_a, rerun_file_b])
    await session.flush()

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
    definition_json = _published_definition_for_flow(flow)
    await FlowVersionRepository(session=session, factory=FlowFactory()).create(
        flow_id=_require_uuid(flow.id),
        version=1,
        definition_json=definition_json,
        tenant_id=admin_user.tenant_id,
    )
    flow = await flow_repo.update(
        flow=flow.model_copy(update={"published_version": 1}),
        tenant_id=admin_user.tenant_id,
    )
    root_step_id = _require_uuid(flow.steps[0].id)
    session.add_all(
        [
            FlowRuntimeUploadedFiles(
                file_id=rerun_file.id,
                flow_id=_require_uuid(flow.id),
                tenant_id=admin_user.tenant_id,
                uploaded_for_step_id=root_step_id,
                owner_type="user",
                owner_user_id=admin_user.id,
                owner_service_id=None,
            )
            for rerun_file in (rerun_file_a, rerun_file_b)
        ]
    )
    await session.flush()

    run_repo = FlowRunRepository(session=session, factory=FlowFactory())
    run = await run_repo.create(
        flow_id=_require_uuid(flow.id),
        flow_version=1,
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
    runtime_steps = parse_published_runtime_steps(
        definition_json,
        flow_version=1,
    )
    graph = build_rerun_invalidation_graph(
        steps=runtime_steps,
        root_step_id=root_step_id,
    )
    return RerunRepositoryScenario(
        tenant_id=admin_user.tenant_id,
        flow_id=_require_uuid(flow.id),
        flow_run_id=run.id,
        requested_by_user_id=admin_user.id,
        root_step_id=root_step_id,
        rerun_file_ids=(rerun_file_a.id, rerun_file_b.id),
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
    inline_payload_json: dict[str, object] | None = None,
    root_step_file_ids: tuple[UUID, ...] | None | object = _DEFAULT_RERUN_FILE_IDS,
    root_step_input_step_id: UUID | None = None,
    invalidated_steps: tuple[RerunInvalidatedStep, ...] | None = None,
):
    if root_step_file_ids is _DEFAULT_RERUN_FILE_IDS:
        root_step_input = RerunStepInputOverride(
            step_id=root_step_input_step_id or scenario.root_step_id,
            file_ids=scenario.rerun_file_ids,
        )
    elif root_step_file_ids is None:
        root_step_input = None
    else:
        root_step_input = RerunStepInputOverride(
            step_id=root_step_input_step_id or scenario.root_step_id,
            file_ids=root_step_file_ids,
        )

    return await FlowRunRerunRepository(
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
        rerun_input_override=RerunInputOverride(
            inline_payload_json=(
                {"case_id": "case-456"}
                if inline_payload_json is None
                else inline_payload_json
            ),
            root_step_input=root_step_input,
        ),
        requested_by_principal=FlowPrincipal(
            principal_type=PrincipalType.USER,
            principal_user_id=scenario.requested_by_user_id,
        ),
        invalidated_steps=(
            scenario.invalidated_steps
            if invalidated_steps is None
            else invalidated_steps
        ),
    )


def _build_rerun_fingerprint(
    *,
    scenario: RerunRepositoryScenario,
    expected_run_revision: int,
    root_step_file_ids: tuple[UUID, ...],
    prior_root_attempt_id: UUID | None,
) -> str:
    return build_rerun_request_fingerprint(
        FlowRunRerunRequestFingerprintInput(
            tenant_id=scenario.tenant_id,
            requested_by_principal_type=PrincipalType.USER,
            requested_by_user_id=scenario.requested_by_user_id,
            requested_by_service_id=None,
            flow_id=scenario.flow_id,
            flow_run_id=scenario.flow_run_id,
            rerun_step_id=scenario.root_step_id,
            expected_run_revision=expected_run_revision,
            prior_root_attempt_id=prior_root_attempt_id,
            input_payload_json={"case_id": "case-456"},
            root_step_inputs={scenario.root_step_id: root_step_file_ids},
        )
    )


@pytest.mark.parametrize(
    ("root_step_file_ids", "expected_override_requested"),
    (
        pytest.param(None, False, id="inherit-root-files"),
        pytest.param((), True, id="clear-root-files"),
        pytest.param(_DEFAULT_RERUN_FILE_IDS, True, id="replace-root-files"),
    ),
)
@pytest.mark.asyncio
@pytest.mark.integration
async def test_accept_rerun_records_root_step_input_override_intent(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    root_step_file_ids,
    expected_override_requested,
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

        accepted = await _accept_rerun(
            session=session,
            scenario=scenario,
            root_step_file_ids=root_step_file_ids,
        )

        assert (
            accepted.operation.root_step_input_override_requested
            is expected_override_requested
        )
        if expected_override_requested:
            expected_file_ids = (
                scenario.rerun_file_ids
                if root_step_file_ids is _DEFAULT_RERUN_FILE_IDS
                else tuple(root_step_file_ids or ())
            )
            assert accepted.operation.root_step_input_override is not None
            assert accepted.operation.root_step_input_override.step_id == (
                scenario.root_step_id
            )
            assert accepted.operation.root_step_input_override.file_ids == (
                expected_file_ids
            )
        else:
            assert accepted.operation.root_step_input_override is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_terminalizer_closes_active_rerun_operation_with_structured_failure_code(
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
        accepted = await _accept_rerun(session=session, scenario=scenario)
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())

        await _flow_run_terminalizer(run_repo).terminalize_run(
            run_id=scenario.flow_run_id,
            tenant_id=scenario.tenant_id,
            target_status=FlowRunStatus.FAILED,
            source=FlowRunLifecycleSource.TASK_FAILURE,
            error=FlowRunError.from_source(
                FlowRunLifecycleSource.TASK_FAILURE,
                code=FlowApiErrorCode.STEP_EXECUTION_FAILED,
                message="Step execution failed.",
            ),
        )

        operation_row = await session.scalar(
            sa.select(FlowRunRerunOperations).where(
                FlowRunRerunOperations.id == accepted.operation.id
            )
        )
        assert operation_row is not None
        assert operation_row.status == FlowRunRerunOperationStatus.FAILED.value
        assert (
            operation_row.failure_code == FlowApiErrorCode.STEP_EXECUTION_FAILED.value
        )
        assert operation_row.failure_message == "Step execution failed."


@pytest.mark.asyncio
@pytest.mark.integration
async def test_terminalizer_closes_active_rerun_operation_with_null_failure_code_without_structured_error(
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
        accepted = await _accept_rerun(session=session, scenario=scenario)
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())

        await _flow_run_terminalizer(run_repo).terminalize_run(
            run_id=scenario.flow_run_id,
            tenant_id=scenario.tenant_id,
            target_status=FlowRunStatus.CANCELLED,
            source=FlowRunLifecycleSource.USER_CANCEL,
        )

        operation_row = await session.scalar(
            sa.select(FlowRunRerunOperations).where(
                FlowRunRerunOperations.id == accepted.operation.id
            )
        )
        assert operation_row is not None
        assert operation_row.status == FlowRunRerunOperationStatus.CANCELLED.value
        assert operation_row.failure_code is None
        assert operation_row.failure_message is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_latest_completed_attempt_id_for_step_uses_highest_completed_attempt_number(
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
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        rerun_repo = FlowRunRerunRepository(session=session, factory=FlowFactory())
        first_attempt = await session.scalar(
            sa.select(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == scenario.flow_run_id)
            .where(FlowStepAttempts.step_id == scenario.root_step_id)
            .where(FlowStepAttempts.attempt_no == 1)
        )
        assert first_attempt is not None
        first_attempt_id = first_attempt.id
        second_attempt = await run_repo.create_or_get_attempt_started(
            run_id=scenario.flow_run_id,
            flow_id=scenario.flow_id,
            tenant_id=scenario.tenant_id,
            step_id=scenario.root_step_id,
            step_order=1,
            attempt_no=2,
            celery_task_id="root-attempt-2",
        )
        finished_second_attempt = await run_repo.finish_attempt(
            run_id=scenario.flow_run_id,
            step_id=scenario.root_step_id,
            attempt_no=2,
            tenant_id=scenario.tenant_id,
            status=FlowStepAttemptStatus.COMPLETED,
        )
        assert finished_second_attempt is not None
        second_attempt_id = second_attempt.id
        third_attempt = await run_repo.create_or_get_attempt_started(
            run_id=scenario.flow_run_id,
            flow_id=scenario.flow_id,
            tenant_id=scenario.tenant_id,
            step_id=scenario.root_step_id,
            step_order=1,
            attempt_no=3,
            celery_task_id="root-attempt-3",
        )
        failed_third_attempt = await run_repo.finish_attempt(
            run_id=scenario.flow_run_id,
            step_id=scenario.root_step_id,
            attempt_no=3,
            tenant_id=scenario.tenant_id,
            status=FlowStepAttemptStatus.FAILED,
            error_code="step_failed",
            error_message="Step failed.",
        )
        assert failed_third_attempt is not None
        third_attempt_id = third_attempt.id
        # Crossed timestamps prove attempt number, not wall-clock time, defines latest.
        first_started_at = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
        second_started_at = datetime(2026, 1, 1, 9, tzinfo=timezone.utc)
        third_started_at = datetime(2026, 1, 1, 11, tzinfo=timezone.utc)
        await session.execute(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.id == first_attempt_id)
            .values(started_at=first_started_at, finished_at=first_started_at)
        )
        await session.execute(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.id == second_attempt_id)
            .values(started_at=second_started_at, finished_at=second_started_at)
        )
        await session.execute(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.id == third_attempt_id)
            .values(started_at=third_started_at, finished_at=third_started_at)
        )

        latest_attempt_id = await rerun_repo.get_latest_completed_attempt_id_for_step(
            run_id=scenario.flow_run_id,
            flow_id=scenario.flow_id,
            tenant_id=scenario.tenant_id,
            step_id=scenario.root_step_id,
        )
        wrong_flow_attempt_id = (
            await rerun_repo.get_latest_completed_attempt_id_for_step(
                run_id=scenario.flow_run_id,
                flow_id=uuid4(),
                tenant_id=scenario.tenant_id,
                step_id=scenario.root_step_id,
            )
        )
        missing_step_attempt_id = (
            await rerun_repo.get_latest_completed_attempt_id_for_step(
                run_id=scenario.flow_run_id,
                flow_id=scenario.flow_id,
                tenant_id=scenario.tenant_id,
                step_id=uuid4(),
            )
        )

    assert latest_attempt_id == second_attempt_id
    assert wrong_flow_attempt_id is None
    assert missing_step_attempt_id is None


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

        requested_file_order = tuple(
            sorted(
                scenario.rerun_file_ids, key=lambda file_id: str(file_id), reverse=True
            )
        )

        accepted = await _accept_rerun(
            session=session,
            scenario=scenario,
            root_step_file_ids=requested_file_order,
        )
        projection_count_after_accept = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunStepInputFiles)
            .where(FlowRunStepInputFiles.flow_run_id == scenario.flow_run_id)
            .where(FlowRunStepInputFiles.step_id == scenario.root_step_id)
            .where(
                FlowRunStepInputFiles.attempt_no == accepted.operation.root_attempt_no
            )
        )
        replayed = await _accept_rerun(session=session, scenario=scenario)
        projection_count_after_replay = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunStepInputFiles)
            .where(FlowRunStepInputFiles.flow_run_id == scenario.flow_run_id)
            .where(FlowRunStepInputFiles.step_id == scenario.root_step_id)
            .where(
                FlowRunStepInputFiles.attempt_no == accepted.operation.root_attempt_no
            )
        )

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
        assert accepted.run.input_payload_json == {"case_id": "case-456"}
        assert replayed.run.revision == 2
        assert replayed.run.input_payload_json == accepted.run.input_payload_json
        assert accepted.operation.input_payload_json == {"case_id": "case-456"}
        assert accepted.operation.root_step_input_override is not None
        assert (
            accepted.operation.root_step_input_override.step_id == scenario.root_step_id
        )
        assert (
            accepted.operation.root_step_input_override.file_ids == requested_file_order
        )
        assert projection_count_after_accept == len(scenario.rerun_file_ids)
        assert projection_count_after_replay == projection_count_after_accept
        projection_rows = (
            (
                await session.execute(
                    sa.select(FlowRunStepInputFiles)
                    .where(FlowRunStepInputFiles.flow_run_id == scenario.flow_run_id)
                    .where(FlowRunStepInputFiles.step_id == scenario.root_step_id)
                    .where(
                        FlowRunStepInputFiles.attempt_no
                        == accepted.operation.root_attempt_no
                    )
                    .order_by(FlowRunStepInputFiles.ordinal.asc())
                )
            )
            .scalars()
            .all()
        )
        assert [
            (row.file_id, row.ordinal, row.step_order) for row in projection_rows
        ] == [
            (requested_file_order[0], 0, accepted.operation.rerun_step_order),
            (requested_file_order[1], 1, accepted.operation.rerun_step_order),
        ]
        listed_operations = await FlowRunRerunRepository(
            session=session,
            factory=FlowFactory(),
        ).list_rerun_operations_for_run(
            run_id=scenario.flow_run_id,
            tenant_id=scenario.tenant_id,
        )
        listed_operation = next(
            operation
            for operation in listed_operations
            if operation.id == accepted.operation.id
        )

        assert listed_operation.root_step_input_override is not None
        assert (
            listed_operation.root_step_input_override.file_ids == requested_file_order
        )
        assert accepted.run.output_payload_json is None
        assert accepted.run.error is None
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
                for column_name in _EXPECTED_RERUN_STEP_RESULT_RESET_VALUES
            } == _EXPECTED_RERUN_STEP_RESULT_RESET_VALUES

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
async def test_accept_rerun_distinguishes_ordered_file_input_sequences(
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
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        rerun_repo = FlowRunRerunRepository(session=session, factory=FlowFactory())
        first_order = scenario.rerun_file_ids
        reversed_order = tuple(reversed(first_order))
        prior_root_attempt_id = await session.scalar(
            sa.select(FlowStepAttempts.id)
            .where(FlowStepAttempts.flow_run_id == scenario.flow_run_id)
            .where(FlowStepAttempts.flow_id == scenario.flow_id)
            .where(FlowStepAttempts.tenant_id == scenario.tenant_id)
            .where(FlowStepAttempts.step_id == scenario.root_step_id)
            .where(FlowStepAttempts.attempt_no == 1)
        )
        assert prior_root_attempt_id is not None
        first_fingerprint = _build_rerun_fingerprint(
            scenario=scenario,
            expected_run_revision=1,
            root_step_file_ids=first_order,
            prior_root_attempt_id=prior_root_attempt_id,
        )
        same_revision_reversed_fingerprint = _build_rerun_fingerprint(
            scenario=scenario,
            expected_run_revision=1,
            root_step_file_ids=reversed_order,
            prior_root_attempt_id=prior_root_attempt_id,
        )
        assert first_fingerprint != same_revision_reversed_fingerprint

        first = await _accept_rerun(
            session=session,
            scenario=scenario,
            fingerprint=first_fingerprint,
            root_step_file_ids=first_order,
        )
        first_root_attempt = await run_repo.create_or_get_attempt_started(
            run_id=scenario.flow_run_id,
            flow_id=scenario.flow_id,
            tenant_id=scenario.tenant_id,
            step_id=scenario.root_step_id,
            step_order=1,
            attempt_no=first.operation.root_attempt_no,
            celery_task_id="complete-first-ordered-rerun",
            rerun_operation_id=first.operation.id,
            predecessor_attempt_id=prior_root_attempt_id,
        )
        finished_root_attempt = await run_repo.finish_attempt(
            run_id=scenario.flow_run_id,
            step_id=scenario.root_step_id,
            attempt_no=first_root_attempt.attempt_no,
            tenant_id=scenario.tenant_id,
            status=FlowStepAttemptStatus.COMPLETED,
        )
        assert finished_root_attempt is not None
        now = datetime.now(timezone.utc)
        await session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == scenario.flow_run_id)
            .where(FlowStepResults.tenant_id == scenario.tenant_id)
            .values(
                status=FlowStepResultStatus.COMPLETED.value,
                error_message=None,
                output_payload_json={"text": "first ordered rerun completed"},
                started_at=now,
                finished_at=now,
            )
        )
        await session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == scenario.flow_run_id)
            .where(FlowStepResults.tenant_id == scenario.tenant_id)
            .where(FlowStepResults.step_id == scenario.root_step_id)
            .values(current_attempt_no=first_root_attempt.attempt_no)
        )
        await session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == scenario.flow_run_id)
            .where(FlowStepResults.tenant_id == scenario.tenant_id)
            .where(FlowStepResults.step_id != scenario.root_step_id)
            .values(current_attempt_no=1)
        )
        assert (
            await rerun_repo.close_active_rerun_operations_for_terminal_run(
                run_id=scenario.flow_run_id,
                tenant_id=scenario.tenant_id,
                target_status=FlowRunStatus.COMPLETED,
            )
            == 1
        )
        completed_run = await run_repo.terminalize_run_status(
            run_id=scenario.flow_run_id,
            tenant_id=scenario.tenant_id,
            target_status=FlowRunStatus.COMPLETED,
            output_payload_json={"answer": "first ordered rerun completed"},
        )
        assert completed_run is not None
        assert completed_run.revision == 2

        second_fingerprint = _build_rerun_fingerprint(
            scenario=scenario,
            expected_run_revision=2,
            root_step_file_ids=reversed_order,
            prior_root_attempt_id=first_root_attempt.id,
        )
        second = await _accept_rerun(
            session=session,
            scenario=scenario,
            fingerprint=second_fingerprint,
            expected_run_revision=2,
            root_step_file_ids=reversed_order,
        )
        operation_rows = (
            (
                await session.execute(
                    sa.select(FlowRunRerunOperations)
                    .where(FlowRunRerunOperations.flow_run_id == scenario.flow_run_id)
                    .where(
                        FlowRunRerunOperations.request_fingerprint.in_(
                            (first_fingerprint, second_fingerprint)
                        )
                    )
                    .order_by(FlowRunRerunOperations.expected_run_revision.asc())
                )
            )
            .scalars()
            .all()
        )
        projection_rows = (
            (
                await session.execute(
                    sa.select(FlowRunStepInputFiles)
                    .where(FlowRunStepInputFiles.flow_run_id == scenario.flow_run_id)
                    .where(FlowRunStepInputFiles.step_id == scenario.root_step_id)
                    .where(
                        FlowRunStepInputFiles.attempt_no.in_(
                            (
                                first.operation.root_attempt_no,
                                second.operation.root_attempt_no,
                            )
                        )
                    )
                    .order_by(
                        FlowRunStepInputFiles.attempt_no.asc(),
                        FlowRunStepInputFiles.ordinal.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        projected_file_ids_by_attempt: dict[int, list[tuple[UUID, int]]] = {}
        for row in projection_rows:
            projected_file_ids_by_attempt.setdefault(row.attempt_no, []).append(
                (row.file_id, row.ordinal)
            )

        assert first.created is True
        assert second.created is True
        assert first.operation.id != second.operation.id
        assert second.operation.root_attempt_no == first_root_attempt.attempt_no + 1
        assert [(row.request_fingerprint, row.status) for row in operation_rows] == [
            (first_fingerprint, FlowRunRerunOperationStatus.COMPLETED.value),
            (second_fingerprint, FlowRunRerunOperationStatus.QUEUED.value),
        ]
        assert projected_file_ids_by_attempt == {
            first.operation.root_attempt_no: [
                (first_order[0], 0),
                (first_order[1], 1),
            ],
            second.operation.root_attempt_no: [
                (reversed_order[0], 0),
                (reversed_order[1], 1),
            ],
        }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_copy_step_input_files_from_predecessor_attempt_preserves_order(
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
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        source_attempt_id = await session.scalar(
            sa.select(FlowStepAttempts.id)
            .where(FlowStepAttempts.flow_run_id == scenario.flow_run_id)
            .where(FlowStepAttempts.flow_id == scenario.flow_id)
            .where(FlowStepAttempts.tenant_id == scenario.tenant_id)
            .where(FlowStepAttempts.step_id == scenario.root_step_id)
            .where(FlowStepAttempts.attempt_no == 1)
        )
        assert source_attempt_id is not None
        session.add_all(
            [
                FlowRunStepInputFiles(
                    flow_run_id=scenario.flow_run_id,
                    flow_id=scenario.flow_id,
                    tenant_id=scenario.tenant_id,
                    step_id=scenario.root_step_id,
                    step_order=1,
                    attempt_no=1,
                    file_id=scenario.rerun_file_ids[1],
                    ordinal=0,
                ),
                FlowRunStepInputFiles(
                    flow_run_id=scenario.flow_run_id,
                    flow_id=scenario.flow_id,
                    tenant_id=scenario.tenant_id,
                    step_id=scenario.root_step_id,
                    step_order=1,
                    attempt_no=1,
                    file_id=scenario.rerun_file_ids[0],
                    ordinal=1,
                ),
            ]
        )
        await session.flush()
        target_attempt = await run_repo.create_or_get_attempt_started(
            run_id=scenario.flow_run_id,
            flow_id=scenario.flow_id,
            tenant_id=scenario.tenant_id,
            step_id=scenario.root_step_id,
            step_order=1,
            attempt_no=2,
            celery_task_id="copy-step-input-files",
        )

        for _ in range(2):
            await run_repo.copy_step_input_files_from_predecessor_attempt(
                run_id=scenario.flow_run_id,
                flow_id=scenario.flow_id,
                tenant_id=scenario.tenant_id,
                step_id=scenario.root_step_id,
                step_order=1,
                predecessor_attempt_id=source_attempt_id,
                target_attempt_no=target_attempt.attempt_no,
            )
        copied_rows = (
            (
                await session.execute(
                    sa.select(FlowRunStepInputFiles)
                    .where(FlowRunStepInputFiles.flow_run_id == scenario.flow_run_id)
                    .where(FlowRunStepInputFiles.step_id == scenario.root_step_id)
                    .where(
                        FlowRunStepInputFiles.attempt_no == target_attempt.attempt_no
                    )
                    .order_by(FlowRunStepInputFiles.ordinal.asc())
                )
            )
            .scalars()
            .all()
        )
        copied_projection = [
            (row.file_id, row.ordinal, row.step_order) for row in copied_rows
        ]

    assert copied_projection == [
        (scenario.rerun_file_ids[1], 0, 1),
        (scenario.rerun_file_ids[0], 1, 1),
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_non_override_rerun_does_not_project_copied_rows_as_override(
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
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        rerun_repo = FlowRunRerunRepository(session=session, factory=FlowFactory())
        source_attempt_id = await session.scalar(
            sa.select(FlowStepAttempts.id)
            .where(FlowStepAttempts.flow_run_id == scenario.flow_run_id)
            .where(FlowStepAttempts.flow_id == scenario.flow_id)
            .where(FlowStepAttempts.tenant_id == scenario.tenant_id)
            .where(FlowStepAttempts.step_id == scenario.root_step_id)
            .where(FlowStepAttempts.attempt_no == 1)
        )
        assert source_attempt_id is not None
        session.add_all(
            [
                FlowRunStepInputFiles(
                    flow_run_id=scenario.flow_run_id,
                    flow_id=scenario.flow_id,
                    tenant_id=scenario.tenant_id,
                    step_id=scenario.root_step_id,
                    step_order=1,
                    attempt_no=1,
                    file_id=scenario.rerun_file_ids[0],
                    ordinal=0,
                ),
                FlowRunStepInputFiles(
                    flow_run_id=scenario.flow_run_id,
                    flow_id=scenario.flow_id,
                    tenant_id=scenario.tenant_id,
                    step_id=scenario.root_step_id,
                    step_order=1,
                    attempt_no=1,
                    file_id=scenario.rerun_file_ids[1],
                    ordinal=1,
                ),
            ]
        )
        await session.flush()
        accepted = await _accept_rerun(
            session=session,
            scenario=scenario,
            root_step_file_ids=None,
        )
        target_attempt = await run_repo.create_or_get_attempt_started(
            run_id=scenario.flow_run_id,
            flow_id=scenario.flow_id,
            tenant_id=scenario.tenant_id,
            step_id=scenario.root_step_id,
            step_order=1,
            attempt_no=accepted.operation.root_attempt_no,
            celery_task_id="non-override-copied-input-files",
            rerun_operation_id=accepted.operation.id,
            predecessor_attempt_id=source_attempt_id,
        )
        await run_repo.copy_step_input_files_from_predecessor_attempt(
            run_id=scenario.flow_run_id,
            flow_id=scenario.flow_id,
            tenant_id=scenario.tenant_id,
            step_id=scenario.root_step_id,
            step_order=1,
            predecessor_attempt_id=source_attempt_id,
            target_attempt_no=target_attempt.attempt_no,
        )

        replayed = await _accept_rerun(
            session=session,
            scenario=scenario,
            root_step_file_ids=None,
        )
        listed_operations = await rerun_repo.list_rerun_operations_for_run(
            run_id=scenario.flow_run_id,
            tenant_id=scenario.tenant_id,
        )
        active_operation = await rerun_repo.get_active_rerun_operation(
            run_id=scenario.flow_run_id,
            flow_id=scenario.flow_id,
            tenant_id=scenario.tenant_id,
        )

        assert accepted.operation.root_step_input_override_requested is False
        assert replayed.operation.root_step_input_override is None
        listed_operation = next(
            operation
            for operation in listed_operations
            if operation.id == accepted.operation.id
        )
        assert listed_operation.root_step_input_override is None
        assert active_operation is not None
        assert active_operation.operation.root_step_input_override is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rerun_attempt_start_and_success_records_lineage(
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
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        rerun_repo = FlowRunRerunRepository(session=session, factory=FlowFactory())
        accepted = await _accept_rerun(session=session, scenario=scenario)
        root_invalidated_step = accepted.invalidated_steps[0]
        assert root_invalidated_step.prior_attempt_id is not None
        assert await run_repo.mark_running_if_claimable(
            run_id=scenario.flow_run_id,
            tenant_id=scenario.tenant_id,
        )
        claimed = await run_repo.claim_step_result(
            run_id=scenario.flow_run_id,
            step_id=scenario.root_step_id,
            tenant_id=scenario.tenant_id,
        )
        assert claimed is not None

        started_attempt = await run_repo.create_or_get_attempt_started(
            run_id=scenario.flow_run_id,
            flow_id=scenario.flow_id,
            tenant_id=scenario.tenant_id,
            step_id=scenario.root_step_id,
            step_order=1,
            attempt_no=accepted.operation.root_attempt_no,
            celery_task_id="rerun-root-attempt",
            rerun_operation_id=accepted.operation.id,
            predecessor_attempt_id=root_invalidated_step.prior_attempt_id,
        )
        await rerun_repo.link_rerun_invalidated_step_attempt(
            operation_id=accepted.operation.id,
            tenant_id=scenario.tenant_id,
            step_id=scenario.root_step_id,
            new_attempt_no=started_attempt.attempt_no,
            new_attempt_id=started_attempt.id,
        )
        await rerun_repo.mark_rerun_operation_running(
            operation_id=accepted.operation.id,
            tenant_id=scenario.tenant_id,
            root_attempt_id=started_attempt.id,
        )
        operation_after_first_start = await session.scalar(
            sa.select(FlowRunRerunOperations).where(
                FlowRunRerunOperations.id == accepted.operation.id
            )
        )
        assert operation_after_first_start is not None
        first_started_at = operation_after_first_start.started_at
        assert first_started_at is not None

        await rerun_repo.mark_rerun_operation_running(
            operation_id=accepted.operation.id,
            tenant_id=scenario.tenant_id,
            root_attempt_id=started_attempt.id,
        )
        await session.refresh(operation_after_first_start)
        assert operation_after_first_start.started_at == first_started_at
        assert operation_after_first_start.root_attempt_id == started_attempt.id

        await FlowRunRepository(
            session=session, factory=FlowFactory()
        ).save_step_result(
            scenario.flow_run_id,
            claimed.model_copy(
                update={
                    "status": FlowStepResultStatus.COMPLETED,
                    "output_payload_json": {"text": "rerun output"},
                },
                deep=True,
            ),
            tenant_id=scenario.tenant_id,
            attempt_no=started_attempt.attempt_no,
        )
        finished_attempt = await run_repo.finish_attempt(
            run_id=scenario.flow_run_id,
            step_id=scenario.root_step_id,
            attempt_no=started_attempt.attempt_no,
            tenant_id=scenario.tenant_id,
            status=FlowStepAttemptStatus.COMPLETED,
        )
        assert finished_attempt is not None

        operation_row = await session.scalar(
            sa.select(FlowRunRerunOperations).where(
                FlowRunRerunOperations.id == accepted.operation.id
            )
        )
        assert operation_row is not None
        assert operation_row.status == FlowRunRerunOperationStatus.RUNNING.value
        assert operation_row.root_attempt_id == started_attempt.id
        assert operation_row.started_at is not None

        invalidated_row = await session.scalar(
            sa.select(FlowRunRerunInvalidatedSteps).where(
                FlowRunRerunInvalidatedSteps.id == root_invalidated_step.id
            )
        )
        assert invalidated_row is not None
        assert invalidated_row.new_attempt_no == started_attempt.attempt_no
        assert invalidated_row.new_attempt_id == started_attempt.id

        current_result = await session.scalar(
            sa.select(FlowStepResults).where(
                FlowStepResults.id == root_invalidated_step.prior_step_result_id
            )
        )
        assert current_result is not None
        assert current_result.current_attempt_no == started_attempt.attempt_no
        assert current_result.output_payload_json == {"text": "rerun output"}

        prior_attempt = await session.scalar(
            sa.select(FlowStepAttempts).where(
                FlowStepAttempts.id == root_invalidated_step.prior_attempt_id
            )
        )
        assert prior_attempt is not None
        assert prior_attempt.superseded_by_attempt_id == started_attempt.id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rerun_invalidated_step_link_conflict_raises_typed_error(
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
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        rerun_repo = FlowRunRerunRepository(session=session, factory=FlowFactory())
        accepted = await _accept_rerun(session=session, scenario=scenario)
        root_invalidated_step = accepted.invalidated_steps[0]
        assert root_invalidated_step.prior_attempt_id is not None
        assert await run_repo.mark_running_if_claimable(
            run_id=scenario.flow_run_id,
            tenant_id=scenario.tenant_id,
        )
        claimed = await run_repo.claim_step_result(
            run_id=scenario.flow_run_id,
            step_id=scenario.root_step_id,
            tenant_id=scenario.tenant_id,
        )
        assert claimed is not None

        started_attempt = await run_repo.create_or_get_attempt_started(
            run_id=scenario.flow_run_id,
            flow_id=scenario.flow_id,
            tenant_id=scenario.tenant_id,
            step_id=scenario.root_step_id,
            step_order=1,
            attempt_no=accepted.operation.root_attempt_no,
            celery_task_id="rerun-root-attempt",
            rerun_operation_id=accepted.operation.id,
            predecessor_attempt_id=root_invalidated_step.prior_attempt_id,
        )
        await rerun_repo.link_rerun_invalidated_step_attempt(
            operation_id=accepted.operation.id,
            tenant_id=scenario.tenant_id,
            step_id=scenario.root_step_id,
            new_attempt_no=started_attempt.attempt_no,
            new_attempt_id=started_attempt.id,
        )
        conflicting_attempt_id = uuid4()

        with pytest.raises(FlowRunRerunAttemptLineageConflictError) as exc_info:
            await rerun_repo.link_rerun_invalidated_step_attempt(
                operation_id=accepted.operation.id,
                tenant_id=scenario.tenant_id,
                step_id=scenario.root_step_id,
                new_attempt_no=started_attempt.attempt_no + 1,
                new_attempt_id=conflicting_attempt_id,
            )

        assert exc_info.value.operation_id == accepted.operation.id
        assert exc_info.value.step_id == scenario.root_step_id
        assert exc_info.value.new_attempt_id == conflicting_attempt_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_accept_rerun_projects_file_inputs_at_next_root_attempt(
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
        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        second_attempt = await run_repo.create_or_get_attempt_started(
            run_id=scenario.flow_run_id,
            flow_id=scenario.flow_id,
            tenant_id=scenario.tenant_id,
            step_id=scenario.root_step_id,
            step_order=1,
            attempt_no=2,
            celery_task_id="completed-second-root-attempt",
        )
        finished_second_attempt = await run_repo.finish_attempt(
            run_id=scenario.flow_run_id,
            step_id=scenario.root_step_id,
            attempt_no=second_attempt.attempt_no,
            tenant_id=scenario.tenant_id,
            status=FlowStepAttemptStatus.COMPLETED,
        )
        assert finished_second_attempt is not None

        accepted = await _accept_rerun(
            session=session,
            scenario=scenario,
            fingerprint="rerun-after-second-attempt",
        )

        assert accepted.operation.root_attempt_no == 3
        projection_rows = (
            (
                await session.execute(
                    sa.select(FlowRunStepInputFiles)
                    .where(FlowRunStepInputFiles.flow_run_id == scenario.flow_run_id)
                    .where(FlowRunStepInputFiles.step_id == scenario.root_step_id)
                    .order_by(
                        FlowRunStepInputFiles.attempt_no.asc(),
                        FlowRunStepInputFiles.ordinal.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [
            (row.attempt_no, row.file_id, row.ordinal) for row in projection_rows
        ] == [
            (3, scenario.rerun_file_ids[0], 0),
            (3, scenario.rerun_file_ids[1], 1),
        ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_rerun_lineage_for_evidence_is_tenant_scoped_and_ordered(
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
        rerun_repo = FlowRunRerunRepository(session=session, factory=FlowFactory())
        started_at = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
        later_operation = FlowRunRerunOperations(
            tenant_id=scenario.tenant_id,
            flow_id=scenario.flow_id,
            flow_run_id=scenario.flow_run_id,
            rerun_step_id=scenario.step_ids[1],
            rerun_step_order=2,
            root_attempt_no=3,
            status=FlowRunRerunOperationStatus.FAILED.value,
            request_fingerprint="evidence-rerun-later",
            expected_run_revision=2,
            accepted_run_revision=3,
            reason="Later evidence operation",
            input_payload_json={"case_id": "later"},
            root_step_input_override_requested=False,
            requested_by_principal_type=PrincipalType.USER.value,
            requested_by_user_id=scenario.requested_by_user_id,
            failure_code="step_failed",
            failure_message="Step failed",
            started_at=started_at + timedelta(minutes=5),
            finished_at=started_at + timedelta(minutes=6),
            created_at=started_at + timedelta(minutes=5),
            updated_at=started_at + timedelta(minutes=6),
        )
        earlier_operation = FlowRunRerunOperations(
            tenant_id=scenario.tenant_id,
            flow_id=scenario.flow_id,
            flow_run_id=scenario.flow_run_id,
            rerun_step_id=scenario.step_ids[0],
            rerun_step_order=1,
            root_attempt_no=2,
            status=FlowRunRerunOperationStatus.COMPLETED.value,
            request_fingerprint="evidence-rerun-earlier",
            expected_run_revision=1,
            accepted_run_revision=2,
            reason="Earlier evidence operation",
            input_payload_json={"case_id": "earlier"},
            root_step_input_override_requested=True,
            requested_by_principal_type=PrincipalType.USER.value,
            requested_by_user_id=scenario.requested_by_user_id,
            failure_code=None,
            failure_message=None,
            started_at=started_at,
            finished_at=started_at + timedelta(minutes=1),
            created_at=started_at,
            updated_at=started_at + timedelta(minutes=1),
        )
        session.add_all([later_operation, earlier_operation])
        await session.flush()
        session.add_all(
            [
                FlowRunRerunInvalidatedSteps(
                    operation_id=later_operation.id,
                    tenant_id=scenario.tenant_id,
                    flow_id=scenario.flow_id,
                    flow_run_id=scenario.flow_run_id,
                    step_id=scenario.step_ids[2],
                    step_order=3,
                    invalidation_order=2,
                    role=FlowRunRerunInvalidationRole.DOWNSTREAM.value,
                    dependency_sources_json=[
                        RerunDependencyKind.INPUT_SOURCE_PREVIOUS_STEP.value
                    ],
                    prior_step_result_id=None,
                    prior_attempt_id=None,
                    new_attempt_no=None,
                    new_attempt_id=None,
                ),
                FlowRunRerunInvalidatedSteps(
                    operation_id=later_operation.id,
                    tenant_id=scenario.tenant_id,
                    flow_id=scenario.flow_id,
                    flow_run_id=scenario.flow_run_id,
                    step_id=scenario.step_ids[1],
                    step_order=2,
                    invalidation_order=1,
                    role=FlowRunRerunInvalidationRole.ROOT.value,
                    dependency_sources_json=[],
                    prior_step_result_id=None,
                    prior_attempt_id=None,
                    new_attempt_no=3,
                    new_attempt_id=None,
                ),
                FlowRunRerunInvalidatedSteps(
                    operation_id=earlier_operation.id,
                    tenant_id=scenario.tenant_id,
                    flow_id=scenario.flow_id,
                    flow_run_id=scenario.flow_run_id,
                    step_id=scenario.step_ids[0],
                    step_order=1,
                    invalidation_order=1,
                    role=FlowRunRerunInvalidationRole.ROOT.value,
                    dependency_sources_json=[
                        RerunDependencyKind.INPUT_BINDINGS_QUESTION.value
                    ],
                    prior_step_result_id=None,
                    prior_attempt_id=None,
                    new_attempt_no=2,
                    new_attempt_id=None,
                ),
            ]
        )
        await session.flush()

        operations = await rerun_repo.list_rerun_operations_for_run(
            run_id=scenario.flow_run_id,
            tenant_id=scenario.tenant_id,
        )
        invalidated_steps = await rerun_repo.list_rerun_invalidated_steps_for_run(
            run_id=scenario.flow_run_id,
            tenant_id=scenario.tenant_id,
        )
        wrong_tenant_operations = await rerun_repo.list_rerun_operations_for_run(
            run_id=scenario.flow_run_id,
            tenant_id=uuid4(),
        )
        missing_run_invalidated_steps = (
            await rerun_repo.list_rerun_invalidated_steps_for_run(
                run_id=uuid4(),
                tenant_id=scenario.tenant_id,
            )
        )
        expected_invalidated_order = sorted(
            [
                (earlier_operation.id, 1),
                (later_operation.id, 1),
                (later_operation.id, 2),
            ],
            key=lambda entry: (entry[0].int, entry[1]),
        )

    assert [operation.request_fingerprint for operation in operations] == [
        "evidence-rerun-earlier",
        "evidence-rerun-later",
    ]
    assert [
        (step.operation_id, step.invalidation_order) for step in invalidated_steps
    ] == expected_invalidated_order
    assert wrong_tenant_operations == []
    assert missing_run_invalidated_steps == []


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

        with pytest.raises(FlowRunRerunStaleRevisionError) as exc_info:
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

    assert exc_info.value.expected_run_revision == 0
    assert exc_info.value.current_run_revision == 1
    assert operation_count == 0
    assert run_state == (FlowRunStatus.COMPLETED.value, 1)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "run_status",
    [
        FlowRunStatus.QUEUED,
        FlowRunStatus.RUNNING,
        FlowRunStatus.AWAITING_REVIEW,
        FlowRunStatus.CANCELLED,
    ],
)
async def test_non_rerunnable_run_status_rejects_without_mutation(
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

        with pytest.raises(FlowRunRerunInvalidTransitionError) as exc_info:
            await _accept_rerun(session=session, scenario=scenario)

        operation_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.flow_run_id == scenario.flow_run_id)
        )

    assert exc_info.value.status == run_status.value
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

        with pytest.raises(FlowRunRerunRootStepIncompleteError) as exc_info:
            await _accept_rerun(session=session, scenario=scenario)

        operation_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.flow_run_id == scenario.flow_run_id)
        )

    assert exc_info.value.step_ids == (scenario.root_step_id,)
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

        with pytest.raises(FlowRunRerunMissingCurrentResultsError) as exc_info:
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

    assert exc_info.value.step_ids == (scenario.step_ids[2],)
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

        with pytest.raises(FlowRunRerunStepNotFoundError):
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

    assert operation_count == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_wrong_root_step_input_rejects_without_mutation(
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
        invalid_step_id = scenario.step_ids[1]

        with pytest.raises(FlowRunRerunStepInputsInvalidError) as exc_info:
            await _accept_rerun(
                session=session,
                scenario=scenario,
                root_step_input_step_id=invalid_step_id,
            )

        operation_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.flow_run_id == scenario.flow_run_id)
        )

    assert exc_info.value.step_ids == (invalid_step_id,)
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
            rerun_file_ids=scenario.rerun_file_ids,
            step_ids=scenario.step_ids,
            invalidated_steps=scenario.invalidated_steps,
        )

        with pytest.raises(FlowRunNotFoundError):
            await _accept_rerun(session=session, scenario=wrong_tenant)

        operation_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.flow_run_id == scenario.flow_run_id)
        )

    assert operation_count == 0
