from dataclasses import dataclass

from eneo.tokens.token_utils import (
    TokenCountSource,
    measure_message_tokens,
)


@dataclass(frozen=True)
class SkillContextMeasurement:
    tokens: int
    limit: int
    source: TokenCountSource


def _system_message(instructions: str) -> list[dict[str, str]]:
    if not instructions:
        return []
    return [{"role": "system", "content": instructions}]


def measure_skill_context(
    *,
    base_instructions: str,
    composed_instructions: str,
    model_name: str,
    max_input_tokens: int,
    context_share_percent: int,
) -> SkillContextMeasurement:
    """Measure the prompt cost added by Skills using the completion counter."""

    base = measure_message_tokens(_system_message(base_instructions), model_name)
    composed = measure_message_tokens(
        _system_message(composed_instructions),
        model_name,
    )
    source = (
        TokenCountSource.LITELLM
        if (
            base.source is TokenCountSource.LITELLM
            and composed.source is TokenCountSource.LITELLM
        )
        else TokenCountSource.FALLBACK_ESTIMATE
    )
    return SkillContextMeasurement(
        tokens=max(composed.tokens - base.tokens, 0),
        limit=max_input_tokens * context_share_percent // 100,
        source=source,
    )
