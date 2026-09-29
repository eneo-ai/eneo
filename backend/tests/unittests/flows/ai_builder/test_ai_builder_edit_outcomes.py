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

SEED = "s" * 64
# None: a case the corpus declares but this report does not score.
DECLARED: dict[str, Any] = {
    "edit": outcomes.Declared("edit_success", SEED),
    "rename": outcomes.Declared("structural_pass", SEED),
    "decline": outcomes.Declared("correct_decline", SEED),
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


def _edit(
    verdict: str, failed: tuple[str, ...] = (), seed_sha256: str = SEED
) -> dict[str, Any]:
    """A verdict as the harness writes it, on every row that reached the scorer."""

    return {
        "verdict": verdict,
        "failed_checks": list(failed),
        "categories": sorted({CATEGORY[name] for name in failed}),
        "seed": "edit_seed_a.json",
        "seed_sha256": seed_sha256,
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


def _unavailable(case_id: str, repetition: int = 1, seed: str = SEED) -> Any:
    """Real infrastructure rows still carry the scorer's verdict on no plan."""

    return _observation(
        case_id,
        repetition,
        edit=_edit("fail", ("outcome",), seed),
        status="acquisition_failure",
        failure_class="provider_request",
        error_codes=("session_turn_provider_outcome_unknown",),
    )


def _invalid(
    case_id: str,
    repetition: int = 1,
    evidence: tuple[str, ...] = ("observation_input_identity_consistent",),
) -> Any:
    return _observation(
        case_id,
        repetition,
        edit=_edit("fail", ("scope",)),
        status="invalid_evidence",
        evidence_failed=evidence,
    )


def _errored(case_id: str, repetition: int = 1) -> Any:
    return _observation(
        case_id,
        repetition,
        edit=_edit("fail", ("outcome",)),
        status="error_terminated",
        failure_class="builder_semantic",
        error_codes=("planner_output_too_long",),
    )


def _report(
    *observations: Any, repetitions: int = 1, planned: int | None = None
) -> dict[str, Any]:
    return outcomes.edit_outcome_report(
        observations,
        declared=DECLARED,
        repetitions=repetitions,
        planned=planned or repetitions,
    )


def _first_failures(report: dict[str, Any], case_id: str) -> list[tuple[int, str]]:
    return [
        (row["repetition"], row["first_failure"])
        for row in report["first_failures"]
        if row["case_id"] == case_id
    ]


def test_every_declared_slot_lands_in_exactly_one_bucket() -> None:
    report = _report(
        _scored("edit", 1),
        _scored("edit", 2, "fail", ("outcome",)),
        _scored("edit", 3, "fail", ("outcome", "questions")),
        _scored("decline", 1),
        _unavailable("edit", 4),
        _invalid("edit", 5),
        _errored("edit", 6),
        repetitions=6,
    )

    assert report["attempted"] == 18
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


def test_a_missing_observation_is_reported_not_rescaled_away() -> None:
    report = _report(_scored("edit", 1), repetitions=2)

    assert report["attempted"] == 6
    assert report["buckets"]["not_observed"] == 5
    assert {
        (row["case_id"], row["repetition"])
        for row in report["first_failures"]
        if row["bucket"] == "not_observed"
    } == {("edit", 2), ("rename", 1), ("rename", 2), ("decline", 1), ("decline", 2)}
    assert outcomes.headline(report).startswith("attempted 6: edit_success 1/2, ")


def test_an_observation_the_corpus_cannot_place_is_refused() -> None:
    with pytest.raises(ValueError, match="stranger"):
        _report(_scored("stranger"))
    with pytest.raises(ValueError, match=r"\('edit', 2\)"):
        _report(_scored("edit", 2))


def test_rows_of_cases_this_report_does_not_score_are_ignored_and_counted() -> None:
    report = _report(
        _scored("edit", 1),
        _unavailable("create_case", 1),
        _scored("create_case", 2),
    )

    assert report["attempted"] == 3
    assert report["buckets"]["edit_success"] == 1
    assert report["ignored_not_edit"] == {"rows": 2, "case_ids": ["create_case"]}
    assert all(row["case_id"] != "create_case" for row in report["first_failures"])


def test_a_pass_lands_in_the_bucket_its_own_case_declares() -> None:
    report = _report(_scored("edit"), _scored("rename"), _scored("decline"))

    assert {bucket: report["buckets"][bucket] for bucket in outcomes._SCORED} == {
        "edit_success": 1,
        "structural_pass": 1,
        "correct_decline": 1,
    }


def test_a_decline_scores_only_on_a_case_that_expects_one() -> None:
    report = _report(
        _scored("edit", 1, "fail", ("outcome",)),
        _scored("decline", 1, "fail", ("outcome",)),
    )

    assert report["buckets"]["correct_decline"] == 0
    assert report["buckets"]["failed_edit"] == 2


# Every way a row can fail to complete: (status, failure class, its bucket).
NOT_COMPLETED = [
    ("invalid_evidence", None, "invalid_evidence"),
    ("error_terminated", "runtime", "failed_edit"),
    ("acquisition_failure", "provider_request", "infrastructure"),
    ("execution_failure", "harness_configuration", "infrastructure"),
]


@pytest.mark.parametrize(("status", "failure_class", "bucket"), NOT_COMPLETED)
def test_a_pass_verdict_on_a_row_that_did_not_complete_is_never_a_success(
    status: str, failure_class: str | None, bucket: str
) -> None:
    report = _report(
        _observation(
            "edit", edit=_edit("pass"), status=status, failure_class=failure_class
        )
    )

    assert report["buckets"][bucket] == 1
    assert report["buckets"]["edit_success"] == 0


def test_a_completed_row_with_no_verdict_is_invalid_evidence() -> None:
    report = _report(_observation("edit", edit=None))

    assert report["buckets"]["invalid_evidence"] == 1
    assert _first_failures(report, "edit")[0] == (1, "no_edit_verdict")


def test_an_unmeasured_verdict_is_invalid_evidence_never_a_pass() -> None:
    report = _report(_scored("edit", verdict="unmeasured"))

    assert report["buckets"]["invalid_evidence"] == 1
    assert report["buckets"]["edit_success"] == 0
    assert _first_failures(report, "edit")[0] == (1, "unmeasured")


@pytest.mark.parametrize(
    ("failed", "bucket"),
    [
        (("outcome", "questions"), "question"),
        (("questions",), "question"),
        (("flow_unchanged_before_approval", "questions"), "failed_edit"),
        (("questions", "scope"), "failed_edit"),
        (("outcome",), "failed_edit"),
    ],
)
def test_a_question_never_hides_a_failure_beyond_asking(
    failed: tuple[str, ...], bucket: str
) -> None:
    report = _report(_scored("edit", verdict="fail", failed=failed))

    assert report["buckets"][bucket] == 1


def test_first_failure_is_read_from_the_source_its_bucket_names() -> None:
    report = _report(
        _scored("edit", 1),
        _scored("edit", 2, "fail", ("scope", "fulfilment", "diff_matches_applied")),
        _unavailable("edit", 3),
        _invalid("edit", 4, evidence=("observation_input_identity_consistent", "x")),
        _errored("edit", 5),
        _scored("edit", 6, "fail", ("outcome", "questions")),
        repetitions=6,
    )

    assert _first_failures(report, "edit") == [
        (2, "scope"),
        (3, "provider_request"),
        (4, "observation_input_identity_consistent"),
        (5, "planner_output_too_long"),
        (6, "outcome"),
    ]


def test_the_headline_shows_the_attempted_total_and_every_denominator() -> None:
    report = _report(_unavailable("edit"), _scored("decline"))

    assert outcomes.headline(report) == (
        "attempted 3: edit_success 0/1, structural_pass 0/1, correct_decline 1/1, "
        "question 0, failed_edit 0, infrastructure 1, invalid_evidence 0, "
        "not_observed 1"
    )


def _edit_case(
    case_id: str,
    outcome: str,
    *,
    files: list[str] | None = None,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    """An edit case; naming run `files` makes it an executed edit."""

    return {
        "id": case_id,
        "edit": {"seed_flow_fixture": "seed.json", "expect": {"outcome": outcome}},
        **({"attachments": attachments} if attachments is not None else {}),
        **(
            {"execution": {"inputs": {"files": files}, "expect": {}}}
            if files is not None
            else {}
        ),
    }


def _corpus(tmp_path: Path, *cases: dict[str, Any]) -> Path:
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"version": 9, "cases": list(cases)}), encoding="utf-8")
    return path


