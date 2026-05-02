from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from intric.database.database import sessionmanager
from intric.database.tables.flow_tables import (
    FlowRunAuditOutbox,
    FlowRunReviewCheckpoints,
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
)
from intric.flows.enums import (
    FlowRunLifecycleSource,
    FlowRunReviewCheckpointState,
)
from intric.flows.flow_factory import FlowFactory
from intric.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy
from intric.flows.infrastructure.flow_repo import FlowRepository
from intric.flows.infrastructure.flow_version_repo import FlowVersionRepository
from intric.flows.published_definition import build_published_definition_json
from intric.flows.runtime.executor import FlowRunExecutor, FlowRunExecutorConfig
from intric.flows.runtime.tasks import enable_autobegin_for_flow_task_session
from intric.main.container.container import Container


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


def _build_review_pause_flow(
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
        steps=[
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
                output_type="text",
                output_contract=None,
                input_bindings={"question": "{{flow.input.question}}"},
                output_classification_override=None,
                mcp_policy="inherit",
                input_config=None,
                output_config=None,
                review_policy=FlowStepReviewPolicy(mode=FlowStepReviewMode.VIEW),
            ),
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
        ],
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
    return payload


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
    async with sessionmanager.session() as session:
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
            ),
            tenant_id=admin_user.tenant_id,
        )
        flow = flow.model_copy(update={"published_version": 1})
        flow = await flow_repo.update(flow=flow, tenant_id=admin_user.tenant_id)
        assert flow.id is not None
        first_step, second_step, third_step = flow.steps
        assert first_step.id is not None
        assert second_step.id is not None
        assert third_step.id is not None

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
                _definition_step(first_step, assistant_snapshot=assistant_snapshot),
                _definition_step(second_step, assistant_snapshot=assistant_snapshot),
                _definition_step(third_step, assistant_snapshot=assistant_snapshot),
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
        completion_service = SimpleNamespace(
            get_response=AsyncMock(
                return_value=SimpleNamespace(
                    completion="This answer needs review.",
                    total_token_count=17,
                )
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
            celery_task_id=f"review-pause-{uuid4()}",
            retry_count=0,
        )
        duplicate_result = await executor.execute(
            run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            celery_task_id=f"review-pause-duplicate-{uuid4()}",
            retry_count=1,
        )

        run_row = await session.scalar(sa.select(FlowRuns).where(FlowRuns.id == run.id))
        checkpoint_row = await session.scalar(
            sa.select(FlowRunReviewCheckpoints).where(
                FlowRunReviewCheckpoints.flow_run_id == run.id
            )
        )
        step_result_rows = (
            (
                await session.execute(
                    sa.select(FlowStepResults)
                    .where(FlowStepResults.flow_run_id == run.id)
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
                        FlowStepAttempts.flow_run_id == run.id
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
                        FlowRunAuditOutbox.flow_run_id == run.id
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
    assert run_row.revision == run.revision + 1
    assert run_row.output_payload_json is None

    assert checkpoint_row is not None
    assert checkpoint_row.state == FlowRunReviewCheckpointState.AWAITING_REVIEW.value
    assert checkpoint_row.step_id == first_step.id
    assert checkpoint_row.step_order == 1
    assert checkpoint_row.attempt_no == 1
    assert checkpoint_row.original_payload_json == {
        "text": "This answer needs review.",
        "webhook_delivered": False,
    }
    assert checkpoint_row.current_payload_json == checkpoint_row.original_payload_json
    assert checkpoint_row.next_step_ids_json == [
        str(second_step.id),
        str(third_step.id),
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
