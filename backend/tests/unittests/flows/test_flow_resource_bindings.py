from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from eneo.flows.flow_resource_bindings import (
    FLOW_RESOURCE_BINDING_SOURCE_VALUES,
    RESOURCE_SLOT_LOCAL_KIND_PAIRS,
    FlowResourceBindingResolutionError,
    FlowResourceBindingResolutionReason,
    FlowResourceBindingSource,
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotAllocator,
    ResourceSlotKind,
    ResourceSlotRef,
    assistant_update_field_for_knowledge_local_kind,
    index_local_resource_bindings,
    is_uuid_shaped_resource_ref,
    local_resource_kinds_for_slot_kind,
    resolve_local_resource_ref,
)


def test_resource_slot_ref_derives_ref_from_kind_and_slot() -> None:
    slot_ref = ResourceSlotRef(
        kind=ResourceSlotKind.MODEL,
        slot="structured-extraction",
        label="Structured extraction",
    )

    assert slot_ref.ref == "model.structured-extraction"
    assert slot_ref.model_dump(mode="json")["ref"] == "model.structured-extraction"


def test_resource_slot_ref_forbids_supplied_ref_field() -> None:
    with pytest.raises(ValidationError):
        ResourceSlotRef.model_validate(
            {
                "kind": ResourceSlotKind.MODEL,
                "slot": "structured-extraction",
                "label": "Structured extraction",
                "ref": "model.other",
            }
        )


def test_resource_slot_allocator_normalizes_and_deduplicates_slots() -> None:
    allocator = ResourceSlotAllocator()

    first, first_binding = allocator.allocate(
        slot_kind=ResourceSlotKind.KNOWLEDGE,
        local_kind=LocalResourceKind.COLLECTION,
        local_ref="11111111-1111-4111-8111-111111111111",
        display_name="Risk & Policy",
    )
    second, second_binding = allocator.allocate(
        slot_kind=ResourceSlotKind.KNOWLEDGE,
        local_kind=LocalResourceKind.COLLECTION,
        local_ref="22222222-2222-4222-8222-222222222222",
        display_name="Risk / Policy",
    )

    assert first.ref == "knowledge.risk-policy"
    assert second.ref == "knowledge.risk-policy-2"
    assert first_binding is not None
    assert second_binding is not None


def test_resource_slot_ref_rejects_uuid_shaped_slot() -> None:
    with pytest.raises(ValidationError):
        ResourceSlotRef(
            kind=ResourceSlotKind.MODEL,
            slot="11111111-1111-4111-8111-111111111111",
            label="UUID",
        )


def test_resource_slot_ref_rejects_uuid_shaped_slot_that_matches_slot_format() -> None:
    with pytest.raises(ValidationError, match="UUID-shaped"):
        ResourceSlotRef(
            kind=ResourceSlotKind.MODEL,
            slot="abcdef12-abcd-4abc-8def-abcdef012345",
            label="UUID",
        )


def test_uuid_shaped_resource_ref_detection_is_narrow() -> None:
    assert is_uuid_shaped_resource_ref("11111111-1111-4111-8111-111111111111")
    assert is_uuid_shaped_resource_ref("abcdef12-abcd-4abc-8def-abcdef012345")
    assert not is_uuid_shaped_resource_ref("model.structured-extraction")
    assert not is_uuid_shaped_resource_ref("model-uuid-1")


def test_slot_local_kind_pairs_match_local_binding_contract() -> None:
    assert RESOURCE_SLOT_LOCAL_KIND_PAIRS == (
        ("model", "completion_model"),
        ("model", "transcription_model"),
        ("knowledge", "collection"),
        ("knowledge", "integration_knowledge"),
        ("knowledge", "website"),
        ("mcp_server", "mcp_server"),
        ("mcp_tool", "mcp_tool"),
        ("template_asset", "template_asset"),
    )


def test_local_resource_kinds_for_slot_kind_exposes_binding_contract() -> None:
    assert local_resource_kinds_for_slot_kind(ResourceSlotKind.MODEL) == frozenset(
        {
            LocalResourceKind.COMPLETION_MODEL,
            LocalResourceKind.TRANSCRIPTION_MODEL,
        }
    )
    assert local_resource_kinds_for_slot_kind(ResourceSlotKind.MCP_TOOL) == frozenset(
        {LocalResourceKind.MCP_TOOL}
    )


