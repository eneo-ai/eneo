from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from intric.database.tables.assistant_table import Assistants
from intric.database.tables.flow_tables import FlowRuns, FlowStepResults, FlowSteps, Flows
from intric.flows import (
    Flow,
    FlowFactory,
    FlowRepository,
    FlowStep,
    FlowStepResult,
    FlowStepResultStatus,
    FlowVersionRepository,
)
from intric.main.exceptions import NotFoundException


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
        name="Case Intake Flow",
        description="Flow for tenant-scoped repository tests.",
        created_by_user_id=user_id,
        owner_user_id=user_id,
        published_version=None,
        metadata_json={"form_schema": {"fields": [{"name": "question", "type": "string"}]}},
        data_retention_days=30,
        created_at=None,
        updated_at=None,
        steps=[
            FlowStep(
                id=None,
                flow_id=uuid4(),  # overwritten by repository insert payload
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                step_order=1,
                user_description="Initial summarization step",
                input_source="flow_input",
                input_type="text",
                input_contract=None,
                output_mode="pass_through",
                output_type="json",
                output_contract={"type": "object"},
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
async def test_flow_repository_create_get_and_tenant_scope(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows space", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow Assistant",
            model.id,
            space_id=space.id,
        )

        repo = FlowRepository(session=session, factory=FlowFactory())
        created = await repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )

        assert created.id is not None
        assert created.tenant_id == admin_user.tenant_id
        assert len(created.steps) == 1
        assert created.steps[0].flow_id == created.id
        assert created.steps[0].assistant_id == assistant.id

        fetched = await repo.get(created.id, admin_user.tenant_id)
        assert fetched.id == created.id
        assert fetched.steps[0].step_order == 1

        with pytest.raises(NotFoundException):
            await repo.get(created.id, uuid4())


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_repository_soft_delete_hides_row(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows soft-delete space", [model.id])
        assistant = await assistant_factory(
            session,
            "Soft Delete Assistant",
            model.id,
            space_id=space.id,
        )

        repo = FlowRepository(session=session, factory=FlowFactory())
        created = await repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )

        await repo.delete(created.id, admin_user.tenant_id)

        with pytest.raises(NotFoundException):
            await repo.get(created.id, admin_user.tenant_id)

        soft_deleted_row = await session.scalar(
            sa.select(Flows).where(Flows.id == created.id)
        )
        assert soft_deleted_row is not None
        assert soft_deleted_row.deleted_at is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_save_step_result_upserts_on_run_and_step(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows run space", [model.id])
        assistant = await assistant_factory(
            session,
            "Run Assistant",
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
        step_id = flow.steps[0].id
        assert step_id is not None

        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_checksum="checksum-v1",
            definition_json={"steps": [{"id": str(step_id), "step_order": 1}]},
            tenant_id=admin_user.tenant_id,
        )
        run_row = FlowRuns(
            flow_id=flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            status="queued",
            input_payload_json={"question": "What happened?"},
        )
        session.add(run_row)
        await session.flush()

        now = datetime.now(timezone.utc)
        first_result = FlowStepResult(
            id=uuid4(),
            flow_run_id=run_row.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=step_id,
            step_order=1,
            assistant_id=assistant.id,
            input_payload_json={"question": "What happened?"},
            effective_prompt="Summarize the incident.",
            output_payload_json={"summary": "First output"},
            model_parameters_json={"model_id": str(model.id), "temperature": 0.2},
            num_tokens_input=11,
            num_tokens_output=9,
            status=FlowStepResultStatus.PENDING,
            error_message=None,
            flow_step_execution_hash="hash-1",
            tool_calls_metadata=[],
            created_at=now,
            updated_at=now,
        )
        await flow_repo.save_step_result(
            flow_run_id=run_row.id,
            result=first_result,
            tenant_id=admin_user.tenant_id,
        )

        updated_result = FlowStepResult(
            id=uuid4(),
            flow_run_id=run_row.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=step_id,
            step_order=1,
            assistant_id=assistant.id,
            input_payload_json={"question": "What happened?"},
            effective_prompt="Summarize the incident and classify.",
            output_payload_json={"summary": "Updated output", "classification": "open"},
            model_parameters_json={"model_id": str(model.id), "temperature": 0.1},
            num_tokens_input=15,
            num_tokens_output=12,
            status=FlowStepResultStatus.COMPLETED,
            error_message=None,
            flow_step_execution_hash="hash-1",
            tool_calls_metadata=[{"tool_name": "none"}],
            created_at=now,
            updated_at=now,
        )
        await flow_repo.save_step_result(
            flow_run_id=run_row.id,
            result=updated_result,
            tenant_id=admin_user.tenant_id,
        )

        count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_row.id)
            .where(FlowStepResults.step_id == step_id)
        )
        assert count == 1

        saved = await flow_repo.get_step_result(
            flow_run_id=run_row.id,
            step_id=step_id,
            tenant_id=admin_user.tenant_id,
        )
        assert saved is not None
        assert saved.status == FlowStepResultStatus.COMPLETED
        assert saved.output_payload_json == {
            "summary": "Updated output",
            "classification": "open",
        }
        assert saved.model_parameters_json == {
            "model_id": str(model.id),
            "temperature": 0.1,
        }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_save_step_result_legacy_update_raises_when_row_missing(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Legacy flow space", [model.id])
        assistant = await assistant_factory(
            session,
            "Legacy Assistant",
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
        step_id = flow.steps[0].id
        assert step_id is not None
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_checksum="checksum-legacy",
            definition_json={"steps": [{"id": str(step_id), "step_order": 1}]},
            tenant_id=admin_user.tenant_id,
        )

        run_row = FlowRuns(
            flow_id=flow.id,
            flow_version=1,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            status="queued",
            input_payload_json={"question": "What happened?"},
        )
        session.add(run_row)
        await session.flush()

        now = datetime.now(timezone.utc)
        missing_row_update = FlowStepResult(
            id=uuid4(),
            flow_run_id=run_row.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=None,
            step_order=1,
            assistant_id=assistant.id,
            input_payload_json={"question": "What happened?"},
            effective_prompt="legacy",
            output_payload_json={"summary": "legacy output"},
            model_parameters_json={"temperature": 0.2},
            num_tokens_input=10,
            num_tokens_output=10,
            status=FlowStepResultStatus.COMPLETED,
            error_message=None,
            flow_step_execution_hash="hash-legacy",
            tool_calls_metadata=[],
            created_at=now,
            updated_at=now,
        )

        with pytest.raises(NotFoundException):
            await flow_repo.save_step_result(
                flow_run_id=run_row.id,
                result=missing_row_update,
                tenant_id=admin_user.tenant_id,
            )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_update_deletes_orphaned_flow_managed_assistant(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flow orphan cleanup", [model.id])
        assistant_one = await assistant_factory(
            session,
            "Flow Assistant One",
            model.id,
            space_id=space.id,
        )
        assistant_two = await assistant_factory(
            session,
            "Flow Assistant Two",
            model.id,
            space_id=space.id,
        )

        repo = FlowRepository(session=session, factory=FlowFactory())
        created = await repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant_one.id,
            ),
            tenant_id=admin_user.tenant_id,
        )

        await session.execute(
            sa.update(Assistants)
            .where(Assistants.id.in_([assistant_one.id, assistant_two.id]))
            .values(
                origin="flow_managed",
                managing_flow_id=created.id,
                hidden=True,
            )
        )

        updated = created.model_copy(
            update={
                "steps": [
                    created.steps[0].model_copy(
                        update={
                            "assistant_id": assistant_two.id,
                            "flow_id": created.id,
                            "tenant_id": admin_user.tenant_id,
                        }
                    )
                ]
            }
        )
        await repo.update(updated, tenant_id=admin_user.tenant_id)

        deleted_assistant = await session.scalar(
            sa.select(Assistants).where(Assistants.id == assistant_one.id)
        )
        remaining_assistant = await session.scalar(
            sa.select(Assistants).where(Assistants.id == assistant_two.id)
        )
        assert deleted_assistant is None
        assert remaining_assistant is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_repository_update_allows_transcribe_only_output_mode(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flow transcribe-only mode", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow Transcribe Assistant",
            model.id,
            space_id=space.id,
        )

        repo = FlowRepository(session=session, factory=FlowFactory())
        created = await repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )

        step = created.steps[0]
        updated = created.model_copy(
            update={
                "steps": [
                    step.model_copy(
                        update={
                            "flow_id": created.id,
                            "tenant_id": admin_user.tenant_id,
                            "input_type": "audio",
                            "output_type": "text",
                            "output_mode": "transcribe_only",
                        }
                    )
                ]
            }
        )

        persisted = await repo.update(updated, tenant_id=admin_user.tenant_id)
        assert persisted.steps[0].output_mode == "transcribe_only"
        assert persisted.steps[0].input_type == "audio"
        assert persisted.steps[0].output_type == "text"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_delete_cascades_owned_flow_managed_assistants(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flow delete cleanup", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow-owned Assistant",
            model.id,
            space_id=space.id,
        )

        repo = FlowRepository(session=session, factory=FlowFactory())
        created = await repo.create(
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
            .values(
                origin="flow_managed",
                managing_flow_id=created.id,
                hidden=True,
            )
        )
        await repo.delete(created.id, tenant_id=admin_user.tenant_id)

        step_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowSteps)
            .where(FlowSteps.flow_id == created.id)
        )
        assistant_row = await session.scalar(
            sa.select(Assistants).where(Assistants.id == assistant.id)
        )

        assert step_count == 0
        assert assistant_row is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_delete_keeps_shared_flow_managed_assistant_referenced_by_other_flow(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flow shared assistant guard", [model.id])
        shared_assistant = await assistant_factory(
            session,
            "Shared Flow-owned Assistant",
            model.id,
            space_id=space.id,
        )
        other_assistant = await assistant_factory(
            session,
            "Other Flow Assistant",
            model.id,
            space_id=space.id,
        )

        repo = FlowRepository(session=session, factory=FlowFactory())
        owner_flow = await repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=shared_assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        await session.execute(
            sa.update(Assistants)
            .where(Assistants.id == shared_assistant.id)
            .values(
                origin="flow_managed",
                managing_flow_id=owner_flow.id,
                hidden=True,
            )
        )

        referencing_flow = await repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=other_assistant.id,
            ).model_copy(
                update={
                    "name": "Referencing Flow",
                    "steps": [
                        FlowStep(
                            id=None,
                            flow_id=None,
                            tenant_id=admin_user.tenant_id,
                            assistant_id=shared_assistant.id,
                            step_order=1,
                            user_description="Reuses shared assistant",
                            input_source="flow_input",
                            input_type="text",
                            input_contract=None,
                            output_mode="pass_through",
                            output_type="json",
                            output_contract={"type": "object"},
                            input_bindings={"question": "{{flow.input.question}}"},
                            output_classification_override=None,
                            mcp_policy="inherit",
                            input_config=None,
                            output_config=None,
                        )
                    ],
                }
            ),
            tenant_id=admin_user.tenant_id,
        )

        await repo.delete(owner_flow.id, tenant_id=admin_user.tenant_id)

        shared_assistant_row = await session.scalar(
            sa.select(Assistants).where(Assistants.id == shared_assistant.id)
        )
        referencing_steps = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowSteps)
            .where(FlowSteps.flow_id == referencing_flow.id)
        )

        assert shared_assistant_row is not None
        assert shared_assistant_row.managing_flow_id == owner_flow.id
        assert referencing_steps == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_repository_rejects_duplicate_active_name_in_space(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows unique-name space", [model.id])
        assistant = await assistant_factory(
            session,
            "Unique Name Assistant",
            model.id,
            space_id=space.id,
        )

        repo = FlowRepository(session=session, factory=FlowFactory())
        base_flow = _build_flow(
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=admin_user.id,
            assistant_id=assistant.id,
        )
        await repo.create(flow=base_flow, tenant_id=admin_user.tenant_id)

        with pytest.raises(IntegrityError):
            await repo.create(flow=base_flow.model_copy(deep=True), tenant_id=admin_user.tenant_id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_repository_allows_name_reuse_after_soft_delete(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows name-reuse space", [model.id])
        assistant = await assistant_factory(
            session,
            "Name Reuse Assistant",
            model.id,
            space_id=space.id,
        )

        repo = FlowRepository(session=session, factory=FlowFactory())
        flow = await repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        await repo.delete(flow.id, admin_user.tenant_id)

        recreated = await repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        assert recreated.id != flow.id
