"""Mechanism diagnostics: how a run's published flow was wired, observed, never judged.

Two typed observations per run, read from the product's own records, carried
by the Builder observation's quality report (`_quality_report`); the oracle
arm's report does not carry them. Neither is a verdict: no check carries them,
so no plan, output or case state can depend on them; the paired analysis
compares them between arms.

- `consumer_received`: for each run-form field, whether the run's author
  consumed it. The author is found by producer identity, never by position:
  the one model-producing step whose result the delivery step (the run
  contract's `final_output`) consumes, followed back through deterministic
  steps on their typed `step_result` lineage sources. Only a selection of a
  step's `output` is consumption of its result; a selection of its input,
  status or error is not, and any other selection abstains. A run with no run
  form is not applicable, whatever its author. A field is consumed when
  the author's current attempt has a source of kind `flow_input` whose
  selector starts at the field, or selects the whole form.
  A binding's spelling (`flow_input.x`, `flow.input.x`, `input_source`) is
  never read. Absence says only that the author was not given the field; an
  earlier step may have used it.
- `review_checkpoint_on`: the step each review checkpoint was created on, from
  the product's checkpoint record, cross-checked with what the harness saw
  before any edit, and how that step sits relative to the author. A
  checkpoint's payload is never read: the harness edits it.

Each observation is decided, or abstains with a typed reason; evidence that
does not parse abstains, never decides.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, NamedTuple, TypeVar, cast
from uuid import UUID

from ai_builder_runtime_lineage import (
    RuntimeLineageStatus,
    StepAttemptEvidence,
    current_tracked_lineage,
    parse_step_attempt_evidence,
    strict_json,
)
from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from eneo.flows.enums import (
    FLOW_COMPLETION_MODEL_OUTPUT_MODES,
    FlowOutputMode,
    FlowStepResultStatus,
)
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputFlowInputSource,
    FlowResolvedInputLineageTracked,
    FlowResolvedInputStepResultSource,
)

JsonObject = dict[str, Any]
CONSUMER_AUTHOR = "author"
# What a `step_result` selector reads of a prior step (`variable_resolver`'s
# step context): only its `output` is the step's result. Its `input`, `status`
# and `error_message` are about the step, not consumption of what it wrote.
_STEP_OUTPUT = "output"
_STEP_METADATA = frozenset({"input", "status", "error_message"})


class Abstain(StrEnum):
    NO_RUN = "no_run"
    DEFINITION_INVALID = "definition_invalid"
    RUN_FORM_INVALID = "run_form_invalid"
    DELIVERY_INVALID = "delivery_invalid"
    # A step on the way back from the delivery has no completed result: the
    # run stopped before it (a review pause the harness ended, a failure).
    DELIVERY_NOT_COMPLETED = "delivery_not_completed"
    CONSUMER_UNRESOLVED = "consumer_unresolved"
    CONSUMER_AMBIGUOUS = "consumer_ambiguous"
    SELECTION_UNSUPPORTED = "selection_unsupported"
    NOT_REACHED = "not_reached"
    STEP_NOT_COMPLETED = "step_not_completed"
    CHECKPOINTS_INVALID = "checkpoints_invalid"
    NO_CHECKPOINT_CREATED = "no_checkpoint_created"
    CHECKPOINT_UNRECORDED = "checkpoint_unrecorded"
    CHECKPOINT_EVIDENCE_CONFLICT = "checkpoint_evidence_conflict"
    CHECKPOINT_STEP_UNKNOWN = "checkpoint_step_unknown"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


def _distinct(field: str) -> AfterValidator:
    def check(rows: tuple[Any, ...]) -> tuple[Any, ...]:
        values = [getattr(row, field) for row in rows]
        if len(set(values)) != len(values):
            raise ValueError(f"{field} must be distinct")
        return rows

    return AfterValidator(check)


class _Step(_Strict):
    step_id: UUID
    step_order: Annotated[int, Field(ge=1)]
    output_mode: FlowOutputMode


class _Definition(_Strict):
    steps: Annotated[
        tuple[_Step, ...],
        Field(min_length=1),
        _distinct("step_id"),
        _distinct("step_order"),
    ]


class _FormField(_Strict):
    name: Annotated[str, Field(min_length=1)]


class _RunForm(_Strict):
    form_fields: Annotated[tuple[_FormField, ...], _distinct("name")]


class _Author(NamedTuple):
    step: _Step
    attempts: StepAttemptEvidence


class _FinalOutput(_Strict):
    step_id: UUID


class _Delivery(_Strict):
    final_output: _FinalOutput


class _CheckpointRow(_Strict):
    id: UUID
    step_id: UUID
    step_order: Annotated[int, Field(ge=1)]
    attempt_no: Annotated[int, Field(ge=1)]
    # Aware only: a naive time cannot be ordered against an aware one.
    created_at: AwareDatetime


class _ObservedCheckpoint(_Strict):
    id: UUID
    step_id: UUID
    step_order: Annotated[int, Field(ge=1)]


class _CheckpointRecords(_Strict):
    rows: Annotated[tuple[_CheckpointRow, ...], _distinct("id")]
    observed: tuple[_ObservedCheckpoint, ...]


_Model = TypeVar("_Model", bound=BaseModel)


def _parsed(model: type[_Model], value: object) -> _Model | None:
    """The record under the lineage reader's strict JSON rules, or None."""
    try:
        return strict_json(model, value)
    except (ValidationError, TypeError, ValueError):
        return None


