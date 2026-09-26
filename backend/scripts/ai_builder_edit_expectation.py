"""Typed edit gold and the one comparator of a Builder edit (eneo-e7h6).

Pure: no I/O. It judges what the harness read through the public API — the
seeded baseline, the flow after the last turn, the server's edit diff, the
apply record, the applied flow and the run — against a closed per-case gold.

Every difference is one typed atom: a step field, a flow field, a form field,
an added or dropped read (edge), an added or removed step. The applied flow
against the baseline gives the observed atoms, the server's diff the shown
atoms, the gold the required and permitted ones; three set comparisons then
decide scope, fulfilment and diff honesty. Steps are compared by seeded
identity (the assistant id, the only identity an apply keeps) and references
are read and canonicalized with the product's own owners, never re-parsed.

The verdict is STRUCTURAL: scope, order, dependencies, stated postconditions
and literal run facts. Tone and plain language are human judgements and stay
unmeasured here.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Any, Final, Literal, Self, cast, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from eneo.flows.ai_builder.ai_builder_domain_models import FlowBuilderEditApproval
from eneo.flows.ai_builder.ai_builder_edit_preview_models import StepChangeField
from eneo.flows.ai_builder.ai_builder_new_step_compiler import make_plan_step_ref
from eneo.flows.ai_builder.ai_builder_non_plan_outcome import (
    DeclineReason,
    decline_message,
)
from eneo.flows.domain.step_output import OUTPUT_TEXT_OVERFLOW_KEY
from eneo.flows.flow_authoring_variable_rewriting import (
    rewrite_source_ref_step_refs,
    rewrite_variable_value,
)
from eneo.flows.input_binding_contract_rules import effective_question_binding
from eneo.flows.step_lineage import (
    existing_step_order_from_ref,
    existing_step_ref_for_order,
    resolve_upstream_step_orders,
)
from eneo.flows.template_reference_analyzer import (
    TemplateReferenceKind,
    analyze_template,
)

JsonObject = dict[str, Any]
Atom = tuple[str, ...]
Category = Literal[
    "fulfilment",
    "questions",
    "pre_approval_write",
    "diff_integrity",
    "apply_refused",
    "order",
    "unauthorized_mutation",
    "dependency_loss",
    "dangling_reference",
    "execution",
]
ZERO_CATEGORIES: Final[tuple[Category, ...]] = (
    "unauthorized_mutation",
    "dependency_loss",
    "dangling_reference",
    "pre_approval_write",
)
STEP_FIELDS: Final[tuple[str, ...]] = get_args(StepChangeField)
# Everything a StepChangeField names that lives on the step row itself; the
# name is its `user_description`, the rest belongs to the step's assistant.
PERSISTED_STEP_KEYS: Final = tuple(
    field
    for field in STEP_FIELDS
    if field not in {"name", "instructions", "model_ref", "knowledge_refs"}
)
FlowField = Literal["flow_name", "flow_description", "metadata"]
FLOW_FIELDS: Final[tuple[str, ...]] = get_args(FlowField)
_SLOT = re.compile(r"[sn][1-9]\d*")
_EDGE = (
    r"^(?P<producer>(?P<slot>[sn][1-9]\d*)\.(?:text|structured)(?:\.[\w-]+)*"
    r"|(?:form|sys|run)\.[\w-]+) -> (?P<consumer>[sn][1-9]\d*)"
    r"(?: @(?P<placeholder>[\w.-]+))?$"
)
_DIGIT_GROUP = re.compile(r"(?<=\d) (?=\d{3}(?!\d))")
# A preview names a model or knowledge by its portable slot ref and the flow
# by resource id, so their displayed values are not comparable here; every
# other field's displayed value must be the value the apply wrote.
_RESOURCE_FIELDS: Final = frozenset({"model_ref", "knowledge_refs"})
_NEW_SLOT_BASE = 1000


# --- Shared parsing and literal oracle ---------------------------------------


def closed_object(
    value: object, allowed: frozenset[str], *, owner: str, noun: str = "keys"
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{owner} must be an object.")
    raw = cast(Mapping[str, Any], value)
    unknown = sorted(str(key) for key in set(raw) - allowed)
    if unknown:
        raise ValueError(f"{owner} has unknown {noun}: {', '.join(unknown)}")
    return raw


def normalized_text(value: str) -> str:
    """Edit fact normalization: also one fact across "48 500" and "48500"."""

    collapsed = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    return _DIGIT_GROUP.sub("", collapsed)


def literal_list(
    value: object, *, owner: str, normalize: Callable[[str], str]
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and normalize(item) for item in cast(list[object], value)
    ):
        raise ValueError(f"{owner} must be a list of non-empty literals.")
    literals = tuple(cast(list[str], value))
    if len({normalize(item) for item in literals}) != len(literals):
        raise ValueError(f"{owner} repeats a literal.")
    return literals


def literal_checks(
    text: str,
    *,
    required: Sequence[str],
    forbidden: Sequence[str],
    normalize: Callable[[str], str],
) -> list[JsonObject]:
    """Each literal must (or must not) appear in the normalized text."""

    normalized = normalize(text) if text else ""
    checks: list[JsonObject] = []
    for name, key, literals, must_appear in (
        ("required_fact", "fact", required, True),
        ("forbidden_literal", "literal", forbidden, False),
    ):
        for literal in literals:
            present = bool(normalized) and normalize(literal) in normalized
            checks.append(
                {
                    "name": name,
                    key: literal,
                    "passed": bool(normalized) and present == must_appear,
                    "reason": f"{literal!r} "
                    + ("appears in" if present else "is missing from")
                    + " the final output",
                }
            )
    return checks


# --- Gold ---------------------------------------------------------------------


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldScope(_Closed):
    required: list[StepChangeField] = []
    permitted: list[StepChangeField] = []

    @model_validator(mode="after")
    def _required_is_permitted(self) -> Self:
        if not set(self.required) <= set(self.permitted):
            raise ValueError("every required field must also be permitted")
        return self


class FlowScope(_Closed):
    required: list[FlowField] = []
    permitted: list[FlowField] = []

    @model_validator(mode="after")
    def _required_is_permitted(self) -> Self:
        if not set(self.required) <= set(self.permitted):
            raise ValueError("every required field must also be permitted")
        return self


class FormDelta(_Closed):
    added: list[str] = []
    removed: list[str] = []
    modified: list[str] = []


Edge = Annotated[str, StringConstraints(pattern=_EDGE)]


class EdgeDelta(_Closed):
    add: list[Edge] = []
    may_add: list[Edge] = []
    drop: list[Edge] = []
    may_drop: list[Edge] = []


class NameIs(_Closed):
    kind: Literal["name"]
    step: str
    equals: str


class OutputTypeIs(_Closed):
    kind: Literal["output_type"]
    step: str
    equals: str


class FormFieldIs(_Closed):
    kind: Literal["form_field"]
    name: str
    type: str
    required: bool


class StepOutput(_Closed):
    """A bounded literal check on one step's own run output."""

    output_kind: Literal["text", "json"] | None = None
    required_facts: list[str] = Field(min_length=1)
    forbidden: list[str] = []

    @field_validator("required_facts", "forbidden")
    @classmethod
    def _literals(cls, value: list[str]) -> list[str]:
        return list(literal_list(value, owner="step output", normalize=normalized_text))


