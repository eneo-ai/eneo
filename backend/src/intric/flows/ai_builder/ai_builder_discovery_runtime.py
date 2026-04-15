from __future__ import annotations

from typing import Any

from intric.flows.ai_builder.ai_builder_discovery import (
    analyze_discovery,
    build_discovery_block_message,
    build_discovery_followup,
)
from intric.flows.ai_builder.ai_builder_discovery_models import DiscoveryAnalysis
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_semantic_adjudication import (
    adjudicate_discovery_semantics,
    should_run_semantic_adjudication,
)
from intric.flows.domain.flow import Flow


async def analyze_discovery_runtime(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    litellm_client: Any | None = None,
    litellm_model: str | None = None,
    litellm_kwargs: dict[str, Any] | None = None,
    ui_language: str | None = None,
    allow_semantic_adjudication: bool = True,
) -> DiscoveryAnalysis:
    analysis = analyze_discovery(conversation, flow=flow)
    if (
        not allow_semantic_adjudication
        or litellm_client is None
        or litellm_model is None
        or not should_run_semantic_adjudication(analysis)
    ):
        return analysis

    semantic_result = await adjudicate_discovery_semantics(
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs or {},
        conversation=conversation,
        analysis=analysis,
        ui_language=ui_language,
    )
    if semantic_result is None:
        return analysis
    return analyze_discovery(conversation, flow=flow, semantic_result=semantic_result)


async def build_discovery_block_message_runtime(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    litellm_client: Any | None = None,
    litellm_model: str | None = None,
    litellm_kwargs: dict[str, Any] | None = None,
    ui_language: str | None = None,
    allow_semantic_adjudication: bool = True,
) -> tuple[str | None, DiscoveryAnalysis]:
    analysis = await analyze_discovery_runtime(
        conversation,
        flow=flow,
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        ui_language=ui_language,
        allow_semantic_adjudication=allow_semantic_adjudication,
    )
    return build_discovery_block_message(
        conversation,
        flow=flow,
        analysis=analysis,
    ), analysis


async def build_discovery_followup_runtime(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    litellm_client: Any | None = None,
    litellm_model: str | None = None,
    litellm_kwargs: dict[str, Any] | None = None,
    ui_language: str | None = None,
    allow_semantic_adjudication: bool = True,
):
    analysis = await analyze_discovery_runtime(
        conversation,
        flow=flow,
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        ui_language=ui_language,
        allow_semantic_adjudication=allow_semantic_adjudication,
    )
    return build_discovery_followup(
        conversation,
        flow=flow,
        analysis=analysis,
    ), analysis
