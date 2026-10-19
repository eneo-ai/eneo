"""MCP tool cases of the Builder harness: the seeded catalogue a run is read
against, the case's answers to tool questions, and the M1-M8 checks.

A seed manifest (written by the seeding tool) names each server and tool of
the run's space with the ref the Builder shows for it, and the call log the
test server writes. A case names tools by server and name only; the manifest
resolves them. Scripted answers are matched on a question's typed tool facts
and its offered options, never on its id or text. The checks read only what
an observation bundle keeps (`mcp_evidence`, the interactions and the final
plan, and for an edit the saved and applied flow), so a reanalysis decides
as the live run did; evidence that does not read whole leaves a check
unmeasured, never passed.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias, cast
from uuid import UUID

from ai_builder_edit_expectation import (
    edge_steps,
    flow_edges,
    observed_atoms,
    snapshot_view,
)
from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from eneo.flows.ai_builder.ai_builder_event_models import (
    AIBuilderToolRefusal,
    StructuredQuestionOptionPayload,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import NonPlanKind
from eneo.flows.ai_builder.ai_builder_tool_catalog import TOOL_REF_PATTERN, tool_ref
from eneo.flows.ai_builder.ai_builder_tool_question_ids import AIBuilderToolQuestion
from eneo.flows.ai_builder.ai_builder_tool_questions import (
    NO_TOOL,
    RELEVANCE_DONT_USE,
    RELEVANCE_SHOW_TOOLS,
    RELEVANCE_USE,
)
from eneo.flows.domain.tool_input import (
    TOOL_INPUT_CONFIG_KEY,
    BoundArgument,
    ToolArgumentError,
    ToolInputConfig,
)
from eneo.flows.flow_authoring_spec import FormFieldSpec, authoring_form_field
from eneo.flows.flow_metadata import FlowFormFieldType, parse_flow_form_field_type
from eneo.flows.template_reference_analyzer import (
    TemplateReferenceKind,
    analyze_template,
)
from eneo.main.exceptions import BadRequestException
from eneo.mcp_servers.domain.unattended_tool_refusal import UnattendedToolRefusal

JsonObject = dict[str, Any]
_CLOSED = ConfigDict(extra="forbid", frozen=True)
_Name = Annotated[str, Field(min_length=1)]
_Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ToolQuestionFamily = Literal["relevance", "choice", "argument"]
# The answer source an interaction records when a tool rule answered it.
TOOL_ANSWER_SOURCE = "case_tool_answer"
# Set on the interaction that sends a scripted follow-up message: it starts
# the next user turn of the session.
SCRIPTED_TURN_KEY = "scripted_turn"
# The checks each dimension needs, when applicable (`_verdict_states`); the
# others (M2, M6) carry `gating` false: reported beside them, deciding nothing.
PLAN_CHECK_NAMES = (
    "mcp_m1_questions",
    "mcp_m1_no_tools",
    "mcp_m3_bindings",
    "mcp_m4_outcome",
    "mcp_m7_tool_output_reaches_last_step",
    "mcp_m8_saved_flow_kept",
)
OUTPUT_CHECK_NAMES = ("mcp_m5_calls",)


class ToolSelector(BaseModel):
    """A tool as a case names it: its server's name and its own."""

    model_config = _CLOSED

    server: _Name
    name: _Name


# --- the seed manifest ---------------------------------------------------------


class SeedServer(BaseModel):
    model_config = _CLOSED

    name: _Name
    server_id: UUID
    url: _Name


class SeedTool(BaseModel):
    model_config = _CLOSED

    server: _Name
    name: _Name
    tool_id: UUID
    ref: Annotated[str, Field(pattern=TOOL_REF_PATTERN)]
    schema_sha256: _Sha256
    enabled_in_space: StrictBool


class SeedManifest(BaseModel):
    model_config = _CLOSED

    version: Literal[1]
    block: _Name
    space_id: UUID
    seeded_at: AwareDatetime
    servers: list[SeedServer] = Field(min_length=1)
    tools: list[SeedTool]
    call_log: _Name
    catalog_sha256: _Sha256

    @model_validator(mode="after")
    def _tools_carry_the_refs_the_builder_shows(self) -> SeedManifest:
        server_ids = {server.name: server.server_id for server in self.servers}
        if len(server_ids) != len(self.servers):
            raise ValueError("each seeded server is named once")
        if len({(tool.server, tool.name) for tool in self.tools}) != len(self.tools):
            raise ValueError("each seeded tool is named once")
        for tool in self.tools:
            server_id = server_ids.get(tool.server)
            if server_id is None or tool.ref != tool_ref(server_id, tool.tool_id):
                raise ValueError(
                    f"tool {tool.server}/{tool.name}: ref is not the one the "
                    "Builder shows for its server and tool ids"
                )
        if not Path(self.call_log).is_absolute():
            raise ValueError("call_log must be an absolute path")
        return self

    def tool(self, selector: ToolSelector) -> SeedTool | None:
        return next(
            (
                tool
                for tool in self.tools
                if (tool.server, tool.name) == (selector.server, selector.name)
            ),
            None,
        )

    def selector_of_ref(self, ref: object) -> ToolSelector | None:
        return next(
            (
                ToolSelector(server=tool.server, name=tool.name)
                for tool in self.tools
                if tool.ref == ref
            ),
            None,
        )

    def selector_of(self, server_id: UUID, tool_id: UUID) -> ToolSelector | None:
        names = {server.server_id: server.name for server in self.servers}
        server = names.get(server_id)
        return next(
            (
                ToolSelector(server=tool.server, name=tool.name)
                for tool in self.tools
                if tool.server == server and tool.tool_id == tool_id
            ),
            None,
        )


