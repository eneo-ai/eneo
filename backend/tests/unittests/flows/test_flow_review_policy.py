from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.api.flow_models import FlowStepCreateRequest, FlowStepUpdateRequest
from eneo.flows.domain.flow import FlowStep
from eneo.flows.enums import FlowOutputMode, flow_output_mode_has_outbound_delivery
from eneo.flows.flow_review_expiry_policy import (
    FLOW_REVIEW_EXPIRY_MAX_SECONDS,
    FLOW_REVIEW_EXPIRY_MIN_SECONDS,
)
from eneo.flows.flow_review_policy import (
    FLOW_REVIEW_POLICY_INVALID,
    FLOW_REVIEW_POLICY_OUTBOUND_OUTPUT_UNSUPPORTED,
    FlowStepReviewMode,
    FlowStepReviewPolicy,
    dump_flow_step_review_policy,
    parse_flow_step_review_policy,
)
from eneo.main.exceptions import BadRequestException


def test_parse_flow_step_review_policy_accepts_view_and_edit_modes() -> None:
    view_policy = parse_flow_step_review_policy(
        raw_policy={
            "mode": "view",
            "expires_after_seconds": FLOW_REVIEW_EXPIRY_MIN_SECONDS,
        },
        output_mode=FlowOutputMode.PASS_THROUGH,
    )
    edit_policy = parse_flow_step_review_policy(
        raw_policy={
            "mode": "edit",
            "expires_after_seconds": FLOW_REVIEW_EXPIRY_MAX_SECONDS,
        },
        output_mode=FlowOutputMode.TEMPLATE_FILL,
    )

    assert view_policy is not None
    assert view_policy.mode == FlowStepReviewMode.VIEW
    assert view_policy.expires_after_seconds == FLOW_REVIEW_EXPIRY_MIN_SECONDS
    assert view_policy.model_dump(mode="json") == {
        "mode": "view",
        "expires_after_seconds": FLOW_REVIEW_EXPIRY_MIN_SECONDS,
    }
    assert edit_policy is not None
    assert edit_policy.mode == FlowStepReviewMode.EDIT
    assert edit_policy.expires_after_seconds == FLOW_REVIEW_EXPIRY_MAX_SECONDS


@pytest.mark.parametrize("output_mode", list(FlowOutputMode))
def test_parse_flow_step_review_policy_allows_absent_policy_for_every_mode(
    output_mode: FlowOutputMode,
) -> None:
    assert (
        parse_flow_step_review_policy(raw_policy=None, output_mode=output_mode) is None
    )


def test_parse_flow_step_review_policy_accepts_canonical_policy_object() -> None:
    policy = FlowStepReviewPolicy(
        mode=FlowStepReviewMode.VIEW,
        expires_after_seconds=FLOW_REVIEW_EXPIRY_MIN_SECONDS,
    )

    parsed = parse_flow_step_review_policy(
        raw_policy=policy,
        output_mode=FlowOutputMode.PASS_THROUGH,
    )

    assert parsed is policy


def test_parse_flow_step_review_policy_rejects_invalid_shape() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        parse_flow_step_review_policy(
            raw_policy={"mode": "approve"},
            output_mode=FlowOutputMode.PASS_THROUGH,
        )

    assert exc_info.value.code == FLOW_REVIEW_POLICY_INVALID


@pytest.mark.parametrize(
    "expires_after_seconds",
    [FLOW_REVIEW_EXPIRY_MIN_SECONDS - 1, FLOW_REVIEW_EXPIRY_MAX_SECONDS + 1],
)
def test_parse_flow_step_review_policy_rejects_expiry_outside_bounds(
    expires_after_seconds: int,
) -> None:
    with pytest.raises(BadRequestException) as exc_info:
        parse_flow_step_review_policy(
            raw_policy={
                "mode": "view",
                "expires_after_seconds": expires_after_seconds,
            },
            output_mode=FlowOutputMode.PASS_THROUGH,
        )

    assert exc_info.value.code == FLOW_REVIEW_POLICY_INVALID


