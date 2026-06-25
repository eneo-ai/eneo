from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from intric.assistants.assistant_update import AssistantUpdateCommand
from intric.flows.application.flow_draft_materialization import (
    FlowDraftAssistantToCreate,
    FlowDraftAssistantToDelete,
    FlowDraftAssistantToUpdate,
    FlowDraftChangeSet,
    FlowDraftCompiledStep,
    FlowDraftMaterializationProgress,
    FlowDraftMaterializationStage,
    FlowDraftStepChangeKind,
)
from intric.flows.application.flow_draft_materialization_executor import (
    FlowDraftMaterializer,
)
from intric.flows.domain.flow import Flow
from intric.flows.flow_authoring_spec import AssistantSpec
from intric.flows.flow_resource_bindings import (
    FlowResourceBindingSource,
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from intric.main.exceptions import BadRequestException


def _flow(
    *,
    flow_id: UUID | None = None,
    space_id: UUID | None = None,
    name: str = "Flow",
) -> Flow:
    return Flow(
        id=flow_id or uuid4(),
        tenant_id=uuid4(),
        space_id=space_id or uuid4(),
        name=name,
        description=None,
        steps=[],
    )


def _compiled_step(
    *,
    plan_step_ref: str = "step_a",
    step_order: int = 1,
    change_kind: FlowDraftStepChangeKind = FlowDraftStepChangeKind.ADDED,
    assistant_id: UUID | None = None,
    output_mode: str = "pass_through",
) -> FlowDraftCompiledStep:
    return FlowDraftCompiledStep(
        plan_step_ref=plan_step_ref,
        step_order=step_order,
        change_kind=change_kind,
        user_description="Test step",
        assistant_id=assistant_id,
        input_source="flow_input",
        input_type="text",
        output_mode=output_mode,
        output_type="text",
        mcp_policy="inherit",
    )


def _resource_binding(
    *,
    slot: str = "default-model",
    slot_kind: ResourceSlotKind = ResourceSlotKind.MODEL,
    local_kind: LocalResourceKind = LocalResourceKind.COMPLETION_MODEL,
    local_id: UUID | None = None,
) -> LocalResourceBinding:
    return LocalResourceBinding(
        slot_ref=ResourceSlotRef(kind=slot_kind, slot=slot, label=slot),
        local_kind=local_kind,
        local_id=local_id or uuid4(),
    )


def _flow_service() -> AsyncMock:
    service = AsyncMock()
    service.list_flows.return_value = []
    return service


def test_shared_executor_has_no_ai_builder_imports() -> None:
    import intric.flows.application.flow_draft_materialization_executor as executor

    assert "ai_builder" not in inspect.getsource(executor)
    assert "flow_packages" not in inspect.getsource(executor)


@pytest.mark.asyncio
async def test_create_mode_materializes_flow_and_resource_bindings() -> None:
    flow_id = uuid4()
    space_id = uuid4()
    assistant_id = uuid4()
    binding = _resource_binding()
    service = _flow_service()
    service.create_flow.return_value = _flow(flow_id=flow_id, space_id=space_id)
    assistant = MagicMock()
    assistant.id = assistant_id
    service.create_flow_assistant.return_value = (assistant, [])

    result = await FlowDraftMaterializer().execute(
        changeset=FlowDraftChangeSet(
            flow_name="Created flow",
            flow_description="Description",
            assistants_to_create=[
                FlowDraftAssistantToCreate(
                    plan_step_ref="step_a",
                    assistant_spec=AssistantSpec(instructions="Do it."),
                )
            ],
            compiled_steps=[_compiled_step()],
        ),
        flow_service=service,
        space_id=space_id,
        flow_id=None,
        resource_bindings=(binding,),
        binding_source=FlowResourceBindingSource.PACKAGE_IMPORT,
    )

    service.create_flow.assert_awaited_once_with(
        space_id=space_id,
        name="Created flow",
        description="Description",
        steps=[],
        metadata_json=None,
    )
    service.update_flow.assert_awaited_once()
    update_kwargs = service.update_flow.await_args.kwargs
    assert update_kwargs["flow_id"] == flow_id
    assert update_kwargs["steps"][0].assistant_id == assistant_id
    service.replace_resource_bindings.assert_awaited_once_with(
        flow_id=flow_id,
        bindings=(binding,),
        source=FlowResourceBindingSource.PACKAGE_IMPORT,
    )
    assert result.flow_id == flow_id
    assert result.flow_name == "Created flow"
    assert result.steps_created == 1


@pytest.mark.asyncio
async def test_create_mode_propagates_update_failure_without_cleanup() -> None:
    flow_id = uuid4()
    service = _flow_service()
    service.create_flow.return_value = _flow(flow_id=flow_id)
    assistant = MagicMock()
    assistant.id = uuid4()
    service.create_flow_assistant.return_value = (assistant, [])
    service.update_flow.side_effect = RuntimeError("update failed")

    with pytest.raises(RuntimeError, match="update failed"):
        await FlowDraftMaterializer().execute(
            changeset=FlowDraftChangeSet(
                flow_name="Created flow",
                flow_description="Description",
                assistants_to_create=[
                    FlowDraftAssistantToCreate(
                        plan_step_ref="step_a",
                        assistant_spec=AssistantSpec(instructions="Do it."),
                    )
                ],
                compiled_steps=[_compiled_step()],
            ),
            flow_service=service,
            space_id=uuid4(),
            flow_id=None,
            binding_source=FlowResourceBindingSource.AI_BUILDER,
        )

    service.delete_flow.assert_not_awaited()


@pytest.mark.asyncio
async def test_edit_mode_updates_assistants_before_flow_and_deletes_after_flow() -> (
    None
):
    flow_id = uuid4()
    existing_assistant_id = uuid4()
    deleted_assistant_id = uuid4()
    service = _flow_service()

    result = await FlowDraftMaterializer().execute(
        changeset=FlowDraftChangeSet(
            flow_name="Updated flow",
            flow_description="Description",
            assistants_to_update=[
                FlowDraftAssistantToUpdate(
                    existing_step_id=uuid4(),
                    existing_assistant_id=existing_assistant_id,
                    assistant_spec=AssistantSpec(instructions="Updated prompt"),
                )
            ],
            assistants_to_delete=[
                FlowDraftAssistantToDelete(
                    step_id=uuid4(),
                    assistant_id=deleted_assistant_id,
                )
            ],
            compiled_steps=[
                _compiled_step(
                    change_kind=FlowDraftStepChangeKind.MODIFIED,
                    assistant_id=existing_assistant_id,
                )
            ],
        ),
        flow_service=service,
        space_id=uuid4(),
        flow_id=flow_id,
        expected_revision=7,
        binding_source=FlowResourceBindingSource.AI_BUILDER,
    )

    service.update_flow_assistant.assert_awaited_once()
    service.update_flow.assert_awaited_once()
    service.delete_flow_assistant.assert_awaited_once_with(
        flow_id=flow_id,
        assistant_id=deleted_assistant_id,
    )
    call_names = [call[0] for call in service.mock_calls]
    assert call_names.index("update_flow_assistant") < call_names.index("update_flow")
    assert call_names.index("update_flow") < call_names.index("delete_flow_assistant")
    assert result.steps_updated == 1
    assert result.steps_removed == 1


@pytest.mark.asyncio
async def test_slot_refs_configure_model_knowledge_and_mcp() -> None:
    flow_id = uuid4()
    model_id = uuid4()
    collection_id = uuid4()
    server_id = uuid4()
    tool_id = uuid4()
    service = _flow_service()
    service.create_flow.return_value = _flow(flow_id=flow_id)
    assistant = MagicMock()
    assistant.id = uuid4()
    service.create_flow_assistant.return_value = (assistant, [])

    await FlowDraftMaterializer().execute(
        changeset=FlowDraftChangeSet(
            flow_name="MCP flow",
            flow_description="",
            assistants_to_create=[
                FlowDraftAssistantToCreate(
                    plan_step_ref="kb",
                    assistant_spec=AssistantSpec(
                        instructions="Use knowledge.",
                        model_ref="model.default-model",
                        knowledge_refs=["knowledge.policy"],
                    ),
                ),
                FlowDraftAssistantToCreate(
                    plan_step_ref="mcp",
                    assistant_spec=AssistantSpec(
                        instructions="Use tools.",
                        mcp_server_refs=["mcp_server.case-registry"],
                        mcp_tool_refs=["mcp_tool.case-lookup"],
                    ),
                ),
            ],
            compiled_steps=[
                _compiled_step(plan_step_ref="kb", step_order=1),
                _compiled_step(plan_step_ref="mcp", step_order=2),
            ],
        ),
        flow_service=service,
        space_id=uuid4(),
        flow_id=None,
        resource_bindings=(
            _resource_binding(
                slot="default-model",
                slot_kind=ResourceSlotKind.MODEL,
                local_kind=LocalResourceKind.COMPLETION_MODEL,
                local_id=model_id,
            ),
            _resource_binding(
                slot="policy",
                slot_kind=ResourceSlotKind.KNOWLEDGE,
                local_kind=LocalResourceKind.COLLECTION,
                local_id=collection_id,
            ),
            _resource_binding(
                slot="case-registry",
                slot_kind=ResourceSlotKind.MCP_SERVER,
                local_kind=LocalResourceKind.MCP_SERVER,
                local_id=server_id,
            ),
            _resource_binding(
                slot="case-lookup",
                slot_kind=ResourceSlotKind.MCP_TOOL,
                local_kind=LocalResourceKind.MCP_TOOL,
                local_id=tool_id,
            ),
        ),
        binding_source=FlowResourceBindingSource.AI_BUILDER,
    )

    first_update, second_update = service.update_flow_assistant.await_args_list
    first_command = first_update.kwargs["update"]
    second_command = second_update.kwargs["update"]
    assert isinstance(first_command, AssistantUpdateCommand)
    assert isinstance(second_command, AssistantUpdateCommand)
    assert first_command.completion_model_id == model_id
    assert first_command.groups == [collection_id]
    assert first_command.mcp_server_ids == []
    assert first_command.mcp_tools == []
    assert first_command.websites == []
    assert first_command.integration_knowledge_ids == []
    assert first_command.prompt is not None
    assert first_command.prompt.text == "Use knowledge."
    assert second_command.mcp_server_ids == [server_id]
    assert second_command.mcp_tools == [(tool_id, True)]
    assert second_command.groups == []
    assert second_command.websites == []
    assert second_command.integration_knowledge_ids == []


@pytest.mark.asyncio
async def test_knowledge_bindings_are_materialized_by_local_kind() -> None:
    flow_id = uuid4()
    collection_id = uuid4()
    website_id = uuid4()
    integration_knowledge_id = uuid4()
    service = _flow_service()
    service.create_flow.return_value = _flow(flow_id=flow_id)
    assistant = MagicMock()
    assistant.id = uuid4()
    service.create_flow_assistant.return_value = (assistant, [])

    await FlowDraftMaterializer().execute(
        changeset=FlowDraftChangeSet(
            flow_name="Knowledge flow",
            flow_description="",
            assistants_to_create=[
                FlowDraftAssistantToCreate(
                    plan_step_ref="knowledge",
                    assistant_spec=AssistantSpec(
                        instructions="Use local knowledge.",
                        knowledge_refs=[
                            "knowledge.policy",
                            "knowledge.website",
                            "knowledge.integration",
                        ],
                    ),
                )
            ],
            compiled_steps=[_compiled_step(plan_step_ref="knowledge", step_order=1)],
        ),
        flow_service=service,
        space_id=uuid4(),
        flow_id=None,
        resource_bindings=(
            _resource_binding(
                slot="policy",
                slot_kind=ResourceSlotKind.KNOWLEDGE,
                local_kind=LocalResourceKind.COLLECTION,
                local_id=collection_id,
            ),
            _resource_binding(
                slot="website",
                slot_kind=ResourceSlotKind.KNOWLEDGE,
                local_kind=LocalResourceKind.WEBSITE,
                local_id=website_id,
            ),
            _resource_binding(
                slot="integration",
                slot_kind=ResourceSlotKind.KNOWLEDGE,
                local_kind=LocalResourceKind.INTEGRATION_KNOWLEDGE,
                local_id=integration_knowledge_id,
            ),
        ),
        binding_source=FlowResourceBindingSource.PACKAGE_IMPORT,
    )

    command = service.update_flow_assistant.await_args.kwargs["update"]
    assert isinstance(command, AssistantUpdateCommand)
    assert command.groups == [collection_id]
    assert command.websites == [website_id]
    assert command.integration_knowledge_ids == [integration_knowledge_id]


@pytest.mark.asyncio
async def test_step_without_knowledge_or_mcp_clears_resource_lists() -> None:
    flow_id = uuid4()
    service = _flow_service()
    service.create_flow.return_value = _flow(flow_id=flow_id)
    assistant = MagicMock()
    assistant.id = uuid4()
    service.create_flow_assistant.return_value = (assistant, [])

    await FlowDraftMaterializer().execute(
        changeset=FlowDraftChangeSet(
            flow_name="Plain flow",
            flow_description="",
            assistants_to_create=[
                FlowDraftAssistantToCreate(
                    plan_step_ref="plain",
                    assistant_spec=AssistantSpec(instructions=""),
                ),
            ],
            compiled_steps=[_compiled_step(plan_step_ref="plain", step_order=1)],
        ),
        flow_service=service,
        space_id=uuid4(),
        flow_id=None,
        binding_source=FlowResourceBindingSource.AI_BUILDER,
    )

    command = service.update_flow_assistant.await_args.kwargs["update"]
    assert isinstance(command, AssistantUpdateCommand)
    assert command.groups == []
    assert command.websites == []
    assert command.integration_knowledge_ids == []
    assert command.mcp_server_ids == []
    assert command.mcp_tools == []
    assert command.prompt is not None
    assert command.prompt.text == ""


@pytest.mark.asyncio
async def test_materializer_clears_completion_model_for_transcribe_only_create_changeset() -> (
    None
):
    flow_id = uuid4()
    service = _flow_service()
    service.create_flow.return_value = _flow(flow_id=flow_id)
    assistant = MagicMock()
    assistant.id = uuid4()
    service.create_flow_assistant.return_value = (assistant, [])

    await FlowDraftMaterializer().execute(
        changeset=FlowDraftChangeSet(
            flow_name="Transcription flow",
            flow_description="",
            assistants_to_create=[
                FlowDraftAssistantToCreate(
                    plan_step_ref="transcribe",
                    assistant_spec=AssistantSpec(
                        instructions="Transcribe.",
                        model_ref="model.default",
                    ),
                )
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref="transcribe",
                    output_mode="transcribe_only",
                )
            ],
        ),
        flow_service=service,
        space_id=uuid4(),
        flow_id=None,
        binding_source=FlowResourceBindingSource.AI_BUILDER,
    )

    command = service.update_flow_assistant.await_args.kwargs["update"]
    assert isinstance(command, AssistantUpdateCommand)
    assert command.completion_model_id is None
    assert "completion_model_id" in command.model_fields_set