def load_seed_manifest(path: Path, *, space_id: str) -> SeedManifest:
    """The manifest at `path`, refused unless it seeded the run's space."""

    manifest = SeedManifest.model_validate_json(path.read_bytes())
    if manifest.space_id != UUID(space_id):
        raise ValueError(
            f"{path} seeded space {manifest.space_id}, not the run's {space_id}"
        )
    return manifest


# --- the case's expectation (`expected.expected_mcp`) ------------------------------


class AppliedPlanOutcome(BaseModel):
    model_config = _CLOSED

    kind: Literal["applied_plan"]


class GuidanceOutcome(BaseModel):
    """The Builder explains why a needed tool cannot be used (`tool_refusal`)."""

    model_config = _CLOSED

    kind: Literal["guidance"]
    refusal_kind: Literal["refused", "input_schema_invalid", "input_schema_too_large"]
    refusal: UnattendedToolRefusal | None

    @model_validator(mode="after")
    def _a_reason_exactly_for_a_refusal(self) -> GuidanceOutcome:
        if (self.refusal is None) == (self.refusal_kind == "refused"):
            raise ValueError("refusal names the reason exactly of a refused tool")
        return self


class AnswerOutcome(BaseModel):
    model_config = _CLOSED

    kind: Literal["answer"]
    non_plan_kind: NonPlanKind


class RunInputSource(BaseModel):
    """The run-form field an argument reads, by name; its type when declared."""

    model_config = _CLOSED

    field: _Name
    type: FlowFormFieldType | None = None


class RunInputBinding(BaseModel):
    model_config = _CLOSED

    run_input: RunInputSource


class FixedBinding(BaseModel):
    model_config = _CLOSED

    fixed: JsonValue


class ProducerTool(BaseModel):
    """The earlier step that reads this tool. A tool is the producer's
    identity where it has one: a step's position moves when the Builder adds
    a step before it, and its name is free text."""

    model_config = _CLOSED

    tool: ToolSelector


class ProducerOrder(BaseModel):
    """The earlier step at this position, for a producer that reads no tool."""

    model_config = _CLOSED

    order: Annotated[int, Field(ge=1)]


class EarlierSource(BaseModel):
    model_config = _CLOSED

    step: ProducerTool | ProducerOrder
    field: _Name


class EarlierBinding(BaseModel):
    model_config = _CLOSED

    earlier: EarlierSource


ArgumentBinding: TypeAlias = RunInputBinding | FixedBinding | EarlierBinding


class ExpectedUse(BaseModel):
    model_config = _CLOSED

    tool: ToolSelector
    arguments: dict[str, ArgumentBinding]


class ExpectedCall(BaseModel):
    model_config = _CLOSED

    tool: ToolSelector
    arguments: dict[str, JsonValue]


class McpExpectation(BaseModel):
    model_config = _CLOSED

    outcome: Annotated[
        AppliedPlanOutcome | GuidanceOutcome | AnswerOutcome,
        Field(discriminator="kind"),
    ]
    # Per user turn, the tool question families asked in it, in order; a turn
    # beyond the list expects none.
    turns: list[list[ToolQuestionFamily]]
    # Empty: no turn's final plan may read a tool.
    uses: list[ExpectedUse]
    calls: list[ExpectedCall] | None = None
    run_input: dict[str, JsonValue] | None = None
    # Checks of an edit, each reported only when declared, so the reports of
    # the cases that declare none keep their recorded shape. M7: the applied
    # flow's last step reads each tool step's output, directly or through the
    # steps between. M8: the applied flow still makes every read the saved
    # flow made, and each saved run-form field keeps its type, label,
    # requiredness and options.
    tool_output_reaches_last_step: StrictBool = False
    keeps_saved_flow: StrictBool = False

    @model_validator(mode="after")
    def _only_an_applied_plan_uses_tools(self) -> McpExpectation:
        if self.outcome.kind != "applied_plan" and (
            self.uses
            or self.calls
            or self.tool_output_reaches_last_step
            or self.keeps_saved_flow
        ):
            raise ValueError(
                "only an applied plan has tool uses, calls and edit checks"
            )
        return self


# --- scripted answers (top-level `tool_answers`) -------------------------------------


def _one_of(*allowed: str) -> Callable[[str], str]:
    def check(value: str) -> str:
        if value not in allowed:
            raise ValueError(f"must be one of {', '.join(allowed)}")
        return value

    return check


class RelevanceAnswer(BaseModel):
    model_config = _CLOSED

    family: Literal["relevance"]
    option: Annotated[
        str,
        AfterValidator(
            _one_of(RELEVANCE_USE, RELEVANCE_DONT_USE, RELEVANCE_SHOW_TOOLS)
        ),
    ]