class EditExpectation(_Closed):
    """A case's gold. Omitted keys are strict: nothing of that kind changes."""

    outcome: Literal["plan", "declined"]
    decline_reason: DeclineReason | None = None
    sequence: list[str] | None = None
    changes: dict[str, FieldScope] = {}
    flow: FlowScope = FlowScope()
    form_fields: FormDelta = FormDelta()
    edges: EdgeDelta = EdgeDelta()
    postconditions: list[
        Annotated[NameIs | OutputTypeIs | FormFieldIs, Field(discriminator="kind")]
    ] = []
    step_outputs: dict[str, StepOutput] = {}

    @model_validator(mode="after")
    def _outcome_shape(self) -> Self:
        if self.outcome != "plan" and self.model_fields_set - {
            "outcome",
            "decline_reason",
        }:
            raise ValueError(f"a {self.outcome} outcome carries no plan gold")
        if (self.outcome == "declined") != (self.decline_reason is not None):
            raise ValueError("decline_reason belongs to a declined outcome only")
        return self

    def expected_sequence(self, step_count: int) -> list[str]:
        return self.sequence or [f"s{order}" for order in range(1, step_count + 1)]


def parse_edit_expectation(
    raw: object, *, seed: Mapping[str, Any], owner: str
) -> EditExpectation:
    """The gold, typed and checked against its seed fixture."""

    try:
        gold = EditExpectation.model_validate(raw)
    except ValidationError as error:
        raise ValueError(f"{owner}: {error}") from error
    if gold.outcome != "plan":
        return gold
    count = len(seed["steps"])
    sequence = gold.expected_sequence(count)
    new = [slot for slot in sequence if slot.startswith("n")]
    if (
        len(set(sequence)) != len(sequence)
        or not all(_SLOT.fullmatch(slot) for slot in sequence)
        or any(int(slot[1:]) > count for slot in sequence if slot.startswith("s"))
        or new != [f"n{index}" for index in range(1, len(new) + 1)]
    ):
        raise ValueError(f"{owner}.sequence must list s1..s{count} and n1.. in order.")
    baseline = flow_edges(seed_view(seed))[0]
    edges = gold.edges
    misfits = [f"changes.{slot}" for slot in gold.changes if slot not in sequence]
    misfits += [
        f"drop {edge}" for edge in edges.drop + edges.may_drop if edge not in baseline
    ]
    misfits += [
        f"add {edge}"
        for edge in edges.add + edges.may_add
        if edge in baseline
        or any(end and end not in sequence for end in _edge_steps(edge))
    ]
    misfits += [
        f"postcondition {post.step}"
        for post in gold.postconditions
        if not isinstance(post, FormFieldIs) and post.step not in sequence
    ]
    misfits += [
        f"step_outputs.{slot}" for slot in gold.step_outputs if slot not in sequence
    ]
    if misfits:
        raise ValueError(f"{owner} does not fit its seed: {misfits}")
    return gold