def test_declared_cases_read_each_case_bucket_seed_bytes_and_fixture_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "seed.json").write_bytes(b'{"seed": 1}')
    monkeypatch.setattr(outcomes, "FIXTURE_DIR", tmp_path)
    corpus = _corpus(
        tmp_path,
        _edit_case("a", "plan", files=["f.pdf", "g.pdf"], attachments=["h.pdf"]),
        _edit_case("b", "plan"),
        _edit_case("c", "declined"),
        {**_edit_case("d", "plan"), "execution": None},
        {"id": "create_case"},
        {"id": "unscored", "edit": {"seed_flow_fixture": "seed.json"}},
    )
    seed = hashlib.sha256(b'{"seed": 1}').hexdigest()

    assert outcomes.declared_cases(corpus) == {
        "a": outcomes.Declared("edit_success", seed, ("h.pdf",), ("f.pdf", "g.pdf")),
        "b": outcomes.Declared("structural_pass", seed),
        "c": outcomes.Declared("correct_decline", seed),
        "d": outcomes.Declared("structural_pass", seed),
        "create_case": None,
        "unscored": None,
    }


def test_the_report_reads_the_corpus_as_the_harness_that_scored_it_does() -> None:
    import eneo.database.tables  # noqa: F401  (tables before the Builder modules)

    harness = importlib.import_module("ai_builder_api_battle_test")
    declared = outcomes.declared_cases(outcomes.DEFAULT_CASES_FILE)
    cases = {
        case.case_id: case
        for case in harness._read_cases_file(outcomes.DEFAULT_CASES_FILE)
    }

    assert outcomes.FIXTURE_DIR == harness.FIXTURE_DIR
    assert outcomes.FIXTURE_DIR / "manifest.json" == harness.FIXTURE_MANIFEST_FILE
    assert outcomes.fixture_pins(harness.FIXTURE_MANIFEST_FILE) == (
        harness._fixture_manifest()
    )
    assert declared.keys() == cases.keys()
    assert {
        case_id: None if value is None else tuple(value)
        for case_id, value in declared.items()
    } == {
        case_id: None
        if case.edit is None or case.edit.gold is None
        else (
            "correct_decline"
            if case.edit.gold.outcome == "declined"
            else "edit_success"
            if case.executes
            else "structural_pass",
            case.edit.seed_flow_sha256,
            case.attachments,
            case.runtime_files,
        )
        for case_id, case in cases.items()
    }
    assert any(value and value.runtime_files for value in declared.values())


