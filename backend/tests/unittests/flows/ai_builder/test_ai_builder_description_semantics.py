"""Tests for AI Builder description semantic signatures."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.flows.application.flow_authoring_description_semantics import (
    FlowSemanticSignature,
)
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)


def _step(
    *,
    input_source: InputSource = InputSource.FLOW_INPUT,
    input_type: InputType = InputType.TEXT,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    output_type: OutputType = OutputType.TEXT,
) -> StepSpec:
    return StepSpec(
        plan_step_ref="step_a",
        name="Test",
        assistant_spec=AssistantSpec(instructions="Do."),
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
    )


class TestFlowSemanticSignature:
    def test_from_steps_empty(self) -> None:
        sig = FlowSemanticSignature.from_steps([])
        assert sig.entry_input_type is None
        assert sig.entry_input_source is None
        assert sig.terminal_output_type is None
        assert sig.terminal_output_mode is None

    def test_from_steps_single(self) -> None:
        steps = [
            _step(
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                output_type=OutputType.TEXT,
            )
        ]
        sig = FlowSemanticSignature.from_steps(steps)
        assert sig.entry_input_type == "audio"
        assert sig.entry_input_source == "flow_input"
        assert sig.terminal_output_type == "text"
        assert sig.terminal_output_mode == "transcribe_only"

    def test_from_steps_multi(self) -> None:
        steps = [
            _step(
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.DOCUMENT,
            ),
            _step(
                input_source=InputSource.PREVIOUS_STEP,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.PDF,
            ),
        ]
        sig = FlowSemanticSignature.from_steps(steps)
        assert sig.entry_input_type == "document"
        assert sig.entry_input_source == "flow_input"
        assert sig.terminal_output_type == "pdf"
        assert sig.terminal_output_mode == "pass_through"

    def test_from_flow_steps_coerces_current_flow_vocabulary(self) -> None:
        sig = FlowSemanticSignature.from_flow_steps(
            [
                _flow_step(
                    step_order=1,
                    input_source="all_previous_steps",
                    input_type="json",
                    output_mode="pass_through",
                    output_type="text",
                ),
                _flow_step(
                    step_order=2,
                    input_source="previous_step",
                    input_type="text",
                    output_mode="template_fill",
                    output_type="docx",
                ),
            ]
        )

        assert sig.entry_input_source == "all_previous_steps"
        assert sig.entry_input_type == "json"
        assert sig.terminal_output_mode == "template_fill"
        assert sig.terminal_output_type == "docx"

    def test_from_flow_steps_rejects_unsupported_middle_step_vocabulary(self) -> None:
        with pytest.raises(ValueError):
            FlowSemanticSignature.from_flow_steps(
                [
                    _flow_step(step_order=1, input_source="flow_input"),
                    _flow_step(step_order=2, input_source="http_get"),
                    _flow_step(step_order=3, input_source="previous_step"),
                ]
            )

    def test_has_semantic_change_detects_input_type_change(self) -> None:
        old = FlowSemanticSignature(
            entry_input_type="audio",
            entry_input_source="flow_input",
            terminal_output_type="text",
            terminal_output_mode="transcribe_only",
        )
        new = FlowSemanticSignature(
            entry_input_type="document",
            entry_input_source="flow_input",
            terminal_output_type="text",
            terminal_output_mode="pass_through",
        )
        assert old.has_semantic_change(new) is True

    def test_has_semantic_change_no_change(self) -> None:
        sig = FlowSemanticSignature(
            entry_input_type="text",
            entry_input_source="flow_input",
            terminal_output_type="pdf",
            terminal_output_mode="pass_through",
        )
        assert sig.has_semantic_change(sig) is False

    def test_has_semantic_change_output_change(self) -> None:
        old = FlowSemanticSignature(
            entry_input_type="text",
            entry_input_source="flow_input",
            terminal_output_type="text",
            terminal_output_mode="pass_through",
        )
        new = old.model_copy(update={"terminal_output_type": "pdf"})
        assert old.has_semantic_change(new) is True


def _flow_step(
    *,
    step_order: int,
    input_source: str,
    input_type: str = "text",
    output_mode: str = "pass_through",
    output_type: str = "text",
) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=f"Step {step_order}",
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
    )
