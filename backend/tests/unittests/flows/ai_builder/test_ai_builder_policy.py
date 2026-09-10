from types import SimpleNamespace

import pytest

from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_settings import (
    AIBuilderBudgetPolicy,
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


@pytest.mark.parametrize("operation", ["classification", "proposal", "review"])
@pytest.mark.parametrize(
    ("context_window", "output_ceiling"),
    [(1_000_000, 128_000), (128_000, 16_384)],
)
def test_request_admission_preserves_the_selected_models_full_output_capacity(
    operation: str, context_window: int, output_ceiling: int
) -> None:
    policy = AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=2_000,
        minimum_conversation_budget_tokens=4_000,
    )
    budget = getattr(policy, f"{operation}_request_budget")(
        context_window_tokens=context_window,
        model_output_ceiling_tokens=output_ceiling,
    )
    input_limit = context_window - output_ceiling - 2_000

    resolved = budget.resolve(input_tokens=20_000)
    assert resolved is not None
    assert resolved.available_input_tokens == input_limit
    assert resolved.model_output_ceiling_tokens == output_ceiling
    assert budget.resolve(input_tokens=input_limit) is not None
    assert budget.resolve(input_tokens=input_limit + 1) is None


@pytest.mark.parametrize("operation", ["classification", "proposal", "review"])
def test_request_admission_refuses_a_window_without_room_for_full_output(
    operation: str,
) -> None:
    policy = AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=2_000,
        minimum_conversation_budget_tokens=4_000,
    )
    budget = getattr(policy, f"{operation}_request_budget")(
        context_window_tokens=128_000,
        model_output_ceiling_tokens=128_000,
    )

    assert budget.resolve(input_tokens=1) is None


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
    resolved = budget.resolve(input_tokens=20_000)

    assert budget.context_window_tokens == context_window
    assert budget.timeout_seconds == 240.0
    assert resolved is not None
    assert resolved.model_output_ceiling_tokens == 32_000


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
    assert (
        capped.review_request_budget(
            context_window_tokens=1_000_000, model_output_ceiling_tokens=8_000
        ).available_input_tokens
        == 32_000
    )
    # A cap above the model's window never widens it.
    assert (
        capped.review_request_budget(
            context_window_tokens=16_000, model_output_ceiling_tokens=8_000
        ).available_input_tokens
        == 6_000
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
    assert review_backed.available_input_tokens == 12_000
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
    assert budget.available_input_tokens == input_cap
    assert budget.resolve(input_tokens=input_cap) is not None
    assert budget.resolve(input_tokens=input_cap + 1) is None
