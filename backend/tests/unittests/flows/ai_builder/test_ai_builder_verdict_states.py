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
    _completed_structured_run,  # pyright: ignore[reportPrivateUsage]
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
    return {
        "action": "edit_target",
        "checkpoint": {"step_order": 2},
        "edit_oracle": oracle,
    }


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
        # The reviewed step delivers its field at the path the edit names.
        "run": {"result": {"kind": "structured", "value": {"belopp": 7920}}},
        "run_contract": {"final_output": {"output_type": "json", "step_order": 2}},
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


def _review_case(
    harness: ModuleType, groups: list[list[str]], *, output_kind: str = "text"
) -> Any:
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
            output_kind=output_kind,
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
    output_type: str = "text",
) -> dict[str, Any]:
    api = _RuntimeApi(
        runs=runs,
        checkpoints=checkpoints,
        # The reviewed step delivers the run's result.
        contract={
            "final_output": {
                "output_type": output_type,
                "step_order": _checkpoint()["step_order"],
            }
        },
    )
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


def test_a_delivered_review_edit_on_a_right_placement_passes_beside_an_ungraded_plan(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    case = _review_case(harness, _PLACEMENT_RIGHT, output_kind="json")
    evidence = _review_run(
        harness,
        monkeypatch,
        tmp_path,
        case,
        output_type="json",
        runs=[
            _awaiting_review_run(),
            # The flow delivers the reviewed supplier at its own field.
            _completed_structured_run(
                {"kommun": "Njurunda", "supplier": "review-edit-cp-1"}
            ),
        ],
        checkpoints=[
            _checkpoint(
                output_type="json",
                current_payload_json={"structured": {"supplier": "Alfa", "score": 4}},
            )
        ],
    )

    row = _sealed_row(harness, tmp_path, case, evidence=evidence, name="delivered")

    # A Builder plan has no step-content gold: right placement is no plan pass.
    assert _states(row) == {
        "plan": "unmeasured",
        "review_edit": "pass",
        "output": "pass",
        "case": "unmeasured",
    }
    # Every check passed, but the case was not measured: no conformance pass.
    assert row["failed_checks"] == []
    assert row["expectation_verdict"] == "not_evaluated"


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
        "plan": "unmeasured",
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
        "plan": "unmeasured",
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
        "plan": "unmeasured",
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
    # A plan its step-content grader measured.
    bundle = _complete_live_case_bundle(
        harness,
        case,
        quality_checks=[
            {"name": "plan_created", "passed": True},
            {"name": harness.PLAN_CONTENT_GRADER, "passed": True},
        ],
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
        "plan": "unmeasured",
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
    # The kept plan is scored: its checks pass, and without step-content gold
    # it is unmeasured, as any Builder plan is.
    assert _states(row) == {
        "plan": "unmeasured",
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
    assert row["verdict_states"]["plan"] == "unmeasured"
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


def test_receipts_of_these_graders_name_scorer_semantics_2_or_later(
    harness: ModuleType,
) -> None:
    """Scorer 1 passed a literal inside a longer token and a plan on names
    alone: a receipt of these graders must never claim its identity."""

    assert harness.SCORER_SEMANTICS_VERSION >= 2


@mark.parametrize(
    "module",
    [
        "ai_builder_edit_expectation.py",
        "ai_builder_oracle_arm.py",
        "ai_builder_receipt.py",
    ],
)
def test_the_scorer_digest_moves_with_each_module_whose_bytes_decide_a_verdict(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path, module: str
) -> None:
    """The literal rule, the oracle arm's plan grader and the receipt reader
    decide verdicts beside the harness: a change to any of them is another
    scorer."""

    for name in harness._SCORER_MODULES:  # pyright: ignore[reportPrivateUsage]
        (tmp_path / name).write_bytes((_SCRIPTS / name).read_bytes())
    monkeypatch.setattr(harness, "_SCRIPTS_DIR", tmp_path)
    before = harness._scorer_sha256()  # pyright: ignore[reportPrivateUsage]
    path = tmp_path / module
    path.write_bytes((_SCRIPTS / module).read_bytes() + b"\n# changed\n")

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
            harness,
            case,
            quality_checks=[
                {"name": "plan_created", "passed": True},
                {"name": harness.PLAN_CONTENT_GRADER, "passed": True},
            ],
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


# --- graders of the confirmed false-pass classes -----------------------------
#
# Each grader names its gold and when it applies; where the gold is missing or
# cannot decide, the dimension it grades is unmeasured, never a pass.

# (literal, delivered text, the literal holds in it)
_LITERAL_TABLE: list[tuple[str, str, bool]] = [
    ("8 120", "Summa 8120 kr.", True),
    ("8120", "Summa 8 120 kr.", True),
    ("8 150", "Summa 8 150,00 kr.", True),
    ("10,6", "Temperatur 10,60 grader.", True),
    ("30 m", "Staketet är 30 m långt.", True),
    ("2026-09-21", "Beslutat 2026-09-21.", True),
    ("KS-2026-00866", "Dnr KS-2026-00866, se bilaga.", True),
    ("3.4.1", "Enligt avsnitt 3.4.1.", True),
    # A comma-separated row: the next field is no decimal of the value.
    ("VON 2026/00588", "10,2026-08-12,VON 2026/00588,7.1,Tobias Grahn", True),
    # A street number beside a postcode is no thousands group.
    ("Sidsjövägen 17", "Adress: Sidsjövägen 17  851 86 Sundsvall", True),
    ("12 345 678", "Kontonummer 12345678.", True),
    # Table cells read as lines: each cell's number is its own.
    ("9 655", "Åk 7–9\n\n9 655\n\nnovember", True),
    # A word or name holds as text: Swedish inflects and compounds it.
    ("Granbacka", "Paviljong vid Granbackaskolan.", True),
    ("förhandl", "Karin förhandlar om avtalet.", True),
    # A stated value extended into another value.
    ("30 m", "Beslut den 30 mars.", False),
    ("5 arbetsdagar", "Svar inom 15 arbetsdagar.", False),
    ("8 kap. 5 §", "Enligt 18 kap. 5 § gäller.", False),
    ("104233", "Anställningsnummer 1042331.", False),
    ("03:31", "Larm klockan 03:311.", False),
    ("Lindbacken 3:10", "Svar från Lindbacken 3:101.", False),
    ("3.4.1", "Enligt avsnitt 3.4.12.", False),
    # A number read as a whole number, by value.
    ("8 150", "Kvoten 0,8150 anges.", False),
    ("8 150", "Saldo -8150 kr.", False),
    ("8 150", "Summa 8150e3.", False),
    ("10,6", "Temperatur 10,61 grader.", False),
    # The whole number is read first (sign, leading decimal point, exponent),
    # then its unit: a value is never found inside another value.
    ("8150", "Summa 8150e+3.", False),
    ("8150", "Summa 8150E-3 kr.", False),
    ("8150", "Kvoten .8150 anges.", False),
    ("8150", ".8150", False),
    ("8150", "Värdet 8150.5 kr.", False),
    ("8150", "Saldo -8150.", False),
    ("-8150", "Saldo -8150.", True),
    ("1000", "Värdet 1e3.", True),
    ("1e3", "Värdet 1000.", True),
    ("8150e+3", "Summa 8150e+3.", True),
    ("0,5", "Andel ,5 av beloppet.", True),
    # A point after a word is no decimal point: the number is its own.
    ("8150", "Se kap.8150 i lagen.", True),
    # A value is exact at any exponent and any number of digits: never
    # rounded or flushed to zero by a decimal context.
    ("1", "Värdet 1e99999999999.", False),
    ("0", "Värdet 1e-1000027.", False),
    ("1e-1000027", "Värdet 10e-1000028.", True),
    ("12345678901234567890123456789", "Värdet 12345678901234567890123456789e0.", True),
    ("12345678901234567890123456790", "Värdet 12345678901234567890123456789e0.", False),
    ("12345678901234567890123456789e0", "Värdet 12345678901234567890123456790.", False),
    # An exponent too large to represent equals only its own spelling.
    ("1e100000000000000000000", "Värdet 1e100000000000000000000.", True),
    ("10e99999999999999999999", "Värdet 1e100000000000000000000.", False),
    # An ambiguous form is never guessed: it equals only its own spelling.
    ("1,500", "Vikt 1.500 ton.", False),
    # A date, a time and an id are one token: a number is not inside them.
    ("30", "Beslutat 2026-09-30.", False),
    ("30", "Möte klockan 12:30.", False),
    ("2026", "Ärende KS-2026.", False),
    ("12345", "Se ref-12345.", False),
    ("12345", "Se id_12345.", False),
    ("8150", "Nummer 8150-2.", False),
    ("8150", "Se https://x/8150.", False),
    ("8150", "Kod a8150.", False),
    ("2026-09-30", "Beslutat 2026-09-30.", True),
    ("2026-09-30", "Datum 12026-09-30.", False),
    ("2026-09-30", "Datum 30.09.2026.", False),
    # An ISO date is the date of an ISO date and time.
    ("2026-09-30", "Mötet 2026-09-30T10:00Z.", True),
    # Letters right after a number are its unit, a token of their own.
    ("8150", "Pris 8150kr.", True),
    ("22", "Sträckan 22m.", True),
    ("50 %", "Andel 50%.", True),
    ("50%", "Andel 50 %.", True),
    ("30 m", "Staketet är 30m långt.", True),
    ("30 m", "Avstånd 30 km.", False),
    ("30 m", "Avstånd 30 mm.", False),
    # A leading zero makes an identifier: it equals only its own spelling.
    ("007", "Antal 7.", False),
    ("7", "Kod 007.", False),
    ("007", "Kod 007.", True),
    # A sign belongs to its number; a mark after a letter is no sign.
    ("2184", "Saldo −2 184.", False),
    ("-2184", "Saldo 2 184.", False),
]


def _text_report(
    harness: ModuleType,
    text: str,
    *,
    required: tuple[str, ...] = (),
    forbidden: tuple[str, ...] = (),
    associations: tuple[Any, ...] = (),
) -> dict[str, Any]:
    return harness._output_report(
        harness.OutputExpectation(
            output_kind="text",
            required_facts=required,
            forbidden=forbidden,
            associations=associations,
        ),
        {"run_contract": {"final_output": {"output_type": "text"}}, **_completed(text)},
        runtime_checks=[],
    )


def _passed(report: dict[str, Any], name: str) -> list[object]:
    return [c["passed"] for c in report["output_checks"] if c["name"] == name]


@mark.parametrize(("literal", "text", "holds"), _LITERAL_TABLE)
def test_a_literal_holds_only_as_itself_in_facts_forbidden_literals_and_edit_gold(
    harness: ModuleType, literal: str, text: str, holds: bool
) -> None:
    fact = _passed(_text_report(harness, text, required=(literal,)), "required_fact")
    leak = _passed(
        _text_report(harness, text, forbidden=(literal,)), "forbidden_literal"
    )
    gold = edit.literal_checks(
        text,
        required=[literal],
        forbidden=[literal],
        normalize=edit.normalized_text,
        delivered=True,
    )

    assert fact == [holds]
    assert leak == [not holds]
    # One literal rule: edit gold and the run's facts agree on every row.
    assert [c["passed"] for c in gold] == [*fact, *leak]


@mark.parametrize(
    ("literal", "text", "holds"), [row for row in _LITERAL_TABLE if "\n" not in row[1]]
)
def test_an_association_reads_a_line_with_the_same_literal_rule(
    harness: ModuleType, literal: str, text: str, holds: bool
) -> None:
    association = harness.OutputAssociation(fact=literal, with_="✓", not_with="✗")

    report = _text_report(harness, f"{text} ✓", associations=(association,))

    assert _passed(report, "output_association") == [holds]


_KYL_FACTS = ("10,6", "8,6")
_KYL_RIGHT = "Kyldisk café: 10,6 grader\nKylrum bageri: 8,6 grader"
_KYL_SWAPPED = "Kyldisk café: 8,6 grader\nKylrum bageri: 10,6 grader"


def _output_states(harness: ModuleType, report: dict[str, Any]) -> dict[str, str]:
    bundle = {
        "case": {"expected": {}, "execution": {"expect": {}}},
        "runtime_evidence": {"execution": {"failures": []}},
        "quality_report": {
            "checks": [],
            "delivery_check_names": [],
            "output_checks": report["output_checks"],
        },
    }
    return harness._verdict_states(bundle, observation_status="completed")


def _binding(harness: ModuleType, report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        c for c in report["output_checks"] if c["name"] == harness.OUTPUT_BINDING_GRADER
    ]


@mark.parametrize("text", [_KYL_RIGHT, _KYL_SWAPPED], ids=["right", "swapped"])
def test_two_required_values_without_binding_gold_leave_the_output_unmeasured(
    harness: ModuleType, text: str
) -> None:
    """Every literal is present either way: without gold that binds each value
    to its subject, a swap cannot be told from the right output."""

    report = _text_report(harness, text, required=_KYL_FACTS)

    assert _passed(report, "required_fact") == [True, True]
    [binding] = _binding(harness, report)
    assert (binding["passed"], binding["status"]) == (None, "unmeasured")
    assert "10,6" in binding["reason"] and "8,6" in binding["reason"]
    assert report["output_success"] is None
    assert _output_states(harness, report)["output"] == "unmeasured"


@mark.parametrize(
    ("text", "state"),
    [(_KYL_RIGHT, "pass"), (_KYL_SWAPPED, "fail")],
    ids=["right", "swapped"],
)
def test_binding_gold_fails_two_values_that_exchanged_places(
    harness: ModuleType, text: str, state: str
) -> None:
    bound = harness.OutputAssociation(fact="10,6", with_="Kyldisk", not_with="Kylrum")

    report = _text_report(harness, text, required=_KYL_FACTS, associations=(bound,))

    [binding] = _binding(harness, report)
    assert binding["passed"] is (state == "pass")
    assert report["output_success"] is (state == "pass")
    assert _output_states(harness, report)["output"] == state


def test_a_single_required_value_has_nothing_to_exchange_places_with(
    harness: ModuleType,
) -> None:
    report = _text_report(harness, _KYL_RIGHT, required=("10,6",))

    [binding] = _binding(harness, report)
    assert binding["passed"] is True
    assert _output_states(harness, report)["output"] == "pass"


def test_an_output_scored_without_its_binding_grader_is_never_a_pass(
    harness: ModuleType,
) -> None:
    report = _text_report(harness, _KYL_RIGHT, required=("10,6",))
    legacy = {
        "output_checks": [
            c
            for c in report["output_checks"]
            if c["name"] != harness.OUTPUT_BINDING_GRADER
        ]
    }

    assert _output_states(harness, legacy)["output"] == "unmeasured"


def _plan_states(harness: ModuleType, checks: list[dict[str, Any]]) -> dict[str, str]:
    bundle = {
        "case": {"expected": {}},
        "quality_report": {"checks": checks, "delivery_check_names": []},
    }
    return harness._verdict_states(bundle, observation_status="completed")


def test_a_plan_whose_remaining_checks_pass_is_unmeasured_without_step_content_gold(
    harness: ModuleType,
) -> None:
    """A Builder plan has no gold for what each step must do: its name and count
    checks passing says nothing about steps that swapped their instructions."""

    checks = [
        {"name": "plan_created", "passed": True},
        {"name": "expected_leaf_output_fields", "passed": True},
    ]

    assert _plan_states(harness, checks) == {
        "plan": "unmeasured",
        "review_edit": "not_required",
        "output": "not_required",
        "case": "unmeasured",
    }
    assert (
        _plan_states(harness, [*checks[:1], {**checks[1], "passed": False}])["plan"]
        == "fail"
    )


@mark.parametrize(
    ("graded", "state"), [(True, "pass"), (False, "fail"), (None, "unmeasured")]
)
def test_a_plan_is_decided_by_its_step_content_grader(
    harness: ModuleType, graded: bool | None, state: str
) -> None:
    checks = [
        {"name": "plan_created", "passed": True},
        {"name": harness.PLAN_CONTENT_GRADER, "passed": graded},
    ]

    assert _plan_states(harness, checks)["plan"] == state


_OLD, _NEW = "Alfa Bygg AB", "review-edit-cp-1"
# The reviewed step and the template step that fills the delivered document.
_REVIEWED_STEP, _TEMPLATE_STEP = 2, 3


def _template_delivery(
    document: str,
    resolved: dict[str, str],
    bindings: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run evidence of a document a template step filled: its binding map, its
    placeholders and the values the runtime resolved for them."""

    bindings = bindings or {
        "leverantor": f"{{{{ step_{_REVIEWED_STEP}.output.structured.supplier }}}}",
        # Another field of the reviewed step, and the same field of another
        # step: neither is the reviewed field's location.
        "kontakt": f"{{{{ step_{_REVIEWED_STEP}.output.structured.kontaktperson }}}}",
        "sokande": "{{ step_1.output.structured.supplier }}",
        "fotnot": f"{{{{ step_{_REVIEWED_STEP}.output.text }}}}",
    }
    return {
        "run": {"result": {"kind": "artifact", "files": []}},
        "final_artifact": {"text": document},
        "run_contract": {
            "final_output": {
                "output_mode": "template_fill",
                "output_type": "docx",
                "step_order": _TEMPLATE_STEP,
            }
        },
        "definition_snapshot": {
            "steps": [
                {
                    "step_order": _TEMPLATE_STEP,
                    "output_mode": "template_fill",
                    "output_config": {
                        "bindings": bindings,
                        "placeholders": list(bindings),
                    },
                }
            ]
        },
        "step_results": [
            {
                "step_order": _TEMPLATE_STEP,
                "input_payload_json": {
                    "source_text": json.dumps(resolved, ensure_ascii=False)
                },
            }
        ],
    }


def _reviewed(
    harness: ModuleType,
    delivered: str | dict[str, Any],
    *,
    attributable: bool,
    path: tuple[str | int, ...] = ("supplier",),
    delivering_step: int = _REVIEWED_STEP,
) -> dict[str, Any]:
    """The review edit check of one edit of the reviewed step's `path`: the
    delivered output is inline text, a structured value `delivering_step`
    delivered, or run evidence of a filled template (`_template_delivery`)."""

    delivery = (
        {"run": {"result": {"kind": "inline_text", "text": delivered}}}
        if isinstance(delivered, str)
        else delivered
        if "run" in delivered
        else {
            "run": {"result": {"kind": "structured", "value": delivered}},
            "run_contract": {
                "final_output": {"output_type": "json", "step_order": delivering_step}
            },
        }
    )
    evidence = {
        **delivery,
        "execution": {
            # A run with file inputs: the old value may come from them.
            "run_request": {} if attributable else {"step_inputs": {"s1": ["file-1"]}},
            "checkpoints": [
                {
                    "action": "edit_target",
                    "checkpoint": {"step_order": _REVIEWED_STEP},
                    "edit_oracle": {
                        "path": list(path),
                        "value_type": "string",
                        "old": _OLD,
                        "new": _NEW,
                        "old_absent_outside_edit": True,
                    },
                }
            ],
        },
    }
    return harness._review_edit_delivery_check(evidence)


def _review_edit_state(harness: ModuleType, check: dict[str, Any]) -> str:
    bundle = {
        "case": {
            "expected": {"expected_review_policy": {"mode": "edit"}},
            "execution": {"expect": {}},
        },
        "runtime_evidence": {"execution": {"failures": []}},
        "quality_report": {
            "checks": [check],
            "delivery_check_names": [check["name"]],
            "output_checks": [],
        },
    }
    return harness._verdict_states(bundle, observation_status="completed")[
        "review_edit"
    ]


def test_an_old_value_back_at_the_reviewed_place_with_the_new_in_a_footer_is_no_pass(
    harness: ModuleType,
) -> None:
    footer = f"Leverantör: {_OLD}.\n\n{_NEW}"

    unattributable = _reviewed(harness, footer, attributable=False)
    attributable = _reviewed(harness, footer, attributable=True)

    assert (unattributable["passed"], unattributable["status"]) == (None, "unmeasured")
    assert _review_edit_state(harness, unattributable) == "unmeasured"
    assert attributable["passed"] is False
    assert _review_edit_state(harness, attributable) == "fail"


@mark.parametrize(
    "text",
    [
        f"Beslut om upphandling.\nFotnot: {_NEW}",
        f"Beslut om upphandling.\nKontaktperson: {_NEW}",
        f"Beslut om upphandling.\nLeverantör: {_NEW}",
        f"Beslut om upphandling.\n\n{_NEW}",
    ],
    ids=["footnote", "other_field", "labelled_line", "last_line"],
)
@mark.parametrize("attributable", [True, False])
def test_free_text_has_no_location_for_the_reviewed_field_so_the_edit_is_unmeasured(
    harness: ModuleType, text: str, attributable: bool
) -> None:
    """Free text names no field: whether the new value stands where the
    reviewed supplier stood, or in a footnote or another field, is unknowable
    without wording rules, so a delivered new value is never a pass there."""

    check = _reviewed(harness, text, attributable=attributable)

    assert (check["passed"], check["status"]) == (None, "unmeasured")
    assert check["actual"][0]["location"] is None
    assert _review_edit_state(harness, check) == "unmeasured"


@mark.parametrize("attributable", [True, False])
def test_a_structured_delivery_decides_the_edit_at_the_field_its_path_names(
    harness: ModuleType, attributable: bool
) -> None:
    at_field = _reviewed(
        harness, {"supplier": _NEW, "kontaktperson": "Eva"}, attributable=attributable
    )
    elsewhere = _reviewed(
        harness,
        {"supplier": "Beta Bygg AB", "fotnot": _NEW},
        attributable=attributable,
    )
    no_field = _reviewed(harness, {"kontaktperson": _NEW}, attributable=attributable)
    # The path runs through a value the delivery flattened: no such field.
    flattened = _reviewed(
        harness,
        {"supplier": _NEW},
        attributable=attributable,
        path=("supplier", "namn"),
    )
    # Another step delivered the result: a leaf of the same name there is
    # another step's field, not the reviewed one.
    other_step = _reviewed(
        harness,
        {"supplier": _NEW},
        attributable=attributable,
        delivering_step=_TEMPLATE_STEP,
    )

    assert at_field["passed"] is True
    assert at_field["actual"][0]["location"] == "structured_field"
    assert _review_edit_state(harness, at_field) == "pass"
    # The supplier field holds another value: the edit did not reach its place.
    assert elsewhere["passed"] is False
    assert _review_edit_state(harness, elsewhere) == "fail"
    # The delivered value has no field the path names: no location.
    assert (no_field["passed"], no_field["status"]) == (None, "unmeasured")
    assert (flattened["passed"], flattened["status"]) == (None, "unmeasured")
    assert (other_step["passed"], other_step["status"]) == (None, "unmeasured")
    assert other_step["actual"][0]["location"] is None


@mark.parametrize(
    "leaf",
    [f"Beta Bygg AB\nFotnot: {_NEW}", f"{_NEW} (tidigare Beta Bygg AB)", f" {_NEW}x"],
    ids=["footnote_inside_leaf", "suffix_inside_leaf", "longer_token"],
)
@mark.parametrize("attributable", [True, False])
def test_a_structured_leaf_that_merely_contains_the_new_value_is_another_value(
    harness: ModuleType, leaf: str, attributable: bool
) -> None:
    """The harness replaced the whole leaf with the new value, so the reviewed
    field passes only when it holds exactly that value; a leaf that contains it
    among other text is a different value at the reviewed place."""

    check = _reviewed(
        harness, {"supplier": leaf, "kontaktperson": "Eva"}, attributable=attributable
    )

    assert check["passed"] is False
    assert check["actual"][0]["location"] == "structured_field"
    assert _review_edit_state(harness, check) == "fail"


_OTHERS = {"kontakt": "Eva Ek", "sokande": "Gamma AB"}
_SUPPLIER_LEAF = {
    "leverantor": f"{{{{ step_{_REVIEWED_STEP}.output.structured.supplier }}}}"
}


@mark.parametrize(
    "delivery",
    [
        # The reviewed value replaced at its place and the new one appended as
        # a footnote, while the template's inputs still hold the new value:
        # inputs to a template are no proof of where it rendered them.
        _template_delivery(
            "Leverantör: Beta Bygg AB\nKontakt: Eva Ek\nSökande: Gamma AB\n"
            f"Fotnot: {_NEW}",
            {"leverantor": _NEW, **_OTHERS, "fotnot": "inga."},
        ),
        _template_delivery(
            f"Leverantör: Beta Bygg AB\nFotnot: {_NEW}",
            {"leverantor": _NEW},
            bindings=_SUPPLIER_LEAF,
        ),
        # The new value at the placeholder bound to the field: still a
        # rendering the grader cannot trace.
        _template_delivery(
            f"Leverantör: {_NEW}\nKontakt: Eva Ek\nSökande: Gamma AB\nFotnot: inga.",
            {"leverantor": _NEW, **_OTHERS, "fotnot": "inga."},
        ),
        # The bound placeholder's input holds another value.
        _template_delivery(
            f"Leverantör: Beta Bygg AB\nKontakt: Eva Ek\nFotnot: {_NEW}",
            {"leverantor": "Beta Bygg AB", **_OTHERS, "fotnot": _NEW},
        ),
        # No placeholder is bound to the reviewed field.
        _template_delivery(
            f"Leverantör: {_NEW}",
            {"leverantor": _NEW},
            bindings={"leverantor": f"{{{{ step_{_REVIEWED_STEP}.output.text }}}}"},
        ),
    ],
    ids=["footnote", "footnote_one_binding", "placed", "other_input", "unbound"],
)
@mark.parametrize("attributable", [True, False])
def test_a_filled_template_never_decides_where_the_edit_stands(
    harness: ModuleType, delivery: dict[str, Any], attributable: bool
) -> None:
    """A template-filled document names no field: the values its template step
    received are its inputs, not where it rendered them, so the edit there is
    unmeasured, never a pass and never a failure of placement."""

    check = _reviewed(harness, delivery, attributable=attributable)

    assert (check["passed"], check["status"]) == (None, "unmeasured")
    assert check["actual"][0]["location"] is None
    assert _review_edit_state(harness, check) == "unmeasured"


def test_a_placeholder_bound_to_the_collection_holding_the_reviewed_field_is_no_location(
    harness: ModuleType,
) -> None:
    """A binding to the list that holds the reviewed leaf binds the whole list:
    a prefix of the edited path is not the leaf, so where the edit stands is
    unmeasured."""

    rows = _template_delivery(
        f"Bedömningar: Alfa: {_NEW}; Beta: godkänd.",
        {"bedomningar": f"Alfa: {_NEW}; Beta: godkänd."},
        bindings={
            "bedomningar": (
                f"{{{{ step_{_REVIEWED_STEP}.output.structured.bedomningar }}}}"
            )
        },
    )

    check = _reviewed(
        harness, rows, attributable=True, path=("bedomningar", 0, "lagrum")
    )

    assert (check["passed"], check["status"]) == (None, "unmeasured")
    assert check["actual"][0]["location"] is None


def test_a_new_value_extended_into_another_value_did_not_reach_delivery(
    harness: ModuleType,
) -> None:
    check = _reviewed(harness, f"Leverantör: {_NEW}2.", attributable=True)

    assert check["passed"] is False