FIXTURES = {"att.pdf": "8" * 64, "doc.pdf": "9" * 64}


def _small_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One executed edit case naming an attachment and a run file, and one other
    case, beside the seed and the manifest they resolve against."""

    (tmp_path / "seed.json").write_bytes(b"{}")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"version": 1, "fixtures": FIXTURES}), encoding="utf-8"
    )
    monkeypatch.setattr(outcomes, "FIXTURE_DIR", tmp_path)
    return _corpus(
        tmp_path,
        _edit_case("a", "plan", files=["doc.pdf"], attachments=["att.pdf"]),
        {"id": "b"},
    )


SMALL_SEED = hashlib.sha256(b"{}").hexdigest()
_PASS = [_observation("a", edit=_edit("pass", seed_sha256=SMALL_SEED))]


def _declared_contract(corpus: Path, case_id: str) -> dict[str, Any]:
    """The case contract a run of the corpus seals for a case: the fixture names
    the corpus declares, pinned as the manifest reads now. Read from the raw
    files, not through the code under test, so this cannot share its blind spots."""

    pinned = json.loads((outcomes.FIXTURE_DIR / "manifest.json").read_text("utf-8"))
    cases = json.loads(corpus.read_text(encoding="utf-8"))["cases"]
    case = next((c for c in cases if c["id"] == case_id), {})
    files = ((case.get("execution") or {}).get("inputs") or {}).get("files")
    return {
        "attachment_fixture": {
            "attachments": _pins(pinned["fixtures"], case.get("attachments")),
            "direct_file_slot_count": 0,
            "runtime_files": _pins(pinned["fixtures"], files),
        }
    }


def _pins(pinned: dict[str, str], names: list[str] | None) -> list[dict[str, str]]:
    return [{"name": n, "content_sha256": pinned[n]} for n in names or []]


def _write_suite(
    directory: Path,
    corpus: Path,
    *rows: Any,
    repetitions: int = 3,
    recorded_digest: str | None = "corpus",
    contracts: dict[str, dict[str, Any]] | None = None,
) -> Path:
    """A suite as the harness writes it: a summary and one bundle per row, the
    bundle carrying the case contract the row's digest is of."""

    results = []
    for row in rows:
        case_id = row.case_id
        contract = (contracts or {}).get(case_id) or _declared_contract(corpus, case_id)
        results.append(
            {**row.row, "case_contract_sha256": receipts.canonical_sha256(contract)}
        )
        (directory / row.bundle_file).write_text(
            json.dumps({"case_contract": contract}), encoding="utf-8"
        )
    identity: dict[str, Any] = {"source": {"revision": "r"}}
    if recorded_digest is not None:
        identity["build"] = {
            "cases_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest()
            if recorded_digest == "corpus"
            else recorded_digest
        }
    (directory / receipts.SUITE_SUMMARY_FILE).write_text(
        json.dumps(
            {
                "artifact_schema_version": "1",
                "artifact_mode": "suite",
                "repetitions": repetitions,
                "release_identity": identity,
                "results": results,
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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rows: list[Any] | None = None,
    **suite: Any,
) -> tuple[Path, Path]:
    """The small corpus and a suite of `rows` (default: one passing edit)."""

    corpus = _small_corpus(tmp_path, monkeypatch)
    rows = _PASS if rows is None else rows
    return _write_suite(tmp_path, corpus, *rows, **suite), corpus


@pytest.mark.parametrize(
    ("planned", "extra", "expected"),
    [
        (3, [], "attempted 3: edit_success 1/3"),
        (5, [], "attempted 5: edit_success 1/5"),
        (1, [], "attempted 3 (recorded plan 1): edit_success 1/3"),
        (1, ["--repetitions", "2"], "attempted 2 (recorded plan 1): edit_success 1/2"),
        (1, ["--repetitions", "1"], "attempted 1: edit_success 1/1"),
    ],
)
def test_the_population_is_the_registered_repetitions_or_the_suites_plan_if_larger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    planned: int,
    extra: list[str],
    expected: str,
) -> None:
    suite, corpus = _small_suite(tmp_path, monkeypatch, repetitions=planned)

    code, lines, _ = _run(capsys, suite, corpus, *extra)

    assert code == 0
    assert lines[0].startswith(expected)


def test_fewer_repetitions_than_the_suite_planned_are_refused_not_rescaled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    suite, corpus = _small_suite(tmp_path, monkeypatch, repetitions=3)

    code, lines, error = _run(capsys, suite, corpus, "--repetitions", "1")

    assert (code, lines) == (2, [])
    assert "recorded plan" in error


ONE_EDIT_CASE = {"edit": outcomes.Declared("edit_success", SEED)}


def test_the_report_refuses_a_population_above_the_cap_and_accepts_it_at_the_cap() -> (
    None
):
    cap = outcomes.MAX_POPULATION

    at_cap = outcomes.edit_outcome_report(
        [], declared=ONE_EDIT_CASE, repetitions=cap, planned=1
    )
    assert at_cap["attempted"] == cap
    assert len(at_cap["first_failures"]) <= cap
    with pytest.raises(ValueError, match=rf"{cap + 1} repetitions.*maximum.*{cap}"):
        outcomes.edit_outcome_report(
            [], declared=ONE_EDIT_CASE, repetitions=cap + 1, planned=1
        )
    with pytest.raises(ValueError, match=rf"recorded plan.*{cap + 1} repetitions"):
        outcomes.edit_outcome_report(
            [], declared=ONE_EDIT_CASE, repetitions=cap + 1, planned=cap + 1
        )


@pytest.mark.parametrize(
    ("planned", "extra", "code"),
    [
        (1, ["--repetitions", str(outcomes.MAX_POPULATION)], 0),
        (1, ["--repetitions", str(outcomes.MAX_POPULATION + 1)], 2),
        (outcomes.MAX_POPULATION, [], 0),
        (outcomes.MAX_POPULATION + 1, [], 2),
    ],
    ids=["stated_at_cap", "stated_above", "recorded_at_cap", "recorded_above"],
)
def test_the_cli_bounds_the_population_by_the_stated_and_the_recorded_repetitions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    planned: int,
    extra: list[str],
    code: int,
) -> None:
    suite, corpus = _small_suite(tmp_path, monkeypatch, repetitions=planned)

    result, lines, error = _run(capsys, suite, corpus, *extra)

    assert result == code
    if code == 0:
        assert lines[0].startswith(f"attempted {outcomes.MAX_POPULATION}")
    else:
        assert str(outcomes.MAX_POPULATION) in error
        assert str(outcomes.MAX_POPULATION + 1) in error


