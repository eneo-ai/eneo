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


def _with_identity(
    tmp_path: Path,
    name: str,
    field: str,
    value: object,
) -> Path:
    path = tmp_path / name
    payload = _summary([_row("case-a", "plan_first_pass")])
    payload["evaluator_identity"][field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "field, value",
    [
        ("outcome_classification_semantics_version", 1),
        ("question_relevance_semantics_version", 1),
        ("requested_model_id", "some-other-model"),
    ],
)
def test_identity_that_changes_meaning_refuses_comparison(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    # Two semantic-version integers were not enough: receipts scored by a
    # different model compared as though they measured the same thing.
    module = _compare_module()
    baseline = _with_identity(tmp_path, "base.json", field, value)
    current = _write(tmp_path, "cur.json", [_row("case-a", "plan_first_pass")])

    with pytest.raises(SystemExit) as excinfo:
        module.compare(baseline, current)

    assert field in str(excinfo.value)


@pytest.mark.parametrize(
    "field",
    ["harness_sha256", "cases_sha256", "source_revision", "target_sha256"],
)
def test_identity_that_differs_between_builds_is_reported_not_fatal(
    tmp_path: Path,
    field: str,
) -> None:
    # `target_sha256` embeds the deployed app version, so it differs between
    # every pair of builds — the exact axis this tool compares. Refusing on
    # it (or on the whole-identity hash that contains it) would refuse every
    # legitimate comparison.
    module = _compare_module()
    baseline = _with_identity(tmp_path, "base.json", field, "a" * 64)
    current = _with_identity(tmp_path, "cur.json", field, "b" * 64)

    report = module.compare(baseline, current)

    assert report["identity_differences"][field] == {
        "baseline": "a" * 64,
        "current": "b" * 64,
    }


def test_changed_case_contract_is_reported_not_fatal(tmp_path: Path) -> None:
    # Correcting one case's expectations must not block comparing the rest,
    # but the rescored case has to be named so its delta is not read as
    # product movement.
    module = _compare_module()
    baseline_path = tmp_path / "base.json"
    payload = _summary(
        [_row("case-a", "plan_first_pass"), _row("case-b", "plan_first_pass")]
    )
    payload["evaluator_identity"]["case_contract_sha256_by_id"] = {
        "case-a": "1" * 64,
        "case-b": "2" * 64,
    }
    baseline_path.write_text(json.dumps(payload), encoding="utf-8")

    current_path = tmp_path / "cur.json"
    current_payload = _summary(
        [_row("case-a", "plan_first_pass"), _row("case-b", "plan_first_pass")]
    )
    current_payload["evaluator_identity"]["case_contract_sha256_by_id"] = {
        "case-a": "1" * 64,
        "case-b": "9" * 64,
    }
    current_path.write_text(json.dumps(current_payload), encoding="utf-8")

    report = module.compare(baseline_path, current_path)

    assert report["rescored_cases"] == ["case-b"]


def test_blockers_count_cases_not_repetitions(tmp_path: Path) -> None:
    module = _compare_module()
    baseline = _write(tmp_path, "base.json", [_row("case-a", "plan_first_pass")])
    current_path = tmp_path / "cur.json"
    rows: list[dict[str, Any]] = []
    for index in (1, 2, 3):
        row = _row("case-a", "builder_error", repetition=index, verdict="fail")
        row["failure_summary"] = {"failure_codes": ["assembly_plan_invariant_failed"]}
        rows.append(row)
    current_path.write_text(json.dumps(_summary(rows)), encoding="utf-8")

    report = module.compare(baseline, current_path)

    assert report["remaining_blockers_ranked"] == [
        ("assembly_plan_invariant_failed", 1)
    ]


def test_public_error_codes_count_as_blockers(tmp_path: Path) -> None:
    # A router-level refusal carries no internal failure detail, so counting
    # only `failure_codes` printed an empty blocker ranking for a run in
    # which 8 cases errored.
    module = _compare_module()
    baseline = _write(tmp_path, "base.json", [_row("case-a", "plan_first_pass")])
    current_path = tmp_path / "cur.json"
    row = _row("case-a", "provider_outcome_unknown", verdict="fail")
    row["failure_summary"] = {
        "failure_codes": [],
        "error_codes": ["session_turn_provider_outcome_unknown"],
    }
    current_path.write_text(json.dumps(_summary([row])), encoding="utf-8")

    report = module.compare(baseline, current_path)

    assert report["remaining_blockers_ranked"] == [
        ("session_turn_provider_outcome_unknown", 1)
    ]


def test_failed_checks_aggregate_across_repetitions(tmp_path: Path) -> None:
    # The representative row is one repetition. Reading failed checks off it
    # hides every check that only some repetitions fail — exactly the checks
    # a stochastic step fails intermittently.
    module = _compare_module()
    baseline = _write(tmp_path, "base.json", [_row("case-a", "plan_first_pass")])
    current_path = tmp_path / "cur.json"
    rows = [
        _row("case-a", "plan_first_pass", repetition=1),
        _row("case-a", "plan_first_pass", repetition=2, verdict="fail"),
        _row("case-b", "plan_first_pass", repetition=1, verdict="fail"),
    ]
    rows[1]["failed_checks"] = [{"name": "expected_leaf_output_fields"}]
    rows[2]["failed_checks"] = [{"name": "expected_leaf_output_fields"}]
    current_path.write_text(json.dumps(_summary(rows)), encoding="utf-8")

    report = module.compare(baseline, current_path)

    assert report["remaining_failed_checks_ranked"] == [
        ("expected_leaf_output_fields", 2)
    ]


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
