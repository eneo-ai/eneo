from __future__ import annotations

import pytest

from eneo.flows.flow_validators_template import validate_template_placeholder_bindings
from eneo.main.exceptions import BadRequestException


def _refusal(bindings: object, names: list[str] | None = None) -> str:
    with pytest.raises(BadRequestException) as refused:
        validate_template_placeholder_bindings(
            step_order=3, placeholder_names=names or ["a"], bindings=bindings
        )
    return str(refused.value)


def test_every_placeholder_the_file_holds_needs_a_binding() -> None:
    validate_template_placeholder_bindings(
        step_order=3, placeholder_names=["a", "b"], bindings={"a": "{{ x }}", "b": ""}
    )

    assert _refusal({"a": "{{ x }}"}, ["a", "b"]) == (
        "Step 3: template placeholders are missing bindings: b."
    )


@pytest.mark.parametrize(
    ("bindings", "message"),
    [
        (None, "Step 3: output_config.bindings must be an object."),
        (["a"], "Step 3: output_config.bindings must be an object."),
        (
            {"a": "x", " ": "y"},
            "Step 3: output_config.bindings keys must be non-empty strings.",
        ),
        (
            {"a": 1},
            "Step 3: binding 'a' must be a template expression or an explicit empty string.",
        ),
    ],
)
def test_the_bindings_must_be_an_object_of_strings(
    bindings: object, message: str
) -> None:
    assert _refusal(bindings) == message
