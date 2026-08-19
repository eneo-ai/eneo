"""The AI Builder release gate: fourteen rows and all verdict arithmetic.

This module is the single owner of what a release run must prove. It is pure
domain: no CLI, no file reads, no printing. It takes an already-parsed receipt
(`ai_builder_receipt.Receipt`) plus the matrix state and returns verdicts. The
comparator owns presentation and exit codes; the harness owns acquisition.

Why the split matters: pre-registration. The arithmetic below must be fixed
BEFORE a candidate is measured, or verdict semantics can be chosen after
seeing the result. The row inventory, populations and directions are frozen in
`docs/goals/eneo-flows-and-builder-9-of-10/notes/cp0-matrix-freeze.md` §3 and
the method in `notes/cp8-design-brief.md`; this file is their executable form,
and it is the only place any of those numbers may live.

Two habits are deliberate throughout:

* Eleven of the fourteen rows are exact counts or exact percentiles. A release
  run is a CENSUS of its own receipt, not a sample, so only the three
  proportion rows carry an interval at all.
* Every ceiling is derived from the receipt's own manifest. A ceiling restated
  as a constant is how prose and script drifted apart eleven times in review.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from eneo.flows.ai_builder.ai_builder_critic_invariant_kinds import (
    CRITIC_INVARIANT_KINDS,
)

# These are standalone scripts, not a package: operators run them directly and
# tests load them by path. Neither route puts this directory on the import
# path by itself, and a sibling import is still preferable to three copies of
# the receipt contract.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from ai_builder_receipt import Observation, Receipt  # noqa: E402

JsonObject = dict[str, Any]

Verdict = Literal["pass", "fail", "inconclusive"]

# Repetitions are chosen for instability DETECTION, not precision (CP0
# finding 2). A receipt that ran a different design is not this instrument's
# receipt, so it is invalid rather than scored against a shifted denominator.
RELEASE_REPETITIONS = 5

# Wilson, two-sided 95%.
Z = 1.96

CLARIFICATION_STOP_INTENDED = "clarification_stop_intended"
# "Accepted" is CP0's "plan produced", and the harness already decides that
# from `has_plan` (`ai_builder_api_battle_test.py:5528`): a plan carrying an
# error event is still a plan the user received, so `plan_with_error` is an
# accepted outcome that is not a first pass. Subsetting these classes any
# other way would invent a second definition of acceptance.
ACCEPTED_OUTCOME_CLASSES = frozenset(
    {"plan_first_pass", "plan_repaired", "plan_with_error"}
)
FIRST_PASS_OUTCOME_CLASS = "plan_first_pass"
BUILDER_ERROR_OUTCOME_CLASS = "builder_error"

# The outcome vocabulary this gate knows how to score. An unknown class is not
# silently "not accepted": scoring it would guess, so the receipt is invalid.
KNOWN_OUTCOME_CLASSES = frozenset(
    {
        "plan_first_pass",
        "plan_repaired",
        "plan_with_error",
        "clarification_stop_intended",
        "clarify_ok",
        "stalled_unanswered_question",
        "interaction_limit_reached",
        "requirements_unconfirmed",
        "builder_error",
        "provider_outcome_unknown",
    }
)
SCOREABLE_OBSERVATION_STATUSES = frozenset({"completed", "error_terminated"})

QUESTION_RELEVANCE_CHECK = "first_question_relevance"

# Read from the canonical kinds table, never a list copied into this file.
# The heavy critic evaluator is deliberately NOT imported: it initializes the
# application, and an offline statistics module must run from a receipt alone.
SEMANTIC_INVARIANT_IDS = frozenset(
    invariant_id
    for invariant_id, kind in CRITIC_INVARIANT_KINDS.items()
    if kind == "semantic"
)
ARCHITECTURE_INVARIANT_IDS = frozenset(
    invariant_id
    for invariant_id, kind in CRITIC_INVARIANT_KINDS.items()
    if kind == "architecture"
)

# Proportion targets (CP0 §3).
ACCEPTED_TARGET = 0.95
FIRST_PASS_TARGET = 0.90
CONFORMANCE_TARGET = 0.90

# Ceiling fractions (CP0 §3 rows 3, 8, 9). The counts they produce are always
# derived from the receipt's own populations.
REPAIR_BUDGET_FRACTION = 0.05
MIXED_ACCEPTED_FRACTION = 0.03
MIXED_FIRST_PASS_FRACTION = 0.10
# CP8c's five-percent operator overlay, expressed as exact integer arithmetic.
# One owner avoids a producer and evaluator rounding the same policy differently.
REPLACEMENT_LIMIT_DENOMINATOR = 20

# Cost limits, nearest-rank p95 (CP0 §7).
ELIGIBLE_COST_LIMITS = {"model_calls": 8, "total_tokens": 39_000, "elapsed_ms": 50_000}
ACCEPTED_COST_LIMITS = {"model_calls": 8, "total_tokens": 38_000, "elapsed_ms": 48_000}

MATRIX_STATE_SCHEMA_VERSION = "ai-builder-release-matrix.v1"
MATRIX_ROW_STATES = frozenset({"supported", "removed"})


class ReleaseGateError(ValueError):
    """The gate cannot be evaluated as specified."""


@dataclass(frozen=True, slots=True)
class EvaluatorPin:
    """Where the verdict is being computed, and on which policy.

    Resolved by the CLI, never here: this module reads no files and shells out
    to nothing. Row 14 needs both facts to prove the applied release policy is
    the one that was in the tree when the run was measured.
    """

    revision: str
    evaluator_tree_clean: bool


@dataclass(frozen=True, slots=True)
class MatrixState:
    """Which archetype rows a release verdict may generalize to.

    The gate never reads product source; it reads this tracked declaration.
    The declaration cannot name the revision it was affirmed at — a file
    cannot contain the hash of the commit that contains it — so freshness is
    proved the other way round: the evaluator must be checked out at the
    receipt's own revision with this file clean, which makes the file's git
    history the proof that the policy predates the measurement.
    """

    rows: Mapping[str, str]
    # Pattern ids that are orthogonal modifiers rather than archetype rows —
    # `form_field_runtime_inputs` is one. Declaring them is what lets an
    # UNKNOWN pattern id fail closed: without the list, a newly added cascade
    # row would read as a modifier and vanish from the supported population.
    modifiers: frozenset[str]

    @property
    def supported_rows(self) -> frozenset[str]:
        return frozenset(
            row for row, state in self.rows.items() if state == "supported"
        )

    @property
    def known_rows(self) -> frozenset[str]:
        return frozenset(self.rows)


def matrix_state_from_payload(payload: Any, *, where: str) -> MatrixState:
    if not isinstance(payload, Mapping):
        raise ReleaseGateError(f"{where} must contain a JSON object.")
    state = cast(Mapping[str, Any], payload)
    version = state.get("artifact_schema_version")
    if version != MATRIX_STATE_SCHEMA_VERSION:
        raise ReleaseGateError(
            f"{where}: artifact_schema_version must be "
            f"{MATRIX_STATE_SCHEMA_VERSION}; got {version!r}."
        )
    rows = state.get("rows")
    if not isinstance(rows, Mapping) or not rows:
        raise ReleaseGateError(f"{where}: rows must be a non-empty object.")
    typed_rows: dict[str, str] = {}
    for row, row_state in cast(Mapping[str, Any], rows).items():
        if not row:
            raise ReleaseGateError(f"{where}: every row id must be a non-empty string.")
        if row_state not in MATRIX_ROW_STATES:
            raise ReleaseGateError(
                f"{where}: row {row!r} state must be one of "
                + ", ".join(sorted(MATRIX_ROW_STATES))
            )
        typed_rows[row] = str(row_state)
    if not any(state == "supported" for state in typed_rows.values()):
        raise ReleaseGateError(f"{where}: at least one row must be supported.")
    modifiers = state.get("modifiers")
    if not isinstance(modifiers, Sequence) or isinstance(modifiers, (str, bytes)):
        raise ReleaseGateError(f"{where}: modifiers must be an array.")
    typed_modifiers = frozenset(
        str(modifier) for modifier in cast(Sequence[Any], modifiers)
    )
    overlap = typed_modifiers & set(typed_rows)
    if overlap:
        raise ReleaseGateError(
            f"{where}: {sorted(overlap)} are declared as both rows and modifiers."
        )
    return MatrixState(rows=typed_rows, modifiers=typed_modifiers)


@dataclass(frozen=True, slots=True)
class Interval:
    point: float
    lower: float
    upper: float
    cases: int


@dataclass(frozen=True, slots=True)
class RowVerdict:
    number: int
    name: str
    population: str
    direction: str
    threshold: float
    actual: float
    verdict: Verdict
    gating: bool
    detail: JsonObject

    def as_json(self) -> JsonObject:
        return {
            "row": self.number,
            "name": self.name,
            "population": self.population,
            "direction": self.direction,
            "threshold": self.threshold,
            "actual": self.actual,
            "verdict": self.verdict,
            "gating": self.gating,
            **({"detail": self.detail} if self.detail else {}),
        }


@dataclass(frozen=True, slots=True)
class ReleaseVerdict:
    receipt_valid: bool
    invalidity: tuple[str, ...]
    rows: tuple[RowVerdict, ...]
    release: Literal["go", "no_go", "invalid"]
    trajectory: JsonObject
    diagnostics: JsonObject

    def as_json(self) -> JsonObject:
        return {
            "release": self.release,
            "receipt_valid": self.receipt_valid,
            "invalidity": list(self.invalidity),
            "rows": [row.as_json() for row in self.rows],
            "trajectory": self.trajectory,
            "diagnostics": self.diagnostics,
        }


def wilson_interval(successes: int, attempts: int, *, cases: int) -> Interval:
    """Wilson bounds on the number of CASES, not attempts.

    Outcomes cluster hard by case (CP0 finding 3): 136 of 138 cases succeeding
    in all five repetitions and 2 failing in all five is 98.55% of ATTEMPTS,
    which passes a 95% attempt-level gate that case-level treatment refuses.
    The point estimate stays attempt-level — repetition disagreement is
    evidence, never a vote to be resolved — while the interval is widened to
    the independent unit.
    """

    if attempts <= 0 or cases <= 0:
        raise ReleaseGateError("An interval needs at least one case and one attempt.")
    point = successes / attempts
    n = cases
    centre = (point + Z * Z / (2 * n)) / (1 + Z * Z / n)
    margin = (
        Z * math.sqrt(point * (1 - point) / n + Z * Z / (4 * n * n)) / (1 + Z * Z / n)
    )
    return Interval(
        point=point,
        lower=max(0.0, centre - margin),
        upper=min(1.0, centre + margin),
        cases=cases,
    )


def _proportion_verdict(
    interval: Interval, *, threshold: float, direction: Literal[">=", "<="]
) -> Verdict:
    """Direction-aware: a `<=` metric tested on its lower bound false-passes."""

    bound = interval.lower if direction == ">=" else interval.upper
    point_ok = (
        interval.point >= threshold
        if direction == ">="
        else interval.point <= threshold
    )
    bound_ok = bound >= threshold if direction == ">=" else bound <= threshold
    if point_ok and bound_ok:
        return "pass"
    return "inconclusive" if point_ok else "fail"


def nearest_rank_p95(values: Sequence[int]) -> int:
    """p95 = sorted[ceil(0.95n) - 1] (CP0 §7; floor-rank was off by one)."""

    if not values:
        raise ReleaseGateError("A percentile needs at least one observation.")
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _is_accepted(observation: Observation) -> bool:
    return observation.outcome_class in ACCEPTED_OUTCOME_CLASSES


def _is_first_pass(observation: Observation) -> bool:
    return observation.outcome_class == FIRST_PASS_OUTCOME_CLASS


def _is_eligible(observation: Observation) -> bool:
    return observation.outcome_class != CLARIFICATION_STOP_INTENDED


def _by_case(observations: Iterable[Observation]) -> dict[str, list[Observation]]:
    grouped: dict[str, list[Observation]] = {}
    for observation in observations:
        grouped.setdefault(observation.case_id, []).append(observation)
    return grouped


def replacement_limit(observation_count: int) -> int:
    if isinstance(observation_count, bool) or observation_count < 0:
        raise ReleaseGateError("observation_count must be a non-negative integer.")
    return observation_count // REPLACEMENT_LIMIT_DENOMINATOR


def receipt_invalidity(receipt: Receipt, matrix: MatrixState) -> tuple[str, ...]:
    """Every reason this receipt may not be scored at all.

    Fail-closed and exhaustive: the caller reports all of them at once, because
    a receipt fixed one reason at a time is a receipt being negotiated with.
    """

    reasons: list[str] = []
    if not receipt.integrity_verified:
        # A release verdict is computed from the suite directory, where the
        # manifest and every bundle digest can be re-derived. A bare summary
        # is the measured party's word for its own completeness.
        reasons.append(
            "receipt integrity was never re-derived from the suite directory."
        )
    if receipt.repetitions != RELEASE_REPETITIONS:
        reasons.append(
            f"receipt ran {receipt.repetitions} repetitions; a release run is "
            f"{RELEASE_REPETITIONS}."
        )
    allowed_replacements = replacement_limit(len(receipt.observations))
    if len(receipt.replacements) > allowed_replacements:
        reasons.append(
            f"receipt has {len(receipt.replacements)} operator replacements; at most "
            f"{allowed_replacements} of {len(receipt.observations)} may be "
            "operator re-measurements."
        )
    for observation in receipt.observations:
        unknown_patterns = observation.chosen_patterns - matrix.known_rows
        unknown_patterns -= matrix.modifiers
        if unknown_patterns:
            # An undeclared pattern id is the dangerous case: read as a
            # modifier it would silently drop its observations out of the
            # supported population, and read as a row it would change the
            # partition. Neither guess is allowed.
            reasons.append(
                f"{observation.case_id} r{observation.repetition}: pattern(s) "
                f"{sorted(unknown_patterns)} are declared neither a matrix row "
                "nor a modifier."
            )
        if observation.observation_status not in SCOREABLE_OBSERVATION_STATUSES:
            reasons.append(
                f"{observation.case_id} r{observation.repetition}: "
                f"observation_status {observation.observation_status!r} is an "
                "acquisition fault, not a product outcome."
            )
        if observation.outcome_class not in KNOWN_OUTCOME_CLASSES:
            reasons.append(
                f"{observation.case_id} r{observation.repetition}: unknown "
                f"outcome_class {observation.outcome_class!r}."
            )
        if observation.provider_dispositions:
            # CP0 finding 4: provider faults are not product failures, and a
            # marked receipt must not be scored. Error CODES cannot classify
            # them — product paths also emit `planner_upstream_error`.
            reasons.append(
                f"{observation.case_id} r{observation.repetition}: provider "
                f"disposition {sorted(set(observation.provider_dispositions))} "
                "— re-measure the slot (CP8c) rather than scoring it."
            )
        committed = observation.chosen_patterns & matrix.known_rows
        if len(committed) > 1:
            reasons.append(
                f"{observation.case_id} r{observation.repetition}: committed to "
                f"{sorted(committed)} — matrix rows are mutually exclusive."
            )
    for case_id, observations in sorted(_by_case(receipt.observations).items()):
        repetitions = sorted(item.repetition for item in observations)
        if repetitions != list(range(1, RELEASE_REPETITIONS + 1)):
            reasons.append(
                f"{case_id}: repetitions {repetitions} are not "
                f"1..{RELEASE_REPETITIONS}."
            )
    return tuple(reasons)


def _committed_row(observation: Observation, matrix: MatrixState) -> str | None:
    committed = observation.chosen_patterns & matrix.known_rows
    return next(iter(committed)) if len(committed) == 1 else None


def _required_metric(
    observations: Sequence[Observation], attribute: str, *, row: str
) -> list[int]:
    values: list[int] = []
    for observation in observations:
        value = getattr(observation, attribute)
        if value is None:
            raise ReleaseGateError(
                f"{row}: {observation.case_id} r{observation.repetition} has no "
                f"{attribute}; missing cost evidence is fail-closed."
            )
        values.append(value)
    return values


def _cost_row(
    *,
    number: int,
    name: str,
    population: str,
    observations: Sequence[Observation],
    limits: Mapping[str, int],
) -> RowVerdict:
    measured: JsonObject = {}
    failed: list[str] = []
    for metric, limit in limits.items():
        p95 = nearest_rank_p95(_required_metric(observations, metric, row=name))
        measured[metric] = {"p95": p95, "limit": limit}
        if p95 > limit:
            failed.append(metric)
    return RowVerdict(
        number=number,
        name=name,
        population=population,
        direction="<=",
        threshold=0,
        actual=len(failed),
        verdict="fail" if failed else "pass",
        gating=True,
        detail={"metrics": measured, "over_limit": failed},
    )


def _count_row(
    *,
    number: int,
    name: str,
    population: str,
    actual: int,
    ceiling: int,
    detail: JsonObject | None = None,
) -> RowVerdict:
    return RowVerdict(
        number=number,
        name=name,
        population=population,
        direction="<=",
        threshold=ceiling,
        actual=actual,
        verdict="pass" if actual <= ceiling else "fail",
        gating=True,
        detail=detail or {},
    )


def _proportion_row(
    *,
    number: int,
    name: str,
    population: str,
    successes: int,
    attempts: int,
    cases: int,
    threshold: float,
    gating: bool,
) -> RowVerdict:
    interval = wilson_interval(successes, attempts, cases=cases)
    return RowVerdict(
        number=number,
        name=name,
        population=population,
        direction=">=",
        threshold=threshold,
        actual=interval.point,
        verdict=_proportion_verdict(interval, threshold=threshold, direction=">="),
        gating=gating,
        detail={
            "successes": successes,
            "attempts": attempts,
            "cases": interval.cases,
            "lower_bound": interval.lower,
            "upper_bound": interval.upper,
        },
    )


def _critic_event_counts(
    observations: Iterable[Observation],
) -> tuple[dict[str, int], dict[str, int]]:
    semantic: dict[str, int] = {}
    architecture: dict[str, int] = {}
    for observation in observations:
        for code in (*observation.failure_codes, *observation.ladder_failure_codes):
            if code in SEMANTIC_INVARIANT_IDS:
                semantic[code] = semantic.get(code, 0) + 1
            elif code in ARCHITECTURE_INVARIANT_IDS:
                architecture[code] = architecture.get(code, 0) + 1
    return semantic, architecture


def evaluate_rows(
    receipt: Receipt, matrix: MatrixState, pin: EvaluatorPin
) -> tuple[RowVerdict, ...]:
    """The fourteen rows, in inventory order."""

    observations = receipt.observations
    eligible = [item for item in observations if _is_eligible(item)]
    if not eligible:
        raise ReleaseGateError("A release receipt must contain eligible attempts.")
    intended_stops = [item for item in observations if not _is_eligible(item)]
    all_cases = _by_case(observations)
    # An eligible CASE is one with at least one eligible attempt, and its
    # case-level rows then look at ALL of its repetitions. Restricting them to
    # the eligible subset would let a case that stops as intended in some
    # repetitions and produces a plan in others count as stable in both
    # directions — the disagreement IS the instability rows 6-9 exist to find.
    eligible_cases = {
        case_id: case_observations
        for case_id, case_observations in all_cases.items()
        if any(_is_eligible(item) for item in case_observations)
    }
    accepted = [item for item in eligible if _is_accepted(item)]
    supported = [
        item for item in observations if _committed_row(item, matrix) is not None
    ]

    eligible_case_count = len(eligible_cases)
    repair_ceiling = math.floor(REPAIR_BUDGET_FRACTION * len(eligible))
    mixed_accepted_ceiling = math.floor(MIXED_ACCEPTED_FRACTION * eligible_case_count)
    mixed_first_pass_ceiling = math.floor(
        MIXED_FIRST_PASS_FRACTION * eligible_case_count
    )

    repair_attempts = 0
    for observation in eligible:
        if observation.repair_attempts is None:
            raise ReleaseGateError(
                f"row 3: {observation.case_id} r{observation.repetition} has no "
                "repair_attempts; missing data is fail-closed."
            )
        repair_attempts += observation.repair_attempts

    stable_deaths = sorted(
        case_id
        for case_id, case_observations in eligible_cases.items()
        if all(
            item.outcome_class == BUILDER_ERROR_OUTCOME_CLASS
            for item in case_observations
        )
    )
    stable_non_acceptance = sorted(
        case_id
        for case_id, case_observations in eligible_cases.items()
        if case_id not in stable_deaths
        and not any(_is_accepted(item) for item in case_observations)
    )
    mixed_accepted = sorted(
        case_id
        for case_id, case_observations in eligible_cases.items()
        if 0
        < sum(1 for item in case_observations if _is_accepted(item))
        < len(case_observations)
    )
    mixed_first_pass = sorted(
        case_id
        for case_id, case_observations in eligible_cases.items()
        if 0
        < sum(1 for item in case_observations if _is_first_pass(item))
        < len(case_observations)
    )
    question_relevance_failures = [
        item
        for item in intended_stops
        if QUESTION_RELEVANCE_CHECK in item.failed_check_names
    ]
    semantic_events, architecture_events = _critic_event_counts(supported)

    return (
        _proportion_row(
            number=1,
            name="accepted",
            population="eligible attempts",
            successes=len(accepted),
            attempts=len(eligible),
            cases=eligible_case_count,
            threshold=ACCEPTED_TARGET,
            gating=True,
        ),
        _proportion_row(
            number=2,
            name="first_pass",
            population="eligible attempts",
            successes=sum(1 for item in eligible if _is_first_pass(item)),
            attempts=len(eligible),
            cases=eligible_case_count,
            threshold=FIRST_PASS_TARGET,
            gating=True,
        ),
        _count_row(
            number=3,
            name="repair_attempts",
            population="eligible attempts",
            actual=repair_attempts,
            ceiling=repair_ceiling,
        ),
        _count_row(
            number=4,
            name="builder_errors",
            population="eligible attempts",
            actual=sum(
                1
                for item in eligible
                if item.outcome_class == BUILDER_ERROR_OUTCOME_CLASS
            ),
            ceiling=0,
        ),
        _proportion_row(
            number=5,
            name="expectation_conformance",
            population="all observations",
            successes=sum(
                1 for item in observations if item.expectation_verdict == "pass"
            ),
            attempts=len(observations),
            cases=len(all_cases),
            threshold=CONFORMANCE_TARGET,
            # The user's TRAJECTORY decision: conformance is tracked, not
            # gated. It is computed identically so the trajectory verdict is
            # the same arithmetic, never a softer one.
            gating=False,
        ),
        _count_row(
            number=6,
            name="stable_product_deaths",
            population="eligible cases",
            actual=len(stable_deaths),
            ceiling=0,
            detail={"cases": stable_deaths},
        ),
        _count_row(
            number=7,
            name="stable_non_acceptance",
            population="eligible cases",
            actual=len(stable_non_acceptance),
            ceiling=0,
            detail={"cases": stable_non_acceptance},
        ),
        _count_row(
            number=8,
            name="case_instability_mixed_accepted",
            population="eligible cases",
            actual=len(mixed_accepted),
            ceiling=mixed_accepted_ceiling,
            detail={"cases": mixed_accepted, "eligible_cases": eligible_case_count},
        ),
        _count_row(
            number=9,
            name="case_instability_mixed_first_pass",
            population="eligible cases",
            actual=len(mixed_first_pass),
            ceiling=mixed_first_pass_ceiling,
            detail={"cases": mixed_first_pass, "eligible_cases": eligible_case_count},
        ),
        _count_row(
            number=10,
            name="clarification_question_relevance",
            population="intended stops",
            actual=len(question_relevance_failures),
            ceiling=0,
            detail={
                "observations": sorted(
                    f"{item.case_id} r{item.repetition}"
                    for item in question_relevance_failures
                ),
                "intended_stops": len(intended_stops),
            },
        ),
        _count_row(
            number=11,
            name="normal_path_semantic_critic_events",
            population="supported observations",
            actual=sum(semantic_events.values()),
            ceiling=0,
            detail={
                "semantic_events": semantic_events,
                # Architecture invariants are hard-fatal in create and are a
                # different product question; they are reported, never folded
                # into this row's count.
                "architecture_events": architecture_events,
            },
        ),
        _cost_row(
            number=12,
            name="cost_p95_eligible",
            population="eligible attempts",
            observations=eligible,
            limits=ELIGIBLE_COST_LIMITS,
        ),
        _cost_row(
            number=13,
            name="cost_p95_accepted",
            population="accepted attempts",
            observations=accepted,
            limits=ACCEPTED_COST_LIMITS,
        ),
        _matrix_row(receipt, matrix, pin),
    )


def _matrix_row(receipt: Receipt, matrix: MatrixState, pin: EvaluatorPin) -> RowVerdict:
    """Row 14 — the supported matrix is covered, closed, and policy-pinned.

    The gate never reads product source: the source-side invariant (the branch
    is gone and the tuple rejects) is a product test in the removal slice. What
    is machine-verifiable here is that the policy being applied is the one that
    was in the tree when the run was measured, that every supported row has
    evidence, and that nothing was measured outside the matrix.
    """

    violations: list[str] = []
    if pin.revision != receipt.source_revision:
        violations.append(
            f"the evaluator is at {pin.revision} but the receipt was measured "
            f"at {receipt.source_revision}; check out the measured revision to "
            "judge its receipt."
        )
    if not pin.evaluator_tree_clean:
        # Uncommitted edits to the policy, the arithmetic or the invariant
        # kinds would let the verdict be tuned after seeing the run, which is
        # the one thing pre-registration exists to prevent.
        violations.append("the evaluator has uncommitted tracked changes.")
    cases_by_row: dict[str, set[str]] = {}
    for observation in receipt.observations:
        row = _committed_row(observation, matrix)
        if row is not None:
            cases_by_row.setdefault(row, set()).add(observation.case_id)
    for row in sorted(matrix.supported_rows - set(cases_by_row)):
        violations.append(f"supported row {row} has no case in this receipt.")
    for row in sorted(set(cases_by_row) - matrix.supported_rows):
        violations.append(
            f"row {row} is not supported but "
            f"{len(cases_by_row[row])} case(s) committed to it."
        )
    return RowVerdict(
        number=14,
        name="matrix_state_resolved",
        population="matrix",
        direction="<=",
        threshold=0,
        actual=len(violations),
        verdict="pass" if not violations else "fail",
        gating=True,
        detail={
            "violations": violations,
            "cases_per_row": {
                row: sorted(cases) for row, cases in sorted(cases_by_row.items())
            },
        },
    )


def _conformance_instability(receipt: Receipt) -> JsonObject:
    """Cases whose conformance verdict disagrees with itself.

    Rows 6-9 govern acceptance and first-pass only. CP0 finding 5's worked
    counterexample: every case can first-pass while 31 of 155 fail conformance
    in one repetition of five — every listed row passes and a fifth of the
    corpus is conformance-unstable. Reported alongside row 5 so the trajectory
    cannot be declared complete on an unstable measurement.
    """

    cases = _by_case(receipt.observations)
    # Row 5's own predicate, applied per case: at least one pass and at least
    # one non-pass. Two different FAILURE labels are not instability — the
    # case failed either way.
    unstable = sorted(
        case_id
        for case_id, observations in cases.items()
        if any(item.expectation_verdict == "pass" for item in observations)
        and any(item.expectation_verdict != "pass" for item in observations)
    )
    ceiling = math.floor(MIXED_FIRST_PASS_FRACTION * len(cases))
    return {
        "unstable_cases": unstable,
        "count": len(unstable),
        "ceiling": ceiling,
        "cases": len(cases),
        "within_ceiling": len(unstable) <= ceiling,
    }


def evaluate(
    receipt: Receipt, matrix: MatrixState, pin: EvaluatorPin
) -> ReleaseVerdict:
    invalidity = receipt_invalidity(receipt, matrix)
    diagnostics = _receipt_diagnostics(receipt)
    if invalidity:
        return ReleaseVerdict(
            receipt_valid=False,
            invalidity=invalidity,
            rows=(),
            release="invalid",
            trajectory={},
            diagnostics=diagnostics,
        )
    rows = evaluate_rows(receipt, matrix, pin)
    gating = [row for row in rows if row.gating]
    release = "go" if all(row.verdict == "pass" for row in gating) else "no_go"
    conformance_row = next(row for row in rows if row.number == 5)
    instability = _conformance_instability(receipt)
    return ReleaseVerdict(
        receipt_valid=True,
        invalidity=(),
        rows=rows,
        release=release,
        trajectory={
            "conformance": conformance_row.as_json(),
            "conformance_instability": instability,
            "complete": conformance_row.verdict == "pass"
            and bool(instability["within_ceiling"]),
        },
        diagnostics=diagnostics,
    )


def _receipt_diagnostics(receipt: Receipt) -> JsonObject:
    return {
        "observations": len(receipt.observations),
        "cases": len(receipt.case_ids),
        "source_revision": receipt.source_revision,
        "replacement_count": len(receipt.replacements),
        "replacement_limit": replacement_limit(len(receipt.observations)),
        "replaced_slots": [
            {"case_id": case_id, "repetition": repetition}
            for case_id, repetition in receipt.replaced_slots
        ],
    }


def perfect_receipt(receipt: Receipt) -> Receipt:
    """The same manifest, run flawlessly.

    Intended clarification stops stay stops — a perfect product still asks the
    question its case contract demands — so the populations are preserved and
    the audit measures the gate, not a different corpus.
    """

    observations = tuple(
        Observation(
            case_id=observation.case_id,
            repetition=observation.repetition,
            required=observation.required,
            observation_status="completed",
            case_contract_sha256=observation.case_contract_sha256,
            bundle_file=observation.bundle_file,
            bundle_sha256=observation.bundle_sha256,
            outcome_class=(
                CLARIFICATION_STOP_INTENDED
                if not _is_eligible(observation)
                else FIRST_PASS_OUTCOME_CLASS
            ),
            expectation_verdict="pass",
            failed_check_names=(),
            repair_attempts=0,
            failure_codes=(),
            ladder_failure_codes=(),
            chosen_patterns=observation.chosen_patterns,
            provider_dispositions=(),
            model_calls=0,
            total_tokens=0,
            elapsed_ms=0,
            # Feasibility reads typed fields only. Keeping the measured seal
            # avoids manufacturing a second owner for the observation shape.
            row=observation.row,
        )
        for observation in receipt.observations
    )
    return Receipt(
        artifact_schema_version=receipt.artifact_schema_version,
        artifact_mode=receipt.artifact_mode,
        source_revision=receipt.source_revision,
        repetitions=receipt.repetitions,
        observations=observations,
        integrity_verified=receipt.integrity_verified,
        summary=receipt.summary,
        replacements=receipt.replacements,
    )


def feasibility_audit(
    receipt: Receipt, matrix: MatrixState, pin: EvaluatorPin
) -> JsonObject:
    """A gate a perfect product cannot pass is a broken gate (CP0 finding 1).

    Not hypothetical: expressing builder errors as `<=1% of attempts` is
    unpassable on this corpus, which is why row 4 is an exact zero instead.
    """

    verdict = evaluate(perfect_receipt(receipt), matrix, pin)
    unpassable = [
        row.as_json() for row in verdict.rows if row.gating and row.verdict != "pass"
    ]
    return {
        "feasible": verdict.receipt_valid and not unpassable,
        "invalidity": list(verdict.invalidity),
        "unpassable_rows": unpassable,
    }
