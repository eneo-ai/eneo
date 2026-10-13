"""Model usage that Eneo's own model-backed tools report on a tool call.

A loopback tool that runs completions itself (the digest tools) reports
the tokens it spent in its result ``_meta`` under the OpenTelemetry GenAI
attribute names. Token statistics read only the question row's counters,
so the ask path folds those tokens into the row when the tool ran on the
same model as the turn. Only rows the proxy marked as internal count: an
external server controls its own ``_meta`` and must not be able to inflate
a tenant's statistics.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from uuid import UUID

from eneo.questions.question import ToolCallInfo

logger = logging.getLogger(__name__)

INPUT_KEY = "gen_ai.usage.input_tokens"
OUTPUT_KEY = "gen_ai.usage.output_tokens"
MODEL_KEY = "eneo.completion_model_id"
# A single tool call cannot plausibly spend more; larger values are a bug
# or a forged payload, and are skipped rather than folded.
SANITY_CAP = 100_000_000


def _token_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > SANITY_CAP:
        return None
    return value


def tool_usage_tokens(
    tool_calls: Iterable[ToolCallInfo] | None, completion_model_id: UUID | None
) -> tuple[int, int]:
    """``(input, output)`` tokens reported by internal tools on this model."""
    if not tool_calls or completion_model_id is None:
        return 0, 0
    wanted = str(completion_model_id)
    total_in = total_out = 0
    for call in tool_calls:
        meta = call.meta
        if call.is_internal is not True or not meta:
            continue
        if meta.get(MODEL_KEY) != wanted:
            continue
        tokens_in = _token_count(meta.get(INPUT_KEY))
        tokens_out = _token_count(meta.get(OUTPUT_KEY))
        if tokens_in is None or tokens_out is None:
            logger.warning(
                "[TokenUsage] skipping tool usage with invalid counts tool=%s",
                call.mcp_tool_name or call.tool_name,
            )
            continue
        total_in += tokens_in
        total_out += tokens_out
    return total_in, total_out