@pytest.mark.asyncio
async def test_materializer_clears_completion_model_for_transcribe_only_update_changeset() -> (
    None
):
    flow_id = uuid4()
    assistant_id = uuid4()
    service = _flow_service()

    await FlowDraftMaterializer().execute(
        changeset=FlowDraftChangeSet(
            flow_name="Transcription flow",
            flow_description="",
            assistants_to_update=[
                FlowDraftAssistantToUpdate(
                    existing_assistant_id=assistant_id,
                    assistant_spec=AssistantSpec(
                        instructions="Transcribe.",
                        model_ref="model.default",
                    ),
                )
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref="transcribe",
                    change_kind=FlowDraftStepChangeKind.MODIFIED,
                    assistant_id=assistant_id,
                    output_mode="transcribe_only",
                )
            ],
        ),
        flow_service=service,
        space_id=uuid4(),
        flow_id=flow_id,
        binding_source=FlowResourceBindingSource.AI_BUILDER,
    )

    command = service.update_flow_assistant.await_args.kwargs["update"]
    assert isinstance(command, AssistantUpdateCommand)
    assert command.completion_model_id is None
    assert "completion_model_id" in command.model_fields_set


@pytest.mark.asyncio
async def test_duplicate_slot_bindings_fail_before_mutation() -> None:
    first = _resource_binding(slot="default-model")
    second = _resource_binding(slot="default-model")
    service = _flow_service()

    with pytest.raises(BadRequestException) as error:
        await FlowDraftMaterializer().execute(
            changeset=FlowDraftChangeSet(flow_name="Flow", flow_description=""),
            flow_service=service,
            space_id=uuid4(),
            flow_id=None,
            resource_bindings=(first, second),
            binding_source=FlowResourceBindingSource.AI_BUILDER,
        )

    assert error.value.code == "duplicate_slot_binding"
    service.create_flow.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_slot_ref_preserves_bad_request_code_without_cleanup() -> None:
    flow_id = uuid4()
    service = _flow_service()
    service.create_flow.return_value = _flow(flow_id=flow_id)
    assistant = MagicMock()
    assistant.id = uuid4()
    service.create_flow_assistant.return_value = (assistant, [])

    with pytest.raises(BadRequestException) as error:
        await FlowDraftMaterializer().execute(
            changeset=FlowDraftChangeSet(
                flow_name="Flow",
                flow_description="",
                assistants_to_create=[
                    FlowDraftAssistantToCreate(
                        plan_step_ref="step_a",
                        assistant_spec=AssistantSpec(
                            instructions="Use invalid refs.",
                            model_ref="not-a-valid-ref",
                        ),
                    )
                ],
                compiled_steps=[_compiled_step()],
            ),
            flow_service=service,
            space_id=uuid4(),
            flow_id=None,
            binding_source=FlowResourceBindingSource.AI_BUILDER,
        )

    assert error.value.code == "invalid_model_ref"
    service.delete_flow.assert_not_awaited()


