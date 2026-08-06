"""Behavior tests for the suite comparison tool.

The comparator decides whether a change counts as progress, so its own
mistakes become false conclusions about the product. It had no tests until
a peer review found that it branded stable changes unstable (2026-08-06).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[4] / "scripts" / "ai_builder_battle_compare.py"
)


def _compare_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("battle_compare", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "app_version": "DEV-test",
        "evaluator_identity": {
            "question_relevance_semantics_version": 2,
            "outcome_classification_semantics_version": 2,
        },
        "results": rows,
    }


def _row(
    case_id: str,
    outcome: str,
    *,
    repetition: int = 1,
    verdict: str = "pass",
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "repetition": repetition,
        "outcome_class": outcome,
        "expectation_verdict": verdict,
    }


def _write(tmp_path: Path, name: str, rows: list[dict[str, Any]]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(_summary(rows)), encoding="utf-8")
    return path


def _case(report: dict[str, Any], case_id: str) -> dict[str, Any]:
    return next(item for item in report["cases"] if item["case_id"] == case_id)


def test_consistent_change_between_builds_is_not_unstable(tmp_path: Path) -> None:
    module = _compare_module()
    baseline = _write(
        tmp_path,
        "base.json",
        [_row("case-a", "plan_repaired", repetition=index) for index in (1, 2, 3)],
    )
    current = _write(
        tmp_path,
        "cur.json",
        [_row("case-a", "plan_first_pass", repetition=index) for index in (1, 2, 3)],
    )

    report = module.compare(baseline, current)
    case = _case(report, "case-a")

    assert case["direction"] == "improved"
    assert "baseline_unstable" not in case
    assert "current_unstable" not in case
    assert report["unstable_cases"] == {"baseline": [], "current": []}


def test_build_that_disagrees_with_itself_is_marked_unstable(tmp_path: Path) -> None:
    module = _compare_module()
    baseline = _write(
        tmp_path,
        "base.json",
        [_row("case-a", "plan_repaired", repetition=index) for index in (1, 2, 3)],
    )
    current = _write(
        tmp_path,
        "cur.json",
        [
            _row("case-a", "plan_first_pass", repetition=1),
            _row("case-a", "plan_first_pass", repetition=2),
            _row("case-a", "plan_repaired", repetition=3),
        ],
    )

    case = _case(module.compare(baseline, current), "case-a")

    assert case["current_unstable"] is True
    assert "baseline_unstable" not in case
    assert case["current_observed_states"] == [
        "plan_first_pass/pass",
        "plan_repaired/pass",
    ]


def test_same_outcome_with_changing_verdict_counts_as_instability(
    tmp_path: Path,
) -> None:
    # Mechanics can look identical while conformance flips; outcome alone
    # would hide it.
    module = _compare_module()
    baseline = _write(tmp_path, "base.json", [_row("case-a", "plan_first_pass")])
    current = _write(
        tmp_path,
        "cur.json",
        [
            _row("case-a", "plan_first_pass", repetition=1, verdict="pass"),
            _row("case-a", "plan_first_pass", repetition=2, verdict="fail"),
        ],
    )

    case = _case(module.compare(baseline, current), "case-a")

    assert case["current_unstable"] is True
    assert case["current_observed_states"] == [
        "plan_first_pass/fail",
        "plan_first_pass/pass",
    ]


def test_incompatible_evaluator_semantics_refuse_comparison(tmp_path: Path) -> None:
    module = _compare_module()
    baseline_path = tmp_path / "base.json"
    payload = _summary([_row("case-a", "plan_first_pass")])
    payload["evaluator_identity"]["outcome_classification_semantics_version"] = 1
    baseline_path.write_text(json.dumps(payload), encoding="utf-8")
    current = _write(tmp_path, "cur.json", [_row("case-a", "plan_first_pass")])

    with pytest.raises(SystemExit):
        module.compare(baseline_path, current)


def test_case_missing_from_one_run_is_coverage_change(tmp_path: Path) -> None:
    module = _compare_module()
    baseline = _write(tmp_path, "base.json", [_row("case-a", "plan_first_pass")])
    current = _write(tmp_path, "cur.json", [_row("case-b", "plan_first_pass")])

    report = module.compare(baseline, current)

    assert _case(report, "case-a")["direction"] == "coverage_changed"
    assert _case(report, "case-b")["direction"] == "coverage_changed"


def test_modal_outcome_decides_the_representative_row(tmp_path: Path) -> None:
    module = _compare_module()
    baseline = _write(tmp_path, "base.json", [_row("case-a", "plan_repaired")])
    current = _write(
        tmp_path,
        "cur.json",
        [
            _row("case-a", "plan_first_pass", repetition=1),
            _row("case-a", "plan_repaired", repetition=2),
            _row("case-a", "plan_first_pass", repetition=3),
        ],
    )

    case = _case(module.compare(baseline, current), "case-a")

    # Two of three repetitions are first-pass, so the comparison reports the
    # improvement while still flagging the case as unstable.
    assert case["direction"] == "improved"
    assert case["current_unstable"] is True
