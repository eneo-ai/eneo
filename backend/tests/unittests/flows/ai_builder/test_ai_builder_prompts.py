"""Tests for AI Builder flow context and conversation trimming."""

from __future__ import annotations

from uuid import uuid4

from eneo.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_capability_profile,
)
from eneo.flows.ai_builder.ai_builder_edit_scope import (
    EditScopeResolution,
)
from eneo.flows.ai_builder.ai_builder_flow_context import (
    build_flow_context,
    build_plan_summary,
    build_step_ref_mapping,
)
from eneo.flows.ai_builder.ai_builder_prompts import (
    trim_conversation_for_context,
)
from eneo.flows.assistant_authoring_snapshot import (
    AssistantAuthoringResourceRef,
    AssistantAuthoringSnapshot,
)
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    StepSpec,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_flow(
    *,
    name: str = "Test flow",
    description: str | None = "A test flow",
    steps: list[FlowStep] | None = None,
    published_version: int | None = None,
    draft_revision: int = 0,
    metadata_json: dict | None = None,
) -> Flow:
    return Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name=name,
        description=description,
        draft_revision=draft_revision,
        published_version=published_version,
        metadata_json=metadata_json,
        steps=steps or [],
    )


def _make_step(
    *,
    step_order: int = 1,
    user_description: str = "Test step",
    input_source: str = "flow_input",
    input_type: str = "text",
    output_mode: str = "pass_through",
    output_type: str = "text",
    mcp_policy: str = "inherit",
) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=user_description,
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        mcp_policy=mcp_policy,
    )


# ---------------------------------------------------------------------------
# Flow context
# ---------------------------------------------------------------------------


class TestBuildFlowContext:
    def test_empty_flow(self) -> None:
        flow = _make_flow(name="Nytt flöde")
        ctx = build_flow_context(flow)
        assert "Nytt flöde" in ctx
        assert "Antal steg: 0" in ctx

    def test_flow_with_steps(self) -> None:
        flow = _make_flow(
            name="Pipeline",
            steps=[
                _make_step(step_order=1, user_description="Extrahera fakta"),
                _make_step(
                    step_order=2,
                    user_description="Bedöm konsekvenser",
                    input_source="previous_step",
                ),
            ],
        )
        ctx = build_flow_context(flow)
        assert "Extrahera fakta" in ctx
        assert "Bedöm konsekvenser" in ctx
        assert "existing_step_1" in ctx


