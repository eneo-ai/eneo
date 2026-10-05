"""Runtime input lineage is parsed once into a strict model and judged on it.

The fixtures below are the evidence shapes the product writes; the other
report tests (harness, oracle) build on them.
"""

from __future__ import annotations

import copy
import importlib
import random
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pytest import mark

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

lineage = importlib.import_module("ai_builder_runtime_lineage")
Status = lineage.RuntimeLineageStatus

INPUT_STEP = "5a1f0c3e-7d0b-4c51-9f3e-000000000001"
OTHER_STEP = "5a1f0c3e-7d0b-4c51-9f3e-000000000002"
RUNTIME_FILE = "5a1f0c3e-7d0b-4c51-9f3e-000000000003"
INPUT_ATTEMPT = "5a1f0c3e-7d0b-4c51-9f3e-000000000004"
OTHER_ATTEMPT = "5a1f0c3e-7d0b-4c51-9f3e-000000000005"
SECOND_FILE = "5a1f0c3e-7d0b-4c51-9f3e-000000000006"
UNRUN_STEP = "5a1f0c3e-7d0b-4c51-9f3e-000000000007"
CONSUMED_SHA256 = "b" * 64
FILE_SIZE = 358
COMPLETE_READ: dict[str, Any] = {"run": {"summary": {"omissions": []}}}


def _omission(section: str) -> dict[str, Any]:
    """A reader omission as the product records it (RunViewEvidenceOmission)."""
    return {"reason": "row_limit", "section": section, "rows_omitted": 1}


def runtime_file_edge(
    file_id: str = RUNTIME_FILE,
    *,
    ordinal: int = 0,
    checksum: object = CONSUMED_SHA256,
    byte_size: object = FILE_SIZE,
    binding_ref: str = "runtime_files[0]",
) -> dict[str, Any]:
    return {
        "binding_ref": binding_ref,
        "selection": {"encoding": "bound_file"},
        "source": {
            "kind": "runtime_file",
            "selector": {"kind": "json_path", "path": []},
            "input_file_ordinal": ordinal,
            "file_id": file_id,
            "checksum": checksum,
            "byte_size": byte_size,
        },
    }


def tracked(*edges: dict[str, Any]) -> dict[str, Any]:
    return {"status": "tracked", "schema_version": 1, "edges": list(edges)}


