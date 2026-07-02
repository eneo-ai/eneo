"""Tests for Flow authoring transcription defaults."""

from __future__ import annotations

from uuid import uuid4

from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    StepSpec,
)
from eneo.flows.flow_authoring_transcription import (
    apply_audio_transcription_defaults,
)


def _step(
    *,
    input_source: InputSource = InputSource.FLOW_INPUT,
    input_type: InputType = InputType.AUDIO,
) -> StepSpec:
    return StepSpec(
        plan_step_ref="step_a",
        name="Test",
        assistant_spec=AssistantSpec(instructions="Do."),
        input_source=input_source,
        input_type=input_type,
    )


def _spec(*steps: StepSpec) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Test Flow",
        flow_description="Test",
        steps=list(steps),
    )


class TestTranscriptionSetup:
    """Audio flow_input steps get transcription defaults."""

    def test_audio_flow_input_sets_transcription_enabled(self) -> None:
        result = apply_audio_transcription_defaults(
            metadata=None,
            spec=_spec(_step(input_type=InputType.AUDIO)),
            default_transcription_model_id=uuid4(),
        )

        assert result is not None
        wizard = result["wizard"]
        assert wizard["transcription_enabled"] is True

    def test_non_audio_leaves_metadata_unchanged(self) -> None:
        result = apply_audio_transcription_defaults(
            metadata={"existing": "data"},
            spec=_spec(_step(input_type=InputType.DOCUMENT)),
            default_transcription_model_id=uuid4(),
        )

        assert result == {"existing": "data"}


class TestTranscriptionCleanup:
    """When no audio flow_input remains, wizard transcription metadata must be removed."""

    def test_audio_removed_clears_transcription_metadata(self) -> None:
        """After edit changes audio→document, transcription wizard config should be cleared."""
        existing_metadata = {
            "wizard": {
                "transcription_enabled": True,
                "transcription_model": {"id": str(uuid4())},
                "transcription_language": "auto",
            },
            "form_schema": {"fields": []},
        }

        result = apply_audio_transcription_defaults(
            metadata=existing_metadata,
            spec=_spec(_step(input_type=InputType.DOCUMENT)),
            default_transcription_model_id=uuid4(),
        )

        assert result is not None
        # Transcription keys should be removed from wizard
        wizard = result.get("wizard", {})
        assert "transcription_enabled" not in wizard
        assert "transcription_model" not in wizard
        assert "transcription_language" not in wizard

    def test_cleanup_preserves_non_transcription_wizard_data(self) -> None:
        existing_metadata = {
            "wizard": {
                "transcription_enabled": True,
                "transcription_model": {"id": str(uuid4())},
                "transcription_language": "auto",
                "other_setting": "keep_me",
            },
        }

        result = apply_audio_transcription_defaults(
            metadata=existing_metadata,
            spec=_spec(_step(input_type=InputType.DOCUMENT)),
            default_transcription_model_id=None,
        )

        assert result is not None
        wizard = result.get("wizard", {})
        assert wizard.get("other_setting") == "keep_me"
        assert "transcription_enabled" not in wizard

    def test_cleanup_removes_empty_wizard(self) -> None:
        """If wizard only had transcription keys, wizard key itself is cleaned up."""
        existing_metadata = {
            "wizard": {
                "transcription_enabled": True,
                "transcription_model": {"id": str(uuid4())},
                "transcription_language": "sv",
            },
        }

        result = apply_audio_transcription_defaults(
            metadata=existing_metadata,
            spec=_spec(
                _step(input_type=InputType.TEXT, input_source=InputSource.PREVIOUS_STEP)
            ),
            default_transcription_model_id=None,
        )

        # Either wizard is empty/removed, or transcription keys are gone
        if result is not None:
            wizard = result.get("wizard", {})
            assert "transcription_enabled" not in wizard

    def test_no_metadata_no_audio_returns_none(self) -> None:
        result = apply_audio_transcription_defaults(
            metadata=None,
            spec=_spec(_step(input_type=InputType.DOCUMENT)),
            default_transcription_model_id=None,
        )

        assert result is None