@pytest.mark.asyncio
async def test_progress_snapshots_are_bounded_shared_values() -> None:
    flow_id = uuid4()
    service = _flow_service()
    service.create_flow.return_value = _flow(flow_id=flow_id)
    assistant = MagicMock()
    assistant.id = uuid4()
    service.create_flow_assistant.return_value = (assistant, [])
    snapshots: list[FlowDraftMaterializationProgress] = []

    await FlowDraftMaterializer().execute(
        changeset=FlowDraftChangeSet(
            flow_name="Progress flow",
            flow_description="",
            assistants_to_create=[
                FlowDraftAssistantToCreate(
                    plan_step_ref="step_a",
                    assistant_spec=AssistantSpec(instructions="Do it."),
                )
            ],
            compiled_steps=[_compiled_step()],
        ),
        flow_service=service,
        space_id=uuid4(),
        flow_id=None,
        binding_source=FlowResourceBindingSource.AI_BUILDER,
        progress_callback=snapshots.append,
    )

    assert [snapshot.stage for snapshot in snapshots] == [
        FlowDraftMaterializationStage.FLOW_CREATED,
        FlowDraftMaterializationStage.ASSISTANTS_CREATED,
        FlowDraftMaterializationStage.ASSISTANTS_CONFIGURED,
        FlowDraftMaterializationStage.FLOW_UPDATED,
    ]
    assert snapshots[-1].assistants_created == 1
    assert snapshots[-1].flow_updated is True
