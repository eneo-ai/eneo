"""Generated LLM reference for the AI Builder's Flow capability surface."""

from __future__ import annotations

import json
from typing import Any

from intric.flows.ai_builder.ai_builder_flow_schema_values import (
    builder_input_source_values,
    builder_input_type_values,
    builder_output_mode_values,
    builder_output_type_values,
    document_delivery_mode_values,
)
from intric.flows.ai_builder.ai_builder_tools import active_submission_tool_name
from intric.flows.flow_capability_manifest import CAPABILITY_REGISTRY


def build_structured_reference_payload(*, is_edit_mode: bool) -> dict[str, Any]:
    """Return the compact prompt reference from typed Flow sources.

    This is intentionally generated from enums and the Flow Capability
    Manifest so adding/removing builder-exposed Flow capabilities does
    not require a second hand-maintained prompt edit.
    """
    payload: dict[str, Any] = {
        "tool_protocol": {
            "submission_tool": active_submission_tool_name(is_edit_mode=is_edit_mode),
            "question_action_kind": "ask_question",
        },
        "flow_capability_source": "AI Builder schema values + Flow Capability Manifest",
        "input_type": builder_input_type_values(),
        "output_type": builder_output_type_values(),
        "builder_capabilities": sorted(
            cap.id for cap in CAPABILITY_REGISTRY.values() if cap.exposure == "builder"
        ),
    }
    if is_edit_mode:
        payload["input_source"] = builder_input_source_values()
        payload["output_mode"] = builder_output_mode_values()
        payload["hard_rules"] = [
            "only describe changes to existing flow state",
            "use add/modify/remove operations",
            "use existing_step refs only when targeting an existing step",
            "use typed add_payload drafts for new steps instead of raw StepSpec fields",
            "template_fill requires docx output",
        ]
        return payload

    payload["document_delivery_mode"] = document_delivery_mode_values()
    payload["structured_output_fields"] = [
        "name",
        "field_type",
        "description",
        "required",
        "fields",
        "item_fields",
    ]
    payload["hard_rules"] = [
        "do not emit raw JSON Schema",
        "do not emit raw input_config or output_config dicts",
        "do not emit plan_step_ref values",
        "do not emit input_bindings or template variables like {{ ... }}",
        "do not emit input_source in create mode; backend derives step topology",
        "input_fields are secondary runtime parameters only, not the primary material being processed",
        "output_fields are only for json output",
        "output_fields max nesting depth is 3",
        "template_fill requires docx output",
    ]
    return payload


def render_structured_reference_block(*, is_edit_mode: bool) -> str:
    payload = build_structured_reference_payload(is_edit_mode=is_edit_mode)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"# Strukturerad referens\n\n```json\n{rendered}\n```"


__all__ = [
    "build_structured_reference_payload",
    "render_structured_reference_block",
]
