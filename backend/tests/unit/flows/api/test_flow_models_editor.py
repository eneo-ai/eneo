"""The editor update request as the core receives it."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from eneo.flows.api.flow_models import FlowEditorNewStep


def _new_step(name: str) -> FlowEditorNewStep:
    return FlowEditorNewStep.model_validate(
        {"name": name, "configuration": {"input_type": "text"}}
    )


def test_new_step_name_is_kept_without_surrounding_blanks() -> None:
    assert _new_step("  Sammanfatta ").name == "Sammanfatta"


def test_new_step_needs_a_name_that_is_not_blank() -> None:
    with pytest.raises(ValidationError):
        _new_step("   ")
