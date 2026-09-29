"""A benchmark verdict is stated per dimension, and a dimension nobody measured is never a pass.

Plan placement, review-edit delivery and final output each carry pass, fail or
unmeasured on their own. A required fact, an association or a reviewed edit on a
run that delivered nothing was never assessed, so it is `not_evaluated`, not a
failure. A harness refusal keeps the plan it scored. The receipt names the
scorer that judged it, and the comparator refuses two receipts from different
scorers.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

from pytest import MonkeyPatch, fixture, mark, raises

from tests.unittests.flows.ai_builder.test_ai_builder_api_battle_harness import (
    _applied_flow_from_plan,  # pyright: ignore[reportPrivateUsage]
    _awaiting_review_run,  # pyright: ignore[reportPrivateUsage]
    _battle_harness,  # pyright: ignore[reportPrivateUsage]
    _checkpoint,  # pyright: ignore[reportPrivateUsage]
    _complete_live_case_bundle,  # pyright: ignore[reportPrivateUsage]
    _completed_text_run,  # pyright: ignore[reportPrivateUsage]
    _execute,  # pyright: ignore[reportPrivateUsage]
    _execution,  # pyright: ignore[reportPrivateUsage]
    _review_policy_plan,  # pyright: ignore[reportPrivateUsage]
    _RuntimeApi,  # pyright: ignore[reportPrivateUsage]
)
from tests.unittests.flows.ai_builder.test_ai_builder_battle_compare import (
    _compare_module,  # pyright: ignore[reportPrivateUsage]
    _row,  # pyright: ignore[reportPrivateUsage]
    _summary,  # pyright: ignore[reportPrivateUsage]
)
from tests.unittests.flows.ai_builder.test_ai_builder_forbidden_literal_output import (
    _NO_DELIVERY,  # pyright: ignore[reportPrivateUsage]
    _scored_row,  # pyright: ignore[reportPrivateUsage]
)

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

edit = importlib.import_module("ai_builder_edit_expectation")
receipts = importlib.import_module("ai_builder_receipt")

_ALL_PASS = ("pass", "not_required", "not_required", "pass")
_PLAN_FAIL = ("fail", "not_required", "not_required", "fail")


@fixture(scope="module")
def harness() -> ModuleType:
    return _battle_harness()


# --- required facts and associations on a run that delivered nothing ---------


def _expect(harness: ModuleType, **overrides: Any) -> Any:
    return harness.OutputExpectation(
        output_kind="text",
        required_facts=("Njurunda", "Skogsmo"),
        associations=(
            harness.OutputAssociation(
                fact="Kod 17 03 01*", with_="asfalt", not_with="betong"
            ),
        ),
        **overrides,
    )


def _output_checks(
    harness: ModuleType, run_evidence: dict[str, object], name: str
) -> list[dict[str, Any]]:
    report = harness._output_report(
        _expect(harness),
        {"run_contract": {"final_output": {"output_type": "text"}}, **run_evidence},
        runtime_checks=[],
    )
    return [check for check in report["output_checks"] if check["name"] == name]


@mark.parametrize("delivery", sorted(_NO_DELIVERY))
@mark.parametrize("name", ["required_fact", "output_association"])
def test_a_check_of_the_delivered_text_is_not_evaluated_when_nothing_was_delivered(
    harness: ModuleType, delivery: str, name: str
) -> None:
    checks = _output_checks(harness, _NO_DELIVERY[delivery], name)

    assert checks
    assert [(c["passed"], c["status"]) for c in checks] == [
        (None, "not_evaluated")
    ] * len(checks)
    assert all("no output to inspect" in c["reason"] for c in checks)


def test_a_run_without_output_is_no_success_and_its_facts_are_no_failures(
    harness: ModuleType,
) -> None:
    report = harness._output_report(
        _expect(harness),
        {"run_contract": {"final_output": {"output_type": "text"}}}
        | _NO_DELIVERY["failed"],
        runtime_checks=[],
    )

    assert report["output_success"] is False
    failed = [c["name"] for c in report["output_checks"] if c["passed"] is False]
    assert "required_fact" not in failed
    assert "output_association" not in failed
    assert "run_completed" in failed


def _empty_report(harness: ModuleType, run_evidence: dict[str, object]) -> Any:
    return harness._output_report(
        _expect(harness, forbidden=("880521-2381",)),
        {"run_contract": {"final_output": {"output_type": "text"}}, **run_evidence},
        runtime_checks=[],
    )


@mark.parametrize(
    "run",
    [
        {
            "id": "run-1",
            "status": "completed",
            "result": {"kind": "inline_text", "text": ""},
        },
        {
            "id": "run-1",
            "status": "completed",
            "result": {"kind": "structured", "value": {}},
        },
    ],
    ids=["empty_text", "empty_structured_value"],
)
def test_a_run_that_delivered_an_empty_output_lost_its_facts_and_leaked_nothing(
    harness: ModuleType, run: dict[str, object]
) -> None:
    """Delivering nothing readable is a delivery that holds no fact, not a run
    with nothing to inspect: its facts are lost, its forbidden literals absent."""

    report = _empty_report(
        harness, {"execution": {"outcome": "completed", "failures": []}, "run": run}
    )
    by_name = {
        name: [c for c in report["output_checks"] if c["name"] == name]
        for name in ("required_fact", "forbidden_literal", "output_association")
    }

    assert [c["passed"] for c in by_name["required_fact"]] == [False, False]
    assert [c["passed"] for c in by_name["forbidden_literal"]] == [True]
    assert [c["passed"] for c in by_name["output_association"]] == [False]
    assert all("status" not in c for checks in by_name.values() for c in checks)
    assert report["output_success"] is False
    assert [
        c["passed"] for c in report["output_checks"] if c["name"] == "output_readable"
    ] == [False]


@mark.parametrize("delivery", sorted(_NO_DELIVERY))
def test_a_run_with_no_result_still_leaves_every_literal_check_unassessed(
    harness: ModuleType, delivery: str
) -> None:
    report = _empty_report(harness, _NO_DELIVERY[delivery])

    assert {
        (c["name"], c["passed"])
        for c in report["output_checks"]
        if c["name"] in {"required_fact", "forbidden_literal", "output_association"}
    } == {
        ("required_fact", None),
        ("forbidden_literal", None),
        ("output_association", None),
    }


@mark.parametrize(
    ("delivered", "required", "forbidden"),
    [(True, False, True), (False, None, None)],
    ids=["text_delivered", "nothing_delivered"],
)
def test_the_literal_scorer_reads_an_explicit_delivery_signal_not_the_text(
    delivered: bool, required: object, forbidden: object
) -> None:
    checks = edit.literal_checks(
        "",
        required=["startdatum"],
        forbidden=["2026-10-05"],
        normalize=str,
        delivered=delivered,
    )

    assert [c["passed"] for c in checks] == [required, forbidden]


def _completed(text: str) -> dict[str, object]:
    return {
        "execution": {"outcome": "completed", "failures": []},
        "run": _completed_text_run(text),
    }


def test_a_delivered_text_still_fails_a_fact_it_lacks(harness: ModuleType) -> None:
    delivered = _completed("Njurunda. Kod 17 03 01* asfalt.")
    facts = _output_checks(harness, delivered, "required_fact")
    assert [(c["fact"], c["passed"]) for c in facts] == [
        ("Njurunda", True),
        ("Skogsmo", False),
    ]
    assert all("status" not in c for c in facts)
    associations = _output_checks(harness, delivered, "output_association")
    assert [c["passed"] for c in associations] == [True]


@mark.parametrize(
    ("line", "passed"),
    [
        ("Kod 17 03 01* asfalt", True),
        # The delivered text escapes what the case wrote plainly.
        ("Kod 17 03 01\\* asfalt", True),
        ("Kod 17 03 01\\* av\\-fall: asfalt", True),
        ("Kod 17 03 01\\* betong", False),
        ("Kod 17 03 01\\* av annat", False),
        ("Kod 17 03 02\\* asfalt", False),
    ],
)
def test_an_association_reads_the_text_as_a_literal_check_does(
    harness: ModuleType, line: str, passed: bool
) -> None:
    checks = _output_checks(
        harness, _completed(f"Njurunda\n{line}"), "output_association"
    )

    assert [c["passed"] for c in checks] == [passed]


def test_a_row_records_a_fact_nobody_assessed_as_neither_held_nor_lost(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    failed = _scored_row(
        harness,
        monkeypatch,
        tmp_path,
        run={"id": "run-1", "status": "failed"},
        name="failed",
    )
    delivered = _scored_row(
        harness,
        monkeypatch,
        tmp_path,
        run=_completed_text_run("Skogsmo. Kod 17 03 02 för asfalt."),
        name="delivered",
    )

    assert failed["output_required_facts"] == {"Njurunda": None}
    assert "required_fact" not in failed["output_failed_checks"]
    assert delivered["output_required_facts"] == {"Njurunda": False}
    assert delivered["output_failed_checks"] == ["required_fact"]
    # The comparator counts only a held fact as delivered.
    counted = _compare_module()._target_count  # pyright: ignore[reportPrivateUsage]
    assert counted(failed, ["Njurunda"]) is None


def test_a_step_that_ran_and_wrote_nothing_still_misses_its_required_fact() -> None:
    rule = edit.StepOutput(required_facts=["startdatum"], forbidden=["2026-10-05"])

    empty = edit._step_output(  # pyright: ignore[reportPrivateUsage]
        rule, {"output_payload_json": {"text": ""}}
    )

    assert empty[0] is False
    assert [c["name"] for c in empty[1]["failed"]] == ["required_fact"]


def test_an_edit_whose_run_never_happened_has_an_unmeasured_run_output() -> None:
    checks = edit.add_execution(
        {"verdict": "pass", "checks": [], "failed_checks": [], "categories": []},
        SimpleNamespace(step_outputs={}),
        evidence={},
        output_success=None,
        step_results=None,
    )["checks"]

    assert [(c["name"], c["passed"]) for c in checks] == [("run_output", None)]


# --- the review-edit delivery check ------------------------------------------


def _oracle_entry(**oracle: object) -> dict[str, object]:
    return {"action": "edit_target", "edit_oracle": oracle}


_EDITED = {"path": ["belopp"], "value_type": "number", "old": 1, "new": 7920}


@mark.parametrize(
    ("entries", "passed"),
    [
        ([_oracle_entry(**_EDITED, old_absent_outside_edit=True)], "delivered"),
        # An edit was made and did not reach delivery: measured, and lost.
        (
            [_oracle_entry(**{**_EDITED, "new": 4711}, old_absent_outside_edit=True)],
            False,
        ),
        # No edit was ever made: the oracle did not run.
        ([], None),
        ([{"action": "approve"}], None),
        (
            [_oracle_entry(missing="the reviewed value has no leaf the target names")],
            None,
        ),
        (
            [
                _oracle_entry(
                    path=["ja"], value_type="boolean", old=True, unmeasured="x"
                )
            ],
            None,
        ),
        # One edit lost outweighs one that could not be made.
        (
            [
                _oracle_entry(missing="no leaf"),
                _oracle_entry(**{**_EDITED, "new": 4711}, old_absent_outside_edit=True),
            ],
            False,
        ),
    ],
    ids=[
        "delivered",
        "edited_and_lost",
        "no_checkpoint_reached",
        "approved_only",
        "no_target_leaf",
        "boolean_target",
        "lost_beside_unmeasured",
    ],
)
def test_a_review_edit_is_measured_only_where_an_edit_was_made(
    harness: ModuleType, entries: list[dict[str, object]], passed: object
) -> None:
    evidence = {
        "run": {"result": {"kind": "inline_text", "text": "Belopp 7 920 kr."}},
        "execution": {"run_request": {}, "checkpoints": entries},
    }

    check = harness._review_edit_delivery_check(evidence)

    assert check["passed"] is (True if passed == "delivered" else passed)
    if passed is None:
        assert check["status"] == "not_evaluated"
    else:
        assert "status" not in check


def test_a_review_edit_with_no_run_evidence_is_not_evaluated(
    harness: ModuleType,
) -> None:
    assert harness._review_edit_delivery_check(None)["passed"] is None


# --- verdict states ----------------------------------------------------------

_PLACEMENT_RIGHT = [["supplier"]]
_PLACEMENT_WRONG = [["underskott"]]


def _review_case(harness: ModuleType, groups: list[list[str]]) -> Any:
    return harness.BattleCase(
        case_id="reviewed-create",
        prompt="Build and run the Flow.",
        apply_plan=True,
        expected={
            "expected_review_policy": {
                "mode": "edit",
                "target_output_type": "json",
                "target_field_groups": groups,
                "target_must_be_non_terminal": True,
            }
        },
        execution=_execution(
            harness,
            checkpoints=(
                harness.ExpectedCheckpoint(
                    review_mode="edit", output_type="json", action="edit_target"
                ),
            ),
            required_facts=("Njurunda",),
        ),
    )


def _sealed_row(
    harness: ModuleType,
    tmp_path: Path,
    case: Any,
    *,
    evidence: dict[str, Any] | None,
    name: str,
    journey: str = "plan_first_pass",
) -> dict[str, Any]:
    """The case scored by the quality report on its own plan and run, then sealed."""

    plan = _review_policy_plan(mode="edit")
    bundle = _complete_live_case_bundle(harness, case)
    bundle["plan"] = plan
    bundle["journey"] = {"outcome_class": journey}
    bundle["runtime_evidence"] = evidence
    bundle["quality_report"] = harness._quality_report(
        plan=plan,
        summary=harness._summarize_plan(plan),
        expected=case.expected,
        runtime_evidence=evidence,
        output_expectation=case.execution.expect,
    )
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return harness._suite_result(harness.seal_observation(bundle), path)


def _review_run(
    harness: ModuleType,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    case: Any,
    *,
    runs: list[dict[str, object]],
    checkpoints: list[dict[str, object] | None],
) -> dict[str, Any]:
    api = _RuntimeApi(runs=runs, checkpoints=checkpoints)
    api.install(harness, monkeypatch)
    evidence, _ = _execute(
        harness,
        case.execution,
        tmp_path=tmp_path,
        review_target_names=tuple(
            name
            for group in case.expected["expected_review_policy"]["target_field_groups"]
            for name in group
        ),
    )
    return evidence


def _states(row: dict[str, Any]) -> dict[str, str]:
    return row["verdict_states"]


def test_a_delivered_review_edit_on_a_right_placement_is_a_whole_case_pass(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    case = _review_case(harness, _PLACEMENT_RIGHT)
    evidence = _review_run(
        harness,
        monkeypatch,
        tmp_path,
        case,
        runs=[
            _awaiting_review_run(),
            _completed_text_run("Njurunda: review-edit-cp-1."),
        ],
        checkpoints=[
            _checkpoint(
                output_type="json",
                current_payload_json={"structured": {"supplier": "Alfa", "score": 4}},
            )
        ],
    )

    row = _sealed_row(harness, tmp_path, case, evidence=evidence, name="delivered")

    assert _states(row) == {
        "plan": "pass",
        "review_edit": "pass",
        "output": "pass",
        "case": "pass",
    }


def test_an_edit_lost_in_delivery_fails_the_review_edit_and_the_case(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    case = _review_case(harness, _PLACEMENT_RIGHT)
    evidence = _review_run(
        harness,
        monkeypatch,
        tmp_path,
        case,
        runs=[_awaiting_review_run(), _completed_text_run("Njurunda, ingen ändring.")],
        checkpoints=[
            _checkpoint(
                output_type="json",
                current_payload_json={"structured": {"supplier": "Alfa"}},
            )
        ],
    )

    row = _sealed_row(harness, tmp_path, case, evidence=evidence, name="lost")

    assert _states(row) == {
        "plan": "pass",
        "review_edit": "fail",
        "output": "pass",
        "case": "fail",
    }


def test_a_review_the_harness_could_not_edit_is_unmeasured_never_a_pass(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """The plan put the review where the case wants it, but the reviewed value has
    no leaf the case names, so the harness stopped the run before any edit: the
    edit's delivery and the final output were never measured."""

    case = _review_case(harness, _PLACEMENT_RIGHT)
    evidence = _review_run(
        harness,
        monkeypatch,
        tmp_path,
        case,
        runs=[_awaiting_review_run(), {"id": "run-1", "status": "cancelled"}],
        checkpoints=[
            _checkpoint(
                output_type="json", current_payload_json={"structured": {"score": 4}}
            )
        ],
    )

    row = _sealed_row(harness, tmp_path, case, evidence=evidence, name="stopped")

    assert _states(row) == {
        "plan": "pass",
        "review_edit": "unmeasured",
        "output": "unmeasured",
        "case": "unmeasured",
    }
    # The published Builder-check verdict is what it always was.
    assert row["expectation_verdict"] == "fail"
    assert row["output_success"] is False
    assert row["output_required_facts"] == {"Njurunda": None}


