"""Lower the edit tool's wire arguments into the canonical edit proposal.

The wire contract is strict-shaped: every property is present and ``null``
means "keep the current value". The canonical ``OrderedEditProposal`` reads
omission as "keep" (``model_fields_set`` drives the patch semantics in the
authoring projection), so this adapter drops keep-nulls, maps the wire's
explicit clear values onto the canonical ones (``review_mode: "none"`` is a
cleared policy, an empty list is a cleared list) and lowers the provider field
tree into ``StructuredFieldDraft``. It runs for every route, so one admission
contract holds whether or not the provider enforced the schema natively.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    ProposalStructuredFieldIntent,
)
from eneo.flows.ai_builder.ai_builder_step_tool_schema_fragments import (
    REVIEW_MODE_NONE,
)

_FLOW_KEEP_NULL = ("flow_name", "flow_description", "form_fields")
_MODIFY_KEEP_NULL = (
    "name",
    "assistant_spec",
    "input_source",
    "input_type",
    "output_type",
    "document_delivery_mode",
    "uses_form_fields",
    "uses_previous_fields",
    "output_fields",
    "review_mode",
)
_ASSISTANT_KEEP_NULL = ("instructions", "knowledge_refs")
_ADD_KEEP_NULL = (
    "output_type",
    "output_fields",
    "uses_form_fields",
    "model_ref",
    "knowledge_refs",
    "review_mode",
)


def lower_edit_tool_arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    lowered = _without_keep_nulls(arguments, _FLOW_KEEP_NULL)
    form_fields = lowered.get("form_fields")
    if isinstance(form_fields, list):
        lowered["form_fields"] = [
            {**cast(dict[str, Any], field), "provenance": "model_proposed"}
            if isinstance(field, dict)
            else field
            for field in cast(list[Any], form_fields)
        ]
    steps = lowered.get("steps")
    if isinstance(steps, list):
        lowered["steps"] = [_lower_step(step) for step in cast(list[Any], steps)]
    return lowered


def _lower_step(step: Any) -> Any:
    if not isinstance(step, dict):
        return step
    typed = cast(dict[str, Any], step)
    if typed.get("kind") == "keep":
        # A step the turn leaves as it is: the canonical proposal lists it as
        # a modify that changes nothing.
        return {"kind": "modify", "existing_step_ref": typed.get("existing_step_ref")}
    if typed.get("kind") == "modify":
        return _lower_modify_step(typed)
    if typed.get("kind") == "add" and isinstance(typed.get("step"), dict):
        return {**typed, "step": _lower_added_step(cast(dict[str, Any], typed["step"]))}
    return typed


def _lower_modify_step(step: dict[str, Any]) -> dict[str, Any]:
    lowered = _without_keep_nulls(step, _MODIFY_KEEP_NULL)
    assistant_spec = lowered.get("assistant_spec")
    if isinstance(assistant_spec, dict):
        patch = _without_keep_nulls(
            cast(dict[str, Any], assistant_spec), _ASSISTANT_KEEP_NULL
        )
        # An assistant patch that changes nothing is no patch.
        if patch:
            lowered["assistant_spec"] = patch
        else:
            del lowered["assistant_spec"]
    if "output_fields" in lowered:
        lowered["output_fields"] = _lower_field_tree(lowered["output_fields"])
    if lowered.get("review_mode") == REVIEW_MODE_NONE:
        # Present and None: the projection reads an explicit clear.
        lowered["review_mode"] = None
    return lowered


def _lower_added_step(step: dict[str, Any]) -> dict[str, Any]:
    lowered = _without_keep_nulls(step, _ADD_KEEP_NULL)
    if lowered.get("review_mode") == REVIEW_MODE_NONE:
        del lowered["review_mode"]
    if "output_fields" in lowered:
        lowered["output_fields"] = _lower_field_tree(lowered["output_fields"])
    return lowered


def _lower_field_tree(value: Any) -> Any:
    """Provider field tree (``children``) to authoring drafts; other shapes pass
    through for the canonical validator to refuse."""

    if not isinstance(value, list):
        return value
    return [
        ProposalStructuredFieldIntent.model_validate(item).to_structured_field_draft()
        if isinstance(item, dict)
        else item
        for item in cast(list[Any], value)
    ]


def _without_keep_nulls(
    value: Mapping[str, Any], keep_null_keys: tuple[str, ...]
) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if not (item is None and key in keep_null_keys)
    }


__all__ = ["lower_edit_tool_arguments"]
