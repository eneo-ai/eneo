#!/usr/bin/env python3
"""Compare two AI Builder battle suite receipts case by case.

The battle harness answers "what should we improve next" only when run
pairs are comparable. This tool takes two ``suite-summary.json`` receipts
(older first) and reports, per case: the outcome transition, failure-code
and failed-check deltas, question changes, and authoring-token deltas —
then ranks the remaining blockers by family so the next slice is chosen
from evidence instead of memory.

Usage:
    ai_builder_battle_compare.py BASELINE_SUMMARY CURRENT_SUMMARY
        [--format markdown|json] [--only-changed]

Receipts carry their own identity (app_version, evaluator_identity). The
report refuses to compare receipts that measure different things — a
different scoring semantics version or a different model — and reports,
without refusing, the identity fields that are expected to differ between
two builds.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, cast

# Better outcomes rank higher; a transition to a higher rank is an
# improvement. Ties are "changed" but neither improved nor regressed.
_OUTCOME_RANK: dict[str, int] = {
    "plan_first_pass": 6,
    "clarification_stop_intended": 5,
    "clarify_ok": 5,
    "plan_repaired": 4,
    "stalled_unanswered_question": 3,
    "interaction_limit_reached": 2,
    "plan_with_error": 2,
    "builder_error": 1,
    "execution_failure": 1,
    "invalid_evidence": 0,
    "fixture_skip": 0,
}


def _load_rows(path: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Group every repetition per case.

    Discarding all but the last repetition threw away the only evidence that
    distinguishes a real change from proposal variance — and that variance is
    large: 36 of 122 cases changed outcome between two runs of neighbouring
    builds (2026-08-06). Callers decide how to summarize; nothing is dropped
    here.
    """

    summary = cast(dict[str, Any], json.loads(path.read_text()))
    rows: dict[str, list[dict[str, Any]]] = {}
    for row_value in cast(list[Any], summary.get("results") or []):
        if not isinstance(row_value, dict):
            continue
        row = cast(dict[str, Any], row_value)
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            continue
        rows.setdefault(case_id, []).append(row)
    for case_rows in rows.values():
        case_rows.sort(key=lambda item: item.get("repetition") or 0)
    return rows, summary


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
    before_rank = _OUTCOME_RANK.get(before, -1)
    after_rank = _OUTCOME_RANK.get(after, -1)
    if baseline is None or current is None:
        direction = "coverage_changed"
    elif after_rank > before_rank:
        direction = "improved"
    elif after_rank < before_rank:
        direction = "regressed"
    elif before != after:
        direction = "changed"
    else:
        direction = "unchanged"

    delta: dict[str, Any] = {
        "case_id": case_id,
        "direction": direction,
        "outcome": f"{before} -> {after}",
    }
    # Instability is a property of ONE build disagreeing with itself. Judging
    # it from the union of both builds would brand every real, consistent
    # A -> B change unstable.
    baseline_states = _observed_states(baseline_repetitions)
    current_states = _observed_states(current_repetitions)
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
#
# Deliberately excluded, with evidence: `target_sha256` embeds the deployed
# app version and so differs between every pair of builds — the exact axis
# this tool exists to compare (verified on the 9d4237a/9216ec6 receipts).
# The full `evaluator_identity.sha256` differs for the same reason.
# `harness_sha256` and `cases_sha256` change on any harness or corpus edit,
# including ones that do not touch scoring; the two semantics versions are
# the author's explicit declaration that scoring meaning changed, and gating
# on the raw hashes would make that declaration dead. Those fields are
# reported instead, so a reader can audit an undeclared instrument change.
# `case_contract_sha256_by_id` is compared per case, so editing one case's
# expectations does not block comparing the other 121.
_IDENTITY_FIELDS: tuple[str, ...] = (
    "question_relevance_semantics_version",
    "outcome_classification_semantics_version",
    "requested_model_id",
)

# Differences here are expected and reported, never fatal.
_REPORTED_IDENTITY_FIELDS: tuple[str, ...] = (
    "harness_sha256",
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


def _incompatible_identity_fields(
    baseline_summary: dict[str, Any],
    current_summary: dict[str, Any],
) -> list[str]:
    baseline_marker = _identity_marker(baseline_summary)
    current_marker = _identity_marker(current_summary)
    return [
        field
        for field in _IDENTITY_FIELDS
        if baseline_marker[field] != current_marker[field]
    ]


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
) -> dict[str, Any]:
    baseline_rows, baseline_summary = _load_rows(baseline_path)
    current_rows, current_summary = _load_rows(current_path)
    incompatible = _incompatible_identity_fields(baseline_summary, current_summary)
    if incompatible:
        raise SystemExit(
            "Refusing to compare receipts whose evaluator identity differs on "
            f"{', '.join(incompatible)}; they do not measure the same thing. "
            f"baseline={_identity_marker(baseline_summary)!r} "
            f"current={_identity_marker(current_summary)!r}"
        )
    rescored_cases = _case_contract_changes(baseline_summary, current_summary)
    identity_differences = _reported_identity_differences(
        baseline_summary, current_summary
    )

    case_ids = sorted(set(baseline_rows) | set(current_rows))
    deltas = [
        _case_delta(
            case_id,
            _representative_row(baseline_rows.get(case_id)),
            _representative_row(current_rows.get(case_id)),
            baseline_repetitions=baseline_rows.get(case_id) or [],
            current_repetitions=current_rows.get(case_id) or [],
        )
        for case_id in case_ids
    ]
    directions = Counter(delta["direction"] for delta in deltas)
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
    return {
        "baseline": _identity(baseline_summary),
        "current": _identity(current_summary),
        "rescored_cases": rescored_cases,
        "identity_differences": identity_differences,
        "direction_counts": dict(directions),
        "current_outcomes": dict(outcome_counts),
        "remaining_blockers_ranked": remaining_blockers.most_common(),
        "remaining_failed_checks_ranked": remaining_failed_checks.most_common(),
        "unstable_cases": unstable,
        "cases": deltas,
    }


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
    lines.append(f"Direction counts: {report['direction_counts']}")
    lines.append(f"Current outcomes: {report['current_outcomes']}")
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
        if only_changed and delta["direction"] == "unchanged":
            continue
        lines.append(
            f"- **{delta['case_id']}** [{delta['direction']}] {delta['outcome']}"
        )
        for key in (
            "failure_codes",
            "failed_checks",
            "questions",
            "authoring_tokens",
            "repair_economics",
        ):
            if key in delta:
                lines.append(f"  - {key}: {json.dumps(delta[key], ensure_ascii=False)}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("current", type=Path)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument(
        "--only-changed",
        action="store_true",
        help="Omit unchanged cases from the per-case section.",
    )
    args = parser.parse_args()
    report = compare(args.baseline, args.current)
    if args.format == "json":
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(_render_markdown(report, only_changed=args.only_changed))
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