class ToolChoiceAnswer(BaseModel):
    model_config = _CLOSED

    family: Literal["choice"]
    tool: ToolSelector


class NoToolChoiceAnswer(BaseModel):
    model_config = _CLOSED

    family: Literal["choice"]
    option: Annotated[str, AfterValidator(_one_of(NO_TOOL))]


class FixedArgumentAnswer(BaseModel):
    model_config = _CLOSED

    family: Literal["argument"]
    argument: _Name
    source: Literal["fixed"]
    value: JsonValue


class RunInputArgumentAnswer(BaseModel):
    """Read from the run-form field `field`: the product offers every field
    that fits, so the case names the one it means."""

    model_config = _CLOSED

    family: Literal["argument"]
    argument: _Name
    source: Literal["run_input"]
    field: _Name


class EarlierArgumentAnswer(BaseModel):
    """Read from `field` of the earlier step `step`. The question shows each
    producer by position only, so a producer named by its tool answers only
    when one offered step has the field; a position names it outright."""

    model_config = _CLOSED

    family: Literal["argument"]
    argument: _Name
    source: Literal["earlier"]
    step: ProducerTool | ProducerOrder
    field: _Name


ToolAnswerRule: TypeAlias = (
    RelevanceAnswer
    | ToolChoiceAnswer
    | NoToolChoiceAnswer
    | FixedArgumentAnswer
    | RunInputArgumentAnswer
    | EarlierArgumentAnswer
)
TOOL_ANSWER_RULES = TypeAdapter[list[ToolAnswerRule]](list[ToolAnswerRule])


def case_tool_selectors(
    expectation: McpExpectation | None, rules: Sequence[ToolAnswerRule]
) -> list[ToolSelector]:
    """Every tool a case names, the one list the seed check reads: the tools
    its answer rules choose or name as producer, and its expected uses, their
    bindings' producers and its run-probe calls."""

    named = [rule.tool for rule in rules if isinstance(rule, ToolChoiceAnswer)]
    named += [
        rule.step.tool
        for rule in rules
        if isinstance(rule, EarlierArgumentAnswer)
        and isinstance(rule.step, ProducerTool)
    ]
    if expectation is None:
        return named
    for use in expectation.uses:
        named.append(use.tool)
        named += [
            binding.earlier.step.tool
            for binding in use.arguments.values()
            if isinstance(binding, EarlierBinding)
            and isinstance(binding.earlier.step, ProducerTool)
        ]
    return [*named, *(call.tool for call in expectation.calls or ())]


def scripted_tool_answer(
    question: Mapping[str, object],
    rules: Sequence[ToolAnswerRule],
    manifest: SeedManifest | None,
) -> JsonObject | None:
    """The case's answer to a question about the space's tools, or None.

    The first rule whose family (and argument) the question's typed facts
    name and one of whose options the question offers answers it. A choice
    that offers the tools of two rules is about a use the case cannot tell
    apart, so no tool rule answers it: rule order never picks the tool.
    """

    if question.get("tool_question") is None:
        return None
    try:
        shown = StructuredQuestionPayload.model_validate(question)
    except ValidationError:
        return None
    facts = shown.tool_question
    assert facts is not None
    named = {
        seeded.ref
        for rule in rules
        if isinstance(rule, ToolChoiceAnswer)
        and manifest is not None
        and (seeded := manifest.tool(rule.tool)) is not None
    }
    if len(named & {option.value for option in shown.options}) > 1:
        rules = [rule for rule in rules if not isinstance(rule, ToolChoiceAnswer)]
    return next(
        (
            answer
            for rule in rules
            if (answer := _rule_answer(rule, shown, facts, manifest)) is not None
        ),
        None,
    )


def _rule_answer(
    rule: ToolAnswerRule,
    shown: StructuredQuestionPayload,
    facts: AIBuilderToolQuestion,
    manifest: SeedManifest | None,
) -> JsonObject | None:
    if rule.family != facts.family:
        return None
    if isinstance(rule, RelevanceAnswer | NoToolChoiceAnswer):
        return _selected(shown, _offered(shown, rule.option))
    if isinstance(rule, ToolChoiceAnswer):
        seeded = manifest.tool(rule.tool) if manifest is not None else None
        return _selected(shown, _offered(shown, seeded.ref) if seeded else None)
    if rule.argument != facts.argument_name:
        return None
    if isinstance(rule, FixedArgumentAnswer):
        fixed_id = facts.fixed_value_option_id
        if fixed_id is None:
            # An argument with allowed values offers each as an option.
            return _selected(shown, _offered(shown, rule.value))
        # The product reads the typed text as the value itself for a text,
        # date or select argument, and as JSON otherwise.
        text = rule.value if isinstance(rule.value, str) else json.dumps(rule.value)
        fixed = next(option for option in shown.options if option.id == fixed_id)
        return _selected(shown, fixed, custom_value=text)
    if isinstance(rule, RunInputArgumentAnswer):
        return _selected(
            shown,
            next((o for o in shown.options if _run_input_field(o) == rule.field), None),
        )
    producers = [
        (order, option)
        for option in shown.options
        if (earlier := _earlier_field(option)) is not None and earlier[1] == rule.field
        for order in [earlier[0]]
    ]
    if isinstance(rule.step, ProducerOrder):
        producers = [(order, o) for order, o in producers if order == rule.step.order]
    return _selected(shown, producers[0][1] if len(producers) == 1 else None)


