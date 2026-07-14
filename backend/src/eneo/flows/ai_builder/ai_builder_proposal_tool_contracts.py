"""Shared proposal tool contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    NotRequired,
    Protocol,
    TypeAlias,
    TypedDict,
)
from uuid import UUID

from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
    FlowBuilderProposalContent,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_event_models import AIBuilderStreamEvent
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    EMPTY_REQUESTED_OUTPUT_SECTIONS,
    RequestedOutputSections,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
    ToolProcessingFailureKind,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import AIBuilderResourceCatalog
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from eneo.flows.ai_builder.planning_state import AggregationIntent, PlanningState
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from eneo.flows.flow_resource_bindings import LocalResourceBinding

if TYPE_CHECKING:
    from eneo.completion_models.infrastructure.completion_service import (
        ResolvedCompletionModelRoute,
    )
    from eneo.flows.ai_builder.ai_builder_litellm_completion import (
        LLMCompletionResponse,
    )
    from eneo.flows.domain.flow import Flow


class LLMToolCallFunctionParam(TypedDict):
    name: str
    arguments: str


class LLMToolCallParam(TypedDict):
    id: str
    type: Literal["function"]
    function: LLMToolCallFunctionParam


LLMMessageRole: TypeAlias = Literal["system", "user", "assistant", "tool"]


class LLMMessageParam(TypedDict):
    role: LLMMessageRole
    content: str | None
    tool_calls: NotRequired[list[LLMToolCallParam]]
    tool_call_id: NotRequired[str]


class ForcedToolChoiceFunctionParam(TypedDict):
    name: str


class ForcedToolChoiceParam(TypedDict):
    type: Literal["function"]
    function: ForcedToolChoiceFunctionParam


ToolChoiceParam: TypeAlias = Literal["auto", "none", "required"] | ForcedToolChoiceParam
MAX_PROPOSAL_PROVIDER_CALLS = 4


def forced_tool_choice(tool_name: str) -> ForcedToolChoiceParam:
    return {
        "type": "function",
        "function": {"name": tool_name},
    }


class ProposalCompletionFn(Protocol):
    def __call__(
        self,
        request: "ProposalCompletionRequest",
    ) -> Awaitable["LLMCompletionResponse"]: ...


@dataclass(slots=True)
class ProposalCallBudget:
    """One per-turn budget shared by the initial proposal and every repair."""

    call_limit: int = MAX_PROPOSAL_PROVIDER_CALLS
    calls_started: int = 0

    def __post_init__(self) -> None:
        if self.call_limit < 1:
            raise ValueError("Proposal call limit must be positive")
        if not 0 <= self.calls_started <= self.call_limit:
            raise ValueError("Started proposal calls must be within the call limit")

    @property
    def calls_remaining(self) -> int:
        return self.call_limit - self.calls_started

    def try_start_call(self) -> bool:
        if self.calls_remaining == 0:
            return False
        self.calls_started += 1
        return True


@dataclass(frozen=True)
class ProposalCompletionRequest:
    messages: list[LLMMessageParam]
    tool_schemas: list[dict[str, Any]]
    route: ResolvedCompletionModelRoute
    max_output_tokens: int
    temperature: float
    tool_choice: ToolChoiceParam | None = None
    counts_as_repair: bool = False


@dataclass(frozen=True)
class CompiledProposal:
    content: FlowBuilderProposalContent
    validation: SpecValidationResult
    reasoning: str | None = None
    resource_bindings: tuple[LocalResourceBinding, ...] = tuple()
    aggregation_intent: AggregationIntent = "linear"


@dataclass(frozen=True)
class ToolProcessingResult:
    events: tuple[AIBuilderStreamEvent, ...] = ()
    compiled_proposal: CompiledProposal | None = None
    user_message: str | None = None
    feedback: str | None = None
    failure_kind: ToolProcessingFailureKind | None = None
    failure_codes: frozenset[str] = frozenset()
    new_planning_state_version: int | None = None


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
    llm_messages: list[LLMMessageParam]
    tool_schemas: list[dict[str, Any]]
    route: ResolvedCompletionModelRoute
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
    before_provider_call: Callable[[], Awaitable[None]] | None = None
    requested_output_sections: RequestedOutputSections = EMPTY_REQUESTED_OUTPUT_SECTIONS
    proposal_call_budget: ProposalCallBudget = field(default_factory=ProposalCallBudget)

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
        messages: list[LLMMessageParam] | None = None,
        tool_schemas: list[dict[str, Any]] | None = None,
        tool_choice: ToolChoiceParam | None = None,
        counts_as_repair: bool = False,
    ) -> ProposalCompletionRequest:
        return ProposalCompletionRequest(
            messages=self.llm_messages if messages is None else messages,
            tool_schemas=self.tool_schemas if tool_schemas is None else tool_schemas,
            route=self.route,
            max_output_tokens=self.max_output_tokens,
            temperature=temperature,
            tool_choice=tool_choice,
            counts_as_repair=counts_as_repair,
        )
