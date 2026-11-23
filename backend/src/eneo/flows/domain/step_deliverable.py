"""A step its author marks as one of a run's deliverables.

The mark lives in the step's ``output_config`` under ``deliverable``: the
label a client shows for the text or document and, for a document,
optionally the name it is saved under. Only a step that can be a deliverable
(``step_can_be_deliverable``) carries it, and only a document step a file
name; saving a step drops what it cannot carry, and publishing or importing
refuses it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from eneo.flows.domain.one_line_text import ONE_LINE_TEXT_MAX_CHARS, one_line
from eneo.flows.flow_variable_definitions import variable_path_segments
from eneo.flows.variable_resolver import TEMPLATE_VARIABLE_PATTERN

FLOW_STEP_DELIVERABLE_KEY = "deliverable"
DELIVERABLE_LABEL_MAX_CHARS = ONE_LINE_TEXT_MAX_CHARS
DELIVERABLE_FILE_NAME_MAX_CHARS = 200
_FORM_FIELD_HEAD = "flow_input"
# Where a read of a form field by a deliverable's file name is reported.
DELIVERABLE_FILE_NAME_READ_SITE = f"output_config.{FLOW_STEP_DELIVERABLE_KEY}.file_name"


def _as_written_one_line(value: str, *, max_chars: int) -> str:
    if one_line(value, max_chars=max_chars) != value:
        raise ValueError(
            f"must be one line of at most {max_chars} characters, without "
            "leading, trailing or repeated spaces."
        )
    return value


class FlowStepDeliverable(BaseModel):
    """One text or document a run delivers: what a client calls it and, for
    a document, what it is saved as."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    label: str = Field(
        description=(
            "What a client calls this text or document, for example `Standup "
            "Eneo`. One "
            f"line of at most {DELIVERABLE_LABEL_MAX_CHARS} characters, shown as "
            "written: publishing refuses `{{` or `}}` in it."
        ),
    )
    file_name: str | None = Field(
        default=None,
        description=(
            "Only for a document. The name it is saved under, without "
            "extension: fixed text "
            "mixed with `{{ flow_input.<field> }}` for a field of the flow's "
            "form. The run's day is added after it, and equal names are "
            "numbered. One line of at most "
            f"{DELIVERABLE_FILE_NAME_MAX_CHARS} characters. Left out, the "
            "document is named as before."
        ),
    )

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        return _as_written_one_line(value, max_chars=DELIVERABLE_LABEL_MAX_CHARS)

    @field_validator("file_name")
    @classmethod
    def _validate_file_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _as_written_one_line(value, max_chars=DELIVERABLE_FILE_NAME_MAX_CHARS)


class FlowStepDeliverableError(ValueError):
    """A deliverable of the wrong form, with the path of its first wrong
    field (`output_config.deliverable.label`), where an editor shows it."""

    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(message)
        self.field = field


def parse_flow_step_deliverable(output_config: object) -> FlowStepDeliverable | None:
    """The deliverable ``output_config`` marks, or None when it has no
    ``deliverable`` key. Only its form is checked: whether the step can
    deliver it, and whether its file name reads fields the form has, are the
    flow validator's to judge at publish, so a stored version always reads."""
    if not isinstance(output_config, Mapping):
        return None
    raw_output_config = cast(Mapping[object, object], output_config)
    if FLOW_STEP_DELIVERABLE_KEY not in raw_output_config:
        return None
    try:
        return FlowStepDeliverable.model_validate(
            raw_output_config[FLOW_STEP_DELIVERABLE_KEY]
        )
    except ValidationError as exc:
        reasons = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'value'}: {error['msg']}"
            for error in exc.errors()
        )
        first_loc = exc.errors()[0]["loc"]
        raise FlowStepDeliverableError(
            f"output_config.deliverable is invalid: {reasons}",
            field=".".join(
                ["output_config", FLOW_STEP_DELIVERABLE_KEY]
                + [str(part) for part in first_loc]
            ),
        ) from exc


def file_name_expressions(file_name: str) -> list[str] | None:
    """Each `{{ }}` expression ``file_name`` holds, in order, or None when a
    `{{` or `}}` is left over that no expression closes."""
    leftover = TEMPLATE_VARIABLE_PATTERN.sub("", file_name)
    if "{{" in leftover or "}}" in leftover:
        return None
    return [
        match.group(1).strip()
        for match in TEMPLATE_VARIABLE_PATTERN.finditer(file_name)
    ]


def form_field_read_by(expression: str) -> str | None:
    """The form field an expression reads when it is exactly
    `flow_input.<field>`; None for anything else, so a step output, an alias,
    `datum` or a nested path never reaches a file name."""
    segments = variable_path_segments(expression)
    if len(segments) == 2 and segments[0] == _FORM_FIELD_HEAD and segments[1]:
        return segments[1]
    return None


def deliverable_file_name_fields(output_config: object) -> list[str]:
    """The form fields the file name of ``output_config``'s deliverable reads,
    in order; none when it has no file name or one that is not well formed.
    The label is literal text and reads nothing."""
    try:
        deliverable = parse_flow_step_deliverable(output_config)
    except ValueError:
        return []
    if deliverable is None or deliverable.file_name is None:
        return []
    return [
        field
        for expression in file_name_expressions(deliverable.file_name) or []
        if (field := form_field_read_by(expression)) is not None
    ]
