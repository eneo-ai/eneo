"""AI Builder baseline benchmark runner.

Executes the deterministic pre-LLM discovery pipeline against every canonical
case and produces a structural snapshot. The committed ``baseline.json`` is a
frozen reference: architectural changes are expected to move the numbers, so
per-PR tests validate schema, determinism, and coverage, and the drift is
surfaced by an on-demand / nightly diff against the frozen reference.

Scope
-----

This runner covers deterministic discovery metrics only — question count and
budget, over/under-questioning flag, planner pattern signals, selected
discovery question IDs, blocking-issue count, MVS and confirmation state.
LLM-dependent fields (plan depth, repair-loop rate, architecture-chain
correctness, shallow-two-step incidence) are reserved as ``None`` here and
populated later by a golden-fixture evaluation harness without a schema
break.

Usage
-----

From ``/workspace/backend`` inside the devcontainer::

    # Print current measurements to stdout
    uv run python -m tests.integration.flows.ai_builder.benchmark.runner

    # Diff current measurements against the frozen baseline
    uv run python -m tests.integration.flows.ai_builder.benchmark.runner --diff

    # Re-freeze the baseline (explicit; only at deliberate re-baseline
    # points the team has agreed to)
    uv run python -m tests.integration.flows.ai_builder.benchmark.runner \\
        --write-baseline
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from intric.flows.ai_builder.ai_builder_discovery import analyze_discovery
from intric.flows.ai_builder.ai_builder_discovery_decision_engine import (
    compute_question_budget,
    has_explicit_step_plan,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
    detect_planner_pattern_signals,
)
from tests.integration.flows.ai_builder.benchmark.cases import (
    BENCHMARK_CASES,
    BenchmarkCase,
)

BASELINE_SCHEMA_VERSION = 1
BASELINE_PATH: Path = Path(__file__).parent / "baseline.json"

PATTERN_SIGNAL_KEYS: tuple[str, ...] = (
    "needs_form_fields",
    "prefers_structured_intermediate",
    "prefers_quality_step",
    "rich_document_workflow",
)

DEFERRED_EVAL_METRIC_KEYS: tuple[str, ...] = (
    "plan_depth",
    "repair_loop_rate",
    "architecture_chain_correctness",
    "shallow_two_step_incidence",
)


def _classify_questioning(question_count: int, budget: int, ready: bool) -> str:
    if question_count > budget:
        return "over_budget"
    if question_count == 0 and not ready:
        return "under_signal"
    return "within_budget"


def compute_case_metrics(case: BenchmarkCase) -> dict[str, Any]:
    """Run the deterministic discovery path for a single case."""
    conversation = [
        ConversationMessage(
            role="user",
            content=case.prompt,
            metadata={"ui_language": case.ui_language},
        )
    ]
    analysis = analyze_discovery(conversation)
    pattern = detect_planner_pattern_signals(case.prompt)

    selected = list(analysis.selected_question_ids)
    question_budget = compute_question_budget(case.prompt)
    questioning_flag = _classify_questioning(
        question_count=len(selected),
        budget=question_budget,
        ready=analysis.ready_for_confirmation,
    )

    return {
        "case_id": case.case_id,
        "archetype": case.archetype,
        "ui_language": case.ui_language,
        "question_budget": question_budget,
        "question_count": len(selected),
        "questioning_flag": questioning_flag,
        "has_explicit_step_plan": has_explicit_step_plan(case.prompt),
        "pattern_signals": {key: getattr(pattern, key) for key in PATTERN_SIGNAL_KEYS},
        "blocking_issue_count": len(analysis.blocking_issues),
        "selected_question_ids": selected,
        "mvs_met": analysis.mvs_met,
        "ready_for_confirmation": analysis.ready_for_confirmation,
        # Deferred eval slots — filled by golden-fixture replay later.
        "plan_depth": None,
        "repair_loop_rate": None,
        "architecture_chain_correctness": None,
        "shallow_two_step_incidence": None,
    }


def _compute_cases_sha256(cases: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        cases, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_current_document() -> dict[str, Any]:
    cases = sorted(
        (compute_case_metrics(case) for case in BENCHMARK_CASES),
        key=lambda entry: entry["case_id"],
    )
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "note": (
            "Deterministic pre-LLM measurements only. LLM-dependent fields "
            "(plan_depth, repair_loop_rate, architecture_chain_correctness, "
            "shallow_two_step_incidence) are populated by a later "
            "golden-fixture evaluation harness. The committed baseline is a "
            "frozen reference; diffs against it are expected as the "
            "architecture evolves."
        ),
        "cases_sha256": _compute_cases_sha256(cases),
        "cases": cases,
    }


def load_baseline() -> dict[str, Any]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _serialize(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _diff_cases(
    baseline_cases: list[dict[str, Any]],
    current_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_by_id = {entry["case_id"]: entry for entry in baseline_cases}
    current_by_id = {entry["case_id"]: entry for entry in current_cases}
    added = sorted(current_by_id.keys() - baseline_by_id.keys())
    removed = sorted(baseline_by_id.keys() - current_by_id.keys())
    changed: dict[str, dict[str, dict[str, Any]]] = {}
    for case_id in sorted(baseline_by_id.keys() & current_by_id.keys()):
        diffs: dict[str, dict[str, Any]] = {}
        base = baseline_by_id[case_id]
        cur = current_by_id[case_id]
        for key in sorted(set(base.keys()) | set(cur.keys())):
            if base.get(key) != cur.get(key):
                diffs[key] = {"baseline": base.get(key), "current": cur.get(key)}
        if diffs:
            changed[case_id] = diffs
    return {"added": added, "removed": removed, "changed": changed}


def diff_against_baseline() -> dict[str, Any]:
    return _diff_cases(load_baseline()["cases"], build_current_document()["cases"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI Builder baseline benchmark runner.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--diff",
        action="store_true",
        help="Print a structural diff of current measurements vs. baseline.",
    )
    mode.add_argument(
        "--write-baseline",
        action="store_true",
        help=(
            "Re-freeze baseline.json against current measurements. Explicit "
            "only — use at a phase boundary where re-baselining is intended."
        ),
    )
    args = parser.parse_args(argv)

    document = build_current_document()
    if args.write_baseline:
        BASELINE_PATH.write_text(_serialize(document), encoding="utf-8")
        print(f"wrote {BASELINE_PATH} ({len(document['cases'])} cases)")
        return 0
    if args.diff:
        diff = diff_against_baseline()
        print(_serialize(diff), end="")
        return 0 if not (diff["added"] or diff["removed"] or diff["changed"]) else 1
    print(_serialize(document), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
