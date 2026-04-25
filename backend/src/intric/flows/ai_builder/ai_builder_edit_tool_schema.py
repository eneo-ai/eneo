"""Dynamic edit-mode tool schema builder for the AI Builder.

Builds the `edit_flow` tool schema with dynamic constraints based on the
current flow state. By injecting valid step refs as enum values, the LLM
cannot generate an invalid ref — the API layer rejects it before validation.
"""

from __future__ import annotations

from typing import Any

from intric.flows.ai_builder.ai_builder_flow_name import MAX_FLOW_NAME_LENGTH
from intric.flows.ai_builder.ai_builder_flow_schema_values import (
    builder_input_source_values,
    builder_input_type_values,
    builder_output_mode_values,
    builder_output_type_values,
)
from intric.flows.ai_builder.ai_builder_new_step_schema import (
    build_new_step_draft_schema,
    small_ref_enums,
)
from intric.flows.domain.flow import FlowStep

EDIT_FLOW_TOOL_NAME = "edit_flow"


def build_edit_flow_tool_schema(
    current_steps: list[FlowStep],
    available_models: list[dict[str, Any]] | None = None,
    available_kbs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the edit_flow tool schema with dynamic constraints.

    Args:
        current_steps: Existing flow steps (for valid ref enums).
        available_models: Available model refs (for model_ref enum).
        available_kbs: Available KB refs (for knowledge_refs enum).
    """
    valid_refs = [f"existing_step_{s.step_order}" for s in current_steps]
    # Include None for add operations where target_ref should be absent
    target_ref_enum: list[str | None] = valid_refs + [None]
    anchor_ref_enum: list[str | None] = valid_refs + [None]

    model_refs = small_ref_enums(available_models)
    kb_refs = small_ref_enums(available_kbs)

    step_payload_schema = _build_step_payload_schema(model_refs, kb_refs)

    return {
        "type": "function",
        "function": {
            "name": EDIT_FLOW_TOOL_NAME,
            "description": (
                "Edit an existing flow. Describe only the steps or flow properties that truly change — "
                "the backend preserves everything else. Each operation targets "
                "a specific step by its ref. Unmentioned steps are kept as-is. "
                "When you change output_type or output_mode, clear or omit incompatible "
                "output_config fields instead of rewriting unrelated step config."
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
                            "List of step operations. Each operation is add, modify, or remove."
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
                                "patch": _build_patch_schema(model_refs, kb_refs),
                            },
                        },
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
    available_models: list[dict[str, Any]] | None = None,
    available_kbs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build the full tool set for edit mode.

    Includes edit_flow + ask_structured_question + confirm_requirements.
    """
    from intric.flows.ai_builder.ai_builder_tools import (
        build_ask_structured_question_tool_schema,
        build_confirm_requirements_tool_schema,
    )

    return [
        build_edit_flow_tool_schema(current_steps, available_models, available_kbs),
        build_ask_structured_question_tool_schema(),
        build_confirm_requirements_tool_schema(),
    ]


# ---------------------------------------------------------------------------
# Internal schema builders
# ---------------------------------------------------------------------------


def _build_step_payload_schema(
    model_refs: list[str] | None,
    kb_refs: list[str] | None,
) -> dict[str, Any]:
    """Schema for add_payload (shared typed draft for new steps)."""
    return build_new_step_draft_schema(
        model_refs=model_refs,
        kb_refs=kb_refs,
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
        expose_previous_field_refs=False,
    )


def _build_patch_schema(
    model_refs: list[str] | None,
    kb_refs: list[str] | None,
) -> dict[str, Any]:
    """Schema for patch (partial update for modify operations)."""
    assistant_spec = _build_assistant_spec_schema(model_refs, kb_refs)

    return {
        "type": "object",
        "description": (
            "Partial update for existing steps (modify operations). "
            "Only include fields you want to change. "
            "Do not author raw `input_bindings` or field-level previous-step paths; "
            "the backend preserves and derives mechanical dataflow wiring."
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
            "output_mode": {
                "type": "string",
                "enum": builder_output_mode_values(),
            },
            "output_type": {
                "type": "string",
                "enum": builder_output_type_values(),
            },
            "output_config": {
                "type": ["object", "null"],
                "description": (
                    "Optional output configuration patch. Use null when you want to clear "
                    "the existing output_config for this step."
                ),
                "additionalProperties": True,
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
            "model_ref": {
                "type": ["string", "null"],
                "description": "Model alias, or null for space default.",
            },
            "knowledge_refs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Knowledge base aliases to attach.",
            },
        },
    }

    # Inject dynamic enums for small lists
    if model_refs is not None:
        schema["properties"]["model_ref"]["enum"] = model_refs + [None]
    if kb_refs is not None:
        schema["properties"]["knowledge_refs"]["items"]["enum"] = kb_refs

    return schema
