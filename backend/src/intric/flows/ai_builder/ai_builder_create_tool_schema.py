from __future__ import annotations

from typing import Any

from intric.flows.ai_builder.ai_builder_flow_name import MAX_FLOW_NAME_LENGTH
from intric.flows.ai_builder.ai_builder_new_step_schema import (
    build_new_step_draft_schema,
    small_ref_enums,
)

CREATE_FLOW_TOOL_NAME = "create_flow"

CREATE_FLOW_TOOL_DESCRIPTION = (
    "Submit a typed create-flow draft for a brand new flow. "
    "Describe the intended flow shape only. Do not write raw JSON Schema, raw config dicts, "
    "plan_step_ref values, input_bindings, or template variables like {{ ... }}. "
    "Use typed intent fields such as uses_form_fields and uses_previous_fields when downstream steps "
    "should reuse specific runtime or structured inputs. "
    "The backend compiles this draft into the canonical flow spec shown to the user for approval."
)

MAX_FLOW_STEPS = 12


def build_create_flow_tool_schema(
    available_models: list[dict[str, Any]] | None = None,
    available_kbs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    model_refs = small_ref_enums(available_models)
    kb_refs = small_ref_enums(available_kbs)

    return {
        "type": "function",
        "function": {
            "name": CREATE_FLOW_TOOL_NAME,
            "description": CREATE_FLOW_TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "required": ["flow_name", "plan_rationale", "steps"],
                "properties": {
                    "flow_name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_FLOW_NAME_LENGTH,
                        "description": "Name of the new flow.",
                    },
                    "flow_description": {
                        "type": ["string", "null"],
                        "description": "Optional short description of what the flow does.",
                    },
                    "plan_rationale": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Short user-visible explanation of the flow design. Mention important "
                            "choices like JSON extraction, citations, template fill, or runtime uploads."
                        ),
                    },
                    "assumptions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Short assumptions made to keep the flow moving.",
                    },
                    "form_fields": {
                        "type": "array",
                        "description": "Optional runtime form fields the user fills in when running the flow.",
                        "items": _form_field_schema(),
                    },
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_FLOW_STEPS,
                        "description": (
                            "Ordered list of create-step objects. Each item must be a complete JSON object. "
                            "First step must use 'flow_input'. Only later steps may use "
                            "'previous_step' or 'all_previous_steps'. "
                            "Structured field declarations belong in output_fields on a JSON step, never directly in steps[]. "
                            "Do not emit raw JSON Schema, raw configs, plan_step_ref values, input_bindings, "
                            "or quoted fragments inside this array."
                        ),
                        "items": build_new_step_draft_schema(
                            model_refs=model_refs,
                            kb_refs=kb_refs,
                            description=(
                                "Typed authoring draft for one brand-new step. "
                                "Describe only the new step intent; the backend derives "
                                "output_mode, bindings, contracts, and low-level config."
                            ),
                            input_source_description=(
                                "Where this step gets its primary input. Step 1 must use 'flow_input'. "
                                "Only later steps may use 'previous_step' or 'all_previous_steps'."
                            ),
                        ),
                    },
                },
            },
        },
    }


def _form_field_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["variable_name", "label", "field_type", "required"],
        "properties": {
            "variable_name": {
                "type": "string",
                "description": "Stable variable name used for the runtime form field.",
            },
            "label": {
                "type": "string",
                "description": "User-visible form field label.",
            },
            "field_type": {
                "type": "string",
                "enum": ["text", "number", "date", "select", "multiselect"],
            },
            "required": {"type": "boolean"},
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Options for select or multiselect fields.",
            },
        },
        "additionalProperties": False,
    }
