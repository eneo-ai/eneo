"""Dynamic edit-mode proposal schema builder for the AI Builder."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from eneo.flows.ai_builder.ai_builder_flow_schema_values import (
    builder_form_field_type_values,
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
from eneo.flows.flow_capability_manifest import CapabilityProjection, projection_values
from eneo.flows.step_lineage import existing_step_ref_for_order

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_flow_review import ReviewEditScope
    from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
        EditOperationPermissions,
    )


_EDIT_READS_DESCRIPTION = (
    "Change reads only when requested. Keep both lists null to preserve saved "
    "input when its source and type are unchanged. Empty lists replace saved "
    "explicit reads. Setting either list, or changing input_source or input_type, "
    "rebuilds the entire input: "
    "give both lists complete, including every read to retain. If the saved "
    "input cannot be restated exactly, keep input_source, input_type, "
    "uses_form_fields and uses_previous_fields null."
)


def build_edit_flow_tool_schema(
    current_steps: list[FlowStep],
    *,
    resource_catalog: AIBuilderResourceCatalog,
    tool_name: str,
    review_scope: "ReviewEditScope | None" = None,
    permissions: "EditOperationPermissions | None" = None,
) -> dict[str, Any]:
    """One local-command grammar, narrowed by the turn's existing permissions."""
    if review_scope is not None and permissions is not None:
        raise ValueError("Supply either review_scope or permissions, not both.")
    permissions = permissions if permissions is not None else review_scope
    valid_refs = [existing_step_ref_for_order(s.step_order) for s in current_steps]
    if permissions is not None and (
        absent := permissions.step_refs.difference(valid_refs)
    ):
        raise ValueError(f"edit scope names absent steps: {sorted(absent)}")
    modifiable_refs = (
        valid_refs
        if permissions is None
        else [ref for ref in valid_refs if ref in permissions.step_refs]
    )
    kb_refs = resource_catalog.small_ref_enum_for_kind("knowledge_base")
    target_schema = _build_target_schema(valid_refs)
    placement_schema = {
        "anyOf": [
            {
                "type": "object",
                "required": ["kind"],
                "additionalProperties": False,
                "properties": {"kind": {"type": "string", "enum": ["start"]}},
            },
            {
                "type": "object",
                "required": ["kind", "target"],
                "additionalProperties": False,
                "properties": {
                    "kind": {"type": "string", "enum": ["after"]},
                    "target": target_schema,
                },
            },
        ]
    }
    branches = [_build_modify_step_schema(valid_refs=modifiable_refs, kb_refs=kb_refs)]
    branches[0]["properties"]["uses_previous_fields"] = _build_edit_field_reads_schema(
        target_schema
    )
    if permissions is None or permissions.may_add:
        branches.append(
            {
                "type": "object",
                "required": ["kind", "local_id", "placement", "step"],
                "additionalProperties": False,
                "properties": {
                    "kind": {"type": "string", "enum": ["add"]},
                    "local_id": {"type": "string", "minLength": 1},
                    "placement": placement_schema,
                    "step": build_semantic_step_schema(
                        kb_refs=kb_refs, producer_schema=target_schema
                    ),
                },
            }
        )
    removable_refs = (
        valid_refs
        if permissions is None
        else [ref for ref in valid_refs if ref in permissions.removable_step_refs]
    )
    if removable_refs:
        branches.append(
            {
                "type": "object",
                "required": ["kind", "existing_step_ref"],
                "additionalProperties": False,
                "properties": {
                    "kind": {"type": "string", "enum": ["remove"]},
                    "existing_step_ref": {"type": "string", "enum": removable_refs},
                },
            }
        )
    if permissions is None or permissions.may_move:
        branches.append(
            {
                "type": "object",
                "required": ["kind", "existing_step_ref", "placement"],
                "additionalProperties": False,
                "properties": {
                    "kind": {"type": "string", "enum": ["move"]},
                    "existing_step_ref": {"type": "string", "enum": modifiable_refs},
                    "placement": placement_schema,
                },
            }
        )
    if permissions is None:
        branches.append(
            {
                "type": "object",
                "required": ["kind"],
                "additionalProperties": False,
                "properties": {
                    "kind": {"type": "string", "enum": ["modify_flow"]},
                    "flow_name": {
                        "type": ["string", "null"],
                        "maxLength": MAX_FLOW_NAME_LENGTH,
                    },
                    "flow_description": {"type": ["string", "null"]},
                    "form_fields": {
                        "type": ["array", "null"],
                        "items": _build_form_field_spec_schema(),
                        "description": "Complete desired form fields; null keeps, an empty list clears.",
                    },
                },
            }
        )
    properties: dict[str, Any] = {
        "plan_rationale": {"type": "string", "minLength": 1},
        "operations": {
            "type": "array",
            "items": branches[0] if len(branches) == 1 else {"anyOf": branches},
            "description": (
                "Only the explicit changes against the saved baseline. Unmentioned steps stay. "
                "modify changes step fields; modify_flow changes only requested flow metadata or form fields. "
                "add inserts a step absent from the saved flow, including "
                "one retained from a prior preview, with a unique local_id "
                "and name; remove explicitly deletes; move explicitly reorders. Placements "
                "refer to saved or previously added identities. Do not reconstruct saved steps as adds. "
                "Reads name producer identities, never numeric positions."
            ),
        },
        "assumptions": {"type": "array", "items": {"type": "string"}},
    }
    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": (
                "Edit through local commands. The server preserves unmentioned steps and builds "
                "the complete draft. Null keeps a current field; explicit lists replace it. "
                "Whole-flow later turns and selected added-step revisions use cumulative commands against the saved flow, "
                "not against a prior preview. Selected saved-step revisions that retain the "
                "saved sequence use the shown revision."
            ),
            "parameters": {
                "type": "object",
                "required": ["operations", "plan_rationale"],
                "additionalProperties": False,
                "properties": properties,
            },
        },
    }


