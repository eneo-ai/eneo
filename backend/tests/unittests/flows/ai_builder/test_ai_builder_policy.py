from types import SimpleNamespace

import pytest

from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_settings import (
    AIBuilderBudgetPolicy,
    AIBuilderRequestBudget,
    apply_ai_builder_budget_policy_patch,
    resolve_ai_builder_budget_policy,
)
from eneo.flows.flow_ai_builder_budget_settings import (
    AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT,
    AI_BUILDER_MAX_MESSAGE_CHARS_HARD_LIMIT,
    AI_BUILDER_MAX_TEMPLATE_PLACEHOLDERS_HARD_LIMIT,
    AI_BUILDER_TEMPLATE_INSPECTION_HARD_LIMIT_BYTES,
)


def test_ai_builder_policy_resolves_admin_owned_operating_limits() -> None:
    policy = resolve_ai_builder_budget_policy(
        {
            "ai_builder": {
                "max_attachments": 37,
                "max_message_chars": 12_000,
                "max_template_inspection_uncompressed_bytes": 64 * 1024 * 1024,
                "max_template_placeholders": 750,
            }
        },
        defaults=SimpleNamespace(
            ai_builder_conversation_safety_buffer_tokens=2_000,
            ai_builder_minimum_conversation_budget_tokens=4_000,
            ai_builder_classification_timeout_seconds=60.0,
            ai_builder_proposal_timeout_seconds=180.0,
        ),
    )

    assert policy.max_attachments == 37
    assert policy.max_message_chars == 12_000
    assert policy.max_template_inspection_uncompressed_bytes == 64 * 1024 * 1024
    assert policy.max_template_placeholders == 750


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("max_attachments", AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT + 1),
        ("max_message_chars", AI_BUILDER_MAX_MESSAGE_CHARS_HARD_LIMIT + 1),
        (
            "max_template_inspection_uncompressed_bytes",
            AI_BUILDER_TEMPLATE_INSPECTION_HARD_LIMIT_BYTES + 1,
        ),
        (
            "max_template_placeholders",
            AI_BUILDER_MAX_TEMPLATE_PLACEHOLDERS_HARD_LIMIT + 1,
        ),
    ),
)
def test_ai_builder_policy_rejects_operating_limits_above_system_ceiling(
    field_name: str,
    value: int,
) -> None:
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        resolve_ai_builder_budget_policy(
            {"ai_builder": {field_name: value}},
            defaults=SimpleNamespace(
                ai_builder_conversation_safety_buffer_tokens=2_000,
                ai_builder_minimum_conversation_budget_tokens=4_000,
                ai_builder_classification_timeout_seconds=60.0,
                ai_builder_proposal_timeout_seconds=180.0,
            ),
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_AI_BUILDER_SETTINGS


def _policy(**overrides: object) -> AIBuilderBudgetPolicy:
    return AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=2_000,
        minimum_conversation_budget_tokens=4_000,
        **overrides,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("operation", ["classification", "proposal", "review"])
@pytest.mark.parametrize(
    ("context_window", "output_ceiling"),
    [(1_000_000, 128_000), (128_000, 16_384)],
)
def test_a_ceiling_within_half_the_room_is_reserved_whole(
    operation: str, context_window: int, output_ceiling: int
) -> None:
    # The common case: the ceiling fits in half of what the required input
    # leaves, so packing keeps the whole ceiling free and the input budget is
    # exactly the window less the buffer and the ceiling.
    budget = getattr(_policy(), f"{operation}_request_budget")(
        context_window_tokens=context_window,
        model_output_ceiling_tokens=output_ceiling,
    )
    planned = budget.plan(required_input_tokens=20_000)
    assert planned is not None
    assert planned.reserved_output_tokens == output_ceiling
    input_limit = context_window - 2_000 - output_ceiling
    assert planned.available_input_tokens == input_limit
    resolved = planned.resolve(input_tokens=20_000)
    assert resolved is not None
    assert resolved.provider_output_cap_tokens == output_ceiling
    assert planned.resolve(input_tokens=input_limit) is not None
    assert planned.resolve(input_tokens=input_limit + 1) is None


@pytest.mark.parametrize("operation", ["classification", "proposal", "review"])
def test_a_ceiling_at_or_above_the_window_shares_the_room_evenly(
    operation: str,
) -> None:
    # Catalogue metadata often declares the ceiling equal to the window. The
    # request is not refused: half of the room after the required input is
    # kept for the answer, the rest carries optional input, and the model is
    # told it may write what the packed request leaves.
    budget = getattr(_policy(), f"{operation}_request_budget")(
        context_window_tokens=128_000,
        model_output_ceiling_tokens=128_000,
    )
    planned = budget.plan(required_input_tokens=20_000)
    assert planned is not None
    assert planned.reserved_output_tokens == 53_000
    assert planned.available_input_tokens == 126_000 - 53_000
    resolved = planned.resolve(input_tokens=20_000)
    assert resolved is not None
    assert resolved.provider_output_cap_tokens == 106_000
    packed = planned.resolve(input_tokens=planned.available_input_tokens)
    assert packed is not None
    assert packed.provider_output_cap_tokens == planned.reserved_output_tokens


def test_required_input_that_leaves_no_room_is_refused_and_one_token_is_not() -> None:
    budget = _policy().proposal_request_budget(
        context_window_tokens=128_000, model_output_ceiling_tokens=16_384
    )
    assert budget.plan(required_input_tokens=126_000) is None
    planned = budget.plan(required_input_tokens=125_999)
    assert planned is not None
    assert planned.reserved_output_tokens == 1
    assert planned.available_input_tokens == 125_999
    resolved = planned.resolve(input_tokens=125_999)
    assert resolved is not None
    assert resolved.provider_output_cap_tokens == 1
    assert budget.resolve_whole(input_tokens=126_000) is None


def test_the_reserve_rounds_up_and_never_exceeds_the_room() -> None:
    budget = AIBuilderRequestBudget(
        context_window_tokens=105,
        model_output_ceiling_tokens=100,
        safety_buffer_tokens=0,
        answer_reserve_share=0.5,
        timeout_seconds=1.0,
    )
    planned = budget.plan(required_input_tokens=4)
    assert planned is not None
    assert planned.reserved_output_tokens == 51
    assert planned.available_input_tokens == 54
    resolved = planned.resolve(input_tokens=54)
    assert resolved is not None
    assert resolved.provider_output_cap_tokens == 51
    tiny = budget.plan(required_input_tokens=104)
    assert tiny is not None
    assert tiny.reserved_output_tokens == 1


@pytest.mark.parametrize("share", [0.0, 1.0, -0.5, float("nan"), float("inf")])
def test_the_answer_reserve_share_must_be_a_fraction_of_the_room(share: float) -> None:
    with pytest.raises(ValueError):
        AIBuilderRequestBudget(
            context_window_tokens=1_000,
            model_output_ceiling_tokens=100,
            safety_buffer_tokens=0,
            answer_reserve_share=share,
            timeout_seconds=1.0,
        )


def test_the_share_is_deployment_policy_read_once() -> None:
    policy = resolve_ai_builder_budget_policy(
        None,
        defaults=SimpleNamespace(
            ai_builder_conversation_safety_buffer_tokens=2_000,
            ai_builder_minimum_conversation_budget_tokens=4_000,
            ai_builder_answer_reserve_share=0.25,
            ai_builder_classification_timeout_seconds=None,
            ai_builder_proposal_timeout_seconds=180.0,
        ),
    )
    assert policy.answer_reserve_share == 0.25
    planned = policy.proposal_request_budget(
        context_window_tokens=128_000, model_output_ceiling_tokens=128_000
    ).plan(required_input_tokens=26_000)
    assert planned is not None
    assert planned.reserved_output_tokens == 25_000


def test_the_answer_reserve_for_a_packer_stands_in_for_unmeasured_input() -> None:
    policy = _policy()
    assert (
        policy.answer_reserve_tokens(
            context_window_tokens=128_000,
            model_output_ceiling_tokens=16_384,
            required_input_tokens=4_000,
        )
        == 16_384
    )
    assert (
        policy.answer_reserve_tokens(
            context_window_tokens=128_000,
            model_output_ceiling_tokens=128_000,
            required_input_tokens=4_000,
        )
        == 61_000
    )
    # A window with no room keeps the whole ceiling: the packer admits nothing.
    assert (
        policy.answer_reserve_tokens(
            context_window_tokens=6_000,
            model_output_ceiling_tokens=1_024,
            required_input_tokens=4_000,
        )
        == 1_024
    )


@pytest.mark.parametrize("context_window", [128_000, 1_000_000])
def test_classification_uses_model_capacity_and_the_shared_request_deadline(
    context_window: int,
) -> None:
    policy = AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=2_000,
        minimum_conversation_budget_tokens=4_000,
        proposal_timeout_seconds=240.0,
    )

    budget = policy.classification_request_budget(
        context_window_tokens=context_window, model_output_ceiling_tokens=32_000
    )
    resolved = budget.resolve_whole(input_tokens=20_000)

    assert budget.context_window_tokens == context_window
    assert budget.timeout_seconds == 240.0
    assert resolved is not None
    assert resolved.model_output_ceiling_tokens == 32_000
    assert resolved.provider_output_cap_tokens == 32_000


