#!/usr/bin/env python3
"""Read AI Builder battle suite receipts: compare two, or judge one for release.

The battle harness answers "what should we improve next" only when run
pairs are comparable. ``compare`` takes two ``suite-summary.json`` receipts
(older first) and reports, per case: the outcome transition, failure-code
and failed-check deltas, question changes, and authoring-token deltas —
then ranks the remaining blockers by family so the next slice is chosen
from evidence instead of memory.

``release-verdict`` answers the other question — is this build releasable —
by rendering the fourteen rows of `ai_builder_release_gate`. This file owns
presentation and exit codes only; not one number is computed here.

Usage:
    ai_builder_battle_compare.py compare BASELINE_SUMMARY CURRENT_SUMMARY
        [--format markdown|json] [--only-changed]
    ai_builder_battle_compare.py release-verdict SUITE_DIR
        [--feasibility] [--format markdown|json]

Receipts carry their own identity (app_version, evaluator_identity). The
report refuses to compare receipts that measure different things — a
different scoring semantics version or a different model — and reports,
without refusing, the identity fields that are expected to differ between
two builds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

# These are standalone scripts, not a package: operators run them directly and
# tests load them by path, so neither route puts this directory on the import
# path by itself.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from ai_builder_receipt import (  # noqa: E402
    ReceiptError,
    load_release_receipt,
    load_summary_receipt,
    receipt_membership_report,
    require_bundle_identity,
)
from ai_builder_release_gate import (  # noqa: E402
    EvaluatorPin,
    ReleaseGateError,
    evaluate,
    feasibility_audit,
    matrix_state_from_payload,
)

DEFAULT_MATRIX_STATE = (
    Path(__file__).resolve().with_name("ai_builder_release_matrix_state.json")
)

# Better outcomes rank higher; a transition to a higher rank is an
# improvement. Ties are "changed" but neither improved nor regressed.
# Every outcome class the harness can emit must appear here: a class that
# falls through ranks below everything, so provider_outcome_unknown ->
# builder_error once reported as a mechanics improvement. A test cross-checks
# this map against the harness source.
_OUTCOME_RANK: dict[str, int] = {
    "plan_first_pass": 6,
    "clarification_stop_intended": 5,
    "clarify_ok": 5,
    "plan_repaired": 4,
    "stalled_unanswered_question": 3,
    "interaction_limit_reached": 2,
    "requirements_unconfirmed": 2,
    "plan_with_error": 2,
    "builder_error": 1,
    "acquisition_failure": 1,
    "execution_failure": 1,
    "invalid_evidence": 0,
    "unclassified": 0,
}


def _load_rows(path: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Group every repetition per case.

    Discarding all but the last repetition threw away the only evidence that
    distinguishes a real change from proposal variance — and that variance is
    large: 36 of 122 cases changed outcome between two runs of neighbouring
    builds (2026-08-06). Callers decide how to summarize; nothing is dropped
    here.

    Reading is fail-closed and owned by `ai_builder_receipt`: this loader used
    to skip any row it could not read, so a truncated receipt compared as a
    smaller, healthier run.
    """

    receipt = load_summary_receipt(path)
    rows: dict[str, list[dict[str, Any]]] = {}
    for observation in receipt.observations:
        rows.setdefault(observation.case_id, []).append(dict(observation.row))
    for case_rows in rows.values():
        case_rows.sort(key=lambda item: item.get("repetition") or 0)
    return rows, dict(receipt.summary)


def _failure_codes(row: dict[str, Any]) -> tuple[str, ...]:
    """Every code that names why a case did not succeed.

    Receipts carry two disjoint vocabularies: `error_codes` is the public API
    error contract, `failure_codes` the internal failure observability nested
    inside it. Counting only the internal one printed an empty blocker
    ranking for a run in which 8 cases errored, because a router-level
    refusal carries no internal detail (verified on the 9216ec6 receipt).
    """

    failure_summary = cast(dict[str, Any], row.get("failure_summary") or {})
    codes = [
        code
        for key in ("failure_codes", "error_codes")
        for code in cast(list[Any], failure_summary.get(key) or [])
        if isinstance(code, str) and code
    ]
    return tuple(sorted(set(codes)))


def _failed_check_names(row: dict[str, Any]) -> tuple[str, ...]:
    checks = cast(list[Any], row.get("failed_checks") or [])
    return tuple(
        sorted(
            str(cast(dict[str, Any], check).get("name", "?"))
            for check in checks
            if isinstance(check, dict)
        )
    )


def _question_ids(row: dict[str, Any]) -> tuple[str, ...]:
    journey = cast(dict[str, Any], row.get("journey") or {})
    return tuple(cast(list[str], journey.get("question_event_ids") or []))


def _authoring_tokens(row: dict[str, Any]) -> int | None:
    usage = cast(dict[str, Any], row.get("authoring_usage") or {})
    value = usage.get("total_tokens") or usage.get("total_tokens_total")
    return value if isinstance(value, int) else None


def _repair_economics(row: dict[str, Any]) -> dict[str, Any] | None:
    journey = cast(dict[str, Any], row.get("journey") or {})
    plan_outcome = cast(dict[str, Any], journey.get("plan_outcome") or {})
    repair_cost = plan_outcome.get("repair_token_cost")
    if not isinstance(repair_cost, int):
        return None
    ladder = cast(Any, plan_outcome.get("attempt_failure_ladder"))
    failure_codes: list[str] = []
    if isinstance(ladder, list):
        for attempt in cast(list[Any], ladder):
            if not isinstance(attempt, dict):
                continue
            codes = cast(Any, cast(dict[str, Any], attempt).get("failure_codes"))
            if isinstance(codes, list):
                failure_codes.extend(
                    code for code in cast(list[Any], codes) if isinstance(code, str)
                )
    return {"repair_token_cost": repair_cost, "attempt_failure_codes": failure_codes}


def _conformance_direction(before_verdict: str, after_verdict: str) -> str:
    """Direction of the primary quality metric: does the plan satisfy the case.

    `not_evaluated` is not a midpoint between pass and fail — a case that
    stops being evaluated has not improved or regressed, it has left the
    measurement.
    """

    if before_verdict == after_verdict:
        return "unchanged"
    if "not_evaluated" in (before_verdict, after_verdict):
        return "evaluation_changed"
    if before_verdict == "fail" and after_verdict == "pass":
        return "improved"
    if before_verdict == "pass" and after_verdict == "fail":
        return "regressed"
    return "changed"


def _mechanics_direction(
    baseline: dict[str, Any] | None,
    current: dict[str, Any] | None,
    before: str,
    after: str,
) -> str:
    """How the proposal was produced — repairs, stalls, errors.

    Secondary to conformance: a plan can cost fewer repairs and still fail
    the case, or cost more and satisfy it.
    """

    if baseline is None or current is None:
        return "coverage_changed"
    before_rank = _OUTCOME_RANK.get(before, -1)
    after_rank = _OUTCOME_RANK.get(after, -1)
    if after_rank > before_rank:
        return "improved"
    if after_rank < before_rank:
        return "regressed"
    return "changed" if before != after else "unchanged"