def _same_json(left: object, right: object) -> bool:
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def _offered(
    shown: StructuredQuestionPayload, value: object
) -> StructuredQuestionOptionPayload | None:
    matches = [option for option in shown.options if _same_json(option.value, value)]
    return matches[0] if len(matches) == 1 else None


# The option ids the product writes for an argument read from a run-form
# field (`run_input:<field>`) and from an earlier step's field
# (`earlier_step:<step>:<field>`), with the option's value naming the field:
# no typed source is carried per option, so the two spellings are read here.
def _run_input_field(option: StructuredQuestionOptionPayload) -> str | None:
    value = option.value
    return (
        value if isinstance(value, str) and option.id == f"run_input:{value}" else None
    )


def _earlier_field(option: StructuredQuestionOptionPayload) -> tuple[int, str] | None:
    """The producer position and field an earlier-step option offers."""

    value = option.value
    if not isinstance(value, str) or option.id != f"earlier_step:{value}":
        return None
    step, _, name = value.partition(":")
    return (int(step), name) if step.isdecimal() and name else None


def _selected(
    shown: StructuredQuestionPayload,
    option: StructuredQuestionOptionPayload | None,
    *,
    custom_value: str | None = None,
) -> JsonObject | None:
    if option is None or not option.id:
        return None
    return {
        "message": custom_value if custom_value is not None else option.label,
        "answer_source": TOOL_ANSWER_SOURCE,
        "question_answer": {
            "kind": "structured_question_answer",
            "question_id": shown.question_id,
            **(
                {"instance_token": str(shown.instance_token)}
                if shown.instance_token is not None
                else {}
            ),
            "selected_option_ids": [option.id],
            **({"selected_values": [option.value]} if option.value is not None else {}),
            **({"custom_value": custom_value} if custom_value is not None else {}),
        },
    }


# --- the test server's call log ------------------------------------------------------


class _LoggedCall(BaseModel):
    model_config = _CLOSED

    ts: AwareDatetime
    block: _Name
    server: _Name
    tool: _Name
    arguments: dict[str, JsonValue]


_INSTANT = TypeAdapter[datetime](AwareDatetime)
_LOGGED_CALLS = TypeAdapter[list[_LoggedCall]](list[_LoggedCall])


def parse_instant(value: str) -> datetime:
    return _INSTANT.validate_python(value)


def observation_calls(
    manifest: SeedManifest, *, started: datetime, ended: datetime
) -> list[JsonObject] | None:
    """The block's logged calls within [started, ended], each line as logged.

    None when the log cannot be read whole: a missing or broken log is never
    read as no calls.
    """

    try:
        lines = Path(manifest.call_log).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    calls: list[JsonObject] = []
    for line in filter(str.strip, lines):
        try:
            call = _LoggedCall.model_validate_json(line)
        except ValidationError:
            return None
        if call.block == manifest.block and started <= call.ts <= ended:
            calls.append(json.loads(line))
    return calls


# --- the checks ------------------------------------------------------------------------


