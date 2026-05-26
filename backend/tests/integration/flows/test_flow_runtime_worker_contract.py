from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from intric.database.database import sessionmanager
from intric.database.tables.flow_tables import (
    FlowRunAuditOutbox,
    FlowRunRerunInvalidatedSteps,
    FlowRunRerunOperations,
    FlowRuns,
    FlowStepAttempts,
    FlowStepResults,
)
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
from intric.flows.enums import FlowRunLifecycleSource, FlowRunRerunOperationStatus
from intric.flows.flow_factory import FlowFactory
from intric.flows.flow_run_error import FlowRunError
from intric.flows.infrastructure.flow_repo import FlowRepository
from intric.flows.infrastructure.flow_version_repo import FlowVersionRepository
from intric.flows.published_definition import build_published_definition_json
from intric.flows.runtime.executor import FlowRunExecutor, FlowRunExecutorConfig
from intric.flows.runtime.tasks import enable_autobegin_for_flow_task_session
from intric.main.container.container import Container


@dataclass(frozen=True, slots=True)
class _RuntimeWorkerContext:
    executor: FlowRunExecutor
    run_id: UUID
    flow_id: UUID
    tenant_id: UUID


class _ModelKwargs:
    def __init__(self, **values):
        self._values = values

    def model_dump(self, *, exclude_none: bool = False, **_kwargs):
        if exclude_none:
            return {
                key: value for key, value in self._values.items() if value is not None
            }
        return dict(self._values)

    def model_copy(self, *, update):
        values = dict(self._values)
        values.update(update)
        return _ModelKwargs(**values)


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


def _build_flow(
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    assistant_id: UUID,
    output_mode: str = "pass_through",
    output_type: str = "text",
    output_contract: JsonObject | None = None,
) -> Flow:
    return Flow(
        id=None,
        tenant_id=tenant_id,
        space_id=space_id,
        name="Runtime Worker Contract Flow",
        description="Runtime worker contract for run creation and execution.",
        created_by_user_id=user_id,
        owner_user_id=user_id,
        published_version=None,
        metadata_json={
            "form_schema": {"fields": [{"name": "question", "type": "text"}]}
        },
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
                user_description="Answer the submitted question",
                input_source="flow_input",
                input_type="text",
                input_contract=None,
                output_mode=output_mode,
                output_type=output_type,
                output_contract=output_contract,
                input_bindings={"question": "{{flow.input.question}}"},
                output_classification_override=None,
                mcp_policy="inherit",
                input_config=None,
                output_config=None,
            )
        ],
    )


