from unittest.mock import patch

from eneo.completion_models.domain.skill_context import measure_skill_context
from eneo.tokens.token_utils import TokenCount, TokenCountSource


def test_measure_skill_context_uses_system_message_delta_and_policy_share():
    with patch(
        "eneo.completion_models.domain.skill_context.measure_message_tokens",
        side_effect=[
            TokenCount(tokens=20, source=TokenCountSource.LITELLM),
            TokenCount(tokens=145, source=TokenCountSource.LITELLM),
        ],
    ) as counter:
        measurement = measure_skill_context(
            base_instructions="Base",
            composed_instructions="Base plus Skills",
            model_name="openai/gpt-4o",
            max_input_tokens=128_000,
            context_share_percent=15,
        )

    assert counter.call_args_list[0].args == (
        [{"role": "system", "content": "Base"}],
        "openai/gpt-4o",
    )
    assert counter.call_args_list[1].args == (
        [{"role": "system", "content": "Base plus Skills"}],
        "openai/gpt-4o",
    )
    assert measurement.tokens == 125
    assert measurement.limit == 19_200
    assert measurement.source is TokenCountSource.LITELLM


def test_measure_skill_context_names_fallback_when_either_count_is_estimated():
    with patch(
        "eneo.completion_models.domain.skill_context.measure_message_tokens",
        side_effect=[
            TokenCount(tokens=20, source=TokenCountSource.LITELLM),
            TokenCount(tokens=145, source=TokenCountSource.FALLBACK_ESTIMATE),
        ],
    ):
        measurement = measure_skill_context(
            base_instructions="Base",
            composed_instructions="Base plus Skills",
            model_name="unknown-model",
            max_input_tokens=1000,
            context_share_percent=10,
        )

    assert measurement.tokens == 125
    assert measurement.limit == 100
    assert measurement.source is TokenCountSource.FALLBACK_ESTIMATE


def test_measure_skill_context_records_zero_for_byte_identical_prompt():
    measurement = measure_skill_context(
        base_instructions="  Base\n",
        composed_instructions="  Base\n",
        model_name="openai/gpt-4o",
        max_input_tokens=128_000,
        context_share_percent=10,
    )

    assert measurement.tokens == 0
    assert measurement.limit == 12_800
