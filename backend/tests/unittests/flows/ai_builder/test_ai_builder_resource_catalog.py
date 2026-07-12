from __future__ import annotations

from uuid import UUID

import pytest

from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    RESOURCE_DESCRIPTION_MAX_CHARS,
    AIBuilderAvailableKnowledgeBaseResource,
    AIBuilderAvailableModelResource,
    AIBuilderResourceReferenceMaterial,
    AssistantSnapshotResourceUnavailableError,
    build_ai_builder_resource_catalog,
    build_ai_builder_resource_reference_material,
    canonicalize_assistant_spec_resources,
    canonicalize_flow_spec_resources,
    collect_flow_spec_resource_bindings,
    format_resource_resolution_feedback,
    render_resource_reference_block,
)
from eneo.flows.assistant_authoring_snapshot import (
    AssistantAuthoringResourceRef,
    AssistantAuthoringSnapshot,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)


def _model_resource(
    local_id: str,
    name: str,
    *,
    display_name: str | None = None,
    provider: str = "test",
) -> AIBuilderAvailableModelResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": display_name or name,
        "provider": provider,
    }


def _kb_resource(
    local_id: str,
    name: str,
    *,
    display_name: str | None = None,
    description: str = "",
) -> AIBuilderAvailableKnowledgeBaseResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": display_name or name,
        "description": description,
    }


def _make_step_spec(*, model_ref: str | None, knowledge_refs: list[str]) -> StepSpec:
    return StepSpec(
        plan_step_ref="step_a",
        name="Analys",
        assistant_spec=AssistantSpec(
            instructions="Gör analysen.",
            model_ref=model_ref,
            knowledge_refs=knowledge_refs,
        ),
        input_source=InputSource.FLOW_INPUT,
        input_type=InputType.TEXT,
        output_mode=OutputMode.PASS_THROUGH,
        output_type=OutputType.TEXT,
    )


def test_unique_resource_names_are_canonicalized_to_refs() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("model-uuid-1", "gpt-5.4-nano"),
        ],
        available_kbs=[
            _kb_resource("kb-uuid-1", "socio"),
            _kb_resource("kb-uuid-2", "psyk"),
        ],
    )
    spec = FlowDraftSpecCore(
        flow_name="Flow",
        flow_description="Desc",
        steps=[
            _make_step_spec(
                model_ref="gpt-5.4-nano",
                knowledge_refs=["socio", "psyk"],
            )
        ],
    )

    normalized, issues = canonicalize_flow_spec_resources(spec, catalog=catalog)

    assert issues == []
    assistant_spec = normalized.steps[0].assistant_spec
    assert assistant_spec.model_ref == "model.gpt-5-4-nano"
    assert assistant_spec.knowledge_refs == ["knowledge.socio", "knowledge.psyk"]


def test_local_resource_ids_are_not_authoring_aliases() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("model-uuid-1", "gpt-5.4-nano"),
        ],
        available_kbs=[],
    )

    resolved, issue = catalog.resolve(
        kind="model",
        value="model-uuid-1",
        location="test",
    )

    assert resolved is None
    assert issue is not None
    assert issue.code == "unknown_model_ref"


def test_catalog_entries_expose_portable_slot_refs_without_changing_local_refs() -> (
    None
):
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource(
                "11111111-1111-4111-8111-111111111111",
                "GPT 5.4 Mini",
            ),
        ],
        available_kbs=[
            _kb_resource(
                "22222222-2222-4222-8222-222222222222",
                "Local Policy",
            ),
        ],
    )

    model = catalog.models[0]
    knowledge = catalog.knowledge_bases[0]

    assert model.local_ref == "11111111-1111-4111-8111-111111111111"
    assert model.authoring_ref == "model.gpt-5-4-mini"
    assert model.slot_ref.kind is ResourceSlotKind.MODEL
    assert model.slot_ref.ref == "model.gpt-5-4-mini"
    assert model.local_binding is not None
    assert model.local_binding.local_kind is LocalResourceKind.COMPLETION_MODEL

    assert knowledge.local_ref == "22222222-2222-4222-8222-222222222222"
    assert knowledge.authoring_ref == "knowledge.local-policy"
    assert knowledge.slot_ref.ref == "knowledge.local-policy"
    assert knowledge.local_binding is not None
    assert knowledge.local_binding.local_kind is LocalResourceKind.COLLECTION


