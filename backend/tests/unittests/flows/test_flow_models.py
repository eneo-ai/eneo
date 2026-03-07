from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from intric.flows.api.flow_models import FlowStepCreateRequest


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "assistant_id": str(uuid4()),
        "step_order": 1,
        "input_source": "flow_input",
        "input_type": "text",
        "output_mode": "pass_through",
        "output_type": "json",
        "mcp_policy": "inherit",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input_source", "banana"),
        ("input_type", "banana"),
        ("output_mode", "banana"),
        ("output_type", "banana"),
        ("mcp_policy", "banana"),
    ],
)
def test_flow_step_create_request_rejects_invalid_enum_values(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        FlowStepCreateRequest.model_validate(_payload(**{field: value}))