def mcp_checks(
    expectation: McpExpectation,
    *,
    interactions: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any] | None,
    applied: bool,
    evidence: Mapping[str, Any] | None,
    declared_turns: int = 1,
    edit_evidence: Mapping[str, Any] | None = None,
) -> list[JsonObject]:
    """M1-M8 of one observation, each `{name, passed, applicable, actual,
    expected}`; `passed` None is unmeasured. An inapplicable check is
    reported with `applicable` false and judges nothing; M7 and M8 are
    reported only when the expectation declares them."""

    manifest, calls, probe_at = _evidence(evidence)
    turns = _turns(interactions)
    asked = [_tool_questions(turn) for turn in turns]
    readable = [turn for turn in asked if turn is not None]
    families = [[facts.family for facts, _ in turn] for turn in readable]
    expected_turns = [list(turn) for turn in expectation.turns]
    width = max(len(families), len(expected_turns))
    choices = [
        data for turn in readable for facts, data in turn if facts.family == "choice"
    ]
    picks = [data.get("recommended_option_id") for data in choices]
    # The arguments the person was asked about: the model's draft left them
    # open (or its value no longer fit), so their final binding is the answer.
    asked_arguments = {
        facts.argument_name
        for turn in readable
        for facts, _ in turn
        if facts.family == "argument" and facts.argument_name is not None
    }
    tool_steps = [len(_tool_steps(_turn_plan(turn))) for turn in turns]
    uses = [use.model_dump(mode="json") for use in expectation.uses]
    actual_uses = (
        [
            _plan_use(order, plan, manifest)
            for order, step in enumerate(_steps(plan), 1)
            if _reads_tool(step)
        ]
        if manifest is not None
        else None
    )
    # The product shows no draft while a tool question is open: the model's
    # own bindings are the final plan's with every asked argument left open,
    # and are not observable at all once a choice may have changed a use.
    draft_uses = (
        None
        if actual_uses is None or picks or len(readable) != len(asked)
        else [_left_open(use, asked_arguments) for use in actual_uses]
    )
    checks = [
        _check(
            "mcp_m1_questions",
            True,
            # A declared turn that never ran asked nothing, and was not passed.
            False
            if len(turns) < declared_turns
            else None
            if len(readable) != len(asked)
            else all(
                _padded(families, index) == _padded(expected_turns, index)
                for index in range(width)
            ),
            {"families": families, "turns_run": len(turns)},
            {"families": expected_turns, "turns_declared": declared_turns},
        ),
        _check(
            "mcp_m1_no_tools",
            not expectation.uses,
            not any(tool_steps),
            tool_steps,
            [0] * len(turns),
        ),
        _model_pick_check(expectation, choices, manifest),
        _check(
            "mcp_m2_model_bindings",
            bool(expectation.uses),
            None if draft_uses is None else _uses_hold(expectation.uses, draft_uses),
            draft_uses,
            uses,
        ),
        _check(
            "mcp_m3_bindings",
            bool(expectation.uses),
            None if actual_uses is None else _uses_hold(expectation.uses, actual_uses),
            actual_uses,
            uses,
        ),
        _outcome_check(
            expectation, interactions=interactions, plan=plan, applied=applied
        ),
        _calls_check(expectation, calls=calls, probe_at=probe_at),
        _check("mcp_m6_cost", True, None, _cost(interactions, asked), None),
    ]
    views = _edit_views(edit_evidence)
    if expectation.tool_output_reaches_last_step:
        checks.append(_reach_check(views))
    if expectation.keeps_saved_flow:
        checks.append(_kept_check(views))
    return checks


def _check(
    name: str, applicable: bool, passed: bool | None, actual: object, expected: object
) -> JsonObject:
    return {
        "name": name,
        "passed": passed if applicable else None,
        "applicable": applicable,
        "gating": name in (*PLAN_CHECK_NAMES, *OUTPUT_CHECK_NAMES),
        "actual": actual,
        "expected": expected,
    }


def _model_pick_check(
    expectation: McpExpectation,
    choices: Sequence[Mapping[str, Any]],
    manifest: SeedManifest | None,
) -> JsonObject:
    """Per choice question, the model's recommendation against the tool of
    the use it was asked for: the one expected tool among its offered
    options. A question that offers none or several of them cannot be paired
    with a use, so the check is unmeasured rather than read by membership."""

    expected_refs = (
        {seeded.ref for use in expectation.uses if (seeded := manifest.tool(use.tool))}
        if manifest is not None
        else set[str]()
    )
    rows: list[JsonObject] = []
    for data in choices:
        offered = {
            option.get("value") for option in _mappings(data.get("options"))
        } & expected_refs
        intended = next(iter(offered)) if len(offered) == 1 else None
        recommended = data.get("recommended_option_id")
        rows.append(
            {
                "recommended": _ref_selector(manifest, recommended),
                "intended": _ref_selector(manifest, intended) if intended else None,
                "passed": None if intended is None else recommended == intended,
            }
        )
    verdicts = [row["passed"] for row in rows]
    return _check(
        "mcp_m2_model_pick",
        bool(expectation.uses) and bool(choices),
        None
        if manifest is None
        else False
        if False in verdicts
        else None
        if None in verdicts
        else True,
        rows,
        [use.tool.model_dump(mode="json") for use in expectation.uses],
    )


def _ref_selector(manifest: SeedManifest | None, ref: object) -> object:
    selector = manifest.selector_of_ref(ref) if manifest is not None else None
    return selector.model_dump(mode="json") if selector is not None else ref


def _left_open(use: JsonObject, asked: set[str]) -> JsonObject:
    arguments = _mapping(use.get("arguments"))
    if arguments is None:
        return use
    return {
        **use,
        "arguments": {
            name: {"ask_user": {}} if name in asked else binding
            for name, binding in arguments.items()
        },
    }


def _uses_hold(
    expected: Sequence[ExpectedUse], actual: Sequence[JsonObject]
) -> bool | None:
    """Each expected use is one actual use, order aside: the same tool, the
    same arguments, each binding as the expectation names it. A maximum
    bipartite matching over the uses, so its cost is polynomial in their
    number (the product allows 20). None when only a binding that cannot be
    decided (a producer tool read by two steps) would complete it."""

    if len(expected) != len(actual):
        return False
    held = [[_use_holds(want, got) for got in actual] for want in expected]
    if _perfect_matching(held, accept=(True,)):
        return True
    return None if _perfect_matching(held, accept=(True, None)) else False


def _perfect_matching(
    held: Sequence[Sequence[bool | None]], *, accept: tuple[bool | None, ...]
) -> bool:
    """Whether every row matches its own column over the accepted edges
    (augmenting paths, Kuhn's algorithm)."""

    owner: dict[int, int] = {}

    def augment(row: int, seen: set[int]) -> bool:
        for column, edge in enumerate(held[row]):
            if edge not in accept or column in seen:
                continue
            seen.add(column)
            if column not in owner or augment(owner[column], seen):
                owner[column] = row
                return True
        return False

    return all(augment(row, set()) for row in range(len(held)))


