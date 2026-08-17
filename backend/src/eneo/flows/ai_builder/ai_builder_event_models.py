from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal, TypeAlias, cast
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from eneo.flows.ai_builder.ai_builder_domain_models import FlowBuilderProposalContent
from eneo.flows.ai_builder.ai_builder_error_contract import AIBuilderErrorEvent
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)
from eneo.flows.ai_builder.ai_builder_telemetry_models import (
    SessionTelemetrySummary,
)

JsonScalar: TypeAlias = str | int | float | bool | None


class AIBuilderStatus(StrEnum):
    ARCHITECTURE_COMMITTED = "architecture_committed"
    ARCHITECTURE_REVISED = "architecture_revised"
    REPAIRING = "repairing"


class StructuredQuestionOptionPayload(BaseModel):
    id: str | None = None
    label: str
    value: JsonScalar = None
    description: str | None = None
    # What choosing this option produces, said in the user's own terms: the
    # file they end up with, or what the flow does at run time. The
    # description says what the option means; this says what it gets them.
    # Null where no honest concrete consequence can be named, because an
    # invented example is worse than none.
    example: str | None = None


class StructuredQuestionPayload(BaseModel):
    question_id: str
    question: str
    options: list[StructuredQuestionOptionPayload]
    selection_mode: Literal["single", "multi"]
    allow_custom: bool
    requires_confirm: bool = False
    input_field_collection: bool = Field(
        default=False,
        exclude_if=lambda value: value is False,
    )
    # The option the flow being edited already uses for this slot, read off the
    # flow itself. It is what makes a question about a running flow answerable:
    # the user can see which answer keeps the flow as it is, and which one
    # changes what other applications already run against.
    #
    # Null outside an edit session, and null in one whenever the flow does not
    # answer the slot or answers it with something no offered option carries.
    current_option_id: str | None = None
    # Eneo's own reading of this slot, offered so a user who cannot judge the
    # choice can hand this one question back. It settles nothing on its own;
    # naming it here is what makes the answer the option they were shown.
    #
    # While editing, the only thing Eneo recommends is keeping what the flow
    # already does, so this either equals current_option_id or is absent.
    # Anything else is a proposal to change something already running, which is
    # the user's decision to make rather than a badge to accept.
    recommended_option_id: str | None = None
    # The user's own words behind that reading: the quote the classifier cited
    # for the slot, verbatim from a message the user wrote or an option they
    # selected. Null when the reading rests on something else — a policy
    # default, a heuristic, or attachment structure — so a recommendation is
    # never dressed up as something the user said.
    recommended_option_evidence: str | None = None
    # Where this question sits in the sequence the user is walking through:
    # the server's own count of the questions this session has put to them,
    # counting this one. A re-asked question keeps its number.
    #
    # There is deliberately no companion total. Architecture questions, the
    # budget-exempt quality questions, and the schema-direction and
    # runtime-field questions are each decided outside the per-turn ask queue,
    # so no owner holds the length of the whole interview, and a total taken
    # from the queue alone can undercount and claim the last question before
    # another one arrives.
    question_index: int | None = Field(default=None, ge=1)
    # What this question is about, in the same few words the requirements
    # summary already uses for the slot it settles, so the question and the
    # summary row the user later confirms name one topic identically.
    #
    # Null for a question that settles no catalog slot — schema direction and
    # runtime field details — because the catalog holds no label for those, and
    # deriving one from the question's own wording would be a second name for
    # the same thing, free to drift from the first.
    topic: str | None = None
    # How many further questions the interview currently intends to ask after
    # this one, taken from the ordered ask queue this turn was decided from.
    #
    # A snapshot of the current plan, not a promise. The queue is re-derived
    # every turn from everything the session knows by then, so it shrinks when
    # one answer settles several slots, and it can grow when an answer opens a
    # family that was not in play before — answering that a JSON flow returns
    # structured JSON is what makes the JSON-processing question exist at all,
    # and it arrives on the turn after a queue that held nothing else. Null
    # when the question was decided outside that queue and no plan stands
    # behind it: the schema-direction and runtime-field questions, and every
    # question asked by an owner that does not rank the interview.
    questions_planned_remaining: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _named_options_are_offered_and_agree(self) -> "StructuredQuestionPayload":
        if self.current_option_id is not None:
            self._require_one_offered_option(
                "current_option_id", self.current_option_id
            )
        if self.recommended_option_id is None:
            if self.recommended_option_evidence is not None:
                raise ValueError(
                    "recommended_option_evidence requires a recommended option"
                )
            return self
        self._require_one_offered_option(
            "recommended_option_id", self.recommended_option_id
        )
        if (
            self.current_option_id is not None
            and self.recommended_option_id != self.current_option_id
        ):
            raise ValueError(
                "recommended_option_id must not differ from current_option_id: "
                "recommending a change to what the flow already does is a "
                "proposal, not a recommendation"
            )
        return self

    def _require_one_offered_option(self, field_name: str, option_id: str) -> None:
        named = [option for option in self.options if option.id == option_id]
        if len(named) != 1:
            raise ValueError(f"{field_name} must name exactly one offered option")


