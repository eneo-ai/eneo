from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from eneo.flow_packages.application.flow_package_import_planner import (
    FlowPackageImportPlannerCandidates,
    build_flow_package_import_plan,
)
from eneo.flow_packages.application.flow_package_install_service import (
    FlowPackageInstallResult,
    FlowPackageInstallService,
    resolve_flow_package_install_command,
    validate_flow_package_install_selection,
)
from eneo.flow_packages.domain.flow_package_draft import FlowPackageFlowDraft
from eneo.flow_packages.domain.flow_package_envelope import FlowPackageEnvelope
from eneo.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageValidationError,
)
from eneo.flow_packages.domain.flow_package_import_plan import (
    FlowPackageLocalCandidate,
    FlowPackageModelCandidate,
)
from eneo.flow_packages.domain.flow_package_import_record import (
    FlowPackageImportSelection,
)
from eneo.flow_packages.domain.flow_package_manifest import (
    EneoPackageKind,
    FlowPackageManifestMetadata,
)
from eneo.flow_packages.domain.flow_package_provenance import FlowPackageProvenance
from eneo.flow_packages.domain.flow_package_requirements import (
    FlowPackageCompletionModelConstraints,
    FlowPackageKnowledgeRequirement,
    FlowPackageModelIdentity,
    FlowPackageModelKind,
    FlowPackageModelMatchingPreferences,
    FlowPackageModelRequirement,
    FlowPackageRequirementEntry,
    FlowPackageRequirementSet,
    FlowPackageTemplateAssetRequirement,
)
from eneo.flows.application.flow_service import FlowService
from eneo.flows.domain.flow import Flow
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    StepSpec,
)
from eneo.flows.flow_resource_bindings import (
    FlowResourceBindingResolutionError,
    FlowResourceBindingResolutionReason,
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)


@pytest.mark.asyncio
async def test_install_as_draft_materializes_package_with_package_import_bindings() -> (
    None
):
    flow_id = uuid4()
    space_id = uuid4()
    assistant_id = uuid4()
    model_id = uuid4()
    binding = _binding(
        slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=model_id,
    )
    service = _flow_service(flow_id=flow_id, assistant_id=assistant_id)

    result = await _install_as_draft(
        envelope=_envelope(),
        flow_service=service,
        space_id=space_id,
        selected_bindings=(binding,),
        candidates=_candidates(models=[_model_candidate(model_id)]),
    )

    service.create_flow.assert_awaited_once()
    service.replace_resource_bindings.assert_awaited_once()
    replace_kwargs = service.replace_resource_bindings.await_args.kwargs
    assert replace_kwargs["bindings"] == (binding,)
    assert replace_kwargs["source"].value == "package_import"
    assert result.flow_id == flow_id
    assert result.flow_name == "Imported Flow"
    assert result.package_id == "se.demo.import"
    assert result.package_version == "1.0.0"
    assert result.content_checksum == _envelope().content_checksum
    assert result.steps_created == 1
    assert result.resource_bindings_count == 1


@pytest.mark.asyncio
async def test_install_rejects_missing_required_model_before_creating_flow() -> None:
    service = _flow_service()

    with pytest.raises(FlowPackageValidationError) as exc_info:
        await _install_as_draft(
            envelope=_envelope(),
            flow_service=service,
            space_id=uuid4(),
            selected_bindings=tuple(),
            candidates=_candidates(),
        )

    assert (
        exc_info.value.code
        is FlowPackageErrorCode.IMPORT_MISSING_REQUIRED_RESOURCE_BINDING
    )
    assert exc_info.value.context["slot_ref"] == "model.structured"
    service.create_flow.assert_not_called()


@pytest.mark.asyncio
async def test_install_rejects_unbound_required_knowledge_before_creating_flow() -> (
    None
):
    model_id = uuid4()
    model_binding = _binding(
        slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=model_id,
    )
    knowledge_slot = _slot_ref(ResourceSlotKind.KNOWLEDGE, "local-rules")
    service = _flow_service()

    with pytest.raises(FlowPackageValidationError) as exc_info:
        await _install_as_draft(
            envelope=_envelope(
                requirements=[
                    FlowPackageModelRequirement(
                        slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
                    ),
                    FlowPackageKnowledgeRequirement(slot_ref=knowledge_slot),
                ],
                assistant=AssistantSpec(
                    instructions="Use local guidance.",
                    model_ref="model.structured",
                    knowledge_refs=[knowledge_slot.ref],
                ),
            ),
            flow_service=service,
            space_id=uuid4(),
            selected_bindings=(model_binding,),
            candidates=_candidates(models=[_model_candidate(model_id)]),
        )

    assert (
        exc_info.value.code
        is FlowPackageErrorCode.IMPORT_MISSING_REQUIRED_RESOURCE_BINDING
    )
    assert exc_info.value.context["slot_ref"] == knowledge_slot.ref
    service.create_flow.assert_not_called()


