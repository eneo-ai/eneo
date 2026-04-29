from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from intric.audit.domain.action_types import ActionType
from intric.database.database import sessionmanager
from intric.database.tables.flow_tables import (
    FlowRuns,
    FlowStepAttempts,
    FlowStepResults,
)
from intric.flows.assistant_execution_snapshot import stable_hash
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
from intric.flows.runtime.executor import FlowRunExecutor, FlowRunExecutorConfig
from intric.flows.runtime.tasks import _enable_autobegin_for_flow_task_session
from intric.main.container.container import Container


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
        _enable_autobegin_for_flow_task_session(session)
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
        step = flow.steps[0]
        run_correlation_id = f"runtime-worker-contract-{uuid4()}"

        definition_json = {
            "steps": [
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
                }
            ],
            "metadata_json": flow.metadata_json,
        }
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
            file_ids=None,
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
            "file_ids": [],
            "generated_file_ids": [],
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
            "file_ids": [],
            "generated_file_ids": [],
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
            "file_ids": [],
            "generated_file_ids": [],
            "webhook_delivered": False,
        }

        audit_service.log_async.assert_awaited_once()
        audit_kwargs = audit_service.log_async.await_args.kwargs
        assert audit_kwargs["action"] == ActionType.FLOW_RUN_COMPLETED
        assert audit_kwargs["entity_id"] == run.id
        assert isinstance(audit_kwargs["metadata"], dict)
        assert audit_kwargs["metadata"]["target"]["id"] == str(run.id)
        assert audit_kwargs["metadata"]["extra"] == {
            "status": FlowRunStatus.COMPLETED.value,
            "error_message": None,
        }
