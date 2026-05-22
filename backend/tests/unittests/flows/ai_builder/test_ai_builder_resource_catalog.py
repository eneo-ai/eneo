from __future__ import annotations

from uuid import UUID

import pytest

from intric.flows.ai_builder.ai_builder_edit_models import (
    FlowEditDraft,
    StepEditOperation,
    StepPlacement,
)
from intric.flows.ai_builder.ai_builder_new_step_models import NewStepDraft
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    RESOURCE_DESCRIPTION_MAX_CHARS,
    AssistantSnapshotResourceUnavailableError,
    build_ai_builder_resource_catalog,
    build_ai_builder_resource_reference_material,
    canonicalize_assistant_spec_resources,
    canonicalize_edit_draft_resources,
    canonicalize_flow_spec_resources,
    collect_flow_spec_resource_bindings,
    format_resource_resolution_feedback,
)
from intric.flows.assistant_authoring_snapshot import (
    AssistantAuthoringResourceRef,
    AssistantAuthoringSnapshot,
)
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)


def _make_step_spec(*, model_ref: str | None, knowledge_refs: list[str]) -> StepSpec:
    return StepSpec(
        plan_step_ref="step_a",
        name="Analys",
        assistant_spec=AssistantSpec(
            instructions="Gör analysen.",
            model_ref=model_ref,
            knowledge_refs=knowledge_refs,
        ),
        mcp_policy=MCPPolicy.INHERIT,
        input_source=InputSource.FLOW_INPUT,
        input_type=InputType.TEXT,
        output_mode=OutputMode.PASS_THROUGH,
        output_type=OutputType.TEXT,
    )


def test_unique_resource_names_are_canonicalized_to_refs() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            {"id": "model-uuid-1", "name": "gpt-5.4-nano"},
        ],
        available_kbs=[
            {"id": "kb-uuid-1", "name": "socio"},
            {"id": "kb-uuid-2", "name": "psyk"},
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
            {"id": "model-uuid-1", "name": "gpt-5.4-nano"},
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
            {
                "id": "11111111-1111-4111-8111-111111111111",
                "name": "GPT 5.4 Mini",
            },
        ],
        available_kbs=[
            {
                "id": "22222222-2222-4222-8222-222222222222",
                "name": "Local Policy",
            },
        ],
        available_mcps=[
            {
                "id": "33333333-3333-4333-8333-333333333333",
                "name": "Case Registry",
                "tools": [
                    {
                        "id": "44444444-4444-4444-8444-444444444444",
                        "name": "lookup_case",
                    }
                ],
            }
        ],
    )

    model = catalog.models[0]
    knowledge = catalog.knowledge_bases[0]
    mcp_server = catalog.mcp_servers[0]
    mcp_tool = catalog.mcp_tools[0]

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

    assert mcp_server.local_ref == "33333333-3333-4333-8333-333333333333"
    assert mcp_server.authoring_ref == "mcp_server.case-registry"
    assert mcp_server.slot_ref.ref == "mcp_server.case-registry"
    assert mcp_server.local_binding is not None
    assert mcp_server.local_binding.local_kind is LocalResourceKind.MCP_SERVER

    assert mcp_tool.local_ref == "44444444-4444-4444-8444-444444444444"
    assert mcp_tool.authoring_ref == "mcp_tool.case-registry-lookup-case"
    assert mcp_tool.slot_ref.ref == "mcp_tool.case-registry-lookup-case"
    assert mcp_tool.local_binding is not None
    assert mcp_tool.local_binding.local_kind is LocalResourceKind.MCP_TOOL