@pytest.mark.asyncio
async def test_install_omits_only_unbound_optional_knowledge() -> None:
    flow_id = uuid4()
    assistant_id = uuid4()
    model_id = uuid4()
    model_binding = _binding(
        slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=model_id,
    )
    knowledge_slot = _slot_ref(ResourceSlotKind.KNOWLEDGE, "local-rules")
    service = _flow_service(flow_id=flow_id, assistant_id=assistant_id)

    result = await _install_as_draft(
        envelope=_envelope(
            requirements=[
                FlowPackageModelRequirement(
                    slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
                ),
                FlowPackageKnowledgeRequirement(
                    slot_ref=knowledge_slot,
                    required=False,
                ),
            ],
            assistant=AssistantSpec(
                instructions="Use local guidance when available.",
                model_ref="model.structured",
                knowledge_refs=[knowledge_slot.ref],
            ),
        ),
        flow_service=service,
        space_id=uuid4(),
        selected_bindings=(model_binding,),
        candidates=_candidates(models=[_model_candidate(model_id)]),
    )

    assert result.resource_bindings_count == 1
    update = service.update_flow_assistant.await_args.kwargs["update"]
    assert update.groups == []
    replace_kwargs = service.replace_resource_bindings.await_args.kwargs
    assert replace_kwargs["bindings"] == (model_binding,)


@pytest.mark.asyncio
async def test_install_preserves_selected_knowledge_binding() -> None:
    flow_id = uuid4()
    assistant_id = uuid4()
    model_id = uuid4()
    knowledge_id = uuid4()
    model_binding = _binding(
        slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=model_id,
    )
    knowledge_slot = _slot_ref(ResourceSlotKind.KNOWLEDGE, "local-rules")
    knowledge_binding = _binding(
        slot_ref=knowledge_slot,
        local_kind=LocalResourceKind.COLLECTION,
        local_id=knowledge_id,
    )
    service = _flow_service(flow_id=flow_id, assistant_id=assistant_id)

    result = await _install_as_draft(
        envelope=_envelope(
            requirements=[
                FlowPackageModelRequirement(
                    slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
                ),
                FlowPackageKnowledgeRequirement(slot_ref=knowledge_slot),
            ],
            assistant=AssistantSpec(
                instructions="Use local guidance.",
                model_ref="model.structured",
                knowledge_refs=[knowledge_slot.ref],
            ),
        ),
        flow_service=service,
        space_id=uuid4(),
        selected_bindings=(model_binding, knowledge_binding),
        candidates=_candidates(
            models=[_model_candidate(model_id)],
            knowledge=[_knowledge_candidate(knowledge_id)],
        ),
    )

    assert result.resource_bindings_count == 2
    update = service.update_flow_assistant.await_args.kwargs["update"]
    assert update.groups == [knowledge_id]
    replace_kwargs = service.replace_resource_bindings.await_args.kwargs
    assert replace_kwargs["bindings"] == (knowledge_binding, model_binding)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("local_kind", "expected_field"),
    [
        (LocalResourceKind.WEBSITE, "websites"),
        (LocalResourceKind.INTEGRATION_KNOWLEDGE, "integration_knowledge_ids"),
    ],
)
async def test_install_preserves_selected_non_collection_knowledge_binding(
    local_kind: LocalResourceKind,
    expected_field: str,
) -> None:
    flow_id = uuid4()
    assistant_id = uuid4()
    model_id = uuid4()
    knowledge_id = uuid4()
    model_binding = _binding(
        slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=model_id,
    )
    knowledge_slot = _slot_ref(ResourceSlotKind.KNOWLEDGE, "local-rules")
    knowledge_binding = _binding(
        slot_ref=knowledge_slot,
        local_kind=local_kind,
        local_id=knowledge_id,
    )
    service = _flow_service(flow_id=flow_id, assistant_id=assistant_id)

    result = await _install_as_draft(
        envelope=_envelope(
            requirements=[
                FlowPackageModelRequirement(
                    slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
                ),
                FlowPackageKnowledgeRequirement(slot_ref=knowledge_slot),
            ],
            assistant=AssistantSpec(
                instructions="Use local guidance.",
                model_ref="model.structured",
                knowledge_refs=[knowledge_slot.ref],
            ),
        ),
        flow_service=service,
        space_id=uuid4(),
        selected_bindings=(model_binding, knowledge_binding),
        candidates=_candidates(
            models=[_model_candidate(model_id)],
            knowledge=[_knowledge_candidate(knowledge_id, local_kind=local_kind)],
        ),
    )

    assert result.resource_bindings_count == 2
    update = service.update_flow_assistant.await_args.kwargs["update"]
    assert update.groups == ([] if expected_field != "groups" else [knowledge_id])
    assert update.websites == ([knowledge_id] if expected_field == "websites" else [])
    assert update.integration_knowledge_ids == (
        [knowledge_id] if expected_field == "integration_knowledge_ids" else []
    )


