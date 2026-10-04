"""A run of a version keeps executing, and keeps its step assistant, when the
author unpublishes and removes that step while the run is in flight.

At base the removal deleted the flow-managed assistant. The run's step result
row (pre-seeded with the assistant id, `ON DELETE SET NULL`) then took the
step's completion write, which carries the snapshot's assistant id again, and
PostgreSQL refused it with `flow_step_results_assistant_id_fkey`: the step, and
with it the run, failed at its first write instead of completing. The executor
itself tolerates the missing live assistant (it rebuilds from the snapshot, which
this test stands in for), so the foreign key on the result is what the
retained assistant protects.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from eneo.database.database import sessionmanager
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.flow_tables import FlowRuns, FlowStepResults
from eneo.flows.assistant_execution_snapshot import build_assistant_execution_snapshot
from eneo.flows.domain.flow import FlowRunStatus
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.published_definition import build_published_definition_json
from eneo.flows.runtime.executor import FlowRunExecutor, FlowRunExecutorConfig
from eneo.flows.runtime.flow_run_actor import FlowRunActor
from eneo.flows.runtime.tasks import enable_autobegin_for_flow_task_session
from eneo.main.container.container import Container
from tests.integration.flows.test_flow_runtime_worker_contract import (
    _build_flow,  # pyright: ignore[reportPrivateUsage]
    _RuntimeAssistant,  # pyright: ignore[reportPrivateUsage]
)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.usefixtures("object_content_runtime_ready")
async def test_a_run_in_flight_when_its_step_is_removed_completes_with_the_assistant(
    setup_database,
    db_container,
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
        space = await space_factory(session, "Step removal run space", [model.id])
        assistant = await assistant_factory(
            session, "Removed step assistant", model.id, space_id=space.id
        )
        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        await session.execute(
            sa.update(Assistants)
            .where(Assistants.id == assistant.id)
            .values(origin="flow_managed", managing_flow_id=flow.id, hidden=True)
        )
        runtime_assistant = _RuntimeAssistant(
            assistant_id=assistant.id,
            model_id=model.id,
            provider_id=model.provider_id,
            model_name="gpt-4o-mini",
        )
        snapshot = build_assistant_execution_snapshot(assistant=runtime_assistant)
        step = flow.steps[0]
        await FlowVersionRepository(session=session).create(
            flow_id=flow.id,
            version=1,
            definition_json=build_published_definition_json(
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
                        "assistant_snapshot": snapshot,
                    }
                ],
            ),
            tenant_id=admin_user.tenant_id,
        )
        flow = await flow_repo.update(
            flow=flow.model_copy(update={"published_version": 1}),
            tenant_id=admin_user.tenant_id,
        )
        created = await container.flow_run_service().create_run(
            flow_id=flow.id,
            input_payload_json={"question": "What happened?"},
            expected_flow_version=1,
            step_inputs=None,
            idempotency_key=f"step-removal-{uuid4()}",
        )
        run = created.run
        flow_id, space_id, run_id, run_revision = (
            flow.id,
            space.id,
            run.id,
            run.revision,
        )
        assistant_id = assistant.id
        await session.commit()

    # The author unpublishes and removes the step while the run is queued.
    async with db_container() as authoring:
        await authoring.flow_service().unpublish_flow(flow_id=flow_id)
        await authoring.flow_service().update_flow(flow_id=flow_id, steps=[])

    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
            tenant=providers.Object(test_tenant),
        )
        completion_service = SimpleNamespace(
            get_response=AsyncMock(
                return_value=SimpleNamespace(
                    completion="The run completed.", total_token_count=17
                )
            )
        )
        executor = FlowRunExecutor(
            runtime_actor=FlowRunActor.from_user(user=admin_user),
            session=session,
            flow_repo=container.flow_repo(),
            flow_run_repo=container.flow_run_repo(),
            flow_run_review_checkpoint_repo=container.flow_run_review_checkpoint_repo(),
            flow_run_terminalizer=container.flow_run_terminalizer(),
            flow_version_repo=container.flow_version_repo(),
            space_repo=container.space_repo(),
            completion_service=completion_service,
            file_repo=container.file_repo(),
            file_content_loader=container.file_content_loader(),
            file_service=container.file_service(user=admin_user),
            template_asset_repo=container.flow_template_asset_repo(),
            encryption_service=container.encryption_service(),
            audit_service=SimpleNamespace(log_async=AsyncMock(return_value=uuid4())),
            references_service=container.references_service(),
            transcriber=container.transcriber(),
            config=FlowRunExecutorConfig(
                max_inline_text_bytes=1024 * 1024,
                http_request_timeout_seconds=2.0,
                http_max_timeout_seconds=2.0,
                http_allow_private_networks=False,
            ),
        )
        executor._load_assistant = AsyncMock(  # pyright: ignore[reportPrivateUsage]
            side_effect=_loader(executor, space_id, runtime_assistant)
        )

        result = await executor.execute(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=admin_user.tenant_id,
            run_revision=run_revision,
            dispatch_task_id=f"step-removal-{uuid4()}",
            retry_count=0,
        )

        run_row = await session.scalar(sa.select(FlowRuns).where(FlowRuns.id == run_id))
        step_row = await session.scalar(
            sa.select(FlowStepResults).where(FlowStepResults.flow_run_id == run_id)
        )
        assistant_row = await session.scalar(
            sa.select(Assistants.id).where(Assistants.id == assistant_id)
        )

    assert result == {"status": "completed"}
    assert run_row is not None
    assert run_row.status == FlowRunStatus.COMPLETED.value
    assert step_row is not None
    assert step_row.assistant_id == assistant_id
    assert assistant_row == assistant_id


def _loader(executor, space_id, runtime_assistant):
    async def load(assistant_id, state, *, snapshot=None):
        if state.flow_space is None:
            state.flow_space = await executor.space_repo.get_execution_space(space_id)
        return runtime_assistant

    return load
