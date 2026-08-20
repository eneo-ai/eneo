from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.flows.api.flow_models import (
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.domain.flow import FlowStep
from eneo.flows.enums import (
    RECONCILABLE_REVIEW_CHECKPOINT_STATES,
    FlowPrimaryOutputExecutionKind,
    FlowRunReviewCheckpointState,
    flow_output_mode_primary_execution_kind,
    flow_output_mode_uses_completion_model,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    StepSpec,
)


def test_output_mode_completion_model_capability_covers_every_mode() -> None:
    actual = {
        mode: flow_output_mode_uses_completion_model(mode) for mode in FlowOutputMode
    }

    assert actual == {
        FlowOutputMode.PASS_THROUGH: True,
        FlowOutputMode.HTTP_POST: True,
        FlowOutputMode.COMPOSE_TEXT: False,
        FlowOutputMode.TRANSCRIBE_ONLY: False,
        FlowOutputMode.TEMPLATE_FILL: False,
        FlowOutputMode.RENDER_VERBATIM: False,
    }


def test_primary_output_execution_kind_covers_every_mode() -> None:
    actual = {
        mode: flow_output_mode_primary_execution_kind(mode) for mode in FlowOutputMode
    }

    assert actual == {
        FlowOutputMode.PASS_THROUGH: FlowPrimaryOutputExecutionKind.COMPLETION_MODEL,
        FlowOutputMode.HTTP_POST: FlowPrimaryOutputExecutionKind.COMPLETION_MODEL,
        FlowOutputMode.TRANSCRIBE_ONLY: (
            FlowPrimaryOutputExecutionKind.TRANSCRIPTION_MODEL
        ),
        FlowOutputMode.COMPOSE_TEXT: FlowPrimaryOutputExecutionKind.DETERMINISTIC,
        FlowOutputMode.TEMPLATE_FILL: FlowPrimaryOutputExecutionKind.DETERMINISTIC,
        FlowOutputMode.RENDER_VERBATIM: FlowPrimaryOutputExecutionKind.DETERMINISTIC,
    }


def test_review_expiry_reconciles_only_unresolved_review_states() -> None:
    assert RECONCILABLE_REVIEW_CHECKPOINT_STATES == frozenset(
        {
            FlowRunReviewCheckpointState.AWAITING_REVIEW,
            FlowRunReviewCheckpointState.EDITED,
        }
    )
    assert FlowRunReviewCheckpointState.APPROVED not in (
        RECONCILABLE_REVIEW_CHECKPOINT_STATES
    )
    assert FlowRunReviewCheckpointState.EXPIRED.value == "expired"


def test_flow_step_round_trips_string_fields_as_shared_enums() -> None:
    step = FlowStep.model_validate(
        {
            "assistant_id": str(uuid4()),
            "step_order": 1,
            "input_source": "flow_input",
            "input_type": "audio",
            "output_mode": "transcribe_only",
            "output_type": "text",
        }
    )

    assert isinstance(step.input_source, FlowInputSource)
    assert isinstance(step.input_type, FlowInputType)
    assert isinstance(step.output_mode, FlowOutputMode)
    assert isinstance(step.output_type, FlowOutputType)


def test_flow_authoring_step_spec_keeps_supported_subset_restrictions() -> None:
    with pytest.raises(ValidationError):
        StepSpec(
            plan_step_ref="step_a",
            name="HTTP input is not planner-supported",
            assistant_spec=AssistantSpec(instructions="Do something."),
            input_source="http_get",
            input_type="text",
        )

    with pytest.raises(ValidationError):
        StepSpec(
            plan_step_ref="step_a",
            name="Image input is not planner-supported",
            assistant_spec=AssistantSpec(instructions="Do something."),
            input_source="flow_input",
            input_type="image",
        )
