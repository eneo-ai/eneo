"""Dynamic edit-mode tool schema builder for the AI Builder.

Builds the `edit_flow` tool schema with dynamic constraints based on the
current flow state. By injecting valid step refs as enum values, the LLM
cannot generate an invalid ref — the API layer rejects it before validation.
"""

from __future__ import annotations

from typing import Any

from intric.flows.ai_builder.ai_builder_flow_schema_values import (
    builder_form_field_type_values,
    builder_input_source_values,
    builder_input_type_values,
    builder_output_type_values,
    document_delivery_mode_values,
)
from intric.flows.ai_builder.ai_builder_new_step_schema import (
    build_new_step_draft_schema,
    build_previous_field_refs_schema,
    build_review_mode_schema,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
)
from intric.flows.domain.flow import FlowStep
from intric.flows.enums import FlowMcpPolicy
from intric.flows.flow_authoring_name import MAX_FLOW_NAME_LENGTH

EDIT_FLOW_TOOL_NAME = "edit_flow"


def build_edit_flow_tool_schema(
    current_steps: list[FlowStep],
    *,
    resource_catalog: AIBuilderResourceCatalog,
) -> dict[str, Any]:
    valid_refs = [f"existing_step_{s.step_order}" for s in current_steps]

    model_refs = resource_catalog.small_ref_enum_for_kind("model")
    kb_refs = resource_catalog.small_ref_enum_for_kind("knowledge_base")
    # Do not constrain MCP refs with schema enums. When a requested MCP is
    # absent, enums can force the model to pick an unrelated available MCP.
    # Catalog resolution and quality feedback provide the durable guardrail.
    mcp_server_refs: list[str] | None = None
    mcp_tool_refs: list[str] | None = None

    step_payload_schema = _build_step_payload_schema(
        model_refs,
        kb_refs,
        mcp_server_refs,
        mcp_tool_refs,
    )
    modify_step_schema = _build_modify_step_schema(
        valid_refs=valid_refs,
        model_refs=model_refs,
        kb_refs=kb_refs,
        mcp_server_refs=mcp_server_refs,
        mcp_tool_refs=mcp_tool_refs,
    )

    return {
        "type": "function",
        "function": {
            "name": EDIT_FLOW_TOOL_NAME,
            "description": (
                "Edit an existing flow by returning the complete ordered step list. "
                "Every existing step must appear once in steps unless its ref appears "
                "in removed_existing_step_refs. Omit flow fields and form_fields to "
                "preserve them; set form_fields to the complete desired list or null "
                "to clear all flow-level inmatningsfält/form fields. "
                "When you change output_type or document_delivery_mode, clear or omit "
                "incompatible output_config fields instead of rewriting unrelated step config."
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


def build_edit_mode_tool_schemas(
    current_steps: list[FlowStep],
    *,
    resource_catalog: AIBuilderResourceCatalog,
) -> list[dict[str, Any]]:
    from intric.flows.ai_builder.ai_builder_tools import (
        build_ask_structured_question_tool_schema,
        build_confirm_requirements_tool_schema,
    )

    return [
        build_edit_flow_tool_schema(
            current_steps,
            resource_catalog=resource_catalog,
        ),
        build_ask_structured_question_tool_schema(),
        build_confirm_requirements_tool_schema(),
    ]


# ---------------------------------------------------------------------------
# Internal schema builders
# ---------------------------------------------------------------------------


def _build_modify_step_schema(
    *,
    valid_refs: list[str],
    model_refs: list[str] | None,
    kb_refs: list[str] | None,
    mcp_server_refs: list[str] | None,
    mcp_tool_refs: list[str] | None,
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
                mcp_server_refs,
                mcp_tool_refs,
            ),
            "mcp_policy": {
                "type": ["string", "null"],
                "enum": [*(policy.value for policy in FlowMcpPolicy), None],
            },
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
            "input_bindings": {
                "type": ["object", "null"],
                "additionalProperties": True,
            },
            "input_contract": {
                "type": ["object", "null"],
                "additionalProperties": True,
            },
            "output_contract": {
                "type": ["object", "null"],
                "additionalProperties": True,
            },
            "input_config": {
                "type": ["object", "null"],
                "additionalProperties": True,
            },
            "output_config": {
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


def _build_step_payload_schema(
    model_refs: list[str] | None,
    kb_refs: list[str] | None,
    mcp_server_refs: list[str] | None,
    mcp_tool_refs: list[str] | None,
) -> dict[str, Any]:
    return build_new_step_draft_schema(
        model_refs=model_refs,
        kb_refs=kb_refs,
        mcp_server_refs=mcp_server_refs,
        mcp_tool_refs=mcp_tool_refs,
        description=(
            "Typed authoring draft for a new step added to an existing flow. "
            "Describe only the new step intent; the backend derives output_mode, "
            "bindings, contracts, and low-level config."
        ),
        input_source_description=(
            "Where the new step gets its primary input. Use 'flow_input' only when "
            "the added step becomes the new entry step; otherwise use 'previous_step' "
            "or 'all_previous_steps'."
        ),
        expose_previous_field_refs=True,
    )


def _build_assistant_spec_schema(
    model_refs: list[str] | None,
    kb_refs: list[str] | None,
    mcp_server_refs: list[str] | None,
    mcp_tool_refs: list[str] | None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "required": ["instructions"],
        "properties": {
            "instructions": {
                "type": "string",
                "description": "What this step's assistant should do.",
            },
            "model_ref": {
                "type": ["string", "null"],
                "description": "Model alias, or null for space default.",
            },
            "knowledge_refs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Knowledge base aliases to attach.",
            },
            "mcp_server_refs": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "MCP server refs to attach. Use only for external tools/live data "
                    "and do not combine with knowledge_refs."
                ),
            },
            "mcp_tool_refs": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "MCP tool refs to attach for least-privilege tool access."
                ),
            },
        },
    }

    # Inject dynamic enums for small lists
    if model_refs is not None:
        schema["properties"]["model_ref"]["enum"] = model_refs + [None]
    if kb_refs is not None:
        schema["properties"]["knowledge_refs"]["items"]["enum"] = kb_refs
    if mcp_server_refs is not None:
        schema["properties"]["mcp_server_refs"]["items"]["enum"] = mcp_server_refs
    if mcp_tool_refs is not None:
        schema["properties"]["mcp_tool_refs"]["items"]["enum"] = mcp_tool_refs

    return schema
