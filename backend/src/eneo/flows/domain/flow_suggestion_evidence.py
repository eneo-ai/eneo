"""What recent runs of a flow measured, as the suggestion rules read it.

Content-free by construction: input edges as their binding, producer,
selector, size and hash; provider calls as their reason, token counts and
the edges they sent; a step's outcome as its status and failure code; the
forwarding facts the worker measured on a model call (shares, sizes and edge
indexes, ``domain.forwarding_facts``). No prompt text, no output text, no
input value. The infrastructure reads it (``flow_suggestion_evidence_repo``),
the service hands it to the analyzer, and the measured rules
(``flow_suggestion_measured``, ``flow_suggestion_forwarding``) turn it into
numbers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from eneo.flows.domain.canonical_json_hash import canonical_json_hash
from eneo.flows.domain.forwarding_facts import ForwardingFacts
from eneo.flows.domain.tool_input import TOOL_INPUT_CONFIG_KEY

# The runs whose evidence is counted: finished, in any outcome. A run that is
# still going, or waits for review, has not measured all of its steps; the
# repository also leaves out a finished run in which no step ran.
COUNTED_RUN_STATUSES: tuple[str, ...] = ("completed", "failed", "cancelled")
# The most runs a request may measure.
MAX_MEASURED_RUNS = 50

COMPLETED_CALL_STATUS = "completed"
RESPONSE_FORMAT_FALLBACK_REASON = "response_format_fallback"
# The failure code of a step whose input exceeded the inline cap.
INLINE_CAP_FAILURE_CODE = "typed_io_input_too_large"

# The output mode whose published ``output_config`` publish rewrites (the
# template is resolved), so the draft's and the version's differ by design.
_TEMPLATE_FILL_MODE = "template_fill"


@dataclass(frozen=True, slots=True)
class EvidenceEdge:
    """One resolved input of a step attempt. ``binding_ref`` names where
    the step reads it, as ``StepRead.site`` does (``input_source``,
    ``input_bindings.question``, ``input_bindings.source_refs[N]``,
    ``assistant_prompt:<expression>`` and the configuration sites).
    ``source_step_id`` is the producing step, None for any other source;
    ``run_input`` marks the run's own input. ``byte_size`` and ``sha256``
    are those of the value read; None for a bound file, which is sent as a
    file rather than as text."""

    binding_ref: str
    source_step_id: UUID | None
    selector: tuple[str, ...]
    byte_size: int | None
    sha256: str | None
    run_input: bool = False


@dataclass(frozen=True, slots=True)
class EvidenceCall:
    """One completion call of a step attempt: its lifecycle status, why it
    was made, what it was billed and which edges (by index into the
    attempt's) it sent. ``mapped_index`` is the item or source a mapped
    step's call was about."""

    status: str
    call_reason: str
    num_tokens_input: int | None
    num_tokens_output: int | None
    edge_indexes: tuple[int, ...]
    mapped_index: int | None = None

    @property
    def completed(self) -> bool:
        return self.status == COMPLETED_CALL_STATUS


@dataclass(frozen=True, slots=True)
class EvidenceAttempt:
    """The current attempt of one step in one run, with the step result's
    status and failure code. ``edges`` are empty when the attempt never
    resolved its inputs (it failed before, or did not start).
    ``forwarding`` are the forwarding facts of its first model call that
    returned output, whose edge indexes point into ``edges``; None when the
    attempt has none or they cannot be read."""

    step_id: UUID
    step_order: int
    status: str
    error_code: str | None
    edges: tuple[EvidenceEdge, ...] = ()
    calls: tuple[EvidenceCall, ...] = ()
    forwarding: ForwardingFacts | None = None

    def measured_forwarding(self) -> ForwardingFacts | None:
        """The forwarding facts when the worker measured them: facts that
        record ``measured: false`` are no measurement."""
        facts = self.forwarding
        return facts if facts is not None and facts.measured else None

    def measured_call(self) -> EvidenceCall | None:
        """The call the forwarding facts describe: the attempt's first
        completed call."""
        return next((call for call in self.calls if call.completed), None)

    def tokens_per_byte(self, call: EvidenceCall) -> float | None:
        """The call's input tokens over the bytes of the edges it sent: how
        many tokens a byte of its input cost. None when the call did not
        complete, reported no input tokens or sent no measured edge."""
        if not call.completed or call.num_tokens_input is None:
            return None
        sizes = [
            size
            for index in call.edge_indexes
            if 0 <= index < len(self.edges)
            and (size := self.edges[index].byte_size) is not None
        ]
        total = sum(sizes)
        if total <= 0:
            return None
        return call.num_tokens_input / total

    def edge_tokens(self, index: int) -> tuple[float, int] | None:
        """What sending edge ``index`` cost in this attempt, in tokens, over
        every completed call that sent it, and how many calls those were.
        None when no call that sent it can be measured."""
        if not 0 <= index < len(self.edges):
            return None
        size = self.edges[index].byte_size
        if size is None:
            return None
        total = 0.0
        calls = 0
        for call in self.calls:
            if index not in call.edge_indexes:
                continue
            per_byte = self.tokens_per_byte(call)
            if per_byte is None:
                continue
            total += size * per_byte
            calls += 1
        return (total, calls) if calls else None

    def billed_tokens(self) -> int | None:
        """Input and output tokens of the attempt's completed calls; None
        when it has none that reported both."""
        totals = [
            call.num_tokens_input + call.num_tokens_output
            for call in self.calls
            if call.completed
            and call.num_tokens_input is not None
            and call.num_tokens_output is not None
        ]
        return sum(totals) if totals else None

    def peak_input_tokens(self) -> int | None:
        """The largest input of one completed call."""
        inputs = [
            call.num_tokens_input
            for call in self.calls
            if call.completed and call.num_tokens_input is not None
        ]
        return max(inputs) if inputs else None


@dataclass(frozen=True, slots=True)
class EvidenceRun:
    """One counted run: its published version and the current attempt of
    each step it reached."""

    run_id: UUID
    version: int
    attempts: tuple[EvidenceAttempt, ...]

    def attempt(self, step_id: UUID) -> EvidenceAttempt | None:
        return next(
            (attempt for attempt in self.attempts if attempt.step_id == step_id), None
        )


@dataclass(frozen=True, slots=True)
class StepDefinitionFacts:
    """A step's definition as far as measurements depend on it: the
    canonical hash of what decides what reaches its model, its completion
    model and its output type. Built the same way for a draft step and for
    a step of a published version, so equal hashes mean an unchanged step.

    ``reasoning_effort`` is the effort its assistant asks the model for
    (None when it asks for none). It decides nothing of what reaches the
    model, so it is outside the comparison: a rule whose measurement depends
    on it compares it itself (``RunEvidence.same_model_setup``)."""

    definition_hash: str
    completion_model_id: UUID | None
    output_type: str
    reasoning_effort: str | None = field(default=None, compare=False)


@dataclass(frozen=True, slots=True)
class RunEvidence:
    """What the counted runs measured, newest run first, with the facts of
    each step in each of their versions (by version and step id), the same
    facts for the draft's steps (by step id), and what the completion model
    catalogue knows: the input token limits (by model id; unknown limits
    absent) and the models it marks as reasoning-capable."""

    runs: tuple[EvidenceRun, ...]
    published_steps: Mapping[tuple[int, UUID], StepDefinitionFacts] = field(
        default_factory=lambda: dict[tuple[int, UUID], StepDefinitionFacts]()
    )
    draft_steps: Mapping[UUID, StepDefinitionFacts] = field(
        default_factory=lambda: dict[UUID, StepDefinitionFacts]()
    )
    model_input_limits: Mapping[UUID, int] = field(
        default_factory=lambda: dict[UUID, int]()
    )
    reasoning_models: frozenset[UUID] = frozenset()

    def step_changed_since(self, step_id: UUID, version: int) -> bool:
        """Whether the draft's step differs from the step in ``version``; a
        step either side lacks counts as changed."""
        draft = self.draft_steps.get(step_id)
        published = self.published_steps.get((version, step_id))
        return draft is None or published is None or draft != published

    def same_model_and_output(self, step_id: UUID, version: int) -> bool:
        """Whether the draft's step has the model and output type it had in
        ``version``: what a measurement of its model's behaviour needs."""
        draft = self.draft_steps.get(step_id)
        published = self.published_steps.get((version, step_id))
        return (
            draft is not None
            and published is not None
            and draft.completion_model_id == published.completion_model_id
            and draft.output_type == published.output_type
        )

    def same_model_setup(self, step_id: UUID, version: int) -> bool:
        """Whether the draft's step has the model, output type and reasoning
        effort it had in ``version``: what a measurement of how much its
        model writes needs, since the output it is billed includes what it
        spends reasoning."""
        draft = self.draft_steps.get(step_id)
        published = self.published_steps.get((version, step_id))
        return (
            self.same_model_and_output(step_id, version)
            and draft is not None
            and published is not None
            and draft.reasoning_effort == published.reasoning_effort
        )


def step_definition_facts(
    *,
    input_source: str,
    input_type: str,
    input_contract: Mapping[str, object] | None,
    input_bindings: Mapping[str, object] | None,
    input_config: Mapping[str, object] | None,
    output_mode: str,
    output_type: str,
    output_contract: Mapping[str, object] | None,
    output_config: Mapping[str, object] | None,
    prompt_text: str | None,
    completion_model_id: UUID | None,
    reasoning_effort: str | None = None,
) -> StepDefinitionFacts:
    """The facts of a step, draft or published. The hash covers its input,
    output, prompt and model; not its name, order, timeout or review, which
    change no measurement. Two settings publish rewrites by design are left
    out: a tool step's pinned tool (``input_config.tool``) and a template
    fill's ``output_config``. An empty configuration is no configuration,
    and an empty reasoning effort none."""

    config = {
        key: value
        for key, value in (input_config or {}).items()
        if key != TOOL_INPUT_CONFIG_KEY
    }
    return StepDefinitionFacts(
        definition_hash=canonical_json_hash(
            {
                "input_source": input_source,
                "input_type": input_type,
                "input_contract": _object_or_none(input_contract),
                "input_bindings": _object_or_none(input_bindings),
                "input_config": _object_or_none(config),
                "output_mode": output_mode,
                "output_type": output_type,
                "output_contract": _object_or_none(output_contract),
                "output_config": (
                    None
                    if output_mode == _TEMPLATE_FILL_MODE
                    else _object_or_none(output_config)
                ),
                "prompt": prompt_text or "",
                "completion_model_id": (
                    str(completion_model_id) if completion_model_id else None
                ),
            }
        ),
        completion_model_id=completion_model_id,
        output_type=output_type,
        reasoning_effort=reasoning_effort or None,
    )


def _object_or_none(value: Mapping[str, object] | None) -> dict[str, object] | None:
    return dict(value) if value else None


MeasuredValue = tuple[float, int]
"""One run's measurement of a finding and the version that run was of."""


@dataclass(frozen=True, slots=True)
class Measurement:
    """A finding measured over the runs that have it: the average per run,
    how many runs and the newest version among them."""

    average: float
    run_count: int
    version: int


def average_over_runs(values: Sequence[MeasuredValue]) -> Measurement | None:
    if not values:
        return None
    return Measurement(
        average=sum(value for value, _ in values) / len(values),
        run_count=len(values),
        version=max(version for _, version in values),
    )


__all__ = [
    "COMPLETED_CALL_STATUS",
    "COUNTED_RUN_STATUSES",
    "INLINE_CAP_FAILURE_CODE",
    "MAX_MEASURED_RUNS",
    "RESPONSE_FORMAT_FALLBACK_REASON",
    "EvidenceAttempt",
    "EvidenceCall",
    "EvidenceEdge",
    "EvidenceRun",
    "Measurement",
    "MeasuredValue",
    "RunEvidence",
    "StepDefinitionFacts",
    "average_over_runs",
    "step_definition_facts",
]
