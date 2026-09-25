from dataclasses import dataclass

from eneo.tokens.token_utils import (
    TokenCountSource,
    measure_message_token_delta,
    measure_tool_tokens,
)


@dataclass(frozen=True)
class SkillContextMeasurement:
    tokens: int
    limit: int
    source: TokenCountSource


def skill_context_token_allowance(
    *,
    max_input_tokens: int,
    context_share_percent: int,
) -> int:
    return max_input_tokens * context_share_percent // 100


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
    tools: list[dict[str, object]] | None = None,
) -> SkillContextMeasurement:
    """Measure the complete Skill-owned prompt and tool-schema cost."""

    message_delta = measure_message_token_delta(
        _system_message(base_instructions),
        _system_message(composed_instructions),
        model_name,
    )
    tool_delta = measure_tool_tokens(tools or [], model_name)
    source = (
        TokenCountSource.FALLBACK_ESTIMATE
        if TokenCountSource.FALLBACK_ESTIMATE
        in (message_delta.source, tool_delta.source)
        else TokenCountSource.LITELLM
    )
    return SkillContextMeasurement(
        tokens=message_delta.tokens + tool_delta.tokens,
        limit=skill_context_token_allowance(
            max_input_tokens=max_input_tokens,
            context_share_percent=context_share_percent,
        ),
        source=source,
    )