def plan_mechanisms(runtime_evidence: object) -> JsonObject:
    """Both diagnostics of one run's evidence (None: the harness ran nothing)."""

    if not isinstance(runtime_evidence, Mapping):
        return {
            "consumer_received": {
                "consumer": CONSUMER_AUTHOR,
                "abstain": Abstain.NO_RUN,
            },
            "review_checkpoint_on": {"abstain": Abstain.NO_RUN},
        }
    evidence = cast(Mapping[str, object], runtime_evidence)
    definition = _parsed(_Definition, evidence.get("definition_snapshot"))
    attempts = parse_step_attempt_evidence(evidence)
    author = _author(evidence, definition, attempts)
    return {
        "consumer_received": _consumer_received(evidence, author),
        "review_checkpoint_on": _review_checkpoint_on(evidence, definition, author),
    }


def _author(
    evidence: Mapping[str, object],
    definition: _Definition | None,
    attempts: StepAttemptEvidence | RuntimeLineageStatus,
) -> _Author | str:
    """The one producing step whose result reaches the delivery step, followed
    back from the delivery through deterministic steps on typed lineage."""

    if definition is None:
        return Abstain.DEFINITION_INVALID
    contract = _parsed(_Delivery, evidence.get("run_contract"))
    steps = {step.step_id: step for step in definition.steps}
    if contract is None or contract.final_output.step_id not in steps:
        return Abstain.DELIVERY_INVALID
    if isinstance(attempts, RuntimeLineageStatus):
        return attempts
    delivery = contract.final_output.step_id
    producers: set[UUID] = set()
    frontier, seen = [delivery], {delivery}
    while frontier:
        lineage = _current_lineage(attempts, frontier.pop())
        if lineage in (Abstain.NOT_REACHED, Abstain.STEP_NOT_COMPLETED):
            return Abstain.DELIVERY_NOT_COMPLETED
        if isinstance(lineage, str):
            return lineage
        for edge in lineage.edges:
            if not isinstance(edge.source, FlowResolvedInputStepResultSource):
                continue
            path = edge.source.selector.path
            if path[:1] != (_STEP_OUTPUT,):
                if path[:1] and path[0] in _STEP_METADATA:
                    continue
                return Abstain.SELECTION_UNSUPPORTED
            step = steps.get(edge.source.source_step_id)
            if step is None:
                return Abstain.DEFINITION_INVALID
            # The walk starts at the delivery's sources: a delivery that runs a
            # model itself (an HTTP post, a writing step) is never its author.
            if step.output_mode in FLOW_COMPLETION_MODEL_OUTPUT_MODES:
                producers.add(step.step_id)
            elif step.step_id not in seen:
                seen.add(step.step_id)
                frontier.append(step.step_id)
    if len(producers) != 1:
        return Abstain.CONSUMER_AMBIGUOUS if producers else Abstain.CONSUMER_UNRESOLVED
    return _Author(steps[producers.pop()], attempts)