def test_envelope_rejects_optional_model_slot_referenced_by_step() -> None:
    with pytest.raises(FlowPackageValidationError) as exc_info:
        _envelope(
            requirements=[
                FlowPackageModelRequirement(
                    slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
                    required=False,
                )
            ]
        )

    assert exc_info.value.code is FlowPackageErrorCode.REQUIREMENTS_INVALID
    assert exc_info.value.context == {
        "slot_ref": "model.structured",
        "reason": "referenced_model_must_be_required",
    }


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("knowledge_as_model", "assistant_model_ref_kind_mismatch"),
        ("model_as_knowledge", "assistant_knowledge_ref_kind_mismatch"),
        ("transcription_as_model", "assistant_model_requires_completion_model"),
    ],
)
def test_envelope_rejects_requirement_kind_that_does_not_match_draft_use(
    case: str,
    reason: str,
) -> None:
    if case == "knowledge_as_model":
        requirements: list[FlowPackageRequirementEntry] = [
            FlowPackageKnowledgeRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.KNOWLEDGE, "policy")
            )
        ]
        assistant = AssistantSpec(
            instructions="Invalid model use.",
            model_ref="knowledge.policy",
        )
        slot_ref = "knowledge.policy"
    elif case == "model_as_knowledge":
        requirements = [
            FlowPackageModelRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured")
            )
        ]
        assistant = AssistantSpec(
            instructions="Invalid knowledge use.",
            knowledge_refs=["model.structured"],
        )
        slot_ref = "model.structured"
    else:
        requirements = [
            FlowPackageModelRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.MODEL, "speech"),
                model_kind=FlowPackageModelKind.TRANSCRIPTION_MODEL,
            )
        ]
        assistant = AssistantSpec(
            instructions="Invalid assistant model.",
            model_ref="model.speech",
        )
        slot_ref = "model.speech"

    with pytest.raises(FlowPackageValidationError) as exc_info:
        _envelope(requirements=requirements, assistant=assistant)

    assert exc_info.value.code is FlowPackageErrorCode.REQUIREMENTS_INVALID
    assert exc_info.value.context == {"slot_ref": slot_ref, "reason": reason}


@pytest.mark.asyncio
async def test_install_rejects_unknown_selected_binding_before_creating_flow() -> None:
    model_id = uuid4()
    service = _flow_service()
    binding = _binding(
        slot_ref=_slot_ref(ResourceSlotKind.MODEL, "undeclared"),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=model_id,
    )

    with pytest.raises(FlowPackageValidationError) as exc_info:
        await _install_as_draft(
            envelope=_envelope(),
            flow_service=service,
            space_id=uuid4(),
            selected_bindings=(binding,),
            candidates=_candidates(models=[_model_candidate(model_id)]),
        )

    assert exc_info.value.code is FlowPackageErrorCode.IMPORT_UNKNOWN_RESOURCE_BINDING
    assert exc_info.value.context["slot_ref"] == "model.undeclared"
    service.create_flow.assert_not_called()


@pytest.mark.asyncio
async def test_install_preserves_canonical_duplicate_binding_reason_before_creating_flow() -> (
    None
):
    first = _binding(
        slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=uuid4(),
    )
    second = _binding(
        slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=uuid4(),
    )
    service = _flow_service()

    with pytest.raises(FlowResourceBindingResolutionError) as exc_info:
        await _install_as_draft(
            envelope=_envelope(),
            flow_service=service,
            space_id=uuid4(),
            selected_bindings=(first, second),
            candidates=_candidates(
                models=[
                    _model_candidate(first.local_id),
                    _model_candidate(second.local_id),
                ]
            ),
        )

    assert (
        exc_info.value.reason
        is FlowResourceBindingResolutionReason.DUPLICATE_SLOT_BINDING
    )
    service.create_flow.assert_not_called()


