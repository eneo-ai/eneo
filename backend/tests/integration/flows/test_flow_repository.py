from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.assistant_table import (
    AssistantMCPServers,
    AssistantMCPServerTools,
    Assistants,
)
from eneo.database.tables.flow_tables import (
    FlowResourceBindings,
    FlowRuns,
    Flows,
    FlowSteps,
)
from eneo.database.tables.mcp_server_table import MCPServers, MCPServerTools
from eneo.flows import (
    FlowRepository,
    FlowVersionRepository,
)
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.enums import FlowOutputType, FlowRuntimeInputFormat
from eneo.flows.flow_resource_bindings import (
    FlowResourceBindingSource,
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from eneo.main.exceptions import NotFoundException


def _build_flow(
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    assistant_id: UUID,
    additional_assistant_ids: list[UUID] | None = None,
) -> Flow:
    assistant_ids = [assistant_id, *(additional_assistant_ids or [])]
    return Flow(
        id=None,
        tenant_id=tenant_id,
        space_id=space_id,
        name="Case Intake Flow",
        description="Flow for tenant-scoped repository tests.",
        created_by_user_id=user_id,
        owner_user_id=user_id,
        published_version=None,
        metadata_json={
            "form_schema": {"fields": [{"name": "question", "type": "string"}]}
        },
        data_retention_days=30,
        created_at=None,
        updated_at=None,
        steps=[
            _build_step(
                tenant_id=tenant_id,
                assistant_id=step_assistant_id,
                step_order=index + 1,
            )
            for index, step_assistant_id in enumerate(assistant_ids)
        ],
    )


def _build_step(
    *,
    tenant_id: UUID,
    assistant_id: UUID,
    step_order: int,
) -> FlowStep:
    return FlowStep(
        id=None,
        flow_id=uuid4(),  # overwritten by repository insert payload
        tenant_id=tenant_id,
        assistant_id=assistant_id,
        step_order=step_order,
        user_description=f"Repository step {step_order}",
        input_source="flow_input" if step_order == 1 else "previous_step",
        input_type="text",
        input_contract=None,
        output_mode="pass_through",
        output_type="json",
        output_contract={"type": "object"},
        input_bindings={"question": "{{flow.input.question}}"},
        output_classification_override=None,
        input_config=None,
        output_config=None,
    )


def _resource_binding(
    *,
    slot: str,
    local_id: UUID | None = None,
) -> LocalResourceBinding:
    return LocalResourceBinding(
        slot_ref=ResourceSlotRef(
            kind=ResourceSlotKind.MODEL,
            slot=slot,
            label=slot.replace("-", " ").title(),
        ),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=local_id or uuid4(),
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_repository_counts_distinct_mcp_assistants_once_in_one_query(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flow MCP presence", [model.id])
        clean_assistant = await assistant_factory(
            session,
            "Clean Flow Assistant",
            model.id,
            space_id=space.id,
        )
        server_assistant = await assistant_factory(
            session,
            "Server Flow Assistant",
            model.id,
            space_id=space.id,
        )
        tool_assistant = await assistant_factory(
            session,
            "Tool Flow Assistant",
            model.id,
            space_id=space.id,
        )
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name="Flow MCP presence server",
            http_url="https://example.test/mcp",
            http_auth_type="none",
            is_enabled=True,
        )
        session.add(server)
        await session.flush()
        tool = MCPServerTools(
            mcp_server_id=server.id,
            name="lookup",
            input_schema={},
            is_enabled_by_default=True,
            requires_approval=False,
            removed_from_remote=False,
        )
        session.add(tool)
        await session.flush()
        session.add_all(
            [
                AssistantMCPServers(
                    assistant_id=server_assistant.id,
                    mcp_server_id=server.id,
                ),
                AssistantMCPServerTools(
                    assistant_id=server_assistant.id,
                    mcp_server_tool_id=tool.id,
                    is_enabled=True,
                ),
                AssistantMCPServerTools(
                    assistant_id=tool_assistant.id,
                    mcp_server_tool_id=tool.id,
                    is_enabled=True,
                ),
            ]
        )
        await session.flush()

        repo = FlowRepository(session=session)
        flow = await repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=clean_assistant.id,
                additional_assistant_ids=[
                    server_assistant.id,
                    tool_assistant.id,
                    server_assistant.id,
                ],
            ),
            tenant_id=admin_user.tenant_id,
        )
        assert flow.id is not None

        captured_selects: list[tuple[str, tuple[object, ...]]] = []

        def count_selects(
            _conn,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            if statement.lower().lstrip().startswith("select"):
                assert isinstance(statement, str)
                assert isinstance(_parameters, tuple)
                captured_selects.append((statement, _parameters))

        sync_bind = session.sync_session.get_bind()
        sa.event.listen(sync_bind, "before_cursor_execute", count_selects)
        try:
            omitted_assistant_count = (
                await repo.count_flow_step_assistants_with_mcp_configuration(
                    flow_id=flow.id,
                    tenant_id=admin_user.tenant_id,
                )
            )
        finally:
            sa.event.remove(sync_bind, "before_cursor_execute", count_selects)

        assert omitted_assistant_count == 2
        assert len(captured_selects) == 1
        statement, parameters = captured_selects[0]
        connection = await session.connection()
        plan = (
            await connection.exec_driver_sql(
                f"EXPLAIN (FORMAT JSON, COSTS OFF) {statement}",
                parameters,
            )
        ).scalar_one()
        plan_text = json.dumps(plan)
        assert "Aggregate" in plan_text
        assert '"Relation Name": "flow_steps"' in plan_text
        assert '"Relation Name": "assistant_mcp_servers"' in plan_text
        assert '"Relation Name": "assistant_mcp_server_tools"' in plan_text
        assert (
            await repo.count_flow_step_assistants_with_mcp_configuration(
                flow_id=flow.id,
                tenant_id=uuid4(),
            )
            == 0
        )
        assert (
            await repo.count_flow_step_assistants_with_mcp_configuration(
                flow_id=uuid4(),
                tenant_id=admin_user.tenant_id,
            )
            == 0
        )


async def _resource_binding_rows(
    session: AsyncSession,
    *,
    flow_id: UUID,
) -> list[FlowResourceBindings]:
    result = await session.execute(
        sa.select(FlowResourceBindings)
        .where(FlowResourceBindings.flow_id == flow_id)
        .order_by(FlowResourceBindings.slot.asc())
    )
    return list(result.scalars().all())


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

        repo = FlowRepository(session=session)
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
async def test_flow_repository_replaces_resource_bindings(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows binding space", [model.id])
        assistant = await assistant_factory(
            session,
            "Binding Assistant",
            model.id,
            space_id=space.id,
        )

        repo = FlowRepository(session=session)
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

        await repo.replace_resource_bindings(
            flow_id=created.id,
            tenant_id=admin_user.tenant_id,
            bindings=(
                _resource_binding(slot="model-a"),
                _resource_binding(slot="model-b"),
            ),
            source=FlowResourceBindingSource.PACKAGE_IMPORT,
        )
        await repo.replace_resource_bindings(
            flow_id=created.id,
            tenant_id=admin_user.tenant_id,
            bindings=(_resource_binding(slot="model-c"),),
            source=FlowResourceBindingSource.PACKAGE_IMPORT,
        )

        rows = await _resource_binding_rows(session, flow_id=created.id)
        assert [row.slot for row in rows] == ["model-c"]
        assert rows[0].tenant_id == admin_user.tenant_id
        assert rows[0].space_id == space.id
        assert rows[0].source == FlowResourceBindingSource.PACKAGE_IMPORT.value
        assert rows[0].slot_label == "Model C"

        await repo.replace_resource_bindings(
            flow_id=created.id,
            tenant_id=admin_user.tenant_id,
            bindings=tuple(),
            source=FlowResourceBindingSource.PACKAGE_IMPORT,
        )

        assert await _resource_binding_rows(session, flow_id=created.id) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_repository_lists_resource_bindings_as_typed_values(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows binding read space", [model.id])
        assistant = await assistant_factory(
            session,
            "Binding Read Assistant",
            model.id,
            space_id=space.id,
        )

        repo = FlowRepository(session=session)
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
        first_id = uuid4()
        second_id = uuid4()
        await repo.replace_resource_bindings(
            flow_id=created.id,
            tenant_id=admin_user.tenant_id,
            bindings=(
                _resource_binding(slot="model-b", local_id=second_id),
                _resource_binding(slot="model-a", local_id=first_id),
            ),
            source=FlowResourceBindingSource.PACKAGE_IMPORT,
        )

        bindings = await repo.list_resource_bindings(
            flow_id=created.id,
            tenant_id=admin_user.tenant_id,
        )

        assert [binding.slot_ref.slot for binding in bindings] == ["model-a", "model-b"]
        assert [binding.slot_ref.label for binding in bindings] == [
            "Model A",
            "Model B",
        ]
        assert [binding.local_id for binding in bindings] == [first_id, second_id]
        with pytest.raises(NotFoundException):
            await repo.list_resource_bindings(
                flow_id=created.id,
                tenant_id=uuid4(),
            )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_repository_resource_binding_replacement_is_atomic_on_insert_failure(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Flows binding atomicity space", [model.id]
        )
        assistant = await assistant_factory(
            session,
            "Binding Atomicity Assistant",
            model.id,
            space_id=space.id,
        )

        repo = FlowRepository(session=session)
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

        original_local_id = uuid4()
        await repo.replace_resource_bindings(
            flow_id=created.id,
            tenant_id=admin_user.tenant_id,
            bindings=(
                _resource_binding(
                    slot="original-model",
                    local_id=original_local_id,
                ),
            ),
            source=FlowResourceBindingSource.PACKAGE_IMPORT,
        )

        nested = await session.begin_nested()
        try:
            await repo.replace_resource_bindings(
                flow_id=created.id,
                tenant_id=admin_user.tenant_id,
                bindings=(
                    _resource_binding(slot="duplicate-model"),
                    _resource_binding(slot="duplicate-model"),
                ),
                source=FlowResourceBindingSource.PACKAGE_IMPORT,
            )
        except IntegrityError:
            await nested.rollback()
        else:
            await nested.rollback()
            pytest.fail("Expected duplicate binding insert to fail.")

        rows = await _resource_binding_rows(session, flow_id=created.id)
        assert [(row.slot, row.local_resource_id) for row in rows] == [
            ("original-model", original_local_id)
        ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_repository_resource_binding_write_is_tenant_scoped(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows binding tenant space", [model.id])
        assistant = await assistant_factory(
            session,
            "Binding Tenant Assistant",
            model.id,
            space_id=space.id,
        )

        repo = FlowRepository(session=session)
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

        with pytest.raises(NotFoundException):
            await repo.replace_resource_bindings(
                flow_id=created.id,
                tenant_id=uuid4(),
                bindings=(_resource_binding(slot="model-a"),),
                source=FlowResourceBindingSource.PACKAGE_IMPORT,
            )

        assert await _resource_binding_rows(session, flow_id=created.id) == []


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

        repo = FlowRepository(session=session)
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

        repo = FlowRepository(session=session)
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
async def test_flow_repository_update_preserves_step_ids_during_adjacent_reorder(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flow reorder ids", [model.id])
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

        repo = FlowRepository(session=session)
        created = await repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant_one.id,
                additional_assistant_ids=[assistant_two.id],
            ),
            tenant_id=admin_user.tenant_id,
        )
        first_step, second_step = created.steps

        updated = created.model_copy(
            update={
                "steps": [
                    second_step.model_copy(
                        update={"step_order": 1, "input_source": "flow_input"},
                        deep=True,
                    ),
                    first_step.model_copy(
                        update={"step_order": 2, "input_source": "previous_step"},
                        deep=True,
                    ),
                ]
            },
            deep=True,
        )

        persisted = await repo.update(updated, tenant_id=admin_user.tenant_id)

        assert [step.id for step in persisted.steps] == [second_step.id, first_step.id]
        assert [step.assistant_id for step in persisted.steps] == [
            assistant_two.id,
            assistant_one.id,
        ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_repository_update_inserts_new_step_without_replacing_existing_ids(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flow insert ids", [model.id])
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
        assistant_three = await assistant_factory(
            session,
            "Flow Assistant Three",
            model.id,
            space_id=space.id,
        )

        repo = FlowRepository(session=session)
        created = await repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant_one.id,
                additional_assistant_ids=[assistant_two.id],
            ),
            tenant_id=admin_user.tenant_id,
        )
        first_step, second_step = created.steps
        new_step = _build_step(
            tenant_id=admin_user.tenant_id,
            assistant_id=assistant_three.id,
            step_order=1,
        )

        updated = created.model_copy(
            update={
                "steps": [
                    new_step,
                    first_step.model_copy(
                        update={"step_order": 2, "input_source": "previous_step"},
                        deep=True,
                    ),
                    second_step.model_copy(
                        update={"step_order": 3, "input_source": "previous_step"},
                        deep=True,
                    ),
                ]
            },
            deep=True,
        )

        persisted = await repo.update(updated, tenant_id=admin_user.tenant_id)

        assert persisted.steps[0].id not in {first_step.id, second_step.id}
        assert [step.id for step in persisted.steps[1:]] == [
            first_step.id,
            second_step.id,
        ]
        assert [step.assistant_id for step in persisted.steps] == [
            assistant_three.id,
            assistant_one.id,
            assistant_two.id,
        ]


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

        repo = FlowRepository(session=session)
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

        repo = FlowRepository(session=session)
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
async def test_flow_delete_preserves_steps_and_flow_managed_assistant_when_runs_exist(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Flow delete history preservation", [model.id]
        )
        assistant = await assistant_factory(
            session,
            "Flow-owned Assistant With Runs",
            model.id,
            space_id=space.id,
        )

        repo = FlowRepository(session=session)
        version_repo = FlowVersionRepository(session=session)
        created = await repo.create(
            flow=_build_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )

        step_id = created.steps[0].id
        assert step_id is not None

        await session.execute(
            sa.update(Assistants)
            .where(Assistants.id == assistant.id)
            .values(
                origin="flow_managed",
                managing_flow_id=created.id,
                hidden=True,
            )
        )
        await version_repo.create(
            flow_id=created.id,
            version=1,
            definition_json={"steps": [{"id": str(step_id), "step_order": 1}]},
            tenant_id=admin_user.tenant_id,
        )
        run_row = FlowRuns(
            flow_id=created.id,
            flow_version=1,
            principal_type="user",
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            status="completed",
            input_payload_json={"question": "What happened?"},
            output_payload_json={"summary": "done"},
        )
        session.add(run_row)
        await session.flush()

        await repo.delete(created.id, tenant_id=admin_user.tenant_id)

        step_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowSteps)
            .where(FlowSteps.flow_id == created.id)
        )
        assistant_row = await session.scalar(
            sa.select(Assistants).where(Assistants.id == assistant.id)
        )

        assert step_count == 1
        assert assistant_row is not None


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

        repo = FlowRepository(session=session)
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

        repo = FlowRepository(session=session)
        base_flow = _build_flow(
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=admin_user.id,
            assistant_id=assistant.id,
        )
        await repo.create(flow=base_flow, tenant_id=admin_user.tenant_id)

        with pytest.raises(IntegrityError):
            await repo.create(
                flow=base_flow.model_copy(deep=True), tenant_id=admin_user.tenant_id
            )


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

        repo = FlowRepository(session=session)
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


def _build_step_with(
    *,
    tenant_id: UUID,
    assistant_id: UUID,
    step_order: int,
    output_type: str,
    input_config: dict[str, object] | None,
    input_type: str = "text",
) -> FlowStep:
    return FlowStep(
        id=None,
        flow_id=uuid4(),  # overwritten by repository insert payload
        tenant_id=tenant_id,
        assistant_id=assistant_id,
        step_order=step_order,
        user_description=f"Sparse list step {step_order}",
        input_source="flow_input" if step_order == 1 else "previous_step",
        input_type=input_type,
        input_contract=None,
        output_mode="pass_through",
        output_type=output_type,
        output_contract=None,
        input_bindings=None,
        output_classification_override=None,
        input_config=input_config,
        output_config=None,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_repository_sparse_list_derives_step_projection_in_one_batched_query(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    """`get_sparse_by_space` must derive step_count/input_type/output_type for
    every row from one batched steps query, not one query per flow, and each
    row's values must match its own `FlowSteps` configuration. (This test
    proves the repository's batching and per-flow wiring on real Postgres.
    That the input-format derivation itself matches the run contract's is
    proven independently in test_flow_run_step_inputs.py; the output-type
    derivation has no second aggregate consumer to cross-check against, so
    test_flow_run_contract_service.py instead proves there is exactly one
    implementation to import.)
    """
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flow sparse list projection", [model.id])
        assistant = await assistant_factory(
            session,
            "Sparse list assistant",
            model.id,
            space_id=space.id,
        )

        repo = FlowRepository(session=session)
        audio_to_pdf_flow = await repo.create(
            flow=Flow(
                id=None,
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                name="Audio to PDF",
                created_by_user_id=admin_user.id,
                owner_user_id=admin_user.id,
                published_version=None,
                steps=[
                    _build_step_with(
                        tenant_id=admin_user.tenant_id,
                        assistant_id=assistant.id,
                        step_order=1,
                        output_type="text",
                        input_config={
                            "runtime_input": {
                                "enabled": True,
                                "input_format": "audio",
                            }
                        },
                    ),
                    _build_step_with(
                        tenant_id=admin_user.tenant_id,
                        assistant_id=assistant.id,
                        step_order=2,
                        output_type="pdf",
                        # No `runtime_input` key, but carries an authored
                        # HTTP config shape (see http_transport/
                        # authored_config.py) with a secret-shaped value, to
                        # prove the sparse list query never has to fetch this
                        # column's full contents to resolve input_type=None.
                        input_config={
                            "url": "https://example.test/lookup",
                            "auth": {
                                "mode": "bearer_token",
                                "token": "s3cret-bearer-token-value",
                            },
                        },
                        input_type="json",
                    ),
                ],
            ),
            tenant_id=admin_user.tenant_id,
        )
        single_json_step_flow = await repo.create(
            flow=Flow(
                id=None,
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                name="Single JSON step",
                created_by_user_id=admin_user.id,
                owner_user_id=admin_user.id,
                published_version=None,
                steps=[
                    _build_step_with(
                        tenant_id=admin_user.tenant_id,
                        assistant_id=assistant.id,
                        step_order=1,
                        output_type="json",
                        input_config=None,
                    ),
                ],
            ),
            tenant_id=admin_user.tenant_id,
        )

        captured_selects: list[str] = []

        def count_selects(
            _conn,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            if statement.lower().lstrip().startswith("select"):
                captured_selects.append(statement)

        sync_bind = session.sync_session.get_bind()
        sa.event.listen(sync_bind, "before_cursor_execute", count_selects)
        try:
            rows = await repo.get_sparse_by_space(
                space_id=space.id,
                tenant_id=admin_user.tenant_id,
            )
        finally:
            sa.event.remove(sync_bind, "before_cursor_execute", count_selects)

        # One query for flows + the retention envelope, one batched query for
        # every flow's steps together — independent of how many flows the
        # space holds, so this stays flat as the list page grows.
        assert len(captured_selects) == 2
        steps_statement = captured_selects[1]
        # The steps query must extract only the `runtime_input` JSON
        # subfield (compiled by asyncpg as `input_config[$n::TEXT]`, not a
        # bare column reference), so authored HTTP step secrets (auth
        # tokens, custom headers) never round-trip through the sparse list
        # path.
        assert "flow_steps.input_config[" in steps_statement
        assert "flow_steps.input_config," not in steps_statement
        assert "flow_steps.input_config \n" not in steps_statement

        by_id = {row.id: row for row in rows}
        assert by_id[audio_to_pdf_flow.id].step_count == 2
        assert by_id[audio_to_pdf_flow.id].input_type == FlowRuntimeInputFormat.AUDIO
        assert by_id[audio_to_pdf_flow.id].output_type == FlowOutputType.PDF
        assert by_id[single_json_step_flow.id].step_count == 1
        assert by_id[single_json_step_flow.id].input_type is None
        assert by_id[single_json_step_flow.id].output_type == FlowOutputType.JSON

        # All three repository read paths must agree on the same flow's
        # projection, since only `get_sparse_by_space`'s steps query changed
        # shape — `get` and `get_by_space` already loaded full step rows.
        full_flow = await repo.get(audio_to_pdf_flow.id, admin_user.tenant_id)
        assert full_flow.step_count == 2
        assert full_flow.input_type == FlowRuntimeInputFormat.AUDIO
        assert full_flow.output_type == FlowOutputType.PDF

        paged_flows = await repo.get_by_space(space.id, admin_user.tenant_id)
        paged_by_id = {flow.id: flow for flow in paged_flows}
        assert paged_by_id[audio_to_pdf_flow.id].step_count == 2
        assert (
            paged_by_id[audio_to_pdf_flow.id].input_type == FlowRuntimeInputFormat.AUDIO
        )
        assert paged_by_id[audio_to_pdf_flow.id].output_type == FlowOutputType.PDF
        assert paged_by_id[single_json_step_flow.id].step_count == 1
        assert paged_by_id[single_json_step_flow.id].input_type is None
        assert paged_by_id[single_json_step_flow.id].output_type == FlowOutputType.JSON
