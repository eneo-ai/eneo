"""Shared proposal tool contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from intric.flows.ai_builder.ai_builder_edit_models import BuilderPlanEditResult
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ToolProcessingFailureKind,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import AIBuilderResourceCatalog
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from intric.flows.ai_builder.planning_state import AggregationIntent
from intric.flows.flow_resource_bindings import LocalResourceBinding

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow
    from intric.flows.flow_authoring_spec import FlowDraftSpecCore


class ProposalCompletionFn(Protocol):
    def __call__(
        self,
        *,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        max_output_tokens: int,
        temperature: float,
        tool_choice: dict[str, Any] | None = None,
    ) -> Awaitable[Any]: ...


@dataclass(frozen=True)
class CompiledProposal:
    spec: "FlowDraftSpecCore"
    assumptions: tuple[str, ...]
    plan_rationale: str | None
    reasoning: str | None
    validation: SpecValidationResult
    resource_bindings: tuple[LocalResourceBinding, ...] = tuple()
    edit_result: BuilderPlanEditResult | None = None
    aggregation_intent: AggregationIntent = "linear"


@dataclass(frozen=True)
class ToolProcessingResult:
    event: dict[str, str] | None = None
    events: tuple[dict[str, str], ...] = ()
    compiled_proposal: CompiledProposal | None = None
    feedback: str | None = None
    failure_kind: ToolProcessingFailureKind | None = None
    failure_codes: frozenset[str] = frozenset()
    new_planning_state_version: int | None = None

    @property
    def has_events(self) -> bool:
        return self.event is not None or bool(self.events)

    def iter_events(self) -> tuple[dict[str, str], ...]:
        if self.event is None:
            return self.events
        return (self.event, *self.events)


@dataclass(frozen=True)
class ToolRetryInvocation:
    turn: SessionSendTurn
    conversation: list[ConversationMessage]
    new_messages_start: int
    arguments: dict[str, Any]
    assistant_content: str
    tool_call_id: str
    available_model_refs: set[str] | None
    available_kb_refs: set[str] | None
    resource_catalog: AIBuilderResourceCatalog | None = None
    flow: "Flow | None" = None
    assistant_metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolRetryConfig:
    target_tool_name: str
    forced_tool_prompt: str
    process_tool_invocation: Callable[
        [ToolRetryInvocation], Awaitable[ToolProcessingResult]
    ]