@pytest.mark.asyncio
async def test_install_rejects_selected_local_id_not_available_in_target_space() -> (
    None
):
    unavailable_model_id = uuid4()
    service = _flow_service()
    binding = _binding(
        slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=unavailable_model_id,
    )

    with pytest.raises(FlowPackageValidationError) as exc_info:
        await _install_as_draft(
            envelope=_envelope(),
            flow_service=service,
            space_id=uuid4(),
            selected_bindings=(binding,),
            candidates=_candidates(models=[_model_candidate(uuid4())]),
        )

    assert exc_info.value.code is FlowPackageErrorCode.IMPORT_UNAVAILABLE_LOCAL_RESOURCE
    assert exc_info.value.context == {
        "slot_ref": "model.structured",
        "local_kind": "completion_model",
        "local_id": str(unavailable_model_id),
    }
    service.create_flow.assert_not_called()


def test_validate_rechecks_selected_model_hard_requirements_at_install_time() -> None:
    model_id = uuid4()
    binding = _binding(
        slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=model_id,
    )
    envelope = _envelope(
        requirements=[
            FlowPackageModelRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
                completion_constraints=FlowPackageCompletionModelConstraints(
                    minimum_context_tokens=128000,
                ),
            )
        ]
    )

    with pytest.raises(FlowPackageValidationError) as exc_info:
        validate_flow_package_install_selection(
            envelope=envelope,
            selected_bindings=(binding,),
            candidates=_candidates(
                models=[_model_candidate(model_id, max_context_tokens=16000)]
            ),
        )

    assert exc_info.value.code is FlowPackageErrorCode.IMPORT_SELECTED_MODEL_INELIGIBLE
    assert exc_info.value.context["reason"] == "model_context_too_small"


def test_validate_rejects_model_that_became_ineligible_after_import_plan() -> None:
    model_id = uuid4()
    slot_ref = _slot_ref(ResourceSlotKind.MODEL, "structured")
    binding = _binding(
        slot_ref=slot_ref,
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=model_id,
    )
    envelope = _envelope(
        requirements=[
            FlowPackageModelRequirement(
                slot_ref=slot_ref,
                matching_preferences=FlowPackageModelMatchingPreferences(
                    tested_with=[
                        FlowPackageModelIdentity(
                            provider="openai",
                            model="gpt-5.4-mini",
                        )
                    ]
                ),
                completion_constraints=FlowPackageCompletionModelConstraints(
                    minimum_context_tokens=32000,
                ),
            )
        ]
    )
    plan = build_flow_package_import_plan(
        envelope,
        candidates=_candidates(models=[_model_candidate(model_id)]),
    )
    assert plan.dependency_resolutions[0].auto_select_allowed is True

    with pytest.raises(FlowPackageValidationError) as exc_info:
        validate_flow_package_install_selection(
            envelope=envelope,
            selected_bindings=(binding,),
            candidates=_candidates(
                models=[_model_candidate(model_id, max_context_tokens=16000)]
            ),
        )

    assert exc_info.value.code is FlowPackageErrorCode.IMPORT_SELECTED_MODEL_INELIGIBLE
    assert exc_info.value.context["reason"] == "model_context_too_small"


def test_resolved_install_command_rejects_package_changed_after_plan() -> None:
    envelope = _envelope()
    candidates = _candidates(models=[_model_candidate(uuid4())])
    plan = build_flow_package_import_plan(envelope, candidates=candidates)

    with pytest.raises(FlowPackageValidationError) as exc_info:
        resolve_flow_package_install_command(
            envelope=envelope,
            import_plan=plan,
            expected_content_checksum="f" * 64,
            expected_target_state=plan.target_state,
            selection=FlowPackageImportSelection(),
            candidates=candidates,
        )

    assert exc_info.value.code is FlowPackageErrorCode.CHECKSUM_MISMATCH
    assert exc_info.value.context == {
        "expected_content_checksum": "f" * 64,
        "current_content_checksum": envelope.content_checksum,
    }