def test_catalog_slot_refs_deduplicate_without_leaking_uuid_refs() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[
            _kb_resource("11111111-1111-4111-8111-111111111111", "Policy"),
            _kb_resource("22222222-2222-4222-8222-222222222222", "Policy"),
        ],
    )

    assert [entry.local_ref for entry in catalog.knowledge_bases] == [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]
    assert [entry.slot_ref.ref for entry in catalog.knowledge_bases] == [
        "knowledge.policy",
        "knowledge.policy-2",
    ]


def test_catalog_reuses_prior_slot_for_renamed_resource() -> None:
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

    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource(str(local_id), "Renamed production model"),
        ],
        available_kbs=[],
        prior_bindings=(prior_binding,),
    )

    model = catalog.models[0]
    assert model.local_ref == str(local_id)
    assert model.authoring_ref == "model.fast-model"
    assert model.slot_ref.label == "Renamed production model"
    assert model.local_binding is not None
    assert model.local_binding.slot_ref.ref == "model.fast-model"


def test_catalog_keeps_prior_suffix_when_collision_disappears_after_rename() -> None:
    first_id = UUID("11111111-1111-4111-8111-111111111111")
    second_id = UUID("22222222-2222-4222-8222-222222222222")
    prior_bindings = (
        LocalResourceBinding(
            slot_ref=ResourceSlotRef(
                kind=ResourceSlotKind.KNOWLEDGE,
                slot="policy",
                label="Policy",
            ),
            local_kind=LocalResourceKind.COLLECTION,
            local_id=first_id,
        ),
        LocalResourceBinding(
            slot_ref=ResourceSlotRef(
                kind=ResourceSlotKind.KNOWLEDGE,
                slot="policy-2",
                label="Policy",
            ),
            local_kind=LocalResourceKind.COLLECTION,
            local_id=second_id,
        ),
    )

    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[
            _kb_resource(str(first_id), "Policy"),
            _kb_resource(str(second_id), "Local regulation"),
        ],
        prior_bindings=prior_bindings,
    )

    assert [entry.authoring_ref for entry in catalog.knowledge_bases] == [
        "knowledge.policy",
        "knowledge.policy-2",
    ]
    assert catalog.knowledge_bases[1].slot_ref.label == "Local regulation"


def test_catalog_allocates_current_ref_when_prior_slots_share_one_local_target() -> (
    None
):
    local_id = UUID("11111111-1111-4111-8111-111111111111")
    prior_bindings = (
        LocalResourceBinding(
            slot_ref=ResourceSlotRef(
                kind=ResourceSlotKind.MODEL,
                slot="source-model-a",
                label="Source model A",
            ),
            local_kind=LocalResourceKind.COMPLETION_MODEL,
            local_id=local_id,
        ),
        LocalResourceBinding(
            slot_ref=ResourceSlotRef(
                kind=ResourceSlotKind.MODEL,
                slot="source-model-b",
                label="Source model B",
            ),
            local_kind=LocalResourceKind.COMPLETION_MODEL,
            local_id=local_id,
        ),
    )

    catalog = build_ai_builder_resource_catalog(
        available_models=[_model_resource(str(local_id), "Shared production model")],
        available_kbs=[],
        prior_bindings=prior_bindings,
    )

    assert [entry.authoring_ref for entry in catalog.models] == [
        "model.shared-production-model"
    ]
    assert catalog.models[0].local_binding is not None
    assert (
        catalog.models[0].local_binding.slot_ref.ref == "model.shared-production-model"
    )


def test_catalog_uses_invisible_prior_bindings_only_as_slot_seeds() -> None:
    missing_id = UUID("11111111-1111-4111-8111-111111111111")
    visible_id = UUID("22222222-2222-4222-8222-222222222222")
    prior_binding = LocalResourceBinding(
        slot_ref=ResourceSlotRef(
            kind=ResourceSlotKind.KNOWLEDGE,
            slot="policy",
            label="Policy",
        ),
        local_kind=LocalResourceKind.COLLECTION,
        local_id=missing_id,
    )

    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[_kb_resource(str(visible_id), "Policy")],
        prior_bindings=(prior_binding,),
    )

    assert [entry.local_ref for entry in catalog.knowledge_bases] == [str(visible_id)]
    assert [entry.authoring_ref for entry in catalog.knowledge_bases] == [
        "knowledge.policy-2"
    ]


