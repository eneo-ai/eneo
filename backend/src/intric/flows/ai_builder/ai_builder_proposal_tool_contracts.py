"""Shared proposal tool contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from intric.flows.ai_builder.ai_builder_discovery_runtime import DiscoveryRuntimeResult
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
    FlowBuilderEditApproval,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
    ToolProcessingFailureKind,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import AIBuilderResourceCatalog
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from intric.flows.ai_builder.planning_state import AggregationIntent, PlanningState
from intric.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from intric.flows.flow_resource_bindings import LocalResourceBinding

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow
    from intric.flows.flow_authoring_spec import FlowDraftSpecCore


class ProposalCompletionFn(Protocol):
    def __call__(
        self,
        request: "ProposalCompletionRequest",
    ) -> Awaitable["ProposalCompletionResponse"]: ...


class ProposalCompletionUsage(Protocol):
    @property
    def prompt_tokens(self) -> int: ...

    @property
    def completion_tokens(self) -> int: ...

    @property
    def total_tokens(self) -> int: ...


class ProposalCompletionToolCallFunction(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def arguments(self) -> str: ...


class ProposalCompletionToolCall(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def function(self) -> ProposalCompletionToolCallFunction: ...


class ProposalCompletionMessage(Protocol):
    @property
    def content(self) -> str | None: ...

    @property
    def tool_calls(self) -> Sequence[ProposalCompletionToolCall]: ...


class ProposalCompletionChoice(Protocol):
    @property
    def message(self) -> ProposalCompletionMessage: ...

    @property
    def finish_reason(self) -> str | None: ...


class ProposalCompletionResponse(Protocol):
    @property
    def choices(self) -> Sequence[ProposalCompletionChoice]: ...

    @property
    def usage(self) -> ProposalCompletionUsage | None: ...


@dataclass(frozen=True)
class ProposalCompletionRequest:
    messages: list[dict[str, Any]]
    tool_schemas: list[dict[str, Any]]
    litellm_model: str
    litellm_kwargs: dict[str, Any]
    max_output_tokens: int
    temperature: float
    tool_choice: dict[str, Any] | str | None = None
    counts_as_repair: bool = False


@dataclass(frozen=True)
class CompiledProposal:
    spec: "FlowDraftSpecCore"
    assumptions: tuple[str, ...]
    plan_rationale: str | None
    reasoning: str | None
    validation: SpecValidationResult
    resource_bindings: tuple[LocalResourceBinding, ...] = tuple()
    edit: FlowBuilderEditApproval | None = None
    aggregation_intent: AggregationIntent = "linear"


@dataclass(frozen=True)
class ToolProcessingResult:
    event: dict[str, str] | None = None
    events: tuple[dict[str, str], ...] = ()
    compiled_proposal: CompiledProposal | None = None
    user_message: str | None = None
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
    target_kind: TargetKind
    forced_tool_prompt: str
    process_tool_invocation: Callable[
        [ToolRetryInvocation], Awaitable[ToolProcessingResult]
    ]


@dataclass(frozen=True)
class ProposalTurnContext:
    turn: SessionSendTurn
    conversation: list[ConversationMessage]
    new_messages_start: int
    llm_messages: list[dict[str, Any]]
    tool_schemas: list[dict[str, Any]]
    litellm_model: str
    litellm_kwargs: dict[str, Any]
    available_model_refs: set[str] | None
    available_kb_refs: set[str] | None
    resource_catalog: AIBuilderResourceCatalog | None
    max_output_tokens: int
    request_id: str
    flow: "Flow | None" = None
    assistant_snapshots: AssistantAuthoringSnapshots | None = None
    text_content: str | None = None
    assistant_metadata: dict[str, Any] | None = None
    planning_state: PlanningState | None = None
    usage_tracker: ProposalTurnTelemetry | None = None
    plan_edit_context: AIBuilderPlanEditContext | None = None
    prior_plan_for_revision: BuilderPlan | None = None
    discovery_runtime: DiscoveryRuntimeResult | None = None

    @property
    def session_id(self) -> UUID:
        return self.turn.session_id

    @property
    def base_planning_state_version(self) -> int:
        return self.turn.base_planning_state_version

    def completion_request(
        self,
        *,
        temperature: float,
        messages: list[dict[str, Any]] | None = None,
        tool_schemas: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | str | None = None,
        counts_as_repair: bool = False,
    ) -> ProposalCompletionRequest:
        return ProposalCompletionRequest(
            messages=self.llm_messages if messages is None else messages,
            tool_schemas=self.tool_schemas if tool_schemas is None else tool_schemas,
            litellm_model=self.litellm_model,
            litellm_kwargs=self.litellm_kwargs,
            max_output_tokens=self.max_output_tokens,
            temperature=temperature,
            tool_choice=tool_choice,
            counts_as_repair=counts_as_repair,
        )
