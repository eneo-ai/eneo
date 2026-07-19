from __future__ import annotations

from enum import Enum

from eneo.flows.enums import FLOW_OUTPUT_MODE_VALUES

ALLOWED_OUTPUT_MODES = set(FLOW_OUTPUT_MODE_VALUES)


def transcribe_only_violation(
    *,
    step_order: int,
    input_type: str,
    output_type: str,
    output_mode: str,
) -> str | None:
    if output_mode != "transcribe_only":
        return None
    if input_type != "audio":
        return f"Step {step_order}: output_mode 'transcribe_only' requires input_type 'audio'."
    if output_type != "text":
        return f"Step {step_order}: output_mode 'transcribe_only' requires output_type 'text'."
    return None


def render_verbatim_violation(
    *,
    step_order: int,
    input_type: str,
    output_type: str,
    output_mode: str,
) -> str | None:
    if output_mode != "render_verbatim":
        return None
    if input_type != "text":
        return f"Step {step_order}: output_mode 'render_verbatim' requires input_type 'text'."
    if output_type not in {"pdf", "docx"}:
        return (
            f"Step {step_order}: output_mode 'render_verbatim' requires output_type "
            "'pdf' or 'docx'."
        )
    return None


def compose_text_violation(
    *,
    step_order: int,
    input_type: str,
    output_type: str,
    output_mode: str,
) -> str | None:
    if output_mode != "compose_text":
        return None
    if input_type != "text":
        return (
            f"Step {step_order}: output_mode 'compose_text' requires input_type 'text'."
        )
    if output_type != "text":
        return f"Step {step_order}: output_mode 'compose_text' requires output_type 'text'."
    return None


def text_document_pass_through_violation(
    *,
    step_order: int,
    input_type: str | Enum,
    output_type: str | Enum,
    output_mode: str | Enum,
) -> str | None:
    input_type_value = _enum_value(input_type)
    output_type_value = _enum_value(output_type)
    output_mode_value = _enum_value(output_mode)

    if output_mode_value != "pass_through":
        return None
    if input_type_value != "text" or output_type_value not in {"pdf", "docx"}:
        return None
    return (
        f"Step {step_order}: output_mode 'pass_through' is not supported for "
        f"text-to-{output_type_value} document steps; use output_mode "
        "'render_verbatim'."
    )


def _enum_value(value: str | Enum) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return value
