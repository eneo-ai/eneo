"""Tests for AI Builder domain models."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.flows.ai_builder.ai_builder_api_models import SendMessageRequest
from eneo.flows.ai_builder.ai_builder_domain_models import (
    FlowBuilderProposalContent,
    PlanStatus,
    SessionStatus,
    TargetKind,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    AssistantSpecLocalRefNotPortableError,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_step(
    ref: str = "step_a",
    name: str = "Test step",
    instructions: str = "Do something",
    input_source: InputSource = InputSource.FLOW_INPUT,
    input_type: InputType = InputType.TEXT,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    output_type: OutputType = OutputType.TEXT,
    **kwargs: object,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=ref,
        name=name,
        assistant_spec=AssistantSpec(instructions=instructions),
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        **kwargs,  # type: ignore[arg-type]
    )


def _make_spec(
    steps: list[StepSpec] | None = None,
    flow_name: str = "Test flow",
) -> FlowDraftSpecCore:
    if steps is None:
        steps = [_make_step()]
    return FlowDraftSpecCore(flow_name=flow_name, steps=steps)


def _has_local_ref_not_portable_error(exc: ValidationError) -> bool:
    for error in exc.errors():
        ctx = error.get("ctx")
        if not isinstance(ctx, dict):
            continue
        if isinstance(ctx.get("error"), AssistantSpecLocalRefNotPortableError):
            return True
    return False


# ---------------------------------------------------------------------------
# FlowDraftSpecCore
# ---------------------------------------------------------------------------


class TestFlowDraftSpecCore:
    def test_minimal_valid_spec(self) -> None:
        spec = _make_spec()
        assert spec.flow_name == "Test flow"
        assert len(spec.steps) == 1
        assert spec.steps[0].plan_step_ref == "step_a"

    def test_spec_hash_deterministic(self) -> None:
        spec1 = _make_spec()
        spec2 = _make_spec()
        assert spec1.spec_hash() == spec2.spec_hash()

    def test_spec_hash_changes_with_content(self) -> None:
        spec1 = _make_spec(flow_name="Flow A")
        spec2 = _make_spec(flow_name="Flow B")
        assert spec1.spec_hash() != spec2.spec_hash()

    def test_multi_step_spec(self) -> None:
        steps = [
            _make_step(
                ref="step_a", name="Extract", input_source=InputSource.FLOW_INPUT
            ),
            _make_step(
                ref="step_b", name="Analyze", input_source=InputSource.PREVIOUS_STEP
            ),
            _make_step(
                ref="step_c",
                name="Summarize",
                input_source=InputSource.ALL_PREVIOUS_STEPS,
            ),
        ]
        spec = _make_spec(steps=steps)
        assert len(spec.steps) == 3
        assert spec.steps[2].input_source == InputSource.ALL_PREVIOUS_STEPS

    def test_step_with_all_optional_fields(self) -> None:
        step = _make_step(
            input_bindings={"question": "{{ step_a.output.text }}"},
            input_contract={"type": "object"},
            output_contract={"type": "object"},
            input_config={"runtime_input": {"enabled": True}},
            output_config={"template_asset_id": "abc"},
        )
        assert step.input_bindings is not None
        assert step.input_contract is not None

    def test_assistant_spec_with_model_and_kb(self) -> None:
        spec_obj = AssistantSpec(
            instructions="Test",
            model_ref="gpt-4",
            knowledge_refs=["kb_policy", "kb_guidelines"],
        )
        assert spec_obj.model_ref == "gpt-4"
        assert len(spec_obj.knowledge_refs) == 2

    def test_assistant_spec_normalizes_refs(self) -> None:
        spec_obj = AssistantSpec(
            instructions="Test",
            model_ref="  gpt-4o-mini  ",
            knowledge_refs=[" kb_policy ", "kb_policy", "", "kb_guidelines"],
        )
        assert spec_obj.model_ref == "gpt-4o-mini"
        assert spec_obj.knowledge_refs == ["kb_policy", "kb_guidelines"]

    @pytest.mark.parametrize("field", ["mcp_server_refs", "mcp_tool_refs"])
    def test_assistant_spec_rejects_removed_mcp_refs(self, field: str) -> None:
        with pytest.raises(ValidationError, match="Flow MCP fields are unsupported"):
            AssistantSpec.model_validate(
                {"instructions": "Test", field: ["mcp_tool.legacy"]}
            )

    def test_step_spec_rejects_removed_mcp_policy(self) -> None:
        payload = _make_step().model_dump(mode="json")
        payload["mcp_policy"] = "inherit"

        with pytest.raises(ValidationError, match="Flow MCP fields are unsupported"):
            StepSpec.model_validate(payload)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("model_ref", "11111111-1111-4111-8111-111111111111"),
            ("knowledge_refs", ["11111111-1111-4111-8111-111111111111"]),
        ],
    )
    def test_assistant_spec_rejects_uuid_shaped_resource_refs(
        self, field: str, value: str | list[str]
    ) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AssistantSpec(instructions="Test", **{field: value})

        assert _has_local_ref_not_portable_error(exc_info.value)

    def test_step_spec_strips_input_binding_question(self) -> None:
        step = _make_step(input_bindings={"question": "  {{ step_a.output.text }}  "})
        assert step.input_bindings == {"question": "{{ step_a.output.text }}"}

    def test_form_fields(self) -> None:
        from eneo.flows.flow_authoring_spec import (
            FormFieldSpec,
        )

        spec = FlowDraftSpecCore(
            flow_name="With form",
            steps=[_make_step()],
            form_fields=[
                FormFieldSpec(
                    name="company", type="text", label="Företag", required=True
                ),
                FormFieldSpec(
                    name="priority",
                    type="select",
                    label="Prioritet",
                    options=["Hög", "Medel", "Låg"],
                ),
            ],
        )
        assert spec.form_fields is not None
        assert len(spec.form_fields) == 2
        assert spec.form_fields[0].required is True

    def test_serialization_roundtrip(self) -> None:
        spec = _make_spec()
        data = spec.model_dump(mode="json")
        restored = FlowDraftSpecCore.model_validate(data)
        assert restored.spec_hash() == spec.spec_hash()


# ---------------------------------------------------------------------------
# FlowBuilderProposalContent
# ---------------------------------------------------------------------------


class TestFlowBuilderProposalContent:
    def test_wraps_spec(self) -> None:
        spec = _make_spec()
        proposal = FlowBuilderProposalContent(
            spec=spec,
            assumptions=["User wants text output"],
        )
        assert proposal.spec.flow_name == "Test flow"
        assert len(proposal.assumptions) == 1

    def test_empty_content(self) -> None:
        spec = _make_spec()
        proposal = FlowBuilderProposalContent(spec=spec)
        assert proposal.assumptions == []
        assert proposal.lint_warnings == []
        assert "risk_acknowledgments" not in type(proposal).model_fields


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_session_status_values(self) -> None:
        assert SessionStatus.CHATTING.value == "chatting"
        assert SessionStatus.AWAITING_APPROVAL.value == "awaiting_approval"
        assert SessionStatus.APPLIED.value == "applied"


class TestApiModels:
    def test_send_message_request_accepts_message_at_limit(self) -> None:
        request = SendMessageRequest(client_turn_id=uuid4(), message="x" * 50_000)
        assert len(request.message) == 50_000

    def test_send_message_request_rejects_message_above_limit(self) -> None:
        with pytest.raises(ValidationError):
            SendMessageRequest(client_turn_id=uuid4(), message="x" * 50_001)

    def test_send_message_request_accepts_bounded_retry_fields_at_limits(self) -> None:
        request = SendMessageRequest(
            client_turn_id=uuid4(),
            message="Build a flow",
            file_ids=[uuid4() for _ in range(100)],
            ui_language="x" * 16,
            question_answer={
                "kind": "structured_question_answer",
                "question_id": "q" * 128,
                "selected_option_ids": ["o" * 128 for _ in range(20)],
                "selected_values": ["v" * 500 for _ in range(20)],
                "custom_value": "c" * 500,
                "ui_language": "x" * 16,
            },
        )

        assert len(request.file_ids or []) == 100
        assert len(request.question_answer.selected_values or []) == 20

    @pytest.mark.parametrize(
        "request_fields",
        [
            {"file_ids": [uuid4() for _ in range(101)]},
            {"ui_language": "x" * 17},
            {
                "question_answer": {
                    "kind": "structured_question_answer",
                    "question_id": "q" * 129,
                    "selected_values": ["valid"],
                }
            },
            {
                "question_answer": {
                    "kind": "structured_question_answer",
                    "question_id": "question",
                    "selected_values": ["valid" for _ in range(21)],
                }
            },
            {
                "question_answer": {
                    "kind": "structured_question_answer",
                    "question_id": "question",
                    "selected_values": ["v" * 501],
                }
            },
            {
                "question_answer": {
                    "kind": "requirements_confirmation",
                    "requirements_version": "v" * 129,
                }
            },
        ],
    )
    def test_send_message_request_rejects_retry_fields_above_limits(
        self,
        request_fields: dict[str, object],
    ) -> None:
        with pytest.raises(ValidationError):
            SendMessageRequest(
                client_turn_id=uuid4(),
                message="Build a flow",
                **request_fields,
            )

    def test_plan_status_values(self) -> None:
        assert tuple(status.value for status in PlanStatus) == (
            "proposed",
            "approved",
            "applied",
            "superseded",
        )
        assert "rejected" not in {status.value for status in PlanStatus}

    def test_target_kind_values(self) -> None:
        assert TargetKind.CREATE.value == "create"
        assert TargetKind.EDIT.value == "edit"

    def test_input_source_no_http(self) -> None:
        """AI builder doesn't expose http_get/http_post sources."""
        values = {e.value for e in InputSource}
        assert "http_get" not in values
        assert "http_post" not in values
