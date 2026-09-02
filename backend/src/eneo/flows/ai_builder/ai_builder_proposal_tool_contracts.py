"""Shared proposal tool contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    NotRequired,
    Protocol,
    TypeAlias,
    TypedDict,
    cast,
)
from uuid import UUID

from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    FlowBuilderProposalContent,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorCode,
    AIBuilderErrorPhase,
    AIBuilderKnownProviderRejectionException,
    build_ai_builder_request_budget_exhausted_error,
)
from eneo.flows.ai_builder.ai_builder_event_models import AIBuilderStreamEvent
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    ResolvedAIBuilderEditContext,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    ProposalObligationProjection,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalAttemptFailureKind,
    ProposalTurnTelemetry,
    ToolProcessingFailureKind,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import AIBuilderResourceCatalog
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.flows.ai_builder.ai_builder_settings import (
    AIBuilderRequestBudget,
    AIBuilderResolvedRequestBudget,
)
from eneo.flows.ai_builder.ai_builder_tool_names import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.ai_builder.ai_builder_tools import ProposalToolSchema
from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from eneo.flows.ai_builder.planning_state import AggregationIntent, PlanningState
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore
from eneo.flows.flow_resource_bindings import LocalResourceBinding
from eneo.tokens.token_utils import count_tool_tokens, measure_provider_input_reserve

if TYPE_CHECKING:
    from eneo.completion_models.infrastructure.completion_service import (
        ResolvedCompletionModelRoute,
    )
    from eneo.flows.ai_builder.ai_builder_create_compile_context import (
        CreateCompileContext,
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


MAX_PROPOSAL_PROVIDER_CALLS = 4

ProposalToolChoiceParam: TypeAlias = ForcedToolChoiceParam | Literal["required"]


def forced_tool_choice(tool_name: str) -> ForcedToolChoiceParam:
    return {
        "type": "function",
        "function": {"name": tool_name},
    }


def proposal_turn_tool_schemas(
    proposal_tool_schema: ProposalToolSchema,
    decline_tool_schema: ProposalToolSchema | None,
) -> list[dict[str, Any]]:
    """Every tool one proposal turn offers, in prompt and budget order."""

    schemas = [cast(dict[str, Any], proposal_tool_schema)]
    if decline_tool_schema is not None:
        schemas.append(cast(dict[str, Any], decline_tool_schema))
    return schemas


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


def replace_repair_group(
    groups: tuple[ProposalMessageGroup, ...],
    messages: tuple[LLMMessageParam, ...],
) -> tuple[ProposalMessageGroup, ...]:
    """Keep exactly one repair group: the latest failed payload and its feedback.

    Earlier failed payloads never return to the prompt, so a repair request
    does not grow per attempt (2,674 to 6,751 prompt tokens over three repairs
    was observed when they accumulated).
    """

    return (
        *(group for group in groups if group.kind != "repair"),
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
        fits=lambda candidate: measure_provider_input_reserve(
            [dict(message) for message in flatten_proposal_message_groups(candidate)],
            [],
            model_name,
        ).tokens
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


def fit_proposal_request_budget(
    *,
    budget: AIBuilderRequestBudget,
    message_groups: tuple[ProposalMessageGroup, ...],
    tool_schemas: list[dict[str, Any]],
    model_name: str,
) -> tuple[tuple[ProposalMessageGroup, ...], AIBuilderResolvedRequestBudget]:
    tool_tokens = count_tool_tokens(tool_schemas, model_name)
    protected_messages = flatten_proposal_message_groups(
        tuple(group for group in message_groups if group.protected)
    )
    resolved = budget.resolve(
        input_tokens=(
            tool_tokens
            + measure_provider_input_reserve(
                [dict(message) for message in protected_messages],
                [],
                model_name,
            ).tokens
        )
    )
    if resolved is None:
        raise AIBuilderKnownProviderRejectionException(
            build_ai_builder_request_budget_exhausted_error(
                request_id=budget.request_id
            )
        )
    fitted = fit_proposal_message_groups(
        message_groups,
        token_limit=resolved.available_input_tokens - tool_tokens,
        model_name=model_name,
    )
    assert fitted is not None, "resolved protected proposal context must fit"
    return fitted, resolved


@dataclass(frozen=True)
class ProposalCompletionRequest:
    message_groups: tuple[ProposalMessageGroup, ...]
    tool_schemas: list[dict[str, Any]]
    route: ResolvedCompletionModelRoute
    target_kind: TargetKind
    request_budget: AIBuilderRequestBudget
    temperature: float
    tool_choice: ProposalToolChoiceParam = field(
        default_factory=lambda: forced_tool_choice(PROPOSE_FLOW_TOOL_NAME)
    )
    counts_as_repair: bool = False
    call_budget: ProposalCallBudget = field(default_factory=ProposalCallBudget)


@dataclass(frozen=True)
class CompiledProposal:
    content: FlowBuilderProposalContent
    validation: SpecValidationResult
    resource_bindings: tuple[LocalResourceBinding, ...] = tuple()
    aggregation_intent: AggregationIntent = "linear"


@dataclass(frozen=True)
class ProposalReady:
    """A compiled candidate that finalization still has to persist."""

    compiled: CompiledProposal


@dataclass(frozen=True)
class ProposalAnswer:
    """A completed answer with no plan.

    The submission owner persists it like an accepted proposal, so it is never
    a turn the conversation forgets.
    """

    answer: str


@dataclass(frozen=True)
class CorrectableFailure:
    """The model can fix this with one more call; the feedback is the whole brief.

    Producers write feedback that stands on its own: the failure, the exact
    path, and the correction. No consumer adds recipes or inspects `codes` to
    decide whether to retry.
    """

    feedback: str
    kind: ToolProcessingFailureKind
    codes: frozenset[str] = frozenset()


@dataclass(frozen=True)
class TerminalFailure:
    """No further model call can help; the turn ends with this typed error.

    A server defect, a precondition the request cannot meet, or something only
    the user can change. The producer states the public error's facts; the loop
    owner renders the event with the request identity.
    """

    kind: ProposalAttemptFailureKind
    message: str
    code: AIBuilderErrorCode
    phase: AIBuilderErrorPhase
    details: Mapping[str, object] | None = None
    codes: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ProposalCompleted:
    """The turn is durably committed; these are the events the client sees."""

    events: tuple[AIBuilderStreamEvent, ...]


PreparationOutcome: TypeAlias = (
    ProposalReady | ProposalAnswer | CorrectableFailure | TerminalFailure
)
SubmissionOutcome: TypeAlias = ProposalCompleted | CorrectableFailure | TerminalFailure


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
    forced_tool_prompt: str
    process_tool_invocation: Callable[
        [ToolRetryInvocation], Awaitable[SubmissionOutcome]
    ]


@dataclass(frozen=True)
class ProposalTurnContext:
    turn: SessionSendTurn
    conversation: list[ConversationMessage]
    new_messages_start: int
    message_groups: tuple[ProposalMessageGroup, ...]
    proposal_tool_schema: ProposalToolSchema
    route: ResolvedCompletionModelRoute
    available_model_refs: set[str] | None
    available_kb_refs: set[str] | None
    resource_catalog: AIBuilderResourceCatalog | None
    proposal_request_budget: AIBuilderRequestBudget
    request_id: str
    planning_state: PlanningState
    flow: "Flow | None" = None
    assistant_snapshots: AssistantAuthoringSnapshots | None = None
    text_content: str | None = None
    assistant_metadata: dict[str, Any] | None = None
    usage_tracker: ProposalTurnTelemetry | None = None
    plan_edit_context: ResolvedAIBuilderEditContext | None = None
    prior_spec_for_revision: FlowDraftSpecCore | None = None
    obligation_projection: ProposalObligationProjection | None = None
    before_provider_call: Callable[[], Awaitable[None]] | None = None
    proposal_call_budget: ProposalCallBudget = field(default_factory=ProposalCallBudget)
    compile_context: "CreateCompileContext | None" = None
    decline_tool_schema: ProposalToolSchema | None = None

    @property
    def session_id(self) -> UUID:
        return self.turn.session_id

    @property
    def base_planning_state_version(self) -> int:
        return self.turn.base_planning_state_version

    @property
    def target_kind(self) -> TargetKind:
        return TargetKind.EDIT if self.flow is not None else TargetKind.CREATE

    def completion_request(
        self,
        *,
        temperature: float,
        message_groups: tuple[ProposalMessageGroup, ...] | None = None,
        counts_as_repair: bool = False,
    ) -> ProposalCompletionRequest:
        selected_message_groups = (
            self.message_groups if message_groups is None else message_groups
        )
        tool_schemas = proposal_turn_tool_schemas(
            self.proposal_tool_schema,
            None if counts_as_repair else self.decline_tool_schema,
        )
        return ProposalCompletionRequest(
            message_groups=selected_message_groups,
            tool_schemas=tool_schemas,
            route=self.route,
            target_kind=self.target_kind,
            request_budget=self.proposal_request_budget,
            temperature=temperature,
            tool_choice=(
                "required"
                if self.decline_tool_schema is not None and not counts_as_repair
                else forced_tool_choice(PROPOSE_FLOW_TOOL_NAME)
            ),
            counts_as_repair=counts_as_repair,
            call_budget=self.proposal_call_budget,
        )
