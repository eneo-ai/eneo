"""Tests for AI Builder description semantics — signature, provenance, hashing."""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_description_semantics import (
    DescriptionProvenance,
    FlowSemanticSignature,
    _description_hash,
)
from intric.flows.flow_authoring_spec import (
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


class TestDescriptionProvenance:
    def test_default_is_manual(self) -> None:
        prov = DescriptionProvenance()
        assert prov.mode == "manual"
        assert prov.semantic_signature is None
        assert prov.last_generated_hash is None
        assert prov.version == 1

    def test_builder_managed_with_signature(self) -> None:
        sig = FlowSemanticSignature(
            entry_input_type="audio",
            entry_input_source="flow_input",
            terminal_output_type="text",
            terminal_output_mode="transcribe_only",
        )
        prov = DescriptionProvenance(
            mode="builder_managed",
            semantic_signature=sig,
            last_generated_hash="abc123",
        )
        assert prov.mode == "builder_managed"
        assert prov.semantic_signature == sig

    def test_roundtrip_serialization(self) -> None:
        sig = FlowSemanticSignature(
            entry_input_type="document",
            entry_input_source="flow_input",
            terminal_output_type="pdf",
            terminal_output_mode="pass_through",
        )
        prov = DescriptionProvenance(
            mode="builder_managed",
            semantic_signature=sig,
            last_generated_hash="deadbeef",
        )
        data = prov.model_dump(mode="json")
        restored = DescriptionProvenance.model_validate(data)
        assert restored == prov


class TestDescriptionHash:
    def test_deterministic(self) -> None:
        assert _description_hash("hello") == _description_hash("hello")

    def test_normalizes_whitespace(self) -> None:
        assert _description_hash("hello ") == _description_hash("hello")

    def test_normalizes_line_endings(self) -> None:
        assert _description_hash("a\r\nb") == _description_hash("a\nb")

    def test_none_treated_as_empty(self) -> None:
        assert _description_hash(None) == _description_hash("")

    def test_different_content_different_hash(self) -> None:
        assert _description_hash("hello") != _description_hash("world")
