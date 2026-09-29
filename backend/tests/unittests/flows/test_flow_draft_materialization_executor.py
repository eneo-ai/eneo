from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.flows.application.flow_authoring_command import TemplateAttachmentIntent
from eneo.flows.application.flow_draft_materialization import (
    ALL_ASSISTANT_FIELDS,
    FlowDraftAssistantToCreate,
    FlowDraftAssistantToUpdate,
    FlowDraftChangeSet,
    FlowDraftCompiledStep,
    FlowDraftMaterializationProgress,
    FlowDraftMaterializationStage,
    FlowDraftStepChangeKind,
)
from eneo.flows.application.flow_draft_materialization_executor import (
    FlowDraftMaterializer,
)
from eneo.flows.domain.flow import Flow, FlowStep, FlowTemplateAsset
from eneo.flows.flow_authoring_spec import AssistantSpec
from eneo.flows.flow_resource_bindings import (
    FlowResourceBindingSource,
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from eneo.flows.infrastructure.flow_repo import StoredAssistantPrompt
from eneo.main.exceptions import BadRequestException


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
    output_type: str = "text",
    output_config: dict[str, object] | None = None,
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
        output_type=output_type,
        output_config=output_config,
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
    service.get_flow_assistant_prompts.return_value = {}
    return service


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
async def test_create_mode_resolves_template_intent_after_flow_creation() -> None:
    flow_id = uuid4()
    space_id = uuid4()
    file_id = uuid4()
    assistant_ids = iter((uuid4(), uuid4()))
    service = _flow_service()
    service.create_flow.return_value = _flow(flow_id=flow_id, space_id=space_id)
    promoted = False

    async def create_assistant(**_kwargs):
        assert promoted is True
        assistant = MagicMock()
        assistant.id = next(assistant_ids)
        return assistant, []

    service.create_flow_assistant.side_effect = create_assistant
    template_asset_service = AsyncMock()
    now = datetime.now(timezone.utc)
    asset = FlowTemplateAsset(
        id=uuid4(),
        flow_id=flow_id,
        space_id=space_id,
        tenant_id=uuid4(),
        file_id=file_id,
        name="template.docx",
        checksum="checksum",
        placeholders=["case_id"],
        created_at=now,
        updated_at=now,
    )

    async def promote(**_kwargs):
        nonlocal promoted
        service.create_flow.assert_awaited_once()
        promoted = True
        return asset

    template_asset_service.create_from_existing_attached_file.side_effect = promote

    await FlowDraftMaterializer().execute(
        changeset=FlowDraftChangeSet(
            flow_name="Template flow",
            flow_description="",
            assistants_to_create=[
                FlowDraftAssistantToCreate(
                    plan_step_ref="step_a",
                    assistant_spec=AssistantSpec(instructions="Prepare."),
                ),
                FlowDraftAssistantToCreate(
                    plan_step_ref="step_b",
                    assistant_spec=AssistantSpec(instructions="Fill."),
                ),
            ],
            compiled_steps=[
                _compiled_step(plan_step_ref="step_a", step_order=1),
                _compiled_step(
                    plan_step_ref="step_b",
                    step_order=2,
                    output_mode="template_fill",
                    output_type="docx",
                    output_config={"bindings": {"case_id": "{{ flow_input.case_id }}"}},
                ),
            ],
        ),
        flow_service=service,
        space_id=space_id,
        flow_id=None,
        binding_source=FlowResourceBindingSource.AI_BUILDER,
        template_attachment_intent=TemplateAttachmentIntent(
            file_id=file_id,
            terminal_plan_step_ref="step_b",
        ),
        template_asset_service=template_asset_service,
    )

    update = service.update_flow.await_args.kwargs
    assert update["steps"][-1].output_config == {
        "template_asset_id": str(asset.id),
        "bindings": {"case_id": "{{ flow_input.case_id }}"},
    }
    assert "metadata_json" not in update
    template_binding = service.replace_resource_bindings.await_args.kwargs["bindings"][
        -1
    ]
    assert template_binding.local_kind is LocalResourceKind.TEMPLATE_ASSET
    assert template_binding.local_id == asset.id


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
async def test_edit_mode_updates_assistants_before_flow_and_deletes_nothing() -> None:
    flow_id = uuid4()
    existing_assistant_id = uuid4()
    service = _flow_service()

    result = await FlowDraftMaterializer().execute(
        changeset=FlowDraftChangeSet(
            flow_name="Updated flow",
            flow_description="Description",
            assistants_to_update=[
                FlowDraftAssistantToUpdate(
                    existing_assistant_id=existing_assistant_id,
                    fields=ALL_ASSISTANT_FIELDS - {"model_ref"},
                    prompt_alias_renumbering={},
                    assistant_spec=AssistantSpec(instructions="Updated prompt"),
                )
            ],
            removed_existing_step_refs=frozenset({"existing_step_2"}),
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
    # The flow update deletes the removed step's assistant; a second delete
    # here would fail on the row the update already removed.
    service.delete_flow_assistant.assert_not_awaited()
    call_names = [call[0] for call in service.mock_calls]
    assert call_names.index("update_flow_assistant") < call_names.index("update_flow")
    assert result.steps_updated == 1
    assert result.steps_removed == 1


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
async def test_step_without_knowledge_clears_resource_lists() -> None:
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
    assert not command.is_set("mcp_server_ids")
    assert not command.is_set("mcp_tools")
    assert command.prompt is not None
    assert command.prompt.text == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("output_mode", "output_type"),
    [("transcribe_only", "text"), ("template_fill", "docx")],
)
async def test_materializer_clears_completion_model_for_non_completion_create_changeset(
    output_mode: str,
    output_type: str,
) -> None:
    flow_id = uuid4()
    service = _flow_service()
    service.create_flow.return_value = _flow(flow_id=flow_id)
    assistant = MagicMock()
    assistant.id = uuid4()
    service.create_flow_assistant.return_value = (assistant, [])

    await FlowDraftMaterializer().execute(
        changeset=FlowDraftChangeSet(
            flow_name="Non-completion flow",
            flow_description="",
            assistants_to_create=[
                FlowDraftAssistantToCreate(
                    plan_step_ref="non_completion_step",
                    assistant_spec=AssistantSpec(
                        instructions="Run the step.",
                        model_ref="model.default",
                    ),
                )
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref="non_completion_step",
                    output_mode=output_mode,
                    output_type=output_type,
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
@pytest.mark.parametrize(
    ("output_mode", "output_type"),
    [("transcribe_only", "text"), ("template_fill", "docx")],
)
async def test_materializer_clears_completion_model_for_non_completion_update_changeset(
    output_mode: str,
    output_type: str,
) -> None:
    flow_id = uuid4()
    assistant_id = uuid4()
    service = _flow_service()

    await FlowDraftMaterializer().execute(
        changeset=FlowDraftChangeSet(
            flow_name="Non-completion flow",
            flow_description="",
            assistants_to_update=[
                FlowDraftAssistantToUpdate(
                    existing_assistant_id=assistant_id,
                    fields=ALL_ASSISTANT_FIELDS,
                    prompt_alias_renumbering={},
                    assistant_spec=AssistantSpec(
                        instructions="Run the step.",
                        model_ref="model.default",
                    ),
                )
            ],
            compiled_steps=[
                _compiled_step(
                    plan_step_ref="non_completion_step",
                    change_kind=FlowDraftStepChangeKind.MODIFIED,
                    assistant_id=assistant_id,
                    output_mode=output_mode,
                    output_type=output_type,
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
async def test_unresolved_slot_binding_fails_before_mutation() -> None:
    service = _flow_service()

    with pytest.raises(BadRequestException) as error:
        await FlowDraftMaterializer().execute(
            changeset=FlowDraftChangeSet(
                flow_name="Flow",
                flow_description="",
                assistants_to_create=[
                    FlowDraftAssistantToCreate(
                        plan_step_ref="step_a",
                        assistant_spec=AssistantSpec(
                            instructions="Use model.",
                            model_ref="model.default",
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

    assert error.value.code == "unresolved_slot_binding"
    assert error.value.context["slot_ref"] == "model.default"
    service.create_flow.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_slot_ref_fails_before_mutation() -> None:
    service = _flow_service()

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
    service.create_flow.assert_not_called()


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


@pytest.mark.asyncio
async def test_a_retained_step_is_written_as_its_saved_row_with_the_authored_columns() -> (
    None
):
    """The step keeps its id and the columns the spec has no field for; the
    columns the changeset carries replace the saved ones; an added step has
    neither."""

    flow_id, kept_assistant_id, new_assistant_id = uuid4(), uuid4(), uuid4()
    saved = FlowStep(
        id=uuid4(),
        flow_id=flow_id,
        tenant_id=uuid4(),
        assistant_id=kept_assistant_id,
        step_order=1,
        timeout_seconds=90,
        output_classification_override=2,
        user_description="Gammal",
        input_source="flow_input",
        input_type="text",
        output_mode="pass_through",
        output_type="text",
    )
    service = _flow_service()
    service.update_flow.return_value = MagicMock(draft_revision=2)
    created = MagicMock()
    created.id = new_assistant_id
    service.create_flow_assistant.return_value = (created, [])
    retained = _compiled_step(
        change_kind=FlowDraftStepChangeKind.UNCHANGED, assistant_id=kept_assistant_id
    ).model_copy(update={"saved_step": saved})

    await FlowDraftMaterializer().execute(
        changeset=FlowDraftChangeSet(
            flow_name="Flow",
            flow_description="",
            assistants_to_create=[
                FlowDraftAssistantToCreate(
                    plan_step_ref="step_b",
                    assistant_spec=AssistantSpec(instructions="Do it."),
                )
            ],
            compiled_steps=[
                retained,
                _compiled_step(plan_step_ref="step_b", step_order=2),
            ],
        ),
        flow_service=service,
        space_id=uuid4(),
        flow_id=flow_id,
        expected_revision=1,
        binding_source=FlowResourceBindingSource.AI_BUILDER,
    )

    kept, added = service.update_flow.await_args.kwargs["steps"]
    assert (kept.id, kept.timeout_seconds, kept.output_classification_override) == (
        saved.id,
        90,
        2,
    )
    assert kept.user_description == "Test step"
    assert (added.id, added.timeout_seconds, added.output_classification_override) == (
        None,
        None,
        None,
    )


async def _update_command(
    fields: frozenset[str],
    *,
    spec: AssistantSpec,
    output_mode: str = "pass_through",
    bindings: tuple[LocalResourceBinding, ...] = (),
    renumbering: dict[int, int] | None = None,
    stored_prompt: str = "",
    stored_description: str | None = None,
) -> AssistantUpdateCommand | None:
    """The assistant update an edit changeset makes for one step, if any; the
    assistant holds `stored_prompt` when the apply runs."""

    assistant_id = uuid4()
    service = _flow_service()
    service.update_flow.return_value = MagicMock(draft_revision=2)
    service.get_flow_assistant_prompts.return_value = {
        assistant_id: StoredAssistantPrompt(
            text=stored_prompt, description=stored_description
        )
    }
    await FlowDraftMaterializer().execute(
        changeset=FlowDraftChangeSet(
            flow_name="Flow",
            flow_description="",
            assistants_to_update=[
                FlowDraftAssistantToUpdate(
                    existing_assistant_id=assistant_id,
                    fields=fields,  # type: ignore[arg-type]
                    prompt_alias_renumbering=renumbering or {},
                    assistant_spec=spec,
                )
            ],
            compiled_steps=[
                _compiled_step(
                    change_kind=FlowDraftStepChangeKind.MODIFIED,
                    assistant_id=assistant_id,
                    output_mode=output_mode,
                )
            ],
        ),
        flow_service=service,
        space_id=uuid4(),
        flow_id=uuid4(),
        expected_revision=1,
        resource_bindings=bindings,
        binding_source=FlowResourceBindingSource.AI_BUILDER,
    )
    if not service.update_flow_assistant.await_args_list:
        return None
    return service.update_flow_assistant.await_args.kwargs["update"]


@pytest.mark.asyncio
async def test_an_update_naming_no_assistant_field_makes_no_assistant_call() -> None:
    assert (
        await _update_command(frozenset(), spec=AssistantSpec(instructions="x")) is None
    )


@pytest.mark.asyncio
async def test_an_instruction_update_writes_the_prompt_and_no_other_field() -> None:
    command = await _update_command(
        frozenset({"instructions"}),
        spec=AssistantSpec(instructions="Ny text", knowledge_refs=["knowledge.policy"]),
        bindings=(
            _resource_binding(
                slot="policy",
                slot_kind=ResourceSlotKind.KNOWLEDGE,
                local_kind=LocalResourceKind.COLLECTION,
            ),
        ),
    )

    assert command is not None and command.prompt is not None
    assert command.prompt.text == "Ny text"
    assert command.model_fields_set == {"prompt"}


@pytest.mark.asyncio
async def test_a_knowledge_update_replaces_the_collections_and_keeps_other_kinds() -> (
    None
):
    collection_id, website_id = uuid4(), uuid4()
    only_collections = await _update_command(
        frozenset({"knowledge_refs"}),
        spec=AssistantSpec(instructions="x", knowledge_refs=["knowledge.policy"]),
        bindings=(
            _resource_binding(
                slot="policy",
                slot_kind=ResourceSlotKind.KNOWLEDGE,
                local_kind=LocalResourceKind.COLLECTION,
                local_id=collection_id,
            ),
        ),
    )
    naming_a_website = await _update_command(
        frozenset({"knowledge_refs"}),
        spec=AssistantSpec(instructions="x", knowledge_refs=["knowledge.site"]),
        bindings=(
            _resource_binding(
                slot="site",
                slot_kind=ResourceSlotKind.KNOWLEDGE,
                local_kind=LocalResourceKind.WEBSITE,
                local_id=website_id,
            ),
        ),
    )
    no_knowledge = await _update_command(
        frozenset({"knowledge_refs"}), spec=AssistantSpec(instructions="x")
    )

    assert only_collections is not None and no_knowledge is not None
    assert only_collections.model_fields_set == {"groups"}
    assert only_collections.groups == [collection_id]
    assert no_knowledge.model_fields_set == {"groups"} and no_knowledge.groups == []
    assert naming_a_website is not None
    assert naming_a_website.model_fields_set == {"groups", "websites"}
    assert naming_a_website.websites == [website_id]


@pytest.mark.asyncio
async def test_a_model_update_clears_the_model_of_a_step_without_completion() -> None:
    command = await _update_command(
        frozenset({"model_ref"}),
        spec=AssistantSpec(instructions="x"),
        output_mode="render_verbatim",
    )

    assert command is not None
    assert command.model_fields_set == {"completion_model_id"}
    assert command.completion_model_id is None


@pytest.mark.asyncio
async def test_an_update_that_names_the_model_of_a_step_that_runs_one_is_refused() -> (
    None
):
    """An edit never chooses a model, so nothing can carry it out: the apply
    fails instead of reporting success without writing a model."""

    with pytest.raises(BadRequestException, match="does not choose"):
        await _update_command(
            frozenset({"model_ref"}),
            spec=AssistantSpec(instructions="x", model_ref="model.gpt"),
            bindings=(
                _resource_binding(
                    slot="gpt",
                    slot_kind=ResourceSlotKind.MODEL,
                    local_kind=LocalResourceKind.COMPLETION_MODEL,
                ),
            ),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "written"),
    [("instructions", {"prompt"}), ("knowledge_refs", {"groups"})],
)
async def test_an_update_of_another_field_leaves_the_model_of_a_step_without_completion(
    field: str, written: set[str]
) -> None:
    """A step that runs no completion model may still hold one it was saved
    with. Only an update that names `model_ref` clears it."""

    command = await _update_command(
        frozenset({field}),
        spec=AssistantSpec(instructions="x"),
        output_mode="render_verbatim",
    )

    assert command is not None
    assert command.model_fields_set == written


@pytest.mark.asyncio
async def test_a_moved_step_renumbers_the_prompt_the_assistant_holds_and_nothing_else() -> (
    None
):
    """Whatever the plan's copy of the prompt says, the prompt written is the
    one the assistant holds at apply, with the moved aliases renumbered and
    the author's spacing kept."""

    command = await _update_command(
        frozenset(),
        spec=AssistantSpec(instructions="Planens text {{ step_3.output.text }}."),
        renumbering={2: 3},
        stored_prompt="Redigerad {{step_2.output.text}} och {{ step_1 }}.",
    )

    assert command is not None and command.prompt is not None
    assert command.prompt.text == "Redigerad {{step_3.output.text}} och {{ step_1 }}."
    assert command.model_fields_set == {"prompt"}


@pytest.mark.asyncio
async def test_a_moved_step_leaves_a_prompt_that_reads_no_moved_step_unwritten() -> (
    None
):
    assert (
        await _update_command(
            frozenset(),
            spec=AssistantSpec(instructions="x"),
            renumbering={2: 3},
            stored_prompt="Läs {{ step_1.output.text }}.",
        )
        is None
    )


@pytest.mark.asyncio
async def test_a_named_field_beside_a_move_writes_the_field_and_the_renumbered_prompt() -> (
    None
):
    command = await _update_command(
        frozenset({"knowledge_refs"}),
        spec=AssistantSpec(instructions="Planens text."),
        renumbering={2: 3},
        stored_prompt="Läs {{ step_2 }}.",
    )

    assert command is not None and command.prompt is not None
    assert command.prompt.text == "Läs {{ step_3 }}."
    assert command.model_fields_set == {"prompt", "groups"}


@pytest.mark.asyncio
async def test_the_prompts_to_renumber_are_read_once_per_apply() -> None:
    """Three kept steps after a move: one read of the flow's prompts, no read
    per assistant, and only the prompt that reads a moved step is written."""

    ids = [uuid4(), uuid4(), uuid4()]
    service = _flow_service()
    service.update_flow.return_value = MagicMock(draft_revision=2)
    prompts = ["Läs.", "Läs {{ step_2.output.text }}.", "Skriv."]
    service.get_flow_assistant_prompts.return_value = {
        assistant_id: StoredAssistantPrompt(text=prompt, description=None)
        for assistant_id, prompt in zip(ids, prompts, strict=True)
    }
    await FlowDraftMaterializer().execute(
        changeset=FlowDraftChangeSet(
            flow_name="Flow",
            flow_description="",
            assistants_to_update=[
                FlowDraftAssistantToUpdate(
                    existing_assistant_id=assistant_id,
                    fields=frozenset(),
                    prompt_alias_renumbering={2: 3},
                    assistant_spec=AssistantSpec(instructions="x"),
                )
                for assistant_id in ids
            ],
            compiled_steps=[
                _compiled_step(
                    change_kind=FlowDraftStepChangeKind.UNCHANGED,
                    assistant_id=assistant_id,
                )
                for assistant_id in ids
            ],
        ),
        flow_service=service,
        space_id=uuid4(),
        flow_id=uuid4(),
        expected_revision=1,
        binding_source=FlowResourceBindingSource.AI_BUILDER,
    )

    assert service.get_flow_assistant_prompts.await_count == 1
    assert service.get_flow_assistant_snapshots.await_count == 0
    assert service.get_flow_assistant.await_count == 0
    ((_, call),) = [
        (c.args, c.kwargs) for c in service.update_flow_assistant.await_args_list
    ]
    assert call["assistant_id"] == ids[1]
    assert call["update"].prompt.text == "Läs {{ step_3.output.text }}."


@pytest.mark.asyncio
async def test_a_renumbered_prompt_is_the_stored_one_whitespace_and_description_kept() -> (
    None
):
    command = await _update_command(
        frozenset(),
        spec=AssistantSpec(instructions="x"),
        renumbering={2: 3},
        stored_prompt="\nLäs {{ step_2.output.text }}\n",
        stored_description="Skriven av Anna.",
    )

    assert command is not None and command.prompt is not None
    assert command.prompt.text == "\nLäs {{ step_3.output.text }}\n"
    assert command.prompt.description == "Skriven av Anna."


@pytest.mark.asyncio
async def test_an_instruction_update_keeps_the_stored_prompts_description() -> None:
    command = await _update_command(
        frozenset({"instructions"}),
        spec=AssistantSpec(instructions="Ny text"),
        stored_prompt="Gammal text",
        stored_description="Skriven av Anna.",
    )

    assert command is not None and command.prompt is not None
    assert (command.prompt.text, command.prompt.description) == (
        "Ny text",
        "Skriven av Anna.",
    )
