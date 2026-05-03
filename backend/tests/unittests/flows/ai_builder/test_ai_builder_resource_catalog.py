from __future__ import annotations

from intric.flows.ai_builder.ai_builder_edit_models import (
    FlowEditDraft,
    StepEditOperation,
    StepPlacement,
)
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_new_step_models import NewStepDraft
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    RESOURCE_DESCRIPTION_MAX_CHARS,
    build_ai_builder_resource_catalog,
    build_ai_builder_resource_reference_material,
    canonicalize_assistant_spec_resources,
    canonicalize_edit_draft_resources,
    canonicalize_flow_spec_resources,
    format_resource_resolution_feedback,
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
    assert assistant_spec.model_ref == "model-uuid-1"
    assert assistant_spec.knowledge_refs == ["kb-uuid-1", "kb-uuid-2"]


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
    assert "kb-uuid-1" in format_resource_resolution_feedback(issues)


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
    assert assistant_spec.mcp_server_refs == ["server-uuid-1"]
    assert assistant_spec.mcp_tool_refs == ["tool-uuid-1"]


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
    assert add_payload.mcp_server_refs == ["server-uuid-1"]
    assert add_payload.mcp_tool_refs == ["tool-uuid-1"]


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
    assert assistant_spec.mcp_server_refs == ["server-uuid-1"]
    assert assistant_spec.mcp_tool_refs == ["tool-uuid-1", "tool-uuid-2"]


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
    ) == frozenset({"time-server"})
    assert catalog.refs_mentioned_in_text(
        kind="mcp_tool",
        text="Använd get_current_time och convert_time i detta steg.",
    ) == frozenset({"current-time", "convert-time"})
    assert (
        catalog.refs_mentioned_in_text(
            kind="mcp_server",
            text="Runtime-input ska anges manuellt.",
        )
        == frozenset()
    )


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

    assert catalog.mcp_server_refs == {"server-uuid-1"}
    assert catalog.mcp_tool_refs == {"tool-uuid-1"}


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
        selected_mcp_server_refs={"server-uuid-1"},
    )

    assert material.models[0].ref == "model-uuid-1"
    assert material.models[0].display_name == "gpt-5.4-nano"
    assert material.knowledge_bases[0].ref == "kb-uuid-1"
    assert (
        len(material.knowledge_bases[0].description) == RESOURCE_DESCRIPTION_MAX_CHARS
    )
    assert material.knowledge_bases[0].description.endswith("...")
    assert material.mcp_servers[0].ref == "server-uuid-1"
    assert material.mcp_tools[0].ref == "tool-uuid-1"
    assert material.mcp_tools[0].parent_ref == "server-uuid-1"
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