def _use_holds(expected: ExpectedUse, actual: JsonObject) -> bool | None:
    arguments = _mapping(actual.get("arguments"))
    if (
        actual.get("tool") != expected.tool.model_dump(mode="json")
        or arguments is None
        or set(arguments) != set(expected.arguments)
    ):
        return False
    verdicts = [
        _binding_holds(want, got) if (got := _mapping(arguments[name])) else False
        for name, want in expected.arguments.items()
    ]
    return False if False in verdicts else None if None in verdicts else True


def _binding_holds(expected: ArgumentBinding, actual: Mapping[str, Any]) -> bool | None:
    if isinstance(expected, FixedBinding):
        return "fixed" in actual and _same_json(actual["fixed"], expected.fixed)
    if isinstance(expected, RunInputBinding):
        field = _mapping(actual.get("run_input"))
        wanted = expected.run_input
        return (
            field is not None
            and field.get("field") == wanted.field
            and (wanted.type is None or field.get("type") == wanted.type.value)
        )
    earlier = _mapping(actual.get("earlier"))
    producer = _mapping(earlier.get("step")) if earlier is not None else None
    wanted_step = expected.earlier.step
    if (
        earlier is None
        or producer is None
        or earlier.get("field") != expected.earlier.field
    ):
        return False
    if isinstance(wanted_step, ProducerOrder):
        return producer.get("order") == wanted_step.order
    if producer.get("tool") != wanted_step.tool.model_dump(mode="json"):
        return False
    # A tool that two steps read does not name one producer: the case must
    # name it by position, and until then the binding is undecided.
    return True if producer.get("tool_steps") == 1 else None


