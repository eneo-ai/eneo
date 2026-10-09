from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant import AssistantOrigin
from eneo.completion_models.domain.model_kwargs_capabilities import (
    SupportedModelKwargs,
)
from eneo.database.database import sessionmanager
from eneo.database.tables.flow_tables import (
    FlowRunAuditOutbox,
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowStepAttemptResolvedInputs,
    FlowStepAttempts,
    FlowStepResults,
    FlowSteps,
)
from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    CreateCompileContext,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    compile_create_intent_to_spec,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.planning_state import CheckpointIntent
from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.application.flow_draft_materialization import (
    compile_flow_draft_changeset,
)
from eneo.flows.application.flow_draft_materialization_executor import (
    build_flow_steps,
)
from eneo.flows.assistant_execution_snapshot import build_assistant_execution_snapshot
from eneo.flows.domain.flow import (
    Flow,
    FlowPersistedJsonObject,
    FlowRunStatus,
    FlowStep,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
)
from eneo.flows.domain.review_checkpoint_exceptions import (
    FlowReviewCheckpointStepResultIncompleteError,
    FlowReviewMultipleActiveCheckpointsError,
    FlowReviewOpenBlockedByActiveCheckpointError,
)
from eneo.flows.enums import (
    FlowOutputType,
    FlowRunLifecycleSource,
    FlowRunReviewCheckpointState,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore, InputType, OutputType
from eneo.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.published_definition import build_published_definition_json
from eneo.flows.runtime.executor import FlowRunExecutor, FlowRunExecutorConfig
from eneo.flows.runtime.flow_run_actor import FlowRunActor
from eneo.flows.runtime.tasks import enable_autobegin_for_flow_task_session
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import BadRequestException, TypedIOValidationException

pytestmark = pytest.mark.usefixtures("object_content_runtime_ready")


class _RuntimeAssistant:
    def __init__(
        self, *, assistant_id: UUID, model_id: UUID, provider_id: UUID, model_name: str
    ):
        self.id = assistant_id
        self.origin = AssistantOrigin.FLOW_MANAGED
        self.prompt = SimpleNamespace(text="Answer the submitted question.")
        self.completion_model = SimpleNamespace(
            id=model_id,
            name=model_name,
            nickname=model_name,
            litellm_model_name=model_name,
            provider_type="openai",
            provider_id=provider_id,
            get_model_route=lambda: f"openai/{model_name}",
            supported_model_kwargs=SupportedModelKwargs(),
        )
        self.completion_model_kwargs = ModelKwargs(temperature=0.2)
        self.collections = []
        self.websites = []
        self.integration_knowledge_list = []
        self.mcp_servers = []
        self.attachments = []
        self.inline_file_text = False

    def get_prompt_text(self) -> str:
        return self.prompt.text

    def has_knowledge(self) -> bool:
        return False

    async def get_response(self, *, completion_service, **kwargs):
        return await completion_service.get_response(**kwargs)


@dataclass(frozen=True, slots=True)
class _ReviewPauseRuntimeContext:
    container: Container
    executor: FlowRunExecutor
    run_id: UUID
    flow_id: UUID
    tenant_id: UUID
    first_step_id: UUID
    second_step_id: UUID | None
    third_step_id: UUID | None
    initial_run_revision: int


def _build_review_pause_flow(
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    assistant_id: UUID,
    include_downstream_steps: bool = True,
    first_step_output_type: str = "text",
    first_step_output_contract: dict[str, object] | None = None,
    first_step_review_mode: FlowStepReviewMode = FlowStepReviewMode.VIEW,
) -> Flow:
    steps = [
        FlowStep(
            id=None,
            flow_id=uuid4(),
            tenant_id=tenant_id,
            assistant_id=assistant_id,
            step_order=1,
            user_description="Draft answer for review",
            input_source="flow_input",
            input_type="text",
            input_contract=None,
            output_mode="pass_through",
            output_type=first_step_output_type,
            output_contract=first_step_output_contract,
            input_bindings={"question": "{{flow.input.question}}"},
            output_classification_override=None,
            input_config=None,
            output_config=None,
            review_policy=FlowStepReviewPolicy(mode=first_step_review_mode),
        )
    ]
    if include_downstream_steps:
        steps.extend(
            [
                FlowStep(
                    id=None,
                    flow_id=uuid4(),
                    tenant_id=tenant_id,
                    assistant_id=assistant_id,
                    step_order=2,
                    user_description="Use approved answer",
                    input_source="previous_step",
                    input_type="text",
                    input_contract=None,
                    output_mode="pass_through",
                    output_type="text",
                    output_contract=None,
                    input_bindings={"question": "{{step_1.output.text}}"},
                    output_classification_override=None,
                    input_config=None,
                    output_config=None,
                ),
                FlowStep(
                    id=None,
                    flow_id=uuid4(),
                    tenant_id=tenant_id,
                    assistant_id=assistant_id,
                    step_order=3,
                    user_description="Archive reviewed answer",
                    input_source="previous_step",
                    input_type="text",
                    input_contract=None,
                    output_mode="pass_through",
                    output_type="text",
                    output_contract=None,
                    input_bindings={"question": "{{step_2.output.text}}"},
                    output_classification_override=None,
                    input_config=None,
                    output_config=None,
                ),
            ]
        )
    return Flow(
        id=None,
        tenant_id=tenant_id,
        space_id=space_id,
        name="Runtime Worker Review Pause Flow",
        description="Runtime worker contract for human review pause.",
        created_by_user_id=user_id,
        owner_user_id=user_id,
        published_version=None,
        metadata_json={
            "form_schema": {"fields": [{"name": "question", "type": "text"}]}
        },
        data_retention_days=30,
        created_at=None,
        updated_at=None,
        steps=steps,
    )


def _definition_step(
    step: FlowStep,
    *,
    assistant_snapshot: dict[str, object],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "step_id": str(step.id),
        "assistant_id": str(step.assistant_id),
        "step_order": step.step_order,
        "user_description": step.user_description,
        "input_source": step.input_source.value,
        "input_type": step.input_type.value,
        "input_bindings": step.input_bindings,
        "output_mode": step.output_mode.value,
        "output_type": step.output_type.value,
        "assistant_snapshot": assistant_snapshot,
    }
    if step.review_policy is not None:
        payload["review_policy"] = step.review_policy.model_dump(mode="json")
    if step.input_contract is not None:
        payload["input_contract"] = step.input_contract
    if step.output_contract is not None:
        payload["output_contract"] = step.output_contract
    return payload


async def _create_review_pause_runtime_context(
    *,
    session: AsyncSession,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
    completion_service: SimpleNamespace,
    include_downstream_steps: bool = True,
    first_step_output_type: str = "text",
    first_step_output_contract: dict[str, object] | None = None,
    first_step_review_mode: FlowStepReviewMode = FlowStepReviewMode.VIEW,
    compiled_spec: FlowDraftSpecCore | None = None,
    input_payload_json: FlowPersistedJsonObject | None = None,
) -> _ReviewPauseRuntimeContext:
    enable_autobegin_for_flow_task_session(session)
    setup_container = Container(
        session=providers.Object(session),
        user=providers.Object(admin_user),
        tenant=providers.Object(test_tenant),
    )
    model = await completion_model_factory(session, "gpt-4o-mini")
    space = await space_factory(session, "Review pause worker space", [model.id])
    assistant = await assistant_factory(
        session,
        "Review Pause Worker Assistant",
        model.id,
        space_id=space.id,
    )
    flow_repo = FlowRepository(session=session)
    version_repo = FlowVersionRepository(session=session)
    flow = _build_review_pause_flow(
        tenant_id=admin_user.tenant_id,
        space_id=space.id,
        user_id=admin_user.id,
        assistant_id=assistant.id,
        include_downstream_steps=include_downstream_steps,
        first_step_output_type=first_step_output_type,
        first_step_output_contract=first_step_output_contract,
        first_step_review_mode=first_step_review_mode,
    )
    if compiled_spec is not None:
        # The rows the authoring materializer writes for a compiled spec.
        flow = flow.model_copy(
            update={
                "metadata_json": None,
                "steps": [
                    step.model_copy(
                        update={"flow_id": uuid4(), "tenant_id": admin_user.tenant_id}
                    )
                    for step in build_flow_steps(
                        compiled_steps=compile_flow_draft_changeset(
                            compiled_spec, None
                        ).compiled_steps,
                        ref_to_assistant_id={
                            step.plan_step_ref: assistant.id
                            for step in compiled_spec.steps
                        },
                    )
                ],
            }
        )
    flow = await flow_repo.create(flow=flow, tenant_id=admin_user.tenant_id)
    assert flow.id is not None
    first_step = flow.steps[0]
    assert first_step.id is not None
    second_step = flow.steps[1] if len(flow.steps) > 1 else None
    third_step = flow.steps[2] if len(flow.steps) > 2 else None
    assert second_step is None or second_step.id is not None
    assert third_step is None or third_step.id is not None

    runtime_assistant = _RuntimeAssistant(
        assistant_id=assistant.id,
        model_id=model.id,
        provider_id=model.provider_id,
        model_name="gpt-4o-mini",
    )
    assistant_snapshot = build_assistant_execution_snapshot(
        assistant=runtime_assistant,
    )
    assert assistant_snapshot is not None
    definition_json = build_published_definition_json(
        flow_id=flow.id,
        name=flow.name,
        description=flow.description,
        metadata_json=flow.metadata_json,
        steps=[
            _definition_step(step, assistant_snapshot=assistant_snapshot)
            for step in flow.steps
        ],
    )
    await version_repo.create(
        flow_id=flow.id,
        version=1,
        definition_json=definition_json,
        tenant_id=admin_user.tenant_id,
    )
    flow = await flow_repo.update(
        flow=flow.model_copy(update={"published_version": 1}),
        tenant_id=admin_user.tenant_id,
    )
    create_result = await setup_container.flow_run_service().create_run(
        flow_id=flow.id,
        input_payload_json=input_payload_json or {"question": "What needs review?"},
        expected_flow_version=1,
        step_inputs=None,
        idempotency_key=f"review-pause-{uuid4()}",
    )
    assert create_result.created is True
    run = create_result.run
    audit_service = SimpleNamespace(log_async=AsyncMock(return_value=uuid4()))
    worker_container = Container(
        session=providers.Object(session),
        tenant=providers.Object(test_tenant),
    )
    file_service = worker_container.file_service(user=admin_user)
    executor = FlowRunExecutor(
        runtime_actor=FlowRunActor.from_user(user=admin_user),
        session=session,
        flow_repo=worker_container.flow_repo(),
        flow_run_repo=worker_container.flow_run_repo(),
        flow_run_review_checkpoint_repo=worker_container.flow_run_review_checkpoint_repo(),
        flow_run_terminalizer=worker_container.flow_run_terminalizer(),
        flow_version_repo=worker_container.flow_version_repo(),
        space_repo=worker_container.tenant_scoped_space_repo(),
        completion_service=completion_service,
        file_repo=worker_container.file_repo(),
        file_content_loader=worker_container.file_content_loader(),
        file_service=file_service,
        template_asset_repo=worker_container.flow_template_asset_repo(),
        encryption_service=worker_container.encryption_service(),
        audit_service=audit_service,
        references_service=worker_container.references_service(
            datastore__create_embeddings_service__user=admin_user
        ),
        config=FlowRunExecutorConfig(
            max_inline_text_bytes=1024 * 1024,
            http_request_timeout_seconds=2.0,
            http_max_timeout_seconds=2.0,
            http_allow_private_networks=False,
        ),
    )

    async def _load_assistant(assistant_id, state, *, snapshot=None):
        if state.flow_space is None:
            state.flow_space = await executor.space_repo.get_execution_space(
                flow.space_id
            )
        return runtime_assistant

    executor._load_assistant = AsyncMock(side_effect=_load_assistant)
    return _ReviewPauseRuntimeContext(
        container=setup_container,
        executor=executor,
        run_id=run.id,
        flow_id=flow.id,
        tenant_id=admin_user.tenant_id,
        first_step_id=first_step.id,
        second_step_id=second_step.id if second_step is not None else None,
        third_step_id=third_step.id if third_step is not None else None,
        initial_run_revision=run.revision,
    )


async def _review_pause_state_from_fresh_session(
    *,
    run_id: UUID,
    tenant_id: UUID,
) -> tuple[
    FlowRuns | None,
    list[FlowRunReviewCheckpoints],
    list[FlowStepResults],
    list[FlowStepAttempts],
    list[FlowRunAuditOutbox],
]:
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        run_row = await session.scalar(sa.select(FlowRuns).where(FlowRuns.id == run_id))
        checkpoint_rows = (
            (
                await session.execute(
                    sa.select(FlowRunReviewCheckpoints)
                    .where(FlowRunReviewCheckpoints.flow_run_id == run_id)
                    .where(FlowRunReviewCheckpoints.tenant_id == tenant_id)
                    .order_by(FlowRunReviewCheckpoints.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        step_result_rows = (
            (
                await session.execute(
                    sa.select(FlowStepResults)
                    .where(FlowStepResults.flow_run_id == run_id)
                    .where(FlowStepResults.tenant_id == tenant_id)
                    .order_by(FlowStepResults.step_order.asc())
                )
            )
            .scalars()
            .all()
        )
        attempt_rows = (
            (
                await session.execute(
                    sa.select(FlowStepAttempts)
                    .where(FlowStepAttempts.flow_run_id == run_id)
                    .where(FlowStepAttempts.tenant_id == tenant_id)
                    .order_by(FlowStepAttempts.attempt_no.asc())
                )
            )
            .scalars()
            .all()
        )
        outbox_rows = (
            (
                await session.execute(
                    sa.select(FlowRunAuditOutbox)
                    .where(FlowRunAuditOutbox.flow_run_id == run_id)
                    .where(FlowRunAuditOutbox.tenant_id == tenant_id)
                    .order_by(FlowRunAuditOutbox.run_revision.asc())
                )
            )
            .scalars()
            .all()
        )
    return run_row, checkpoint_rows, step_result_rows, attempt_rows, outbox_rows


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("target_status", "expected_worker_result"),
    [
        (
            FlowRunStatus.CANCELLED,
            {"status": "skipped", "reason": "run_cancelled"},
        ),
        (
            FlowRunStatus.FAILED,
            {"status": "failed", "error": "Run was terminalized as failed."},
        ),
    ],
)
async def test_review_checkpoint_open_after_terminalization_returns_terminal_outcome(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
    monkeypatch,
    target_status,
    expected_worker_result,
):
    completion_service = SimpleNamespace(
        get_response=AsyncMock(
            return_value=SimpleNamespace(
                completion="This answer needs review.",
                total_token_count=17,
            )
        )
    )
    async with sessionmanager.session() as session:
        context = await _create_review_pause_runtime_context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            completion_service=completion_service,
        )
        await session.commit()

        original_open = (
            FlowRunReviewCheckpointRepository.open_review_checkpoint_for_completed_step
        )

        async def _terminalize_then_open(self, **kwargs):
            async with sessionmanager.session() as terminal_session:
                enable_autobegin_for_flow_task_session(terminal_session)
                terminal_container = Container(
                    session=providers.Object(terminal_session),
                    tenant=providers.Object(test_tenant),
                )
                await terminal_container.flow_run_terminalizer().terminalize_run(
                    run_id=context.run_id,
                    tenant_id=context.tenant_id,
                    target_status=target_status,
                    source=(
                        FlowRunLifecycleSource.USER_CANCEL
                        if target_status == FlowRunStatus.CANCELLED
                        else FlowRunLifecycleSource.STALE_RUNNING_RECONCILER
                    ),
                    error=FlowRunError.from_source(
                        (
                            FlowRunLifecycleSource.USER_CANCEL
                            if target_status == FlowRunStatus.CANCELLED
                            else FlowRunLifecycleSource.STALE_RUNNING_RECONCILER
                        ),
                        code=(
                            FlowApiErrorCode.RUN_USER_CANCELLED
                            if target_status == FlowRunStatus.CANCELLED
                            else FlowApiErrorCode.RUN_WORKER_STALLED
                        ),
                        message=f"Run was terminalized as {target_status.value}.",
                    ),
                )
                await terminal_session.commit()
            return await original_open(self, **kwargs)

        monkeypatch.setattr(
            FlowRunReviewCheckpointRepository,
            "open_review_checkpoint_for_completed_step",
            _terminalize_then_open,
        )

        worker_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            run_revision=context.initial_run_revision,
            dispatch_task_id=f"review-open-terminalized-{target_status.value}",
            retry_count=0,
        )

    (
        run_row,
        checkpoint_rows,
        step_result_rows,
        attempt_rows,
        outbox_rows,
    ) = await _review_pause_state_from_fresh_session(
        run_id=context.run_id,
        tenant_id=context.tenant_id,
    )

    assert worker_result == expected_worker_result
    completion_service.get_response.assert_awaited_once()
    assert run_row is not None
    assert run_row.status == target_status.value
    assert checkpoint_rows == []
    downstream_step_status = (
        FlowStepResultStatus.CANCELLED
        if target_status == FlowRunStatus.CANCELLED
        else FlowStepResultStatus.FAILED
    )
    assert [row.status for row in step_result_rows] == [
        FlowStepResultStatus.COMPLETED.value,
        downstream_step_status.value,
        downstream_step_status.value,
    ]
    assert step_result_rows[0].output_payload_json == {
        "text": "This answer needs review.",
    }
    assert len(attempt_rows) == 1
    assert attempt_rows[0].status == FlowStepAttemptStatus.COMPLETED.value
    assert attempt_rows[0].finished_at is not None
    assert "flow_run_review_checkpoint_opened" not in {
        row.action for row in outbox_rows
    }
    assert FlowRunLifecycleSource.REVIEW_CHECKPOINT_OPENED.value not in {
        row.source for row in outbox_rows
    }


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("review_open_error", "expected_code", "expected_message"),
    [
        (
            FlowReviewOpenBlockedByActiveCheckpointError(active_checkpoint_id=uuid4()),
            "flow_review_open_active_conflict_invariant",
            "Review checkpoint opening failed because another checkpoint is active.",
        ),
        (
            FlowReviewCheckpointStepResultIncompleteError(
                step_id=uuid4(), attempt_no=1
            ),
            "flow_review_open_step_result_incomplete_invariant",
            "Review checkpoint opening failed because the completed step result was unavailable.",
        ),
        (
            FlowReviewMultipleActiveCheckpointsError(),
            "flow_review_open_multiple_active_checkpoints_invariant",
            "Review checkpoint opening failed because multiple checkpoints are active.",
        ),
    ],
)
async def test_review_checkpoint_open_invariant_terminalizes_failed_run(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
    monkeypatch,
    review_open_error,
    expected_code,
    expected_message,
):
    completion_service = SimpleNamespace(
        get_response=AsyncMock(
            return_value=SimpleNamespace(
                completion="This answer needs review.",
                total_token_count=17,
            )
        )
    )
    async with sessionmanager.session() as session:
        context = await _create_review_pause_runtime_context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            completion_service=completion_service,
        )
        await session.commit()

        async def _raise_review_open_invariant(self, **_kwargs):
            raise review_open_error

        monkeypatch.setattr(
            FlowRunReviewCheckpointRepository,
            "open_review_checkpoint_for_completed_step",
            _raise_review_open_invariant,
        )

        worker_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            run_revision=context.initial_run_revision,
            dispatch_task_id="review-open-invariant",
            retry_count=0,
        )

    (
        run_row,
        checkpoint_rows,
        step_result_rows,
        attempt_rows,
        outbox_rows,
    ) = await _review_pause_state_from_fresh_session(
        run_id=context.run_id,
        tenant_id=context.tenant_id,
    )

    assert worker_result == {"status": "failed", "error": expected_message}
    completion_service.get_response.assert_awaited_once()
    assert run_row is not None
    assert run_row.status == FlowRunStatus.FAILED.value
    assert run_row.error_json is not None
    assert run_row.error_json["code"] == expected_code
    assert run_row.error_json["message"] == expected_message
    assert checkpoint_rows == []
    assert [row.status for row in step_result_rows] == [
        FlowStepResultStatus.COMPLETED.value,
        FlowStepResultStatus.FAILED.value,
        FlowStepResultStatus.FAILED.value,
    ]
    assert step_result_rows[0].output_payload_json == {
        "text": "This answer needs review.",
    }
    assert len(attempt_rows) == 1
    assert attempt_rows[0].status == FlowStepAttemptStatus.COMPLETED.value
    assert "flow_run_review_checkpoint_opened" not in {
        row.action for row in outbox_rows
    }
    assert "flow_run_failed" in {row.action for row in outbox_rows}
    assert FlowRunLifecycleSource.REVIEW_CHECKPOINT_OPENED.value not in {
        row.source for row in outbox_rows
    }
    assert FlowRunLifecycleSource.EXECUTOR_FAILED.value in {
        row.source for row in outbox_rows
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_executor_pauses_after_review_policy_step_and_duplicate_delivery_skips(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    completion_service = SimpleNamespace(
        get_response=AsyncMock(
            return_value=SimpleNamespace(
                completion="This answer needs review.",
                total_token_count=17,
            )
        )
    )
    async with sessionmanager.session() as session:
        context = await _create_review_pause_runtime_context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            completion_service=completion_service,
        )

        worker_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            run_revision=context.initial_run_revision,
            dispatch_task_id=f"review-pause-{uuid4()}",
            retry_count=0,
        )
        duplicate_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            run_revision=context.initial_run_revision,
            dispatch_task_id=f"review-pause-duplicate-{uuid4()}",
            retry_count=1,
        )

        run_row = await session.scalar(
            sa.select(FlowRuns).where(FlowRuns.id == context.run_id)
        )
        checkpoint_row = await session.scalar(
            sa.select(FlowRunReviewCheckpoints).where(
                FlowRunReviewCheckpoints.flow_run_id == context.run_id
            )
        )
        step_result_rows = (
            (
                await session.execute(
                    sa.select(FlowStepResults)
                    .where(FlowStepResults.flow_run_id == context.run_id)
                    .order_by(FlowStepResults.step_order.asc())
                )
            )
            .scalars()
            .all()
        )
        attempt_rows = (
            (
                await session.execute(
                    sa.select(FlowStepAttempts).where(
                        FlowStepAttempts.flow_run_id == context.run_id
                    )
                )
            )
            .scalars()
            .all()
        )
        outbox_rows = (
            (
                await session.execute(
                    sa.select(FlowRunAuditOutbox).where(
                        FlowRunAuditOutbox.flow_run_id == context.run_id
                    )
                )
            )
            .scalars()
            .all()
        )

    assert worker_result == {"status": FlowRunStatus.AWAITING_REVIEW.value}
    assert duplicate_result == {
        "status": "skipped",
        "reason": "run_awaiting_review",
    }
    completion_service.get_response.assert_awaited_once()
    assert run_row is not None
    assert run_row.status == FlowRunStatus.AWAITING_REVIEW.value
    assert run_row.revision == context.initial_run_revision + 1
    assert run_row.output_payload_json is None

    assert checkpoint_row is not None
    assert checkpoint_row.state == FlowRunReviewCheckpointState.AWAITING_REVIEW.value
    assert checkpoint_row.step_id == context.first_step_id
    assert checkpoint_row.step_order == 1
    assert checkpoint_row.attempt_no == 1
    assert checkpoint_row.original_payload_json == {
        "text": "This answer needs review.",
    }
    assert checkpoint_row.current_payload_json == checkpoint_row.original_payload_json
    assert context.second_step_id is not None
    assert context.third_step_id is not None
    assert checkpoint_row.next_step_ids_json == [
        str(context.second_step_id),
        str(context.third_step_id),
    ]

    assert [row.status for row in step_result_rows] == [
        FlowStepResultStatus.COMPLETED.value,
        FlowStepResultStatus.PENDING.value,
        FlowStepResultStatus.PENDING.value,
    ]
    assert step_result_rows[0].current_attempt_no == 1
    assert (
        step_result_rows[0].output_payload_json == checkpoint_row.original_payload_json
    )
    assert step_result_rows[1].output_payload_json is None
    assert step_result_rows[2].output_payload_json is None

    assert len(attempt_rows) == 1
    assert attempt_rows[0].status == FlowStepAttemptStatus.COMPLETED.value
    assert attempt_rows[0].finished_at is not None

    assert len(outbox_rows) == 1
    assert outbox_rows[0].review_checkpoint_id == checkpoint_row.id
    assert outbox_rows[0].checkpoint_revision == checkpoint_row.revision
    assert outbox_rows[0].run_revision == run_row.revision
    assert outbox_rows[0].action == "flow_run_review_checkpoint_opened"
    assert (
        outbox_rows[0].source == FlowRunLifecycleSource.REVIEW_CHECKPOINT_OPENED.value
    )
    assert outbox_rows[0].target_status == (
        FlowRunReviewCheckpointState.AWAITING_REVIEW.value
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_review_checkpoint_snapshot_is_enough_to_render_consumer_review_ui(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    output_contract = {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
        "additionalProperties": False,
    }
    completion_service = SimpleNamespace(
        get_response=AsyncMock(
            return_value=SimpleNamespace(
                completion='{"summary":"This answer needs review."}',
                total_token_count=17,
            )
        )
    )

    async with sessionmanager.session() as session:
        context = await _create_review_pause_runtime_context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            completion_service=completion_service,
            include_downstream_steps=False,
            first_step_output_type="json",
            first_step_output_contract=output_contract,
        )

        pause_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            run_revision=context.initial_run_revision,
            dispatch_task_id=f"review-pause-json-{uuid4()}",
            retry_count=0,
        )
        review_service = context.container.flow_run_review_checkpoint_service()
        checkpoint = await review_service.get_active_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
        )
        assert checkpoint is not None

        await session.execute(
            sa.update(FlowSteps)
            .where(FlowSteps.id == context.first_step_id)
            .values(
                user_description="Changed after checkpoint opened",
                output_contract={"type": "object", "properties": {}},
            )
        )

        unchanged_checkpoint = await review_service.get_active_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
        )

    assert pause_result == {"status": FlowRunStatus.AWAITING_REVIEW.value}
    assert unchanged_checkpoint is not None

    public = FlowAssembler().to_review_checkpoint_public(unchanged_checkpoint)
    assert public.step_label == "Draft answer for review"
    assert public.review_mode == FlowStepReviewMode.VIEW
    assert public.output_type == FlowOutputType.JSON
    assert not hasattr(public, "step_snapshot_available")
    assert public.output_contract == output_contract
    assert public.current_payload_json == {
        "text": '{"summary":"This answer needs review."}',
        "structured": {"summary": "This answer needs review."},
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_review_checkpoint_edit_validates_output_contract_before_persisting(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    output_contract: FlowPersistedJsonObject = {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
        "additionalProperties": False,
    }
    original_payload: FlowPersistedJsonObject = {
        "text": '{"summary":"This answer needs review."}',
        "structured": {"summary": "This answer needs review."},
    }
    edited_value: FlowPersistedJsonObject = {"summary": "Edited answer."}
    expected_edited_payload: FlowPersistedJsonObject = {
        "text": '{"summary": "Edited answer."}',
        "structured": {"summary": "Edited answer."},
    }
    completion_service = SimpleNamespace(
        get_response=AsyncMock(
            return_value=SimpleNamespace(
                completion='{"summary":"This answer needs review."}',
                total_token_count=17,
            )
        )
    )

    async with sessionmanager.session() as session:
        context = await _create_review_pause_runtime_context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            completion_service=completion_service,
            include_downstream_steps=False,
            first_step_output_type="json",
            first_step_output_contract=output_contract,
            first_step_review_mode=FlowStepReviewMode.EDIT,
        )
        await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            run_revision=context.initial_run_revision,
            dispatch_task_id=f"review-contract-pause-{uuid4()}",
            retry_count=0,
        )
        review_service = context.container.flow_run_review_checkpoint_service()
        checkpoint = await review_service.get_active_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
        )
        assert checkpoint is not None
        assert checkpoint.current_payload_json == original_payload
        run_before_invalid = await session.scalar(
            sa.select(FlowRuns).where(FlowRuns.id == context.run_id)
        )
        assert run_before_invalid is not None
        run_state_before_invalid = (
            run_before_invalid.status,
            run_before_invalid.revision,
            run_before_invalid.output_payload_json,
        )

        with pytest.raises(TypedIOValidationException) as exc_info:
            await review_service.edit_review_checkpoint(
                flow_id=context.flow_id,
                run_id=context.run_id,
                checkpoint_id=checkpoint.id,
                expected_checkpoint_revision=checkpoint.revision,
                edited_value={"wrong": "shape"},
            )

        with pytest.raises(TypedIOValidationException) as wrong_kind_exc:
            await review_service.edit_review_checkpoint(
                flow_id=context.flow_id,
                run_id=context.run_id,
                checkpoint_id=checkpoint.id,
                expected_checkpoint_revision=checkpoint.revision,
                edited_value='{"summary": "A JSON step does not take a string."}',
            )

        with pytest.raises(BadRequestException) as too_large_exc:
            await review_service.edit_review_checkpoint(
                flow_id=context.flow_id,
                run_id=context.run_id,
                checkpoint_id=checkpoint.id,
                expected_checkpoint_revision=checkpoint.revision,
                edited_value={
                    "summary": "x" * (get_settings().flow_max_inline_text_bytes + 1)
                },
            )

        await session.execute(
            sa.update(FlowRunReviewCheckpoints)
            .where(FlowRunReviewCheckpoints.id == checkpoint.id)
            .values(schema_version=2)
        )
        with pytest.raises(TypedIOValidationException) as schema_version_exc:
            await review_service.edit_review_checkpoint(
                flow_id=context.flow_id,
                run_id=context.run_id,
                checkpoint_id=checkpoint.id,
                expected_checkpoint_revision=checkpoint.revision,
                edited_value=edited_value,
            )
        await session.execute(
            sa.update(FlowRunReviewCheckpoints)
            .where(FlowRunReviewCheckpoints.id == checkpoint.id)
            .values(schema_version=1)
        )

        checkpoint_after_invalid = await session.scalar(
            sa.select(FlowRunReviewCheckpoints).where(
                FlowRunReviewCheckpoints.id == checkpoint.id
            )
        )
        step_result_after_invalid = await session.scalar(
            sa.select(FlowStepResults).where(
                FlowStepResults.flow_run_id == context.run_id,
                FlowStepResults.step_id == context.first_step_id,
            )
        )
        run_after_invalid = await session.scalar(
            sa.select(FlowRuns).where(FlowRuns.id == context.run_id)
        )
        outbox_actions_after_invalid = (
            (
                await session.execute(
                    sa.select(FlowRunAuditOutbox.action)
                    .where(FlowRunAuditOutbox.flow_run_id == context.run_id)
                    .order_by(FlowRunAuditOutbox.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        assert checkpoint_after_invalid is not None
        assert checkpoint_after_invalid.revision == checkpoint.revision
        assert checkpoint_after_invalid.current_payload_json == original_payload
        assert step_result_after_invalid is not None
        assert step_result_after_invalid.output_payload_json == original_payload
        assert run_after_invalid is not None
        assert (
            run_after_invalid.status,
            run_after_invalid.revision,
            run_after_invalid.output_payload_json,
        ) == run_state_before_invalid
        assert outbox_actions_after_invalid == ["flow_run_review_checkpoint_opened"]

        edited = await review_service.edit_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=checkpoint.revision,
            edited_value=edited_value,
        )
        step_result_after_valid = await session.scalar(
            sa.select(FlowStepResults).where(
                FlowStepResults.flow_run_id == context.run_id,
                FlowStepResults.step_id == context.first_step_id,
            )
        )
        outbox_actions_after_valid = (
            (
                await session.execute(
                    sa.select(FlowRunAuditOutbox.action)
                    .where(FlowRunAuditOutbox.flow_run_id == context.run_id)
                    .order_by(FlowRunAuditOutbox.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    assert exc_info.value.code == "typed_io_contract_violation"
    assert "Review checkpoint step 1 output" in str(exc_info.value)
    assert exc_info.value.context == {
        "checkpoint_id": str(checkpoint.id),
        "step_id": str(context.first_step_id),
        "step_order": 1,
        "payload_field": "structured",
    }
    assert wrong_kind_exc.value.code == "typed_io_validation_failed"
    assert "expects a JSON object or array" in str(wrong_kind_exc.value)
    assert too_large_exc.value.code == "flow_review_edit_output_too_large"
    assert schema_version_exc.value.code == "typed_io_validation_failed"
    assert edited.revision == checkpoint.revision + 1
    assert edited.current_payload_json == expected_edited_payload
    assert step_result_after_valid is not None
    assert step_result_after_valid.output_payload_json == expected_edited_payload
    assert outbox_actions_after_valid == [
        "flow_run_review_checkpoint_opened",
        "flow_run_review_checkpoint_edited",
    ]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "continuation",
    ["approve_then_resume", "approve_and_continue"],
)
async def test_edit_approve_resume_uses_edited_payload_for_downstream_steps(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
    continuation: str,
):
    completion_service = SimpleNamespace(
        get_response=AsyncMock(
            side_effect=[
                SimpleNamespace(
                    completion="This answer needs review.",
                    total_token_count=17,
                ),
                SimpleNamespace(
                    completion="Second step used edited answer.",
                    total_token_count=11,
                ),
                SimpleNamespace(
                    completion="Final archive output.",
                    total_token_count=13,
                ),
            ]
        )
    )
    edited_value = "Edited answer for resume."
    edited_payload = {"text": edited_value}

    async with sessionmanager.session() as session:
        context = await _create_review_pause_runtime_context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            completion_service=completion_service,
            first_step_review_mode=FlowStepReviewMode.EDIT,
        )

        pause_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            run_revision=context.initial_run_revision,
            dispatch_task_id=f"review-pause-{uuid4()}",
            retry_count=0,
        )
        review_service = context.container.flow_run_review_checkpoint_service()
        checkpoint = await review_service.get_active_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
        )
        assert checkpoint is not None
        edited = await review_service.edit_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=checkpoint.revision,
            edited_value=edited_value,
        )
        if continuation == "approve_then_resume":
            approved = await review_service.approve_review_checkpoint(
                flow_id=context.flow_id,
                run_id=context.run_id,
                checkpoint_id=checkpoint.id,
                expected_checkpoint_revision=edited.revision,
            )
            resumed = await review_service.resume_review_checkpoint(
                flow_id=context.flow_id,
                run_id=context.run_id,
                checkpoint_id=checkpoint.id,
                expected_checkpoint_revision=approved.checkpoint.revision,
                idempotency_key=f"resume-{uuid4()}",
            )
        else:
            # One command from the edited revision: the worker, the edited
            # payload and the audit sequence below must not tell the difference.
            resumed = await review_service.approve_and_resume_review_checkpoint(
                flow_id=context.flow_id,
                run_id=context.run_id,
                checkpoint_id=checkpoint.id,
                expected_checkpoint_revision=edited.revision,
                idempotency_key=f"continue-{uuid4()}",
            )
        stale_epoch_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            run_revision=context.initial_run_revision,
            dispatch_task_id=f"review-stale-epoch-{uuid4()}",
            retry_count=0,
        )
        completed_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            run_revision=resumed.run.revision,
            dispatch_task_id=f"review-resume-{uuid4()}",
            retry_count=0,
        )

        assert stale_epoch_result == {"status": "skipped", "reason": "run_queued"}
        run_row = await session.scalar(
            sa.select(FlowRuns).where(FlowRuns.id == context.run_id)
        )
        step_result_rows = (
            (
                await session.execute(
                    sa.select(FlowStepResults)
                    .where(FlowStepResults.flow_run_id == context.run_id)
                    .order_by(FlowStepResults.step_order.asc())
                )
            )
            .scalars()
            .all()
        )
        downstream_resolved_inputs = await session.scalar(
            sa.select(FlowStepAttemptResolvedInputs.resolved_input_edges_jsonb)
            .join(
                FlowStepAttempts,
                FlowStepAttempts.id
                == FlowStepAttemptResolvedInputs.flow_step_attempt_id,
            )
            .where(FlowStepAttempts.flow_run_id == context.run_id)
            .where(FlowStepAttempts.step_id == context.second_step_id)
        )
        checkpoint_row = await session.scalar(
            sa.select(FlowRunReviewCheckpoints).where(
                FlowRunReviewCheckpoints.id == checkpoint.id
            )
        )
        outbox_rows = (
            (
                await session.execute(
                    sa.select(FlowRunAuditOutbox)
                    .where(FlowRunAuditOutbox.flow_run_id == context.run_id)
                    .order_by(
                        FlowRunAuditOutbox.review_checkpoint_id.asc().nulls_last(),
                        FlowRunAuditOutbox.checkpoint_revision.asc().nulls_last(),
                        FlowRunAuditOutbox.run_revision.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )

    assert pause_result == {"status": FlowRunStatus.AWAITING_REVIEW.value}
    assert resumed.accepted is True
    assert resumed.run.status == FlowRunStatus.QUEUED
    assert completed_result == {"status": FlowRunStatus.COMPLETED.value}
    assert run_row is not None
    assert run_row.status == FlowRunStatus.COMPLETED.value
    assert run_row.output_payload_json == {
        "text": "Final archive output.",
    }

    assert checkpoint_row is not None
    assert checkpoint_row.state == FlowRunReviewCheckpointState.RESUMED.value
    assert checkpoint_row.current_payload_json == edited_payload

    assert [row.status for row in step_result_rows] == [
        FlowStepResultStatus.COMPLETED.value,
        FlowStepResultStatus.COMPLETED.value,
        FlowStepResultStatus.COMPLETED.value,
    ]
    assert step_result_rows[0].output_payload_json == edited_payload
    assert step_result_rows[1].input_payload_json["text"] == edited_payload["text"]
    assert step_result_rows[1].output_payload_json == {
        "text": "Second step used edited answer.",
    }
    assert downstream_resolved_inputs is not None
    assert downstream_resolved_inputs["edges"][0]["source"]["source_attempt_no"] == 1

    questions = [
        call.kwargs["question"]
        for call in completion_service.get_response.await_args_list
    ]
    assert questions == [
        "What needs review?",
        "Edited answer for resume.",
        "Second step used edited answer.",
    ]
    assert [row.action for row in outbox_rows] == [
        "flow_run_review_checkpoint_opened",
        "flow_run_review_checkpoint_edited",
        "flow_run_review_checkpoint_approved",
        "flow_run_review_checkpoint_resumed",
        "flow_run_completed",
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_edit_of_the_compiled_earlier_result_reaches_delivery(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    """Built from the compiled comparison -> decision -> letter flow: the gate
    sits on the comparison, and a schema-valid edit of it is what the decision
    and the delivered letter are derived from."""

    spec = compile_create_intent_to_spec(
        parse_create_flow_intent_arguments(
            {
                "flow_name": "Grant decision",
                "plan_rationale": "Compare, decide, write.",
                "steps": [
                    {
                        "name": "Compare offers",
                        "instructions": "Compare the offers.",
                        "output_fields": [
                            {
                                "name": "comparison",
                                "field_type": "string",
                                "description": "Offer comparison.",
                            }
                        ],
                        "review_mode": "edit",
                    },
                    {
                        "name": "Decide grant",
                        "instructions": "Decide the grant.",
                        "output_fields": [
                            {
                                "name": "decision",
                                "field_type": "string",
                                "description": "The decision.",
                            }
                        ],
                    },
                    {"name": "Write letter", "instructions": "Write the letter."},
                ],
            }
        ),
        context=CreateCompileContext(
            runtime_input_type=InputType.TEXT,
            final_output_type=OutputType.TEXT,
            checkpoint_intents=(
                CheckpointIntent(
                    evidence_level="explicit",
                    producer_kind="structured_result",
                    operation="set",
                    mode=FlowStepReviewMode.EDIT,
                    confidence="high",
                    evidence=["quote:user_message:1:Let me correct the comparison."],
                ),
            ),
        ),
    )
    sentinel = "Offer B is cheapest at 12 500 kr (edited)."

    async def derive(**kwargs: object) -> SimpleNamespace:
        # A provider whose answer is derived from the input it receives.
        question = str(kwargs["question"])
        call = completion_service.get_response.await_count
        if call == 1:
            completion = '{"comparison": "Offer A is cheapest."}'
        elif call == 2:
            completion = json.dumps({"decision": f"Grant based on: {question}"})
        else:
            completion = f"Letter: {question}"
        return SimpleNamespace(completion=completion, total_token_count=10)

    completion_service = SimpleNamespace(get_response=AsyncMock(side_effect=derive))

    async with sessionmanager.session() as session:
        context = await _create_review_pause_runtime_context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            completion_service=completion_service,
            compiled_spec=spec,
            input_payload_json={"text": "Two offers for a ramp."},
        )
        pause_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            run_revision=context.initial_run_revision,
            dispatch_task_id=f"compiled-review-pause-{uuid4()}",
            retry_count=0,
        )
        review_service = context.container.flow_run_review_checkpoint_service()
        checkpoint = await review_service.get_active_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
        )
        assert checkpoint is not None
        edited = await review_service.edit_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=checkpoint.revision,
            edited_value={"comparison": sentinel},
        )
        resumed = await review_service.approve_and_resume_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=edited.revision,
            idempotency_key=f"compiled-continue-{uuid4()}",
        )
        completed_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            run_revision=resumed.run.revision,
            dispatch_task_id=f"compiled-review-resume-{uuid4()}",
            retry_count=0,
        )
        step_result_rows = (
            (
                await session.execute(
                    sa.select(FlowStepResults)
                    .where(FlowStepResults.flow_run_id == context.run_id)
                    .order_by(FlowStepResults.step_order.asc())
                )
            )
            .scalars()
            .all()
        )
        run_row = await session.scalar(
            sa.select(FlowRuns).where(FlowRuns.id == context.run_id)
        )

    assert pause_result == {"status": FlowRunStatus.AWAITING_REVIEW.value}
    # The checkpoint is the compiled comparison step, not the later decision.
    assert checkpoint.step_id == context.first_step_id
    assert completed_result == {"status": FlowRunStatus.COMPLETED.value}
    assert step_result_rows[0].output_payload_json["structured"] == {
        "comparison": sentinel
    }
    decision_input = step_result_rows[1].input_payload_json["text"]
    assert sentinel in decision_input
    assert "Offer A is cheapest." not in decision_input
    letter_input = step_result_rows[2].input_payload_json["text"]
    assert sentinel in letter_input
    assert "Offer A is cheapest." not in letter_input
    assert run_row is not None
    delivered = run_row.output_payload_json["text"]
    assert delivered == f"Letter: {letter_input}"
    assert sentinel in delivered


