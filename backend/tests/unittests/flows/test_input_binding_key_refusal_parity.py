"""Publish validation and the runtime parser refuse the same input_bindings."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from eneo.flows.domain.flow_step_validation import FlowStepValidationError
from eneo.flows.flow_validators import (
    _validate_supported_input_binding_keys as validate_at_publish,  # pyright: ignore[reportPrivateUsage]
)
from eneo.flows.input_binding_contract_rules import (
    FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
    input_binding_key_refusal,
)
from eneo.flows.runtime.step_definition_parser import (
    _validate_supported_input_binding_keys as validate_at_runtime,  # pyright: ignore[reportPrivateUsage]
)
from eneo.main.exceptions import BadRequestException

_VALID_REF = {"step_ref": "step_1", "output": "text"}

ACCEPTED: list[object] = [
    None,
    {},
    {"question": "{{ flow_input.text }}"},
    {"source_refs": [_VALID_REF]},
    {"question": "q", "source_refs": [_VALID_REF]},
    "not-a-mapping",
]
REFUSED: list[tuple[object, str]] = [
    ({"text": "{{ flow_input.text }}"}, "text"),
    ({"question": "q", "extra": 1}, "extra"),
    ({1: "bad"}, "1"),
    ({"source_refs": "nope"}, "source_refs"),
    ({"source_refs": [{"step_ref": "step_1", "output": "json"}]}, "source_refs"),
    ({"source_refs": [{**_VALID_REF, "bogus": 1}]}, "source_refs"),
    ({"source_refs": ["not-an-object"]}, "source_refs"),
]


@pytest.mark.parametrize("bindings", ACCEPTED)
def test_all_three_accept_valid_bindings(bindings: object) -> None:
    assert input_binding_key_refusal(bindings) is None
    validate_at_runtime(cast(Any, SimpleNamespace(input_bindings=bindings)))
    validate_at_publish(
        step=cast(Any, SimpleNamespace(step_order=2, input_bindings=bindings))
    )


@pytest.mark.parametrize(("bindings", "key"), REFUSED)
def test_both_callers_refuse_what_the_rule_refuses(bindings: object, key: str) -> None:
    refusal = input_binding_key_refusal(bindings)
    assert refusal is not None
    assert refusal.key == key

    with pytest.raises(BadRequestException) as runtime:
        validate_at_runtime(cast(Any, SimpleNamespace(input_bindings=bindings)))
    with pytest.raises(FlowStepValidationError) as publish:
        validate_at_publish(
            step=cast(Any, SimpleNamespace(step_order=2, input_bindings=bindings))
        )

    expected_context = {"field": "input_bindings", "key": key}
    for raised in (runtime.value, publish.value):
        assert raised.code == FLOW_INPUT_BINDING_UNSUPPORTED_KEY
        assert raised.context == expected_context
        assert str(refusal) in str(raised)
    assert str(publish.value).startswith("Step 2: ")