def _build_target_schema(valid_refs: list[str]) -> dict[str, object]:
    return {
        "anyOf": [
            {
                "type": "object",
                "required": ["kind", "existing_step_ref"],
                "additionalProperties": False,
                "properties": {
                    "kind": {"type": "string", "enum": ["saved"]},
                    "existing_step_ref": {"type": "string", "enum": valid_refs},
                },
            },
            {
                "type": "object",
                "required": ["kind", "local_id"],
                "additionalProperties": False,
                "properties": {
                    "kind": {"type": "string", "enum": ["added"]},
                    "local_id": {"type": "string", "minLength": 1},
                },
            },
        ]
    }


def _build_edit_field_reads_schema(target_schema: dict[str, object]) -> dict[str, Any]:
    schema = build_previous_field_refs_schema()
    schema["description"] = (
        "Fields of earlier JSON-producing steps this step reads. "
        + _EDIT_READS_DESCRIPTION
    )
    item = schema["items"]
    item["properties"].pop("from_step")
    item["properties"]["producer"] = target_schema
    item["required"] = ["producer", "field_path"]
    return schema


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
                "enum": [
                    *projection_values(
                        CapabilityProjection.EDITABLE_EXISTING, "input_source"
                    ),
                    None,
                ],
            },
            "input_type": {
                "type": ["string", "null"],
                "enum": [
                    *projection_values(
                        CapabilityProjection.EDITABLE_EXISTING, "input_type"
                    ),
                    None,
                ],
            },
            "output_type": {
                "type": ["string", "null"],
                "enum": [
                    *projection_values(
                        CapabilityProjection.EDITABLE_EXISTING, "output_type"
                    ),
                    None,
                ],
            },
            "document_delivery_mode": {
                "type": ["string", "null"],
                "enum": [*document_delivery_mode_values(), None],
            },
            "uses_form_fields": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": (
                    "Form fields this step reads. " + _EDIT_READS_DESCRIPTION
                ),
            },
            "uses_previous_fields": build_previous_field_refs_schema(),
            "output_fields": {
                "type": ["array", "null"],
                "items": build_proposal_structured_field_schema(),
                "description": (
                    "Complete structured fields of a JSON output step. Supported "
                    "restatements keep the full saved contract, including annotations "
                    "and constraints. Description-only changes are unsupported; report "
                    "any requested description change this operation cannot apply. "
                    "A different non-empty tree is supported only "
                    "when the saved constraints are representable by these fields. "
                    "Null keeps the current contract; an empty list removes it."
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
            "options": {"type": "array", "items": {"type": "string"}},
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