def completed_evidence(
    *, lineage_record: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A run whose input step completed and consumed one uploaded file."""
    return {
        "run_contract": {"steps_requiring_input": [{"step_id": INPUT_STEP}]},
        "uploaded_files": [{"id": RUNTIME_FILE, "size": FILE_SIZE}],
        "step_results": [
            {
                "step_id": INPUT_STEP,
                "status": "completed",
                "current_attempt_no": 1,
                "runtime_input_file_ids": [RUNTIME_FILE],
            },
            {
                "step_id": OTHER_STEP,
                "status": "completed",
                "current_attempt_no": 1,
                "runtime_input_file_ids": [],
            },
        ],
        "step_attempts": [
            {
                "id": INPUT_ATTEMPT,
                "step_id": INPUT_STEP,
                "attempt_no": 1,
                "status": "completed",
                "resolved_input_lineage": (
                    lineage_record
                    if lineage_record is not None
                    else tracked(runtime_file_edge())
                ),
            },
            {
                "id": OTHER_ATTEMPT,
                "step_id": OTHER_STEP,
                "attempt_no": 1,
                "status": "completed",
                "resolved_input_lineage": {"status": "not_tracked"},
            },
        ],
        "debug_export": copy.deepcopy(COMPLETE_READ),
    }


def failed_result_evidence() -> dict[str, Any]:
    """The input step ran and failed: a recorded non-completed result."""
    evidence = completed_evidence()
    evidence["step_results"][0]["status"] = "failed"
    evidence["step_attempts"][0]["status"] = "failed"
    return evidence


def no_result_evidence() -> dict[str, Any]:
    """A complete read that holds no result for the input step."""
    evidence = completed_evidence()
    del evidence["step_results"][0]
    del evidence["step_attempts"][0]
    return evidence


def _judged(evidence: object, expected_count: int = 1) -> Any:
    return lineage.runtime_lineage(evidence, expected_count=expected_count)


COMPLETE = (Status.COMPLETE, (CONSUMED_SHA256,))
NOT_REACHED = (Status.NOT_REACHED, (None,))


def _outcome(evidence: object, expected_count: int = 1) -> tuple[Any, Any]:
    judged = _judged(evidence, expected_count)
    return judged.status, judged.sha256s


@mark.parametrize(
    ("build", "expected"),
    [
        (completed_evidence, COMPLETE),
        (failed_result_evidence, NOT_REACHED),
        (no_result_evidence, NOT_REACHED),
        (lambda: None, NOT_REACHED),
    ],
    ids=["completed", "failed_result", "no_result_complete_read", "never_executed"],
)
def test_each_valid_base_record_has_its_lineage(
    build: Callable[[], object], expected: tuple[Any, Any]
) -> None:
    assert _outcome(build()) == expected
    assert _judged(build()).holds


def test_a_case_without_runtime_files_reads_no_evidence_and_holds() -> None:
    for evidence in (completed_evidence(), None, "garbage", {"step_results": 7}):
        judged = _judged(evidence, expected_count=0)
        assert (judged.status, judged.sha256s) == (Status.NOT_REQUIRED, ())
        assert judged.holds


def _set(path: tuple[Any, ...], value: object) -> Callable[[Any], None]:
    def apply(evidence: Any) -> None:
        node = evidence
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return apply


def _drop(path: tuple[Any, ...]) -> Callable[[Any], None]:
    def apply(evidence: Any) -> None:
        node = evidence
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]

    return apply


def _append(
    path: tuple[Any, ...], row: Callable[[Any], object]
) -> Callable[[Any], None]:
    def apply(evidence: Any) -> None:
        node = evidence
        for key in path:
            node = node[key]
        node.append(row(evidence))

    return apply


_UUID_MALFORMATIONS: dict[str, object] = {
    "null": None,
    "int": 7,
    "bool": True,
    "list": [],
    "blank": "",
    "whitespace": "   ",
    "not_a_uuid": "reader-step",
}
_ATTEMPT_NO_MALFORMATIONS: dict[str, object] = {
    "bool": True,
    "float": 1.0,
    "string": "1",
    "zero": 0,
    "list": [],
}
_ROWS_MALFORMATIONS: dict[str, object] = {
    "null": None,
    "mapping": {},
    "scalar": "rows",
    "none_row": [None],
    "scalar_row": ["row"],
}
_INPUT_ATTEMPT = ("step_attempts", 0)
_LINEAGE_SOURCE = (*_INPUT_ATTEMPT, "resolved_input_lineage", "edges", 0, "source")

# Each field the parser reads, its contract-breaking values and the reason the
# contract names. Nullable fields (`current_attempt_no`, `debug_export`) are
# absent from the null column: null is a legal value there (see the
# preservation test).
_FIELD_CONTRACTS: list[tuple[tuple[Any, ...], dict[str, object], Any]] = [
    (
        ("run_contract",),
        {"null": None, "list": [], "scalar": "x"},
        Status.INPUT_STEP_INVALID,
    ),
    (
        ("run_contract", "steps_requiring_input"),
        {**_ROWS_MALFORMATIONS, "empty": []},
        Status.INPUT_STEP_INVALID,
    ),
    (
        ("run_contract", "steps_requiring_input", 0, "step_id"),
        _UUID_MALFORMATIONS,
        Status.INPUT_STEP_INVALID,
    ),
    (("uploaded_files",), _ROWS_MALFORMATIONS, Status.UPLOADED_FILES_INVALID),
    (("uploaded_files", 0, "id"), _UUID_MALFORMATIONS, Status.UPLOADED_FILES_INVALID),
    (
        ("uploaded_files", 0, "size"),
        {"null": None, "bool": True, "float": 358.0, "string": "358", "negative": -1},
        Status.UPLOADED_FILES_INVALID,
    ),
    (("step_results",), _ROWS_MALFORMATIONS, Status.STEP_RESULTS_INVALID),
    (("step_results", 0, "step_id"), _UUID_MALFORMATIONS, Status.STEP_RESULTS_INVALID),
    (
        ("step_results", 0, "status"),
        {
            "null": None,
            "unknown": "mystery",
            "upper": "COMPLETED",
            "int": 1,
            "blank": "",
        },
        Status.STEP_RESULTS_INVALID,
    ),
    (
        ("step_results", 0, "current_attempt_no"),
        _ATTEMPT_NO_MALFORMATIONS,
        Status.STEP_RESULTS_INVALID,
    ),
    (
        ("step_results", 0, "runtime_input_file_ids"),
        {
            "null": None,
            "mapping": {},
            "scalar": RUNTIME_FILE,
            "none_id": [None],
            "blank_id": [""],
        },
        Status.STEP_RESULTS_INVALID,
    ),
    (("step_attempts",), _ROWS_MALFORMATIONS, Status.STEP_ATTEMPTS_INVALID),
    ((*_INPUT_ATTEMPT, "id"), _UUID_MALFORMATIONS, Status.STEP_ATTEMPTS_INVALID),
    ((*_INPUT_ATTEMPT, "step_id"), _UUID_MALFORMATIONS, Status.STEP_ATTEMPTS_INVALID),
    (
        (*_INPUT_ATTEMPT, "attempt_no"),
        {"null": None, **_ATTEMPT_NO_MALFORMATIONS},
        Status.STEP_ATTEMPTS_INVALID,
    ),
    (
        (*_INPUT_ATTEMPT, "status"),
        {"null": None, "unknown": "mystery", "result_only": "pending", "int": 1},
        Status.STEP_ATTEMPTS_INVALID,
    ),
    (
        (*_INPUT_ATTEMPT, "resolved_input_lineage"),
        {"null": None, "list": [], "unknown_status": {"status": "not_reached"}},
        Status.STEP_ATTEMPTS_INVALID,
    ),
    (
        (*_INPUT_ATTEMPT, "resolved_input_lineage", "edges"),
        {"null": None, "mapping": {}, "none_edge": [None]},
        Status.STEP_ATTEMPTS_INVALID,
    ),
    (
        (*_LINEAGE_SOURCE, "byte_size"),
        {"null": None, "bool": True, "float": 358.0, "string": "358"},
        Status.STEP_ATTEMPTS_INVALID,
    ),
    (
        (*_LINEAGE_SOURCE, "input_file_ordinal"),
        {"null": None, "bool": False, "float": 0.0},
        Status.STEP_ATTEMPTS_INVALID,
    ),
    ((*_LINEAGE_SOURCE, "file_id"), _UUID_MALFORMATIONS, Status.STEP_ATTEMPTS_INVALID),
    (
        (*_LINEAGE_SOURCE, "checksum"),
        {"null": None, "int": 7, "blank": ""},
        Status.STEP_ATTEMPTS_INVALID,
    ),
    (
        ("debug_export",),
        {"list": [], "scalar": "x", "empty": {}},
        Status.READER_METADATA_INVALID,
    ),
    (
        ("debug_export", "run", "summary", "omissions"),
        {
            "null": None,
            **_ROWS_MALFORMATIONS,
            "untyped_row": [{"section": "step_results"}],
            "padded_section": [_omission(" step_results")],
            "newline_section": [_omission("step_results\n")],
            "upper_section": [_omission("STEP_RESULTS")],
            "unknown_reason": [{**_omission("step_results"), "reason": "other"}],
            "bool_rows": [{**_omission("step_results"), "rows_omitted": True}],
        },
        Status.READER_METADATA_INVALID,
    ),
]


def _malformations() -> list[tuple[str, Callable[[Any], None], Any]]:
    cases: list[tuple[str, Callable[[Any], None], Any]] = []
    for path, values, reason in _FIELD_CONTRACTS:
        name = ".".join(map(str, path))
        cases.append((f"{name}:drop", _drop(path), reason))
        cases += [
            (f"{name}:{label}", _set(path, value), reason)
            for label, value in values.items()
        ]
    # A valid row beside a junk row is never read as the valid rows alone.
    for path, reason in (
        (("run_contract", "steps_requiring_input"), Status.INPUT_STEP_INVALID),
        (("uploaded_files",), Status.UPLOADED_FILES_INVALID),
        (("step_results",), Status.STEP_RESULTS_INVALID),
        (("step_attempts",), Status.STEP_ATTEMPTS_INVALID),
        (
            ("debug_export", "run", "summary", "omissions"),
            Status.READER_METADATA_INVALID,
        ),
    ):
        for label, junk in (("none", None), ("str", "row"), ("empty", {})):
            cases.append(
                (
                    f"{'.'.join(path)}:junk_row_{label}",
                    _append(path, lambda _e, junk=junk: junk),
                    reason,
                )
            )
    # Extra and duplicate rows break a row contract too.
    cases += [
        (
            "steps_requiring_input:extra_row",
            _append(
                ("run_contract", "steps_requiring_input"),
                lambda _e: {"step_id": OTHER_STEP},
            ),
            Status.INPUT_STEP_INVALID,
        ),
        (
            "uploaded_files:duplicate_row",
            _append(
                ("uploaded_files",), lambda e: copy.deepcopy(e["uploaded_files"][0])
            ),
            Status.UPLOADED_FILES_INVALID,
        ),
        (
            "uploaded_files:extra_row",
            _append(("uploaded_files",), lambda _e: {"id": SECOND_FILE, "size": 1}),
            Status.UPLOADED_FILES_INVALID,
        ),
        (
            "step_results:duplicate_row",
            _append(("step_results",), lambda e: copy.deepcopy(e["step_results"][-1])),
            Status.STEP_RESULTS_INVALID,
        ),
        (
            "step_attempts:duplicate_row",
            _append(
                ("step_attempts",), lambda e: copy.deepcopy(e["step_attempts"][-1])
            ),
            Status.STEP_ATTEMPTS_INVALID,
        ),
        (
            "step_attempts:duplicate_attempt_no",
            _append(
                ("step_attempts",),
                lambda e: {**copy.deepcopy(e["step_attempts"][-1]), "id": SECOND_FILE},
            ),
            Status.STEP_ATTEMPTS_INVALID,
        ),
        (
            "step_attempts:duplicate_id",
            _append(
                ("step_attempts",),
                lambda e: {**copy.deepcopy(e["step_attempts"][-1]), "attempt_no": 2},
            ),
            Status.STEP_ATTEMPTS_INVALID,
        ),
        (
            "runtime_evidence:not_json",
            lambda e: e.clear() or e.update({"run_contract": object()}),
            Status.RUNTIME_EVIDENCE_MALFORMED,
        ),
    ]
    return cases


_MALFORMATIONS = _malformations()


@mark.parametrize(
    ("mutate", "reason"),
    [(mutate, reason) for _, mutate, reason in _MALFORMATIONS],
    ids=[name for name, _, _ in _MALFORMATIONS],
)
def test_a_contract_breaking_field_is_invalid_evidence_with_its_reason(
    mutate: Callable[[Any], None], reason: Any
) -> None:
    applied = 0
    for base in (completed_evidence, failed_result_evidence, no_result_evidence):
        evidence = base()
        try:
            mutate(evidence)
        except (IndexError, KeyError):
            continue  # the base has no such row (no_result_evidence)
        applied += 1
        judged = _judged(evidence)
        assert (judged.status, judged.sha256s) == (reason, (None,)), base.__name__
        assert not judged.holds
    assert applied >= 2


def test_random_combined_malformations_never_yield_valid_lineage() -> None:
    rng = random.Random(20261001)
    bases = (completed_evidence, failed_result_evidence, no_result_evidence)
    applied_draws = 0
    for _ in range(500):
        evidence = rng.choice(bases)()
        applied = 0
        for _, mutate, _reason in rng.sample(_MALFORMATIONS, rng.randint(2, 3)):
            try:
                mutate(evidence)
                applied += 1
            except (AttributeError, IndexError, KeyError, TypeError):
                continue  # an earlier malformation removed this path
        if not applied:
            continue
        applied_draws += 1
        judged = _judged(evidence)
        assert judged.status not in {Status.COMPLETE, Status.NOT_REACHED}
        assert judged.sha256s == (None,)
        assert not judged.holds
    assert applied_draws > 450


def _injected_supersession(evidence: dict[str, Any]) -> None:
    for attempt in evidence["step_attempts"]:
        attempt["superseded_by_attempt_id"] = "not even a uuid"


@mark.parametrize(
    ("build", "change", "expected"),
    [
        (completed_evidence, lambda e: e.update(debug_export=None), COMPLETE),
        (completed_evidence, _injected_supersession, COMPLETE),
        (completed_evidence, lambda e: e["step_results"].reverse(), COMPLETE),
        (completed_evidence, lambda e: e["step_results"].pop(), COMPLETE),
        (
            completed_evidence,
            lambda e: e["step_results"][1].update(current_attempt_no=None),
            COMPLETE,
        ),
        (
            completed_evidence,
            lambda e: e["uploaded_files"][0].update(extra="kept out"),
            COMPLETE,
        ),
        (
            completed_evidence,
            lambda e: e["debug_export"]["run"]["summary"]["omissions"].append(
                _omission("provider_calls")
            ),
            COMPLETE,
        ),
        # Any valid UUID representation is normalized (no canonical-wire rule).
        (
            completed_evidence,
            lambda e: e["uploaded_files"][0].update(id=RUNTIME_FILE.upper()),
            COMPLETE,
        ),
        (failed_result_evidence, lambda e: e.update(step_attempts=[]), NOT_REACHED),
        (failed_result_evidence, lambda e: e.update(debug_export=None), NOT_REACHED),
        (
            failed_result_evidence,
            lambda e: e["step_results"][0].update(current_attempt_no=None),
            NOT_REACHED,
        ),
        (no_result_evidence, lambda e: e.update(step_attempts=[]), NOT_REACHED),
        (no_result_evidence, lambda e: e.update(step_results=[]), NOT_REACHED),
        (no_result_evidence, _injected_supersession, NOT_REACHED),
    ],
    ids=[
        "completed_without_reader_metadata",
        "completed_with_supersession_key",
        "completed_rows_reordered",
        "completed_without_other_step",
        "completed_other_step_without_attempt",
        "completed_upload_extra_field",
        "completed_unrelated_omission",
        "completed_uppercase_uuid",
        "failed_without_attempts",
        "failed_without_reader_metadata",
        "failed_without_attempt_no",
        "no_result_without_attempts",
        "no_result_without_any_result",
        "no_result_with_supersession_key",
    ],
)
def test_a_valid_change_preserves_the_lineage(
    build: Callable[[], dict[str, Any]],
    change: Callable[[dict[str, Any]], None],
    expected: tuple[Any, Any],
) -> None:
    evidence = build()
    change(evidence)
    assert _outcome(evidence) == expected


def _with(
    build: Callable[[], dict[str, Any]], change: Callable[[dict[str, Any]], None]
) -> dict[str, Any]:
    evidence = build()
    change(evidence)
    return evidence


def _completed_attempt_for_input(evidence: dict[str, Any]) -> None:
    evidence["step_attempts"].append(
        {
            "id": SECOND_FILE,
            "step_id": INPUT_STEP,
            "attempt_no": 2,
            "status": "completed",
            # Supersession is not a producer field: it cannot hide completion.
            "superseded_by_attempt_id": OTHER_ATTEMPT,
            "resolved_input_lineage": {"status": "not_tracked"},
        }
    )


def _contract_names_another_step(evidence: dict[str, Any]) -> None:
    evidence["run_contract"]["steps_requiring_input"] = [{"step_id": UNRUN_STEP}]


@mark.parametrize(
    ("evidence", "expected"),
    [
        (
            _with(
                failed_result_evidence,
                lambda e: e["step_results"][0].update(status="pending"),
            ),
            Status.NOT_REACHED,
        ),
        (
            _with(
                failed_result_evidence,
                lambda e: e["step_results"][0].update(status="running"),
            ),
            Status.NOT_REACHED,
        ),
        (
            _with(
                failed_result_evidence,
                lambda e: e["step_results"][0].update(status="cancelled"),
            ),
            Status.NOT_REACHED,
        ),
        (
            _with(no_result_evidence, lambda e: e.update(debug_export=None)),
            Status.CURRENT_STEP_UNREAD,
        ),
        (
            _with(
                no_result_evidence,
                lambda e: e["debug_export"]["run"]["summary"]["omissions"].append(
                    _omission("step_results")
                ),
            ),
            Status.CURRENT_STEP_UNREAD,
        ),
        (
            _with(no_result_evidence, _completed_attempt_for_input),
            Status.CURRENT_STEP_CONTRADICTORY,
        ),
        (
            _with(failed_result_evidence, _completed_attempt_for_input),
            Status.CURRENT_STEP_CONTRADICTORY,
        ),
        (
            _with(
                failed_result_evidence,
                lambda e: e["step_attempts"][0].update(status="completed"),
            ),
            Status.CURRENT_STEP_CONTRADICTORY,
        ),
        (
            _with(completed_evidence, _contract_names_another_step),
            Status.CURRENT_STEP_CONTRADICTORY,
        ),
        (
            _with(
                completed_evidence,
                lambda e: _contract_names_another_step(e)
                or e["step_attempts"][0].update(
                    resolved_input_lineage={"status": "not_tracked"}
                ),
            ),
            Status.CURRENT_STEP_CONTRADICTORY,
        ),
        (
            _with(
                completed_evidence,
                lambda e: _contract_names_another_step(e)
                or e["step_results"][0].update(runtime_input_file_ids=[]),
            ),
            Status.CURRENT_STEP_CONTRADICTORY,
        ),
        (
            _with(
                failed_result_evidence,
                lambda e: e["step_results"][1].update(
                    runtime_input_file_ids=[RUNTIME_FILE]
                ),
            ),
            Status.CURRENT_STEP_CONTRADICTORY,
        ),
        ("corrupted evidence", Status.RUNTIME_EVIDENCE_MALFORMED),
        ({"run_contract": float("nan")}, Status.RUNTIME_EVIDENCE_MALFORMED),
        (
            _with(completed_evidence, lambda e: e["uploaded_files"].clear()),
            Status.UPLOADED_FILES_INVALID,
        ),
        (
            _with(
                completed_evidence,
                lambda e: e["step_results"][0].update(current_attempt_no=None),
            ),
            Status.CURRENT_STEP_INVALID,
        ),
        (
            _with(
                completed_evidence,
                lambda e: e["step_results"][0].update(runtime_input_file_ids=[]),
            ),
            Status.CURRENT_STEP_INVALID,
        ),
        (
            _with(
                completed_evidence,
                lambda e: e["step_results"][0].update(current_attempt_no=2),
            ),
            Status.CURRENT_ATTEMPT_INVALID,
        ),
        (
            _with(
                completed_evidence,
                lambda e: e["step_attempts"][0].update(status="failed"),
            ),
            Status.CURRENT_ATTEMPT_INVALID,
        ),
        (
            completed_evidence(lineage_record={"status": "not_tracked"}),
            Status.CURRENT_LINEAGE_NOT_TRACKED,
        ),
        (
            completed_evidence(
                lineage_record={
                    "status": "corrupt",
                    "error_code": "flow_resolved_input_edges_invalid_payload",
                    "message": "x",
                }
            ),
            Status.CURRENT_LINEAGE_NOT_TRACKED,
        ),
        (
            completed_evidence(lineage_record=tracked()),
            Status.CURRENT_LINEAGE_INCOMPLETE,
        ),
        (
            completed_evidence(lineage_record=tracked(runtime_file_edge(checksum="x"))),
            Status.CURRENT_LINEAGE_INVALID,
        ),
        (
            completed_evidence(
                lineage_record=tracked(runtime_file_edge(byte_size=359))
            ),
            Status.CURRENT_LINEAGE_INVALID,
        ),
        (
            completed_evidence(lineage_record=tracked(runtime_file_edge(SECOND_FILE))),
            Status.CURRENT_LINEAGE_INVALID,
        ),
        (
            completed_evidence(
                lineage_record=tracked(runtime_file_edge(), runtime_file_edge())
            ),
            Status.CURRENT_LINEAGE_INVALID,
        ),
        (
            completed_evidence(
                lineage_record=tracked(
                    runtime_file_edge(ordinal=1, binding_ref="runtime_files[1]")
                )
            ),
            Status.CURRENT_LINEAGE_INVALID,
        ),
    ],
    ids=[
        "pending_result",
        "running_result",
        "cancelled_result",
        "no_result_unread",
        "no_result_step_results_omitted",
        "no_result_but_completed_attempt",
        "failed_result_but_completed_attempt",
        "failed_result_its_attempt_completed",
        "contract_names_a_step_without_result_while_uploads_were_consumed",
        "consumer_result_lists_the_uploads",
        "consumer_attempt_has_a_runtime_file_edge",
        "another_completed_step_read_the_uploads",
        "scalar_runtime_evidence",
        "not_json",
        "fewer_uploads_than_expected",
        "completed_without_attempt_no",
        "completed_other_files",
        "current_attempt_absent",
        "current_attempt_failed",
        "lineage_not_tracked",
        "lineage_corrupt",
        "lineage_without_runtime_edge",
        "checksum_not_sha256",
        "size_differs_from_upload",
        "file_not_uploaded",
        "file_twice",
        "ordinal_out_of_range",
    ],
)
def test_the_policy_names_what_the_evidence_does_not_prove(
    evidence: object, expected: Any
) -> None:
    judged = _judged(evidence)
    assert judged.status == expected
    assert judged.holds is (expected is Status.NOT_REACHED)


def test_per_source_runs_prove_lineage_with_local_ordinals() -> None:
    evidence = completed_evidence(
        lineage_record=tracked(
            runtime_file_edge(checksum="a" * 64),
            runtime_file_edge(SECOND_FILE, checksum="c" * 64, byte_size=22),
        )
    )
    evidence["uploaded_files"].append({"id": SECOND_FILE, "size": 22})
    evidence["step_results"][0]["runtime_input_file_ids"].append(SECOND_FILE)

    assert _outcome(evidence, expected_count=2) == (
        Status.COMPLETE,
        ("a" * 64, "c" * 64),
    )


@mark.parametrize(
    ("status", "sha256s", "holds"),
    [
        ("not_required", (), True),
        ("not_required", (None,), False),
        ("complete", (CONSUMED_SHA256,), True),
        ("complete", (None,), False),
        ("complete", (), False),
        ("not_reached", (None,), True),
        ("not_reached", (CONSUMED_SHA256,), False),
        ("not_reached", (), False),
        ("current_step_unread", (None,), False),
    ],
)
def test_only_the_three_valid_statuses_hold_with_their_digests(
    status: str, sha256s: tuple[str | None, ...], holds: bool
) -> None:
    assert lineage.RuntimeLineage(Status(status), sha256s).holds is holds


def _two_file_evidence(*edges: dict[str, Any]) -> dict[str, Any]:
    evidence = completed_evidence(lineage_record=tracked(*edges))
    evidence["uploaded_files"].append({"id": SECOND_FILE, "size": 22})
    evidence["step_results"][0]["runtime_input_file_ids"].append(SECOND_FILE)
    return evidence


@mark.parametrize(
    "edges",
    [
        # Run-global ordinals in the wrong order.
        (
            runtime_file_edge(ordinal=1, binding_ref="runtime_files[1]"),
            runtime_file_edge(SECOND_FILE, ordinal=0, byte_size=22),
        ),
        # Local ordinal 0 is per-source only when each source is runtime_files[0].
        (
            runtime_file_edge(),
            runtime_file_edge(
                SECOND_FILE, byte_size=22, binding_ref="runtime_files[1]"
            ),
        ),
    ],
    ids=["swapped_global_ordinals", "local_ordinal_on_another_binding"],
)
def test_two_files_need_global_or_per_source_ordinals(
    edges: tuple[dict[str, Any], ...],
) -> None:
    judged = _judged(_two_file_evidence(*edges), expected_count=2)
    assert judged.status is Status.CURRENT_LINEAGE_INVALID


def test_two_files_with_global_ordinals_prove_lineage() -> None:
    evidence = _two_file_evidence(
        runtime_file_edge(checksum="a" * 64),
        runtime_file_edge(
            SECOND_FILE,
            ordinal=1,
            checksum="c" * 64,
            byte_size=22,
            binding_ref="runtime_files[1]",
        ),
    )
    assert _outcome(evidence, expected_count=2) == (
        Status.COMPLETE,
        ("a" * 64, "c" * 64),
    )


def test_uploads_sharing_an_id_are_invalid_whatever_the_count() -> None:
    evidence = completed_evidence()
    evidence["uploaded_files"].append({"id": RUNTIME_FILE, "size": FILE_SIZE})
    evidence["step_results"][0]["runtime_input_file_ids"].append(RUNTIME_FILE)

    assert _judged(evidence, expected_count=2).status is Status.UPLOADED_FILES_INVALID


def test_a_bundle_without_its_runtime_evidence_recorded_nothing() -> None:
    assert lineage.recorded_runtime_lineage({}, expected_count=1).status is (
        Status.RUNTIME_EVIDENCE_UNRECORDED
    )
    assert lineage.recorded_runtime_lineage(
        {"runtime_evidence": None}, expected_count=1
    ) == lineage.RuntimeLineage(Status.NOT_REACHED, (None,))
    assert lineage.recorded_runtime_lineage({}, expected_count=0).holds


_NOT_REACHED_ONE = lineage.RuntimeLineage(Status.NOT_REACHED, (None,))
_COMPLETE_ONE = lineage.RuntimeLineage(Status.COMPLETE, (CONSUMED_SHA256,))


@mark.parametrize(
    ("recomputed", "status", "sha256s", "accepted"),
    [
        (_NOT_REACHED_ONE, "not_reached", [None], True),
        (_COMPLETE_ONE, "complete", [CONSUMED_SHA256], True),
        (lineage.RuntimeLineage(Status.NOT_REQUIRED, ()), "not_required", [], True),
        (_NOT_REACHED_ONE, "missing", [None], False),
        (_NOT_REACHED_ONE, "complete", [CONSUMED_SHA256], False),
        (_NOT_REACHED_ONE, "not_reached", [None, None], False),
        (_NOT_REACHED_ONE, "not_reached", [CONSUMED_SHA256], False),
        (_COMPLETE_ONE, "complete", ["c" * 64], False),
        (_COMPLETE_ONE, "complete", (CONSUMED_SHA256,), False),
        (_NOT_REACHED_ONE, None, [None], False),
        (
            lineage.RuntimeLineage(Status.CURRENT_STEP_UNREAD, (None,)),
            "current_step_unread",
            [None],
            False,
        ),
    ],
    ids=[
        "not_reached",
        "complete",
        "not_required",
        "retired_status",
        "claims_complete",
        "extra_digest",
        "not_reached_with_digest",
        "other_digest",
        "not_a_json_list",
        "no_status",
        "matching_failure",
    ],
)
def test_a_stored_claim_is_accepted_only_as_the_recomputed_lineage_that_holds(
    recomputed: Any, status: object, sha256s: object, accepted: bool
) -> None:
    identity = {"runtime_evidence_status": status, "runtime_source_sha256s": sha256s}
    assert recomputed.accepts(identity) is accepted