def test_import_selection_canonicalizes_semantically_unordered_bindings() -> None:
    model = _binding(
        slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=UUID("11111111-1111-4111-8111-111111111111"),
    )
    knowledge = _binding(
        slot_ref=_slot_ref(ResourceSlotKind.KNOWLEDGE, "policy"),
        local_kind=LocalResourceKind.COLLECTION,
        local_id=UUID("22222222-2222-4222-8222-222222222222"),
    )

    first = FlowPackageImportSelection(selected_bindings=[model, knowledge])
    reversed_selection = FlowPackageImportSelection(
        selected_bindings=[knowledge, model]
    )

    assert first.model_dump(mode="json") == reversed_selection.model_dump(mode="json")


def test_resolved_install_command_uses_declared_slot_label_for_retry_identity() -> None:
    envelope = _envelope()
    model_id = UUID("11111111-1111-4111-8111-111111111111")
    candidates = _candidates(models=[_model_candidate(model_id)])
    plan = build_flow_package_import_plan(envelope, candidates=candidates)
    tampered_label = ResourceSlotRef(
        kind=ResourceSlotKind.MODEL,
        slot="structured",
        label="Client supplied label",
    )

    command = resolve_flow_package_install_command(
        envelope=envelope,
        import_plan=plan,
        expected_content_checksum=plan.content_checksum,
        expected_target_state=plan.target_state,
        selection=FlowPackageImportSelection(
            selected_bindings=[
                _binding(
                    slot_ref=tampered_label,
                    local_kind=LocalResourceKind.COMPLETION_MODEL,
                    local_id=model_id,
                )
            ]
        ),
        candidates=candidates,
    )

    assert command.selection.selected_bindings[0].slot_ref == _slot_ref(
        ResourceSlotKind.MODEL,
        "structured",
    )
    stored_selection = command.selection.storage_json()
    assert stored_selection == {
        "selected_bindings": [
            {
                "slot_ref": {
                    "kind": "model",
                    "slot": "structured",
                    "label": "Structured",
                },
                "local_kind": "completion_model",
                "local_id": str(model_id),
            }
        ]
    }
    assert (
        FlowPackageImportSelection.model_validate_json(json.dumps(stored_selection))
        == command.selection
    )


def test_validate_rejects_template_requirements_until_template_install_exists() -> None:
    envelope = _envelope(
        requirements=[
            FlowPackageTemplateAssetRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.TEMPLATE_ASSET, "report-template")
            )
        ],
        assistant=AssistantSpec(instructions="No resources."),
    )

    with pytest.raises(FlowPackageValidationError) as exc_info:
        validate_flow_package_install_selection(
            envelope=envelope,
            selected_bindings=tuple(),
            candidates=_candidates(),
        )

    assert (
        exc_info.value.code is FlowPackageErrorCode.IMPORT_TEMPLATE_ASSETS_UNSUPPORTED
    )
    assert exc_info.value.context["slot_ref"] == "template_asset.report-template"


@pytest.mark.asyncio
async def test_install_zero_requirement_package_with_zero_bindings() -> None:
    flow_id = uuid4()
    service = _flow_service(flow_id=flow_id)

    result = await _install_as_draft(
        envelope=_envelope(
            requirements=[],
            assistant=AssistantSpec(instructions="No resources."),
        ),
        flow_service=service,
        space_id=uuid4(),
        selected_bindings=tuple(),
        candidates=_candidates(),
    )

    assert result.flow_id == flow_id
    assert result.resource_bindings_count == 0
    replace_kwargs = service.replace_resource_bindings.await_args.kwargs
    assert replace_kwargs["bindings"] == tuple()
    assert replace_kwargs["source"].value == "package_import"


@pytest.mark.asyncio
async def test_distinct_resolved_commands_create_distinct_drafts() -> None:
    first_flow_id = uuid4()
    second_flow_id = uuid4()
    model_id = uuid4()
    service = _flow_service(flow_ids=[first_flow_id, second_flow_id])
    binding = _binding(
        slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=model_id,
    )
    first = await _install_as_draft(
        envelope=_envelope(),
        flow_service=service,
        space_id=uuid4(),
        selected_bindings=(binding,),
        candidates=_candidates(models=[_model_candidate(model_id)]),
    )
    second = await _install_as_draft(
        envelope=_envelope(),
        flow_service=service,
        space_id=uuid4(),
        selected_bindings=(binding,),
        candidates=_candidates(models=[_model_candidate(model_id)]),
    )

    assert first.flow_id == first_flow_id
    assert second.flow_id == second_flow_id
    assert first.flow_id != second.flow_id
    assert service.create_flow.await_count == 2


