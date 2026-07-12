"""Dynamic edit-mode proposal schema builder for the AI Builder."""

from __future__ import annotations

from typing import Any

from eneo.flows.ai_builder.ai_builder_flow_schema_values import (
    builder_form_field_type_values,
    builder_input_source_values,
    builder_input_type_values,
    builder_output_type_values,
    document_delivery_mode_values,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    build_semantic_step_schema,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
)
from eneo.flows.ai_builder.ai_builder_step_tool_schema_fragments import (
    build_previous_field_refs_schema,
    build_resource_ref_property_schemas,
    build_review_mode_schema,
)
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_name import MAX_FLOW_NAME_LENGTH
from eneo.flows.step_lineage import existing_step_ref_for_order


def build_edit_flow_tool_schema(
    current_steps: list[FlowStep],
    *,
    resource_catalog: AIBuilderResourceCatalog,
    tool_name: str,
) -> dict[str, Any]:
    valid_refs = [existing_step_ref_for_order(s.step_order) for s in current_steps]

    model_refs = resource_catalog.small_ref_enum_for_kind("model")
    kb_refs = resource_catalog.small_ref_enum_for_kind("knowledge_base")
    step_payload_schema = build_semantic_step_schema(
        model_refs=model_refs,
        kb_refs=kb_refs,
    )
    modify_step_schema = _build_modify_step_schema(
        valid_refs=valid_refs,
        model_refs=model_refs,
        kb_refs=kb_refs,
    )

    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": (
                "Edit an existing flow by returning the complete ordered step list. "
                "Every existing step must appear once in steps unless its ref appears "
                "in removed_existing_step_refs. Omit flow fields and form_fields to "
                "preserve them; set form_fields to the complete desired list or null "
                "to clear all flow-level inmatningsfält/form fields."
            ),
            "parameters": {
                "type": "object",
                "required": ["steps", "plan_rationale"],
                "properties": {
                    "plan_rationale": {
                        "type": "string",
                        "description": (
                            "Explain what changes you're making and why, "
                            "in 1-2 sentences."
                        ),
                    },
                    "flow_name": {
                        "type": ["string", "null"],
                        "maxLength": MAX_FLOW_NAME_LENGTH,
                        "description": "New flow name, or null to keep current.",
                    },
                    "flow_description": {
                        "type": ["string", "null"],
                        "description": "New flow description, or null to keep current.",
                    },
                    "steps": {
                        "type": "array",
                        "description": (
                            "Complete ordered step list after the edit. Preserve an "
                            "existing step with kind=modify and its existing_step_ref; "
                            "include only fields that change on that step. Add new "
                            "steps with kind=add and a typed step payload."
                        ),
                        "items": {
                            "oneOf": [
                                modify_step_schema,
                                {
                                    "type": "object",
                                    "required": ["kind", "step"],
                                    "additionalProperties": False,
                                    "properties": {
                                        "kind": {"type": "string", "enum": ["add"]},
                                        "step": step_payload_schema,
                                    },
                                },
                            ],
                        },
                    },
                    "removed_existing_step_refs": {
                        "type": "array",
                        "items": {"type": "string", "enum": valid_refs},
                        "uniqueItems": True,
                        "description": (
                            "Existing step refs intentionally deleted by this edit. "
                            "Omission is never deletion; list every removed ref here."
                        ),
                    },
                    "form_fields": {
                        "type": ["array", "null"],
                        "items": _build_form_field_spec_schema(),
                        "description": (
                            "Complete desired form field list. Omit to preserve current "
                            "fields; set null to clear all fields; provide a list to add, "
                            "modify, or remove fields by complete state."
                        ),
                    },
                    "assumptions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Assumptions made about the edit.",
                    },
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# Internal schema builders
# ---------------------------------------------------------------------------


def _build_modify_step_schema(
    *,
    valid_refs: list[str],
    model_refs: list[str] | None,
    kb_refs: list[str] | None,
) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["kind", "existing_step_ref"],
        "additionalProperties": False,
        "properties": {
            "kind": {"type": "string", "enum": ["modify"]},
            "existing_step_ref": {
                "type": "string",
                "enum": valid_refs,
                "description": f"Server alias for the existing step. Valid refs: {valid_refs}.",
            },
            "name": {"type": ["string", "null"]},
            "assistant_spec": _build_assistant_spec_schema(
                model_refs,
                kb_refs,
            ),
            "input_source": {
                "type": ["string", "null"],
                "enum": [*builder_input_source_values(), None],
            },
            "input_type": {
                "type": ["string", "null"],
                "enum": [*builder_input_type_values(), None],
            },
            "output_type": {
                "type": ["string", "null"],
                "enum": [*builder_output_type_values(), None],
            },
            "document_delivery_mode": {
                "type": ["string", "null"],
                "enum": [*document_delivery_mode_values(), None],
            },
            "uses_form_fields": {
                "type": ["array", "null"],
                "items": {"type": "string"},
            },
            "uses_previous_fields": build_previous_field_refs_schema(),
            "output_contract": {
                "type": ["object", "null"],
                "additionalProperties": True,
            },
            "review_mode": build_review_mode_schema(),
        },
    }


def _build_form_field_spec_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["name", "type", "label"],
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "type": {
                "type": "string",
                "enum": builder_form_field_type_values(),
            },
            "label": {"type": "string", "minLength": 1},
            "required": {"type": "boolean", "default": False},
            "options": {
                "type": ["array", "null"],
                "items": {"type": "string"},
            },
        },
    }


def _build_assistant_spec_schema(
    model_refs: list[str] | None,
    kb_refs: list[str] | None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "required": ["instructions"],
        "properties": {
            "instructions": {
                "type": "string",
                "description": "What this step's assistant should do.",
            },
            **build_resource_ref_property_schemas(
                model_refs=model_refs,
                kb_refs=kb_refs,
            ),
        },
    }

    return schema