def _edge_steps(edge: str) -> tuple[str | None, str | None]:
    match = re.match(_EDGE, edge)
    return (match["slot"], match["consumer"]) if match else (None, None)


# --- Views and edges -----------------------------------------------------------


def seed_view(fixture: Mapping[str, Any]) -> JsonObject:
    """A seed fixture read as the view a persisted flow gives."""

    steps = [
        {
            "slot": f"s{order}",
            "name": step.get("user_description") or step["name"],
            "instructions": step["instructions"],
            **{key: step.get(key) for key in PERSISTED_STEP_KEYS},
        }
        for order, step in enumerate(cast(list[Mapping[str, Any]], fixture["steps"]), 1)
    ]
    return {
        "steps": steps,
        "form_fields": _form_fields(fixture.get("metadata_json")),
        "metadata": {
            key: value
            for key, value in _obj(fixture.get("metadata_json")).items()
            if key != "form_schema"
        },
    }


def snapshot_view(
    snapshot: Mapping[str, Any], identity: Mapping[str, str]
) -> JsonObject:
    """One persisted flow read as seed slots; unknown assistants become n1.."""

    flow = _obj(snapshot["flow"])
    assistants = _obj(snapshot["assistants"])
    steps: list[JsonObject] = []
    for step in sorted(
        cast(list[Mapping[str, Any]], flow.get("steps") or []),
        key=lambda item: int(item.get("step_order") or 0),
    ):
        assistant_id = str(step.get("assistant_id"))
        assistant = _obj(assistants.get(assistant_id))
        new = sum(item["slot"].startswith("n") for item in steps) + 1
        steps.append(
            {
                "slot": identity.get(assistant_id, f"n{new}"),
                "assistant_id": assistant_id,
                "name": step.get("user_description"),
                "instructions": _obj(assistant.get("prompt")).get("text"),
                "model_ref": _obj(assistant.get("completion_model")).get("id"),
                "knowledge_refs": sorted(
                    str(_obj(item).get("id"))
                    for key in ("groups", "websites", "integration_knowledge_list")
                    for item in _items(assistant.get(key))
                ),
                **{key: step.get(key) for key in PERSISTED_STEP_KEYS},
            }
        )
    metadata = _obj(flow.get("metadata_json"))
    return {
        "steps": steps,
        "form_fields": _form_fields(metadata),
        "revision": flow.get("draft_revision"),
        "flow_name": flow.get("name"),
        "flow_description": flow.get("description") or "",
        # Form fields are judged by name; `ai_builder` is the server's own
        # provenance stamp, written by every apply.
        "metadata": {
            key: value
            for key, value in metadata.items()
            if key not in {"form_schema", "ai_builder"}
        },
    }