def test_knowledge_local_kinds_have_assistant_update_fields() -> None:
    knowledge_local_kinds = local_resource_kinds_for_slot_kind(
        ResourceSlotKind.KNOWLEDGE
    )

    assert {
        local_kind: assistant_update_field_for_knowledge_local_kind(local_kind)
        for local_kind in knowledge_local_kinds
    } == {
        LocalResourceKind.COLLECTION: "groups",
        LocalResourceKind.WEBSITE: "websites",
        LocalResourceKind.INTEGRATION_KNOWLEDGE: "integration_knowledge_ids",
    }


def test_non_knowledge_local_kind_has_no_assistant_update_field() -> None:
    with pytest.raises(ValueError, match="cannot be applied as assistant knowledge"):
        assistant_update_field_for_knowledge_local_kind(
            LocalResourceKind.COMPLETION_MODEL
        )


def test_binding_source_values_are_canonical() -> None:
    assert FLOW_RESOURCE_BINDING_SOURCE_VALUES == (
        FlowResourceBindingSource.AI_BUILDER.value,
        FlowResourceBindingSource.PACKAGE_IMPORT.value,
        FlowResourceBindingSource.MANUAL_ADMIN.value,
    )


def test_local_resource_binding_accepts_matching_local_kind() -> None:
    slot_ref = ResourceSlotRef(
        kind=ResourceSlotKind.MODEL,
        slot="default-model",
        label="Default model",
    )
    local_id = uuid4()

    binding = LocalResourceBinding(
        slot_ref=slot_ref,
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=local_id,
    )

    assert binding.local_id == local_id


def test_local_resource_binding_rejects_mismatched_local_kind() -> None:
    slot_ref = ResourceSlotRef(
        kind=ResourceSlotKind.KNOWLEDGE,
        slot="local-policy",
        label="Local policy",
    )

    with pytest.raises(ValidationError):
        LocalResourceBinding(
            slot_ref=slot_ref,
            local_kind=LocalResourceKind.COMPLETION_MODEL,
            local_id=uuid4(),
        )


def test_resource_slot_allocator_preserves_uuid_outside_slot_ref() -> None:
    local_id = UUID("11111111-1111-4111-8111-111111111111")
    allocator = ResourceSlotAllocator()

    slot_ref, binding = allocator.allocate(
        slot_kind=ResourceSlotKind.MCP_TOOL,
        local_kind=LocalResourceKind.MCP_TOOL,
        local_ref=str(local_id),
        display_name="Case lookup",
    )

    assert binding is not None
    assert binding.local_id == local_id
    assert slot_ref.ref == "mcp_tool.case-lookup"
    assert binding.slot_ref.ref == "mcp_tool.case-lookup"


def test_resource_slot_allocator_ignores_non_uuid_local_refs() -> None:
    allocator = ResourceSlotAllocator()

    slot_ref, binding = allocator.allocate(
        slot_kind=ResourceSlotKind.MODEL,
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_ref="model-uuid-1",
        display_name="gpt-5.4",
    )

    assert slot_ref.ref == "model.gpt-5-4"
    assert binding is None


def test_resource_slot_allocator_reuses_prior_slot_for_renamed_local_target() -> None:
    local_id = UUID("11111111-1111-4111-8111-111111111111")
    prior_binding = LocalResourceBinding(
        slot_ref=ResourceSlotRef(
            kind=ResourceSlotKind.MODEL,
            slot="fast-model",
            label="Fast model",
        ),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=local_id,
    )
    allocator = ResourceSlotAllocator(prior_bindings=(prior_binding,))

    slot_ref, binding = allocator.allocate(
        slot_kind=ResourceSlotKind.MODEL,
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_ref=str(local_id),
        display_name="Renamed production model",
    )

    assert slot_ref.ref == "model.fast-model"
    assert slot_ref.label == "Renamed production model"
    assert binding is not None
    assert binding.slot_ref == slot_ref