class AIBuilderTextEventData(BaseModel):
    text: str


class AIBuilderStatusEventData(BaseModel):
    status: AIBuilderStatus


class KeyDecisionPayload(BaseModel):
    topic: str
    decision: str
    # The structured question that settles this decision, so a reader can be
    # sent back to the exact question instead of guessing which one moved.
    # Present only when the user answered a question the catalog can ask
    # again; None for everything the Builder derived.
    question_id: str | None = None
    # Whether this decision follows from what the user said rather than being
    # answered. Derived is the default: a record that does not say cannot
    # prove the user answered, and presenting it as answered invites trust the
    # record does not carry.
    is_derived: bool = True

    @model_validator(mode="after")
    def _provenance_is_one_claim(self) -> "KeyDecisionPayload":
        # Two fields, one fact. Naming a question the user answered while
        # calling the decision derived — or either half alone — would leave a
        # client to guess which half to believe.
        if self.is_derived != (self.question_id is None):
            raise ValueError(
                "a decision names the question it was answered with exactly "
                "when it is not derived"
            )
        if self.question_id is not None and (
            self.question_id not in KNOWN_REQUIREMENT_SLOT_NAMES
        ):
            # The point of naming a question is that the reader can be sent
            # back to it. A name the vocabulary does not hold is a link to
            # nowhere, which is worse than saying nothing.
            raise ValueError("question_id must name a known requirement question")
        return self


class ResolvedRequirementPayload(BaseModel):
    requirement_id: str
    selected_value: str


def _named_content_fields_are_empty(
    value: list["NamedContentFieldPayload"],
) -> bool:
    return not value


class NamedContentFieldPayload(BaseModel):
    """One content obligation the user named, as an item rather than prose.

    `id` is the obligation name as the user wrote it and as planning state
    stores it. It is not a promise that a field by that name reaches the
    compiled result: whether an obligation is projected at all depends on the
    output mode, the presence of a declared schema, and the confidence the name
    was admitted with. `label` is what the summary sentence says about the same
    obligation, rendered by the same owner, so list and prose cannot disagree.
    """

    id: str
    label: str


def _resolved_requirements_are_empty(
    value: list[ResolvedRequirementPayload],
) -> bool:
    return not value


def _empty_resolved_requirements() -> list[ResolvedRequirementPayload]:
    return []


class RequirementsDisclosureContent(BaseModel):
    """What the user is shown, before an identity is stamped on it.

    The requirements version hashes this content, so the version cannot be one
    of its own fields. Only the disclosure builder handles the unversioned
    form; everything the Builder emits or persists is a
    `RequirementsSummaryPayload`.
    """

    summary: str
    key_decisions: list[KeyDecisionPayload]
    input_description: str
    output_description: str
    assumptions: list[str] = Field(default_factory=list)
    manual_setup_notes: list[str] = Field(default_factory=list)
    resolved_requirements: list[ResolvedRequirementPayload] = Field(
        default_factory=_empty_resolved_requirements,
        max_length=len(KNOWN_REQUIREMENT_SLOT_NAMES),
        exclude_if=_resolved_requirements_are_empty,
    )

    @field_validator("key_decisions", mode="after")
    @classmethod
    def _one_decision_per_topic(
        cls, decisions: list[KeyDecisionPayload]
    ) -> list[KeyDecisionPayload]:
        # A topic names a single decision; the planner occasionally repeats a
        # topic, which would render as duplicate rows. Keep the first occurrence
        # so the summary stays unique and the UI's per-topic keys do not collide.
        seen: set[str] = set()
        unique: list[KeyDecisionPayload] = []
        for decision in decisions:
            if decision.topic in seen:
                continue
            seen.add(decision.topic)
            unique.append(decision)
        return unique

    @field_validator("resolved_requirements", mode="after")
    @classmethod
    def _one_value_per_requirement(
        cls, requirements: list[ResolvedRequirementPayload]
    ) -> list[ResolvedRequirementPayload]:
        seen: set[str] = set()
        unique: list[ResolvedRequirementPayload] = []
        for requirement in requirements:
            if requirement.requirement_id in seen:
                continue
            seen.add(requirement.requirement_id)
            unique.append(requirement)
        return unique


class RequirementsSummaryPayload(RequirementsDisclosureContent):
    """A disclosure the user can confirm, named by the hash of its content."""

    # Required, because a summary the client cannot name is a summary the user
    # cannot confirm: the confirmation request carries this exact version back.
    requirements_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    # The content obligations the user named, as items beside the sentence
    # that already states them. Read-only: naming content is admitted from
    # cited user evidence, and adding or removing an obligation has no
    # contract yet, so this list is for reading and not an edit surface.
    #
    # It deliberately sits outside `RequirementsDisclosureContent`, so it does
    # not enter the version hash. The same names already reach identity
    # through the summary prose; hashing them again would make a projection of
    # one fact look like a second fact the user attested to.
    named_content_fields: list[NamedContentFieldPayload] = Field(
        default_factory=list[NamedContentFieldPayload],
        exclude_if=_named_content_fields_are_empty,
    )