def _obj(value: object) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else {}


def _form_fields(metadata: object) -> dict[str, Any]:
    fields = _items(_obj(_obj(metadata).get("form_schema")).get("fields"))
    return {str(_obj(field).get("name")): field for field in fields}


def _items(value: object) -> list[object]:
    return cast(list[object], value) if isinstance(value, list) else []


def flow_edges(view: Mapping[str, Any]) -> tuple[frozenset[str], list[str]]:
    """Every producer->consumer read of a flow, and every dangling reference.

    Inputs are the effective underlag (`effective_question_binding` lowers
    `source_refs`) or, without one, the implicit input the product resolves;
    instructions and template_fill bindings always count; a speaker mapping
    reads its participants field. `step_N` resolves by position, as at run time.
    """

    steps = cast(list[Mapping[str, Any]], view["steps"])
    forms = set(_obj(view["form_fields"]))
    edges: set[str] = set()
    dangling: list[str] = []

    def read(text: str, order: int, placeholder: object = None) -> None:
        consumer = steps[order - 1]["slot"]
        suffix = f" @{placeholder}" if placeholder else ""
        for ref in analyze_template(text, step_refs={}, form_field_names=forms):
            if ref.kind is TemplateReferenceKind.STEP:
                producer = ref.step_order
                if ref.path_error_code or producer is None or not 1 <= producer < order:
                    dangling.append(f"{ref.expression} -> {consumer}")
                    continue
                edges.add(
                    _edge(steps[producer - 1], consumer, ref.tail, ref.structured_path)
                    + suffix
                )
            elif ref.form_field_name or ref.kind is TemplateReferenceKind.FORM_FIELD:
                edges.add(
                    f"form.{ref.form_field_name or ref.head} -> {consumer}{suffix}"
                )
            elif ref.head in {"datum", "step_input"}:
                source = "sys" if ref.head == "datum" else "run"
                edges.add(f"{source}.{ref.head} -> {consumer}{suffix}")

    for order, step in enumerate(steps, start=1):
        question = effective_question_binding(step.get("input_bindings"))
        if question is not None:
            read(question, order)
        elif step.get("input_source") == "flow_input":
            edges.add(f"run.input -> {step['slot']}")
        else:
            for producer in resolve_upstream_step_orders(
                input_source=step.get("input_source"),
                step_order=order,
                binding_references=None,
                max_prior_step_order=order - 1,
            ):
                previous = steps[producer - 1]
                tail = (
                    "output.structured"
                    if previous.get("output_type") == "json"
                    else "output.text"
                )
                edges.add(_edge(previous, step["slot"], tail, None))
        if isinstance(step.get("instructions"), str):
            read(step["instructions"], order)
        output_config = _obj(step.get("output_config"))
        for placeholder, expression in _obj(output_config.get("bindings")).items():
            if isinstance(expression, str) and expression.strip():
                read(expression, order, placeholder)
        participants = _obj(output_config.get("speaker_mapping")).get(
            "participants_field"
        )
        if participants:
            edges.add(f"form.{participants} -> {step['slot']}")
    return frozenset(edges), dangling