def test_classification_honors_an_explicit_deployment_deadline() -> None:
    policy = AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=2_000,
        minimum_conversation_budget_tokens=4_000,
        classification_timeout_seconds=90.0,
        proposal_timeout_seconds=240.0,
    )

    budget = policy.classification_request_budget(
        context_window_tokens=1_000_000, model_output_ceiling_tokens=32_000
    )

    assert budget.timeout_seconds == 90.0


def test_review_evidence_cap_limits_input_within_the_models_capacity() -> None:
    policy = resolve_ai_builder_budget_policy(None)
    assert policy.review_evidence_max_input_tokens is None
    budget = policy.review_request_budget(
        context_window_tokens=1_000_000, model_output_ceiling_tokens=8_000
    )
    assert budget.context_window_tokens == 1_000_000
    assert budget.timeout_seconds == policy.proposal_timeout_seconds

    capped = resolve_ai_builder_budget_policy(
        {"ai_builder": {"review_evidence_max_input_tokens": 32_000}}
    )
    assert capped.review_evidence_max_input_tokens == 32_000
    wide = capped.review_request_budget(
        context_window_tokens=1_000_000, model_output_ceiling_tokens=8_000
    ).plan(required_input_tokens=1)
    assert wide is not None
    assert wide.available_input_tokens == 32_000
    # A cap above the model's window never widens it: the window less the
    # buffer is 14 000, of which half the room after the required input
    # (7 000) stays free for the answer.
    narrow = capped.review_request_budget(
        context_window_tokens=16_000, model_output_ceiling_tokens=8_000
    ).plan(required_input_tokens=1)
    assert narrow is not None
    assert narrow.available_input_tokens == 7_000
    # Required input above the cap is refused before any packing.
    assert (
        capped.review_request_budget(
            context_window_tokens=1_000_000, model_output_ceiling_tokens=8_000
        ).plan(required_input_tokens=32_001)
        is None
    )
    with pytest.raises(AIBuilderBadRequestException):
        resolve_ai_builder_budget_policy(
            {"ai_builder": {"review_evidence_max_input_tokens": "many"}}
        )