def _compiled_price_review_spec() -> FlowDraftSpecCore:
    """Compare (reviewed) -> decide -> letter; the comparison states the price
    twice, so a decision step can re-derive an edited price from its sibling."""

    return compile_create_intent_to_spec(
        parse_create_flow_intent_arguments(
            {
                "flow_name": "Grant decision",
                "plan_rationale": "Compare, decide, write.",
                "steps": [
                    {
                        "name": "Compare offers",
                        "instructions": "Compare the offers.",
                        "output_fields": [
                            {
                                "name": "price",
                                "field_type": "string",
                                "description": "Cheapest price.",
                            },
                            {
                                "name": "comparison",
                                "field_type": "string",
                                "description": "Offer comparison.",
                            },
                        ],
                        "review_mode": "edit",
                    },
                    {
                        "name": "Decide grant",
                        "instructions": "Decide the grant.",
                        "output_fields": [
                            {
                                "name": "decision",
                                "field_type": "string",
                                "description": "The decision.",
                            }
                        ],
                    },
                    {"name": "Write letter", "instructions": "Write the letter."},
                ],
            }
        ),
        context=CreateCompileContext(
            runtime_input_type=InputType.TEXT,
            final_output_type=OutputType.TEXT,
            checkpoint_intents=(
                CheckpointIntent(
                    evidence_level="explicit",
                    producer_kind="structured_result",
                    operation="set",
                    mode=FlowStepReviewMode.EDIT,
                    confidence="high",
                    evidence=["quote:user_message:1:Let me correct the price."],
                ),
            ),
        ),
    )


