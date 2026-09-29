"""A forbidden literal is judged on the output a run delivered, and only on that.

A run that failed or never delivered has nothing to inspect, so its forbidden
literals are `not_evaluated`: never failed, never counted as a leak. A run that
delivered the literal stays a hit however the delivered text writes it, and
every reader of the check reads the new status as neither pass nor fail.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

from pytest import MonkeyPatch, fixture, mark

from tests.unittests.flows.ai_builder.test_ai_builder_api_battle_harness import (
    _battle_harness,  # pyright: ignore[reportPrivateUsage]
    _complete_live_case_bundle,  # pyright: ignore[reportPrivateUsage]
    _completed_text_run,  # pyright: ignore[reportPrivateUsage]
    _execute,  # pyright: ignore[reportPrivateUsage]
    _execution,  # pyright: ignore[reportPrivateUsage]
    _RuntimeApi,  # pyright: ignore[reportPrivateUsage]
)
from tests.unittests.flows.ai_builder.test_ai_builder_battle_compare import (
    _compare_module,  # pyright: ignore[reportPrivateUsage]
)
from tests.unittests.flows.ai_builder.test_ai_builder_edit_expectation import (
    E14,  # pyright: ignore[reportPrivateUsage]
    S2_EXPLICIT,  # pyright: ignore[reportPrivateUsage]
    A,  # pyright: ignore[reportPrivateUsage]
    _e14_applied,  # pyright: ignore[reportPrivateUsage]
    _evidence,  # pyright: ignore[reportPrivateUsage]
    _plan,  # pyright: ignore[reportPrivateUsage]
)
from tests.unittests.flows.ai_builder.test_ai_builder_edit_outcomes import (
    DECLARED,  # pyright: ignore[reportPrivateUsage]
    _edit,  # pyright: ignore[reportPrivateUsage]
    _observation,  # pyright: ignore[reportPrivateUsage]
    outcomes,  # pyright: ignore[reportPrivateUsage]
)

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

edit = importlib.import_module("ai_builder_edit_expectation")

_FORBIDDEN = ("17 03 01*", "880521-2381")
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@fixture(scope="module")
def harness() -> ModuleType:
    return _battle_harness()


def _expect(harness: ModuleType, forbidden: tuple[str, ...] = _FORBIDDEN) -> Any:
    return harness.OutputExpectation(
        output_kind="text", required_facts=("Njurunda",), forbidden=forbidden
    )


def _report(harness: ModuleType, run_evidence: Mapping[str, object]) -> dict[str, Any]:
    return harness._output_report(
        _expect(harness),
        {"run_contract": {"final_output": {"output_type": "text"}}, **run_evidence},
        runtime_checks=[],
    )


def _completed(text: str) -> dict[str, object]:
    return {
        "execution": {"outcome": "completed", "failures": []},
        "run": _completed_text_run(text),
    }


def _forbidden(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [c for c in report["output_checks"] if c["name"] == "forbidden_literal"]


_NO_DELIVERY: dict[str, dict[str, object]] = {
    # The run failed at a checkpoint, before any result.
    "failed": {
        "execution": {
            "outcome": "checkpoint_failure",
            "failures": [{"kind": "review_target_missing"}],
        },
        "run": {"id": "run-1", "status": "failed"},
        "final_artifact": None,
    },
    # A run that was never started: the evidence holds the execution record only.
    "never_started": {
        "execution": {"outcome": "not_started", "failures": []},
    },
    # A run that finished, but whose file could not be read: nothing to inspect.
    "unreadable_file": {
        "execution": {"outcome": "completed", "failures": []},
        "run": {
            "id": "run-1",
            "status": "completed",
            "result": {"kind": "artifact", "files": [{"mimetype": _DOCX}]},
        },
        "final_artifact": {"unreadable": "BadZipFile: not a zip"},
    },
}


@mark.parametrize("delivery", sorted(_NO_DELIVERY))
def test_a_forbidden_literal_on_a_run_without_delivered_output_is_not_evaluated(
    harness: ModuleType, delivery: str
) -> None:
    report = _report(harness, _NO_DELIVERY[delivery])

    forbidden = _forbidden(report)
    assert [(c["literal"], c["passed"], c["status"]) for c in forbidden] == [
        (literal, None, "not_evaluated") for literal in _FORBIDDEN
    ]
    # Never a failure or a hit: a reader of "appears in" finds nothing.
    assert not [c for c in forbidden if c["passed"] is False]
    assert not [c for c in forbidden if "appears in" in c["reason"]]
    # Nothing was delivered, so the run is no success and its lost fact stays lost.
    assert report["output_success"] is False
    required = [c for c in report["output_checks"] if c["name"] == "required_fact"]
    assert [c["passed"] for c in required] == [False]


@mark.parametrize(
    "delivered",
    [
        "Kod 17 03 01* för asfalt.",
        "Kod 17 03 01\\* för asfalt.",
        "KOD 17\u00a003\u00a001* FÖR ASFALT.",
        "Personnummer 880521-2381.",
        "Personnummer 880521\\-2381.",
    ],
    ids=[
        "plain",
        "escaped_star",
        "case_and_no_break_spaces",
        "plain_personnummer",
        "escaped_hyphen",
    ],
)
def test_a_delivered_forbidden_literal_is_a_hit_however_its_text_is_written(
    harness: ModuleType, delivered: str
) -> None:
    report = _report(harness, _completed(f"Njurunda. {delivered}"))

    hits = [c for c in _forbidden(report) if c["passed"] is False]
    assert len(hits) == 1
    assert "appears in" in hits[0]["reason"]
    assert "status" not in hits[0]
    assert not [c for c in _forbidden(report) if c["passed"] is None]
    assert report["output_success"] is False


def test_a_hit_in_a_delivered_file_is_a_hit_too(harness: ModuleType) -> None:
    report = _report(
        harness,
        {
            "execution": {"outcome": "completed", "failures": []},
            "run": {
                "id": "run-1",
                "status": "completed",
                "result": {"kind": "artifact", "files": [{"mimetype": _DOCX}]},
            },
            "final_artifact": {"text": "Njurunda. Kod 17 03 01\\* för asfalt."},
        },
    )

    assert [(c["literal"], c["passed"]) for c in _forbidden(report)] == [
        ("17 03 01*", False),
        ("880521-2381", True),
    ]


@mark.parametrize(
    "delivered",
    [
        "Kod 17 03 02 för asfalt.",
        # Folding an escape is not dropping the character it escapes.
        "Kod 17 03 01 för asfalt.",
        "Kod 17 03 01\\ för asfalt.",
        "Kod 17 03 02\\* för asfalt.",
        "Personnummer 880521 2381.",
    ],
    ids=[
        "other_code",
        "star_dropped",
        "backslash_before_a_space",
        "escaped_star_on_another_code",
        "hyphen_replaced_by_space",
    ],
)
def test_a_delivered_text_without_the_literal_passes_it(
    harness: ModuleType, delivered: str
) -> None:
    report = _report(harness, _completed(f"Njurunda. {delivered}"))

    assert [(c["literal"], c["passed"]) for c in _forbidden(report)] == [
        ("17 03 01*", True),
        ("880521-2381", True),
    ]
    assert report["output_success"] is True


@mark.parametrize(
    ("literal", "text", "appears"),
    [
        ("17 03 01*", "17 03 01\\*", True),
        ("17 03 01\\*", "17 03 01*", True),
        ("a-b", "a\\-b", True),
        ("a\\\\b", "a\\b", True),
        # A backslash before a letter or at the end is no escape: kept as written.
        ("c:\\users", "c:\\users\\anna", True),
        ("ab\\", "ab\\*", True),
        ("c:\\users", "c:users", False),
        ("17 03 01*", "17 03 01", False),
        ("17 03 01*", "17 03 01\\", False),
        ("ab", "a\\b", False),
    ],
)
def test_a_literal_appears_as_written_or_with_markdown_escapes_folded(
    literal: str, text: str, appears: bool
) -> None:
    assert edit.literal_appears(literal, text) is appears


def _scored_row(
    harness: ModuleType,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    *,
    run: dict[str, object],
    name: str,
) -> dict[str, Any]:
    """One run scored by the quality report and sealed as a suite result row."""

    _RuntimeApi(runs=[run]).install(harness, monkeypatch)
    execution = _execution(
        harness, required_facts=("Njurunda",), forbidden=("17 03 01*",)
    )
    case = harness.BattleCase(
        case_id=name, prompt="Build and run.", apply_plan=True, execution=execution
    )
    plan_check = {"name": "plan_created", "passed": True, "actual": True}
    bundle = _complete_live_case_bundle(
        harness, case, quality_checks=[{**plan_check, "expected": True}]
    )
    evidence, report = _execute(harness, execution, tmp_path=tmp_path)
    bundle["journey"] = {"outcome_class": "plan_first_pass"}
    bundle["runtime_evidence"] = evidence
    bundle["quality_report"].update(
        output_checks=report["output_checks"], output_success=report["output_success"]
    )
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return harness._suite_result(harness.seal_observation(bundle), path)


def test_a_suite_row_lists_a_forbidden_literal_only_where_one_was_delivered(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    failed = _scored_row(
        harness,
        monkeypatch,
        tmp_path,
        run={"id": "run-1", "status": "failed"},
        name="failed",
    )
    leaked = _scored_row(
        harness,
        monkeypatch,
        tmp_path,
        run=_completed_text_run("Njurunda. Kod 17 03 01\\* för asfalt."),
        name="leaked",
    )
    clean = _scored_row(
        harness,
        monkeypatch,
        tmp_path,
        run=_completed_text_run("Njurunda. Kod 17 03 02 för asfalt."),
        name="clean",
    )

    assert "forbidden_literal" not in failed["output_failed_checks"]
    assert failed["output_failed_checks"]
    assert failed["output_success"] is False
    assert leaked["output_failed_checks"] == ["forbidden_literal"]
    assert leaked["output_success"] is False
    assert clean["output_failed_checks"] == []
    assert clean["output_success"] is True

    # The target gate reads the same list: only the clean run's output is valid.
    counted = _compare_module()._target_count  # pyright: ignore[reportPrivateUsage]
    assert [counted(row, ["Njurunda"]) for row in (failed, leaked, clean)] == [
        None,
        None,
        1,
    ]


def test_a_reanalysis_scores_a_kept_failed_run_not_evaluated(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    _scored_row(
        harness,
        monkeypatch,
        tmp_path,
        run={"id": "run-1", "status": "failed"},
        name="kept",
    )
    bundle_path = tmp_path / "kept.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    # The bundle was scored before the fix: every literal failed as "is missing".
    bundle["quality_report"]["output_checks"] = [
        {**check, "passed": False, "reason": f"{check['literal']!r} is missing"}
        if check["name"] == "forbidden_literal"
        else check
        for check in bundle["quality_report"]["output_checks"]
    ]
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    output_dir = tmp_path / "reanalyzed"
    assert (
        harness._reanalyze_bundles(bundle_paths=[bundle_path], output_dir=output_dir)
        == 0
    )

    reanalyzed = json.loads(next(output_dir.iterdir()).read_text(encoding="utf-8"))
    assert [
        (c["passed"], c["status"])
        for c in reanalyzed["quality_report"]["output_checks"]
        if c["name"] == "forbidden_literal"
    ] == [(None, "not_evaluated")]


def test_a_step_output_that_is_empty_lists_no_forbidden_literal_as_failed() -> None:
    rule = edit.StepOutput(required_facts=["startdatum"], forbidden=["2026-10-05"])

    empty = edit._step_output(  # pyright: ignore[reportPrivateUsage]
        rule, {"output_payload_json": {"text": ""}}
    )
    leaked = edit._step_output(  # pyright: ignore[reportPrivateUsage]
        rule, {"output_payload_json": {"text": "startdatum 2026-10-05"}}
    )
    clean = edit._step_output(  # pyright: ignore[reportPrivateUsage]
        rule, {"output_payload_json": {"text": "startdatum saknas"}}
    )

    assert empty[0] is False
    assert [c["name"] for c in empty[1]["failed"]] == ["required_fact"]
    assert leaked[0] is False
    assert [c["name"] for c in leaked[1]["failed"]] == ["forbidden_literal"]
    assert clean == (True, {"kind": "text", "failed": []})


def test_an_edit_slot_with_an_empty_step_output_is_a_failed_edit_not_a_leak() -> None:
    # The presenter reads the scorer's verdict and categories only: an empty
    # step output stays one failed edit, whose only failed check is the step.
    gold = edit.parse_edit_expectation(E14, seed=A, owner="test")
    evidence = _evidence(
        A,
        _e14_applied(keep_s2_explicit=True),
        _plan(3, {2: {"input_bindings": S2_EXPLICIT}}, added=1),
    )
    structural = edit.evaluate_edit(gold, seed=A, evidence=evidence)

    scored = edit.add_execution(
        structural,
        gold,
        evidence=evidence,
        output_success=True,
        step_results=[{"assistant_id": "n-new", "output_payload_json": {"text": ""}}],
    )

    step = next(c for c in scored["checks"] if c["name"] == "step_output_n1")
    assert [c["name"] for c in step["detail"]["failed"]] == ["required_fact"] * 2
    slot = _observation(
        "edit",
        edit={
            **_edit("fail"),
            "verdict": scored["verdict"],
            "failed_checks": scored["failed_checks"],
            "categories": scored["categories"],
        },
    )
    assert scored["failed_checks"] == ["step_output_n1"]
    assert outcomes.edit_bucket(slot, DECLARED["edit"]) == "failed_edit"
