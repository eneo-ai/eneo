from __future__ import annotations

from uuid import uuid4

import pytest

from intric.flows.runtime.step_definition_parser import parse_runtime_steps
from intric.main.exceptions import BadRequestException


def _step_snapshot(**overrides: object) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "step_id": str(uuid4()),
        "step_order": 1,
        "assistant_id": str(uuid4()),
        "input_source": "flow_input",
        "output_mode": "pass_through",
    }
    snapshot.update(overrides)
    return snapshot


def _definition(*steps: dict[str, object]) -> dict[str, object]:
    return {"steps": list(steps)}


def test_parse_runtime_steps_rejects_invalid_output_mode():
    with pytest.raises(BadRequestException, match="Unsupported output mode"):
        parse_runtime_steps(_definition(_step_snapshot(output_mode="invalid_mode")))


def test_parse_runtime_steps_scopes_invalid_step_identifier():
    with pytest.raises(BadRequestException) as exc_info:
        parse_runtime_steps(
            _definition(
                _step_snapshot(
                    step_id="not-a-uuid",
                    user_description="Analysera bakgrund",
                )
            )
        )

    assert str(exc_info.value) == (
        "Step 1 (Analysera bakgrund): Invalid step identifiers in flow snapshot."
    )
    assert exc_info.value.context == {
        "step_order": 1,
        "step_description": "Analysera bakgrund",
    }


def test_parse_runtime_steps_rejects_invalid_input_type():
    with pytest.raises(BadRequestException, match="Unsupported input type"):
        parse_runtime_steps(_definition(_step_snapshot(input_type="banana")))


def test_parse_runtime_steps_rejects_invalid_output_type():
    with pytest.raises(BadRequestException, match="Unsupported output type"):
        parse_runtime_steps(_definition(_step_snapshot(output_type="banana")))


def test_parse_runtime_steps_accepts_transcribe_only_output_mode():
    parsed = parse_runtime_steps(
        _definition(
            _step_snapshot(
                input_type="audio",
                output_type="text",
                output_mode="transcribe_only",
            )
        )
    )

    assert len(parsed) == 1
    assert parsed[0].output_mode == "transcribe_only"


def test_parse_runtime_steps_accepts_step_timeout():
    parsed = parse_runtime_steps(_definition(_step_snapshot(timeout_seconds=1800)))

    assert parsed[0].timeout_seconds == 1800


def test_parse_runtime_steps_rejects_boolean_step_timeout():
    with pytest.raises(BadRequestException, match="timeout_seconds must be an integer"):
        parse_runtime_steps(_definition(_step_snapshot(timeout_seconds=True)))


def test_parse_runtime_steps_rejects_non_object_webhook_headers():
    with pytest.raises(
        BadRequestException, match="output_config.headers must be an object"
    ):
        parse_runtime_steps(
            _definition(
                _step_snapshot(
                    output_mode="http_post",
                    output_config={
                        "url": "https://example.org",
                        "headers": "not-an-object",
                    },
                )
            )
        )


def test_parse_runtime_steps_rejects_all_previous_steps_json_input():
    with pytest.raises(
        BadRequestException, match="incompatible with input_source 'all_previous_steps'"
    ):
        parse_runtime_steps(
            _definition(
                _step_snapshot(
                    step_order=1,
                    input_type="text",
                    output_type="text",
                ),
                _step_snapshot(
                    step_order=2,
                    input_source="all_previous_steps",
                    input_type="json",
                    output_type="text",
                ),
            )
        )


def test_parse_runtime_steps_rejects_incompatible_previous_step_chain():
    with pytest.raises(BadRequestException, match="incompatible type chain"):
        parse_runtime_steps(
            _definition(
                _step_snapshot(
                    step_order=1,
                    input_type="text",
                    output_type="docx",
                ),
                _step_snapshot(
                    step_order=2,
                    input_source="previous_step",
                    input_type="json",
                    output_type="text",
                ),
            )
        )


def test_parse_runtime_steps_rejects_duplicate_step_orders():
    with pytest.raises(BadRequestException, match="Duplicate step_order detected"):
        parse_runtime_steps(
            _definition(
                _step_snapshot(step_order=1),
                _step_snapshot(step_order=1),
            )
        )


def test_parse_runtime_steps_rejects_non_contiguous_step_orders():
    with pytest.raises(
        BadRequestException, match="Step order must be contiguous and start at 1"
    ):
        parse_runtime_steps(
            _definition(
                _step_snapshot(step_order=1),
                _step_snapshot(step_order=3, input_source="previous_step"),
            )
        )


def test_parse_runtime_steps_includes_typed_fields():
    steps = parse_runtime_steps(
        _definition(
            _step_snapshot(
                output_type="json",
                output_contract={"type": "object"},
                input_type="document",
                input_contract={"type": "string"},
            )
        )
    )

    assert steps[0].output_type == "json"
    assert steps[0].output_contract == {"type": "object"}
    assert steps[0].input_type == "document"
    assert steps[0].input_contract == {"type": "string"}


def test_parse_runtime_steps_includes_publish_assistant_snapshot():
    assistant_snapshot = {
        "schema_version": 1,
        "instructions": "Pinned at publish time.",
        "mcp_tools": [],
        "tool_surface_hash": "abc",
        "execution_surface_hash": "def",
    }

    steps = parse_runtime_steps(
        _definition(_step_snapshot(assistant_snapshot=assistant_snapshot))
    )

    assert steps[0].step_order == 1
    assert steps[0].assistant_snapshot == assistant_snapshot


def test_parse_runtime_steps_defaults_typed_fields():
    steps = parse_runtime_steps(_definition(_step_snapshot()))

    assert steps[0].output_type == "text"
    assert steps[0].output_contract is None
    assert steps[0].input_type == "text"
    assert steps[0].input_contract is None
