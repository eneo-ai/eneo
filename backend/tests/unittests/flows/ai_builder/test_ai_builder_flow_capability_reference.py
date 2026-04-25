from __future__ import annotations

from intric.flows.ai_builder.ai_builder_flow_capability_reference import (
    build_structured_reference_payload,
)
from intric.flows.ai_builder.ai_builder_flow_schema_values import (
    builder_input_source_values,
)


def test_create_reference_keeps_flow_topology_backend_owned() -> None:
    payload = build_structured_reference_payload(is_edit_mode=False)

    assert "input_source" not in payload
    assert "semantic_input_strategy" not in payload
    assert any(
        "backend derives step topology" in rule for rule in payload["hard_rules"]
    )


def test_edit_reference_exposes_flow_input_sources() -> None:
    payload = build_structured_reference_payload(is_edit_mode=True)

    assert payload["input_source"] == builder_input_source_values()
    assert "semantic_input_strategy" not in payload
