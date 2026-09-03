"""What the Builder does with each requirement slot: ask, assume, or accept.

One table and one evaluator. Before this module the same decision was spread
over a question budget keyed on phrases in the brief, a one-question-per-family
gate, per-issue "assumption safe" predicates, per-issue heuristics, a separate
impact map, a separate priority map, and a separate default-value table. They
disagreed: a slot could be assumption-safe and impact-architecture at once, and
which of the two won depended on the order the branches happened to run in.

`evaluate_slot_interaction` is the only place that decides. The table says what
a slot costs to get wrong (`impact`), what to do when it is unknown
(`when_unknown`), what to fall back to (`default_value`), and where it belongs
in the order questions are asked (`order`). Nothing else about a slot's
interaction lives anywhere else.

The evaluator decides; it does not write. `planning_state_builder` remains the
only writer of policy defaults into `PlanningState`, so the live fold and a
replay of the same conversation reach the same slots.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from eneo.flows.ai_builder.ai_builder_aggregation_intent import (
    comparison_scope_is_relevant,
    report_disposition_is_relevant_for_state,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    architecture_required_slot_names,
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_commit_invariance import (
    architecture_commit_draft_matches_pinned,
)
from eneo.flows.ai_builder.ai_builder_discovery_signal_inference import (
    mentions_comparison_request,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    has_explicit_docx_mode_text,
    has_explicit_pdf_mode_text,
    mentions_runtime_metadata,
)
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import (
    LLM_RESOLVABLE_SLOT_NAMES,
)
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.flows.enums import FlowAuthoringInputType

SlotImpact = Literal["architecture", "quality"]
SlotWhenUnknown = Literal["ask", "assume"]
SlotInteraction = Literal["not_relevant", "commit", "accept", "ask", "assume", "open"]


def _never_explicit_text(_: str) -> bool:
    return False


@dataclass(frozen=True, slots=True)
class SlotInteractionPolicy:
    """How one requirement slot is obtained, and what it costs to be wrong.

    `impact` is the slot's static cost. It can be overridden upward for a
    single state — a report disposition is a style choice for one document and
    a topology choice for several — which is why `effective_slot_impact` reads
    the architecture derivation instead of this field alone.

    `default_value` is the value assumed when the slot is unknown and
    `when_unknown` is "assume". It is also the recommended answer offered
    alongside an ask, so the user is never shown a default the server would not
    have taken itself. `has_explicit_text` guards a default that the user's own
    words can contradict.
    """

    slot_name: str
    impact: SlotImpact
    when_unknown: SlotWhenUnknown
    order: int
    default_value: str | None = None
    has_explicit_text: Callable[[str], bool] = _never_explicit_text
    # Whether a confident text rule may settle the slot. A phrase match is
    # enough for what material comes in or goes out; it is not enough to
    # refuse a template PDF on the user's behalf. That is settled only by the
    # user or by cited classifier evidence.
    settled_by_text_rules: bool = True

    def __post_init__(self) -> None:
        if self.when_unknown == "assume" and self.default_value is None:
            raise ValueError(
                f"slot policy {self.slot_name!r} assumes without a default value"
            )


_POLICIES: tuple[SlotInteractionPolicy, ...] = (
    SlotInteractionPolicy(
        slot_name="primary_runtime_input",
        impact="architecture",
        when_unknown="ask",
        order=10,
    ),
    SlotInteractionPolicy(
        slot_name="terminal_output",
        impact="architecture",
        when_unknown="ask",
        order=20,
    ),
    SlotInteractionPolicy(
        slot_name="structured_io_contract",
        impact="architecture",
        when_unknown="ask",
        order=30,
    ),
    # Committed only through the option/custom-answer lane, never by the model.
    SlotInteractionPolicy(
        slot_name="mapped_file_limit",
        impact="architecture",
        when_unknown="ask",
        order=40,
    ),
    # A brief that says nothing about comparing gets no comparison; one that
    # asks for it, in words or through its goal, is asked how (see the goal
    # rule in the evaluator).
    SlotInteractionPolicy(
        slot_name="comparison_scope",
        impact="architecture",
        when_unknown="assume",
        order=50,
        default_value="no_direct_compare",
        has_explicit_text=mentions_comparison_request,
    ),
    SlotInteractionPolicy(
        slot_name="document_material_scope",
        impact="quality",
        when_unknown="assume",
        order=60,
        default_value="flexible_document_case",
    ),
    # Quality for one document, architecture for several: the derivation says
    # which, so the impact override rather than the table decides per state.
    SlotInteractionPolicy(
        slot_name="report_disposition",
        impact="quality",
        when_unknown="ask",
        order=70,
    ),
    # Asked before the input and output questions whose answers depend on it.
    SlotInteractionPolicy(
        slot_name="post_processing_goal",
        impact="quality",
        when_unknown="ask",
        order=5,
    ),
    # Right behind the output it refines: a template DOCX needs its attachment
    # before anything else is worth asking.
    SlotInteractionPolicy(
        slot_name="docx_output_mode",
        impact="architecture",
        when_unknown="assume",
        order=25,
        default_value="generated_docx",
        has_explicit_text=has_explicit_docx_mode_text,
    ),
    # A template PDF is not built at all, so the refusal comes before any other
    # question is spent.
    SlotInteractionPolicy(
        slot_name="pdf_generation_mode",
        impact="architecture",
        when_unknown="assume",
        order=6,
        default_value="generated_pdf",
        has_explicit_text=has_explicit_pdf_mode_text,
        settled_by_text_rules=False,
    ),
    SlotInteractionPolicy(
        slot_name="runtime_metadata_fields",
        impact="quality",
        when_unknown="assume",
        order=100,
        default_value="no_extra_metadata",
        has_explicit_text=mentions_runtime_metadata,
    ),
)

SLOT_INTERACTION_POLICIES: Mapping[str, SlotInteractionPolicy] = MappingProxyType(
    {policy.slot_name: policy for policy in _POLICIES}
)

# Slots the model may resolve, plus the three the server resolves for itself.
# A slot the Builder can hold a requirement for and cannot decide about is a
# gap in this table, not a slot with no policy, so the set is pinned.
POLICY_COVERED_SLOT_NAMES: frozenset[str] = LLM_RESOLVABLE_SLOT_NAMES | {
    "docx_output_mode",
    "pdf_generation_mode",
    "mapped_file_limit",
}


def slot_is_relevant(
    *,
    slot_name: str,
    state: PlanningState,
    unresolved_values_are_relevant: bool = True,
    require_commit_grade_primary_input: bool = False,
) -> bool:
    """Whether this slot is a question at all for the shape being built.

    Read before anything else: an irrelevant slot is neither asked nor assumed,
    and a value already resolved for it is dropped rather than carried into an
    architecture that has no place for it.

    `unresolved_values_are_relevant` is what an unresolved neighbour means. For
    asking it is True: a shape that is not decided yet cannot rule a slot out,
    and the question order settles the neighbour first. For assuming it is
    False: a default is written the moment it is taken, so a dependent slot is
    assumed only once the slot it depends on is known.
    `require_commit_grade_primary_input` reads the primary input as unresolved
    while it is below commit grade, for callers that must not build on it.
    """

    if slot_name == "mapped_file_limit":
        return _mapped_file_limit_is_relevant(state)

    primary = state.resolved_slots.get("primary_runtime_input")
    terminal = state.resolved_slots.get("terminal_output")
    primary_value = None
    if primary is not None and (
        not require_commit_grade_primary_input or primary.is_commit_grade
    ):
        primary_value = primary.value
    terminal_value = terminal.value if terminal is not None else None

    if slot_name in {"comparison_scope", "document_material_scope"}:
        return comparison_scope_is_relevant(
            primary_runtime_input=primary_value,
            unresolved_values_are_relevant=unresolved_values_are_relevant,
        )
    if slot_name == "report_disposition":
        return report_disposition_is_relevant_for_state(
            state,
            unresolved_values_are_relevant=unresolved_values_are_relevant,
        )
    if slot_name == "docx_output_mode":
        if terminal_value is None:
            return unresolved_values_are_relevant
        return terminal_value == "docx_document"
    if slot_name == "pdf_generation_mode":
        if terminal_value is None:
            return unresolved_values_are_relevant
        return terminal_value == "pdf_document"
    if slot_name == "runtime_metadata_fields":
        return primary_value is not None or unresolved_values_are_relevant
    if slot_name == "post_processing_goal":
        # JSON in, JSON out is a transform with its contract as the purpose.
        if primary_value == "json" and terminal_value == "structured_json":
            return False
        # A template PDF the user has not confirmed is refused, not built; the
        # purpose question waits for that answer.
        pdf_mode = state.resolved_slots.get("pdf_generation_mode")
        return not (
            pdf_mode is not None
            and pdf_mode.value == "pdf_template_requested"
            and not pdf_mode.is_commit_grade
        )
    if slot_name != "structured_io_contract":
        return True
    input_fits = (
        primary_value == "json"
        if primary_value is not None
        else unresolved_values_are_relevant
    )
    output_fits = (
        terminal_value == "structured_json"
        if terminal_value is not None
        else unresolved_values_are_relevant
    )
    return input_fits and output_fits


def _mapped_file_limit_is_relevant(state: PlanningState) -> bool:
    """The ceiling is only a question once the shape that consumes it is fixed.

    It is not a slot the model resolves and not a value the conversation can
    imply: it is confirmed against the organization's policy, so it becomes a
    question only when the architecture is settled and reads files.
    """

    draft = derive_architecture_commit_draft(state)
    if draft is None or not architecture_commit_draft_matches_pinned(
        before=state.architecture_commit,
        after=draft,
    ):
        return False
    return draft.tuples_chain[0].input_type in {
        FlowAuthoringInputType.DOCUMENT,
        FlowAuthoringInputType.FILE,
    }


def _evaluate_mapped_file_limit(state: PlanningState) -> SlotInteraction:
    """The ceiling lives in its own typed field, not in `resolved_slots`.

    Acceptance is the whole point of the question — a proposed organization
    limit is not an answer until the user has confirmed or lowered it — so
    acceptance, not evidence strength, is what makes it commit grade.
    """

    limit = state.mapped_file_limit
    if limit.accepted_value is not None:
        return "commit"
    if limit.proposed_value is None:
        return "not_relevant"
    return "ask"


def effective_slot_impact(
    policy: SlotInteractionPolicy,
    state: PlanningState,
) -> SlotImpact:
    """The slot's cost of being wrong for this state, not in general.

    The create derivation is the authority on which slots the architecture
    cannot be committed without. A slot it needs is architectural here even
    when the table calls it quality, so the two can never disagree about
    whether a missing answer blocks the build.
    """

    if policy.slot_name in architecture_required_slot_names(state):
        return "architecture"
    return policy.impact


def evaluate_slot_interaction(
    policy: SlotInteractionPolicy,
    state: PlanningState,
    *,
    freeform_text: str = "",
) -> SlotInteraction:
    """The single decision about one slot for one turn.

    - `not_relevant`: the shape has no place for it, or the slots it depends
      on are not known yet. A dependent slot is decided the turn its
      prerequisite is, never before: nothing is asked or assumed about a
      report's disposition while the input is still open.
    - `commit`: resolved with evidence strong enough to build on.
    - `accept`: resolved below commit grade and kept as an assumption row the
      user can reopen: a default the policy itself took, confident evidence
      from the model or a text rule, or weaker evidence for a slot the table
      would have assumed anyway.
    - `ask`: the user has to decide. The model said it did not know; the answer
      is missing and the table says to ask; or the only evidence is weak and
      the slot is worth a question (architecture impact, or a quality slot the
      table asks about).
    - `assume`: the default is taken, silently, as a reopenable row.
    - `open`: the table would assume, but the user's own words speak to the
      slot without settling it; no default, no question this turn.

    `freeform_text` is the user's own wording, read only through the policy's
    explicit-text guard.
    """

    if not slot_is_relevant(
        slot_name=policy.slot_name,
        state=state,
        unresolved_values_are_relevant=False,
    ):
        return "not_relevant"
    if policy.slot_name == "mapped_file_limit":
        return _evaluate_mapped_file_limit(state)
    resolved = state.resolved_slots.get(policy.slot_name)
    if (
        policy.slot_name == "docx_output_mode"
        and _template_attached(state)
        and (resolved is None or resolved.source == "policy_default")
    ):
        # An attached template is the user's own evidence for the mode; the
        # attachment reader settles it when it can read the file, and until
        # then a generated default would contradict what they uploaded.
        return "ask"
    if resolved is not None:
        if resolved.is_commit_grade:
            return "commit"
        if resolved.source == "policy_default":
            return "accept"
        if resolved.confidence == "high" and (
            resolved.source != "heuristic" or policy.settled_by_text_rules
        ):
            return "accept"
        worth_a_question = (
            effective_slot_impact(policy, state) == "architecture"
            or policy.when_unknown == "ask"
        )
        return "ask" if worth_a_question else "accept"
    if policy.slot_name in state.slot_uncertainties:
        return "ask"
    if policy.when_unknown == "ask":
        return "ask"
    if policy.slot_name == "comparison_scope" and (
        policy.has_explicit_text(freeform_text) or _comparison_is_the_goal(state)
    ):
        # A brief that speaks of comparing, in words or through its goal, is
        # asked how; only silence about it takes the no-comparison default.
        return "ask"
    if policy.has_explicit_text(freeform_text):
        # The user's own words speak to the slot, so no default is taken, and
        # the words alone did not settle it: a later reader (an attachment,
        # the classifier) will.
        return "open"
    return "assume"


def _comparison_is_the_goal(state: PlanningState) -> bool:
    goal = state.resolved_slots.get("post_processing_goal")
    return goal is not None and goal.value == "compare_or_validate"


def _template_attached(state: PlanningState) -> bool:
    return any(role.role == "template" for role in state.file_roles)


def slots_to_ask(state: PlanningState, *, freeform_text: str = "") -> tuple[str, ...]:
    """Every slot this state needs the user to decide, in the order to ask."""

    return tuple(
        policy.slot_name
        for policy in sorted(_POLICIES, key=lambda item: item.order)
        if evaluate_slot_interaction(policy, state, freeform_text=freeform_text)
        == "ask"
    )


def slot_interaction_order(slot_name: str) -> int:
    """Where a slot's question belongs, for callers ordering a mixed list.

    Anything without a policy sorts after every slot: non-slot gates carry
    their own explicit order and are placed by their owner.
    """

    policy = SLOT_INTERACTION_POLICIES.get(slot_name)
    return policy.order if policy is not None else 999


__all__ = [
    "POLICY_COVERED_SLOT_NAMES",
    "SLOT_INTERACTION_POLICIES",
    "SlotImpact",
    "SlotInteraction",
    "SlotInteractionPolicy",
    "SlotWhenUnknown",
    "effective_slot_impact",
    "evaluate_slot_interaction",
    "slot_interaction_order",
    "slot_is_relevant",
    "slots_to_ask",
]