class TestBuildFlowContextDetails:
    def test_flow_with_form_fields(self) -> None:
        flow = _make_flow(
            metadata_json={
                "form_schema": {
                    "fields": [
                        {"name": "Referensnummer", "type": "text"},
                        {"name": "Prioritet", "type": "select"},
                    ]
                }
            },
        )
        ctx = build_flow_context(flow)
        assert "Referensnummer" in ctx
        assert "Prioritet" in ctx
        assert "Formulärfält" in ctx

    def test_published_flow(self) -> None:
        flow = _make_flow(published_version=3)
        ctx = build_flow_context(flow)
        assert "Ja (v3)" in ctx

    def test_draft_revision_shown(self) -> None:
        flow = _make_flow(draft_revision=5)
        ctx = build_flow_context(flow)
        assert "Draft-revision: 5" in ctx

    def test_step_without_name(self) -> None:
        flow = _make_flow(
            steps=[_make_step(step_order=1, user_description=None)],  # type: ignore[arg-type]
        )
        ctx = build_flow_context(flow)
        assert "(namnlöst)" in ctx

    def test_step_with_input_bindings(self) -> None:
        step = _make_step(step_order=1, user_description="Bedöm")
        step.input_bindings = {"question": "BAKGRUND:\n{{ step_1.output.text }}"}
        flow = _make_flow(steps=[step])
        ctx = build_flow_context(flow)
        assert "Underlag:" in ctx
        assert "{{ step_1.output.text }}" in ctx

    def test_step_with_output_contract(self) -> None:
        step = _make_step(step_order=1, user_description="Extrahera")
        step.output_contract = {
            "type": "object",
            "properties": {
                "sammanfattning": {"type": "string"},
                "risk": {"type": "string"},
            },
        }
        flow = _make_flow(steps=[step])
        ctx = build_flow_context(flow)
        assert "Utdatakontrakt:" in ctx
        assert "sammanfattning" in ctx
        assert "risk" in ctx

    def test_step_with_input_contract(self) -> None:
        step = _make_step(step_order=1, user_description="Validera")
        step.input_contract = {
            "type": "object",
            "properties": {
                "referensnummer": {"type": "string"},
                "bakgrund": {"type": "string"},
            },
        }
        flow = _make_flow(steps=[step])
        ctx = build_flow_context(flow)
        assert "Indatakontrakt:" in ctx
        assert "referensnummer" in ctx

    def test_long_bindings_are_truncated(self) -> None:
        step = _make_step(step_order=1, user_description="Steg")
        step.input_bindings = {"question": "A" * 200}
        flow = _make_flow(steps=[step])
        ctx = build_flow_context(flow)
        assert "..." in ctx

    def test_flow_context_includes_assistant_snapshots(self) -> None:
        step = _make_step(step_order=1, user_description="Analysera")
        step.output_config = {
            "bindings": {"SAMMANFATTNING": "{{ step_1.output.structured.summary }}"},
        }
        flow = _make_flow(steps=[step])
        ctx = build_flow_context(
            flow,
            assistant_snapshots={
                step.assistant_id: AssistantAuthoringSnapshot(
                    instructions="Extrahera summary, keywords och teman.",
                    model=AssistantAuthoringResourceRef(
                        local_ref="model-uuid-1",
                        label="GPT-4",
                    ),
                    knowledge_refs=(
                        AssistantAuthoringResourceRef(
                            local_ref="kb-policy",
                            label="Policy",
                        ),
                        AssistantAuthoringResourceRef(
                            local_ref="kb-archive",
                            label="Archive",
                        ),
                    ),
                )
            },
        )
        assert "Syfte:" in ctx
        assert "Extrahera summary" in ctx
        assert "Modell: GPT-4 [model-uuid-1]" in ctx
        assert "Kunskapsbaser: Policy [kb-policy], Archive [kb-archive]" in ctx
        assert "Output config" in ctx

    def test_edit_mode_flow_context_uses_structured_capability_brief(self) -> None:
        step_one = _make_step(
            step_order=1,
            user_description="Extrahera text",
            input_source="flow_input",
            input_type="file",
            output_mode="pass_through",
            output_type="text",
        )
        step_one.input_config = {"runtime_input": {"enabled": True, "max_files": 3}}
        step_one.output_config = {"citation_mode": "inline_inref_sidecar"}
        step_two = _make_step(
            step_order=2,
            user_description="Generera rapport",
            input_source="previous_step",
            input_type="text",
            output_mode="pass_through",
            output_type="pdf",
        )
        flow = _make_flow(
            name="Rapportflöde",
            steps=[step_one, step_two],
            metadata_json={
                "form_schema": {"fields": [{"name": "Referensnummer", "type": "text"}]}
            },
        )

        ctx = build_flow_context(
            flow,
            assistant_snapshots={
                step_two.assistant_id: AssistantAuthoringSnapshot(
                    instructions="",
                    knowledge_refs=(
                        AssistantAuthoringResourceRef(
                            local_ref="kb-policy",
                            label="Policy",
                        ),
                    ),
                )
            },
            is_edit_mode=True,
            capabilities=build_flow_capability_profile(flow),
            edit_scope=EditScopeResolution(
                settled_families=frozenset({"input_shape", "output_artifact"}),
                active_families=frozenset({"output_artifact"}),
                requested_output_artifact="docx_document",
            ),
        )

        assert "Flödets nuvarande profil" in ctx
        assert "Indata: dokument via steg 1" in ctx
        assert "Utdata: PDF via steg 2" in ctx
        assert "Formulär: Referensnummer" in ctx
        assert "Kunskapsbaser: steg 2 (Policy [kb-policy])" in ctx
        assert "Källhänvisningar: steg 1" in ctx
        assert "Aktiv familj: output_artifact" in ctx
        assert "Begärd ändring: PDF -> DOCX" in ctx
        assert "Draft-revision" not in ctx


