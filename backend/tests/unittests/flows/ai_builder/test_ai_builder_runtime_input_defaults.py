"""Tests for AI Builder runtime input defaults — input_format/description sync."""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    InputSource,
    InputType,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_runtime_input_defaults import (
    resolve_runtime_input_config,
)


def _step(
    *,
    input_source: InputSource = InputSource.FLOW_INPUT,
    input_type: InputType = InputType.DOCUMENT,
    input_config: dict | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref="step_a",
        name="Test",
        assistant_spec=AssistantSpec(instructions="Do."),
        input_source=input_source,
        input_type=input_type,
        input_config=input_config,
    )


class TestInputFormatSyncsWithInputType:
    """Regression: setdefault kept stale input_format when input_type changed."""

    def test_audio_to_document_updates_input_format(self) -> None:
        """Changing input_type from audio to document must update input_format."""
        existing_config = {
            "runtime_input": {
                "enabled": True,
                "required": True,
                "input_format": "audio",
                "description": "Ladda upp ljudfiler som detta steg ska transkribera eller analysera.",
            }
        }

        result = resolve_runtime_input_config(
            step_spec=_step(input_type=InputType.DOCUMENT, input_config=existing_config),
        )

        assert result is not None
        ri = result["runtime_input"]
        assert ri["input_format"] == "document"
        assert ri["description"] == "Ladda upp dokument som detta steg ska analysera."
        # Preserve non-default fields
        assert ri["required"] is True

    def test_audio_to_file_updates_input_format(self) -> None:
        existing_config = {
            "runtime_input": {
                "enabled": True,
                "input_format": "audio",
                "description": "Ladda upp ljudfiler som detta steg ska transkribera eller analysera.",
            }
        }

        result = resolve_runtime_input_config(
            step_spec=_step(input_type=InputType.FILE, input_config=existing_config),
        )

        assert result is not None
        ri = result["runtime_input"]
        assert ri["input_format"] == "file"
        assert ri["description"] == "Ladda upp filer som detta steg ska analysera."

    def test_document_to_audio_updates_input_format(self) -> None:
        existing_config = {
            "runtime_input": {
                "enabled": True,
                "input_format": "document",
                "description": "Ladda upp dokument som detta steg ska analysera.",
            }
        }

        result = resolve_runtime_input_config(
            step_spec=_step(input_type=InputType.AUDIO, input_config=existing_config),
        )

        assert result is not None
        ri = result["runtime_input"]
        assert ri["input_format"] == "audio"
        assert ri["description"] == "Ladda upp ljudfiler som detta steg ska transkribera eller analysera."

    def test_preserves_custom_description_when_type_changes(self) -> None:
        """If user wrote a custom description, keep it even when type changes."""
        existing_config = {
            "runtime_input": {
                "enabled": True,
                "input_format": "audio",
                "description": "Ladda upp mötesinspelningen från Teams.",
            }
        }

        result = resolve_runtime_input_config(
            step_spec=_step(input_type=InputType.DOCUMENT, input_config=existing_config),
        )

        assert result is not None
        ri = result["runtime_input"]
        assert ri["input_format"] == "document"
        # Custom description preserved — not a default
        assert ri["description"] == "Ladda upp mötesinspelningen från Teams."

    def test_same_type_preserves_everything(self) -> None:
        """When input_type hasn't changed, everything stays the same."""
        existing_config = {
            "runtime_input": {
                "enabled": True,
                "required": True,
                "input_format": "document",
                "description": "Ladda upp dokument som detta steg ska analysera.",
                "max_files": 5,
            }
        }

        result = resolve_runtime_input_config(
            step_spec=_step(input_type=InputType.DOCUMENT, input_config=existing_config),
        )

        assert result is not None
        ri = result["runtime_input"]
        assert ri["input_format"] == "document"
        assert ri["description"] == "Ladda upp dokument som detta steg ska analysera."
        assert ri["max_files"] == 5
        assert ri["required"] is True

    def test_new_step_without_existing_config_gets_defaults(self) -> None:
        """Brand new step with no existing config gets proper defaults."""
        result = resolve_runtime_input_config(
            step_spec=_step(input_type=InputType.AUDIO),
        )

        assert result is not None
        ri = result["runtime_input"]
        assert ri["enabled"] is True
        assert ri["input_format"] == "audio"
        assert ri["description"] == "Ladda upp ljudfiler som detta steg ska transkribera eller analysera."

    def test_existing_config_from_parameter_used_when_spec_has_none(self) -> None:
        """When step_spec.input_config is None, existing_input_config is used as base."""
        existing = {
            "runtime_input": {
                "enabled": True,
                "input_format": "audio",
                "description": "Ladda upp ljudfiler som detta steg ska transkribera eller analysera.",
                "max_files": 3,
            }
        }

        result = resolve_runtime_input_config(
            step_spec=_step(input_type=InputType.DOCUMENT, input_config=None),
            existing_input_config=existing,
        )

        assert result is not None
        ri = result["runtime_input"]
        assert ri["input_format"] == "document"
        assert ri["description"] == "Ladda upp dokument som detta steg ska analysera."
        assert ri["max_files"] == 3


class TestAcceptedMimetypesOverrideCleared:
    """Format change must clear accepted_mimetypes_override to prevent stale constraints."""

    def test_format_change_clears_accepted_mimetypes_override(self) -> None:
        existing_config = {
            "runtime_input": {
                "enabled": True,
                "input_format": "audio",
                "description": "Ladda upp ljudfiler som detta steg ska transkribera eller analysera.",
                "accepted_mimetypes_override": ["audio/mpeg", "audio/wav"],
            }
        }

        result = resolve_runtime_input_config(
            step_spec=_step(input_type=InputType.DOCUMENT, input_config=existing_config),
        )

        assert result is not None
        ri = result["runtime_input"]
        assert ri["input_format"] == "document"
        assert "accepted_mimetypes_override" not in ri

    def test_same_format_preserves_accepted_mimetypes_override(self) -> None:
        existing_config = {
            "runtime_input": {
                "enabled": True,
                "input_format": "document",
                "description": "Ladda upp dokument som detta steg ska analysera.",
                "accepted_mimetypes_override": ["application/pdf"],
            }
        }

        result = resolve_runtime_input_config(
            step_spec=_step(input_type=InputType.DOCUMENT, input_config=existing_config),
        )

        assert result is not None
        ri = result["runtime_input"]
        assert ri["accepted_mimetypes_override"] == ["application/pdf"]
