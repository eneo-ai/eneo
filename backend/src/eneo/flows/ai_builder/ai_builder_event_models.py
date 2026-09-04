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
from eneo.flows.ai_builder.ai_builder_flow_schema_values import BuilderFormFieldType
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)
from eneo.flows.ai_builder.ai_builder_telemetry_models import (
    SessionTelemetrySummary,
)
from eneo.flows.ai_builder.planning_state import (
    AttachmentCoverage,
    FileRole,
    NamedResultOrigin,
)
from eneo.flows.flow_ai_builder_budget_settings import (
    AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT,
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


class AssumptionRowPayload(BaseModel):
    """One requirement Eneo settled without the user answering it.

    `topic` is the slot's summary label and `label` the option's own label,
    so the card can say "Topic: Label" without knowing the catalog;
    `question_id` names the canonical question a reopen sends the user back
    to, and is the slot. A row carries no provenance on purpose: accepting
    the card must re-render the same record, so how the value was read is
    not part of what the user signs.
    """

    question_id: str
    slot_name: str
    value: str
    topic: str
    label: str

    @model_validator(mode="after")
    def _row_is_its_question(self) -> "AssumptionRowPayload":
        if self.question_id != self.slot_name:
            raise ValueError("an assumption row reopens the question of its own slot")
        if self.question_id not in KNOWN_REQUIREMENT_SLOT_NAMES:
            raise ValueError("assumption row must name a known requirement slot")
        return self


class AttachmentRowPayload(BaseModel):
    """One attached file as the card shows it: what it is, how sure, and
    whether it travels with the flow.

    `travels` is the committed architecture's decision (a template under a
    template-fill commit), never the role label's. How sure the reading is
    stays outside this row: a new citation or a changed confidence for the
    same role is not a different plan, so it must not move the version
    (see `RequirementsSummaryPayload.weak_role_file_ids`). Ids only: the
    client owns the labels.
    """

    file_id: UUID
    filename: str
    role: FileRole
    readable: bool
    coverage: AttachmentCoverage
    travels: bool
    placeholders: list[str] | None = None


class RunPreviewTemplatePayload(BaseModel):
    filename: str
    placeholder_count: int = Field(ge=0)


class RunPreviewPayload(BaseModel):
    """The contract a run will follow, derived from planning state alone.

    A preview of the contract, not of a result: it names what a run receives
    and what kind of result comes out, never values, prose, layout, step
    counts or execution. Every field is commit grade or a committed decision,
    so the card previews only what the user is asked to sign.
    """

    runtime_input: str | None = None
    max_files: int | None = Field(default=None, ge=1)
    result_type: str | None = None
    report_layout: str | None = None
    required_sections: list[str] = Field(default_factory=list)
    obligations: list[str] = Field(default_factory=list)
    template: RunPreviewTemplatePayload | None = None


def _named_content_fields_are_empty(
    value: list["NamedContentFieldPayload"],
) -> bool:
    return not value


class NamedContentFieldPayload(BaseModel):
    """One content obligation the user named, as an item rather than prose.

    `id` is an opaque stable encoding of the full folded location. `label` is
    the bounded leaf rendering; `segments` and `unplaced` carry placement for
    the card without asking the client to parse the identifier.

    `origin` says how the name got here — read out of the user's own writing,
    or typed into this card. It is display provenance, not a requirement: both
    origins oblige the result to exactly the same content, which is why it
    stays outside the confirmed disclosure identity.
    """

    id: str
    label: str
    name: str
    segments: list[str]
    unplaced: bool
    # True when the obligation's declared shape (array/object) can own
    # nested fields — the card's placement affordance offers exactly these,
    # including childless ones.
    can_contain_fields: bool
    origin: NamedResultOrigin = "described"

    @model_validator(mode="after")
    def require_unplaced_without_segments(self) -> "NamedContentFieldPayload":
        # The wire shape is flat for client simplicity, but the placement is
        # a discriminated union in substance: an unplaced name has no path.
        if self.unplaced and self.segments:
            raise ValueError("an unplaced named content field cannot carry segments")
        return self


def _weak_role_file_ids_are_empty(value: list[UUID]) -> bool:
    return not value


def _attachment_rows_are_empty(value: list["AttachmentRowPayload"]) -> bool:
    return not value


def _run_preview_is_absent(value: "RunPreviewPayload | None") -> bool:
    return value is None


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
    # The two facts a user signs off on: the confirmation card must never
    # show a hole where the input or output should be, so the contract, not
    # the builder's defaults, guarantees they are filled.
    input_description: str = Field(min_length=1)
    output_description: str = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    assumption_rows: list[AssumptionRowPayload] = Field(
        default_factory=list[AssumptionRowPayload],
        max_length=len(KNOWN_REQUIREMENT_SLOT_NAMES),
    )
    manual_setup_notes: list[str] = Field(default_factory=list)
    resolved_requirements: list[ResolvedRequirementPayload] = Field(
        default_factory=_empty_resolved_requirements,
        max_length=len(KNOWN_REQUIREMENT_SLOT_NAMES),
        exclude_if=_resolved_requirements_are_empty,
    )
    # Typed truth for the card: every attachment as a row, and the contract a
    # run will follow. Both are part of what the user signs.
    attachment_rows: list[AttachmentRowPayload] = Field(
        default_factory=list[AttachmentRowPayload],
        max_length=AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT,
        exclude_if=_attachment_rows_are_empty,
    )
    run_preview: RunPreviewPayload | None = Field(
        default=None, exclude_if=_run_preview_is_absent
    )

    @field_validator("input_description", "output_description", mode="after")
    @classmethod
    def _describes_something(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must describe the input or output, not be blank")
        return value

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

    @field_validator("assumption_rows", mode="after")
    @classmethod
    def _one_assumption_per_slot(
        cls,
        rows: list[AssumptionRowPayload],
    ) -> list[AssumptionRowPayload]:
        if len({row.slot_name for row in rows}) != len(rows):
            raise ValueError("assumption rows require one row per slot")
        return rows


def _runtime_input_fields_are_empty(
    value: list["RuntimeInputFieldPayload"],
) -> bool:
    return not value


class RuntimeInputFieldPayload(BaseModel):
    """One field the flow's operator fills in before a run.

    `key` is the variable name the compiled form and the step instructions
    use, `label` and `type` are what the form control shows and is, and
    `options` are the choices a `select` or `multiselect` offers (a `list`
    field is free entry and has none). Values are
    exact rather than clipped: the summary sentence composes every field into
    one line and has to keep that line readable, while a list gives each field
    its own row and must show the identity the compiled flow will use.

    `purpose` is what the field is for, in the same words the user picked it
    by, so it is a localized label and not a token to branch on.
    """

    key: str
    label: str
    type: BuilderFormFieldType
    required: bool
    purpose: str
    options: list[str] = Field(default_factory=list[str])


class RequirementsSummaryPayload(RequirementsDisclosureContent):
    """A disclosure the user can confirm, named by the hash of its content."""

    # Required, because a summary the client cannot name is a summary the user
    # cannot confirm: the confirmation request carries this exact version back.
    requirements_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Attachments whose role is a weak reading the user should check. Display
    # provenance beside the hashed rows: a changed confidence for the same role
    # is not a different disclosure.
    weak_role_file_ids: list[UUID] = Field(
        default_factory=list[UUID], exclude_if=_weak_role_file_ids_are_empty
    )
    # The content obligations the user named, as readable items below the lead
    # summary. This is also the edit surface: the user sends
    # the ids they leave standing back as a `named_content_fields_edit`, and
    # the disclosure is rebuilt from the resulting set.
    #
    # It deliberately sits outside `RequirementsDisclosureContent`, so it does
    # not enter the version hash. The same names already reach the private
    # identity rendering; hashing them again would make a projection of
    # one fact look like a second fact the user attested to.
    named_content_fields: list[NamedContentFieldPayload] = Field(
        default_factory=list[NamedContentFieldPayload],
        exclude_if=_named_content_fields_are_empty,
    )
    # The form the flow will ask its operator to fill in, as items beside the
    # assumption sentence that already states it. Outside the hashed content
    # for the same reason as the names above: the same fields already reach
    # identity through that sentence, and hashing the projection too would
    # make one confirmed fact look like two.
    runtime_input_fields: list[RuntimeInputFieldPayload] = Field(
        default_factory=list[RuntimeInputFieldPayload],
        exclude_if=_runtime_input_fields_are_empty,
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
    RuntimeInputFieldPayload,
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
    "AssumptionRowPayload",
    "KeyDecisionPayload",
    "NamedContentFieldPayload",
    "ResolvedRequirementPayload",
    "RequirementsSummaryPayload",
    "RuntimeInputFieldPayload",
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