_ORIGINAL_PRICE = "71 200 kr"
_EDITED_PRICE = "64 900 kr"


def _price_deriving_completion_service() -> SimpleNamespace:
    """A provider that re-derives the price from the comparison text unless its
    request names the price as set by the reviewer - the failure mechanism of
    a model step that re-authors reviewed values from its whole input."""

    async def derive(**kwargs: object) -> SimpleNamespace:
        question = str(kwargs["question"])
        prompt = str(kwargs.get("prompt_override") or "")
        call = completion_service.get_response.await_count
        if call == 1:
            completion = json.dumps(
                {
                    "price": _ORIGINAL_PRICE,
                    "comparison": f"Offer A at {_ORIGINAL_PRICE} is cheapest.",
                }
            )
        elif call == 2:
            reviewed = json.loads(question)
            price = (
                reviewed["price"]
                if '["price"] set by the reviewer' in prompt
                else reviewed["comparison"].split(" at ")[1].split(" is")[0]
            )
            completion = json.dumps({"decision": f"Grant at {price}."})
        else:
            decided = [line for line in question.splitlines() if "Grant at" in line]
            completion = f"Letter: {' '.join(decided)}"
        return SimpleNamespace(completion=completion, total_token_count=10)

    completion_service = SimpleNamespace(get_response=AsyncMock(side_effect=derive))
    return completion_service