def _current_lineage(
    attempts: StepAttemptEvidence, step_id: UUID
) -> FlowResolvedInputLineageTracked | str:
    result = next((r for r in attempts.step_results if r.step_id == step_id), None)
    if result is None:
        return Abstain.NOT_REACHED
    if result.status is not FlowStepResultStatus.COMPLETED:
        return Abstain.STEP_NOT_COMPLETED
    return current_tracked_lineage(attempts, result)


def _consumer_received(
    evidence: Mapping[str, object], author: _Author | str
) -> JsonObject:
    def abstain(reason: str) -> JsonObject:
        return {"consumer": CONSUMER_AUTHOR, "abstain": reason}

    run_form = _parsed(_RunForm, evidence.get("run_contract"))
    if run_form is None:
        return abstain(Abstain.RUN_FORM_INVALID)
    # Applicability comes first: with no run form there is nothing to receive,
    # however the author resolves.
    if not run_form.form_fields:
        return {"consumer": CONSUMER_AUTHOR, "not_applicable": "no_run_form"}
    if isinstance(author, str):
        return abstain(author)
    lineage = _current_lineage(author.attempts, author.step.step_id)
    if isinstance(lineage, str):
        return abstain(lineage)
    selected = [
        edge.source.selector.path
        for edge in lineage.edges
        if isinstance(edge.source, FlowResolvedInputFlowInputSource)
    ]
    return {
        "consumer": CONSUMER_AUTHOR,
        "step_order": author.step.step_order,
        "fields": {
            field.name: "received"
            if any(not path or path[0] == field.name for path in selected)
            else "not_received"
            for field in run_form.form_fields
        },
    }


def _review_checkpoint_on(
    evidence: Mapping[str, object],
    definition: _Definition | None,
    author: _Author | str,
) -> JsonObject:
    records = _checkpoint_records(evidence)
    if records is None:
        return {"abstain": Abstain.CHECKPOINTS_INVALID}
    if not records.rows:
        return {
            "abstain": Abstain.CHECKPOINT_UNRECORDED
            if records.observed
            else Abstain.NO_CHECKPOINT_CREATED
        }
    if {seen.id for seen in records.observed} - {row.id for row in records.rows}:
        return {"abstain": Abstain.CHECKPOINT_UNRECORDED}
    if definition is None:
        return {"abstain": Abstain.DEFINITION_INVALID}
    steps = {step.step_id: step for step in definition.steps}
    rows = sorted(records.rows, key=lambda row: (row.created_at, str(row.id)))
    return {
        "checkpoints": [
            _checkpoint_on(row, records.observed, steps, author) for row in rows
        ]
    }


def _checkpoint_on(
    row: _CheckpointRow,
    observed: tuple[_ObservedCheckpoint, ...],
    steps: Mapping[UUID, _Step],
    author: _Author | str,
) -> JsonObject:
    item: JsonObject = {
        "checkpoint_id": str(row.id),
        "attempt_no": row.attempt_no,
        "step_order": row.step_order,
    }
    step = steps.get(row.step_id)
    if step is None:
        return {**item, "abstain": Abstain.CHECKPOINT_STEP_UNKNOWN}
    if step.step_order != row.step_order or any(
        seen.id == row.id
        and (seen.step_id, seen.step_order) != (row.step_id, row.step_order)
        for seen in observed
    ):
        return {**item, "abstain": Abstain.CHECKPOINT_EVIDENCE_CONFLICT}
    if isinstance(author, str):
        return {**item, "abstain": author}
    author_order = author.step.step_order
    relation = (
        "is_author"
        if step.step_order == author_order
        else "upstream"
        if step.step_order < author_order
        else "downstream"
    )
    return {**item, "relation": relation}


def _checkpoint_records(evidence: Mapping[str, object]) -> _CheckpointRecords | None:
    """The product's checkpoint rows and the checkpoints the harness saw open."""

    execution = evidence.get("execution")
    if not isinstance(execution, Mapping):
        return None
    observed: list[object] = []
    for key in ("checkpoints", "failures"):
        entries = cast(Mapping[str, object], execution).get(key)
        if not isinstance(entries, list):
            return None
        for entry in cast(list[object], entries):
            if not isinstance(entry, Mapping):
                return None
            entry = cast(Mapping[str, object], entry)
            if "checkpoint" in entry:
                observed.append(entry["checkpoint"])
    return _parsed(
        _CheckpointRecords,
        {"rows": evidence.get("review_checkpoints"), "observed": observed},
    )