def _edge(
    producer: Mapping[str, Any], consumer: str, tail: str, path: tuple[str, ...] | None
) -> str:
    if tail.startswith("output.structured"):
        return f"{producer['slot']}.structured{''.join(f'.{part}' for part in path or ())} -> {consumer}"
    return f"{producer['slot']}.text -> {consumer}"


def _identity(view: Mapping[str, Any], *, plan_refs: bool = False) -> dict[str, int]:
    """Each name a step reference can use for a position, to the identity of
    the step there (its seed order; new steps 1000+).

    The flow refers by run position (`step_N`); a preview by the plan's own
    refs (`make_plan_step_ref`) over the same, applied, order.
    """

    identity: dict[str, int] = {}
    for position, step in enumerate(cast(list[Mapping[str, Any]], view["steps"]), 1):
        order = int(step["slot"][1:]) + (
            _NEW_SLOT_BASE if step["slot"][0] == "n" else 0
        )
        identity[f"step_{position}"] = order
        if plan_refs:
            identity[make_plan_step_ref(position - 1)] = order
    return identity


def _rewritten(value: object, identity: dict[str, int]) -> object:
    """A field value with its step references, and only those, rewritten to
    producer identity by the product's own rewriters."""

    return rewrite_source_ref_step_refs(
        rewrite_variable_value(value, identity), identity
    )


def _canonical_steps(view: Mapping[str, Any]) -> dict[str, JsonObject]:
    """Each step by slot, its step refs rewritten to its producers' identity,
    so a renumbering alone compares equal and a switched producer does not."""

    identity = _identity(view)
    return {
        step["slot"]: {
            **step,
            **{field: _rewritten(step.get(field), identity) for field in STEP_FIELDS},
        }
        for step in cast(list[Mapping[str, Any]], view["steps"])
    }


def _value(value: object) -> str:
    """A displayed or applied value as comparable JSON; null and "" are absence."""

    def present(item: object) -> object:
        if isinstance(item, Mapping):
            return {
                key: present(inner)
                for key, inner in cast(Mapping[str, object], item).items()
                if inner is not None
            }
        return item or None if isinstance(item, str) else item

    return json.dumps(present(value), sort_keys=True, ensure_ascii=False)


# --- Atoms -----------------------------------------------------------------------


def observed_atoms(before: Mapping[str, Any], after: Mapping[str, Any]) -> set[Atom]:
    """Everything that differs between two views of one seeded flow."""

    old, new = _canonical_steps(before), _canonical_steps(after)
    atoms: set[Atom] = {("removed", slot) for slot in old.keys() - new.keys()}
    atoms |= {("added", slot) for slot in new.keys() - old.keys()}
    atoms |= {
        ("step", slot, field)
        for slot in old.keys() & new.keys()
        for field in STEP_FIELDS
        if old[slot].get(field) != new[slot].get(field)
    }
    atoms |= {
        ("value", atom[1], atom[2], _value(new[atom[1]].get(atom[2])))
        for atom in list(atoms)
        if atom[0] == "step" and atom[2] not in _RESOURCE_FIELDS
    }
    atoms |= {("flow", key) for key in FLOW_FIELDS if before.get(key) != after.get(key)}
    old_forms, new_forms = _obj(before["form_fields"]), _obj(after["form_fields"])
    atoms |= {("form", "added", name) for name in new_forms.keys() - old_forms.keys()}
    atoms |= {("form", "removed", name) for name in old_forms.keys() - new_forms.keys()}
    atoms |= {
        ("form", "modified", name)
        for name in old_forms.keys() & new_forms.keys()
        if old_forms[name] != new_forms[name]
    }
    old_edges, new_edges = flow_edges(before)[0], flow_edges(after)[0]
    atoms |= {("edge+", edge) for edge in new_edges - old_edges}
    atoms |= {("edge-", edge) for edge in old_edges - new_edges}
    return atoms