def test_a_wrong_placement_fails_the_plan_beside_an_unmeasured_delivery(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    case = _review_case(harness, _PLACEMENT_WRONG)
    evidence = _review_run(
        harness,
        monkeypatch,
        tmp_path,
        case,
        runs=[_awaiting_review_run(), {"id": "run-1", "status": "cancelled"}],
        checkpoints=[
            _checkpoint(
                output_type="json",
                current_payload_json={"structured": {"supplier": "Alfa"}},
            )
        ],
    )

    row = _sealed_row(harness, tmp_path, case, evidence=evidence, name="misplaced")

    assert _states(row) == {
        "plan": "fail",
        "review_edit": "unmeasured",
        "output": "unmeasured",
        "case": "fail",
    }


def test_a_run_that_never_reached_its_declared_review_fails_it_without_an_edit(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    case = _review_case(harness, _PLACEMENT_RIGHT)
    evidence = _review_run(
        harness,
        monkeypatch,
        tmp_path,
        case,
        runs=[_completed_text_run("Njurunda.")],
        checkpoints=[],
    )

    row = _sealed_row(harness, tmp_path, case, evidence=evidence, name="no-pause")

    # The run did not complete through the checkpoint the case declared, which
    # the product owns; no edit was made, so its delivery is unmeasured.
    assert _states(row) == {
        "plan": "pass",
        "review_edit": "unmeasured",
        "output": "fail",
        "case": "fail",
    }


def test_a_failed_run_fails_its_output_without_counting_unassessed_facts(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    case = _review_case(harness, _PLACEMENT_RIGHT)
    evidence = _review_run(
        harness,
        monkeypatch,
        tmp_path,
        case,
        runs=[_awaiting_review_run(), {"id": "run-1", "status": "failed"}],
        checkpoints=[
            _checkpoint(
                output_type="json",
                current_payload_json={"structured": {"supplier": "Alfa"}},
            )
        ],
    )

    row = _sealed_row(harness, tmp_path, case, evidence=evidence, name="failed-run")

    assert _states(row)["output"] == "fail"
    assert _states(row)["case"] == "fail"
    assert row["output_required_facts"] == {"Njurunda": None}


def test_a_case_that_asks_for_no_delivery_takes_its_plan_verdict(
    harness: ModuleType, tmp_path: Path
) -> None:
    case = harness.BattleCase(case_id="plan-only", prompt="Build a Flow.")
    bundle = _complete_live_case_bundle(
        harness,
        case,
        quality_checks=[{"name": "plan_created", "passed": True}],
    )
    bundle["journey"] = {"outcome_class": "plan_first_pass"}
    path = tmp_path / "plan-only.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")

    row = harness._suite_result(harness.seal_observation(bundle), path)

    assert _states(row) == {
        "plan": "pass",
        "review_edit": "not_required",
        "output": "not_required",
        "case": "pass",
    }


def test_an_executed_case_that_ran_nothing_is_unmeasured_not_a_plan_only_pass(
    harness: ModuleType, tmp_path: Path
) -> None:
    case = harness.BattleCase(
        case_id="executed",
        prompt="Build and run.",
        apply_plan=True,
        execution=_execution(harness),
    )
    bundle = _complete_live_case_bundle(
        harness,
        case,
        quality_checks=[{"name": "plan_created", "passed": True}],
    )
    bundle["journey"] = {"outcome_class": "plan_first_pass"}
    path = tmp_path / "executed.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")

    row = harness._suite_result(harness.seal_observation(bundle), path)

    assert _states(row) == {
        "plan": "pass",
        "review_edit": "not_required",
        "output": "unmeasured",
        "case": "unmeasured",
    }


def test_the_suite_summary_counts_each_dimension_apart(harness: ModuleType) -> None:
    rows = [
        {
            "verdict_states": {
                "plan": "pass",
                "review_edit": "not_required",
                "output": "fail",
                "case": "fail",
            }
        },
        {
            "verdict_states": {
                "plan": "pass",
                "review_edit": "unmeasured",
                "output": "unmeasured",
                "case": "unmeasured",
            }
        },
        {
            "verdict_states": {
                "plan": "fail",
                "review_edit": "not_required",
                "output": "not_required",
                "case": "fail",
            }
        },
    ]

    counts = harness._suite_observation_summary(rows)["state_counts"]  # pyright: ignore[reportPrivateUsage]

    assert counts == {
        "plan": {"pass": 2, "fail": 1},
        "review_edit": {"not_required": 2, "unmeasured": 1},
        "output": {"fail": 1, "not_required": 1, "unmeasured": 1},
        "case": {"fail": 2, "unmeasured": 1},
    }


# --- a harness refusal keeps the plan ----------------------------------------


def _refusing_session(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> dict[str, Any]:
    """The real session, apply and run owners over a fake API: the published flow
    has no runtime file-input step, so the harness cannot start the run."""

    api = _RuntimeApi(runs=[_completed_text_run("unused")])
    plan = _review_policy_plan(mode="edit")
    monkeypatch.setattr(
        harness, "_create_session", lambda **_: {"session_id": "session-1"}
    )
    monkeypatch.setattr(
        harness,
        "_send_and_fetch",
        lambda **_: {"plan_id": "plan-1", "plan": plan, "events": []},
    )
    monkeypatch.setattr(
        harness, "_case_runtime_file_paths", lambda _case: (Path("export.json"),)
    )

    def request(*, method: str, path: str, **kwargs: object) -> object:
        if path.endswith("/models"):
            return {}
        if path == "/flows/flow-1/" and method == "GET":
            return _applied_flow_from_plan(plan)
        if path.endswith("/_diagnostics/classifier-slots"):
            return {"session_id": "session-1"}
        return api.request(method=method, path=path, **kwargs)

    monkeypatch.setattr(harness, "_request_json", request)
    monkeypatch.setattr(harness, "_request_no_content", request)
    monkeypatch.setattr(harness, "_optional_request_json", lambda **_: None)
    # The fake session records no telemetry to judge live provenance by.
    monkeypatch.setattr(
        harness, "_quality_report_with_live_provenance", lambda report, **_: report
    )
    case = _review_case(harness, _PLACEMENT_RIGHT)
    return harness._run_case_session(
        case=case,
        config=harness.ApiConfig(
            base_url="http://localhost:8123/api/v1",
            api_key="test-key",
            timeout_seconds=1,
        ),
        args=SimpleNamespace(
            space_id="space-1",
            model_id=None,
            ui_language="sv",
            file_ids=None,
            auto_confirm_requirements=False,
            timeout_seconds=1,
        ),
        existing_session_id=None,
        artifact_output_dir=tmp_path,
        cases_path=None,
        provisioned_fixtures=None,
        seeded_flow=None,
    )


def test_a_refused_run_keeps_and_scores_the_plan_it_was_given(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    bundle = _refusing_session(harness, monkeypatch, tmp_path)

    assert bundle["plan_id"] == "plan-1"
    assert bundle["plan"] is not None
    assert bundle["runtime_evidence"] is None
    assert "runtime file-input step" in bundle["harness_refusal"]["error"]
    placement = {
        check["name"]: check["passed"]
        for check in bundle["quality_report"]["checks"]
        if check["name"].startswith("proposed_review_policy")
    }
    assert placement["proposed_review_policy_target"] is True


def test_a_refused_run_is_an_unmeasured_slot_never_a_whole_case_pass(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    bundle = _refusing_session(harness, monkeypatch, tmp_path)
    case = _review_case(harness, _PLACEMENT_RIGHT)
    bundle["case_identity"] = harness._case_identity(case)
    bundle["case_contract_sha256"] = harness._case_contract_sha256(case)
    bundle["repetition"] = 1
    path = tmp_path / "refused.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")

    row = harness._suite_result(harness.seal_observation(bundle), path)

    assert row["observation_status"] == "execution_failure"
    assert row["outcome_class"] == "execution_failure"
    assert row["failure_class"] == "harness_configuration"
    assert row["expectation_verdict"] == "not_evaluated"
    assert row["failed_checks"] == []
    assert "runtime file-input step" in row["error"]
    assert _states(row) == {
        "plan": "pass",
        "review_edit": "unmeasured",
        "output": "unmeasured",
        "case": "unmeasured",
    }
    # The slot is still the instrument's to re-measure.
    observation = harness.observation_from_row(row, where="refused")
    assert harness.observation_is_replacement_eligible(observation) is True


def test_a_refused_required_case_stays_an_execution_failure_of_the_instrument(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """A refused slot keeps its plan but is still never observed as a whole: it
    carries no release identity checks to fail, so it stays re-measurable."""

    bundle = _refusing_session(harness, monkeypatch, tmp_path)
    required = replace(_review_case(harness, _PLACEMENT_RIGHT), required=True)
    monkeypatch.setattr(harness, "_run_case", lambda **_: bundle)

    row = harness._acquire_suite_observation(  # pyright: ignore[reportPrivateUsage]
        repetition=1,
        case_index=1,
        case=required,
        case_count=1,
        total_repetitions=1,
        config=object(),
        args=SimpleNamespace(),
        artifact_output_dir=tmp_path,
        cases_path=None,
        provisioned_fixtures={},
        acquisition_contract=harness.AcquisitionContract(
            required_case_ids=(required.case_id,)
        ),
        release_identity={},
        failure_execution_provenance={},
    )

    assert row["observation_status"] == "execution_failure"
    assert row["identity_failed_check_count"] == 0
    assert row["verdict_states"]["plan"] == "pass"
    observation = harness.observation_from_row(row, where="refused")
    assert harness.observation_is_replacement_eligible(observation) is True


def test_a_failure_without_a_plan_is_unmeasured_in_every_dimension(
    harness: ModuleType, tmp_path: Path
) -> None:
    case = _review_case(harness, _PLACEMENT_RIGHT)
    failure = {
        "artifact_mode": "live_execution_failure",
        "case_identity": harness._case_identity(case),
        "case_contract": harness._case_contract_payload(case),
        "case_contract_sha256": harness._case_contract_sha256(case),
        "repetition": 1,
        "error": "stack down",
        "failure_class": "dependency_stack",
    }
    path = tmp_path / "failure.json"
    path.write_text(json.dumps(failure), encoding="utf-8")

    row = harness._suite_result(harness.seal_observation(failure), path)

    assert _states(row) == {
        "plan": "unmeasured",
        "review_edit": "unmeasured",
        "output": "unmeasured",
        "case": "unmeasured",
    }


# --- an evidence status changes what a pass can mean -------------------------


def test_an_observation_whose_evidence_is_invalid_passes_nothing(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    case = _review_case(harness, _PLACEMENT_RIGHT)
    evidence = _review_run(
        harness,
        monkeypatch,
        tmp_path,
        case,
        runs=[
            _awaiting_review_run(),
            _completed_text_run("Njurunda: review-edit-cp-1."),
        ],
        checkpoints=[
            _checkpoint(
                output_type="json",
                current_payload_json={"structured": {"supplier": "Alfa"}},
            )
        ],
    )
    row = _sealed_row(harness, tmp_path, case, evidence=evidence, name="invalid")
    assert row["observation_status"] == "completed"

    bundle = json.loads((tmp_path / "invalid.json").read_text(encoding="utf-8"))
    bundle.pop("observation", None)
    bundle["observation_input_identity"] = {"verified": False}
    invalid = harness.seal_observation(bundle)["observation"]

    assert invalid["observation_status"] == "invalid_evidence"
    assert set(invalid["verdict_states"].values()) == {"unmeasured"}


def test_a_builder_that_ended_its_turn_in_error_failed_the_plan(
    harness: ModuleType, tmp_path: Path
) -> None:
    case = harness.BattleCase(case_id="plan-only", prompt="Build a Flow.")
    bundle = _complete_live_case_bundle(
        harness, case, quality_checks=[{"name": "plan_created", "passed": False}]
    )
    bundle["journey"] = {"outcome_class": "builder_error"}
    bundle["observation_input_identity"] = {"verified": False}

    observation = harness.seal_observation(bundle)["observation"]

    assert observation["observation_status"] == "error_terminated"
    assert observation["verdict_states"] == {
        "plan": "fail",
        "review_edit": "not_required",
        "output": "not_required",
        "case": "fail",
    }


# --- question ids ------------------------------------------------------------


def _question_check(
    harness: ModuleType,
    *,
    allow: bool,
    expected_ids: list[str],
    asked: list[str],
    plan: bool = True,
) -> bool | None:
    report = harness._quality_report(
        plan={"id": "plan-1"} if plan else None,
        summary={},
        expected={
            **({"allow_question_instead_of_plan": True} if allow else {}),
            "expected_question_event_ids": expected_ids,
        },
        event_summary={"question_event_ids": asked, "question_event_count": len(asked)},
        runtime_evidence=None,
        output_expectation=None,
    )
    return next(
        c["passed"]
        for c in report["checks"]
        if c["name"] == "expected_question_event_ids"
    )


@mark.parametrize(
    ("expected_ids", "asked", "plan", "passed"),
    [
        # A plan is allowed, so asking nothing breaks no promise.
        (["terminal_output"], [], True, True),
        (["terminal_output"], ["terminal_output"], False, True),
        (["a", "b"], ["b"], False, True),
        (["a", "b"], ["a", "b"], False, True),
        # A question the case did not name is still a failure, with or without a plan.
        (["terminal_output"], ["docx_output_mode"], False, False),
        (["terminal_output"], ["docx_output_mode"], True, False),
        (["terminal_output"], ["terminal_output", "docx_output_mode"], False, False),
    ],
)
def test_a_question_the_case_allows_instead_of_a_plan_may_be_a_subset_of_its_ids(
    harness: ModuleType,
    expected_ids: list[str],
    asked: list[str],
    plan: bool,
    passed: bool,
) -> None:
    assert (
        _question_check(
            harness, allow=True, expected_ids=expected_ids, asked=asked, plan=plan
        )
        is passed
    )


@mark.parametrize(
    ("asked", "passed"),
    [
        (["terminal_output"], True),
        ([], False),
        (["terminal_output", "docx_output_mode"], False),
        (["docx_output_mode"], False),
    ],
)
def test_a_question_the_case_requires_must_be_exactly_its_ids(
    harness: ModuleType, asked: list[str], passed: bool
) -> None:
    assert (
        _question_check(
            harness, allow=False, expected_ids=["terminal_output"], asked=asked
        )
        is passed
    )


# --- repetitions on a single-case part ---------------------------------------


def _single_case_args(tmp_path: Path, **overrides: object) -> SimpleNamespace:
    return SimpleNamespace(
        reanalyze_bundle=None,
        api_key="test-key",
        output_dir=str(tmp_path),
        replacement_suite_dir=None,
        space_id="space-1",
        base_url="http://localhost:8123/api/v1",
        timeout_seconds=1,
        cases_file=None,
        run_suite=False,
        sealed_targeted_suite=False,
        case_id=["interview_open_meeting_audio"],
        cohort=None,
        max_cases=None,
        file_ids=None,
        session_id=None,
        seed_calibration=False,
        repetitions=3,
        concurrency=1,
        model_id="model-a",
        **overrides,
    )


def test_a_single_case_part_runs_every_repetition_it_was_given(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    args = _single_case_args(tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr(harness, "_parse_args", lambda: args)
    monkeypatch.setattr(harness, "_provision_fixtures", lambda **_: {})
    monkeypatch.setattr(
        harness,
        "_run_suite",
        lambda **kwargs: captured.update(kwargs) or 0,
    )
    monkeypatch.setattr(
        harness,
        "_run_case",
        lambda **_: (_ for _ in ()).throw(AssertionError("ran once, not 3 times")),
    )

    assert harness.main() == 0

    cases = captured["cases"]
    assert isinstance(cases, list)
    assert [case.case_id for case in cases] == ["interview_open_meeting_audio"]
    assert captured["args"] is args
    assert args.repetitions == 3


def test_a_resumed_session_cannot_be_repeated(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    args = _single_case_args(tmp_path)
    args.session_id = "session-1"
    monkeypatch.setattr(harness, "_parse_args", lambda: args)
    monkeypatch.setattr(harness, "_provision_fixtures", lambda **_: {})
    monkeypatch.setattr(
        harness,
        "_run_case",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not run a session")),
    )
    monkeypatch.setattr(
        harness,
        "_run_suite",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not repeat a session")),
    )

    assert harness.main() == 1

    failure = json.loads(next(tmp_path.glob("*-failure.json")).read_text("utf-8"))
    assert "--session-id" in failure["error"]


# --- the scorer's identity ---------------------------------------------------


def test_the_evaluator_identity_names_the_scorer_that_judged_the_run(
    harness: ModuleType,
) -> None:
    identity = harness._suite_evaluator_identity(  # pyright: ignore[reportPrivateUsage]
        release_identity={"build": {"harness_sha256": "a" * 64}},
        run_context={},
        expected_observations=[],
    )

    assert identity["scorer_semantics_version"] == harness.SCORER_SEMANTICS_VERSION
    expected = hashlib.sha256()
    for module in harness._SCORER_MODULES:  # pyright: ignore[reportPrivateUsage]
        expected.update(hashlib.sha256((_SCRIPTS / module).read_bytes()).digest())
    assert identity["scorer_sha256"] == expected.hexdigest()


def test_the_scorer_digest_moves_when_a_scoring_module_changes(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    module = tmp_path / "scorer.py"
    module.write_text("LITERALS = 1\n", encoding="utf-8")
    monkeypatch.setattr(harness, "_SCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(harness, "_SCORER_MODULES", ("scorer.py",))
    before = harness._scorer_sha256()  # pyright: ignore[reportPrivateUsage]
    module.write_text("LITERALS = 2\n", encoding="utf-8")

    assert harness._scorer_sha256() != before  # pyright: ignore[reportPrivateUsage]


_DIGEST = "a" * 64


def _scored_by(
    tmp_path: Path,
    name: str,
    *,
    scorer: tuple[int, str] | None = None,
    **identity: object,
) -> Path:
    """A receipt scored by (version, digest of the scoring modules), or by the
    scorer that recorded neither."""

    path = tmp_path / name
    payload = _summary([_row("case-a", "plan_first_pass")])
    payload["evaluator_identity"].update(identity)
    if scorer is not None:
        payload["evaluator_identity"]["scorer_semantics_version"] = scorer[0]
        payload["evaluator_identity"]["scorer_sha256"] = scorer[1]
        # A receipt of the states scorer states them, and counts them.
        states = dict(zip(receipts.VERDICT_STATE_DIMENSIONS, _ALL_PASS, strict=True))
        payload["results"][0]["verdict_states"] = states
        payload["observation_summary"] = {
            "state_counts": receipts.verdict_state_counts([states])
        }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@mark.parametrize("waived", [False, True], ids=["plain", "harness_change_waived"])
def test_receipts_scored_by_different_semantics_are_never_compared(
    tmp_path: Path, waived: bool
) -> None:
    module = _compare_module()
    baseline = _scored_by(tmp_path, "base.json", scorer=(1, _DIGEST))
    current = _scored_by(tmp_path, "cur.json", scorer=(2, _DIGEST))

    with raises(SystemExit) as refused:
        module.compare(baseline, current, allow_harness_change=waived)

    assert "scorer_semantics_version" in str(refused.value)


def test_a_receipt_from_before_scorer_identity_is_not_a_receipt_scored_by_it(
    tmp_path: Path,
) -> None:
    module = _compare_module()
    old = _scored_by(tmp_path, "old.json")
    new = _scored_by(tmp_path, "new.json", scorer=(1, _DIGEST))

    with raises(SystemExit) as refused:
        module.compare(old, new)

    assert "scorer_semantics_version" in str(refused.value)
    # Two receipts of that same earlier scorer still compare.
    module.compare(old, _scored_by(tmp_path, "older.json"))


def test_a_scorer_module_change_refuses_comparison_unless_waived_like_the_harness(
    tmp_path: Path,
) -> None:
    module = _compare_module()
    baseline = _scored_by(tmp_path, "base.json", scorer=(1, "a" * 64))
    current = _scored_by(tmp_path, "cur.json", scorer=(1, "b" * 64))

    with raises(SystemExit) as refused:
        module.compare(baseline, current)
    assert "scorer_sha256" in str(refused.value)

    module.compare(baseline, current, allow_harness_change=True)


def test_an_unchanged_case_contract_cannot_hide_a_changed_harness(
    tmp_path: Path,
) -> None:
    module = _compare_module()
    same_cases = {"case-a": "1" * 64}
    baseline = _scored_by(tmp_path, "base.json", case_contract_sha256_by_id=same_cases)
    current = _scored_by(
        tmp_path,
        "cur.json",
        case_contract_sha256_by_id=same_cases,
        harness_sha256="9" * 64,
    )

    with raises(SystemExit) as refused:
        module.compare(baseline, current)

    assert "harness_sha256" in str(refused.value)


# --- the receipt reader ------------------------------------------------------


def _row_with_states(states: object) -> dict[str, Any]:
    return {
        **_row("case-a", "plan_first_pass"),
        "repetition": 1,
        "verdict_states": states,
    }


def test_a_receipt_row_carries_its_verdict_states_or_none() -> None:
    states = {
        "plan": "pass",
        "review_edit": "not_required",
        "output": "unmeasured",
        "case": "unmeasured",
    }

    assert (
        receipts.observation_from_row(
            _row_with_states(states), where="r"
        ).verdict_states
        == states
    )
    assert (
        receipts.observation_from_row(
            {**_row("case-a", "plan_first_pass"), "repetition": 1}, where="r"
        ).verdict_states
        is None
    )


@mark.parametrize(
    "states",
    [
        "pass",
        {"plan": "pass"},
        {
            "plan": "maybe",
            "review_edit": "pass",
            "output": "pass",
            "case": "pass",
        },
        {
            "plan": "not_required",
            "review_edit": "pass",
            "output": "pass",
            "case": "pass",
        },
    ],
    ids=[
        "not_an_object",
        "missing_dimensions",
        "unknown_state",
        "plan_is_always_required",
    ],
)
def test_a_malformed_verdict_state_makes_the_receipt_unreadable(
    states: object,
) -> None:
    with raises(receipts.ReceiptError, match="verdict_states"):
        receipts.observation_from_row(_row_with_states(states), where="r")


# --- the receipt reader holds the states to their own algebra ----------------


def _states_row(plan: str, review_edit: str, output: str, case: str) -> dict[str, Any]:
    return _row_with_states(
        {"plan": plan, "review_edit": review_edit, "output": output, "case": case}
    )


@mark.parametrize(
    ("plan", "review_edit", "output", "case"),
    [
        ("pass", "not_required", "not_required", "pass"),
        ("pass", "pass", "pass", "pass"),
        ("fail", "unmeasured", "unmeasured", "fail"),
        ("pass", "pass", "unmeasured", "unmeasured"),
        ("pass", "unmeasured", "fail", "fail"),
        ("unmeasured", "not_required", "not_required", "unmeasured"),
    ],
)
def test_a_case_state_that_follows_from_its_dimensions_is_readable(
    plan: str, review_edit: str, output: str, case: str
) -> None:
    row = _states_row(plan, review_edit, output, case)

    assert receipts.observation_from_row(row, where="r").verdict_states is not None
    assert receipts.case_state(row["verdict_states"]) == case


@mark.parametrize(
    ("plan", "review_edit", "output", "case"),
    [
        # A failed dimension is never a passed case.
        ("fail", "not_required", "not_required", "pass"),
        ("pass", "fail", "pass", "pass"),
        # Unmeasured is never a pass, and never outweighs a failure.
        ("pass", "unmeasured", "pass", "pass"),
        ("pass", "pass", "unmeasured", "pass"),
        ("fail", "unmeasured", "pass", "unmeasured"),
        # Every dimension passed, so the case cannot be less.
        ("pass", "pass", "pass", "fail"),
        ("pass", "not_required", "not_required", "unmeasured"),
    ],
)
@mark.parametrize("required", [False, True], ids=["optional", "required"])
def test_a_case_state_its_dimensions_contradict_makes_the_row_unreadable(
    plan: str, review_edit: str, output: str, case: str, required: bool
) -> None:
    with raises(receipts.ReceiptError, match="verdict_states.case"):
        receipts.observation_from_row(
            _states_row(plan, review_edit, output, case),
            where="r",
            require_verdict_states=required,
        )


def test_a_scorer_that_states_verdicts_cannot_leave_them_out() -> None:
    row = {**_row("case-a", "plan_first_pass"), "repetition": 1}

    assert receipts.observation_from_row(row, where="r").verdict_states is None
    with raises(receipts.ReceiptError, match="verdict_states"):
        receipts.observation_from_row(row, where="r", require_verdict_states=True)
    with raises(receipts.ReceiptError, match="verdict_states"):
        receipts.observation_from_row(
            {**row, "verdict_states": None}, where="r", require_verdict_states=True
        )


def _receipt_summary(
    tmp_path: Path,
    rows: list[dict[str, Any]],
    *,
    version: object = 1,
    digest: object = _DIGEST,
    counts: object = "derived",
) -> dict[str, Any]:
    payload = _summary(rows)
    if version is not None:
        payload["evaluator_identity"]["scorer_semantics_version"] = version
    if digest is not None:
        payload["evaluator_identity"]["scorer_sha256"] = digest
    if counts == "derived":
        counts = receipts.verdict_state_counts(
            row["verdict_states"] for row in rows if "verdict_states" in row
        )
    if counts is not None:
        payload["observation_summary"] = {"state_counts": counts}
    return payload


def _stated_rows() -> list[dict[str, Any]]:
    return [
        {**_states_row(*_ALL_PASS), "case_id": "case-a"},
        {**_states_row(*_PLAN_FAIL), "case_id": "case-b"},
    ]


def test_a_receipt_of_the_states_scorer_is_read_when_its_counts_follow_its_rows(
    tmp_path: Path,
) -> None:
    receipt = receipts.receipt_from_summary(
        _receipt_summary(tmp_path, _stated_rows()), where="receipt"
    )

    assert [o.verdict_states["case"] for o in receipt.observations] == ["pass", "fail"]  # type: ignore[index]
    assert receipt.summary["observation_summary"]["state_counts"]["case"] == {
        "fail": 1,
        "pass": 1,
    }


@mark.parametrize(
    "counts",
    [
        None,
        {},
        {
            "plan": {"pass": 2},
            "review_edit": {"not_required": 2},
            "output": {"not_required": 2},
            "case": {"pass": 2},
        },
    ],
    ids=["absent", "empty", "counts_of_other_rows"],
)
def test_state_counts_that_disagree_with_the_rows_refuse_the_receipt(
    tmp_path: Path, counts: object
) -> None:
    with raises(receipts.ReceiptError, match="state_counts"):
        receipts.receipt_from_summary(
            _receipt_summary(tmp_path, _stated_rows(), counts=counts), where="receipt"
        )


def test_a_receipt_of_the_states_scorer_needs_a_state_on_every_row(
    tmp_path: Path,
) -> None:
    rows = [*_stated_rows(), {**_row("case-c", "plan_first_pass"), "repetition": 1}]

    with raises(receipts.ReceiptError, match="verdict_states"):
        receipts.receipt_from_summary(
            _receipt_summary(tmp_path, rows, counts={}), where="receipt"
        )


def test_a_row_that_contradicts_itself_refuses_the_receipt_whatever_the_counts(
    tmp_path: Path,
) -> None:
    rows = [
        {**_states_row("fail", "not_required", "not_required", "pass"), "case_id": "a"}
    ]

    with raises(receipts.ReceiptError, match="verdict_states.case"):
        receipts.receipt_from_summary(_receipt_summary(tmp_path, rows), where="receipt")


def test_a_receipt_from_before_verdict_states_is_still_readable(tmp_path: Path) -> None:
    rows = [{**_row("case-a", "plan_first_pass"), "repetition": 1}]

    receipt = receipts.receipt_from_summary(
        _receipt_summary(tmp_path, rows, version=None, digest=None, counts=None),
        where="receipt",
    )

    assert [o.verdict_states for o in receipt.observations] == [None]


@mark.parametrize("version", ["1", 1.0, True, 0, -1])
def test_a_scorer_version_that_is_no_positive_integer_refuses_the_receipt(
    tmp_path: Path, version: object
) -> None:
    with raises(receipts.ReceiptError, match="scorer_semantics_version"):
        receipts.receipt_from_summary(
            _receipt_summary(tmp_path, _stated_rows(), version=version), where="receipt"
        )


def test_the_harness_writes_the_counts_the_reader_derives(harness: ModuleType) -> None:
    rows = _stated_rows()

    written = harness._suite_observation_summary(rows)["state_counts"]  # pyright: ignore[reportPrivateUsage]

    assert written == receipts.verdict_state_counts(r["verdict_states"] for r in rows)


def test_every_state_the_harness_seals_is_one_the_reader_accepts(
    harness: ModuleType, tmp_path: Path
) -> None:
    plan_only = harness.BattleCase(case_id="plan-only", prompt="Build a Flow.")
    executed = harness.BattleCase(
        case_id="executed",
        prompt="Build and run.",
        apply_plan=True,
        execution=_execution(harness),
    )
    rows: list[dict[str, Any]] = []
    for case in (plan_only, executed):
        bundle = _complete_live_case_bundle(
            harness, case, quality_checks=[{"name": "plan_created", "passed": True}]
        )
        bundle["journey"] = {"outcome_class": "plan_first_pass"}
        path = tmp_path / f"{case.case_id}.json"
        path.write_text(json.dumps(bundle), encoding="utf-8")
        rows.append(harness._suite_result(harness.seal_observation(bundle), path))

    assert [row["verdict_states"]["case"] for row in rows] == ["pass", "unmeasured"]
    for row in rows:
        observation = receipts.observation_from_row(
            row, where="sealed", require_verdict_states=True
        )
        assert observation.verdict_states == row["verdict_states"]


# --- the scorer identity is one pair -----------------------------------------


def test_a_receipt_records_its_scorer_as_a_version_and_its_digest_or_neither(
    tmp_path: Path,
) -> None:
    stated = receipts.receipt_from_summary(
        _receipt_summary(tmp_path, _stated_rows()), where="receipt"
    )
    assert stated.observations[0].verdict_states is not None

    legacy_rows = [{**_row("case-a", "plan_first_pass"), "repetition": 1}]
    receipts.receipt_from_summary(
        _receipt_summary(tmp_path, legacy_rows, version=None, digest=None, counts=None),
        where="receipt",
    )


@mark.parametrize(
    ("identity", "names"),
    [
        ({"scorer_semantics_version": 1}, "scorer_sha256"),
        ({"scorer_sha256": _DIGEST}, "scorer_semantics_version"),
        (
            {"scorer_semantics_version": None, "scorer_sha256": _DIGEST},
            "scorer_semantics_version",
        ),
        ({"scorer_semantics_version": 1, "scorer_sha256": None}, "scorer_sha256"),
        (
            {"scorer_semantics_version": None, "scorer_sha256": None},
            "scorer_semantics_version",
        ),
        *(
            ({"scorer_semantics_version": 1, "scorer_sha256": digest}, "scorer_sha256")
            for digest in ("", "A" * 64, "a" * 63, "a" * 65, "g" * 64, 7, [_DIGEST])
        ),
    ],
    ids=[
        "digest_absent",
        "version_absent",
        "version_null",
        "digest_null",
        "both_null",
        "digest_empty",
        "digest_uppercase",
        "digest_short",
        "digest_long",
        "digest_not_hex",
        "digest_number",
        "digest_list",
    ],
)
def test_a_half_recorded_or_malformed_scorer_identity_refuses_the_receipt(
    identity: dict[str, object], names: str
) -> None:
    payload = _summary(_stated_rows())
    payload["observation_summary"] = {
        "state_counts": receipts.verdict_state_counts(
            row["verdict_states"] for row in _stated_rows()
        )
    }
    payload["evaluator_identity"].update(identity)

    with raises(receipts.ReceiptError, match=names):
        receipts.receipt_from_summary(payload, where="receipt")


def test_two_receipts_of_the_states_scorer_without_digests_are_refused_unread(
    tmp_path: Path,
) -> None:
    module = _compare_module()
    stated = [{**_states_row(*_ALL_PASS), "case_id": "case-a"}]
    paths = []
    for name in ("base.json", "cur.json"):
        payload = _receipt_summary(tmp_path, stated, digest=None)
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths.append(path)

    # Equal on every field they record, they would compare as the same scorer.
    assert _summary(stated)["evaluator_identity"].get("scorer_sha256") is None
    with raises(ValueError, match="scorer_sha256"):
        module.compare(*paths)