def test_the_review_evidence_cap_bounds_every_request_that_carries_run_evidence() -> (
    None
):
    capped = resolve_ai_builder_budget_policy(
        {"ai_builder": {"review_evidence_max_input_tokens": 12_000}}
    )
    review_backed = capped.proposal_request_budget(
        context_window_tokens=1_000_000,
        model_output_ceiling_tokens=8_000,
        carries_review_evidence=True,
    )
    assert review_backed.context_window_tokens == 1_000_000
    planned = review_backed.plan(required_input_tokens=1)
    assert planned is not None
    assert planned.available_input_tokens == 12_000
    ordinary = capped.proposal_request_budget(
        context_window_tokens=1_000_000, model_output_ceiling_tokens=8_000
    )
    assert ordinary.context_window_tokens == 1_000_000


def test_the_investigation_evidence_share_is_a_ceiling_tenants_can_only_lower() -> None:
    policy = resolve_ai_builder_budget_policy(None)
    assert policy.review_investigation_evidence_max_tokens == 16_000
    lowered = resolve_ai_builder_budget_policy(
        {"ai_builder": {"review_investigation_evidence_max_tokens": 12_000}}
    )
    assert lowered.review_investigation_evidence_max_tokens == 12_000
    with pytest.raises(AIBuilderBadRequestException):
        resolve_ai_builder_budget_policy(
            {"ai_builder": {"review_investigation_evidence_max_tokens": 40_000}}
        )