def test_catalog_slot_allocation_is_deterministic_for_identical_inputs() -> None:
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
    kwargs = {
        "available_models": [
            _model_resource(str(local_id), "Renamed model"),
            _model_resource(
                "22222222-2222-4222-8222-222222222222",
                "Renamed model",
            ),
        ],
        "available_kbs": [],
        "prior_bindings": (prior_binding,),
    }

    first = build_ai_builder_resource_catalog(**kwargs)
    second = build_ai_builder_resource_catalog(**kwargs)

    assert [entry.authoring_ref for entry in first.models] == [
        entry.authoring_ref for entry in second.models
    ]


def test_catalog_owns_small_ref_enums() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("model-uuid-1", "gpt-5.4-nano"),
        ],
        available_kbs=[
            _kb_resource("kb-uuid-1", "Policy"),
        ],
    )

    assert catalog.small_ref_enum_for_kind("model") == ["model.gpt-5-4-nano"]
    assert catalog.small_ref_enum_for_kind("knowledge_base") == ["knowledge.policy"]


def test_collect_flow_spec_resource_bindings_uses_only_normalized_spec_refs() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("11111111-1111-4111-8111-111111111111", "Model A"),
            _model_resource(
                "22222222-2222-4222-8222-222222222222",
                "Unused Model",
            ),
        ],
        available_kbs=[
            _kb_resource("33333333-3333-4333-8333-333333333333", "Policy"),
        ],
    )
    spec = FlowDraftSpecCore(
        flow_name="Flow",
        steps=[
            _make_step_spec(
                model_ref="model.model-a",
                knowledge_refs=[],
            ),
            _make_step_spec(
                model_ref="model.model-a",
                knowledge_refs=[],
            ),
        ],
    )

    bindings = collect_flow_spec_resource_bindings(spec, catalog=catalog)

    assert len(bindings) == 1
    assert bindings[0].slot_ref.ref == "model.model-a"
    assert bindings[0].local_kind is LocalResourceKind.COMPLETION_MODEL


def test_collect_flow_spec_resource_bindings_is_derived_from_current_spec() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("11111111-1111-4111-8111-111111111111", "Model A"),
            _model_resource("22222222-2222-4222-8222-222222222222", "Model B"),
        ],
        available_kbs=[
            _kb_resource("33333333-3333-4333-8333-333333333333", "Policy"),
        ],
    )
    first_spec = FlowDraftSpecCore(
        flow_name="Flow",
        steps=[
            _make_step_spec(
                model_ref="model.model-a",
                knowledge_refs=["knowledge.policy"],
            )
        ],
    )
    revised_spec = FlowDraftSpecCore(
        flow_name="Flow",
        steps=[
            _make_step_spec(
                model_ref="model.model-b",
                knowledge_refs=[],
            )
        ],
    )

    first_bindings = collect_flow_spec_resource_bindings(first_spec, catalog=catalog)
    revised_bindings = collect_flow_spec_resource_bindings(
        revised_spec,
        catalog=catalog,
    )

    assert {binding.slot_ref.ref for binding in first_bindings} == {
        "model.model-a",
        "knowledge.policy",
    }
    assert {binding.slot_ref.ref for binding in revised_bindings} == {
        "model.model-b",
    }


def test_collect_flow_spec_resource_bindings_skips_unbound_or_unknown_refs() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("non-uuid-model-ref", "Local test model"),
        ],
        available_kbs=[
            _kb_resource("33333333-3333-4333-8333-333333333333", "Policy"),
        ],
    )
    spec = FlowDraftSpecCore(
        flow_name="Flow",
        steps=[
            _make_step_spec(
                model_ref="non-uuid-model-ref",
                knowledge_refs=["missing-kb-ref"],
            )
        ],
    )

    assert collect_flow_spec_resource_bindings(spec, catalog=catalog) == tuple()


def test_ambiguous_resource_alias_returns_typed_issue() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[
            _kb_resource("kb-uuid-1", "Psyk"),
            _kb_resource("kb-uuid-2", "psyk"),
        ],
    )

    assistant_spec, issues = canonicalize_assistant_spec_resources(
        AssistantSpec(
            instructions="Gör analysen.",
            knowledge_refs=["psyk"],
        ),
        catalog=catalog,
        location_prefix="step 'step_a'",
    )

    assert assistant_spec.knowledge_refs == []
    assert len(issues) == 1
    assert issues[0].code == "ambiguous_kb_ref"
    assert issues[0].provided_value == "psyk"
    assert "knowledge.psyk" in format_resource_resolution_feedback(issues)