# ---------------------------------------------------------------------------
# Step ref mapping
# ---------------------------------------------------------------------------


class TestStepRefMapping:
    def test_maps_step_order_to_id(self) -> None:
        step1 = _make_step(step_order=1)
        step2 = _make_step(step_order=2)
        flow = _make_flow(steps=[step1, step2])
        mapping = build_step_ref_mapping(flow)
        assert mapping["existing_step_1"] == step1.id
        assert mapping["existing_step_2"] == step2.id

    def test_empty_flow(self) -> None:
        flow = _make_flow()
        mapping = build_step_ref_mapping(flow)
        assert mapping == {}

    def test_step_without_id_skipped(self) -> None:
        step = FlowStep(
            id=None,
            assistant_id=uuid4(),
            step_order=1,
            input_source="flow_input",
            input_type="text",
            output_mode="pass_through",
            output_type="text",
            mcp_policy="inherit",
        )
        flow = _make_flow(steps=[step])
        mapping = build_step_ref_mapping(flow)
        assert mapping == {}


# ---------------------------------------------------------------------------
# Conversation trimming
# ---------------------------------------------------------------------------


class TestBuildPlanSummary:
    def test_basic_summary(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Sammanfatta dokument",
            flow_description="Extraherar och sammanfattar",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Extrahera fakta",
                    assistant_spec=AssistantSpec(instructions="Extrahera."),
                    input_source="flow_input",
                ),
            ],
        )
        summary = build_plan_summary(spec)
        assert "Sammanfatta dokument" in summary
        assert "Extrahera fakta" in summary
        assert "step_a" in summary
        assert "Antal steg: 1" in summary

    def test_summary_includes_output_contract_fields(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Pipeline",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Extrahera",
                    assistant_spec=AssistantSpec(instructions="Gör det."),
                    input_source="flow_input",
                    output_type="json",
                    output_contract={
                        "type": "object",
                        "properties": {
                            "sammanfattning": {"type": "string"},
                            "risk": {"type": "string"},
                        },
                    },
                ),
            ],
        )
        summary = build_plan_summary(spec)
        assert "sammanfattning" in summary
        assert "risk" in summary
        assert "Utdatakontrakt" in summary

    def test_summary_includes_form_fields(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Formulärflöde",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Steg 1",
                    assistant_spec=AssistantSpec(instructions="Test."),
                    input_source="flow_input",
                ),
            ],
            form_fields=[
                FormFieldSpec(name="Referensnummer", type="text", label="Ärende"),
                FormFieldSpec(name="Prioritet", type="select", label="Prio"),
            ],
        )
        summary = build_plan_summary(spec)
        assert "Referensnummer" in summary
        assert "Prioritet" in summary
        assert "Formulärfält" in summary

    def test_summary_includes_assumptions(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Test",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="S1",
                    assistant_spec=AssistantSpec(instructions="X."),
                    input_source="flow_input",
                ),
            ],
        )
        summary = build_plan_summary(spec, assumptions=["Texten är på svenska"])
        assert "Texten är på svenska" in summary
        assert "Antaganden" in summary

    def test_summary_shows_existing_step_ref(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Edit flow",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Uppdaterat steg",
                    existing_step_ref="existing_step_1",
                    assistant_spec=AssistantSpec(instructions="Ny instruktion."),
                    input_source="flow_input",
                ),
            ],
        )
        summary = build_plan_summary(spec)
        assert "existing_step_1" in summary
        assert "modifierar" in summary