def test_the_investigation_evidence_bound_itself_is_stored_as_no_override() -> None:
    lowered = apply_ai_builder_budget_policy_patch(
        None, review_investigation_evidence_max_tokens=12_000
    )
    assert lowered["ai_builder"]["review_investigation_evidence_max_tokens"] == 12_000
    # Sending the bound restores inheritance instead of pinning today's value.
    at_bound = apply_ai_builder_budget_policy_patch(
        lowered, review_investigation_evidence_max_tokens=16_000
    )
    assert "review_investigation_evidence_max_tokens" not in at_bound.get(
        "ai_builder", {}
    )
    # So does an explicit null (the PATCH service maps it to remove_keys).
    removed = apply_ai_builder_budget_policy_patch(
        lowered, remove_keys={"review_investigation_evidence_max_tokens"}
    )
    assert "review_investigation_evidence_max_tokens" not in removed.get(
        "ai_builder", {}
    )
    with pytest.raises(AIBuilderBadRequestException):
        apply_ai_builder_budget_policy_patch(
            None, review_investigation_evidence_max_tokens=16_001
        )


@pytest.mark.parametrize("operation", ["review", "proposal"])
@pytest.mark.parametrize("input_cap", [32_000, 128_000])
def test_review_input_cap_preserves_output_outside_the_cap(
    operation: str, input_cap: int
) -> None:
    policy = AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=2_000,
        minimum_conversation_budget_tokens=4_000,
        review_evidence_max_input_tokens=input_cap,
    )
    kwargs = {"carries_review_evidence": True} if operation == "proposal" else {}
    budget = getattr(policy, f"{operation}_request_budget")(
        context_window_tokens=1_000_000,
        model_output_ceiling_tokens=128_000,
        **kwargs,
    )
    assert budget.context_window_tokens == 1_000_000
    planned = budget.plan(required_input_tokens=1)
    assert planned is not None
    assert planned.available_input_tokens == input_cap
    at_cap = planned.resolve(input_tokens=input_cap)
    assert at_cap is not None
    # The answer is never charged to the input cap.
    assert at_cap.provider_output_cap_tokens == 128_000
    assert planned.resolve(input_tokens=input_cap + 1) is None


def test_a_planned_budget_is_one_allocation_until_a_new_call_plans_again() -> None:
    budget = AIBuilderRequestBudget(
        context_window_tokens=100,
        model_output_ceiling_tokens=100,
        safety_buffer_tokens=0,
        answer_reserve_share=0.5,
        timeout_seconds=1.0,
    )
    planned = budget.plan(required_input_tokens=20)
    assert planned is not None
    assert (planned.reserved_output_tokens, planned.available_input_tokens) == (40, 60)
    with pytest.raises(TypeError):
        planned.plan(required_input_tokens=50)
    with pytest.raises(TypeError):
        planned.resolve_whole(input_tokens=50)
    again = planned.unplanned().plan(required_input_tokens=50)
    assert again is not None
    assert (again.reserved_output_tokens, again.available_input_tokens) == (25, 75)
    assert planned.unplanned() == budget