def _edit_views(
    evidence: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    """The saved and the applied flow as the edit comparator reads them
    (`snapshot_view`: steps by their seeded identity); None when the bundle
    keeps no applied flow (an apply refused or never made)."""

    if evidence is None:
        return None
    identity = _mapping(evidence.get("identity"))
    baseline = _snapshot(evidence.get("baseline"))
    applied = _snapshot(evidence.get("applied"))
    if identity is None or baseline is None or applied is None:
        return None
    return snapshot_view(baseline, identity), snapshot_view(applied, identity)


def _snapshot(value: object) -> Mapping[str, Any] | None:
    snapshot = _mapping(value)
    if snapshot is None or any(
        _mapping(snapshot.get(key)) is None for key in ("flow", "assistants")
    ):
        return None
    return snapshot


def _reach_check(
    views: tuple[Mapping[str, Any], Mapping[str, Any]] | None,
) -> JsonObject:
    """M7 over the reads the edit comparator finds (`flow_edges`): from each
    tool step, read by read, to the applied flow's last step. A read through
    another tool step's arguments is no edge there, so a chain of tool steps
    needs that reader extended before a case declares it."""

    name = "mcp_m7_tool_output_reaches_last_step"
    if views is None:
        return _check(name, True, None, None, None)
    steps = _mappings(views[1].get("steps"))
    readers: dict[str, set[str]] = {}
    for edge in flow_edges(views[1])[0]:
        producer, consumer = edge_steps(edge)
        if producer is not None and consumer is not None:
            readers.setdefault(producer, set()).add(consumer)
    last = steps[-1].get("slot") if steps else None
    tools = [str(step.get("slot")) for step in steps if _reads_tool(step)]
    unread = [slot for slot in tools if last not in _reached(slot, readers)]
    return _check(
        name,
        True,
        bool(tools) and not unread,
        {"tool_steps": tools, "unread_by_last_step": unread},
        {"last_step": last},
    )


def _reached(start: str, readers: Mapping[str, set[str]]) -> set[str]:
    reached, frontier = {start}, [start]
    while frontier:
        for consumer in readers.get(frontier.pop(), set()) - reached:
            reached.add(consumer)
            frontier.append(consumer)
    return reached


def _kept_check(
    views: tuple[Mapping[str, Any], Mapping[str, Any]] | None,
) -> JsonObject:
    """M8: no read of the saved flow is gone (the comparator's dropped-read
    atoms), and each saved run-form field keeps its authoring contract; a
    field's order is not part of it, so adding one first changes none."""

    name = "mcp_m8_saved_flow_kept"
    if views is None:
        return _check(name, True, None, None, None)
    baseline, applied = views
    dropped = sorted(
        atom[1] for atom in observed_atoms(baseline, applied) if atom[0] == "edge-"
    )
    saved = _mapping(baseline.get("form_fields")) or {}
    final = _mapping(applied.get("form_fields")) or {}
    contracts = {field: _form_contract(raw) for field, raw in saved.items()}
    changed = sorted(
        field
        for field, contract in contracts.items()
        if contract != _form_contract(final.get(field))
    )
    return _check(
        name,
        True,
        None if None in contracts.values() else not dropped and not changed,
        {"dropped_reads": dropped, "changed_form_fields": changed},
        {"saved_form_fields": sorted(saved)},
    )


def _form_contract(raw: object) -> FormFieldSpec | None:
    """A saved run-form field as the authoring view reads it (the one owner of
    that reading); None when it is no field or its type is one the platform
    does not accept."""

    if not isinstance(raw, Mapping):
        return None
    try:
        return authoring_form_field(cast(Mapping[str, object], raw), index=0)
    except BadRequestException:
        return None


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def _padded(turns: Sequence[Sequence[str]], index: int) -> list[str]:
    return list(turns[index]) if index < len(turns) else []


def _evidence(
    evidence: Mapping[str, Any] | None,
) -> tuple[SeedManifest | None, list[_LoggedCall] | None, datetime | None]:
    """The bundle's manifest, calls and probe start; calls None when any of
    the three cannot be read, so they are never judged against a guess."""

    if evidence is None:
        return None, None, None
    try:
        manifest = SeedManifest.model_validate(evidence.get("manifest"))
    except ValidationError:
        return None, None, None
    raw_probe = evidence.get("run_probe_started_at")
    try:
        calls = _LOGGED_CALLS.validate_python(evidence.get("calls"))
        probe_at = None if raw_probe is None else _INSTANT.validate_python(raw_probe)
    except ValidationError:
        return manifest, None, None
    return manifest, calls, probe_at


def _turns(
    interactions: Sequence[Mapping[str, Any]],
) -> list[list[Mapping[str, Any]]]:
    turns: list[list[Mapping[str, Any]]] = [[]]
    for interaction in interactions:
        if interaction.get(SCRIPTED_TURN_KEY) is not None:
            turns.append([])
        turns[-1].append(interaction)
    return turns


def _mapping(value: object) -> Mapping[str, Any] | None:
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else None


def _mappings(value: object) -> list[Mapping[str, Any]]:
    items = cast(list[object], value) if isinstance(value, list) else []
    return [item for raw in items if (item := _mapping(raw)) is not None]


def _events(interaction: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return _mappings(interaction.get("events"))


def _tool_questions(
    turn: Sequence[Mapping[str, Any]],
) -> list[tuple[AIBuilderToolQuestion, Mapping[str, Any]]] | None:
    """The tool questions shown in a turn, in order; None when one of them
    carries facts that do not read."""

    shown: list[tuple[AIBuilderToolQuestion, Mapping[str, Any]]] = []
    for interaction in turn:
        for event in _events(interaction):
            data = _mapping(event.get("data"))
            if event.get("event") != "question" or data is None:
                continue
            facts = data.get("tool_question")
            if facts is None:
                continue
            try:
                shown.append((AIBuilderToolQuestion.model_validate(facts), data))
            except ValidationError:
                return None
    return shown


def _turn_plan(turn: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return _mapping(turn[-1].get("plan")) if turn else None


def _spec(plan: Mapping[str, Any] | None) -> Mapping[str, Any]:
    proposal = _mapping(plan.get("proposal")) if plan is not None else None
    return (_mapping(proposal.get("spec")) if proposal is not None else None) or {}


def _steps(plan: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    return _mappings(_spec(plan).get("steps"))


def _reads_tool(step: Mapping[str, Any]) -> bool:
    config = _mapping(step.get("input_config"))
    return config is not None and TOOL_INPUT_CONFIG_KEY in config


def _tool_steps(plan: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    return [step for step in _steps(plan) if _reads_tool(step)]


def _plan_use(
    consumer: int, plan: Mapping[str, Any] | None, manifest: SeedManifest
) -> JsonObject:
    """The tool step at position `consumer` as an expected use is written:
    the tool by name, and per argument its fixed value, run-form field or
    earlier field with its producer."""

    steps = _steps(plan)
    step = steps[consumer - 1]
    try:
        config = ToolInputConfig.model_validate(
            step["input_config"][TOOL_INPUT_CONFIG_KEY]
        )
        bound = {argument.name: argument for argument in config.bound_arguments()}
    except (ValidationError, ToolArgumentError) as error:
        return {"unreadable": str(error)}
    selector = manifest.selector_of(config.mcp_server_id, config.tool_id)
    step_orders = {
        str(item.get("plan_step_ref")): order for order, item in enumerate(steps, 1)
    }
    # The steps that can produce this step's earlier fields: those before it.
    producer_tools = {
        order: _step_tool(item, manifest)
        for order, item in enumerate(steps[: consumer - 1], 1)
    }
    form_types = {
        str(field.get("name")): _form_field_type(field.get("type"))
        for field in _mappings(_spec(plan).get("form_fields"))
    }
    return {
        "tool": selector.model_dump(mode="json")
        if selector is not None
        else {
            "mcp_server_id": str(config.mcp_server_id),
            "tool_id": str(config.tool_id),
        },
        "arguments": {
            name: (
                _reference_binding(bound[name], step_orders, producer_tools, form_types)
                if name in bound
                else {"fixed": value}
            )
            for name, value in config.arguments.items()
        },
    }


def _step_tool(step: Mapping[str, Any], manifest: SeedManifest) -> object:
    """The tool a step reads, by name, or None for a step that reads none."""

    config = _mapping(step.get("input_config"))
    if config is None or TOOL_INPUT_CONFIG_KEY not in config:
        return None
    try:
        tool = ToolInputConfig.model_validate(config[TOOL_INPUT_CONFIG_KEY])
    except ValidationError:
        return {"unreadable": True}
    selector = manifest.selector_of(tool.mcp_server_id, tool.tool_id)
    return (
        selector.model_dump(mode="json")
        if selector is not None
        else {"mcp_server_id": str(tool.mcp_server_id), "tool_id": str(tool.tool_id)}
    )


def _form_field_type(raw: object) -> str | None:
    try:
        return parse_flow_form_field_type(raw).value if isinstance(raw, str) else None
    except ValueError:
        return None


def _reference_binding(
    bound: BoundArgument,
    step_orders: dict[str, int],
    producer_tools: Mapping[int, object],
    form_types: Mapping[str, str | None],
) -> JsonObject:
    references = analyze_template(
        bound.template, step_refs=step_orders, form_field_names=set(form_types)
    )
    reference = references[0] if len(references) == 1 else None
    if reference is not None and reference.path_error_code is None:
        field = reference.form_field_name or (
            reference.head
            if reference.kind is TemplateReferenceKind.FORM_FIELD
            else None
        )
        if field is not None:
            return {"run_input": {"field": field, "type": form_types.get(field)}}
        order = reference.step_order
        if (
            reference.kind is TemplateReferenceKind.STEP
            and reference.structured_path
            and order is not None
        ):
            return {
                "earlier": {
                    "step": {
                        "order": order,
                        "tool": (tool := producer_tools.get(order)),
                        "tool_steps": list(producer_tools.values()).count(tool)
                        if tool is not None
                        else 0,
                    },
                    "field": ".".join(reference.structured_path),
                }
            }
    return {"unreadable": bound.expression}


def _tool_refusal(interaction: Mapping[str, Any]) -> AIBuilderToolRefusal | None:
    """The refusal the session's last assistant answer carries, if any."""

    session = _mapping(interaction.get("latest_session")) or {}
    answers = [
        message
        for message in _mappings(session.get("conversation"))
        if message.get("role") == "assistant"
    ]
    stored = answers[-1].get("tool_refusal") if answers else None
    try:
        return None if stored is None else AIBuilderToolRefusal.model_validate(stored)
    except ValidationError:
        return None


def _outcome_check(
    expectation: McpExpectation,
    *,
    interactions: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any] | None,
    applied: bool,
) -> JsonObject:
    outcome = expectation.outcome
    refusal = _tool_refusal(interactions[-1]) if interactions else None
    passed: bool | None
    if isinstance(outcome, AppliedPlanOutcome):
        passed = plan is not None and applied
    elif isinstance(outcome, GuidanceOutcome):
        passed = (
            plan is None
            and refusal is not None
            and (refusal.kind, refusal.refusal)
            == (outcome.refusal_kind, outcome.refusal)
        )
    else:
        # The API does not show which non-plan answer a turn gave: any plan or
        # tool refusal contradicts it, and nothing else can confirm it.
        passed = False if plan is not None or refusal is not None else None
    return _check(
        "mcp_m4_outcome",
        True,
        passed,
        {
            "plan": plan is not None,
            "applied": applied,
            "tool_refusal": refusal.model_dump(mode="json") if refusal else None,
        },
        outcome.model_dump(mode="json"),
    )


def _calls_check(
    expectation: McpExpectation,
    *,
    calls: list[_LoggedCall] | None,
    probe_at: datetime | None,
) -> JsonObject:
    """The run probe's calls equal the expected ones, as a multiset, and
    nothing called the server before the probe started (authoring)."""

    def key(server: str, tool: str, arguments: Mapping[str, object]) -> str:
        return _canonical([server, tool, arguments])

    expected = [
        key(call.tool.server, call.tool.name, call.arguments)
        for call in expectation.calls or ()
    ]
    if calls is None:
        return _check("mcp_m5_calls", True, None, None, expected)
    authoring = [
        key(c.server, c.tool, c.arguments)
        for c in calls
        if probe_at is None or c.ts < probe_at
    ]
    probe = [
        key(c.server, c.tool, c.arguments)
        for c in calls
        if probe_at is not None and c.ts >= probe_at
    ]
    return _check(
        "mcp_m5_calls",
        True,
        not authoring and Counter(probe) == Counter(expected),
        {"authoring": authoring, "probe": probe},
        expected,
    )


def _cost(
    interactions: Sequence[Mapping[str, Any]],
    asked: Sequence[Sequence[object] | None],
) -> JsonObject:
    session = (
        _mapping(interactions[-1].get("latest_session")) if interactions else None
    ) or {}
    telemetry = _mapping(session.get("telemetry")) or {}
    return {
        "total_tokens": telemetry.get("total_tokens_total"),
        "repair_attempts": telemetry.get("repair_attempts_total"),
        "wall_clock_ms": telemetry.get("wall_clock_ms_total"),
        "questions": sum(
            event.get("event") == "question"
            for interaction in interactions
            for event in _events(interaction)
        ),
        "tool_questions": sum(len(turn) for turn in asked if turn is not None),
    }