def test_catalog_slot_refs_deduplicate_without_leaking_uuid_refs() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[
            {
                "id": "11111111-1111-4111-8111-111111111111",
                "name": "Policy",
            },
            {
                "id": "22222222-2222-4222-8222-222222222222",
                "name": "Policy",
            },
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
            {
                "id": str(local_id),
                "name": "Renamed production model",
            },
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
            {"id": str(first_id), "name": "Policy"},
            {"id": str(second_id), "name": "Local regulation"},
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
        available_models=[{"id": str(local_id), "name": "Shared production model"}],
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
        available_kbs=[{"id": str(visible_id), "name": "Policy"}],
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
            {"id": str(local_id), "name": "Renamed model"},
            {
                "id": "22222222-2222-4222-8222-222222222222",
                "name": "Renamed model",
            },
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
            {"id": "model-uuid-1", "name": "gpt-5.4-nano"},
        ],
        available_kbs=[
            {"id": "kb-uuid-1", "name": "Policy"},
        ],
    )

    assert catalog.small_ref_enum_for_kind("model") == ["model.gpt-5-4-nano"]
    assert catalog.small_ref_enum_for_kind("knowledge_base") == ["knowledge.policy"]


def test_collect_flow_spec_resource_bindings_uses_only_normalized_spec_refs() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            {
                "id": "11111111-1111-4111-8111-111111111111",
                "name": "Model A",
            },
            {
                "id": "22222222-2222-4222-8222-222222222222",
                "name": "Unused Model",
            },
        ],
        available_kbs=[
            {
                "id": "33333333-3333-4333-8333-333333333333",
                "name": "Policy",
            },
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
            {
                "id": "11111111-1111-4111-8111-111111111111",
                "name": "Model A",
            },
            {
                "id": "22222222-2222-4222-8222-222222222222",
                "name": "Model B",
            },
        ],
        available_kbs=[
            {
                "id": "33333333-3333-4333-8333-333333333333",
                "name": "Policy",
            },
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
            {
                "id": "non-uuid-model-ref",
                "name": "Local test model",
            },
        ],
        available_kbs=[
            {
                "id": "33333333-3333-4333-8333-333333333333",
                "name": "Policy",
            },
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
            {"id": "kb-uuid-1", "name": "Psyk"},
            {"id": "kb-uuid-2", "name": "psyk"},
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
            {"id": "model-uuid-1", "name": "gpt-5.4-nano"},
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
            {"id": "11111111-1111-4111-8111-111111111111", "name": "GPT"},
        ],
        available_kbs=[
            {"id": "22222222-2222-4222-8222-222222222222", "name": "Policy"},
        ],
        available_mcps=[
            {
                "id": "33333333-3333-4333-8333-333333333333",
                "name": "Case system",
                "tools": [
                    {
                        "id": "44444444-4444-4444-8444-444444444444",
                        "name": "lookup_case",
                    },
                ],
            }
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
    mcp_assistant_spec = catalog.assistant_spec_from_snapshot(
        AssistantAuthoringSnapshot(
            instructions="Använd lokala resurser.",
            model=AssistantAuthoringResourceRef(
                local_ref="11111111-1111-4111-8111-111111111111",
                label="GPT",
            ),
            mcp_server_refs=(
                AssistantAuthoringResourceRef(
                    local_ref="33333333-3333-4333-8333-333333333333",
                    label="Case system",
                ),
            ),
            mcp_tool_refs=(
                AssistantAuthoringResourceRef(
                    local_ref="44444444-4444-4444-8444-444444444444",
                    label="lookup_case",
                ),
            ),
        )
    )

    assert knowledge_assistant_spec.model_ref == "model.gpt"
    assert knowledge_assistant_spec.knowledge_refs == ["knowledge.policy"]
    assert mcp_assistant_spec.model_ref == "model.gpt"
    assert mcp_assistant_spec.mcp_server_refs == ["mcp_server.case-system"]
    assert mcp_assistant_spec.mcp_tool_refs == ["mcp_tool.case-system-lookup-case"]


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


def test_mcp_tool_alias_adds_parent_server_without_enabling_sibling_tools() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "server-uuid-1",
                "name": "Ärendesystem",
                "tools": [
                    {"id": "tool-uuid-1", "name": "lookup_case"},
                    {"id": "tool-uuid-2", "name": "delete_case"},
                ],
            }
        ],
    )

    assistant_spec, issues = canonicalize_assistant_spec_resources(
        AssistantSpec(
            instructions="Hämta aktuell ärendedata.",
            mcp_tool_refs=["lookup_case"],
        ),
        catalog=catalog,
        location_prefix="step 'step_a'",
    )

    assert issues == []
    assert assistant_spec.mcp_server_refs == ["mcp_server.rendesystem"]
    assert assistant_spec.mcp_tool_refs == ["mcp_tool.rendesystem-lookup-case"]