async def _install_as_draft(
    *,
    envelope: FlowPackageEnvelope,
    flow_service: FlowService,
    space_id: UUID,
    selected_bindings: tuple[LocalResourceBinding, ...],
    candidates: FlowPackageImportPlannerCandidates,
    default_transcription_model_id: UUID | None = None,
) -> FlowPackageInstallResult:
    import_plan = build_flow_package_import_plan(
        envelope,
        candidates=candidates,
        default_transcription_model_id=default_transcription_model_id,
    )
    command = resolve_flow_package_install_command(
        envelope=envelope,
        import_plan=import_plan,
        expected_content_checksum=import_plan.content_checksum,
        expected_target_state=import_plan.target_state,
        selection=FlowPackageImportSelection(selected_bindings=list(selected_bindings)),
        candidates=candidates,
    )
    return await FlowPackageInstallService().install_as_draft(
        command=command,
        flow_service=flow_service,
        space_id=space_id,
    )


def _envelope(
    *,
    requirements: list[FlowPackageRequirementEntry] | None = None,
    assistant: AssistantSpec | None = None,
) -> FlowPackageEnvelope:
    spec = FlowDraftSpecCore(
        flow_name="Imported Flow",
        steps=[
            StepSpec(
                plan_step_ref="extract",
                name="Extract",
                assistant_spec=assistant
                or AssistantSpec(
                    instructions="Extract facts.",
                    model_ref="model.structured",
                ),
                input_source=InputSource.FLOW_INPUT,
            )
        ],
    )
    return FlowPackageEnvelope.build_for_export(
        manifest_metadata=FlowPackageManifestMetadata(
            schema_version=1,
            kind=EneoPackageKind.FLOW,
            package_id="se.demo.import",
            package_version="1.0.0",
            name="Imported Flow",
            description="Import package",
        ),
        draft=FlowPackageFlowDraft(schema_version=1, spec=spec),
        requirements=FlowPackageRequirementSet(
            schema_version=1,
            requirements=requirements
            if requirements is not None
            else [
                FlowPackageModelRequirement(
                    slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
                )
            ],
        ),
        provenance=FlowPackageProvenance(
            schema_version=1,
            exported_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
            omissions=[],
        ),
    )


def _slot_ref(kind: ResourceSlotKind, slot: str) -> ResourceSlotRef:
    return ResourceSlotRef(kind=kind, slot=slot, label=slot.replace("-", " ").title())


def _binding(
    *,
    slot_ref: ResourceSlotRef,
    local_kind: LocalResourceKind,
    local_id: UUID,
) -> LocalResourceBinding:
    return LocalResourceBinding(
        slot_ref=slot_ref,
        local_kind=local_kind,
        local_id=local_id,
    )


def _model_candidate(
    local_id: UUID,
    *,
    max_context_tokens: int | None = 64000,
) -> FlowPackageModelCandidate:
    return FlowPackageModelCandidate(
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=local_id,
        label="Structured Model",
        model_kind=FlowPackageModelKind.COMPLETION_MODEL,
        identity=FlowPackageModelIdentity(provider="openai", model="gpt-5.4-mini"),
        max_context_tokens=max_context_tokens,
    )


def _candidates(
    *,
    models: list[FlowPackageModelCandidate] | None = None,
    knowledge: list[FlowPackageLocalCandidate] | None = None,
) -> FlowPackageImportPlannerCandidates:
    return FlowPackageImportPlannerCandidates(
        models=models or [],
        knowledge=knowledge or [],
    )


def _knowledge_candidate(
    local_id: UUID,
    *,
    local_kind: LocalResourceKind = LocalResourceKind.COLLECTION,
) -> FlowPackageLocalCandidate:
    return FlowPackageLocalCandidate(
        local_kind=local_kind,
        local_id=local_id,
        label="Local Rules",
    )


def _flow_service(
    *,
    flow_id: UUID | None = None,
    flow_ids: list[UUID] | None = None,
    assistant_id: UUID | None = None,
) -> AsyncMock:
    service = AsyncMock()
    service.list_flows.return_value = []
    ids = flow_ids or [flow_id or uuid4()]
    service.create_flow.side_effect = [
        Flow(
            id=created_flow_id,
            tenant_id=uuid4(),
            space_id=uuid4(),
            name="Imported Flow",
            description=None,
            steps=[],
        )
        for created_flow_id in ids
    ]
    assistant = MagicMock()
    assistant.id = assistant_id or uuid4()
    service.create_flow_assistant.return_value = (assistant, [])
    return service
