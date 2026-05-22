from __future__ import annotations

from typing import Any

from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalCompletionFn,
)
from intric.main.logging import get_logger

logger = get_logger(__name__)


async def call_proposal_completion(
    *,
    litellm_client: Any,
    messages: list[dict[str, Any]],
    tool_schemas: list[dict[str, Any]],
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    max_output_tokens: int,
    temperature: float,
    tool_choice: dict[str, Any] | None = None,
) -> Any:
    provider_kwargs = dict(litellm_kwargs)
    provider_kwargs.pop("drop_params", None)
    dropped_response_format = provider_kwargs.pop("response_format", None)
    if dropped_response_format is not None:
        logger.debug("ai_builder_proposal_completion_dropped_response_format")

    return await litellm_client.acompletion(
        model=litellm_model,
        messages=messages,
        tools=tool_schemas,
        tool_choice=tool_choice,
        stream=False,
        drop_params=True,
        max_tokens=max_output_tokens,
        temperature=temperature,
        **provider_kwargs,
    )


async def call_proposal_completion_with_usage(
    *,
    litellm_client: Any,
    messages: list[dict[str, Any]],
    tool_schemas: list[dict[str, Any]],
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    max_output_tokens: int,
    temperature: float,
    usage_tracker: ProposalTurnTelemetry | None,
    tool_choice: dict[str, Any] | None = None,
    counts_as_repair: bool = False,
) -> Any:
    response = await call_proposal_completion(
        litellm_client=litellm_client,
        messages=messages,
        tool_schemas=tool_schemas,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        tool_choice=tool_choice,
    )
    if usage_tracker is not None:
        usage_tracker.record_response(
            response,
            messages=messages,
            counts_as_repair=counts_as_repair,
        )
    return response


def make_usage_tracked_proposal_completion(
    *,
    litellm_client: Any,
    usage_tracker: ProposalTurnTelemetry | None,
    counts_as_repair: bool,
) -> ProposalCompletionFn:
    async def _tracked_completion(
        *,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        max_output_tokens: int,
        temperature: float,
        tool_choice: dict[str, Any] | None = None,
    ) -> Any:
        return await call_proposal_completion_with_usage(
            litellm_client=litellm_client,
            messages=messages,
            tool_schemas=tool_schemas,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            usage_tracker=usage_tracker,
            tool_choice=tool_choice,
            counts_as_repair=counts_as_repair,
        )

    return _tracked_completion