def shown_atoms(
    approval: FlowBuilderEditApproval, applied: Mapping[str, Any]
) -> set[Atom]:
    """What the server's diff tells the user changed, with the value it shows
    (its full `current_detail` where it has one); it names no reads."""

    identity = _identity(applied, plan_refs=True)
    atoms: set[Atom] = set()
    added = 0
    for change in approval.diff.step_changes:
        if change.kind == "added":
            added += 1
            atoms.add(("added", f"n{added}"))
            continue
        slot = f"s{existing_step_order_from_ref(change.step_ref)}"
        if change.kind == "removed":
            atoms.add(("removed", slot))
        atoms |= {("step", slot, item.field) for item in change.field_changes}
        atoms |= {
            (
                "value",
                slot,
                item.field,
                _value(
                    _rewritten(
                        json.loads(item.current_detail)
                        if item.current_detail is not None
                        else item.current,
                        identity,
                    )
                ),
            )
            for item in change.field_changes
            if item.field not in _RESOURCE_FIELDS
        }
    atoms |= {("flow", key) for key in approval.diff.flow_property_changes}
    if approval.diff.metadata_changes:
        atoms.add(("flow", "metadata"))
    atoms |= {
        ("form", item.kind, item.field_name) for item in approval.diff.form_changes
    }
    return atoms


def gold_atoms(
    gold: EditExpectation, *, baseline: Mapping[str, Any]
) -> tuple[set[Atom], set[Atom]]:
    """The atoms the gold requires, and every atom it permits.

    The reads of a step the gold removes go with it: they are permitted drops.
    """

    seed_slots = [step["slot"] for step in baseline["steps"]]
    sequence = gold.expected_sequence(len(seed_slots))
    removed = set(seed_slots) - set(sequence)
    required: set[Atom] = {("added", slot) for slot in sequence if slot.startswith("n")}
    required |= {("removed", slot) for slot in removed}
    required |= {
        ("step", slot, field)
        for slot, scope in gold.changes.items()
        for field in scope.required
    }
    required |= {("flow", key) for key in gold.flow.required}
    required |= {
        ("form", kind, name)
        for kind in ("added", "removed", "modified")
        for name in getattr(gold.form_fields, kind)
    }
    required |= {("edge+", edge) for edge in gold.edges.add}
    required |= {("edge-", edge) for edge in gold.edges.drop}
    permitted = set(required)
    permitted |= {
        ("step", slot, field)
        for slot, scope in gold.changes.items()
        for field in scope.permitted
    }
    permitted |= {("flow", key) for key in gold.flow.permitted}
    permitted |= {("edge+", edge) for edge in gold.edges.may_add}
    permitted |= {("edge-", edge) for edge in gold.edges.may_drop}
    permitted |= {
        ("edge-", edge)
        for edge in flow_edges(baseline)[0]
        if set(_edge_steps(edge)) & removed
    }
    return required, permitted


# --- Evaluation ------------------------------------------------------------------


