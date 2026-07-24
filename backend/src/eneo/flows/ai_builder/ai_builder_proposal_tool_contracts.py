"""Shared proposal tool contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
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
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderKnownProviderRejectionException,
    build_ai_builder_request_budget_exhausted_error,
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
from eneo.tokens.token_utils import count_message_tokens, count_tool_tokens

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


class ProposalCallBudgetExhausted(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProposalMessageGroup:
    messages: tuple[LLMMessageParam, ...]
    kind: Literal["system", "history", "current_turn", "repair"]
    protected: bool

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("Proposal message groups cannot be empty")


def group_proposal_messages(
    messages: list[LLMMessageParam],
    *,
    current_turn_index: int | None,
) -> tuple[ProposalMessageGroup, ...]:
    groups: list[ProposalMessageGroup] = []
    index = 0
    while index < len(messages):
        group_start = index
        message = messages[index]
        group = [message]
        if message["role"] == "assistant" and message.get("tool_calls"):
            index += 1
            while index < len(messages) and messages[index]["role"] == "tool":
                group.append(messages[index])
                index += 1
        else:
            index += 1
        is_system = message["role"] == "system"
        is_current_turn = (
            current_turn_index is not None and group_start <= current_turn_index < index
        )
        kind: Literal["system", "history", "current_turn", "repair"] = (
            "system" if is_system else "current_turn" if is_current_turn else "history"
        )
        groups.append(
            ProposalMessageGroup(
                messages=tuple(group),
                kind=kind,
                protected=is_system or is_current_turn,
            )
        )
    if current_turn_index is not None and not any(
        group.kind == "current_turn" for group in groups
    ):
        raise ValueError("Current proposal turn is missing from provider messages")
    return tuple(groups)


def append_protected_repair_group(
    groups: tuple[ProposalMessageGroup, ...],
    messages: tuple[LLMMessageParam, ...],
) -> tuple[ProposalMessageGroup, ...]:
    optional_prior_repairs = tuple(
        replace(group, protected=False) if group.kind == "repair" else group
        for group in groups
    )
    return (
        *optional_prior_repairs,
        ProposalMessageGroup(messages=messages, kind="repair", protected=True),
    )


def fit_proposal_message_groups(
    groups: tuple[ProposalMessageGroup, ...],
    *,
    token_limit: int,
    model_name: str,
) -> tuple[ProposalMessageGroup, ...] | None:
    return _evict_optional_message_groups(
        groups,
        fits=lambda candidate: count_message_tokens(
            [dict(message) for message in flatten_proposal_message_groups(candidate)],
            model_name,
        )
        <= token_limit,
    )


def _evict_optional_message_groups(
    groups: tuple[ProposalMessageGroup, ...],
    *,
    fits: Callable[[tuple[ProposalMessageGroup, ...]], bool],
) -> tuple[ProposalMessageGroup, ...] | None:
    kept = list(groups)
    if fits(tuple(kept)):
        return tuple(kept)
    for group in groups:
        if group.protected:
            continue
        kept.remove(group)
        if fits(tuple(kept)):
            return tuple(kept)
    return None


def flatten_proposal_message_groups(
    groups: tuple[ProposalMessageGroup, ...],
) -> list[LLMMessageParam]:
    return [message for group in groups for message in group.messages]


@dataclass(frozen=True)
class ProposalRequestBudget:
    context_window_tokens: int
    output_reserve_tokens: int
    safety_buffer_tokens: int
    request_id: str | None = None

    def __post_init__(self) -> None:
        if self.context_window_tokens < 1:
            raise ValueError("Proposal context window must be positive")
        if self.output_reserve_tokens < 0 or self.safety_buffer_tokens < 0:
            raise ValueError("Proposal request reserves cannot be negative")

    def fit(
        self,
        *,
        message_groups: tuple[ProposalMessageGroup, ...],
        tool_schemas: list[dict[str, Any]],
        model_name: str,
    ) -> tuple[ProposalMessageGroup, ...]:
        reserved_tokens = (
            count_tool_tokens(tool_schemas, model_name)
            + self.output_reserve_tokens
            + self.safety_buffer_tokens
        )
        fitted = fit_proposal_message_groups(
            message_groups,
            token_limit=self.context_window_tokens - reserved_tokens,
            model_name=model_name,
        )
        if fitted is not None:
            return fitted
        raise AIBuilderKnownProviderRejectionException(
            build_ai_builder_request_budget_exhausted_error(request_id=self.request_id)
        )


@dataclass(frozen=True)
class ProposalCompletionRequest:
    message_groups: tuple[ProposalMessageGroup, ...]
    tool_schemas: list[dict[str, Any]]
    route: ResolvedCompletionModelRoute
    max_output_tokens: int
    temperature: float
    tool_choice: ToolChoiceParam | None = None
    counts_as_repair: bool = False
    request_budget: ProposalRequestBudget | None = None
    call_budget: ProposalCallBudget = field(default_factory=ProposalCallBudget)


@dataclass(frozen=True)
class CompiledProposal:
    content: FlowBuilderProposalContent
    validation: SpecValidationResult
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
    message_groups: tuple[ProposalMessageGroup, ...]
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
    proposal_request_budget: ProposalRequestBudget | None = None

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
        message_groups: tuple[ProposalMessageGroup, ...] | None = None,
        tool_schemas: list[dict[str, Any]] | None = None,
        tool_choice: ToolChoiceParam | None = None,
        counts_as_repair: bool = False,
    ) -> ProposalCompletionRequest:
        request_tool_schemas = (
            self.tool_schemas if tool_schemas is None else tool_schemas
        )
        return ProposalCompletionRequest(
            message_groups=(
                self.message_groups if message_groups is None else message_groups
            ),
            tool_schemas=request_tool_schemas,
            route=self.route,
            max_output_tokens=self.max_output_tokens,
            temperature=temperature,
            tool_choice=tool_choice,
            counts_as_repair=counts_as_repair,
            request_budget=self.proposal_request_budget,
            call_budget=self.proposal_call_budget,
        )
