from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.database import sessionmanager
from intric.database.tables.flow_tables import (
    FlowRunAuditOutbox,
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowStepAttempts,
    FlowStepResults,
    FlowSteps,
)
from intric.flows.api.flow_assembler import FlowAssembler
from intric.flows.assistant_execution_snapshot import (
    build_assistant_execution_snapshot,
    stable_hash,
)
from intric.flows.domain.flow import (
    Flow,
    FlowRunStatus,
    FlowStep,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
    JsonObject,
)
from intric.flows.enums import (
    FlowOutputType,
    FlowRunLifecycleSource,
    FlowRunReviewCheckpointState,
)
from intric.flows.flow_factory import FlowFactory
from intric.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy
from intric.flows.infrastructure.flow_repo import FlowRepository
from intric.flows.infrastructure.flow_run_repo import FlowRunRepository
from intric.flows.infrastructure.flow_version_repo import FlowVersionRepository
from intric.flows.published_definition import build_published_definition_json
from intric.flows.runtime.executor import FlowRunExecutor, FlowRunExecutorConfig
from intric.flows.runtime.tasks import enable_autobegin_for_flow_task_session
from intric.main.container.container import Container
from intric.main.exceptions import TypedIOValidationException


class _ModelKwargs:
    def __init__(self, **values):
        self._values = values

    def model_dump(self, *, exclude_none: bool = False, **_kwargs):
        if exclude_none:
            return {
                key: value for key, value in self._values.items() if value is not None
            }
        return dict(self._values)