def test_unknown_model_alias_returns_typed_issue() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("model-uuid-1", "gpt-5.4-nano"),
        ],
        available_kbs=[],
    )

    assistant_spec, issues = canonicalize_assistant_spec_resources(
        AssistantSpec(
            instructions="Gör analysen.",
            model_ref="nano-fast",
        ),
        catalog=catalog,
        location_prefix="step 'step_a'",
    )

    assert assistant_spec.model_ref is None
    assert len(issues) == 1
    assert issues[0].code == "unknown_model_ref"
    assert issues[0].provided_value == "nano-fast"


def test_assistant_snapshot_translates_local_refs_to_authoring_slot_refs() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("11111111-1111-4111-8111-111111111111", "GPT"),
        ],
        available_kbs=[
            _kb_resource("22222222-2222-4222-8222-222222222222", "Policy"),
        ],
    )

    knowledge_assistant_spec = catalog.assistant_spec_from_snapshot(
        AssistantAuthoringSnapshot(
            instructions="Använd lokala resurser.",
            model=AssistantAuthoringResourceRef(
                local_ref="11111111-1111-4111-8111-111111111111",
                label="GPT",
            ),
            knowledge_refs=(
                AssistantAuthoringResourceRef(
                    local_ref="22222222-2222-4222-8222-222222222222",
                    label="Policy",
                ),
            ),
        )
    )
    assert knowledge_assistant_spec.model_ref == "model.gpt"
    assert knowledge_assistant_spec.knowledge_refs == ["knowledge.policy"]


def test_assistant_snapshot_rejects_unavailable_local_resource() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
    )

    with pytest.raises(AssistantSnapshotResourceUnavailableError) as exc_info:
        catalog.assistant_spec_from_snapshot(
            AssistantAuthoringSnapshot(
                instructions="Använd lokala resurser.",
                knowledge_refs=(
                    AssistantAuthoringResourceRef(
                        local_ref="22222222-2222-4222-8222-222222222222",
                        label="Sensitive policy name",
                    ),
                ),
            )
        )

    assert exc_info.value.kind == "knowledge_base"
    assert exc_info.value.local_ref == "22222222-2222-4222-8222-222222222222"
    assert str(exc_info.value) == (
        "Assistant snapshot references an unavailable knowledge_base resource."
    )
    assert "Sensitive policy name" not in str(exc_info.value)


def test_catalog_prefers_longest_overlapping_model_alias_mention() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("model-base", "gpt-5.4"),
            _model_resource("model-nano", "gpt-5.4-nano"),
        ],
        available_kbs=[],
    )

    assert catalog.refs_mentioned_in_text(
        kind="model",
        text="Ändra modell till gpt 5.4 nano.",
    ) == frozenset({"model.gpt-5-4-nano"})
    assert catalog.refs_mentioned_in_text(
        kind="model",
        text="Jämför gpt 5.4 och gpt 5.4 nano.",
    ) == frozenset({"model.gpt-5-4", "model.gpt-5-4-nano"})


def test_resource_reference_material_keeps_description_at_clamp_boundary() -> None:
    description = "x" * RESOURCE_DESCRIPTION_MAX_CHARS
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[
            _kb_resource("kb-uuid-1", "Risk KB", description=description),
        ],
    )

    material = build_ai_builder_resource_reference_material(catalog=catalog)

    assert material.knowledge_bases[0].description == description


def _reference_material(
    *,
    model_count: int = 0,
    kb_count: int = 0,
) -> AIBuilderResourceReferenceMaterial:
    def _uuid(group: int, index: int) -> str:
        return f"{group:08d}-{index:04d}-4000-8000-000000000000"

    models = [_model_resource(_uuid(1, i), f"Model {i}") for i in range(model_count)]
    kbs = [_kb_resource(_uuid(2, i), f"Knowledge {i}") for i in range(kb_count)]
    catalog = build_ai_builder_resource_catalog(
        available_models=models or None,
        available_kbs=kbs or None,
    )
    return build_ai_builder_resource_reference_material(catalog=catalog)


class TestRenderResourceReferenceBlock:
    def test_renders_every_resource_ref(self) -> None:
        material = _reference_material(model_count=2, kb_count=2)

        rendered = render_resource_reference_block(material)

        assert "model.model-0" in rendered.models
        assert "model.model-1" in rendered.models
        assert "knowledge.knowledge-0" in rendered.knowledge_bases
        assert "knowledge.knowledge-1" in rendered.knowledge_bases
