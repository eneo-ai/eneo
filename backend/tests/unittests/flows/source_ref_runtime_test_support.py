"""What the runtime hands a step that reads earlier steps by source ref.

The oracle of a source-ref edit test is the runtime's own input resolution,
not a second reading of the step ref: each earlier step has completed with a
text that names it, and the reader's resolved input says which one it read.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from eneo.flows.domain.flow import FlowRun, FlowStepResult, FlowStepResultStatus
from eneo.flows.runtime.executor import RuntimeStep
from eneo.flows.runtime.step_input_resolution import resolve_step_input_binding
from eneo.flows.variable_resolver import FlowVariableResolver


def completed_result(step_order: int, text: str) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        current_attempt_no=1,
        input_payload_json={"text": ""},
        effective_prompt="",
        output_payload_json={"text": text},
        model_parameters_json={},
        num_tokens_input=1,
        num_tokens_output=1,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash="hash",
        created_at=now,
        updated_at=now,
    )


def runtime_source_ref_text(
    input_bindings: Mapping[str, Any] | None,
    *,
    reader_order: int,
    text_by_order: Mapping[int, str],
) -> str:
    """The input a compose_text step at `reader_order` resolves from its source
    refs when each earlier step has completed with `text_by_order`. Raises the
    runtime's TypedIOValidationException when a ref names no step."""

    reader = RuntimeStep(
        step_id=uuid4(),
        step_order=reader_order,
        assistant_id=uuid4(),
        user_description=None,
        input_source="previous_step",
        input_bindings=dict(input_bindings or {}),
        input_config=None,
        output_mode="compose_text",
        output_config=None,
    )
    resolved = resolve_step_input_binding(
        step=reader,
        run=cast(FlowRun, SimpleNamespace(input_payload_json={})),
        prior_results=[
            completed_result(order, text) for order, text in text_by_order.items()
        ],
        state=None,
        runtime_input_metadata=None,
        variable_resolver=FlowVariableResolver(),
    )
    assert resolved is not None
    return resolved.text