def test_resource_slot_allocator_reuses_current_allocation_for_same_local_target() -> (
    None
):
    local_id = UUID("11111111-1111-4111-8111-111111111111")
    allocator = ResourceSlotAllocator()

    first_slot_ref, first_binding = allocator.allocate(
        slot_kind=ResourceSlotKind.MODEL,
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_ref=str(local_id),
        display_name="Shared model",
    )
    second_slot_ref, second_binding = allocator.allocate(
        slot_kind=ResourceSlotKind.MODEL,
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_ref=str(local_id),
        display_name="Shared model",
    )

    assert first_slot_ref.ref == "model.shared-model"
    assert second_slot_ref.ref == "model.shared-model"
    assert first_binding is not None
    assert second_binding is not None
    assert first_binding.local_id == second_binding.local_id == local_id


def test_resource_slot_allocator_allocates_current_slot_for_ambiguous_prior_target() -> (
    None
):
    local_id = UUID("11111111-1111-4111-8111-111111111111")
    bindings = (
        LocalResourceBinding(
            slot_ref=ResourceSlotRef(
                kind=ResourceSlotKind.MODEL,
                slot="fast-model",
                label="Fast model",
            ),
            local_kind=LocalResourceKind.COMPLETION_MODEL,
            local_id=local_id,
        ),
        LocalResourceBinding(
            slot_ref=ResourceSlotRef(
                kind=ResourceSlotKind.MODEL,
                slot="other-model",
                label="Other model",
            ),
            local_kind=LocalResourceKind.COMPLETION_MODEL,
            local_id=local_id,
        ),
    )

    allocator = ResourceSlotAllocator(prior_bindings=bindings)

    first_slot_ref, first_binding = allocator.allocate(
        slot_kind=ResourceSlotKind.MODEL,
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_ref=str(local_id),
        display_name="Shared production model",
    )
    second_slot_ref, second_binding = allocator.allocate(
        slot_kind=ResourceSlotKind.MODEL,
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_ref=str(local_id),
        display_name="Shared production model",
    )

    assert first_slot_ref.ref == "model.shared-production-model"
    assert second_slot_ref == first_slot_ref
    assert first_binding is not None
    assert second_binding is not None
    assert first_binding.slot_ref == first_slot_ref
    assert second_binding.slot_ref == first_slot_ref


def test_resource_slot_allocator_reuses_current_slot_when_ambiguous_prior_slot_name_matches_label() -> (
    None
):
    local_id = UUID("11111111-1111-4111-8111-111111111111")
    bindings = (
        LocalResourceBinding(
            slot_ref=ResourceSlotRef(
                kind=ResourceSlotKind.MODEL,
                slot="fast-model",
                label="Fast model",
            ),
            local_kind=LocalResourceKind.COMPLETION_MODEL,
            local_id=local_id,
        ),
        LocalResourceBinding(
            slot_ref=ResourceSlotRef(
                kind=ResourceSlotKind.MODEL,
                slot="other-model",
                label="Other model",
            ),
            local_kind=LocalResourceKind.COMPLETION_MODEL,
            local_id=local_id,
        ),
    )

    allocator = ResourceSlotAllocator(prior_bindings=bindings)

    slot_ref, binding = allocator.allocate(
        slot_kind=ResourceSlotKind.MODEL,
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_ref=str(local_id),
        display_name="Fast model",
    )

    assert slot_ref.ref == "model.fast-model"
    assert binding is not None
    assert binding.slot_ref == slot_ref


def test_resource_slot_ref_has_no_public_from_label_allocator_bypass() -> None:
    assert not hasattr(ResourceSlotRef, "from_label")


def test_index_local_resource_bindings_rejects_duplicate_slot_ref() -> None:
    slot_ref = ResourceSlotRef(
        kind=ResourceSlotKind.MODEL,
        slot="default-model",
        label="Default model",
    )
    bindings = [
        LocalResourceBinding(
            slot_ref=slot_ref,
            local_kind=LocalResourceKind.COMPLETION_MODEL,
            local_id=uuid4(),
        ),
        LocalResourceBinding(
            slot_ref=slot_ref,
            local_kind=LocalResourceKind.COMPLETION_MODEL,
            local_id=uuid4(),
        ),
    ]

    with pytest.raises(FlowResourceBindingResolutionError) as error:
        index_local_resource_bindings(bindings)

    assert (
        error.value.reason is FlowResourceBindingResolutionReason.DUPLICATE_SLOT_BINDING
    )
    assert error.value.context()["slot_ref"] == "model.default-model"