async def _pause_edit_price_and_resume(
    *,
    session: AsyncSession,
    completion_service: SimpleNamespace,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
    edit: bool = True,
) -> tuple[_ReviewPauseRuntimeContext, int]:
    context = await _create_review_pause_runtime_context(
        session=session,
        admin_user=admin_user,
        test_tenant=test_tenant,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        completion_service=completion_service,
        compiled_spec=_compiled_price_review_spec(),
        input_payload_json={"text": "Two offers for a ramp."},
    )
    pause_result = await context.executor.execute(
        run_id=context.run_id,
        flow_id=context.flow_id,
        tenant_id=context.tenant_id,
        run_revision=context.initial_run_revision,
        dispatch_task_id=f"price-review-pause-{uuid4()}",
        retry_count=0,
    )
    assert pause_result == {"status": FlowRunStatus.AWAITING_REVIEW.value}
    review_service = context.container.flow_run_review_checkpoint_service()
    checkpoint = await review_service.get_active_review_checkpoint(
        flow_id=context.flow_id,
        run_id=context.run_id,
    )
    assert checkpoint is not None
    revision = checkpoint.revision
    if edit:
        edited = await review_service.edit_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=checkpoint.revision,
            edited_value={
                "price": _EDITED_PRICE,
                "comparison": f"Offer A at {_ORIGINAL_PRICE} is cheapest.",
            },
        )
        revision = edited.revision
    resumed = await review_service.approve_and_resume_review_checkpoint(
        flow_id=context.flow_id,
        run_id=context.run_id,
        checkpoint_id=checkpoint.id,
        expected_checkpoint_revision=revision,
        idempotency_key=f"price-continue-{uuid4()}",
    )
    return context, resumed.run.revision


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_reviewer_edit_is_named_to_the_next_model_step_and_reaches_delivery(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    completion_service = _price_deriving_completion_service()
    async with sessionmanager.session() as session:
        context, run_revision = await _pause_edit_price_and_resume(
            session=session,
            completion_service=completion_service,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        completed_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            run_revision=run_revision,
            dispatch_task_id=f"price-review-resume-{uuid4()}",
            retry_count=0,
        )
        await session.commit()

    run_row, _, step_result_rows, _, _ = await _review_pause_state_from_fresh_session(
        run_id=context.run_id,
        tenant_id=context.tenant_id,
    )

    assert completed_result == {"status": FlowRunStatus.COMPLETED.value}
    decision_prompt = step_result_rows[1].effective_prompt
    assert decision_prompt is not None
    assert 'step 1 "Compare offers"' in decision_prompt
    assert (
        'binding "input_source", selection ["output", "structured"]' in decision_prompt
    )
    assert '["price"] set by the reviewer' in decision_prompt
    assert '["comparison"]' not in decision_prompt
    assert _ORIGINAL_PRICE not in decision_prompt
    # The compiled letter also binds the reviewed price itself, so it is told
    # too, relative to its own selection; the unchanged comparison is not named.
    letter_prompt = step_result_rows[2].effective_prompt or ""
    assert (
        'selection ["output", "structured", "price"]: [] set by the reviewer'
        in letter_prompt
    )
    assert '"comparison"]' not in letter_prompt
    assert _ORIGINAL_PRICE not in letter_prompt
    assert run_row is not None
    delivered = run_row.output_payload_json["text"]
    assert _EDITED_PRICE in delivered
    assert _ORIGINAL_PRICE not in delivered


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("limit_name", "limit_value"),
    [
        ("REVIEWED_EDIT_READ_MAX_ROWS", 0),
        ("REVIEWED_EDIT_READ_MAX_LOGICAL_BYTES", 1),
    ],
)
async def test_an_over_budget_reviewed_edit_read_fails_the_run_before_any_provider_call(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
    monkeypatch,
    limit_name: str,
    limit_value: int,
):
    completion_service = _price_deriving_completion_service()
    async with sessionmanager.session() as session:
        context, run_revision = await _pause_edit_price_and_resume(
            session=session,
            completion_service=completion_service,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        # raising=False: at a base without the limit the run must still fail.
        monkeypatch.setattr(
            f"eneo.flows.runtime.executor.{limit_name}", limit_value, raising=False
        )
        failed_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            run_revision=run_revision,
            dispatch_task_id=f"price-review-overflow-{uuid4()}",
            retry_count=0,
        )
        await session.commit()

    (
        run_row,
        _,
        step_result_rows,
        _,
        outbox_rows,
    ) = await _review_pause_state_from_fresh_session(
        run_id=context.run_id,
        tenant_id=context.tenant_id,
    )

    code = FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE.value
    assert failed_result == {"status": "failed", "error": code}
    # Only the reviewed step ever reached the provider.
    assert completion_service.get_response.await_count == 1
    assert run_row is not None
    assert run_row.status == FlowRunStatus.FAILED.value
    assert run_row.error_json is not None
    assert run_row.error_json["code"] == code
    assert step_result_rows[0].status == FlowStepResultStatus.COMPLETED.value
    assert all(
        row.status != FlowStepResultStatus.COMPLETED.value
        for row in step_result_rows[1:]
    )
    assert "flow_run_failed" in {row.action for row in outbox_rows}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_approval_without_a_change_is_never_read_or_counted(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
    monkeypatch,
):
    completion_service = _price_deriving_completion_service()
    async with sessionmanager.session() as session:
        context, run_revision = await _pause_edit_price_and_resume(
            session=session,
            completion_service=completion_service,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            edit=False,
        )
        # No row may be read: any counted untouched approval fails the run.
        monkeypatch.setattr(
            "eneo.flows.runtime.executor.REVIEWED_EDIT_READ_MAX_ROWS", 0
        )
        completed_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            run_revision=run_revision,
            dispatch_task_id=f"price-review-untouched-{uuid4()}",
            retry_count=0,
        )
        await session.commit()

    run_row, _, step_result_rows, _, _ = await _review_pause_state_from_fresh_session(
        run_id=context.run_id,
        tenant_id=context.tenant_id,
    )

    assert completed_result == {"status": FlowRunStatus.COMPLETED.value}
    assert run_row is not None
    assert run_row.status == FlowRunStatus.COMPLETED.value
    assert all(
        "set by the reviewer" not in (row.effective_prompt or "")
        for row in step_result_rows
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_too_many_reviewed_references_fail_the_reading_step_before_its_provider_call(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
    monkeypatch,
):
    completion_service = _price_deriving_completion_service()
    async with sessionmanager.session() as session:
        context, run_revision = await _pause_edit_price_and_resume(
            session=session,
            completion_service=completion_service,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        # raising=False: at a base without the limit the run must still fail.
        monkeypatch.setattr(
            "eneo.flows.domain.review_edit_references.REVIEWED_EDIT_MAX_REFERENCES",
            0,
            raising=False,
        )
        failed_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            run_revision=run_revision,
            dispatch_task_id=f"price-review-reference-overflow-{uuid4()}",
            retry_count=0,
        )
        await session.commit()

    run_row, _, step_result_rows, _, _ = await _review_pause_state_from_fresh_session(
        run_id=context.run_id,
        tenant_id=context.tenant_id,
    )

    code = FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE.value
    assert failed_result["status"] == "failed"
    assert completion_service.get_response.await_count == 1
    assert run_row is not None
    assert run_row.status == FlowRunStatus.FAILED.value
    assert run_row.error_json is not None
    assert run_row.error_json["code"] == code
    assert step_result_rows[1].status == FlowStepResultStatus.FAILED.value
    assert step_result_rows[1].error_code == code


@pytest.mark.asyncio
@pytest.mark.integration
async def test_resume_last_step_review_terminalizes_completed_run(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    completion_service = SimpleNamespace(
        get_response=AsyncMock(
            return_value=SimpleNamespace(
                completion="Last step answer needs review.",
                total_token_count=17,
            )
        )
    )
    edited_value = "Approved final answer."
    edited_payload = {"text": edited_value}

    async with sessionmanager.session() as session:
        context = await _create_review_pause_runtime_context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            completion_service=completion_service,
            include_downstream_steps=False,
            first_step_review_mode=FlowStepReviewMode.EDIT,
        )

        pause_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            run_revision=context.initial_run_revision,
            dispatch_task_id=f"review-last-step-pause-{uuid4()}",
            retry_count=0,
        )
        review_service = context.container.flow_run_review_checkpoint_service()
        checkpoint = await review_service.get_active_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
        )
        assert checkpoint is not None
        edited = await review_service.edit_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=checkpoint.revision,
            edited_value=edited_value,
        )
        approved = await review_service.approve_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=edited.revision,
        )
        resumed = await review_service.resume_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=approved.checkpoint.revision,
            idempotency_key=f"resume-last-step-{uuid4()}",
        )
        completed_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            run_revision=resumed.run.revision,
            dispatch_task_id=f"review-last-step-resume-{uuid4()}",
            retry_count=0,
        )

        run_row = await session.scalar(
            sa.select(FlowRuns).where(FlowRuns.id == context.run_id)
        )
        checkpoint_row = await session.scalar(
            sa.select(FlowRunReviewCheckpoints).where(
                FlowRunReviewCheckpoints.id == checkpoint.id
            )
        )
        run_values = (
            (run_row.status, run_row.output_payload_json)
            if run_row is not None
            else None
        )
        checkpoint_values = (
            (checkpoint_row.next_step_ids_json, checkpoint_row.state)
            if checkpoint_row is not None
            else None
        )
        outbox_actions = (
            (
                await session.execute(
                    sa.select(FlowRunAuditOutbox.action)
                    .where(FlowRunAuditOutbox.flow_run_id == context.run_id)
                    .order_by(
                        FlowRunAuditOutbox.review_checkpoint_id.asc().nulls_last(),
                        FlowRunAuditOutbox.checkpoint_revision.asc().nulls_last(),
                        FlowRunAuditOutbox.run_revision.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )

    assert pause_result == {"status": FlowRunStatus.AWAITING_REVIEW.value}
    assert resumed.accepted is True
    assert completed_result == {"status": FlowRunStatus.COMPLETED.value}
    assert run_values == (FlowRunStatus.COMPLETED.value, edited_payload)
    assert checkpoint_values == ([], FlowRunReviewCheckpointState.RESUMED.value)
    completion_service.get_response.assert_awaited_once()
    assert outbox_actions == [
        "flow_run_review_checkpoint_opened",
        "flow_run_review_checkpoint_edited",
        "flow_run_review_checkpoint_approved",
        "flow_run_review_checkpoint_resumed",
        "flow_run_completed",
    ]