def evaluate_edit(
    gold: EditExpectation,
    *,
    seed: Mapping[str, Any],
    evidence: Mapping[str, Any],
    selected_step_name: str | None = None,
) -> JsonObject:
    """The structural phase: judge one observation by its expected outcome.

    `evidence`: identity {assistant_id: slot}, captured_revision, baseline,
    after_turn, outcome {plan, questions, final_text, ui_language}, plan,
    apply {applied | refused}, applied.
    """

    checks: list[JsonObject] = []

    def check(
        name: str, passed: bool | None, category: Category, detail: object = None
    ) -> None:
        checks.append(
            {"name": name, "passed": passed, "category": category, "detail": detail}
        )

    identity = cast(Mapping[str, str], evidence["identity"])
    baseline = snapshot_view(evidence["baseline"], identity)
    before_approval = snapshot_view(evidence["after_turn"], identity)
    written = sorted(observed_atoms(baseline, before_approval))
    if before_approval["revision"] != baseline["revision"]:
        written.append(("revision",))
    check("flow_unchanged_before_approval", not written, "pre_approval_write", written)
    outcome = _obj(evidence["outcome"])
    has_plan, questions = outcome.get("plan") is True, outcome.get("questions") or 0
    if gold.outcome == "declined":
        # A behavioural proxy until the session API exposes the typed outcome:
        # the exact server-owned sentence for the declared reason, which names
        # the selected step in a selected-step edit.
        sentence = decline_message(
            cast(DeclineReason, gold.decline_reason),
            ui_language=outcome.get("ui_language"),
            step_name=selected_step_name,
        )
        declined = (
            not has_plan and not questions and outcome.get("final_text") == sentence
        )
        check(
            "outcome",
            declined,
            "fulfilment",
            {
                "plan": has_plan,
                "questions": questions,
                "proxy_outcome": "exact_decline_sentence",
            },
        )
        return report(checks)
    check("outcome", has_plan, "fulfilment", {"plan": has_plan})
    check("questions", not questions, "questions", {"questions": questions})
    if not has_plan:
        return report(checks)
    try:
        approval = FlowBuilderEditApproval.model_validate(
            _obj(_obj(_obj(evidence["plan"]).get("proposal")).get("edit"))
        )
    except ValidationError as error:
        check("diff_complete", False, "diff_integrity", str(error)[:500])
        return report(checks)
    count = len(seed["steps"])
    refs = [
        change.step_ref
        for change in approval.diff.step_changes
        if change.kind != "added"
    ]
    check(
        "diff_complete",
        approval.base_flow_revision == evidence.get("captured_revision")
        and len(refs) == len(set(refs))
        and set(refs)
        == {existing_step_ref_for_order(order) for order in range(1, count + 1)}
        and all(
            bool(change.field_changes) == (change.kind == "modified")
            for change in approval.diff.step_changes
        )
        and frozenset(
            str(change.step_ref)
            for change in approval.diff.step_changes
            if change.kind == "removed"
        )
        == approval.removed_existing_step_refs,
        "diff_integrity",
        {"refs": refs, "base_flow_revision": approval.base_flow_revision},
    )
    apply = _obj(evidence.get("apply"))
    if "refused" in apply or evidence.get("applied") is None:
        # The server's code does not say which rule refused the plan (an
        # unknown step ref and a silently dropped step share one), so the
        # refusal is recorded as it is, not guessed into a zero-tolerance row.
        check(
            "apply", False, "apply_refused", apply.get("refused") or "no applied flow"
        )
        return report(checks)
    applied = snapshot_view(evidence["applied"], identity)
    sequence = gold.expected_sequence(count)
    applied_slots = [step["slot"] for step in applied["steps"]]
    # Order only: which steps exist is judged by the atoms below.
    check(
        "sequence",
        [slot for slot in applied_slots if slot in sequence]
        == [slot for slot in sequence if slot in applied_slots],
        "order",
        {"expected": sequence, "applied": applied_slots},
    )
    observed = observed_atoms(baseline, applied)
    shown = shown_atoms(approval, applied)
    required, permitted = gold_atoms(gold, baseline=baseline)
    # Displayed values are judged for honesty only; scope is by field.
    outside = {atom for atom in observed | shown if atom[0] != "value"} - permitted
    lost = sorted(atom for atom in outside if atom[0] == "edge-")
    check("kept_dependencies", not lost, "dependency_loss", lost)
    check(
        "scope",
        not outside - set(lost),
        "unauthorized_mutation",
        sorted(outside - set(lost)),
    )
    check("fulfilment", required <= observed, "fulfilment", sorted(required - observed))
    unshown = {atom for atom in observed if not atom[0].startswith("edge")}
    check(
        "diff_matches_applied",
        unshown == shown,
        "diff_integrity",
        {"hidden": sorted(unshown - shown), "phantom": sorted(shown - unshown)},
    )
    dangling = flow_edges(applied)[1]
    check("references", not dangling, "dangling_reference", dangling)
    by_slot = {step["slot"]: step for step in applied["steps"]}
    for post in gold.postconditions:
        if isinstance(post, FormFieldIs):
            field = _obj(_obj(applied["form_fields"]).get(post.name))
            holds = (
                field.get("type") == post.type
                and bool(field.get("required")) is post.required
            )
        else:
            key = "name" if isinstance(post, NameIs) else "output_type"
            holds = _obj(by_slot.get(post.step)).get(key) == post.equals
        check(f"postcondition_{post.kind}", holds, "fulfilment", post.model_dump())
    return report(checks)


