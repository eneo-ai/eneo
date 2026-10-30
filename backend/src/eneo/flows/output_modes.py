from __future__ import annotations

from enum import Enum
from typing import Final

from eneo.flows.enums import FLOW_OUTPUT_MODE_VALUES, FlowOutputMode

ALLOWED_OUTPUT_MODES = set(FLOW_OUTPUT_MODE_VALUES)
# The modes whose handler builds its result without resolving the step's
# input. A source that exists only as the step's input would never be read
# under one of them.
OUTPUT_MODES_WITHOUT_STEP_INPUT: frozenset[FlowOutputMode] = frozenset(
    {FlowOutputMode.TEMPLATE_FILL}
)
# The sources whose input is read from outside the run: nothing of the run
# stands in for it, so it is fetched (the MCP tool called, the URL read) when
# the step's input is resolved, before any other part of it, and cannot be
# replaced by underlag.
OUTSIDE_INPUT_SOURCES: Final = frozenset({"http_get", "tool"})


def outside_input_mode_violation(
    *, input_source: str | Enum, output_mode: str | Enum
) -> str | None:
    """Why a step cannot fetch its input from outside the run under this
    output mode (the mode never resolves the step's input, so the fetch would
    never be made); None when it can or the source is not fetched."""
    source = _enum_value(input_source)
    mode = _enum_value(output_mode)
    if (
        source not in OUTSIDE_INPUT_SOURCES
        or mode not in OUTPUT_MODES_WITHOUT_STEP_INPUT
    ):
        return None
    return (
        f"output_mode '{mode}' does not read the step's input, so it cannot be "
        f"used with input_source '{source}'"
    )


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


def copy_input_violation(
    *, step_order: int, input_type: str, output_type: str, output_mode: str
) -> str | None:
    if output_mode != FlowOutputMode.COPY_INPUT:
        return None
    if input_type != "json" or output_type != "json":
        return f"Step {step_order}: output_mode 'copy_input' requires input_type 'json' and output_type 'json'."
    return None


def speaker_mapping_violation(
    *,
    step_order: int,
    input_source: str | Enum,
    input_type: str | Enum,
    output_type: str | Enum,
    output_mode: str | Enum,
) -> str | None:
    if _enum_value(output_mode) != "speaker_mapping":
        return None
    if _enum_value(input_source) != "previous_step":
        return (
            f"Step {step_order}: output_mode 'speaker_mapping' requires "
            "input_source 'previous_step' (the transcript step)."
        )
    if _enum_value(input_type) != "text":
        return f"Step {step_order}: output_mode 'speaker_mapping' requires input_type 'text'."
    if _enum_value(output_type) != "json":
        return f"Step {step_order}: output_mode 'speaker_mapping' requires output_type 'json'."
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
