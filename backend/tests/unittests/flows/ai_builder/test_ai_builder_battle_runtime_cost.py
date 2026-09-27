"""The runtime cost gate, from sealed observation rows to the comparator.

Each row here is a real observation: a live-case bundle whose run is driven
through the harness against a fake Flow API, scored by the quality report,
sealed and projected as a suite result. Only the evidence page varies.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

from pytest import MonkeyPatch, mark, raises

from tests.unittests.flows.ai_builder.test_ai_builder_api_battle_harness import (
    _RUN_PATH,  # pyright: ignore[reportPrivateUsage]
    _battle_harness,  # pyright: ignore[reportPrivateUsage]
    _complete_live_case_bundle,  # pyright: ignore[reportPrivateUsage]
    _completed_text_run,  # pyright: ignore[reportPrivateUsage]
    _execute,  # pyright: ignore[reportPrivateUsage]
    _execution,  # pyright: ignore[reportPrivateUsage]
    _provider_call_item,  # pyright: ignore[reportPrivateUsage]
    _RuntimeApi,  # pyright: ignore[reportPrivateUsage]
)
from tests.unittests.flows.ai_builder.test_ai_builder_battle_compare import (
    _compare_module,  # pyright: ignore[reportPrivateUsage]
    _summary,  # pyright: ignore[reportPrivateUsage]
)

_FACTS = ("Kvissleby", "Njurunda")
_FULL_TEXT = "Förskolan i Kvissleby i Njurunda avvecklas."


class _EvidenceApi(_RuntimeApi):
    """The runtime API, answering the evidence read with a whole page."""

    def __init__(
        self,
        *,
        runs: list[dict[str, object]],
        evidence: object,
        contract: dict[str, object],
    ) -> None:
        super().__init__(runs=runs, contract=contract)
        self.evidence = evidence

    def request(self, *, method: str, path: str, **kwargs: Any) -> object:
        if path == f"{_RUN_PATH}/evidence/":
            return copy.deepcopy(self.evidence)
        return super().request(method=method, path=path, **kwargs)


def _evidence(finishes: tuple[str | None, ...]) -> dict[str, Any]:
    """One model step per finish, one completion call each, then a renderer
    step whose attempt makes no call and so reports no finish reason."""

    calls = len(finishes)
    return {
        "provider_calls": {
            "items": [
                _provider_call_item(
                    f"call-{order}",
                    step_order=order,
                    num_tokens_input=100,
                    num_tokens_output=20,
                )
                for order in range(1, calls + 1)
            ],
            "count": calls,
            "total_count": calls,
            "total_count_truncated": False,
            "has_more": False,
            "next_after_event_id": None,
        },
        "debug_export": {
            "run": {"summary": {"omissions": [], "attempts_count": calls + 1}},
            "steps": [
                {
                    "step_order": order,
                    "attempts": [{"attempt_no": 1, "finish_reason": reason}],
                }
                for order, reason in enumerate((*finishes, None), start=1)
            ],
        },
        "step_results": [],
    }


class _Observer:
    """Seals one observation per call and reads its row back as a suite does:
    sealed, written, then read from the file through the receipt reader."""

    def __init__(self, monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
        self.harness: ModuleType = _battle_harness()
        self.monkeypatch = monkeypatch
        self.tmp_path = tmp_path
        self.sealed = 0

    def row(
        self,
        *,
        case_id: str = "case-a",
        repetition: int = 1,
        finishes: tuple[str | None, ...] = ("stop", "stop"),
        text: str = _FULL_TEXT,
        run_status: str = "completed",
        declared_output: str = "text",
        usage: dict[str, object] | None = None,
        executes: bool = True,
        runs: bool = True,
        edit: Callable[[dict[str, Any]], None] | None = None,
        required_facts: tuple[str, ...] = _FACTS,
    ) -> dict[str, Any]:
        harness = self.harness
        execution = _execution(harness, required_facts=required_facts)
        case = harness.BattleCase(
            case_id=case_id,
            prompt="Build and run the Flow.",
            apply_plan=True,
            execution=execution if executes else None,
        )
        plan_check = {"name": "plan_created", "passed": True, "actual": True}
        bundle = _complete_live_case_bundle(
            harness, case, quality_checks=[{**plan_check, "expected": True}]
        )
        bundle["journey"] = {"outcome_class": "plan_first_pass"}
        bundle["repetition"] = repetition
        # A case that declares execution but never reaches a run (no plan, a
        # refused run) has no runtime evidence at all.
        if executes and runs:
            evidence = _evidence(finishes)
            if edit is not None:
                edit(evidence)
            calls = len(finishes)
            run = {
                **_completed_text_run(text),
                "status": run_status,
                "token_usage": usage
                or {
                    "num_tokens_input": 100 * calls,
                    "num_tokens_output": 20 * calls,
                    "num_tokens_total": 120 * calls,
                    "input_completeness": "complete",
                    "output_completeness": "complete",
                },
            }
            _EvidenceApi(
                runs=[run],
                evidence=evidence,
                contract={"final_output": {"output_type": declared_output}},
            ).install(harness, self.monkeypatch)
            runtime_evidence, report = _execute(
                harness, execution, tmp_path=self.tmp_path
            )
            bundle["runtime_evidence"] = runtime_evidence
            quality_report = bundle["quality_report"]
            assert isinstance(quality_report, dict)
            quality_report.update(
                output_checks=report["output_checks"],
                output_success=report["output_success"],
            )
        self.sealed += 1
        output_dir = self.tmp_path / f"observation-{self.sealed}"
        output_dir.mkdir()
        bundle_path = harness._write_bundle(
            output_dir,
            harness.seal_observation(bundle),
            suffix=f"{case_id}-r{repetition:02d}",
        )
        written = json.loads(bundle_path.read_text(encoding="utf-8"))
        row = harness._suite_result(written, bundle_path)
        return dict(harness.observation_from_row(row, where=bundle_path.name).row)


def _compare(
    tmp_path: Path,
    baseline: list[dict[str, Any]],
    current: list[dict[str, Any]],
    *,
    allowance: int | None = 1,
    **gate: Any,
) -> dict[str, Any]:
    paths: list[Path] = []
    for name, rows in (("base.json", baseline), ("cur.json", current)):
        path = tmp_path / name
        path.write_text(json.dumps(_summary(rows)), encoding="utf-8")
        paths.append(path)
    return _compare_module().compare(
        paths[0], paths[1], runtime_call_allowance=allowance, **gate
    )


def _failures(report: dict[str, Any]) -> dict[str, list[str]]:
    failed = report["runtime_cost_failed_cases"]
    assert isinstance(failed, dict)
    return failed


def test_calls_within_the_allowance_pass_and_are_reported(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    parent = [
        observer.row(repetition=1),
        observer.row(repetition=2, finishes=("stop", "stop", "stop")),
        observer.row(case_id="plan-only", executes=False),
    ]
    candidate = [
        observer.row(repetition=1, finishes=("stop",) * 4),
        observer.row(repetition=2, finishes=("stop", "tool_calls", "stop")),
        observer.row(case_id="plan-only", executes=False),
    ]

    assert parent[0]["runtime_cost"] == {
        "provider_calls": 2,
        "provider_call_evidence": "complete",
        "total_tokens": 240,
        "tokens_complete": True,
        "finish_reasons": {"stop": 2},
        "length_finishes": 0,
        "complete": True,
    }
    assert parent[0]["output_required_facts"] == {"Kvissleby": True, "Njurunda": True}
    assert parent[2]["runtime_cost"] is None

    # Calls alone are under test; tokens scale with them here.
    report = _compare(tmp_path, parent, candidate, runtime_token_tolerance=2)

    assert report["runtime_cost_failed_cases"] == {}
    case = next(item for item in report["cases"] if item["case_id"] == "case-a")
    assert [cost["provider_calls"] for cost in case["runtime_cost"]["before"]] == [2, 3]
    assert [cost["provider_calls"] for cost in case["runtime_cost"]["after"]] == [4, 3]
    assert case["runtime_cost"]["failures"] == []
    plan_only = next(item for item in report["cases"] if item["case_id"] == "plan-only")
    assert "runtime_cost" not in plan_only
    # Without an allowance the costs are reported and nothing is gated.
    ungated = _compare(tmp_path, parent, candidate, allowance=None)
    assert ungated["runtime_cost_failed_cases"] is None
    assert (
        "failures"
        not in next(item for item in ungated["cases"] if item["case_id"] == "case-a")[
            "runtime_cost"
        ]
    )


def test_calls_over_the_allowance_fail_and_exit_nonzero(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    parent = [observer.row()]
    candidate = [observer.row(finishes=("stop",) * 4)]

    report = _compare(tmp_path, parent, candidate, runtime_token_tolerance=2)

    assert _failures(report) == {
        "case-a": [
            "current r1 made 4 runtime calls; the baseline's most is 2, allowance 1"
        ]
    }
    module = _compare_module()
    monkeypatch.setattr(
        "sys.argv",
        [
            "compare",
            "compare",
            str(tmp_path / "base.json"),
            str(tmp_path / "cur.json"),
            "--runtime-call-allowance",
            "1",
        ],
    )
    with raises(SystemExit) as exited:
        module.main()
    assert exited.value.code == 1


def _truncated(evidence: dict[str, Any]) -> None:
    evidence["provider_calls"]["total_count_truncated"] = True


def _no_provider_calls(evidence: dict[str, Any]) -> None:
    del evidence["provider_calls"]


def _attempts_omitted(evidence: dict[str, Any]) -> None:
    evidence["debug_export"]["run"]["summary"]["omissions"] = [
        {"reason": "row_limit", "section": "step_attempts", "rows_omitted": 1}
    ]


def _attempt_unseen(evidence: dict[str, Any]) -> None:
    evidence["debug_export"]["run"]["summary"]["attempts_count"] += 1


def _no_debug_export(evidence: dict[str, Any]) -> None:
    del evidence["debug_export"]


def _model_finish_unreported(evidence: dict[str, Any]) -> None:
    # The first step made a completion call, so its attempt owes a reason.
    evidence["debug_export"]["steps"][0]["attempts"][0]["finish_reason"] = None


def _call_page_partial(evidence: dict[str, Any]) -> None:
    evidence["provider_calls"]["items"].pop()


@mark.parametrize(
    ("edit", "unproven"),
    [
        (_truncated, "provider_calls"),
        (_no_provider_calls, "provider_calls"),
        (_attempts_omitted, "length_finishes"),
        (_attempt_unseen, "length_finishes"),
        (_no_debug_export, "length_finishes"),
        (_model_finish_unreported, "length_finishes"),
        (_call_page_partial, "length_finishes"),
    ],
)
@mark.parametrize("side", ["baseline", "current"])
def test_missing_or_incomplete_evidence_on_either_side_fails(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    edit: Callable[[dict[str, Any]], None],
    unproven: str,
    side: str,
) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    whole = observer.row()
    short = observer.row(edit=edit)
    cost = short["runtime_cost"]
    # Absent or partial evidence is incomplete, never a zero.
    assert cost["complete"] is False
    assert cost[unproven] is None

    baseline, current = ([short], [whole]) if side == "baseline" else ([whole], [short])
    report = _compare(tmp_path, baseline, current)

    assert _failures(report) == {
        "case-a": [f"{side} r1 runtime evidence is missing or incomplete"]
    }


@mark.parametrize(
    "usage",
    [
        {"num_tokens_total": 240, "input_completeness": "complete"},
        {"input_completeness": "complete", "output_completeness": "complete"},
    ],
    ids=["partial_usage", "no_total"],
)
def test_token_usage_without_a_whole_total_fails(
    monkeypatch: MonkeyPatch, tmp_path: Path, usage: dict[str, object]
) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    partial = observer.row(usage=usage)
    assert partial["runtime_cost"]["tokens_complete"] is False
    assert partial["runtime_cost"]["complete"] is False

    report = _compare(tmp_path, [observer.row()], [partial])

    assert _failures(report) == {
        "case-a": ["current r1 runtime evidence is missing or incomplete"]
    }


def test_a_case_executed_on_one_side_only_fails(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    shared = observer.row(case_id="case-a")

    report = _compare(tmp_path, [shared], [shared, observer.row(case_id="case-b")])

    assert _failures(report) == {"case-b": ["the case was observed on one side only"]}


def test_a_new_length_finish_fails(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    parent = [observer.row(finishes=("stop", "stop"))]
    candidate = [observer.row(finishes=("stop", "length"))]

    report = _compare(tmp_path, parent, candidate)

    assert candidate[0]["runtime_cost"]["length_finishes"] == 1
    assert _failures(report) == {
        "case-a": [
            "current r1 has 1 finish_reason=length attempt(s); the baseline's most is 0"
        ]
    }
    # A length finish the parent already had is not new.
    assert _compare(tmp_path, candidate, candidate)["runtime_cost_failed_cases"] == {}


@mark.parametrize(
    "failed_delivery",
    [{"declared_output": "pdf"}, {"run_status": "failed"}],
    ids=["wrong_output_kind", "failed_run"],
)
def test_a_failed_delivery_fails_where_the_parent_delivered(
    monkeypatch: MonkeyPatch, tmp_path: Path, failed_delivery: dict[str, Any]
) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    parent = [observer.row()]
    # Every literal is still there: only the delivery itself went wrong.
    candidate = [observer.row(**failed_delivery)]
    assert parent[0]["output_success"] is True
    assert candidate[0]["output_success"] is False
    assert candidate[0]["output_required_facts"] == dict.fromkeys(_FACTS, True)

    report = _compare(tmp_path, parent, candidate)

    assert _failures(report) == {
        "case-a": [
            "current r1 did not deliver successfully; every baseline observation did"
        ]
    }


def test_a_literal_dropped_from_the_case_still_fails_the_gate(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    parent = [observer.row()]
    # The candidate's case contract no longer asks for Njurunda, so its run
    # succeeds without it.
    candidate = [
        observer.row(
            required_facts=("Kvissleby",), text="Förskolan i Kvissleby avvecklas."
        )
    ]
    assert parent[0]["output_success"] is candidate[0]["output_success"] is True

    report = _compare(tmp_path, parent, candidate)

    assert _failures(report) == {
        "case-a": [
            "current r1 misses required literal(s) the baseline delivered: ['Njurunda']"
        ]
    }


def test_a_required_literal_survives_where_the_parent_delivered_partly(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    parent = [observer.row(declared_output="pdf")]
    candidate = [
        observer.row(declared_output="pdf", text="Förskolan i Kvissleby avvecklas.")
    ]
    assert parent[0]["output_success"] is False

    report = _compare(tmp_path, parent, candidate)

    assert candidate[0]["output_required_facts"] == {
        "Kvissleby": True,
        "Njurunda": False,
    }
    assert _failures(report) == {
        "case-a": [
            "current r1 misses required literal(s) the baseline delivered: ['Njurunda']"
        ]
    }
    # A literal the parent never delivered does not bind the candidate.
    assert _compare(tmp_path, candidate, candidate)["runtime_cost_failed_cases"] == {}


def test_a_receipt_without_runtime_cost_is_refused(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    older = {
        key: value for key, value in observer.row().items() if key != "runtime_cost"
    }

    with raises(SystemExit, match="case-a r1: no runtime_cost"):
        _compare(tmp_path, [older], [observer.row()])
    with raises(SystemExit, match="allowance and the new-case budget must be >= 0"):
        _compare(tmp_path, [observer.row()], [observer.row()], allowance=-1)


@mark.parametrize(
    ("field", "value", "reason"),
    [
        ("provider_calls", None, "needs counted provider_calls"),
        ("length_finishes", "0", "needs counted provider_calls"),
        ("total_tokens", None, "needs counted provider_calls"),
        ("tokens_complete", False, "needs counted provider_calls"),
        ("provider_call_evidence", "truncated", "needs counted provider_calls"),
        ("finish_reasons", None, "needs counted provider_calls"),
        ("complete", "yes", "boolean complete"),
    ],
)
def test_a_malformed_complete_row_is_refused(
    monkeypatch: MonkeyPatch, tmp_path: Path, field: str, value: object, reason: str
) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    row = observer.row()
    malformed = {**row, "runtime_cost": {**row["runtime_cost"], field: value}}

    with raises(SystemExit, match=f"case-a r1: .*{reason}"):
        _compare(tmp_path, [row], [malformed])


def _usage(total: int) -> dict[str, object]:
    return {
        "num_tokens_input": total - 20,
        "num_tokens_output": 20,
        "num_tokens_total": total,
        "input_completeness": "complete",
        "output_completeness": "complete",
    }


def test_a_newly_executable_case_is_held_to_the_absolute_budget(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    # The parent never reached a run: a known non-execution, not a gap.
    parent = [observer.row(runs=False)]
    assert parent[0]["output_executed"] is False
    assert parent[0]["runtime_cost"]["complete"] is False
    candidate = [observer.row()]
    budget = {"new_case_max_runtime_calls": 2, "new_case_max_runtime_tokens": 240}

    report = _compare(tmp_path, parent, candidate, **budget)

    assert report["runtime_cost_failed_cases"] == {}
    assert report["new_case_runtime_budget"] == {"max_calls": 2, "max_tokens": 240}
    case = report["cases"][0]["runtime_cost"]
    assert case["newly_executable"] is True
    assert case["failures"] == []

    over = _compare(
        tmp_path,
        parent,
        candidate,
        new_case_max_runtime_calls=1,
        new_case_max_runtime_tokens=239,
    )
    assert _failures(over) == {
        "case-a": [
            "current r1 made 2 runtime calls; a newly executable case's budget is 1",
            "current r1 used 240 tokens; a newly executable case's budget is 239",
        ]
    }

    short = [observer.row(text="Förskolan i Kvissleby avvecklas.")]
    assert short[0]["output_success"] is False
    assert _failures(_compare(tmp_path, parent, short, **budget)) == {
        "case-a": [
            "current r1 did not deliver successfully; a newly executable case must",
            "current r1 misses required literal(s): ['Njurunda']",
        ]
    }
    # A length finish is not free just because the parent had no run.
    truncated = [observer.row(finishes=("stop", "length"))]
    assert _failures(_compare(tmp_path, parent, truncated, **budget)) == {
        "case-a": [
            "current r1 has 1 finish_reason=length attempt(s); a newly executable "
            "case's budget is 0"
        ]
    }


def test_missing_telemetry_on_a_run_still_fails(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    ran_blind = observer.row(edit=_truncated)
    # The run happened; only its evidence is short.
    assert ran_blind["output_executed"] is True
    assert ran_blind["runtime_cost"]["complete"] is False

    assert _failures(_compare(tmp_path, [ran_blind], [observer.row()])) == {
        "case-a": ["baseline r1 runtime evidence is missing or incomplete"]
    }
    # A newly executable candidate owes whole evidence too.
    assert _failures(_compare(tmp_path, [observer.row(runs=False)], [ran_blind])) == {
        "case-a": ["current r1 runtime evidence is missing or incomplete"]
    }
    # A candidate that stops reaching a run the parent reached fails.
    assert _failures(
        _compare(tmp_path, [observer.row()], [observer.row(runs=False)])
    ) == {"case-a": ["current r1 did not run; the baseline did"]}
    # A row that does not say whether it ran is refused, never read as "did not".
    unknown = {
        key: value
        for key, value in observer.row(runs=False).items()
        if key != "output_executed"
    }
    with raises(SystemExit, match="case-a r1: output_executed must be a boolean"):
        _compare(tmp_path, [unknown], [observer.row()])


def test_a_parent_repetition_without_a_run_leaves_the_others_as_reference(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    parent = [observer.row(repetition=1), observer.row(repetition=2, runs=False)]
    candidate = [observer.row(finishes=("stop",) * 4)]

    assert _failures(_compare(tmp_path, parent, candidate)) == {
        "case-a": [
            "current r1 made 4 runtime calls; the baseline's most is 2, allowance 1",
            "current r1 used 480 tokens; the baseline's most is 240, tolerance 1.25",
        ]
    }


def test_token_inflation_beyond_the_tolerance_fails(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    parent = [observer.row(usage=_usage(1000))]

    within = _compare(
        tmp_path,
        parent,
        [observer.row(usage=_usage(1250))],
        runtime_token_tolerance=1.25,
    )
    assert within["runtime_cost_failed_cases"] == {}
    assert within["runtime_token_tolerance"] == 1.25

    # Same calls, a hundred times the tokens.
    inflated = _compare(
        tmp_path,
        parent,
        [observer.row(usage=_usage(100_000))],
        runtime_token_tolerance=1.25,
    )
    assert _failures(inflated) == {
        "case-a": [
            "current r1 used 100000 tokens; the baseline's most is 1000, tolerance 1.25"
        ]
    }
    with raises(SystemExit, match="tolerance must be >= 1"):
        _compare(tmp_path, parent, parent, runtime_token_tolerance=0.9)


def test_a_run_with_a_null_cost_fails(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    ran = observer.row()
    null_cost = {**ran, "runtime_cost": None}
    assert null_cost["output_executed"] is True

    assert _failures(_compare(tmp_path, [null_cost], [ran])) == {
        "case-a": ["baseline r1 runtime evidence is missing or incomplete"]
    }
    assert _failures(_compare(tmp_path, [ran], [null_cost])) == {
        "case-a": ["current r1 runtime evidence is missing or incomplete"]
    }
    # Even where no row carries a cost object, each run is gated.
    assert _failures(_compare(tmp_path, [null_cost], [null_cost])) == {
        "case-a": [
            "baseline r1 runtime evidence is missing or incomplete",
            "current r1 runtime evidence is missing or incomplete",
        ]
    }
    not_run = {**observer.row(runs=False), "runtime_cost": None}
    assert _failures(_compare(tmp_path, [not_run], [null_cost])) == {
        "case-a": ["current r1 runtime evidence is missing or incomplete"]
    }


def test_a_scored_output_without_its_facts_is_refused(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    ran = observer.row()
    assert ran["output_success"] is True
    unscored_facts = {**ran, "output_required_facts": None}

    with raises(SystemExit, match="case-a r1: a scored output .* needs output_req"):
        _compare(tmp_path, [observer.row(runs=False)], [unscored_facts])


def test_an_acquisition_failure_leaves_the_case_unknown(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    observer = _Observer(monkeypatch, tmp_path)
    # The instrument failed before any run: no run, no cost object. That
    # proves nothing about whether the product could run the case.
    failed = {
        **observer.row(runs=False),
        "observation_status": "acquisition_failure",
        "failure_class": "provider_request",
        "runtime_cost": None,
    }
    assert failed["output_executed"] is False

    report = _compare(tmp_path, [failed], [observer.row()])

    assert _failures(report) == {
        "case-a": ["baseline r1 is an acquisition failure; re-measure"]
    }
    assert "newly_executable" not in report["cases"][0]["runtime_cost"]
    assert _failures(_compare(tmp_path, [failed], [failed])) == {
        "case-a": [
            "baseline r1 is an acquisition failure; re-measure",
            "current r1 is an acquisition failure; re-measure",
        ]
    }
