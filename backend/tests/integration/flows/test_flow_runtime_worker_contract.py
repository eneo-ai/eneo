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
from intric.flows.flow_factory import FlowFactory
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
                output_mode="pass_through",
                output_type="text",
                output_contract=None,
                input_bindings={"question": "{{flow.input.question}}"},
                output_classification_override=None,
                mcp_policy="inherit",
                input_config=None,
                output_config=None,
            )
        ],
    )


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
                return_value=SimpleNamespace(
                    completion="The run completed.",
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

        evidence = await container.flow_run_service().get_evidence(run_id=run.id)
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