def test_edit_add_payload_canonicalizes_mcp_tool_refs() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "server-uuid-1",
                "name": "Ärendesystem",
                "tools": [
                    {"id": "tool-uuid-1", "name": "lookup_case"},
                    {"id": "tool-uuid-2", "name": "delete_case"},
                ],
            }
        ],
    )
    draft = FlowEditDraft(
        operations=[
            StepEditOperation(
                op="add",
                placement=StepPlacement(position="append"),
                add_payload=NewStepDraft(
                    name="Hämta ärende",
                    instructions="Hämta aktuell ärendedata med valt MCP-verktyg.",
                    input_source=InputSource.FLOW_INPUT,
                    mcp_tool_refs=["lookup_case"],
                ),
            )
        ],
        plan_rationale="Lägg till ett steg för live-data.",
    )

    canonicalized, issues = canonicalize_edit_draft_resources(
        draft,
        catalog=catalog,
    )

    assert issues == []
    add_payload = canonicalized.operations[0].add_payload
    assert add_payload is not None
    assert add_payload.mcp_server_refs == ["mcp_server.rendesystem"]
    assert add_payload.mcp_tool_refs == ["mcp_tool.rendesystem-lookup-case"]


def test_mcp_server_ref_expands_to_enabled_server_tools() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "server-uuid-1",
                "name": "Ärendesystem",
                "tools": [
                    {"id": "tool-uuid-1", "name": "lookup_case"},
                    {"id": "tool-uuid-2", "name": "list_cases"},
                ],
            }
        ],
    )

    assistant_spec, issues = canonicalize_assistant_spec_resources(
        AssistantSpec(
            instructions="Använd ärendesystemet.",
            mcp_server_refs=["Ärendesystem"],
        ),
        catalog=catalog,
        location_prefix="step 'step_a'",
    )

    assert issues == []
    assert assistant_spec.mcp_server_refs == ["mcp_server.rendesystem"]
    assert assistant_spec.mcp_tool_refs == [
        "mcp_tool.rendesystem-lookup-case",
        "mcp_tool.rendesystem-list-cases",
    ]


def test_catalog_detects_explicit_resource_alias_mentions_with_boundaries() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "tools": [
                    {"id": "current-time", "name": "get_current_time"},
                    {"id": "convert-time", "name": "convert_time"},
                ],
            }
        ],
    )

    assert catalog.refs_mentioned_in_text(
        kind="mcp_server",
        text="Hämta aktuell tid med Time MCP.",
    ) == frozenset({"mcp_server.time-mcp"})
    assert catalog.refs_mentioned_in_text(
        kind="mcp_tool",
        text="Använd get_current_time och convert_time i detta steg.",
    ) == frozenset(
        {
            "mcp_tool.time-mcp-get-current-time",
            "mcp_tool.time-mcp-convert-time",
        }
    )
    assert (
        catalog.refs_mentioned_in_text(
            kind="mcp_server",
            text="Runtime-input ska anges manuellt.",
        )
        == frozenset()
    )


def test_catalog_prefers_longest_overlapping_model_alias_mention() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            {"id": "model-base", "name": "gpt-5.4"},
            {"id": "model-nano", "name": "gpt-5.4-nano"},
        ],
        available_kbs=[],
        available_mcps=[],
    )

    assert catalog.refs_mentioned_in_text(
        kind="model",
        text="Ändra modell till gpt 5.4 nano.",
    ) == frozenset({"model.gpt-5-4-nano"})
    assert catalog.refs_mentioned_in_text(
        kind="model",
        text="Jämför gpt 5.4 och gpt 5.4 nano.",
    ) == frozenset({"model.gpt-5-4", "model.gpt-5-4-nano"})


