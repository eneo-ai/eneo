from types import SimpleNamespace

import pytest

from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_settings import (
    AIBuilderBudgetPolicy,
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


def test_proposal_budget_clamps_capabilities_without_model_specific_rules() -> None:
    policy = AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=2_000,
        minimum_conversation_budget_tokens=4_000,
    )

    resolved_outputs = []
    for output_ceiling in (32_768, 131_072):
        budget = policy.proposal_request_budget(
            context_window_tokens=131_072,
            model_output_ceiling_tokens=output_ceiling,
        ).resolve(input_tokens=20_000)
        assert budget is not None
        resolved_outputs.append(budget.resolved_output_tokens)

    smaller_budget = policy.proposal_request_budget(
        context_window_tokens=131_072,
        model_output_ceiling_tokens=4_096,
    ).resolve(input_tokens=20_000)

    assert resolved_outputs == [6_144, 6_144]
    assert smaller_budget is not None
    assert smaller_budget.resolved_output_tokens == 4_096