def _full_corpus_suite(
    directory: Path,
    *,
    planned: int,
    observed: int,
    contracts: dict[str, dict[str, Any]] | None = None,
) -> tuple[Path, list[str]]:
    """Every case of the real corpus: its edit cases for `observed` repetitions,
    every other case once, as a full-corpus suite that planned `planned`."""

    declared = outcomes.declared_cases(outcomes.DEFAULT_CASES_FILE)
    rows = [
        _observation(
            case_id,
            repetition,
            edit=_edit("pass", seed_sha256=value.seed_sha256) if value else None,
        )
        for case_id, value in declared.items()
        for repetition in range(1, (observed if value else 1) + 1)
    ]
    suite = _write_suite(
        directory,
        outcomes.DEFAULT_CASES_FILE,
        *rows,
        repetitions=planned,
        contracts=contracts,
    )
    return suite, [case_id for case_id, value in declared.items() if value is None]


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
        ([_observation("nobody", edit=None)], "nobody"),
        ([_observation("a", 4, edit=_edit("pass", seed_sha256=SMALL_SEED))], "outside"),
        (
            [_observation("a", edit=_edit("pass", seed_sha256=SMALL_SEED))] * 2,
            "duplicate",
        ),
        ([], "non-empty"),
        ([_observation("a", edit=_edit("pass", seed_sha256="d" * 64))], "seed"),
    ],
    ids=["unknown_case", "repetition_beyond", "duplicate", "empty", "seed"],
)
def test_a_suite_the_corpus_cannot_place_is_refused_with_its_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    rows: list[Any],
    why: str,
) -> None:
    suite, corpus = _small_suite(tmp_path, monkeypatch, rows)

    code, _, error = _run(capsys, suite, corpus, "--repetitions", "3")

    assert code == 2
    assert why in error


