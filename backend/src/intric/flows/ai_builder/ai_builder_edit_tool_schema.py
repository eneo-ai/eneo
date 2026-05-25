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
from intric.flows.flow_authoring_name import MAX_FLOW_NAME_LENGTH

EDIT_FLOW_TOOL_NAME = "edit_flow"


def build_edit_flow_tool_schema(
    current_steps: list[FlowStep],
    *,
    resource_catalog: AIBuilderResourceCatalog,
) -> dict[str, Any]:
    valid_refs = [f"existing_step_{s.step_order}" for s in current_steps]
    # Include None for add operations where target_ref should be absent
    target_ref_enum: list[str | None] = valid_refs + [None]
    anchor_ref_enum: list[str | None] = valid_refs + [None]

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

    return {
        "type": "function",
        "function": {
            "name": EDIT_FLOW_TOOL_NAME,
            "description": (
                "Edit an existing flow. Describe only the steps or flow properties that truly change — "
                "the backend preserves everything else. Each operation targets "
                "a specific step by its ref. Unmentioned steps are kept as-is. "
                "Use form_operations to add, modify, or remove flow-level inmatningsfält/form fields, "
                "then reference those fields from consuming steps with uses_form_fields. "
                "When you change output_type or document_delivery_mode, clear or omit "
                "incompatible output_config fields instead of rewriting unrelated step config."
            ),
            "parameters": {
                "type": "object",
                "required": ["operations", "plan_rationale"],
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
                    "operations": {
                        "type": "array",
                        "description": (
                            "List of step operations. Each operation is add, modify, or remove. "
                            "Use at most one modify operation per existing target_ref; combine "
                            "all changes for the same step into that one patch."
                        ),
                        "items": {
                            "type": "object",
                            "required": ["op"],
                            "properties": {
                                "op": {
                                    "type": "string",
                                    "enum": ["add", "modify", "remove"],
                                    "description": (
                                        "add: insert a new step. "
                                        "modify: change fields on an existing step. "
                                        "remove: delete an existing step."
                                    ),
                                },
                                "target_ref": {
                                    "type": ["string", "null"],
                                    "enum": target_ref_enum,
                                    "description": (
                                        "For modify/remove: the existing step to target. "
                                        f"Valid refs: {valid_refs}. "
                                        "Must be null for add operations."
                                    ),
                                },
                                "placement": {
                                    "type": "object",
                                    "description": "For add: where to insert the new step.",
                                    "properties": {
                                        "position": {
                                            "type": "string",
                                            "enum": ["before", "after", "append"],
                                        },
                                        "anchor_ref": {
                                            "type": ["string", "null"],
                                            "enum": anchor_ref_enum,
                                            "description": (
                                                "Required for before/after. "
                                                f"Valid refs: {valid_refs}"
                                            ),
                                        },
                                    },
                                },
                                "add_payload": step_payload_schema,
                                "patch": _build_patch_schema(
                                    model_refs,
                                    kb_refs,
                                    mcp_server_refs,
                                    mcp_tool_refs,
                                ),
                            },
                        },
                    },
                    "form_operations": _build_form_operations_schema(),
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


def _build_form_operations_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "description": (
            "Optional operations for flow-level form fields/inmatningsfält. "
            "When adding a field, also add the field name to uses_form_fields on "
            "every step that consumes it; declared fields without step references "
            "become orphan UI controls. field_payload is required for add and "
            "modify; omit field_payload for remove."
        ),
        "items": {
            "type": "object",
            "required": ["op", "field_name"],
            "additionalProperties": False,
            "properties": {
                "op": {
                    "type": "string",
                    "enum": ["add", "modify", "remove"],
                    "description": (
                        "add: create a new form field. "
                        "modify: update an existing form field. "
                        "remove: delete an existing form field."
                    ),
                },
                "field_name": {"type": "string", "minLength": 1},
                "field_payload": _build_form_field_payload_schema(),
            },
        },
    }


def _build_form_field_payload_schema() -> dict[str, Any]:
    return {
        "type": ["object", "null"],
        "additionalProperties": False,
        "properties": {
            "label": {"type": "string"},
            "field_type": {
                "type": "string",
                "enum": builder_form_field_type_values(),
            },
            "required": {"type": "boolean"},
            "description": {"type": "string"},
            "options": {
                "type": "array",
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
    """Schema for add_payload (shared typed draft for new steps)."""
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


def _build_patch_schema(
    model_refs: list[str] | None,
    kb_refs: list[str] | None,
    mcp_server_refs: list[str] | None,
    mcp_tool_refs: list[str] | None,
) -> dict[str, Any]:
    """Schema for patch (partial update for modify operations)."""
    assistant_spec = _build_assistant_spec_schema(
        model_refs,
        kb_refs,
        mcp_server_refs,
        mcp_tool_refs,
    )

    return {
        "type": "object",
        "description": (
            "Partial update for existing steps (modify operations). "
            "Only include fields you want to change. "
            "Use typed `uses_previous_fields` for field-level reuse from earlier "
            "JSON-producing steps; do not author raw `input_bindings`."
        ),
        "properties": {
            "name": {"type": "string"},
            "assistant_spec": assistant_spec,
            "input_source": {
                "type": "string",
                "enum": builder_input_source_values(),
            },
            "input_type": {
                "type": "string",
                "enum": builder_input_type_values(),
            },
            "uses_form_fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional form field variable names this existing step should reuse in its compiled underlag.",
            },
            "uses_previous_fields": build_previous_field_refs_schema(),
            "output_type": {
                "type": "string",
                "enum": builder_output_type_values(),
            },
            "document_delivery_mode": {
                "type": "string",
                "enum": document_delivery_mode_values(),
                "description": (
                    "How a DOCX/PDF output should be produced. Use 'generated' for normal "
                    "generated DOCX/PDF and 'template_fill' only when filling a DOCX template. "
                    "Do not use this for human review checkpoints; use review_mode."
                ),
            },
            "output_config": {
                "type": ["object", "null"],
                "description": (
                    "Optional output configuration patch. Use null when you want to clear "
                    "the existing output_config for this step."
                ),
                "additionalProperties": True,
            },
            "review_mode": build_review_mode_schema(),
        },
    }


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