class TestTrimConversation:
    def test_within_budget_unchanged(self) -> None:
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        result = trim_conversation_for_context(messages, max_tokens=999_999)
        assert len(result) == 2

    def test_over_budget_keeps_recent(self) -> None:
        messages = [
            {"role": "user", "content": f"Message {i}" + "x" * 100} for i in range(20)
        ]
        # Small budget forces trimming to only the most recent messages
        result = trim_conversation_for_context(messages, max_tokens=200)
        assert len(result) < 20
        assert result[-1]["content"].startswith("Message 19")

    def test_empty_messages(self) -> None:
        result = trim_conversation_for_context([], max_tokens=999_999)
        assert result == []

    def test_returns_new_list(self) -> None:
        messages = [{"role": "user", "content": "Test"}]
        result = trim_conversation_for_context(messages, max_tokens=999_999)
        assert result is not messages

    def test_tool_call_and_result_kept_together(self) -> None:
        """When trimming, assistant+tool_calls and tool result messages are atomic."""
        messages = [
            {"role": "user", "content": "Old message 1" + "x" * 500},
            {"role": "user", "content": "Old message 2" + "x" * 500},
            {"role": "user", "content": "Build a flow"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "propose_flow", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "content": "Plan: Test flow", "tool_call_id": "call_1"},
            {"role": "user", "content": "Change step 2"},
        ]
        # Budget that fits the tool group + last user msg but not the old messages
        result = trim_conversation_for_context(messages, max_tokens=200)
        roles = [m["role"] for m in result]
        # The assistant+tool pair should be kept together
        assert "assistant" in roles
        assert "tool" in roles
        # Tool result should follow its assistant
        assistant_idx = roles.index("assistant")
        tool_idx = roles.index("tool")
        assert tool_idx == assistant_idx + 1

    def test_tool_call_group_not_split(self) -> None:
        """Trimming should never orphan a tool result from its assistant."""
        messages = [
            {"role": "user", "content": f"Msg {i}" + "x" * 200} for i in range(8)
        ] + [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_x",
                        "type": "function",
                        "function": {"name": "propose_flow", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "content": "Plan summary", "tool_call_id": "call_x"},
            {"role": "user", "content": "Final msg"},
        ]
        result = trim_conversation_for_context(messages, max_tokens=300)
        # Should never have a tool message without its preceding assistant
        for i, msg in enumerate(result):
            if msg.get("role") == "tool":
                assert i > 0
                assert result[i - 1].get("role") == "assistant"

    def test_token_budget_trims_old_large_messages(self) -> None:
        messages = [
            {"role": "user", "content": "A" * 1200},
            {"role": "assistant", "content": "B" * 1200},
            {"role": "user", "content": "Keep me"},
            {"role": "assistant", "content": "And me"},
        ]

        result = trim_conversation_for_context(messages, max_tokens=80)

        assert [message["content"] for message in result] == ["Keep me", "And me"]

    def test_token_budget_keeps_latest_tool_call_group_atomic(self) -> None:
        messages = [
            {"role": "user", "content": "A" * 1200},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_latest",
                        "type": "function",
                        "function": {"name": "propose_flow", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "content": "Plan summary", "tool_call_id": "call_latest"},
        ]

        result = trim_conversation_for_context(messages, max_tokens=20)

        assert len(result) == 2
        assert result[0]["role"] == "assistant"
        assert result[1]["role"] == "tool"

    def test_large_budget_keeps_everything(self) -> None:
        """With a budget larger than the conversation, nothing is trimmed."""
        messages = [{"role": "user", "content": f"Message {i}"} for i in range(50)]
        result = trim_conversation_for_context(messages, max_tokens=999_999)
        assert len(result) == 50
