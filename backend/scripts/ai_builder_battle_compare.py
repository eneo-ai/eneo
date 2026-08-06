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

Receipts carry their own identity (app_version, evaluator_identity); the
report refuses to compare receipts whose evaluator semantics differ,
because relevance rates across semantic versions do not mean the same
thing.
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
    failure_summary = cast(dict[str, Any], row.get("failure_summary") or {})
    codes = cast(list[str], failure_summary.get("failure_codes") or [])
    return tuple(sorted(codes))


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


def _semantics_marker(summary: dict[str, Any]) -> Any:
    identity = summary.get("evaluator_identity")
    if not isinstance(identity, dict):
        return (1, 1)
    typed_identity = cast(dict[str, Any], identity)
    return (
        typed_identity.get("question_relevance_semantics_version", 1),
        typed_identity.get("outcome_classification_semantics_version", 1),
    )


def compare(
    baseline_path: Path,
    current_path: Path,
) -> dict[str, Any]:
    baseline_rows, baseline_summary = _load_rows(baseline_path)
    current_rows, current_summary = _load_rows(current_path)
    if _semantics_marker(baseline_summary) != _semantics_marker(current_summary):
        raise SystemExit(
            "Refusing to compare receipts with different evaluator semantics "
            f"({_semantics_marker(baseline_summary)!r} vs "
            f"{_semantics_marker(current_summary)!r}); relevance rates do not "
            "mean the same thing across semantic versions."
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
    remaining_blockers = Counter(
        code
        for case_rows in current_rows.values()
        for row in case_rows
        for code in _failure_codes(row)
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
        "direction_counts": dict(directions),
        "current_outcomes": dict(outcome_counts),
        "remaining_blockers_ranked": remaining_blockers.most_common(),
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
    lines.append("## Remaining blockers (ranked)")
    for code, count in report["remaining_blockers_ranked"]:
        lines.append(f"- {count}x {code}")
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
