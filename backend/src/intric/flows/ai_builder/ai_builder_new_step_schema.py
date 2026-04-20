from __future__ import annotations

from typing import Any, cast

from intric.flows.ai_builder.ai_builder_models import InputSource, InputType, OutputType
from intric.flows.ai_builder.ai_builder_new_step_models import (
    MAX_STRUCTURED_FIELD_DEPTH,
)


def small_ref_enums(values: list[dict[str, Any]] | None) -> list[str] | None:
    if not values or len(values) > 15:
        return None
    refs = [value["ref"] for value in values if isinstance(value.get("ref"), str)]
    return refs or None


def build_new_step_draft_schema(
    *,
    model_refs: list[str] | None,
    kb_refs: list[str] | None,
    description: str,
    input_source_description: str,
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "name": {
            "type": "string",
            "minLength": 1,
            "description": "User-visible step name.",
        },
        "instructions": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Plain assistant instructions for this step. Do not include variable references like "
                "{{ indata_text }} or {{ step_a.output.text }}."
            ),
        },
        "input_source": {
            "type": "string",
            "enum": [value.value for value in InputSource],
            "description": input_source_description,
        },
        "input_type": {
            "type": "string",
            "enum": [value.value for value in InputType],
            "default": InputType.TEXT.value,
        },
        "output_type": {
            "type": "string",
            "enum": [value.value for value in OutputType],
            "default": OutputType.TEXT.value,
        },
        "runtime_upload": {
            "type": "boolean",
            "default": False,
            "description": "Whether this step should receive uploaded runtime files.",
        },
        "runtime_required": {
            "type": "boolean",
            "default": False,
            "description": "Whether the runtime upload is required for this step.",
        },
        "runtime_max_files": {
            "type": ["integer", "null"],
            "minimum": 1,
            "description": "Optional max number of files for runtime upload.",
        },
        "uses_form_fields": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Form field variable names this step needs in its compiled underlag.",
        },
        "uses_previous_fields": {
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
                        "description": "1-based earlier step number to reuse structured fields from.",
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
                        "description": "Optional human-readable label to use in the compiled underlag.",
                    },
                },
                "additionalProperties": False,
            },
        },
        "document_delivery_mode": {
            "type": "string",
            "enum": ["not_applicable", "generated", "template_fill"],
            "default": "not_applicable",
            "description": (
                "For docx/pdf outputs: generated document or template_fill. "
                "Only DOCX supports template_fill."
            ),
        },
        "citations_requested": {
            "type": "boolean",
            "default": False,
            "description": "Whether the backend should enable inline citations for this text step.",
        },
        "output_fields": {
            "type": ["array", "null"],
            "description": (
                "Typed structured output fields for JSON output. Use these instead of raw JSON Schema. "
                "These field objects belong inside output_fields, never directly in steps[]. "
                f"Keep max nesting depth {MAX_STRUCTURED_FIELD_DEPTH}: top-level fields, child fields, "
                "and one grandchild level only."
            ),
            "items": _structured_field_schema(depth=1),
        },
    }

    properties["model_ref"] = {
        "type": ["string", "null"],
        "description": "Optional canonical model ref to use for this step.",
    }
    if model_refs is not None:
        model_ref_property = cast(dict[str, Any], properties["model_ref"])
        model_ref_property["enum"] = [*model_refs, None]

    properties["knowledge_refs"] = {
        "type": "array",
        "items": {"type": "string"},
        "uniqueItems": True,
        "description": "Optional canonical knowledge base refs for this step.",
    }
    if kb_refs is not None:
        knowledge_ref_property = cast(dict[str, Any], properties["knowledge_refs"])
        knowledge_ref_items = cast(dict[str, Any], knowledge_ref_property["items"])
        knowledge_ref_items["enum"] = kb_refs

    return {
        "type": "object",
        "description": (
            f"{description} Use `uses_previous_fields` instead of raw `input_bindings` "
            "when a downstream step should reuse specific structured fields."
        ),
        "required": ["name", "instructions", "input_source"],
        "properties": properties,
        "additionalProperties": False,
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