def add_execution(
    structural: Mapping[str, Any],
    gold: EditExpectation,
    *,
    evidence: Mapping[str, Any],
    output_success: object,
    step_results: object,
) -> JsonObject:
    """The execution phase, appended to the structural one: one verdict."""

    checks = list(cast(list[JsonObject], structural["checks"]))
    checks.append(
        {
            "name": "run_output",
            "passed": output_success is True,
            "category": "execution",
            "detail": output_success,
        }
    )
    results = {
        str(_obj(item).get("assistant_id")): _obj(item)
        for item in cast(list[object], step_results or [])
    }
    applied = evidence.get("applied")
    slots = (
        {
            step["slot"]: step["assistant_id"]
            for step in snapshot_view(applied, evidence["identity"])["steps"]
        }
        if applied is not None
        else {}
    )
    for slot, rule in gold.step_outputs.items():
        passed, detail = _step_output(rule, results.get(slots.get(slot, "")))
        checks.append(
            {
                "name": f"step_output_{slot}",
                "passed": passed,
                "category": "execution",
                "detail": detail,
            }
        )
    return report(checks)


def _step_output(
    rule: StepOutput, result: Mapping[str, Any] | None
) -> tuple[bool | None, object]:
    """A missing or file-backed (preview-only) output is unmeasured, never a pass."""

    payload = _obj(_obj(result).get("output_payload_json"))
    if OUTPUT_TEXT_OVERFLOW_KEY in payload or not isinstance(payload.get("text"), str):
        return None, "step output missing or file-backed"
    structured = payload.get("structured")
    kind = "text" if structured is None else "json"
    text = payload["text"] + (
        "" if structured is None else json.dumps(structured, ensure_ascii=False)
    )
    literals = literal_checks(
        text,
        required=rule.required_facts,
        forbidden=rule.forbidden,
        normalize=normalized_text,
    )
    failed = [check for check in literals if not check["passed"]]
    return rule.output_kind in {None, kind} and not failed, {
        "kind": kind,
        "failed": failed,
    }


def report(checks: list[JsonObject]) -> JsonObject:
    failed = [check for check in checks if check["passed"] is False]
    verdict = (
        "fail"
        if failed
        else (
            "unmeasured" if any(check["passed"] is None for check in checks) else "pass"
        )
    )
    return {
        "verdict": verdict,
        "failed_checks": [check["name"] for check in failed],
        "categories": sorted({check["category"] for check in failed}),
        "checks": checks,
    }