def _case_delta(
    case_id: str,
    baseline: dict[str, Any] | None,
    current: dict[str, Any] | None,
    *,
    baseline_repetitions: list[dict[str, Any]] | None = None,
    current_repetitions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    before = str((baseline or {}).get("outcome_class") or "absent")
    after = str((current or {}).get("outcome_class") or "absent")
    before_verdict = str((baseline or {}).get("expectation_verdict") or "absent")
    after_verdict = str((current or {}).get("expectation_verdict") or "absent")

    # Instability is a property of ONE build disagreeing with itself. Judging
    # it from the union of both builds would brand every real, consistent
    # A -> B change unstable.
    baseline_states = _observed_states(baseline_repetitions)
    current_states = _observed_states(current_repetitions)
    unstable = len(baseline_states) > 1 or len(current_states) > 1

    # Product direction is conformance. Reading it off `outcome_class`
    # reported a case that stopped satisfying its rubric as "unchanged"
    # whenever its mechanics held — the exact regression the no-regression
    # rule exists to catch. Mechanics are still reported, separately.
    if baseline is None or current is None:
        direction = "coverage_changed"
    elif unstable:
        # A build that disagrees with itself cannot supply a direction; the
        # modal row would promote one repetition to a verdict.
        direction = "inconclusive"
    else:
        direction = _conformance_direction(before_verdict, after_verdict)

    delta: dict[str, Any] = {
        "case_id": case_id,
        "direction": direction,
        "conformance": f"{before_verdict} -> {after_verdict}",
        "mechanics_direction": _mechanics_direction(baseline, current, before, after),
        "outcome": f"{before} -> {after}",
    }
    if len(baseline_states) > 1:
        delta["baseline_unstable"] = True
        delta["baseline_observed_states"] = sorted(baseline_states)
    if len(current_states) > 1:
        delta["current_unstable"] = True
        delta["current_observed_states"] = sorted(current_states)
    if baseline is not None and current is not None:
        before_codes = _failure_codes(baseline)
        after_codes = _failure_codes(current)
        if before_codes != after_codes:
            delta["failure_codes"] = {
                "resolved": sorted(set(before_codes) - set(after_codes)),
                "introduced": sorted(set(after_codes) - set(before_codes)),
            }
        before_checks = _failed_check_names(baseline)
        after_checks = _failed_check_names(current)
        if before_checks != after_checks:
            delta["failed_checks"] = {
                "resolved": sorted(set(before_checks) - set(after_checks)),
                "introduced": sorted(set(after_checks) - set(before_checks)),
            }
        if _question_ids(baseline) != _question_ids(current):
            delta["questions"] = {
                "before": list(_question_ids(baseline)),
                "after": list(_question_ids(current)),
            }
        before_tokens = _authoring_tokens(baseline)
        after_tokens = _authoring_tokens(current)
        if before_tokens is not None and after_tokens is not None:
            delta["authoring_tokens"] = {
                "before": before_tokens,
                "after": after_tokens,
                "delta": after_tokens - before_tokens,
            }
        before_repairs = _repair_economics(baseline)
        after_repairs = _repair_economics(current)
        if before_repairs is not None or after_repairs is not None:
            repair_delta: dict[str, Any] = {
                "before": before_repairs,
                "after": after_repairs,
            }
            if before_repairs is not None and after_repairs is not None:
                repair_delta["delta"] = (
                    after_repairs["repair_token_cost"]
                    - before_repairs["repair_token_cost"]
                )
            delta["repair_economics"] = repair_delta
    return delta


def _identity(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "app_version": summary.get("app_version"),
        "case_count": summary.get("case_count"),
        "created_at": summary.get("created_at"),
        "evaluator_identity": summary.get("evaluator_identity"),
    }


# Identity fields that change what a score *means*. Two receipts that differ
# on any of these are different experiments, so comparing them is refused.
# The instrument (`harness_sha256`) is gated too: a harness edit can change
# how expectations are evaluated without touching either semantics version.
# `--allow-harness-change` waives only that hash identity when scoring changes
# are confined to cases whose contract hashes also changed; those rescored
# cases are excluded from direction counts.
#
# Deliberately excluded, with evidence: `target_sha256` embeds the deployed
# app version and so differs between every pair of builds — the exact axis
# this tool exists to compare (verified on the 9d4237a/9216ec6 receipts).
# The full `evaluator_identity.sha256` differs for the same reason. The
# environment half of the target is gated separately as `base_url`, which
# the receipt carries in the clear. `cases_sha256` stays nonfatal only
# because `case_contract_sha256_by_id` compares the corpus per case, so
# editing one case's expectations does not block comparing the other 121.
_IDENTITY_FIELDS: tuple[str, ...] = (
    "question_relevance_semantics_version",
    "outcome_classification_semantics_version",
    "observation_input_identity_semantics_version",
    "requested_model_id",
    "harness_sha256",
)

# Run-context fields that change what the builder was asked to do. Sample
# size (`repetitions`) is deliberately absent: it changes confidence, not
# behavior. `max_concurrency` is present for the opposite reason — parallel
# sessions share provider capacity, and provider_outcome_unknown already
# accounts for 3-5 cases per pass. Until someone measures whether that rate
# moves with load, receipts taken at different concurrency are different
# experiments. Per-case scheduling and Flow isolation are gated because older
# harnesses let repeated observations contend with persistent applied Flows.
_GATED_RUN_CONTEXT_FIELDS: tuple[str, ...] = (
    "auto_confirm_requirements",
    "confirm_message_sha256",
    "max_concurrency",
    "max_concurrent_observations_per_case",
    "flow_isolation_semantics_version",
    "ui_language",
)

# Differences here are expected and reported, never fatal.
_REPORTED_IDENTITY_FIELDS: tuple[str, ...] = (
    "cases_sha256",
    "source_revision",
    "target_sha256",
)


def _evaluator_identity(summary: dict[str, Any]) -> dict[str, Any]:
    identity = summary.get("evaluator_identity")
    return cast(dict[str, Any], identity) if isinstance(identity, dict) else {}


def _identity_marker(summary: dict[str, Any]) -> dict[str, Any]:
    """Comparability key drawn from the receipt's own evaluator identity."""

    typed_identity = _evaluator_identity(summary)
    return {field: typed_identity.get(field) for field in _IDENTITY_FIELDS}


def _reported_identity_differences(
    baseline_summary: dict[str, Any],
    current_summary: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Identity fields that differ without making receipts incomparable.

    An undeclared harness or corpus change is the one thing a reader must be
    able to see: it means the instrument moved while its declared semantics
    claimed it had not.
    """

    baseline_identity = _evaluator_identity(baseline_summary)
    current_identity = _evaluator_identity(current_summary)
    return {
        field: {
            "baseline": baseline_identity.get(field),
            "current": current_identity.get(field),
        }
        for field in _REPORTED_IDENTITY_FIELDS
        if baseline_identity.get(field) != current_identity.get(field)
    }


def _run_context(summary: dict[str, Any]) -> dict[str, Any]:
    raw = _evaluator_identity(summary).get("run_context")
    if not isinstance(raw, dict):
        raw = summary.get("run_context")
    return cast(dict[str, Any], raw) if isinstance(raw, dict) else {}


def _incompatible_identity_fields(
    baseline_summary: dict[str, Any],
    current_summary: dict[str, Any],
    *,
    allow_harness_change: bool = False,
) -> list[str]:
    """Fields that make two receipts incomparable, plus any that are absent.

    A missing field must fail closed. Treating absence as a match let two
    receipts that recorded no model, no harness, and no semantics version
    compare as though they agreed on all three.
    """

    baseline_marker = _identity_marker(baseline_summary)
    current_marker = _identity_marker(current_summary)
    baseline_context = _run_context(baseline_summary)
    current_context = _run_context(current_summary)
    incompatible: list[str] = []
    for field in _IDENTITY_FIELDS:
        if field == "harness_sha256" and allow_harness_change:
            continue
        before, after = baseline_marker[field], current_marker[field]
        if before is None or after is None:
            incompatible.append(f"{field} (missing)")
        elif before != after:
            incompatible.append(field)
    for field in _GATED_RUN_CONTEXT_FIELDS:
        before, after = baseline_context.get(field), current_context.get(field)
        if before is None or after is None:
            incompatible.append(f"run_context.{field} (missing)")
        elif before != after:
            incompatible.append(f"run_context.{field}")
    if baseline_summary.get("base_url") != current_summary.get("base_url"):
        incompatible.append("base_url")
    return incompatible


def _case_contract_changes(
    baseline_summary: dict[str, Any],
    current_summary: dict[str, Any],
) -> list[str]:
    def contracts(summary: dict[str, Any]) -> dict[str, Any]:
        raw = _evaluator_identity(summary).get("case_contract_sha256_by_id")
        return cast(dict[str, Any], raw) if isinstance(raw, dict) else {}

    baseline_contracts = contracts(baseline_summary)
    current_contracts = contracts(current_summary)
    return sorted(
        case_id
        for case_id in set(baseline_contracts) & set(current_contracts)
        if baseline_contracts[case_id] != current_contracts[case_id]
    )


def compare(
    baseline_path: Path,
    current_path: Path,
    *,
    allow_harness_change: bool = False,
    noise_margin: int | None = None,
) -> dict[str, Any]:
    baseline_rows, baseline_summary = _load_rows(baseline_path)
    current_rows, current_summary = _load_rows(current_path)
    incompatible = _incompatible_identity_fields(
        baseline_summary,
        current_summary,
        allow_harness_change=allow_harness_change,
    )
    if incompatible:
        raise SystemExit(
            "Refusing to compare receipts whose evaluator identity differs on "
            f"{', '.join(incompatible)}; they do not measure the same thing. "
            "Pass --allow-harness-change only when scoring-affecting harness "
            "edits are confined to cases with changed contract hashes. "
            f"baseline={_identity_marker(baseline_summary)!r} "
            f"current={_identity_marker(current_summary)!r}"
        )
    rescored_cases = _case_contract_changes(baseline_summary, current_summary)
    identity_differences = _reported_identity_differences(
        baseline_summary, current_summary
    )

    case_ids = sorted(set(baseline_rows) | set(current_rows))
    deltas = [
        {
            **_case_delta(
                case_id,
                _representative_row(baseline_rows.get(case_id)),
                _representative_row(current_rows.get(case_id)),
                baseline_repetitions=baseline_rows.get(case_id) or [],
                current_repetitions=current_rows.get(case_id) or [],
            ),
            "cohorts": _cohorts(current_rows.get(case_id))
            or _cohorts(baseline_rows.get(case_id)),
        }
        for case_id in case_ids
    ]
    # A case whose expectations were edited moved because the question
    # changed, not because the product did. Counting it as product movement
    # is how a rubric correction gets reported as a win.
    rescored = set(rescored_cases)
    directions: Counter[str] = Counter(
        str(delta["direction"]) for delta in deltas if delta["case_id"] not in rescored
    )
    mechanics_directions: Counter[str] = Counter(
        str(delta["mechanics_direction"])
        for delta in deltas
        if delta["case_id"] not in rescored
    )
    # Failed checks and blockers count distinct cases, not observations, so
    # repetitions cannot inflate a cluster.
    remaining_blockers = Counter(
        code
        for case_rows in current_rows.values()
        for code in {code for row in case_rows for code in _failure_codes(row)}
    )
    # A check a case fails in any repetition counts once for that case. Reading
    # it off the representative row instead would hide every check that only
    # some repetitions fail.
    remaining_failed_checks = Counter(
        name
        for case_rows in current_rows.values()
        for name in {name for row in case_rows for name in _failed_check_names(row)}
    )
    outcome_counts = Counter(
        row.get("outcome_class") or "unknown"
        for case_rows in current_rows.values()
        for row in case_rows
    )
    unstable = {
        "baseline": [
            delta["case_id"]
            for delta in deltas
            if delta.get("baseline_unstable") is True
        ],
        "current": [
            delta["case_id"]
            for delta in deltas
            if delta.get("current_unstable") is True
        ],
    }
    # The no-regression rule needs names. A count tells a reader something got
    # worse; only the list tells them what to go and look at.
    conformance_regressions = [
        delta["case_id"] for delta in deltas if delta["direction"] == "regressed"
    ]
    conformance_improvements = [
        delta["case_id"] for delta in deltas if delta["direction"] == "improved"
    ]
    return {
        "baseline": _identity(baseline_summary),
        "current": _identity(current_summary),
        "rescored_cases": rescored_cases,
        "identity_differences": identity_differences,
        "verdict": _verdict(
            dict(directions),
            noise_margin=noise_margin,
            baseline_summary=baseline_summary,
            current_summary=current_summary,
        ),
        "evidence": _evidence_strength(baseline_summary, current_summary),
        "direction_counts": dict(directions),
        "direction_counts_by_cohort": _cohort_directions(deltas, rescored),
        "conformance_regressed_cases": conformance_regressions,
        "conformance_improved_cases": conformance_improvements,
        "attachment_evidence_changes": _attachment_evidence_changes(
            baseline_rows, current_rows
        ),
        "mechanics_direction_counts": dict(mechanics_directions),
        "current_outcomes": dict(outcome_counts),
        "remaining_blockers_ranked": remaining_blockers.most_common(),
        "remaining_failed_checks_ranked": remaining_failed_checks.most_common(),
        "unstable_cases": unstable,
        "cases": deltas,
    }


def _cohorts(rows: list[dict[str, Any]] | None) -> tuple[str, ...]:
    for row in rows or []:
        cohorts = row.get("cohorts")
        if isinstance(cohorts, list):
            return tuple(
                cohort for cohort in cast(list[Any], cohorts) if isinstance(cohort, str)
            )
    return ()


def _cohort_directions(
    deltas: list[dict[str, Any]],
    rescored: set[str],
) -> dict[str, dict[str, int]]:
    """Conformance direction per cohort.

    A change usually targets one mechanism. Judging it on all 122 cases buries
    a real cohort move under the rest of the corpus, and judging it on the
    targeted cohort alone hides collateral damage — so report every cohort and
    let the reader use the untargeted ones as negative controls.
    """

    by_cohort: dict[str, Counter[str]] = {}
    for delta in deltas:
        if delta["case_id"] in rescored:
            continue
        for cohort in cast(tuple[str, ...], delta.get("cohorts") or ()):
            by_cohort.setdefault(cohort, Counter())[delta["direction"]] += 1
    return {
        cohort: dict(sorted(counts.items()))
        for cohort, counts in sorted(by_cohort.items())
    }


def _verdict(
    directions: dict[str, int],
    *,
    noise_margin: int | None,
    baseline_summary: dict[str, Any],
    current_summary: dict[str, Any],
) -> dict[str, Any]:
    """Answer the only question a baseline exists to answer.

    The margin is an input, never a default. Choosing it from the result is
    how a noise-sized move becomes a claimed win, so an undeclared margin
    yields no verdict at all — the counts still print, and the reader still
    sees exactly which cases moved.

    The margin was calibrated on repetition-to-repetition movement of runs
    with one design. Comparing a repeated baseline against a single-run
    candidate measures a different quantity — modal states with dropped
    unstable cases against raw observations — so a mismatched design gets
    no verdict either, rather than a false negative dressed as one.
    """

    improved = directions.get("improved", 0)
    regressed = directions.get("regressed", 0)
    net = improved - regressed
    baseline_reps = _run_context(baseline_summary).get("repetitions")
    current_reps = _run_context(current_summary).get("repetitions")
    design_matched = (
        isinstance(baseline_reps, int)
        and isinstance(current_reps, int)
        and baseline_reps == current_reps
    )
    if noise_margin is None:
        answer = "margin_not_declared"
    elif not design_matched:
        answer = "inconclusive_design_mismatch"
    elif net > noise_margin:
        answer = "improved"
    elif -net > noise_margin:
        answer = "regressed"
    else:
        answer = "no_measurable_change"
    return {
        "answer": answer,
        "net_conformance_delta": net,
        "improved": improved,
        "regressed": regressed,
        "noise_margin": noise_margin,
        "baseline_repetitions": baseline_reps,
        "current_repetitions": current_reps,
    }


def _evidence_strength(
    baseline_summary: dict[str, Any],
    current_summary: dict[str, Any],
) -> dict[str, Any]:
    """How much weight the per-case directions can carry.

    One repetition per build cannot distinguish a real change from proposal
    variance; the instability gate stays silent because a single observation
    never disagrees with itself. Saying so is the difference between a
    baseline and a coin flip that looks like one.
    """

    baseline_reps = _run_context(baseline_summary).get("repetitions")
    current_reps = _run_context(current_summary).get("repetitions")
    repeated = (
        isinstance(baseline_reps, int)
        and isinstance(current_reps, int)
        and baseline_reps > 1
        and current_reps > 1
    )
    return {
        "baseline_repetitions": baseline_reps,
        "current_repetitions": current_reps,
        "kind": "repeated" if repeated else "single_observation",
        "note": (
            "Both builds repeated; per-case instability is measured."
            if repeated
            else (
                "At least one build ran a single repetition, so no case-level "
                "state is confirmed stable and every direction below is one "
                "observation against one observation."
            )
        ),
    }


def _attachment_evidence_changes(
    baseline_rows: dict[str, list[dict[str, Any]]],
    current_rows: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Fixtures whose extracted text changed between the two builds.

    Fixture bytes are pinned in git and verified before upload, so a moved
    digest here means the product now reads the same document differently —
    a finding, not a fixture problem, and one a hand-captured constant used to
    turn into a stale-looking failure instead.
    """

    def digests(rows: dict[str, list[dict[str, Any]]]) -> dict[str, set[str]]:
        found: dict[str, set[str]] = {}
        for case_rows in rows.values():
            for row in case_rows:
                identity = row.get("observation_input_identity")
                if not isinstance(identity, dict):
                    continue
                typed = cast(dict[str, Any], identity)
                fixtures = cast(list[Any], typed.get("attachment_fixtures") or [])
                observed = cast(
                    list[Any], typed.get("attachment_evidence_sha256s") or []
                )
                for fixture, digest in zip(fixtures, observed, strict=False):
                    if isinstance(fixture, dict) and isinstance(digest, str):
                        name = cast(dict[str, Any], fixture).get("name")
                        if isinstance(name, str):
                            found.setdefault(name, set()).add(digest)
        return found

    baseline_digests = digests(baseline_rows)
    current_digests = digests(current_rows)
    return [
        {
            "fixture": name,
            "baseline": sorted(baseline_digests[name]),
            "current": sorted(current_digests[name]),
        }
        for name in sorted(set(baseline_digests) & set(current_digests))
        if baseline_digests[name] != current_digests[name]
    ]


def _observed_states(rows: list[dict[str, Any]] | None) -> set[str]:
    """Distinct (mechanics, conformance) states one build produced for a case.

    Outcome alone hides the state that matters: two repetitions can both be
    `plan_first_pass` while one satisfies the case and the other does not.
    """

    return {
        f"{row.get('outcome_class') or 'unknown'}/"
        f"{row.get('expectation_verdict') or 'unknown'}"
        for row in rows or []
    }


def _representative_row(
    case_rows: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Pick the modal outcome's row so one unlucky repetition cannot decide.

    With a single repetition this is the row itself; with several it is the
    most frequently observed outcome, which is what a comparison should
    report for a stochastic proposal step.
    """

    if not case_rows:
        return None
    if len(case_rows) == 1:
        return case_rows[0]
    modal_outcome = Counter(
        row.get("outcome_class") or "unknown" for row in case_rows
    ).most_common(1)[0][0]
    for row in case_rows:
        if (row.get("outcome_class") or "unknown") == modal_outcome:
            return row
    return case_rows[-1]


def _render_markdown(report: dict[str, Any], *, only_changed: bool) -> str:
    lines: list[str] = []
    baseline = cast(dict[str, Any], report["baseline"])
    current = cast(dict[str, Any], report["current"])
    lines.append(
        f"# Battle suite delta: {baseline.get('app_version')} -> "
        f"{current.get('app_version')}"
    )
    lines.append("")
    verdict = cast(dict[str, Any], report["verdict"])
    evidence = cast(dict[str, Any], report["evidence"])
    lines.append(
        f"## Did this change help? **{verdict['answer']}** "
        f"(net conformance {verdict['net_conformance_delta']:+d}: "
        f"{verdict['improved']} improved, {verdict['regressed']} regressed; "
        f"declared margin {verdict['noise_margin']})"
    )
    if verdict["answer"] == "margin_not_declared":
        lines.append(
            "  No verdict: pass --noise-margin with a margin chosen *before* "
            "this run. Choosing it now is how a noise-sized move becomes a "
            "claimed win."
        )
    elif verdict["answer"] == "inconclusive_design_mismatch":
        lines.append(
            f"  No verdict: baseline ran "
            f"{verdict['baseline_repetitions']} repetition(s) and current "
            f"{verdict['current_repetitions']}; the margin is only valid "
            "between runs of the same design. Re-run the candidate with the "
            "baseline's repetition count."
        )
    lines.append(f"Evidence: {evidence['kind']} — {evidence['note']}")
    lines.append("")
    lines.append(f"Conformance direction (primary): {report['direction_counts']}")
    lines.append(f"Mechanics direction: {report['mechanics_direction_counts']}")
    lines.append(f"Current outcomes: {report['current_outcomes']}")
    lines.append("")
    regressed = cast(list[str], report["conformance_regressed_cases"])
    if regressed:
        lines.append("## Conformance regressions (the no-regression rule)")
        lines.extend(f"- {case_id}" for case_id in regressed)
        lines.append("")
    by_cohort = cast(dict[str, dict[str, int]], report["direction_counts_by_cohort"])
    if by_cohort:
        lines.append("## Conformance direction by cohort")
        for cohort, counts in by_cohort.items():
            net = counts.get("improved", 0) - counts.get("regressed", 0)
            lines.append(f"- {cohort}: {net:+d} net; {counts}")
        lines.append("")
    fixture_changes = cast(list[dict[str, Any]], report["attachment_evidence_changes"])
    if fixture_changes:
        lines.append(
            "## Fixture extraction changed (same git-pinned bytes, different "
            "extracted text — a product change, not a fixture problem)"
        )
        for change in fixture_changes:
            lines.append(
                f"- {change['fixture']}: {change['baseline']} -> {change['current']}"
            )
        lines.append("")
    unstable = cast(dict[str, list[str]], report["unstable_cases"])
    if unstable["baseline"] or unstable["current"]:
        lines.append("## Unstable cases (a build disagreed with itself; no direction)")
        for build in ("baseline", "current"):
            if unstable[build]:
                lines.append(f"- {build}: {', '.join(unstable[build])}")
        lines.append("")
    differences = cast(dict[str, Any], report["identity_differences"])
    if differences:
        lines.append(
            "Identity differences (expected between builds; an undeclared "
            f"harness or corpus change would show here): {sorted(differences)}"
        )
        lines.append("")
    rescored = cast(list[str], report["rescored_cases"])
    if rescored:
        lines.append(
            f"Rescored cases (expectations edited, delta is not product "
            f"movement): {', '.join(rescored)}"
        )
        lines.append("")
    for heading, key in (
        ("Remaining blockers", "remaining_blockers_ranked"),
        ("Remaining failed checks", "remaining_failed_checks_ranked"),
    ):
        lines.append(f"## {heading} (ranked, by distinct case)")
        ranked = cast(list[tuple[str, int]], report[key])
        # An empty section rendered as nothing reads as "none found" whether
        # or not anything was counted; say it.
        lines.extend(f"- {count}x {name}" for name, count in ranked)
        if not ranked:
            lines.append("- (none)")
        lines.append("")
    lines.append("## Per-case transitions")
    for delta in report["cases"]:
        # An unstable case is never "unchanged" — suppressing it would hide
        # the cases whose measurement cannot be trusted.
        suppressed = delta["direction"] == "unchanged" and not (
            delta.get("baseline_unstable") or delta.get("current_unstable")
        )
        if only_changed and suppressed:
            continue
        lines.append(
            f"- **{delta['case_id']}** [{delta['direction']}] "
            f"conformance {delta['conformance']}; "
            f"mechanics [{delta['mechanics_direction']}] {delta['outcome']}"
        )
        for key in (
            "baseline_observed_states",
            "current_observed_states",
            "failure_codes",
            "failed_checks",
            "questions",
            "authoring_tokens",
            "repair_economics",
        ):
            if key in delta:
                lines.append(f"  - {key}: {json.dumps(delta[key], ensure_ascii=False)}")
    return "\n".join(lines)


def _git(*arguments: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *arguments],
        capture_output=True,
        text=True,
        cwd=cwd,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def evaluator_pin() -> EvaluatorPin:
    """Where this verdict is being computed, and whether the evaluator is frozen.

    The release policy cannot name the commit that contains it, so freshness is
    proved from the other side: the evaluator must be checked out at the
    receipt's own revision with NO uncommitted tracked changes. Checking only
    the policy file would leave the arithmetic and the invariant kinds free to
    change after the run was seen, which is the same false-green by a longer
    route.
    """

    directory = DEFAULT_MATRIX_STATE.resolve().parent
    return EvaluatorPin(
        revision=_git("rev-parse", "HEAD", cwd=directory),
        evaluator_tree_clean=not _git(
            "status", "--porcelain", "--untracked-files=no", cwd=directory
        ),
    )


def release_verdict_report(
    suite_dir: Path,
    *,
    pin: EvaluatorPin,
    feasibility: bool = False,
) -> dict[str, Any]:
    """Judge one suite directory. Every number below is the gate module's.

    The policy is the tracked canonical file, never an operator-supplied path:
    a `--matrix-state` flag is a way to hand the gate a friendlier, untracked
    set of supported rows after seeing the run.
    """

    matrix_state_path = DEFAULT_MATRIX_STATE
    receipt = load_release_receipt(suite_dir)
    matrix = matrix_state_from_payload(
        json.loads(matrix_state_path.read_text(encoding="utf-8")),
        where=str(matrix_state_path),
    )
    report = evaluate(receipt, matrix, pin).as_json()
    report["suite_dir"] = str(suite_dir)
    report["matrix_state"] = str(matrix_state_path)
    report["evaluator_revision"] = pin.revision
    if feasibility:
        report["feasibility"] = feasibility_audit(receipt, matrix, pin)
    return report


def _render_release_markdown(report: dict[str, Any]) -> str:
    release = cast(str, report["release"])
    lines = [f"# Release verdict: **{release.upper()}**", ""]
    diagnostics = cast(dict[str, Any], report.get("diagnostics") or {})
    replacement_count = diagnostics.get("replacement_count")
    replacement_limit_value = diagnostics.get("replacement_limit")
    if isinstance(replacement_count, int) and isinstance(replacement_limit_value, int):
        lines.append(
            f"Operator re-measurements: {replacement_count} / "
            f"{replacement_limit_value} allowed slots."
        )
        lines.append("")
    invalidity = cast(list[str], report["invalidity"])
    if invalidity:
        lines.append(
            "## The receipt cannot be scored (fail-closed; every reason at once)"
        )
        lines.extend(f"- {reason}" for reason in invalidity)
        lines.append("")
        return "\n".join(lines)
    lines.append("## Gate rows")
    for row in cast(list[dict[str, Any]], report["rows"]):
        scope = "gating" if row["gating"] else "reported"
        lines.append(
            f"- [{row['verdict'].upper()}] row {row['row']} {row['name']} "
            f"({scope}, {row['population']}): {row['actual']} "
            f"{row['direction']} {row['threshold']}"
        )
        detail = row.get("detail")
        if detail:
            lines.append(f"  - {json.dumps(detail, ensure_ascii=False)}")
    trajectory = cast(dict[str, Any], report["trajectory"])
    lines.append("")
    lines.append(
        f"## Conformance trajectory: complete={trajectory['complete']}"
        if trajectory
        else "## Conformance trajectory: not evaluated"
    )
    if trajectory:
        lines.append(
            f"- {json.dumps(trajectory['conformance_instability'], ensure_ascii=False)}"
        )
    feasibility = cast(dict[str, Any] | None, report.get("feasibility"))
    if feasibility is not None:
        lines.append("")
        lines.append(f"## Feasibility audit: feasible={feasibility['feasible']}")
        # A gate a perfect product cannot pass is a plan defect, not a product
        # failure, and it must be named as such before anyone tries to fix the
        # product to satisfy it.
        for row in cast(list[dict[str, Any]], feasibility["unpassable_rows"]):
            lines.append(f"- UNPASSABLE row {row['row']} {row['name']}")
        for reason in cast(list[str], feasibility["invalidity"]):
            lines.append(f"- receipt invalid under a perfect run: {reason}")
    return "\n".join(lines)


_INVALID_RECEIPT_EXIT = 2

# The token baseline reads only observations the product completed. Acquisition
# faults never spent a first attempt on the product's behalf, and a turn from
# an error-terminated bundle would credit a failure with a token cost.
TOKEN_BASELINE_POPULATION = "completed_observations"
_BUNDLE_GLOB = "ai-builder-api-battle-test-*.json"
_MANIFEST_FILE = "release-manifest.json"


@dataclass(frozen=True)
class _CaseTokenEvidence:
    """One completed observation's token facts, kept per case for pairing."""

    case_contract_sha256: str
    repetition: int
    first_attempts: tuple[tuple[int, int, int], ...]
    classifier: tuple[int, int, int] | None

    def as_json(self) -> dict[str, Any]:
        return {
            "case_contract_sha256": self.case_contract_sha256,
            "repetition": self.repetition,
            "first_attempts": [list(attempt) for attempt in self.first_attempts],
            "classifier": list(self.classifier) if self.classifier else None,
        }


def _median(values: list[int]) -> float | None:
    return statistics.median(values) if values else None


def _p90(values: list[int]) -> int | None:
    """Nearest-rank 90th percentile; the frozen R17 numbers use this rank."""

    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


def _bundle_int(value: object, *, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReceiptError(f"{where} must be a non-negative integer; got {value!r}.")
    return value


def _bundle_str(value: object, *, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReceiptError(f"{where} must be a non-empty string.")
    return value


def _int_triple(value: object, *, where: str) -> tuple[int, int, int]:
    if not isinstance(value, list) or len(cast(list[Any], value)) != 3:
        raise ReceiptError(f"{where} must hold three integers.")
    items = cast(list[Any], value)
    return (
        _bundle_int(items[0], where=where),
        _bundle_int(items[1], where=where),
        _bundle_int(items[2], where=where),
    )


def _token_summary(
    evidence: list[_CaseTokenEvidence],
) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt = [attempt[0] for item in evidence for attempt in item.first_attempts]
    completion = [attempt[1] for item in evidence for attempt in item.first_attempts]
    total = [attempt[2] for item in evidence for attempt in item.first_attempts]
    classifier = [item.classifier for item in evidence if item.classifier is not None]
    return (
        {
            "turns": len(total),
            "median_total_tokens": _median(total),
            "median_prompt_tokens": _median(prompt),
            "median_completion_tokens": _median(completion),
            "p90_prompt_tokens": _p90(prompt),
        },
        {
            "observations_with_usage": len(classifier),
            "observations_without_usage": len(evidence) - len(classifier),
            "median_calls": _median([usage[0] for usage in classifier]),
            "median_prompt_tokens": _median([usage[1] for usage in classifier]),
            "median_total_tokens": _median([usage[2] for usage in classifier]),
        },
    )


@dataclass(frozen=True)
class _SuiteManifest:
    """The identity a token baseline is bound to, read from the release manifest."""

    identity: dict[str, Any]
    expected_observations: list[dict[str, Any]]

    @property
    def model(self) -> dict[str, Any]:
        return dict(cast(dict[str, Any], self.identity["model"]))

    @property
    def app_version(self) -> str:
        return str(cast(dict[str, Any], self.identity["build"])["app_version"])


def load_json_object(path: Path, *, what: str) -> dict[str, Any]:
    """Read one JSON object; anything unreadable is a refusal, never a traceback."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ReceiptError(f"{path}: {what} cannot be read: {error}") from error
    if not isinstance(payload, dict):
        raise ReceiptError(f"{path}: {what} must contain a JSON object.")
    return cast(dict[str, Any], payload)


def _read_manifest(suite_dir: Path) -> _SuiteManifest:
    manifest_path = suite_dir / _MANIFEST_FILE
    if not manifest_path.is_file():
        raise ReceiptError(
            f"{suite_dir} has no {_MANIFEST_FILE}; a token baseline needs the "
            "run's model, build and planned population."
        )
    where = str(manifest_path)
    manifest = load_json_object(manifest_path, what="release manifest")
    expected = manifest.get("expected_observations")
    if not isinstance(expected, list):
        raise ReceiptError(f"{where}: expected_observations is missing.")
    identity = manifest.get("release_identity")
    if not isinstance(identity, dict):
        raise ReceiptError(f"{where}: release_identity is missing.")
    identity = cast(dict[str, Any], identity)
    model = identity.get("model")
    build = identity.get("build")
    if not isinstance(model, dict) or not isinstance(build, dict):
        raise ReceiptError(f"{where}: release_identity.model and .build are required.")
    _bundle_str(
        cast(dict[str, Any], build).get("app_version"),
        where=f"{where}: build.app_version",
    )
    return _SuiteManifest(
        identity=dict(identity),
        expected_observations=[
            dict(cast(dict[str, Any], item))
            for item in cast(list[Any], expected)
            if isinstance(item, dict)
        ],
    )


def _bundle_case_evidence(
    bundle: dict[str, Any], *, where: str
) -> tuple[str, _CaseTokenEvidence]:
    case_identity = bundle.get("case_identity")
    case_id = case_identity.get("id") if isinstance(case_identity, dict) else None
    if not isinstance(case_id, str) or not case_id:
        raise ReceiptError(f"{where}: case_identity.id is missing.")
    diagnostics = bundle.get("proposal_telemetry_diagnostics")
    turns = diagnostics.get("proposal_turns") if isinstance(diagnostics, dict) else None
    if not isinstance(turns, list):
        # A completed observation always carries the diagnostics projection;
        # without it the turn count is unknown, not zero.
        raise ReceiptError(
            f"{where}: proposal_telemetry_diagnostics.proposal_turns is missing."
        )
    first_attempts: list[tuple[int, int, int]] = []
    for position, turn in enumerate(cast(list[Any], turns)):
        attempts = turn.get("attempts") if isinstance(turn, dict) else None
        if not isinstance(attempts, list) or not attempts:
            raise ReceiptError(f"{where}: proposal_turns[{position}] has no attempts.")
        first = cast(list[Any], attempts)[0]
        if not isinstance(first, dict):
            raise ReceiptError(
                f"{where}: proposal_turns[{position}].attempts[0] is malformed."
            )
        first = cast(dict[str, Any], first)
        key = f"{where}: proposal_turns[{position}].attempts[0]"
        first_attempts.append(
            (
                _bundle_int(first.get("prompt_tokens"), where=f"{key}.prompt_tokens"),
                _bundle_int(
                    first.get("completion_tokens"), where=f"{key}.completion_tokens"
                ),
                _bundle_int(first.get("total_tokens"), where=f"{key}.total_tokens"),
            )
        )
    journey = bundle.get("journey")
    usage = journey.get("classifier_usage") if isinstance(journey, dict) else None
    classifier: tuple[int, int, int] | None = None
    if isinstance(usage, dict):
        usage = cast(dict[str, Any], usage)
        key = f"{where}: journey.classifier_usage"
        classifier = (
            _bundle_int(usage.get("calls"), where=f"{key}.calls"),
            _bundle_int(usage.get("prompt_tokens"), where=f"{key}.prompt_tokens"),
            _bundle_int(usage.get("total_tokens"), where=f"{key}.total_tokens"),
        )
    return case_id, _CaseTokenEvidence(
        case_contract_sha256=_bundle_str(
            bundle.get("case_contract_sha256"), where=f"{where}: case_contract_sha256"
        ),
        repetition=_bundle_int(bundle.get("repetition"), where=f"{where}: repetition"),
        first_attempts=tuple(first_attempts),
        classifier=classifier,
    )


def token_baseline_report(suite_dir: Path) -> dict[str, Any]:
    """Proposal and classifier token economics of one suite root, frozen.

    Every later gate compares against the same aggregation, so the population
    and the statistics live here and nowhere else: first proposal attempts of
    completed observations, medians as the middle value, p90 as nearest rank.
    Classifier usage the projection could not supply is counted, never zero.
    The receipt owners decide identity and membership: every bundle must
    prove it belongs to the manifest's run (source, build, corpus, model) and
    occupy a planned slot with the planned contract; missing planned slots
    make the root partial, every other membership defect refuses aggregation.
    """

    bundle_paths = sorted(suite_dir.glob(_BUNDLE_GLOB))
    if not bundle_paths:
        raise ReceiptError(f"{suite_dir} holds no observation bundles.")
    manifest = _read_manifest(suite_dir)
    status_counts: Counter[str] = Counter()
    cases: dict[str, list[_CaseTokenEvidence]] = {}
    slots: list[dict[str, Any]] = []
    for path in bundle_paths:
        where = str(path)
        bundle = load_json_object(path, what="observation bundle")
        require_bundle_identity(bundle, where=where, identity=manifest.identity)
        app_version = _bundle_str(
            bundle.get("app_version"), where=f"{where}: app_version"
        )
        if app_version != manifest.app_version:
            raise ReceiptError(
                f"{where}: bundle reports {app_version!r} but the manifest was "
                f"sealed at {manifest.app_version!r}."
            )
        observation = bundle.get("observation")
        if not isinstance(observation, dict):
            raise ReceiptError(f"{where}: carries no sealed observation.")
        observation = cast(dict[str, Any], observation)
        status = _bundle_str(
            observation.get("observation_status"), where=f"{where}: observation_status"
        )
        status_counts[status] += 1
        case_identity = bundle.get("case_identity")
        slots.append(
            {
                "case_id": (
                    case_identity.get("id") if isinstance(case_identity, dict) else None
                ),
                "repetition": bundle.get("repetition"),
                "case_contract_sha256": bundle.get("case_contract_sha256"),
                "bundle_file": path.name,
                "bundle_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
        if status != "completed":
            continue
        case_id, evidence = _bundle_case_evidence(bundle, where=where)
        cases.setdefault(case_id, []).append(evidence)
    membership = receipt_membership_report(
        expected_observations=manifest.expected_observations,
        results=slots,
        suite_dir=suite_dir,
    )
    defects = {
        name: membership[name]
        for name in (
            "unexpected_observation_keys",
            "duplicate_observation_keys",
            "invalid_expected_observation_keys",
            "invalid_actual_observation_keys",
            "case_contract_mismatches",
            "invalid_bundle_references",
        )
        if membership[name]
    }
    if defects:
        raise ReceiptError(
            f"{suite_dir}: bundles do not belong to the manifest's run: "
            + json.dumps(defects, ensure_ascii=False)
        )
    missing = cast(list[Any], membership["missing_observation_keys"])
    proposal, classifier = _token_summary(
        [item for items in cases.values() for item in items]
    )
    return {
        "suite_dir": str(suite_dir),
        "source_revision": manifest.app_version,
        "model": manifest.model,
        "population": TOKEN_BASELINE_POPULATION,
        "observation_status_counts": dict(sorted(status_counts.items())),
        # Planned slots the root never produced make it partial: its case mix
        # is only its own cases, not the corpus.
        "planned_observations": len(manifest.expected_observations),
        "observed_observations": len(bundle_paths),
        "partial": bool(missing),
        "proposal_first_attempt": proposal,
        "classifier": classifier,
        "cases": {
            case_id: [item.as_json() for item in items]
            for case_id, items in sorted(cases.items())
        },
    }


def _case_evidence_from_report(
    report: dict[str, Any], *, where: str
) -> dict[tuple[str, str], list[_CaseTokenEvidence]]:
    """Read a report's per-case evidence back, keyed by case id and contract."""

    raw_cases = report.get("cases")
    if not isinstance(raw_cases, dict):
        raise ReceiptError(
            f"{where}: token baseline report carries no per-case evidence."
        )
    evidence: dict[tuple[str, str], list[_CaseTokenEvidence]] = {}
    for case_id, raw_items in cast(dict[str, Any], raw_cases).items():
        if not isinstance(raw_items, list):
            raise ReceiptError(f"{where}: cases[{case_id!r}] must be a list.")
        for raw_item in cast(list[Any], raw_items):
            if not isinstance(raw_item, dict):
                raise ReceiptError(
                    f"{where}: cases[{case_id!r}] holds a malformed item."
                )
            raw_item = cast(dict[str, Any], raw_item)
            key = f"{where}: cases[{case_id!r}]"
            attempts = raw_item.get("first_attempts")
            if not isinstance(attempts, list):
                raise ReceiptError(f"{key} lacks first_attempts.")
            classifier = raw_item.get("classifier")
            item = _CaseTokenEvidence(
                case_contract_sha256=_bundle_str(
                    raw_item.get("case_contract_sha256"),
                    where=f"{key}.case_contract_sha256",
                ),
                repetition=_bundle_int(
                    raw_item.get("repetition"), where=f"{key}.repetition"
                ),
                first_attempts=tuple(
                    _int_triple(attempt, where=key)
                    for attempt in cast(list[Any], attempts)
                ),
                classifier=(
                    _int_triple(classifier, where=key)
                    if classifier is not None
                    else None
                ),
            )
            evidence.setdefault((str(case_id), item.case_contract_sha256), []).append(
                item
            )
    return evidence


def token_baseline_delta(
    current: dict[str, Any], baseline: dict[str, Any]
) -> dict[str, Any]:
    """Movement of `current` against a frozen report, over the same experiment.

    Two reports compare only when they were measured with the same model, and
    only over the cases whose id AND contract hash both hold: a partial root
    (the R17 broad leg holds 104 of 172 planned observations, skewed away from
    hard cases) or a rewritten case must not pass as the same population. The
    cases either side lacks are named.
    """

    if current.get("model") != baseline.get("model"):
        raise ReceiptError(
            f"token baseline reports were measured with different models "
            f"({current.get('model')!r} vs {baseline.get('model')!r}); not comparable."
        )
    current_cases = _case_evidence_from_report(current, where="current")
    baseline_cases = _case_evidence_from_report(baseline, where="baseline")
    shared = sorted(set(current_cases) & set(baseline_cases))
    if not shared:
        raise ReceiptError("token baseline reports share no cases; nothing to compare.")
    current_paired = _token_summary(
        [item for identity in shared for item in current_cases[identity]]
    )
    baseline_paired = _token_summary(
        [item for identity in shared for item in baseline_cases[identity]]
    )
    deltas: dict[str, Any] = {
        "paired_cases": len(shared),
        "unpaired_current_cases": sorted(
            case_id for case_id, _ in set(current_cases) - set(shared)
        ),
        "unpaired_baseline_cases": sorted(
            case_id for case_id, _ in set(baseline_cases) - set(shared)
        ),
    }
    for section, current_section, baseline_section in (
        ("proposal_first_attempt", current_paired[0], baseline_paired[0]),
        ("classifier", current_paired[1], baseline_paired[1]),
    ):
        for metric, current_value in current_section.items():
            if not str(metric).startswith(("median_", "p90_")):
                continue
            baseline_value = baseline_section.get(metric)
            movable = isinstance(current_value, (int, float)) and isinstance(
                baseline_value, (int, float)
            )
            deltas[f"{section}.{metric}"] = {
                "baseline": float(baseline_value) if movable else None,
                "current": float(current_value) if movable else None,
                "delta": float(current_value - baseline_value) if movable else None,
            }
    return deltas


def _render_token_baseline_markdown(
    report: dict[str, Any], deltas: dict[str, Any] | None
) -> str:
    lines = [
        f"# Token baseline: {report['source_revision']}",
        "",
        f"Model: {json.dumps(report['model'])}",
        f"Population: {report['population']} "
        f"({json.dumps(report['observation_status_counts'])}); observed "
        f"{report['observed_observations']} of planned "
        f"{report['planned_observations']}"
        + (" — PARTIAL root" if report["partial"] else ""),
        "",
        "| metric | value |",
        "| --- | --- |",
    ]
    for section in ("proposal_first_attempt", "classifier"):
        for metric, value in cast(dict[str, Any], report[section]).items():
            lines.append(f"| {section}.{metric} | {value} |")
    lines.append(f"| cases | {len(cast(dict[str, Any], report['cases']))} |")
    if deltas:
        lines += [
            "",
            f"Paired cases: {deltas['paired_cases']} (unpaired current "
            f"{len(deltas['unpaired_current_cases'])}, unpaired baseline "
            f"{len(deltas['unpaired_baseline_cases'])})",
            "",
            "| metric | baseline | current | delta |",
            "| --- | --- | --- | --- |",
        ]
        for metric, movement in deltas.items():
            if not isinstance(movement, dict):
                continue
            movement = cast(dict[str, Any], movement)
            lines.append(
                f"| {metric} | {movement['baseline']} | {movement['current']} | "
                f"{movement['delta']} |"
            )
    return "\n".join(lines)


def _release_exit_code(report: dict[str, Any]) -> int:
    if report["release"] == "invalid":
        return _INVALID_RECEIPT_EXIT
    feasibility = cast(dict[str, Any] | None, report.get("feasibility"))
    if feasibility is not None and not feasibility["feasible"]:
        return _INVALID_RECEIPT_EXIT
    return 0 if report["release"] == "go" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)

    compare_mode = modes.add_parser("compare", help="Compare two receipts.")
    compare_mode.add_argument("baseline", type=Path)
    compare_mode.add_argument("current", type=Path)
    compare_mode.add_argument(
        "--format", choices=("markdown", "json"), default="markdown"
    )
    compare_mode.add_argument(
        "--only-changed",
        action="store_true",
        help="Omit unchanged, stable cases from the per-case section.",
    )
    compare_mode.add_argument(
        "--allow-harness-change",
        action="store_true",
        help=(
            "Waive harness-hash identity when scoring-affecting edits are "
            "confined to cases with changed contract hashes; those rescored "
            "cases are excluded from direction counts."
        ),
    )
    compare_mode.add_argument(
        "--noise-margin",
        type=int,
        default=None,
        help=(
            "Net conformance movement, in cases, that this pair of runs cannot "
            "distinguish from noise. Required for a verdict, and it must be "
            "declared before the runs — a margin chosen after seeing the "
            "result is not a margin."
        ),
    )

    release_mode = modes.add_parser(
        "release-verdict", help="Judge one receipt against the release gate."
    )
    release_mode.add_argument(
        "suite_dir",
        type=Path,
        help=(
            "The suite directory holding suite-summary.json, "
            "release-manifest.json and the observation bundles."
        ),
    )
    release_mode.add_argument(
        "--feasibility",
        action="store_true",
        help=(
            "Also audit whether a PERFECT run of this manifest could pass every "
            "gate; an unpassable gate is a plan defect, not a product failure."
        ),
    )
    release_mode.add_argument(
        "--format", choices=("markdown", "json"), default="markdown"
    )

    baseline_mode = modes.add_parser(
        "token-baseline",
        help="Aggregate first-attempt proposal and classifier token spend of one suite root.",
    )
    baseline_mode.add_argument("suite_dir", type=Path)
    baseline_mode.add_argument(
        "--against",
        type=Path,
        default=None,
        help="A frozen token-baseline JSON report to state movement against.",
    )
    baseline_mode.add_argument(
        "--format", choices=("markdown", "json"), default="markdown"
    )
    args = parser.parse_args()
    if args.mode == "token-baseline":
        try:
            report = token_baseline_report(args.suite_dir)
            deltas = (
                token_baseline_delta(
                    report,
                    load_json_object(args.against, what="token baseline report"),
                )
                if args.against is not None
                else None
            )
        except ReceiptError as error:
            print(f"Refusing to aggregate this root: {error}", file=sys.stderr)
            raise SystemExit(_INVALID_RECEIPT_EXIT) from error
        if args.format == "json":
            json.dump(
                {**report, "against": deltas} if deltas is not None else report,
                sys.stdout,
                ensure_ascii=False,
                indent=2,
            )
            sys.stdout.write("\n")
        else:
            sys.stdout.write(_render_token_baseline_markdown(report, deltas))
            sys.stdout.write("\n")
        return
    if args.mode == "release-verdict":
        try:
            report = release_verdict_report(
                args.suite_dir,
                pin=evaluator_pin(),
                feasibility=args.feasibility,
            )
        except (ReceiptError, ReleaseGateError) as error:
            # A receipt that cannot be read is INVALID, never a NO-GO: exit 1
            # means "measured and failed", and a caller must not confuse the
            # two.
            print(f"Refusing to judge this receipt: {error}", file=sys.stderr)
            raise SystemExit(_INVALID_RECEIPT_EXIT) from error
        if args.format == "json":
            json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(_render_release_markdown(report))
            sys.stdout.write("\n")
        raise SystemExit(_release_exit_code(report))

    report = compare(
        args.baseline,
        args.current,
        allow_harness_change=args.allow_harness_change,
        noise_margin=args.noise_margin,
    )
    if args.format == "json":
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(_render_markdown(report, only_changed=args.only_changed))
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
