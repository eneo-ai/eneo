"""Behavior tests for the suite comparison tool.

The comparator decides whether a change counts as progress, so its own
mistakes become false conclusions about the product. It had no tests until
a peer review found that it branded stable changes unstable (2026-08-06).
"""

from __future__ import annotations

import importlib.util
import json
import re
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
        "artifact_schema_version": "ai-builder-live-release.v4",
        "artifact_mode": "live_execution_exploratory_summary",
        "repetitions": 3,
        "release_identity": {"source": {"revision": "a" * 40}},
        "app_version": "DEV-test",
        "base_url": "http://localhost:8123/api/v1",
        "evaluator_identity": {
            "question_relevance_semantics_version": 3,
            "outcome_classification_semantics_version": 4,
            "observation_input_identity_semantics_version": 3,
            "requested_model_id": "model-under-test",
            "harness_sha256": "0" * 64,
            "run_context": {
                "auto_confirm_requirements": True,
                "confirm_message_sha256": "c" * 64,
                "max_concurrency": 1,
                "max_concurrent_observations_per_case": 1,
                "flow_isolation_semantics_version": 1,
                "repetitions": 3,
                "ui_language": "sv",
            },
        },
        "results": rows,
    }


def _row(
    case_id: str,
    outcome: str,
    *,
    repetition: int = 1,
    verdict: str = "pass",
    cohorts: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "repetition": repetition,
        "observation_status": "completed",
        "outcome_class": outcome,
        "expectation_verdict": verdict,
        "case_contract_sha256": "c" * 64,
        "bundle_file": f"{case_id}-r{repetition}.json",
        "bundle_sha256": "b" * 64,
        "cohorts": cohorts if cohorts is not None else [],
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

    # Both builds agree with themselves, so the change is real: fewer
    # repairs, with conformance unmoved.
    assert case["mechanics_direction"] == "improved"
    assert case["direction"] == "unchanged"
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


def test_every_harness_outcome_class_has_a_mechanics_rank() -> None:
    """A class the rank map does not know falls below everything.

    That hole made provider_outcome_unknown -> builder_error report as a
    mechanics improvement, so the map must cover every outcome class the
    harness can emit — read from its source, not from a hand-kept list.
    """

    module = _compare_module()
    harness_source = _SCRIPT.with_name("ai_builder_api_battle_test.py").read_text(
        encoding="utf-8"
    )
    emitted = set(re.findall(r'outcome_class = "(\w+)"', harness_source))
    assert emitted, "harness source no longer matches the extraction pattern"
    assert emitted <= set(module._OUTCOME_RANK), (
        f"outcome classes missing a rank: {sorted(emitted - set(module._OUTCOME_RANK))}"
    )


def test_error_terminated_siblings_do_not_rank_as_improvement(
    tmp_path: Path,
) -> None:
    # Both are error-terminated journeys without a plan; swapping one for the
    # other is a different failure, not progress.
    module = _compare_module()
    baseline = _write(
        tmp_path,
        "base.json",
        [_row("case-a", "provider_outcome_unknown", verdict="not_evaluated")],
    )
    current = _write(
        tmp_path,
        "cur.json",
        [_row("case-a", "builder_error", verdict="not_evaluated")],
    )

    case = _case(module.compare(baseline, current), "case-a")

    assert case["mechanics_direction"] == "changed"


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
        ("outcome_classification_semantics_version", 3),
        ("question_relevance_semantics_version", 2),
        ("observation_input_identity_semantics_version", 2),
        ("requested_model_id", "some-other-model"),
        ("harness_sha256", "9" * 64),
    ],
)
def test_identity_that_changes_meaning_refuses_comparison(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    # Semantic versions alone are not enough: receipts scored by a different
    # model also measure a different experiment.
    module = _compare_module()
    baseline = _with_identity(tmp_path, "base.json", field, value)
    current = _write(tmp_path, "cur.json", [_row("case-a", "plan_first_pass")])

    with pytest.raises(SystemExit) as excinfo:
        module.compare(baseline, current)

    assert field in str(excinfo.value)


@pytest.mark.parametrize(
    "field",
    ["cases_sha256", "source_revision", "target_sha256"],
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


@pytest.mark.parametrize(
    "before, after, expected",
    [
        ("pass", "fail", "regressed"),
        ("fail", "pass", "improved"),
        ("pass", "pass", "unchanged"),
        ("pass", "not_evaluated", "evaluation_changed"),
        ("not_evaluated", "fail", "evaluation_changed"),
    ],
)
def test_direction_follows_conformance_not_mechanics(
    tmp_path: Path,
    before: str,
    after: str,
    expected: str,
) -> None:
    # Direction read off `outcome_class` reported a case that stopped
    # satisfying its rubric as "unchanged" whenever its mechanics held —
    # the exact regression the no-regression rule exists to catch.
    module = _compare_module()
    baseline = _write(
        tmp_path, "base.json", [_row("case-a", "plan_first_pass", verdict=before)]
    )
    current = _write(
        tmp_path, "cur.json", [_row("case-a", "plan_first_pass", verdict=after)]
    )

    case = _case(module.compare(baseline, current), "case-a")

    assert case["direction"] == expected
    assert case["mechanics_direction"] == "unchanged"
    assert case["conformance"] == f"{before} -> {after}"


def test_mechanics_gain_with_conformance_loss_reports_the_loss(
    tmp_path: Path,
) -> None:
    # Fewer repairs is not progress if the plan stopped satisfying the case.
    module = _compare_module()
    baseline = _write(
        tmp_path, "base.json", [_row("case-a", "plan_repaired", verdict="pass")]
    )
    current = _write(
        tmp_path, "cur.json", [_row("case-a", "plan_first_pass", verdict="fail")]
    )

    case = _case(module.compare(baseline, current), "case-a")

    assert case["direction"] == "regressed"
    assert case["mechanics_direction"] == "improved"


def test_unstable_case_gets_no_direction(tmp_path: Path) -> None:
    # The modal row would promote one repetition of a self-disagreeing build
    # to a verdict.
    module = _compare_module()
    baseline = _write(
        tmp_path, "base.json", [_row("case-a", "plan_first_pass", verdict="fail")]
    )
    current = _write(
        tmp_path,
        "cur.json",
        [
            _row("case-a", "plan_first_pass", repetition=1, verdict="pass"),
            _row("case-a", "plan_first_pass", repetition=2, verdict="fail"),
        ],
    )

    case = _case(module.compare(baseline, current), "case-a")

    assert case["direction"] == "inconclusive"


def test_unstable_case_survives_only_changed_filter(tmp_path: Path) -> None:
    module = _compare_module()
    baseline = _write(
        tmp_path, "base.json", [_row("case-a", "plan_first_pass", verdict="pass")]
    )
    current = _write(
        tmp_path,
        "cur.json",
        [
            _row("case-a", "plan_first_pass", repetition=1, verdict="pass"),
            _row("case-a", "plan_repaired", repetition=2, verdict="pass"),
        ],
    )

    rendered = module._render_markdown(
        module.compare(baseline, current), only_changed=True
    )

    assert "case-a" in rendered
    assert "Unstable cases" in rendered


@pytest.mark.parametrize("field", ["requested_model_id", "harness_sha256"])
def test_missing_identity_field_fails_closed(tmp_path: Path, field: str) -> None:
    # Treating absence as a match let two receipts that recorded no model
    # and no harness compare as though they agreed on both.
    module = _compare_module()
    baseline_path = tmp_path / "base.json"
    payload = _summary([_row("case-a", "plan_first_pass")])
    del payload["evaluator_identity"][field]
    baseline_path.write_text(json.dumps(payload), encoding="utf-8")
    current = _write(tmp_path, "cur.json", [_row("case-a", "plan_first_pass")])

    with pytest.raises(SystemExit) as excinfo:
        module.compare(baseline_path, current)

    assert f"{field} (missing)" in str(excinfo.value)


@pytest.mark.parametrize(
    "field",
    [
        "ui_language",
        "auto_confirm_requirements",
        "flow_isolation_semantics_version",
        "max_concurrent_observations_per_case",
    ],
)
def test_changed_run_context_refuses_comparison(tmp_path: Path, field: str) -> None:
    # Language and auto-confirm change what the builder was asked to do.
    module = _compare_module()
    baseline_path = tmp_path / "base.json"
    payload = _summary([_row("case-a", "plan_first_pass")])
    payload["evaluator_identity"]["run_context"][field] = "changed"
    baseline_path.write_text(json.dumps(payload), encoding="utf-8")
    current = _write(tmp_path, "cur.json", [_row("case-a", "plan_first_pass")])

    with pytest.raises(SystemExit) as excinfo:
        module.compare(baseline_path, current)

    assert f"run_context.{field}" in str(excinfo.value)


def test_changed_environment_refuses_comparison(tmp_path: Path) -> None:
    module = _compare_module()
    baseline_path = tmp_path / "base.json"
    payload = _summary([_row("case-a", "plan_first_pass")])
    payload["base_url"] = "http://staging:8123/api/v1"
    baseline_path.write_text(json.dumps(payload), encoding="utf-8")
    current = _write(tmp_path, "cur.json", [_row("case-a", "plan_first_pass")])

    with pytest.raises(SystemExit) as excinfo:
        module.compare(baseline_path, current)

    assert "base_url" in str(excinfo.value)


def test_harness_change_counts_only_cases_with_unchanged_contracts(
    tmp_path: Path,
) -> None:
    module = _compare_module()
    baseline_path = tmp_path / "base.json"
    payload = _summary(
        [
            _row("unchanged-case", "plan_first_pass", verdict="fail"),
            _row("sentinel", "plan_first_pass", verdict="fail"),
        ]
    )
    payload["evaluator_identity"]["harness_sha256"] = "9" * 64
    payload["evaluator_identity"]["case_contract_sha256_by_id"] = {
        "unchanged-case": "1" * 64,
        "sentinel": "2" * 64,
    }
    baseline_path.write_text(json.dumps(payload), encoding="utf-8")

    current_path = tmp_path / "cur.json"
    current_payload = _summary(
        [
            _row("unchanged-case", "plan_first_pass", verdict="pass"),
            _row("sentinel", "plan_first_pass", verdict="pass"),
        ]
    )
    current_payload["evaluator_identity"]["case_contract_sha256_by_id"] = {
        "unchanged-case": "1" * 64,
        "sentinel": "9" * 64,
    }
    current_path.write_text(json.dumps(current_payload), encoding="utf-8")

    report = module.compare(
        baseline_path,
        current_path,
        allow_harness_change=True,
    )

    assert report["rescored_cases"] == ["sentinel"]
    assert report["direction_counts"] == {"improved": 1}
    assert _case(report, "sentinel")["direction"] == "improved"
    assert _case(report, "unchanged-case")["direction"] == "improved"


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


def test_mixed_repetition_design_gets_no_margin_verdict(tmp_path: Path) -> None:
    # The margin is calibrated on same-design repetition movement. A repeated
    # baseline against a single-run candidate measures a different quantity,
    # so "no_measurable_change" there would be a false negative in disguise.
    module = _compare_module()
    baseline_path = tmp_path / "base.json"
    base_payload = _summary(
        [_row("case-a", "plan_first_pass", repetition=i) for i in (1, 2, 3)]
    )
    base_payload["evaluator_identity"]["run_context"]["repetitions"] = 3
    baseline_path.write_text(json.dumps(base_payload), encoding="utf-8")
    current_path = tmp_path / "cur.json"
    cur_payload = _summary([_row("case-a", "plan_first_pass")])
    cur_payload["evaluator_identity"]["run_context"]["repetitions"] = 1
    current_path.write_text(json.dumps(cur_payload), encoding="utf-8")

    report = module.compare(baseline_path, current_path, noise_margin=5)

    assert report["verdict"]["answer"] == "inconclusive_design_mismatch"


def test_matched_repetition_design_gets_margin_verdict(tmp_path: Path) -> None:
    module = _compare_module()
    baseline_path = tmp_path / "base.json"
    base_payload = _summary([_row("case-a", "plan_first_pass", verdict="fail")])
    base_payload["evaluator_identity"]["run_context"]["repetitions"] = 1
    baseline_path.write_text(json.dumps(base_payload), encoding="utf-8")
    current_path = tmp_path / "cur.json"
    cur_payload = _summary([_row("case-a", "plan_first_pass", verdict="pass")])
    cur_payload["evaluator_identity"]["run_context"]["repetitions"] = 1
    current_path.write_text(json.dumps(cur_payload), encoding="utf-8")

    report = module.compare(baseline_path, current_path, noise_margin=0)

    assert report["verdict"]["answer"] == "improved"


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

    # Two of three repetitions are first-pass, so the modal row represents
    # the case in every delta — but a build that disagrees with itself is
    # never given a direction.
    assert case["outcome"] == "plan_repaired -> plan_first_pass"
    assert case["mechanics_direction"] == "improved"
    assert case["direction"] == "inconclusive"
    assert case["current_unstable"] is True
