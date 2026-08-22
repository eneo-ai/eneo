from __future__ import annotations

from typing import Any

from eneo.flows.ai_builder.ai_builder_new_step_models import (
    MAX_STRUCTURED_FIELD_DEPTH,
    STRUCTURED_FIELD_NAME_PATTERN,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode


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
                        "for example `summary` or `risks.0.title`."
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


def build_previous_output_refs_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "description": (
            "Optional full-output reuse intent for earlier text-producing steps. "
            "The backend compiles these into explicit underlag bindings."
        ),
        "items": {
            "type": "object",
            "required": ["from_step"],
            "properties": {
                "from_step": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "1-based earlier step number to reuse the full text output from."
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


def build_model_ref_property_schema(
    *,
    model_refs: list[str] | None,
) -> dict[str, Any]:
    """Model slot property for a step this proposal creates.

    An existing step's model belongs to the step's model picker, so the
    modify-step schema deliberately offers no such property.
    """
    model_ref_schema: dict[str, Any] = {
        "type": ["string", "null"],
        "description": (
            "Optional portable model slot ref to use for this step; null lets "
            "the space default model apply."
        ),
    }
    if model_refs is not None:
        model_ref_schema["enum"] = [*model_refs, None]
    return {"model_ref": model_ref_schema}


def build_knowledge_refs_property_schema(
    *,
    kb_refs: list[str] | None,
) -> dict[str, Any]:
    knowledge_refs_schema: dict[str, Any] = {
        "type": "array",
        "items": {"type": "string"},
        "uniqueItems": True,
        "description": ("Portable knowledge slot refs this step needs."),
    }
    if kb_refs is not None:
        knowledge_refs_schema["items"]["enum"] = kb_refs
    return {"knowledge_refs": knowledge_refs_schema}


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
            "name": {
                "type": "string",
                "pattern": STRUCTURED_FIELD_NAME_PATTERN,
                "description": (
                    "ASCII English JSON schema key, for example `summary` or "
                    "`date_or_year`. Put localized wording in the description."
                ),
            },
            "field_type": {"type": "string", "enum": field_type_enum},
            "description": {
                "type": "string",
                "description": (
                    "Human-readable field meaning. Do not include template variables."
                ),
            },
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


def _create_structured_field_schema(*, depth: int) -> dict[str, Any]:
    is_leaf_depth = depth >= MAX_STRUCTURED_FIELD_DEPTH
    field_type_enum = (
        ["string", "number", "boolean", "array"]
        if is_leaf_depth
        else ["string", "number", "boolean", "object", "array"]
    )
    children_schema: dict[str, Any] = (
        {"type": "null"}
        if is_leaf_depth
        else {
            "type": ["array", "null"],
            "minItems": 1,
            "items": _create_structured_field_schema(depth=depth + 1),
        }
    )
    return {
        "type": "object",
        "required": ["name", "field_type", "description"],
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "JSON schema key. Localized names are normalized by the typed "
                    "admission boundary; put user-facing wording in the description."
                ),
            },
            "field_type": {"type": "string", "enum": field_type_enum},
            "description": {
                "type": "string",
                "description": (
                    "Human-readable field meaning. Do not include template variables."
                ),
            },
            "required": {"type": "boolean", "default": True},
            "nullable": {
                "type": "boolean",
                "default": False,
                "description": (
                    "Whether a required primitive field may be null when the "
                    "source explicitly lacks the value. Keep false for object "
                    "and array fields."
                ),
            },
            "children": {
                **children_schema,
                "description": (
                    "Nested object members or array-item members. Use null for "
                    "primitive fields, arrays of primitive values, and objects "
                    "whose dynamic member names are not known in advance."
                ),
            },
        },
        "additionalProperties": False,
    }


def build_create_structured_field_schema() -> dict[str, Any]:
    return _create_structured_field_schema(depth=1)


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
