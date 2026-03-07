from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from intric.flows.runtime.models import RunExecutionState
from intric.flows.runtime.step_input_resolution import (
    enforce_inline_input_cap,
    resolve_input_source_text,
)
from intric.main.exceptions import TypedIOValidationException


def test_enforce_inline_input_cap_counts_utf8_bytes_not_characters():
    with pytest.raises(TypedIOValidationException) as exc:
        enforce_inline_input_cap(
            text="ååå",
            step_order=2,
            input_source="flow_input",
            max_inline_text_bytes=5,
        )

    assert exc.value.code == "typed_io_input_too_large"


def test_resolve_input_source_text_serializes_non_text_flow_payload():
    run = SimpleNamespace(id=uuid4(), input_payload_json={"number": 7, "enabled": True})

    resolved = resolve_input_source_text(
        input_source="flow_input",
        run=run,
        step_order=1,
        prior_results=[],
        state=None,
        logger=MagicMock(),
    )

    assert resolved == '{"number": 7, "enabled": true}'


def test_resolve_input_source_text_all_previous_steps_prefers_state_accumulator():
    run = SimpleNamespace(id=uuid4(), input_payload_json=None)
    prior_results = [
        SimpleNamespace(step_order=1, output_payload_json={"text": "older"}),
        SimpleNamespace(step_order=2, output_payload_json={"text": "newer"}),
    ]
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        all_previous_segments=["<step_1_output>\nfrom-state\n</step_1_output>\n"],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )

    resolved = resolve_input_source_text(
        input_source="all_previous_steps",
        run=run,
        step_order=3,
        prior_results=prior_results,
        state=state,
        logger=MagicMock(),
    )

    assert resolved == "<step_1_output>\nfrom-state\n</step_1_output>\n"