@pytest.mark.parametrize("verdict", ["pass", "fail"])
@pytest.mark.parametrize(
    ("status", "failure_class"), [c[:2] for c in NOT_COMPLETED] + [("completed", None)]
)
def test_a_verdict_scored_on_another_seed_is_refused_on_every_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    failure_class: str | None,
    verdict: str,
) -> None:
    edit = _edit(verdict, ("outcome",) if verdict == "fail" else (), "d" * 64)
    row = _observation("a", edit=edit, status=status, failure_class=failure_class)
    suite, corpus = _small_suite(tmp_path, monkeypatch, [row])

    code, _, error = _run(capsys, suite, corpus)

    assert code == 2
    assert "different seed" in error


def _tampered(contract: dict[str, Any], how: str) -> dict[str, Any]:
    """The contract a run would have sealed had the case named other fixtures."""

    fixture = contract["attachment_fixture"]
    kind = "runtime_files" if fixture["runtime_files"] else "attachments"
    pins = fixture[kind]
    changed = {
        "empty": [],
        "missing": pins[:-1],
        "extra": [*pins, pins[0]],
        "renamed": [{**pins[0], "name": "other.pdf"}, *pins[1:]],
        "reordered": pins[::-1],
        "repinned": [{**pins[0], "content_sha256": "0" * 64}, *pins[1:]],
    }[how]
    return {"attachment_fixture": {**fixture, kind: changed}}


TAMPERS = ["empty", "missing", "extra", "renamed", "reordered", "repinned"]