@pytest.mark.parametrize(
    "raw_policy",
    [
        {"mode": "view"},
        {"mode": "view", "expires_after_seconds": None},
    ],
)
def test_parse_flow_step_review_policy_defaults_expiry_to_inherit(
    raw_policy: dict[str, object],
) -> None:
    policy = parse_flow_step_review_policy(
        raw_policy=raw_policy,
        output_mode=FlowOutputMode.PASS_THROUGH,
    )

    assert policy == FlowStepReviewPolicy(
        mode=FlowStepReviewMode.VIEW,
        expires_after_seconds=None,
    )


def test_dump_flow_step_review_policy_omits_inherited_expiry() -> None:
    default_policy = FlowStepReviewPolicy(mode=FlowStepReviewMode.VIEW)
    explicit_policy = FlowStepReviewPolicy(
        mode=FlowStepReviewMode.EDIT,
        expires_after_seconds=FLOW_REVIEW_EXPIRY_MIN_SECONDS,
    )

    assert dump_flow_step_review_policy(default_policy) == {"mode": "view"}
    assert dump_flow_step_review_policy(explicit_policy) == {
        "mode": "edit",
        "expires_after_seconds": FLOW_REVIEW_EXPIRY_MIN_SECONDS,
    }


def test_parse_flow_step_review_policy_reports_outbound_mode_before_shape() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        parse_flow_step_review_policy(
            raw_policy=["not", "an", "object"],
            output_mode=FlowOutputMode.HTTP_POST,
        )

    assert exc_info.value.code == FLOW_REVIEW_POLICY_OUTBOUND_OUTPUT_UNSUPPORTED


def test_parse_flow_step_review_policy_rejects_outbound_delivery_modes() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        parse_flow_step_review_policy(
            raw_policy={"mode": "view"},
            output_mode=FlowOutputMode.HTTP_POST,
        )

    assert exc_info.value.code == FLOW_REVIEW_POLICY_OUTBOUND_OUTPUT_UNSUPPORTED


def test_output_mode_outbound_delivery_predicate_classifies_every_mode() -> None:
    classified = {
        mode: flow_output_mode_has_outbound_delivery(mode) for mode in FlowOutputMode
    }

    assert classified == {
        FlowOutputMode.PASS_THROUGH: False,
        FlowOutputMode.COMPOSE_TEXT: False,
        FlowOutputMode.HTTP_POST: True,
        FlowOutputMode.TRANSCRIBE_ONLY: False,
        FlowOutputMode.TEMPLATE_FILL: False,
        FlowOutputMode.RENDER_VERBATIM: False,
    }


def test_flow_step_uses_review_policy_contract() -> None:
    step = FlowStep(
        assistant_id=uuid4(),
        step_order=1,
        input_source="flow_input",
        input_type="text",
        output_mode="pass_through",
        output_type="text",
        review_policy={"mode": "view"},
    )

    assert step.review_policy == FlowStepReviewPolicy(mode=FlowStepReviewMode.VIEW)


def test_flow_step_create_request_preserves_review_policy_for_domain_step() -> None:
    request = FlowStepCreateRequest(
        assistant_id=uuid4(),
        step_order=1,
        input_source="flow_input",
        input_type="text",
        output_mode="pass_through",
        output_type="text",
        review_policy={"mode": "edit"},
    )

    step = FlowAssembler().to_domain_step(request)

    assert step.review_policy == FlowStepReviewPolicy(mode=FlowStepReviewMode.EDIT)


def test_flow_step_update_request_preserves_id_and_review_policy_for_domain_step() -> (
    None
):
    step_id = uuid4()
    request = FlowStepUpdateRequest(
        id=step_id,
        assistant_id=uuid4(),
        step_order=1,
        input_source="flow_input",
        input_type="text",
        output_mode="pass_through",
        output_type="text",
        review_policy={"mode": "edit"},
    )

    step = FlowAssembler().to_domain_step_for_update(request)

    assert step.id == step_id
    assert step.review_policy == FlowStepReviewPolicy(mode=FlowStepReviewMode.EDIT)
