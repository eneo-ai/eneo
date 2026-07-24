from dataclasses import dataclass

from eneo.tokens.token_utils import (
    TokenCountSource,
    measure_message_token_delta,
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

    delta = measure_message_token_delta(
        _system_message(base_instructions),
        _system_message(composed_instructions),
        model_name,
    )
    return SkillContextMeasurement(
        tokens=delta.tokens,
        limit=max_input_tokens * context_share_percent // 100,
        source=delta.source,
    )