def test_unknown_mcp_tool_alias_returns_typed_issue() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "server-uuid-1",
                "name": "Ärendesystem",
                "tools": [{"id": "tool-uuid-1", "name": "lookup_case"}],
            }
        ],
    )

    assistant_spec, issues = canonicalize_assistant_spec_resources(
        AssistantSpec(
            instructions="Hämta aktuell ärendedata.",
            mcp_tool_refs=["missing_tool"],
        ),
        catalog=catalog,
        location_prefix="step 'step_a'",
    )

    assert assistant_spec.mcp_tool_refs == []
    assert len(issues) == 1
    assert issues[0].code == "unknown_mcp_tool_ref"
    assert "MCP tool" in format_resource_resolution_feedback(issues)


def test_malformed_mcp_resources_do_not_enter_catalog() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {"ref": "", "name": "No ref", "tools": [{"ref": "tool-ignored"}]},
            {
                "ref": "server-uuid-1",
                "name": "Ärendesystem",
                "tools": [
                    {"ref": "", "name": "empty"},
                    {"ref": " ", "name": "blank"},
                    {"ref": "tool-uuid-1", "name": "lookup_case"},
                ],
            },
        ],
    )

    assert catalog.mcp_server_refs == {"mcp_server.rendesystem"}
    assert catalog.mcp_tool_refs == {"mcp_tool.rendesystem-lookup-case"}


def test_resource_reference_material_uses_catalog_refs_and_selected_mcp_tools() -> None:
    long_description = "x" * (RESOURCE_DESCRIPTION_MAX_CHARS + 20)
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            {"id": "model-uuid-1", "name": "gpt-5.4-nano"},
        ],
        available_kbs=[
            {
                "id": "kb-uuid-1",
                "name": "Risk KB",
                "description": long_description,
            },
        ],
        available_mcps=[
            {
                "id": "server-uuid-1",
                "name": "Ärendesystem",
                "description": "Läser ärendedata.",
                "tools": [
                    {
                        "id": "tool-uuid-1",
                        "name": "lookup_case",
                        "description": "Hämtar ett ärende.",
                    },
                    {"id": "", "name": "ignored"},
                ],
            },
            {"id": "", "name": "ignored", "tools": [{"id": "ignored-tool"}]},
        ],
    )

    material = build_ai_builder_resource_reference_material(
        catalog=catalog,
        selected_mcp_server_refs={"mcp_server.rendesystem"},
    )

    assert material.models[0].ref == "model.gpt-5-4-nano"
    assert material.models[0].display_name == "gpt-5.4-nano"
    assert material.knowledge_bases[0].ref == "knowledge.risk-kb"
    assert (
        len(material.knowledge_bases[0].description) == RESOURCE_DESCRIPTION_MAX_CHARS
    )
    assert material.knowledge_bases[0].description.endswith("...")
    assert material.mcp_servers[0].ref == "mcp_server.rendesystem"
    assert material.mcp_tools[0].ref == "mcp_tool.rendesystem-lookup-case"
    assert material.mcp_tools[0].parent_ref == "mcp_server.rendesystem"
    assert material.selected_mcp_servers == material.mcp_servers
    assert material.selected_mcp_tools == material.mcp_tools


def test_resource_reference_material_keeps_description_at_clamp_boundary() -> None:
    description = "x" * RESOURCE_DESCRIPTION_MAX_CHARS
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[
            {"id": "kb-uuid-1", "name": "Risk KB", "description": description},
        ],
    )

    material = build_ai_builder_resource_reference_material(catalog=catalog)

    assert material.knowledge_bases[0].description == description