def test_resolve_local_resource_ref_rejects_uuid_ref() -> None:
    local_id = UUID("11111111-1111-4111-8111-111111111111")

    with pytest.raises(FlowResourceBindingResolutionError) as error:
        resolve_local_resource_ref(
            str(local_id),
            expected_slot_kind=ResourceSlotKind.MODEL,
            bindings_by_slot_ref={},
            allowed_local_kinds=frozenset({LocalResourceKind.COMPLETION_MODEL}),
        )

    assert error.value.reason is FlowResourceBindingResolutionReason.INVALID_SLOT_REF


def test_resolve_local_resource_ref_resolves_matching_slot_binding() -> None:
    local_id = uuid4()
    slot_ref = ResourceSlotRef(
        kind=ResourceSlotKind.KNOWLEDGE,
        slot="local-policy",
        label="Local policy",
    )
    binding = LocalResourceBinding(
        slot_ref=slot_ref,
        local_kind=LocalResourceKind.COLLECTION,
        local_id=local_id,
    )

    resolved = resolve_local_resource_ref(
        "knowledge.local-policy",
        expected_slot_kind=ResourceSlotKind.KNOWLEDGE,
        bindings_by_slot_ref=index_local_resource_bindings([binding]),
        allowed_local_kinds=frozenset({LocalResourceKind.COLLECTION}),
    )

    assert resolved == local_id


@pytest.mark.parametrize(
    ("resource_ref", "reason"),
    [
        ("local-policy", FlowResourceBindingResolutionReason.INVALID_SLOT_REF),
        ("model.LocalPolicy", FlowResourceBindingResolutionReason.INVALID_SLOT_REF),
        (
            "mcp_server.local-policy",
            FlowResourceBindingResolutionReason.WRONG_SLOT_KIND,
        ),
        (
            "knowledge.missing",
            FlowResourceBindingResolutionReason.UNRESOLVED_SLOT_BINDING,
        ),
    ],
)
def test_resolve_local_resource_ref_reports_slot_resolution_failures(
    resource_ref: str,
    reason: FlowResourceBindingResolutionReason,
) -> None:
    with pytest.raises(FlowResourceBindingResolutionError) as error:
        resolve_local_resource_ref(
            resource_ref,
            expected_slot_kind=ResourceSlotKind.KNOWLEDGE,
            bindings_by_slot_ref={},
            allowed_local_kinds=frozenset({LocalResourceKind.COLLECTION}),
        )

    assert error.value.reason is reason
    assert error.value.context()["expected_kind"] == ResourceSlotKind.KNOWLEDGE.value


def test_resolve_local_resource_ref_rejects_disallowed_local_kind() -> None:
    slot_ref = ResourceSlotRef(
        kind=ResourceSlotKind.MODEL,
        slot="transcription-model",
        label="Transcription model",
    )
    binding = LocalResourceBinding(
        slot_ref=slot_ref,
        local_kind=LocalResourceKind.TRANSCRIPTION_MODEL,
        local_id=uuid4(),
    )

    with pytest.raises(FlowResourceBindingResolutionError) as error:
        resolve_local_resource_ref(
            "model.transcription-model",
            expected_slot_kind=ResourceSlotKind.MODEL,
            bindings_by_slot_ref=index_local_resource_bindings([binding]),
            allowed_local_kinds=frozenset({LocalResourceKind.COMPLETION_MODEL}),
        )

    assert (
        error.value.reason is FlowResourceBindingResolutionReason.DISALLOWED_LOCAL_KIND
    )
    assert (
        error.value.context()["local_kind"]
        == LocalResourceKind.TRANSCRIPTION_MODEL.value
    )


def test_resolve_local_resource_ref_rejects_incompatible_allowed_local_kinds() -> None:
    with pytest.raises(ValueError, match="incompatible allowed local resource kinds"):
        resolve_local_resource_ref(
            "model.default-model",
            expected_slot_kind=ResourceSlotKind.MODEL,
            bindings_by_slot_ref={},
            allowed_local_kinds=frozenset({LocalResourceKind.COLLECTION}),
        )
