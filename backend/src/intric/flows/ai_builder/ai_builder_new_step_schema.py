from __future__ import annotations

from typing import Any

from intric.flows.ai_builder.ai_builder_new_step_models import (
    MAX_STRUCTURED_FIELD_DEPTH,
)
from intric.flows.flow_review_policy import FlowStepReviewMode


def build_previous_field_refs_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "description": (
            "Optional field-level reuse intent for earlier JSON-producing steps. "
            "The backend compiles these into explicit underlag bindings."
        ),
        "items": {
            "type": "object",
            "required": ["from_step", "field_path"],
            "properties": {
                "from_step": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "1-based earlier step number to reuse structured fields from."
                    ),
                },
                "field_path": {
                    "type": "string",
                    "description": (
                        "Dot path inside the earlier step's structured JSON output, "
                        "for example `sammanfattning` or `risker.0.rubrik`."
                    ),
                },
                "label": {
                    "type": ["string", "null"],
                    "description": (
                        "Optional human-readable label to use in the compiled underlag."
                    ),
                },
            },
            "additionalProperties": False,
        },
    }


def _structured_field_schema(*, depth: int) -> dict[str, Any]:
    is_leaf_depth = depth >= MAX_STRUCTURED_FIELD_DEPTH
    field_type_enum = (
        ["string", "number", "boolean"]
        if is_leaf_depth
        else ["string", "number", "boolean", "object", "array"]
    )
    schema: dict[str, Any] = {
        "type": "object",
        "required": ["name", "field_type", "description", "required"],
        "properties": {
            "name": {"type": "string"},
            "field_type": {"type": "string", "enum": field_type_enum},
            "description": {"type": "string"},
            "required": {"type": "boolean"},
            "fields": (
                False
                if is_leaf_depth
                else {
                    "type": ["array", "null"],
                    "items": _structured_field_schema(depth=depth + 1),
                }
            ),
            "item_fields": (
                False
                if is_leaf_depth
                else {
                    "type": ["array", "null"],
                    "items": _structured_field_schema(depth=depth + 1),
                }
            ),
        },
        "additionalProperties": False,
    }
    return schema


def build_structured_field_schema() -> dict[str, Any]:
    return _structured_field_schema(depth=1)


def build_review_mode_schema() -> dict[str, Any]:
    return {
        "type": ["string", "null"],
        "enum": [*(mode.value for mode in FlowStepReviewMode), None],
        "default": None,
        "description": (
            "Set when the run must pause after this step for human review before "
            "later steps continue. Use 'view' when the user approves or rejects "
            "the output, and 'edit' when the user may edit the step output."
        ),
    }
