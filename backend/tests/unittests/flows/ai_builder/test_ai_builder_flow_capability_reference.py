from __future__ import annotations

from intric.flows.ai_builder.ai_builder_flow_capability_reference import (
    build_structured_reference_payload,
)
from intric.flows.ai_builder.ai_builder_flow_schema_values import (
    builder_input_source_values,
)
from intric.flows.ai_builder.ai_builder_new_step_models import (
    MAX_STRUCTURED_FIELD_DEPTH,
)


def test_create_reference_keeps_flow_topology_backend_owned() -> None:
    payload = build_structured_reference_payload(is_edit_mode=False)

    assert "input_source" not in payload
    assert "semantic_input_strategy" not in payload
    assert any(
        "backend derives step topology" in rule for rule in payload["hard_rules"]
    )
    assert any("secondary runtime parameters" in rule for rule in payload["hard_rules"])
    assert (
        f"output_fields max nesting depth is {MAX_STRUCTURED_FIELD_DEPTH}"
        in payload["hard_rules"]
    )


def test_edit_reference_exposes_flow_input_sources() -> None:
    payload = build_structured_reference_payload(is_edit_mode=True)

    assert payload["input_source"] == builder_input_source_values()
    assert "semantic_input_strategy" not in payload


def test_edit_reference_uses_ordered_edit_contract_terms() -> None:
    payload = build_structured_reference_payload(is_edit_mode=True)
    hard_rules = "\n".join(payload["hard_rules"])

    assert "operations" not in hard_rules
    assert "add_payload" not in hard_rules
    assert "kind=modify" in hard_rules
    assert "kind=add" in hard_rules
    assert "removed_existing_step_refs" in hard_rules
    assert "omission is never deletion" in hard_rules