class AIBuilderPlanEventData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    proposal: FlowBuilderProposalContent


class AIBuilderTextEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["text"] = "text"
    data: AIBuilderTextEventData


class AIBuilderStatusEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["status"] = "status"
    data: AIBuilderStatusEventData


class AIBuilderQuestionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["question"] = "question"
    data: StructuredQuestionPayload


class AIBuilderRequirementsSummaryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["requirements_summary"] = "requirements_summary"
    data: RequirementsSummaryPayload


class AIBuilderPlanEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["plan"] = "plan"
    data: AIBuilderPlanEventData


class AIBuilderUsageEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["usage"] = "usage"
    data: SessionTelemetrySummary


class AIBuilderDoneEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["done"] = "done"
    data: Literal[""] = ""


AIBuilderStreamEvent: TypeAlias = Annotated[
    AIBuilderTextEvent
    | AIBuilderStatusEvent
    | AIBuilderQuestionEvent
    | AIBuilderRequirementsSummaryEvent
    | AIBuilderPlanEvent
    | AIBuilderUsageEvent
    | AIBuilderErrorEvent
    | AIBuilderDoneEvent,
    Field(discriminator="event"),
]

_AI_BUILDER_STREAM_EVENT_ADAPTER: Final[TypeAdapter[AIBuilderStreamEvent]] = (
    TypeAdapter(AIBuilderStreamEvent)
)


def _event_name(model: type[BaseModel]) -> str:
    value = model.model_fields["event"].default
    if not isinstance(value, str):
        raise TypeError(f"{model.__name__}.event must have a string default")
    return value


SSE_EVENT_TEXT: Final = _event_name(AIBuilderTextEvent)
SSE_EVENT_PLAN: Final = _event_name(AIBuilderPlanEvent)
SSE_EVENT_QUESTION: Final = _event_name(AIBuilderQuestionEvent)
SSE_EVENT_REQUIREMENTS_SUMMARY: Final = _event_name(AIBuilderRequirementsSummaryEvent)
SSE_EVENT_ERROR: Final = _event_name(AIBuilderErrorEvent)
SSE_EVENT_STATUS: Final = _event_name(AIBuilderStatusEvent)
SSE_EVENT_USAGE: Final = _event_name(AIBuilderUsageEvent)
SSE_EVENT_DONE: Final = _event_name(AIBuilderDoneEvent)

AI_BUILDER_STREAM_EVENT_MODELS: tuple[type[BaseModel], ...] = (
    AIBuilderTextEvent,
    AIBuilderStatusEvent,
    AIBuilderQuestionEvent,
    AIBuilderRequirementsSummaryEvent,
    AIBuilderPlanEvent,
    AIBuilderUsageEvent,
    AIBuilderErrorEvent,
    AIBuilderDoneEvent,
)

AI_BUILDER_SCHEMA_HOIST_MODELS: tuple[type[BaseModel], ...] = (
    AIBuilderTextEventData,
    AIBuilderStatusEventData,
    StructuredQuestionOptionPayload,
    StructuredQuestionPayload,
    KeyDecisionPayload,
    ResolvedRequirementPayload,
    NamedContentFieldPayload,
    RequirementsSummaryPayload,
    AIBuilderPlanEventData,
    SessionTelemetrySummary,
    *AI_BUILDER_STREAM_EVENT_MODELS,
)


def ai_builder_stream_event_schema() -> dict[str, object]:
    schema = _AI_BUILDER_STREAM_EVENT_ADAPTER.json_schema(
        ref_template="#/components/schemas/{model}"
    )
    schema.pop("$defs", None)
    return cast(dict[str, object], schema)


__all__ = [
    "AI_BUILDER_SCHEMA_HOIST_MODELS",
    "AI_BUILDER_STREAM_EVENT_MODELS",
    "AIBuilderDoneEvent",
    "AIBuilderErrorEvent",
    "AIBuilderPlanEventData",
    "AIBuilderPlanEvent",
    "AIBuilderQuestionEvent",
    "AIBuilderRequirementsSummaryEvent",
    "AIBuilderStatus",
    "AIBuilderStatusEventData",
    "AIBuilderStatusEvent",
    "AIBuilderStreamEvent",
    "AIBuilderTextEventData",
    "AIBuilderTextEvent",
    "AIBuilderUsageEvent",
    "KeyDecisionPayload",
    "NamedContentFieldPayload",
    "ResolvedRequirementPayload",
    "RequirementsSummaryPayload",
    "SSE_EVENT_DONE",
    "SSE_EVENT_ERROR",
    "SSE_EVENT_PLAN",
    "SSE_EVENT_QUESTION",
    "SSE_EVENT_REQUIREMENTS_SUMMARY",
    "SSE_EVENT_STATUS",
    "SSE_EVENT_TEXT",
    "SSE_EVENT_USAGE",
    "StructuredQuestionOptionPayload",
    "StructuredQuestionPayload",
    "ai_builder_stream_event_schema",
]