async def _create_runtime_worker_context(
    *,
    session,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
    completion_service,
    output_mode: str = "pass_through",
    output_type: str = "text",
    output_contract: JsonObject | None = None,
) -> _RuntimeWorkerContext:
    enable_autobegin_for_flow_task_session(session)
    container = Container(
        session=providers.Object(session),
        user=providers.Object(admin_user),
        tenant=providers.Object(test_tenant),
    )
    model = await completion_model_factory(session, "gpt-4o-mini")
    space = await space_factory(session, "Runtime worker contract space", [model.id])
    assistant = await assistant_factory(
        session,
        "Runtime Worker Assistant",
        model.id,
        space_id=space.id,
    )
    flow_repo = FlowRepository(session=session, factory=FlowFactory())
    version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
    flow = await flow_repo.create(
        flow=_build_flow(
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=admin_user.id,
            assistant_id=assistant.id,
            output_mode=output_mode,
            output_type=output_type,
            output_contract=output_contract,
        ),
        tenant_id=admin_user.tenant_id,
    )
    flow = await flow_repo.update(
        flow=flow.model_copy(update={"published_version": 1}),
        tenant_id=admin_user.tenant_id,
    )
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
    step = flow.steps[0]
    definition_step = {
        "step_id": str(step.id),
        "assistant_id": str(step.assistant_id),
        "step_order": 1,
        "user_description": step.user_description,
        "input_source": step.input_source,
        "input_type": step.input_type,
        "input_bindings": step.input_bindings,
        "output_mode": step.output_mode,
        "output_type": step.output_type,
        "mcp_policy": step.mcp_policy,
        "assistant_snapshot": assistant_snapshot,
    }
    if output_contract is not None:
        definition_step["output_contract"] = output_contract
    definition_json = build_published_definition_json(
        flow_id=flow.id,
        name=flow.name,
        description=flow.description,
        metadata_json=flow.metadata_json,
        steps=[definition_step],
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
        input_payload_json={"question": "What happened?"},
        expected_flow_version=1,
        step_inputs=None,
        idempotency_key=f"runtime-worker-contract-{uuid4()}",
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
    assert flow.id is not None
    assert step.id is not None
    return _RuntimeWorkerContext(
        executor=executor,
        run_id=run.id,
        flow_id=flow.id,
        tenant_id=admin_user.tenant_id,
    )


async def _failure_state_from_fresh_session(
    *,
    run_id: UUID,
    tenant_id: UUID,
) -> tuple[
    FlowRuns | None,
    FlowStepResults | None,
    list[FlowStepAttempts],
    list[FlowRunAuditOutbox],
]:
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        run_row = await session.scalar(sa.select(FlowRuns).where(FlowRuns.id == run_id))
        step_result_row = await session.scalar(
            sa.select(FlowStepResults).where(FlowStepResults.flow_run_id == run_id)
        )
        attempt_rows = (
            (
                await session.execute(
                    sa.select(FlowStepAttempts)
                    .where(FlowStepAttempts.flow_run_id == run_id)
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
    return run_row, step_result_row, attempt_rows, outbox_rows


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("target_status", "expected_worker_result", "expected_step_status"),
    [
        (
            FlowRunStatus.CANCELLED,
            {"status": "skipped", "reason": "run_cancelled"},
            FlowStepResultStatus.CANCELLED,
        ),
        (
            FlowRunStatus.FAILED,
            {"status": "failed", "error": "Run was terminalized as failed."},
            FlowStepResultStatus.FAILED,
        ),
    ],
)
async def test_late_output_after_terminalization_does_not_complete_attempt_or_webhook(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
    target_status,
    expected_worker_result,
    expected_step_status,
):
    completion_service = SimpleNamespace(get_response=AsyncMock())
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        context = await _create_runtime_worker_context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            completion_service=completion_service,
            output_mode="http_post",
        )
        await session.commit()

        async def _terminalize_before_provider_success(**_kwargs):
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
                    error=FlowRunError.from_source(
                        (
                            FlowRunLifecycleSource.USER_CANCEL
                            if target_status == FlowRunStatus.CANCELLED
                            else FlowRunLifecycleSource.STALE_RUNNING_RECONCILER
                        ),
                        code=f"terminalized_{target_status.value}",
                        message=f"Run was terminalized as {target_status.value}.",
                    ),
                )
                await terminal_session.commit()
            return SimpleNamespace(
                completion="late provider success",
                total_token_count=13,
            )

        completion_service.get_response.side_effect = (
            _terminalize_before_provider_success
        )
        context.executor._deliver_webhook = AsyncMock()

        worker_result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            celery_task_id=f"late-output-{target_status.value}",
            retry_count=0,
        )

    (
        run_row,
        step_result_row,
        attempt_rows,
        outbox_rows,
    ) = await _failure_state_from_fresh_session(
        run_id=context.run_id,
        tenant_id=context.tenant_id,
    )

    assert worker_result == expected_worker_result
    assert run_row is not None
    assert run_row.status == target_status.value
    assert step_result_row is not None
    assert step_result_row.status == expected_step_status.value
    assert step_result_row.output_payload_json is None
    assert len(attempt_rows) == 1
    assert attempt_rows[0].status == (
        FlowStepAttemptStatus.CANCELLED.value
        if target_status == FlowRunStatus.CANCELLED
        else FlowStepAttemptStatus.FAILED.value
    )
    context.executor._deliver_webhook.assert_not_awaited()
    assert FlowRunLifecycleSource.EXECUTOR_COMPLETED.value not in {
        row.source for row in outbox_rows
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_run_created_by_service_executes_to_terminal_worker_state(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
            tenant=providers.Object(test_tenant),
        )
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Runtime worker contract space", [model.id]
        )
        assistant = await assistant_factory(
            session,
            "Runtime Worker Assistant",
            model.id,
            space_id=space.id,
        )

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        flow = flow.model_copy(update={"published_version": 1})
        flow = await flow_repo.update(flow=flow, tenant_id=admin_user.tenant_id)
        run_correlation_id = f"runtime-worker-contract-{uuid4()}"
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

        step = flow.steps[0]
        definition_json = build_published_definition_json(
            flow_id=flow.id,
            name=flow.name,
            description=flow.description,
            metadata_json=flow.metadata_json,
            steps=[
                {
                    "step_id": str(step.id),
                    "assistant_id": str(step.assistant_id),
                    "step_order": 1,
                    "user_description": step.user_description,
                    "input_source": step.input_source,
                    "input_type": step.input_type,
                    "input_bindings": step.input_bindings,
                    "output_mode": step.output_mode,
                    "output_type": step.output_type,
                    "mcp_policy": step.mcp_policy,
                    "assistant_snapshot": assistant_snapshot,
                }
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
            input_payload_json={"question": "What happened?"},
            expected_flow_version=1,
            step_inputs=None,
            idempotency_key=run_correlation_id,
        )

        completion_service = SimpleNamespace(
            get_response=AsyncMock(
                side_effect=[
                    SimpleNamespace(
                        completion="The run completed.",
                        total_token_count=17,
                    ),
                    SimpleNamespace(
                        completion="The rerun completed.",
                        total_token_count=19,
                    ),
                ]
            )
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

        worker_result = await executor.execute(
            run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            celery_task_id=run_correlation_id,
            retry_count=0,
        )

        assert worker_result == {"status": "completed"}

        run_row = await session.scalar(sa.select(FlowRuns).where(FlowRuns.id == run.id))
        assert run_row is not None
        assert run_row.status == FlowRunStatus.COMPLETED.value
        assert run_row.output_payload_json == {
            "text": "The run completed.",
            "webhook_delivered": False,
        }

        step_result_rows = (
            (
                await session.execute(
                    sa.select(FlowStepResults).where(
                        FlowStepResults.flow_run_id == run.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(step_result_rows) == 1
        assert step_result_rows[0].status == FlowStepResultStatus.COMPLETED.value
        assert step_result_rows[0].output_payload_json == {
            "text": "The run completed.",
            "webhook_delivered": False,
        }

        attempt_rows = (
            (
                await session.execute(
                    sa.select(FlowStepAttempts).where(
                        FlowStepAttempts.flow_run_id == run.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(attempt_rows) == 1
        assert attempt_rows[0].status == FlowStepAttemptStatus.COMPLETED.value
        assert attempt_rows[0].finished_at is not None

        evidence = (
            await container.flow_run_evidence_service().get_redacted_evidence_bundle(
                run_id=run.id
            )
        ).to_dict()
        assert evidence["run"]["status"] == FlowRunStatus.COMPLETED.value
        assert evidence["step_results"][0]["output_payload_json"] == {
            "text": "The run completed.",
            "webhook_delivered": False,
        }

        audit_service.log_async.assert_not_awaited()
        outbox_row = await session.scalar(
            sa.select(FlowRunAuditOutbox).where(
                FlowRunAuditOutbox.flow_run_id == run.id
            )
        )
        assert outbox_row is not None
        assert outbox_row.action == "flow_run_completed"
        assert outbox_row.source == "executor_completed"
        assert outbox_row.target_status == FlowRunStatus.COMPLETED.value
        assert outbox_row.entity_id == run.id
        assert outbox_row.description == "flow_run_completed:executor_completed"

        rerun_result = await container.flow_run_rerun_service().rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=step.id,
            expected_run_revision=1,
            reason="Regenerate the answer after review.",
        )
        assert rerun_result.created is True
        assert rerun_result.operation.root_attempt_no == 2
        assert rerun_result.invalidated_steps[0].prior_attempt_id == attempt_rows[0].id

        rerun_worker_result = await executor.execute(
            run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            celery_task_id=f"{run_correlation_id}-rerun",
            retry_count=0,
        )

        assert rerun_worker_result == {"status": "completed"}
        rerun_run_row = await session.scalar(
            sa.select(FlowRuns).where(FlowRuns.id == run.id)
        )
        assert rerun_run_row is not None
        assert rerun_run_row.status == FlowRunStatus.COMPLETED.value
        assert rerun_run_row.revision == 2
        assert rerun_run_row.output_payload_json == {
            "text": "The rerun completed.",
            "webhook_delivered": False,
        }

        rerun_step_result = await session.scalar(
            sa.select(FlowStepResults).where(FlowStepResults.flow_run_id == run.id)
        )
        assert rerun_step_result is not None
        assert rerun_step_result.status == FlowStepResultStatus.COMPLETED.value
        assert rerun_step_result.current_attempt_no == 2
        assert rerun_step_result.output_payload_json == {
            "text": "The rerun completed.",
            "webhook_delivered": False,
        }

        rerun_attempt_rows = (
            (
                await session.execute(
                    sa.select(FlowStepAttempts)
                    .where(FlowStepAttempts.flow_run_id == run.id)
                    .order_by(FlowStepAttempts.attempt_no.asc())
                )
            )
            .scalars()
            .all()
        )
        assert [attempt.attempt_no for attempt in rerun_attempt_rows] == [1, 2]
        assert [attempt.status for attempt in rerun_attempt_rows] == [
            FlowStepAttemptStatus.COMPLETED.value,
            FlowStepAttemptStatus.COMPLETED.value,
        ]
        assert (
            rerun_attempt_rows[0].superseded_by_attempt_id == rerun_attempt_rows[1].id
        )
        assert rerun_attempt_rows[1].predecessor_attempt_id == rerun_attempt_rows[0].id
        assert rerun_attempt_rows[1].rerun_operation_id == rerun_result.operation.id

        operation_row = await session.scalar(
            sa.select(FlowRunRerunOperations).where(
                FlowRunRerunOperations.id == rerun_result.operation.id
            )
        )
        assert operation_row is not None
        assert operation_row.status == FlowRunRerunOperationStatus.COMPLETED.value
        assert operation_row.root_attempt_id == rerun_attempt_rows[1].id
        assert operation_row.started_at is not None
        assert operation_row.finished_at is not None

        outbox_rows = (
            (
                await session.execute(
                    sa.select(FlowRunAuditOutbox)
                    .where(FlowRunAuditOutbox.flow_run_id == run.id)
                    .order_by(FlowRunAuditOutbox.run_revision.asc())
                )
            )
            .scalars()
            .all()
        )
        assert [row.run_revision for row in outbox_rows] == [1, 2]
        assert [row.target_status for row in outbox_rows] == [
            FlowRunStatus.COMPLETED.value,
            FlowRunStatus.COMPLETED.value,
        ]

        invalidated_row = await session.scalar(
            sa.select(FlowRunRerunInvalidatedSteps).where(
                FlowRunRerunInvalidatedSteps.operation_id == rerun_result.operation.id
            )
        )
        assert invalidated_row is not None
        assert invalidated_row.new_attempt_no == 2
        assert invalidated_row.new_attempt_id == rerun_attempt_rows[1].id

        rerun_evidence = (
            await container.flow_run_evidence_service().get_redacted_evidence_bundle(
                run_id=run.id
            )
        ).to_dict()
        assert len(rerun_evidence["step_attempts"]) == 2
        assert [
            attempt["attempt_no"] for attempt in rerun_evidence["step_attempts"]
        ] == [
            1,
            2,
        ]
        assert rerun_evidence["step_results"][0]["current_attempt_no"] == 2
        assert rerun_evidence["step_results"][0]["output_payload_json"] == {
            "text": "The rerun completed.",
            "webhook_delivered": False,
        }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_generic_step_failure_persists_failed_state_for_fresh_sessions(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    completion_service = SimpleNamespace(
        get_response=AsyncMock(side_effect=RuntimeError("provider failed"))
    )

    async with sessionmanager.session() as session:
        context = await _create_runtime_worker_context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            completion_service=completion_service,
        )
        result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            celery_task_id=f"runtime-generic-failure-{uuid4()}",
            retry_count=0,
        )

    assert result == {"status": "failed", "error": "step_execution_failed"}
    (
        run_row,
        step_result_row,
        attempt_rows,
        outbox_rows,
    ) = await _failure_state_from_fresh_session(
        run_id=context.run_id,
        tenant_id=context.tenant_id,
    )

    assert run_row is not None
    assert run_row.status == FlowRunStatus.FAILED.value
    assert (
        FlowRunError.model_validate(run_row.error_json).message
        == "Flow step 1 execution failed."
    )
    assert step_result_row is not None
    assert step_result_row.status == FlowStepResultStatus.FAILED.value
    assert step_result_row.error_message == "Flow step 1 execution failed."
    assert len(attempt_rows) == 1
    assert attempt_rows[0].status == FlowStepAttemptStatus.FAILED.value
    assert attempt_rows[0].error_code == "step_execution_failed"
    assert attempt_rows[0].finished_at is not None
    assert [row.target_status for row in outbox_rows] == [FlowRunStatus.FAILED.value]
    assert [row.source for row in outbox_rows] == [
        FlowRunLifecycleSource.EXECUTOR_FAILED.value
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_typed_step_failure_persists_failed_state_for_fresh_sessions(
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
    completion_service = SimpleNamespace(
        get_response=AsyncMock(
            return_value=SimpleNamespace(
                completion="not json",
                total_token_count=1,
            )
        )
    )

    async with sessionmanager.session() as session:
        context = await _create_runtime_worker_context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            completion_service=completion_service,
            output_type="json",
            output_contract=output_contract,
        )
        result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            celery_task_id=f"runtime-typed-failure-{uuid4()}",
            retry_count=0,
        )

    assert result["status"] == "failed"
    assert result["error"] == (
        "Step 1: typed input/output validation failed (typed_io_output_parse_failed)."
    )
    (
        run_row,
        step_result_row,
        attempt_rows,
        outbox_rows,
    ) = await _failure_state_from_fresh_session(
        run_id=context.run_id,
        tenant_id=context.tenant_id,
    )

    assert run_row is not None
    assert run_row.status == FlowRunStatus.FAILED.value
    assert FlowRunError.model_validate(run_row.error_json).message == (
        "Step 1: typed input/output validation failed (typed_io_output_parse_failed)."
    )
    assert step_result_row is not None
    assert step_result_row.status == FlowStepResultStatus.FAILED.value
    assert step_result_row.error_message is not None
    assert "not valid JSON" in step_result_row.error_message
    assert len(attempt_rows) == 1
    assert attempt_rows[0].status == FlowStepAttemptStatus.FAILED.value
    assert attempt_rows[0].error_code == "typed_io_output_parse_failed"
    assert attempt_rows[0].finished_at is not None
    assert [row.target_status for row in outbox_rows] == [FlowRunStatus.FAILED.value]
    assert [row.source for row in outbox_rows] == [
        FlowRunLifecycleSource.EXECUTOR_FAILED.value
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_attempt_start_failure_persists_failed_state_for_fresh_sessions(
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
                completion="This should not run.",
                total_token_count=1,
            )
        )
    )

    async with sessionmanager.session() as session:
        context = await _create_runtime_worker_context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            completion_service=completion_service,
        )
        context.executor.flow_run_repo.create_or_get_attempt_started = AsyncMock(
            side_effect=RuntimeError("attempt start failed")
        )
        result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            celery_task_id=f"runtime-attempt-start-failure-{uuid4()}",
            retry_count=0,
        )

    assert result == {"status": "failed", "error": "step_execution_failed"}
    (
        run_row,
        step_result_row,
        attempt_rows,
        outbox_rows,
    ) = await _failure_state_from_fresh_session(
        run_id=context.run_id,
        tenant_id=context.tenant_id,
    )

    assert run_row is not None
    assert run_row.status == FlowRunStatus.FAILED.value
    assert (
        FlowRunError.model_validate(run_row.error_json).message
        == "Flow step 1 execution failed."
    )
    assert step_result_row is not None
    assert step_result_row.status == FlowStepResultStatus.FAILED.value
    assert step_result_row.error_message == "Flow step 1 execution failed."
    assert attempt_rows == []
    assert [row.target_status for row in outbox_rows] == [FlowRunStatus.FAILED.value]
    assert [row.source for row in outbox_rows] == [
        FlowRunLifecycleSource.EXECUTOR_FAILED.value
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_webhook_delivery_success_uses_handler_intent_for_fresh_sessions(
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
                completion="Webhook payload text.",
                total_token_count=1,
            )
        )
    )

    async with sessionmanager.session() as session:
        context = await _create_runtime_worker_context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            completion_service=completion_service,
            output_mode="http_post",
        )
        context.executor._deliver_webhook = AsyncMock()
        result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            celery_task_id=f"runtime-webhook-success-{uuid4()}",
            retry_count=0,
        )

    assert result == {"status": "completed"}
    context.executor._deliver_webhook.assert_awaited_once()
    (
        run_row,
        step_result_row,
        attempt_rows,
        outbox_rows,
    ) = await _failure_state_from_fresh_session(
        run_id=context.run_id,
        tenant_id=context.tenant_id,
    )

    assert run_row is not None
    assert run_row.status == FlowRunStatus.COMPLETED.value
    assert step_result_row is not None
    assert step_result_row.status == FlowStepResultStatus.COMPLETED.value
    assert step_result_row.output_payload_json == {
        "text": "Webhook payload text.",
        "webhook_delivered": True,
    }
    assert len(attempt_rows) == 1
    assert attempt_rows[0].status == FlowStepAttemptStatus.COMPLETED.value
    assert [row.target_status for row in outbox_rows] == [FlowRunStatus.COMPLETED.value]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_webhook_delivery_failure_persists_failed_state_for_fresh_sessions(
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
                completion="Webhook payload text.",
                total_token_count=1,
            )
        )
    )

    async with sessionmanager.session() as session:
        context = await _create_runtime_worker_context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            completion_service=completion_service,
            output_mode="http_post",
        )
        context.executor._deliver_webhook = AsyncMock(
            side_effect=RuntimeError("webhook unavailable")
        )
        result = await context.executor.execute(
            run_id=context.run_id,
            flow_id=context.flow_id,
            tenant_id=context.tenant_id,
            celery_task_id=f"runtime-webhook-failure-{uuid4()}",
            retry_count=0,
        )

    assert result == {"status": "failed", "error": "webhook unavailable"}
    (
        run_row,
        step_result_row,
        attempt_rows,
        outbox_rows,
    ) = await _failure_state_from_fresh_session(
        run_id=context.run_id,
        tenant_id=context.tenant_id,
    )

    assert run_row is not None
    assert run_row.status == FlowRunStatus.FAILED.value
    assert (
        FlowRunError.model_validate(run_row.error_json).message
        == "Webhook delivery failed: webhook unavailable"
    )
    assert step_result_row is not None
    assert step_result_row.status == FlowStepResultStatus.COMPLETED.value
    assert step_result_row.output_payload_json["webhook_delivered"] is False
    assert step_result_row.output_payload_json["webhook_error"] == "webhook unavailable"
    assert len(attempt_rows) == 1
    assert attempt_rows[0].status == FlowStepAttemptStatus.COMPLETED.value
    assert attempt_rows[0].finished_at is not None
    assert [row.target_status for row in outbox_rows] == [FlowRunStatus.FAILED.value]
    assert [row.source for row in outbox_rows] == [
        FlowRunLifecycleSource.EXECUTOR_FAILED.value
    ]
