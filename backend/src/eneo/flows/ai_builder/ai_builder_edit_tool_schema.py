"""Dynamic edit-mode proposal schema builder for the AI Builder."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
    build_knowledge_refs_property_schema,
    build_previous_field_refs_schema,
    build_proposal_structured_field_schema,
    build_review_mode_schema,
)
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_name import MAX_FLOW_NAME_LENGTH
from eneo.flows.step_lineage import existing_step_ref_for_order

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_flow_review import ReviewEditScope


def build_edit_flow_tool_schema(
    current_steps: list[FlowStep],
    *,
    resource_catalog: AIBuilderResourceCatalog,
    tool_name: str,
    review_scope: "ReviewEditScope | None" = None,
) -> dict[str, Any]:
    """The edit tool: the complete ordered step list after the edit.

    A turn that acts on review findings is bounded by their scope, and the
    schema offers exactly that: the findings' steps take a full modify, every
    other step is listed with a bare ``keep``, adding and removing appear
    only where the findings allow them, and the flow-level fields are absent.
    Whatever the schema does not offer, a strict provider cannot write, so
    the admission checks refuse nothing the model was invited to write.
    """

    valid_refs = [existing_step_ref_for_order(s.step_order) for s in current_steps]

    model_refs = resource_catalog.small_ref_enum_for_kind("model")
    kb_refs = resource_catalog.small_ref_enum_for_kind("knowledge_base")
    step_payload_schema = build_semantic_step_schema(
        model_refs=model_refs,
        kb_refs=kb_refs,
    )
    modifiable_refs = (
        valid_refs
        if review_scope is None
        else [ref for ref in valid_refs if ref in review_scope.step_refs]
    )
    modify_step_schema = _build_modify_step_schema(
        valid_refs=modifiable_refs,
        kb_refs=kb_refs,
    )
    add_step_schema = {
        "type": "object",
        "required": ["kind", "step"],
        "additionalProperties": False,
        "properties": {
            "kind": {"type": "string", "enum": ["add"]},
            "step": step_payload_schema,
        },
    }
    removable_refs = (
        valid_refs
        if review_scope is None
        else [ref for ref in valid_refs if ref in review_scope.removable_step_refs]
    )

    properties: dict[str, Any] = {
        "plan_rationale": {
            "type": "string",
            "description": (
                "Explain what changes you're making and why, in 1-2 sentences."
            ),
        },
    }
    if review_scope is None:
        properties["flow_name"] = {
            "type": ["string", "null"],
            "maxLength": MAX_FLOW_NAME_LENGTH,
            "description": "New flow name, or null to keep current.",
        }
        properties["flow_description"] = {
            "type": ["string", "null"],
            "description": "New flow description, or null to keep current.",
        }
        properties["steps"] = {
            "type": "array",
            "description": (
                "Complete ordered step list after the edit. Preserve an "
                "existing step with kind=modify and its existing_step_ref; "
                "include only fields that change on that step. Add new "
                "steps with kind=add and a typed step payload."
            ),
            "items": {"anyOf": [modify_step_schema, add_step_schema]},
        }
    else:
        step_branches: list[dict[str, Any]] = [
            modify_step_schema,
            _build_keep_step_schema(valid_refs=valid_refs),
        ]
        if review_scope.may_add:
            step_branches.append(add_step_schema)
        properties["steps"] = {
            "type": "array",
            "description": (
                "Complete ordered step list after the edit, in the current "
                "order. The findings' steps take kind=modify with only the "
                "fields that change; every other existing step is listed with "
                "kind=keep and nothing else."
                + (
                    " Add a step with kind=add only where the findings call for one."
                    if review_scope.may_add
                    else ""
                )
            ),
            "items": {"anyOf": step_branches},
        }
    if removable_refs:
        properties["removed_existing_step_refs"] = {
            "type": "array",
            "items": {"type": "string", "enum": removable_refs},
            "uniqueItems": True,
            "description": (
                "Existing step refs intentionally deleted by this edit. "
                "Omission is never deletion; list every removed ref here."
            ),
        }
    if review_scope is None:
        properties["form_fields"] = {
            "type": ["array", "null"],
            "items": _build_form_field_spec_schema(),
            "description": (
                "Complete desired form field list. Null keeps the current "
                "fields; an empty list clears them; a list adds, modifies "
                "or removes fields by complete state."
            ),
        }
    properties["assumptions"] = {
        "type": "array",
        "items": {"type": "string"},
        "description": "Assumptions made about the edit.",
    }

    description = (
        "Edit an existing flow by returning the complete ordered step list. "
        "Every existing step must appear once in steps unless its ref appears "
        "in removed_existing_step_refs. Null keeps a current value: flow "
        "fields, form_fields and every step field. Set form_fields to the "
        "complete desired list, or an empty list to clear all flow-level "
        "inmatningsfält/form fields."
        if review_scope is None
        else (
            "Answer the selected review findings by returning the complete "
            "ordered step list. Change only the findings' steps; list every "
            "other step with kind=keep. Null keeps a current step field. The "
            "flow's name, description and form fields are not part of this turn."
        )
    )
    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": description,
            "parameters": {
                "type": "object",
                "required": ["steps", "plan_rationale"],
                "additionalProperties": False,
                "properties": properties,
            },
        },
    }


def _build_keep_step_schema(*, valid_refs: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["kind", "existing_step_ref"],
        "additionalProperties": False,
        "properties": {
            "kind": {"type": "string", "enum": ["keep"]},
            "existing_step_ref": {
                "type": "string",
                "enum": valid_refs,
                "description": "A step this turn leaves exactly as it is.",
            },
        },
    }


# ---------------------------------------------------------------------------
# Internal schema builders
# ---------------------------------------------------------------------------


def _build_modify_step_schema(
    *,
    valid_refs: list[str],
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
            "name": {
                "type": ["string", "null"],
                "description": "New step name, or null to keep the current one.",
            },
            "assistant_spec": _build_assistant_spec_schema(kb_refs),
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
                "description": (
                    "Form fields this step should consider. Null keeps the current "
                    "bindings; an empty list clears them."
                ),
            },
            "uses_previous_fields": build_previous_field_refs_schema(),
            "output_fields": {
                "type": ["array", "null"],
                "items": build_proposal_structured_field_schema(),
                "description": (
                    "Complete structured fields of a JSON output step, replacing "
                    "the current contract. Null keeps the current contract; an "
                    "empty list removes it."
                ),
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


def _build_assistant_spec_schema(kb_refs: list[str] | None) -> dict[str, Any]:
    # No model_ref: an existing step's model changes only in the model picker.
    return {
        "type": ["object", "null"],
        "additionalProperties": False,
        "description": "Assistant fields to change; null keeps the assistant as is.",
        "properties": {
            "instructions": {
                "type": ["string", "null"],
                "description": (
                    "What this step's assistant should do; null keeps the current "
                    "instructions."
                ),
            },
            **build_knowledge_refs_property_schema(kb_refs=kb_refs),
        },
    }
