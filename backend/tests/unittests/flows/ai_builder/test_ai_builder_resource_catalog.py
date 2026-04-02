from __future__ import annotations

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
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
    canonicalize_assistant_spec_resources,
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
