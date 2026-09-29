"""The edit lane's outcome report: what a worker got, never a blended score."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

outcomes = importlib.import_module("ai_builder_edit_outcomes")
receipts = importlib.import_module("ai_builder_receipt")

# None: a case the corpus declares but this report does not score.
DECLARED: dict[str, Any] = {
    "edit": "edit_success",
    "rename": "structural_pass",
    "decline": "correct_decline",
    "create_case": None,
}
# The scorer's own category per check it fails (ai_builder_edit_expectation).
CATEGORY = {
    "outcome": "fulfilment",
    "questions": "questions",
    "flow_unchanged_before_approval": "pre_approval_write",
    "scope": "unauthorized_mutation",
    "fulfilment": "fulfilment",
    "diff_matches_applied": "diff_integrity",
    "run_output": "execution",
}


def _edit(verdict: str, failed: tuple[str, ...] = ()) -> dict[str, Any]:
    """A verdict as the harness writes it, on every row that reached the scorer."""

    return {
        "verdict": verdict,
        "failed_checks": list(failed),
        "categories": sorted({CATEGORY[name] for name in failed}),
        "seed": "edit_seed_a.json",
        "seed_sha256": "s" * 64,
        "executes": True,
        "outcome": "plan",
        "scope": "whole_flow",
        "runtime_model_id": "model",
    }


def _observation(
    case_id: str,
    repetition: int = 1,
    *,
    edit: dict[str, Any] | None,
    status: str = "completed",
    failure_class: str | None = None,
    failure_codes: tuple[str, ...] = (),
    error_codes: tuple[str, ...] = (),
    evidence_failed: tuple[str, ...] = (),
) -> Any:
    row = {
        "case_id": case_id,
        "repetition": repetition,
        "observation_status": status,
        "outcome_class": status,
        "failure_class": failure_class,
        "expectation_verdict": "not_evaluated",
        "case_contract_sha256": "c" * 64,
        receipts.BUNDLE_FILE_FIELD: f"{case_id}-{repetition}.json",
        receipts.BUNDLE_SHA256_FIELD: "b" * 64,
        "failure_summary": {
            "failure_codes": list(failure_codes),
            "error_codes": list(error_codes),
        },
        "evidence_failed_checks": [
            {"name": name, "passed": False, "expected": "x", "actual": {}}
            for name in evidence_failed
        ],
        "journey": {"plan_outcome": {}, "architecture": {}},
        "authoring_usage": {},
        "edit": edit,
    }
    return receipts.observation_from_row(row, where="row")


def _scored(
    case_id: str,
    repetition: int = 1,
    verdict: str = "pass",
    failed: tuple[str, ...] = (),
    **row: Any,
) -> Any:
    return _observation(case_id, repetition, edit=_edit(verdict, failed), **row)


UNAVAILABLE: dict[str, Any] = {
    "status": "acquisition_failure",
    "failure_class": "provider_request",
    "error_codes": ("session_turn_provider_outcome_unknown",),
}
INVALID: dict[str, Any] = {
    "status": "invalid_evidence",
    "evidence_failed": ("observation_input_identity_consistent", "x"),
}
ERRORED: dict[str, Any] = {
    "status": "error_terminated",
    "failure_class": "builder_semantic",
    "error_codes": ("planner_output_too_long",),
}


def _failed(*checks: str, case: str = "edit", repetition: int = 1, **row: Any) -> Any:
    return _scored(case, repetition, "fail", checks, **row)


def _report(
    *observations: Any, repetitions: int = 1, planned: int | None = None
) -> dict[str, Any]:
    return outcomes.edit_outcome_report(
        observations,
        declared=DECLARED,
        repetitions=repetitions,
        planned=planned or repetitions,
    )


def test_every_declared_slot_lands_in_exactly_one_bucket() -> None:
    report = _report(
        _scored("edit", 1),
        _scored("decline", 1),
        _failed("outcome", repetition=2),
        _failed("outcome", "questions", repetition=3),
        _failed("outcome", repetition=4, **UNAVAILABLE),
        _failed("scope", repetition=5, **INVALID),
        _failed("outcome", repetition=6, **ERRORED),
        repetitions=6,
        planned=2,
    )

    assert (report["attempted"], report["repetitions"], report["recorded_plan"]) == (
        18,
        6,
        6,
    )
    assert report["buckets"] == {
        "edit_success": 1,
        "structural_pass": 0,
        "correct_decline": 1,
        "question": 1,
        "failed_edit": 2,
        "infrastructure": 1,
        "invalid_evidence": 1,
        "not_observed": 11,
    }
    assert sum(report["buckets"].values()) == report["attempted"]
    assert report["expected"] == {
        "edit_success": 6,
        "structural_pass": 6,
        "correct_decline": 6,
    }


# How one observed slot can end: its row, its bucket, its first failure.
SLOT_ENDS: dict[str, tuple[Any, str, str | None]] = {
    "executed_edit_met_oracle": (_scored("edit"), "edit_success", None),
    "plan_with_no_run_oracle": (_scored("rename"), "structural_pass", None),
    "expected_decline": (_scored("decline"), "correct_decline", None),
    "decline_not_declared": (
        _failed("outcome", case="decline"),
        "failed_edit",
        "outcome",
    ),
    "scorers_first_failed_check": (
        _failed("scope", "fulfilment", "diff_matches_applied"),
        "failed_edit",
        "scope",
    ),
    "asked_and_did_not_plan": (_failed("outcome", "questions"), "question", "outcome"),
    "asked_only": (_failed("questions"), "question", "questions"),
    "asked_beside_a_write": (
        _failed("flow_unchanged_before_approval", "questions"),
        "failed_edit",
        "flow_unchanged_before_approval",
    ),
    "asked_beside_a_scope_breach": (
        _failed("questions", "scope"),
        "failed_edit",
        "questions",
    ),
    "acquisition_failure_despite_pass": (
        _scored("edit", **UNAVAILABLE),
        "infrastructure",
        "provider_request",
    ),
    "execution_failure_despite_pass": (
        _scored(
            "edit", status="execution_failure", failure_class="harness_configuration"
        ),
        "infrastructure",
        "harness_configuration",
    ),
    "error_terminated_despite_pass": (
        _scored("edit", **ERRORED),
        "failed_edit",
        "planner_output_too_long",
    ),
    "error_terminated_without_codes": (
        _scored("edit", status="error_terminated", failure_class="runtime"),
        "failed_edit",
        "runtime",
    ),
    "error_terminated_names_failure_code": (
        _scored(
            "edit",
            status="error_terminated",
            failure_codes=("c1",),
            failure_class="runtime",
        ),
        "failed_edit",
        "c1",
    ),
    "failed_without_checks_names_failure_code": (
        _scored("edit", verdict="fail", failure_codes=("c2",)),
        "failed_edit",
        "c2",
    ),
    "failed_without_any_reason_names_outcome_class": (
        _scored("edit", verdict="fail"),
        "failed_edit",
        "completed",
    ),
    "invalid_evidence_without_checks": (
        _scored("edit", status="invalid_evidence"),
        "invalid_evidence",
        "invalid_evidence",
    ),
    "invalid_evidence_despite_pass": (
        _scored("edit", **INVALID),
        "invalid_evidence",
        "observation_input_identity_consistent",
    ),
    "no_verdict": (
        _observation("edit", edit=None),
        "invalid_evidence",
        "no_edit_verdict",
    ),
    "unmeasured_verdict": (
        _scored("edit", verdict="unmeasured"),
        "invalid_evidence",
        "unmeasured",
    ),
}


@pytest.mark.parametrize(
    ("row", "bucket", "first_failure"), SLOT_ENDS.values(), ids=list(SLOT_ENDS)
)
def test_a_slot_lands_in_the_bucket_its_row_earns_with_its_first_failure(
    row: Any, bucket: str, first_failure: str | None
) -> None:
    report = _report(row)

    landed = {b: n for b, n in report["buckets"].items() if n and b != "not_observed"}
    assert landed == {bucket: 1}
    assert [
        failure["first_failure"]
        for failure in report["first_failures"]
        if failure["bucket"] != "not_observed"
    ] == ([] if first_failure is None else [first_failure])


def test_a_missing_observation_is_reported_not_rescaled_away() -> None:
    report = _report(_scored("edit", 1), repetitions=2)

    assert report["attempted"] == 6
    assert report["buckets"]["not_observed"] == 5
    assert [
        (row["case_id"], row["repetition"], row["first_failure"])
        for row in report["first_failures"]
        if row["bucket"] == "not_observed"
    ] == [
        (case, repetition, "no_observation")
        for case, repetition in [
            ("edit", 2),
            ("rename", 1),
            ("rename", 2),
            ("decline", 1),
            ("decline", 2),
        ]
    ]
    assert list(report["buckets"]) == list(outcomes.BUCKETS)
    assert outcomes.headline(report).startswith("attempted 6: edit_success 1/2, ")


@pytest.mark.parametrize(
    ("row", "named"),
    [(_scored("stranger"), "stranger"), (_scored("edit", 2), r"\('edit', 2\)")],
    ids=["undeclared_case", "repetition_beyond_the_population"],
)
def test_an_observation_the_corpus_cannot_place_is_refused(
    row: Any, named: str
) -> None:
    with pytest.raises(ValueError, match=named):
        _report(row)


def test_rows_of_cases_this_report_does_not_score_are_ignored_and_counted() -> None:
    report = _report(
        _scored("edit", 1),
        _scored("create_case", 1, **UNAVAILABLE),
        _scored("create_case", 2),
    )

    assert report["attempted"] == 3
    assert report["buckets"]["edit_success"] == 1
    assert report["ignored_not_edit"] == {"rows": 2, "case_ids": ["create_case"]}
    assert all(row["case_id"] != "create_case" for row in report["first_failures"])


def test_the_headline_shows_the_attempted_total_and_every_denominator() -> None:
    report = _report(_scored("edit", **UNAVAILABLE), _scored("decline"))

    assert outcomes.headline(report) == (
        "attempted 3: edit_success 0/1, structural_pass 0/1, correct_decline 1/1, "
        "question 0, failed_edit 0, infrastructure 1, invalid_evidence 0, "
        "not_observed 1"
    )


def _edit_case(case_id: str, outcome: str, *, executes: bool = False) -> dict[str, Any]:
    """An edit case; an `execution` block makes it an executed edit."""

    return {
        "id": case_id,
        "edit": {"seed_flow_fixture": "seed.json", "expect": {"outcome": outcome}},
        **({"execution": {"inputs": {}, "expect": {}}} if executes else {}),
    }


def _corpus(tmp_path: Path, *cases: dict[str, Any]) -> Path:
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"version": 9, "cases": list(cases)}), encoding="utf-8")
    return path


def test_declared_cases_place_each_pass_where_its_own_case_declares() -> None:
    import eneo.database.tables  # noqa: F401  (tables before the Builder modules)

    harness = importlib.import_module("ai_builder_api_battle_test")
    declared = outcomes.declared_cases(outcomes.DEFAULT_CASES_FILE)
    cases = {
        case.case_id: case
        for case in harness._read_cases_file(outcomes.DEFAULT_CASES_FILE)
    }

    assert declared == {
        case_id: None
        if case.edit is None or case.edit.gold is None
        else "correct_decline"
        if case.edit.gold.outcome == "declined"
        else "edit_success"
        if case.executes
        else "structural_pass"
        for case_id, case in cases.items()
    }


def test_declared_cases_read_a_corpus_by_its_edit_outcome_and_execution(
    tmp_path: Path,
) -> None:
    corpus = _corpus(
        tmp_path,
        _edit_case("a", "plan", executes=True),
        _edit_case("b", "plan"),
        _edit_case("c", "declined"),
        {**_edit_case("d", "plan"), "execution": None},
        {"id": "create_case"},
        {"id": "null_edit", "edit": None},
        {"id": "unscored", "edit": {"seed_flow_fixture": "seed.json"}},
    )

    assert outcomes.declared_cases(corpus) == {
        "a": "edit_success",
        "b": "structural_pass",
        "c": "correct_decline",
        "d": "structural_pass",
        "create_case": None,
        "null_edit": None,
        "unscored": None,
    }


def _write_suite(
    directory: Path,
    corpus: Path,
    *rows: Any,
    repetitions: int = 3,
    recorded_digest: str | None = "corpus",
) -> Path:
    """A suite summary as the harness writes it. The report reads nothing else:
    no bundle, seed or fixture file is needed beside it."""

    identity: dict[str, Any] = {"source": {"revision": "r"}}
    if recorded_digest is not None:
        digest = hashlib.sha256(corpus.read_bytes()).hexdigest()
        identity["build"] = {
            "cases_sha256": {
                "corpus": digest,
                "prefix": digest[:8],
                "upper": digest.upper(),
            }.get(recorded_digest, recorded_digest)
        }
    (directory / receipts.SUITE_SUMMARY_FILE).write_text(
        json.dumps(
            {
                "artifact_schema_version": "1",
                "artifact_mode": "suite",
                "repetitions": repetitions,
                "release_identity": identity,
                "results": [row.row for row in rows],
            }
        ),
        encoding="utf-8",
    )
    return directory


def _run(
    capsys: pytest.CaptureFixture[str], suite: Path, corpus: Path, *extra: str
) -> tuple[int, list[str], str]:
    code = outcomes.main([str(suite), "--cases", str(corpus), *extra])
    captured = capsys.readouterr()
    return code, captured.out.splitlines(), captured.err


def _small_suite(
    tmp_path: Path, rows: list[Any] | None = None, **suite: Any
) -> tuple[Path, Path]:
    """One executed edit case and one other case, and a suite of `rows`
    (default: one passing edit)."""

    corpus = _corpus(tmp_path, _edit_case("a", "plan", executes=True), {"id": "b"})
    rows = [_scored("a")] if rows is None else rows
    return _write_suite(tmp_path, corpus, *rows, **suite), corpus


CAP = 1000  # 50 repetitions of the registered 20 edit cases


@pytest.mark.parametrize(
    ("planned", "extra", "expected"),
    [
        (3, [], "attempted 3: edit_success 1/3"),
        (5, [], "attempted 5: edit_success 1/5"),
        (1, [], "attempted 3 (recorded plan 1): edit_success 1/3"),
        (1, ["--repetitions", "2"], "attempted 2 (recorded plan 1): edit_success 1/2"),
        (1, ["--repetitions", "1"], "attempted 1: edit_success 1/1"),
        (1, ["--repetitions", str(CAP)], f"attempted {CAP} (recorded plan 1)"),
        (CAP, [], f"attempted {CAP}: "),
        (3, ["--repetitions", "1"], "refused: 1 repetitions is below the suite's "),
        (1, ["--repetitions", str(CAP + 1)], f"refused: {CAP + 1} repetitions of 1"),
        (CAP + 1, [], f"refused: {CAP + 1} repetitions of 1"),
    ],
    ids=[
        "registered",
        "suite_plan_if_larger",
        "recorded_plan_shown",
        "asked_more",
        "asked_exact_plan",
        "stated_at_cap",
        "recorded_at_cap",
        "fewer_than_planned",
        "stated_above_cap",
        "recorded_above_cap",
    ],
)
def test_the_population_is_never_rescaled_down_and_is_bounded(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    planned: int,
    extra: list[str],
    expected: str,
) -> None:
    suite, corpus = _small_suite(tmp_path, repetitions=planned)

    code, lines, error = _run(capsys, suite, corpus, *extra)

    if expected.startswith("refused: "):
        assert (code, lines) == (2, [])
        assert expected.removeprefix("refused: ") in error
    else:
        assert code == 0
        assert lines[0].startswith(expected)


@pytest.mark.parametrize("asked", ["0", "-1"])
def test_fewer_than_one_repetition_is_refused_not_read_as_the_default(
    tmp_path: Path, asked: str
) -> None:
    suite, corpus = _small_suite(tmp_path)

    with pytest.raises(SystemExit) as refused:
        outcomes.main([str(suite), "--cases", str(corpus), "--repetitions", asked])

    assert refused.value.code == 2


def _full_corpus_suite(
    directory: Path, *, planned: int, observed: int
) -> tuple[Path, list[str]]:
    """Every case of the real corpus: its edit cases for `observed` repetitions,
    every other case once, as a full-corpus suite that planned `planned`."""

    declared = outcomes.declared_cases(outcomes.DEFAULT_CASES_FILE)
    rows = [
        _observation(case_id, repetition, edit=_edit("pass") if bucket else None)
        for case_id, bucket in declared.items()
        for repetition in range(1, (observed if bucket else 1) + 1)
    ]
    suite = _write_suite(
        directory, outcomes.DEFAULT_CASES_FILE, *rows, repetitions=planned
    )
    return suite, [case_id for case_id, bucket in declared.items() if bucket is None]


@pytest.mark.parametrize(
    ("planned", "observed", "extra", "expected", "not_observed"),
    [
        (3, 1, [], "attempted 60: edit_success 18/54, ", 40),
        (1, 1, [], "attempted 60 (recorded plan 20): edit_success 18/54, ", 40),
        (1, 1, ["--repetitions", "1"], "attempted 20: edit_success 18/18, ", 0),
        (3, 3, [], "attempted 60: edit_success 54/54, ", 0),
    ],
)
def test_a_full_corpus_suite_reads_as_its_edit_slots_and_counts_the_rest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    planned: int,
    observed: int,
    extra: list[str],
    expected: str,
    not_observed: int,
) -> None:
    suite, others = _full_corpus_suite(tmp_path, planned=planned, observed=observed)

    code, lines, _ = _run(capsys, suite, outcomes.DEFAULT_CASES_FILE, *extra)

    assert code == 0
    assert lines[0].startswith(expected)
    assert f"not_observed {not_observed}" in lines[0]
    assert lines[1] == f"ignored (not edit): {len(others)} rows"
    ignored = json.loads("\n".join(lines[2:]))["ignored_not_edit"]
    assert ignored == {"rows": len(others), "case_ids": sorted(others)}


@pytest.mark.parametrize(
    ("rows", "why"),
    [
        ([_scored("nobody")], "nobody"),
        ([_scored("a", 4)], "outside"),
        ([_scored("a")] * 2, "duplicate"),
        ([], "non-empty"),
    ],
    ids=["unknown_case", "repetition_beyond", "duplicate_slot", "empty_suite"],
)
def test_a_suite_the_corpus_or_the_receipt_cannot_place_is_refused_with_its_reason(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    rows: list[Any],
    why: str,
) -> None:
    suite, corpus = _small_suite(tmp_path, rows)

    code, _, error = _run(capsys, suite, corpus, "--repetitions", "3")

    assert code == 2
    assert why in error


@pytest.mark.parametrize(
    "recorded",
    [None, "d" * 64, "prefix", "upper"],
    ids=["none", "another", "prefix_only", "uppercase"],
)
def test_a_suite_scored_on_another_corpus_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], recorded: str | None
) -> None:
    suite, corpus = _small_suite(tmp_path, recorded_digest=recorded)

    code, lines, error = _run(capsys, suite, corpus)

    assert (code, lines) == (2, [])
    assert "different corpus" in error


def test_an_unreadable_corpus_or_suite_is_a_refusal_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    suite, corpus = _small_suite(tmp_path)

    assert _run(capsys, suite, tmp_path / "nowhere.json")[0] == 2
    assert _run(capsys, tmp_path / "nowhere", corpus)[0] == 2


@pytest.mark.parametrize(
    "expect",
    [{"outcome": "maybe"}, None, {}, {"outcome": None}, [], "plan"],
    ids=repr,
)
def test_an_edit_expectation_the_vocabulary_lacks_is_refused_not_a_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], expect: Any
) -> None:
    suite, corpus = _small_suite(tmp_path)
    cases = json.loads(corpus.read_text(encoding="utf-8"))
    cases["cases"][0]["edit"]["expect"] = expect
    corpus.write_text(json.dumps(cases), encoding="utf-8")
    _write_suite(tmp_path, corpus, _scored("a", **UNAVAILABLE))

    code, _, error = _run(capsys, suite, corpus)

    assert code == 2
    assert "outcome" in error


def test_the_registered_report_runs_as_a_script_without_the_app_environment(
    tmp_path: Path,
) -> None:
    suite, others = _full_corpus_suite(tmp_path, planned=3, observed=3)

    result = subprocess.run(
        [sys.executable, str(_SCRIPTS / "ai_builder_edit_outcomes.py"), str(suite)],
        env={"PATH": os.environ["PATH"]},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].startswith(
        "attempted 60: edit_success 54/54, structural_pass 3/3, correct_decline 3/3, "
    )
    assert lines[1] == f"ignored (not edit): {len(others)} rows"