@pytest.mark.parametrize("how", TAMPERS)
def test_a_real_file_backed_case_whose_recorded_fixtures_differ_from_the_corpus_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], how: str
) -> None:
    declared = outcomes.declared_cases(outcomes.DEFAULT_CASES_FILE)
    case_id = next(
        case_id
        for case_id, value in declared.items()
        if value and len(value.runtime_files) > 1
    )
    contract = _declared_contract(outcomes.DEFAULT_CASES_FILE, case_id)
    suite, _ = _full_corpus_suite(
        tmp_path, planned=1, observed=1, contracts={case_id: _tampered(contract, how)}
    )

    code, lines, error = _run(
        capsys, suite, outcomes.DEFAULT_CASES_FILE, "--repetitions", "1"
    )

    assert (code, lines) == (2, [])
    assert case_id in error


@pytest.mark.parametrize(
    "manifest",
    [
        {"doc.pdf": "7" * 64, "att.pdf": FIXTURES["att.pdf"]},
        {"att.pdf": FIXTURES["att.pdf"]},
    ],
    ids=["pin_changed", "fixture_dropped"],
)
def test_a_pass_scored_on_a_fixture_the_manifest_no_longer_pins_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    manifest: dict[str, str],
) -> None:
    suite, corpus = _small_suite(tmp_path, monkeypatch)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"version": 1, "fixtures": manifest}), encoding="utf-8"
    )

    code, lines, error = _run(capsys, suite, corpus)

    assert (code, lines) == (2, [])
    assert "different fixture" in error


@pytest.mark.parametrize("damage", ["another_contract", "gone"])
def test_a_scored_row_whose_bundle_is_not_its_own_contract_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    damage: str,
) -> None:
    suite, corpus = _small_suite(tmp_path, monkeypatch)
    bundle = tmp_path / "a-1.json"
    if damage == "gone":
        bundle.unlink()
    else:
        # The same fixtures, so only the row's digest can tell it is not its own.
        fixture = _declared_contract(corpus, "a")["attachment_fixture"]
        other = {"attachment_fixture": {**fixture, "direct_file_slot_count": 5}}
        bundle.write_text(json.dumps({"case_contract": other}), encoding="utf-8")

    code, _, error = _run(capsys, suite, corpus)

    assert code == 2
    assert "report refused" in error


@pytest.mark.parametrize("recorded", [None, "d" * 64])
def test_a_suite_scored_on_another_corpus_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    recorded: str | None,
) -> None:
    suite, corpus = _small_suite(tmp_path, monkeypatch, recorded_digest=recorded)

    code, _, error = _run(capsys, suite, corpus)

    assert code == 2
    assert "different corpus" in error


def test_an_unreadable_corpus_or_suite_is_a_refusal_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    suite, corpus = _small_suite(tmp_path, monkeypatch)

    assert _run(capsys, suite, tmp_path / "nowhere.json")[0] == 2
    assert _run(capsys, tmp_path / "nowhere", corpus)[0] == 2


@pytest.mark.parametrize(
    "expect",
    [{"outcome": "maybe"}, None, {}, {"outcome": None}, [], "plan"],
    ids=repr,
)
def test_an_edit_expectation_the_vocabulary_lacks_is_refused_not_a_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    expect: Any,
) -> None:
    corpus = _small_corpus(tmp_path, monkeypatch)
    cases = json.loads(corpus.read_text(encoding="utf-8"))
    cases["cases"][0]["edit"]["expect"] = expect
    corpus.write_text(json.dumps(cases), encoding="utf-8")
    suite = _write_suite(tmp_path, corpus, _unavailable("a", seed=SMALL_SEED))

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


def test_the_receipt_keeps_the_scorers_failed_checks_in_evaluation_order() -> None:
    observation = _scored(
        "edit", verdict="fail", failed=("scope", "fulfilment", "diff_matches_applied")
    )

    assert observation.edit.failed_checks == (
        "scope",
        "fulfilment",
        "diff_matches_applied",
    )


def test_the_receipt_names_the_failed_evidence_checks_and_error_codes() -> None:
    observation = _observation(
        "edit",
        edit=None,
        status="invalid_evidence",
        evidence_failed=("second_check", "first_check"),
        error_codes=("code_b", "code_a"),
    )

    assert observation.evidence_failed_check_names == ("second_check", "first_check")
    assert observation.error_codes == ("code_b", "code_a")