class _RuntimeAssistant:
    def __init__(self, *, assistant_id: UUID, model_id: UUID, model_name: str):
        self.id = assistant_id
        self.origin = "flow_managed"
        self.prompt = SimpleNamespace(text="Answer the submitted question.")
        self.completion_model = SimpleNamespace(
            id=model_id,
            name=model_name,
            nickname=model_name,
            litellm_model_name=model_name,
            provider_type="openai",
        )
        self.completion_model_kwargs = _ModelKwargs(temperature=0.2)
        self.collections = []
        self.websites = []
        self.integration_knowledge_list = []
        self.mcp_servers = []

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
            mcp_policy="inherit",
            input_config=None,
            output_config=None,
            review_policy=FlowStepReviewPolicy(mode=FlowStepReviewMode.VIEW),
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
                    input_bindings={"answer": "{{step_1.output.text}}"},
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
                    user_description="Archive reviewed answer",
                    input_source="previous_step",
                    input_type="text",
                    input_contract=None,
                    output_mode="pass_through",
                    output_type="text",
                    output_contract=None,
                    input_bindings={"answer": "{{step_2.output.text}}"},
                    output_classification_override=None,
                    mcp_policy="inherit",
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
        "mcp_policy": step.mcp_policy.value,
        "assistant_snapshot": assistant_snapshot,
    }
    if step.review_policy is not None:
        payload["review_policy"] = step.review_policy.model_dump(mode="json")
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
) -> _ReviewPauseRuntimeContext:
    enable_autobegin_for_flow_task_session(session)
    container = Container(
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
    flow_repo = FlowRepository(session=session, factory=FlowFactory())
    version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
    flow = await flow_repo.create(
        flow=_build_review_pause_flow(
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=admin_user.id,
            assistant_id=assistant.id,
            include_downstream_steps=include_downstream_steps,
            first_step_output_type=first_step_output_type,
            first_step_output_contract=first_step_output_contract,
        ),
        tenant_id=admin_user.tenant_id,
    )
    flow = await flow_repo.update(
        flow=flow.model_copy(update={"published_version": 1}),
        tenant_id=admin_user.tenant_id,
    )
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
        model_name="gpt-4o-mini",
    )
    assistant_snapshot = build_assistant_execution_snapshot(
        assistant=runtime_assistant,
        mcp_server_entities=[],
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
        definition_checksum=stable_hash(definition_json),
        definition_json=definition_json,
        tenant_id=admin_user.tenant_id,
    )
    run = await container.flow_run_service().create_run(
        flow_id=flow.id,
        input_payload_json={"question": "What needs review?"},
        expected_flow_version=1,
        step_inputs=None,
        idempotency_key=f"review-pause-{uuid4()}",
    )
    audit_service = SimpleNamespace(log_async=AsyncMock(return_value=uuid4()))
    executor = FlowRunExecutor(
        user=admin_user,
        session=session,
        flow_repo=container.flow_repo(),
        flow_run_repo=container.flow_run_repo(),
        flow_run_terminalizer=container.flow_run_terminalizer(),
        flow_version_repo=container.flow_version_repo(),
        space_repo=container.space_repo(),
        completion_service=completion_service,
        file_repo=container.file_repo(),
        template_asset_service=container.flow_template_asset_service(),
        encryption_service=container.encryption_service(),
        audit_service=audit_service,
        references_service=container.references_service(),
        transcriber=container.transcriber(),
        config=FlowRunExecutorConfig(
            max_inline_text_bytes=1024 * 1024,
            http_request_timeout_seconds=2.0,
            http_max_timeout_seconds=2.0,
            http_allow_private_networks=False,
        ),
    )
    executor._load_assistant = AsyncMock(return_value=runtime_assistant)
    return _ReviewPauseRuntimeContext(
        container=container,
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

        original_open = FlowRunRepository.open_review_checkpoint_for_completed_step

        async def _terminalize_then_open(self, **kwargs):
            async with sessionmanager.session() as terminal_session:
                enable_autobegin_for_flow_task_session(terminal_session)
                terminal_container = Container(
                    session=providers.Object(terminal_session),
                    user=providers.Object(admin_user),
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
                    error_code=f"terminalized_{target_status.value}",
                    error_message=f"Run was terminalized as {target_status.value}.",
                )
                await terminal_session.commit()
            return await original_open(self, **kwargs)

        monkeypatch.setattr(
            FlowRunRepository,
            "open_review_checkpoint_for_completed_step",
            _terminalize_then_open,
        )

        worker_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            celery_task_id=f"review-open-terminalized-{target_status.value}",
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
        "webhook_delivered": False,
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
            celery_task_id=f"review-pause-{uuid4()}",
            retry_count=0,
        )
        duplicate_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            celery_task_id=f"review-pause-duplicate-{uuid4()}",
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
        "webhook_delivered": False,
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
            celery_task_id=f"review-pause-json-{uuid4()}",
            retry_count=0,
        )
        checkpoint = (
            await context.container.flow_run_service().get_active_review_checkpoint(
                flow_id=context.flow_id,
                run_id=context.run_id,
            )
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

        unchanged_checkpoint = (
            await context.container.flow_run_service().get_active_review_checkpoint(
                flow_id=context.flow_id,
                run_id=context.run_id,
            )
        )

    assert pause_result == {"status": FlowRunStatus.AWAITING_REVIEW.value}
    assert unchanged_checkpoint is not None

    public = FlowAssembler().to_review_checkpoint_public(unchanged_checkpoint)
    assert public.step_label == "Draft answer for review"
    assert public.review_mode == FlowStepReviewMode.VIEW
    assert public.output_type == FlowOutputType.JSON
    assert public.step_snapshot_available is True
    assert public.output_contract == output_contract
    assert public.current_payload_json == {
        "text": '{"summary":"This answer needs review."}',
        "structured": {"summary": "This answer needs review."},
        "webhook_delivered": False,
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
    output_contract: JsonObject = {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
        "additionalProperties": False,
    }
    original_payload: JsonObject = {
        "text": '{"summary":"This answer needs review."}',
        "structured": {"summary": "This answer needs review."},
        "webhook_delivered": False,
    }
    invalid_payload: JsonObject = {
        "text": '{"wrong":"shape"}',
        "structured": {"wrong": "shape"},
        "webhook_delivered": False,
    }
    missing_structured_payload: JsonObject = {
        "text": '{"summary":"Missing structured slot."}',
        "webhook_delivered": False,
    }
    valid_payload: JsonObject = {
        "text": '{"summary":"Edited answer."}',
        "structured": {"summary": "Edited answer."},
        "webhook_delivered": False,
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
        await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            celery_task_id=f"review-contract-pause-{uuid4()}",
            retry_count=0,
        )
        run_service = context.container.flow_run_service()
        checkpoint = await run_service.get_active_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
        )
        assert checkpoint is not None
        assert checkpoint.current_payload_json == original_payload

        with pytest.raises(TypedIOValidationException) as exc_info:
            await run_service.edit_review_checkpoint(
                flow_id=context.flow_id,
                run_id=context.run_id,
                checkpoint_id=checkpoint.id,
                expected_checkpoint_revision=checkpoint.revision,
                current_payload_json=invalid_payload,
            )

        with pytest.raises(TypedIOValidationException) as missing_structured_exc:
            await run_service.edit_review_checkpoint(
                flow_id=context.flow_id,
                run_id=context.run_id,
                checkpoint_id=checkpoint.id,
                expected_checkpoint_revision=checkpoint.revision,
                current_payload_json=missing_structured_payload,
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
        assert outbox_actions_after_invalid == ["flow_run_review_checkpoint_opened"]

        edited = await run_service.edit_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=checkpoint.revision,
            current_payload_json=valid_payload,
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
    assert missing_structured_exc.value.code == "typed_io_contract_violation"
    assert "field `structured` is required" in str(missing_structured_exc.value)
    assert missing_structured_exc.value.context == exc_info.value.context
    assert edited.revision == checkpoint.revision + 1
    assert edited.current_payload_json == valid_payload
    assert step_result_after_valid is not None
    assert step_result_after_valid.output_payload_json == valid_payload
    assert outbox_actions_after_valid == [
        "flow_run_review_checkpoint_opened",
        "flow_run_review_checkpoint_edited",
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_edit_approve_resume_uses_edited_payload_for_downstream_steps(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
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
    edited_payload = {
        "text": "Edited answer for resume.",
        "webhook_delivered": False,
    }

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

        pause_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            celery_task_id=f"review-pause-{uuid4()}",
            retry_count=0,
        )
        run_service = context.container.flow_run_service()
        checkpoint = await run_service.get_active_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
        )
        assert checkpoint is not None
        edited = await run_service.edit_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=checkpoint.revision,
            current_payload_json=edited_payload,
        )
        approved = await run_service.approve_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=edited.revision,
        )
        resumed = await run_service.resume_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=approved.revision,
            idempotency_key=f"resume-{uuid4()}",
        )
        completed_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            celery_task_id=f"review-resume-{uuid4()}",
            retry_count=0,
        )

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
        "webhook_delivered": False,
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
        "webhook_delivered": False,
    }

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
    edited_payload = {
        "text": "Approved final answer.",
        "webhook_delivered": False,
    }

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
        )

        pause_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            celery_task_id=f"review-last-step-pause-{uuid4()}",
            retry_count=0,
        )
        run_service = context.container.flow_run_service()
        checkpoint = await run_service.get_active_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
        )
        assert checkpoint is not None
        edited = await run_service.edit_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=checkpoint.revision,
            current_payload_json=edited_payload,
        )
        approved = await run_service.approve_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=edited.revision,
        )
        resumed = await run_service.resume_review_checkpoint(
            flow_id=context.flow_id,
            run_id=context.run_id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=approved.revision,
            idempotency_key=f"resume-last-step-{uuid4()}",
        )
        completed_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            celery_task_id=f"review-last-step-resume-{uuid4()}",
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
