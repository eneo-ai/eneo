"""MCP tool cases of the Builder harness: the seed manifest, scripted tool
answers, the call log and the M1-M8 checks, including the oracle self-test
(T0): deliberately wrong synthetic bundles must fail, a right one must pass,
and missing evidence is never a pass."""

from __future__ import annotations

import ast
import importlib
import io
import json
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from urllib.error import HTTPError
from uuid import UUID

from pydantic import ValidationError
from pytest import MonkeyPatch, fixture, mark, raises

from eneo.flows.ai_builder.ai_builder_tool_catalog import tool_ref
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from tests.unittests.flows.ai_builder.test_ai_builder_api_battle_harness import (
    _battle_harness,  # pyright: ignore[reportPrivateUsage]
    _complete_live_case_bundle,  # pyright: ignore[reportPrivateUsage]
    _EditApi,  # pyright: ignore[reportPrivateUsage]
    _run_edit,  # pyright: ignore[reportPrivateUsage]
)

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
mcp = importlib.import_module("ai_builder_mcp_eval")

_SPACE = "00000000-0000-0000-0000-00000000005a"
_SERVER_ID = UUID("00000000-0000-0000-0000-0000000000a1")
_TOOL_ID = UUID("00000000-0000-0000-0000-0000000000b1")
_REF = tool_ref(_SERVER_ID, _TOOL_ID)
_EVENTS_ID = UUID("00000000-0000-0000-0000-0000000000b2")
_EVENTS_REF = tool_ref(_SERVER_ID, _EVENTS_ID)
_TOOL = {"server": "Driftdata", "name": "query_daily_metrics"}
_PROBE_AT = "2026-10-18T10:05:00+00:00"
_ARGS = {"from_date": "2026-09-01", "to_date": "2026-09-30", "unit": "day", "days": 3}


def _manifest(call_log: str = "/tmp/calls-driftdata-only.jsonl") -> dict[str, Any]:
    return {
        "version": 1,
        "block": "driftdata-only",
        "space_id": _SPACE,
        "seeded_at": "2026-10-18T10:00:00+00:00",
        "servers": [
            {"name": "Driftdata", "server_id": str(_SERVER_ID), "url": "http://s/mcp"}
        ],
        "tools": [
            {
                **_TOOL,
                "tool_id": str(_TOOL_ID),
                "ref": _REF,
                "schema_sha256": "0" * 64,
                "enabled_in_space": True,
            }
        ],
        "call_log": call_log,
        "catalog_sha256": "1" * 64,
    }


@fixture(scope="module")
def harness() -> ModuleType:
    return _battle_harness()


# --- the oracle self-test (T0) ------------------------------------------------

_USE = {
    "tool": _TOOL,
    "arguments": {
        "from_date": {"run_input": {"field": "from_date", "type": "date"}},
        "to_date": {"run_input": {"field": "to_date"}},
        "unit": {"fixed": "day"},
        "days": {"earlier": {"step": {"order": 1}, "field": "anomaly_days"}},
    },
}


def _tool_step(ref: str, arguments: dict[str, Any]) -> dict[str, Any]:
    tool = {"mcp_server_id": str(_SERVER_ID), "tool_id": str(_TOOL_ID)}
    return {
        "plan_step_ref": ref,
        "name": "Read",
        "input_source": "previous_step",
        "input_config": {"tool": {**tool, "arguments": arguments}},
    }


def _plan(
    *,
    tool_arguments: dict[str, Any] | None,
    plain_steps: int = 1,
    from_type: str = "date",
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = [
        {"plan_step_ref": f"step_{n}", "name": "Find", "input_source": "flow_input"}
        for n in range(1, plain_steps + 1)
    ]
    if tool_arguments is not None:
        steps.append(_tool_step(f"step_{plain_steps + 1}", tool_arguments))
    form = [
        {"name": "from_date", "type": from_type, "label": "Från"},
        {"name": "to_date", "type": "date", "label": "Till"},
    ]
    return {"proposal": {"spec": {"steps": steps, "form_fields": form}}}


_RIGHT_ARGUMENTS = {
    "from_date": "{{ flow_input.from_date }}",
    "to_date": "{{ flow_input.to_date }}",
    "unit": "day",
    "days": "{{ step_1.output.structured.anomaly_days }}",
}


def _question(family: str, **facts: Any) -> dict[str, Any]:
    return {
        "event": "question",
        "data": {
            "question_id": "q",
            "question": "?",
            "options": [{"id": _REF, "label": "t", "value": _REF}],
            "selection_mode": "single",
            "allow_custom": False,
            "recommended_option_id": _REF if family == "choice" else None,
            "tool_question": {"family": family, **facts},
        },
    }


def _call(at: str, **arguments: Any) -> dict[str, Any]:
    return {
        "ts": at,
        "block": "driftdata-only",
        "server": "Driftdata",
        "tool": "query_daily_metrics",
        "arguments": arguments,
    }


_CHOICE_TURN = [
    {"events": [_question("choice", use_ref="metrics")], "plan": None},
    {"events": [], "plan": _plan(tool_arguments=_RIGHT_ARGUMENTS)},
]
_EXPLICIT = {
    "outcome": {"kind": "applied_plan"},
    "turns": [["choice"]],
    "uses": [_USE],
    "calls": [{"tool": _TOOL, "arguments": _ARGS}],
}
_DECLINED = {"outcome": {"kind": "applied_plan"}, "turns": [["relevance"]], "uses": []}
_DECLINED_TURNS = [
    {"events": [_question("relevance")], "plan": None},
    {"events": [], "plan": _plan(tool_arguments=None)},
    {
        "events": [{"event": "plan", "data": {"plan_id": "plan-2"}}],
        "plan": _plan(tool_arguments=_RIGHT_ARGUMENTS),
        "scripted_turn": 1,
    },
]


def _states(
    harness: ModuleType,
    expected_mcp: dict[str, Any],
    interactions: list[dict[str, Any]],
    *,
    calls: list[dict[str, Any]] | None,
    evidence: bool = True,
) -> dict[str, str]:
    bundle = _scored(
        harness, expected_mcp, interactions, calls=calls, evidence=evidence
    )
    return harness._verdict_states(bundle, observation_status="completed")


def _scored(
    harness: ModuleType,
    expected_mcp: dict[str, Any],
    interactions: list[dict[str, Any]],
    *,
    calls: list[dict[str, Any]] | None,
    evidence: bool = True,
    follow_ups: tuple[str, ...] = (),
    delivered: tuple[str, Any] | None = None,
    edit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`delivered` = (the run's text, its OutputExpectation): the case runs;
    `edit` is the bundle's edit evidence of a saved flow."""
    plan = interactions[-1]["plan"]
    case: dict[str, Any] = {"expected": {"expected_mcp": expected_mcp}, "file_ids": []}
    if follow_ups:
        case["script"] = {"turns": list(follow_ups)}
    if delivered is not None:
        case["execution"] = {"inputs": {}, "checkpoints": [], "expect": {}}
    bundle: dict[str, Any] = {
        "case": case,
        "interactions": interactions,
        "plan": plan,
        "applied_flow_evidence": {"flow": {"steps": []}},
        "runtime_evidence": None
        if delivered is None
        else {
            "run_contract": {"final_output": {"output_type": "text"}},
            "execution": {"outcome": "completed", "failures": []},
            "run": {
                "id": "run-1",
                "status": "completed",
                "result": {"kind": "inline_text", "text": delivered[0]},
            },
        },
    }
    if edit is not None:
        bundle["edit_evidence"] = edit
    if evidence:
        bundle["mcp_evidence"] = {
            "manifest": _manifest(),
            "calls": calls,
            "run_probe_started_at": _PROBE_AT,
        }
    bundle["quality_report"] = harness._quality_report_of(
        bundle,
        summary=harness._summarize_plan(plan),
        event_summary=harness._interaction_event_summary(interactions),
        journey={},
        expected=bundle["case"]["expected"],
        output_expectation=None if delivered is None else delivered[1],
    )
    return bundle


_PROBE_CALL = _call("2026-10-18T10:06:00+00:00", **_ARGS)


@mark.parametrize(
    ("expected_mcp", "interactions", "calls", "plan", "output"),
    [
        # Kills: the checks pass without the expected tool, or demand a relevance question.
        (_EXPLICIT, _CHOICE_TURN, [_PROBE_CALL], "pass", "pass"),
        # Kills: an earlier-step binding compared by its kind only, not its field.
        (
            _EXPLICIT,
            [
                _CHOICE_TURN[0],
                {
                    "events": [],
                    "plan": _plan(
                        tool_arguments={
                            **_RIGHT_ARGUMENTS,
                            "days": "{{ step_1.output.structured.other_days }}",
                        }
                    ),
                },
            ],
            [_PROBE_CALL],
            "fail",
            "pass",
        ),
        # Kills: a fixed binding compared by its kind only, not its value.
        (
            _EXPLICIT,
            [
                _CHOICE_TURN[0],
                {
                    "events": [],
                    "plan": _plan(tool_arguments={**_RIGHT_ARGUMENTS, "unit": "week"}),
                },
            ],
            [_PROBE_CALL],
            "fail",
            "pass",
        ),
        # Kills: an earlier binding read by its field name, not its producer.
        (
            _EXPLICIT,
            [
                _CHOICE_TURN[0],
                {
                    "events": [],
                    "plan": _plan(
                        tool_arguments={
                            **_RIGHT_ARGUMENTS,
                            "days": "{{ step_2.output.structured.anomaly_days }}",
                        },
                        plain_steps=2,
                    ),
                },
            ],
            [_PROBE_CALL],
            "fail",
            "pass",
        ),
        # Kills: a run-form binding read by its field type, not its field.
        (
            _EXPLICIT,
            [
                _CHOICE_TURN[0],
                {
                    "events": [],
                    "plan": _plan(
                        tool_arguments={
                            **_RIGHT_ARGUMENTS,
                            "from_date": "{{ flow_input.to_date }}",
                            "to_date": "{{ flow_input.from_date }}",
                        }
                    ),
                },
            ],
            [_PROBE_CALL],
            "fail",
            "pass",
        ),
        # Kills: a declared run-form field type not compared.
        (
            _EXPLICIT,
            [
                _CHOICE_TURN[0],
                {
                    "events": [],
                    "plan": _plan(tool_arguments=_RIGHT_ARGUMENTS, from_type="text"),
                },
            ],
            [_PROBE_CALL],
            "fail",
            "pass",
        ),
        # Kills: probe calls compared as a set, or only the expected ones looked for.
        (_EXPLICIT, _CHOICE_TURN, [_PROBE_CALL, _PROBE_CALL], "pass", "fail"),
        # Kills: calls before the run probe counted as probe calls.
        (
            _EXPLICIT,
            _CHOICE_TURN,
            [_call("2026-10-18T10:01:00+00:00", **_ARGS), _PROBE_CALL],
            "pass",
            "fail",
        ),
        # Kills: only the first turn's plan read for a declined case.
        (_DECLINED, _DECLINED_TURNS, [], "fail", "pass"),
        # Kills: unreadable call evidence read as zero calls.
        (_EXPLICIT, _CHOICE_TURN, None, "pass", "unmeasured"),
    ],
    ids=[
        "explicit_choice_passes",
        "wrong_earlier_field",
        "wrong_fixed_value",
        "earlier_field_from_other_producer",
        "run_form_fields_swapped",
        "run_form_field_of_another_type",
        "extra_call",
        "authoring_call",
        "tool_step_after_no",
        "unreadable_call_log",
    ],
)
def test_the_mcp_oracle_fails_wrong_bundles_and_passes_a_right_one(
    harness: ModuleType,
    expected_mcp: dict[str, Any],
    interactions: list[dict[str, Any]],
    calls: list[dict[str, Any]] | None,
    plan: str,
    output: str,
) -> None:
    states = _states(harness, expected_mcp, interactions, calls=calls)

    assert (states["plan"], states["output"]) == (plan, output)


def test_an_mcp_case_without_its_evidence_is_never_a_pass(harness: ModuleType) -> None:
    # Kills: missing evidence read as passing bindings or calls.
    states = _states(harness, _EXPLICIT, _CHOICE_TURN, calls=None, evidence=False)

    assert states["case"] == "unmeasured"


def test_a_dimension_missing_a_required_mcp_check_is_never_a_pass(
    harness: ModuleType,
) -> None:
    # Kills: the plan dimension graded without the case's applicable MCP checks.
    report = {
        "checks": [{"name": "question_event_contract", "passed": True}],
        "required_check_names": {"plan": ["mcp_m3_bindings"], "output": []},
    }
    states = harness._verdict_states(
        {"quality_report": report, "case": {"expected": {}}},
        observation_status="completed",
    )

    assert states["plan"] == "unmeasured"


def test_a_turn_beyond_the_declared_ones_expects_no_tool_question(
    harness: ModuleType,
) -> None:
    # Kills: turns compared only up to the declared count.
    asked_again = [
        *_CHOICE_TURN,
        {"events": [_question("relevance")], "plan": None, "scripted_turn": 1},
        {
            "events": [{"event": "plan", "data": {"plan_id": "plan-2"}}],
            "plan": _CHOICE_TURN[1]["plan"],
        },
    ]

    assert _states(harness, _EXPLICIT, asked_again, calls=[_PROBE_CALL])["plan"] == (
        "fail"
    )


def _refused(kind: str, code: str | None = None) -> list[dict[str, Any]]:
    refusal: dict[str, Any] = (
        {"kind": kind, "request_text": "kalendern Bokning"}
        if kind == "request_unresolved"
        else {"tool_name": "t", "server_name": "s", "kind": kind}
        | ({"refusal": code} if code else {})
    )
    conversation = [{"role": "assistant", "tool_refusal": refusal}]
    return [
        {"events": [], "plan": None, "latest_session": {"conversation": conversation}}
    ]


_GUIDANCE = {
    "outcome": {
        "kind": "guidance",
        "refusal_kind": "input_schema_too_large",
        "refusal": None,
    },
    "turns": [],
    "uses": [],
}


def test_a_guidance_outcome_matches_the_typed_refusal_of_the_last_answer(
    harness: ModuleType,
) -> None:
    # Kills: a guidance outcome passed on "no plan" alone.
    right = _states(harness, _GUIDANCE, _refused("input_schema_too_large"), calls=[])
    wrong = _states(harness, _GUIDANCE, _refused("input_schema_invalid"), calls=[])

    assert (right["plan"], wrong["plan"]) == ("pass", "fail")


def test_a_refused_tool_guidance_matches_the_refusal_code(
    harness: ModuleType,
) -> None:
    # Kills: the code of a refused tool left out of the comparison, so any
    # refused tool passes whatever refused it.
    refused = {
        "outcome": {
            "kind": "guidance",
            "refusal_kind": "refused",
            "refusal": "tool_switched_off_in_space",
        },
        "turns": [],
        "uses": [],
    }

    right = _states(
        harness, refused, _refused("refused", "tool_switched_off_in_space"), calls=[]
    )
    wrong = _states(
        harness, refused, _refused("refused", "space_is_personal"), calls=[]
    )

    assert (right["plan"], wrong["plan"]) == ("pass", "fail")


@mark.parametrize("kind", ["tool_not_usable", "tool_request_unresolved"])
def test_a_tool_answer_cannot_be_expected_as_a_plain_answer(kind: str) -> None:
    # Kills: an answer expectation for a tool refusal that validates and then
    # can never pass, because the refusal contradicts an answer outcome.
    with raises(ValueError, match="guidance outcome"):
        mcp.AnswerOutcome.model_validate({"kind": "answer", "non_plan_kind": kind})


def test_a_guidance_outcome_reads_the_unresolved_request_variant(
    harness: ModuleType,
) -> None:
    # Kills: the harness reading the guidance with the refusal type only, so a
    # correct unresolved answer scores as no guidance (or an expectation of
    # it cannot be written).
    unresolved = {
        "outcome": {
            "kind": "guidance",
            "refusal_kind": "request_unresolved",
            "refusal": None,
        },
        "turns": [],
        "uses": [],
    }

    right = _states(harness, unresolved, _refused("request_unresolved"), calls=[])
    wrong = _states(harness, unresolved, _refused("input_schema_invalid"), calls=[])

    assert (right["plan"], wrong["plan"]) == ("pass", "fail")


def test_a_bundle_without_a_plan_is_scored_again_by_reanalysis(
    harness: ModuleType, tmp_path: Path
) -> None:
    expected = {"expected_mcp": _GUIDANCE}
    case = harness.BattleCase(
        case_id="mcp-guidance", prompt="Hämta.", expected=expected
    )
    bundle = _complete_live_case_bundle(harness, case)
    # The fixture's one turn, with the refusal its answer carried.
    refused = _refused("input_schema_too_large")[0]["latest_session"]
    interactions = [{**bundle["interactions"][0], "latest_session": refused}]
    bundle.update(
        interactions=interactions,
        mcp_evidence={
            "manifest": _manifest(),
            "calls": [],
            "run_probe_started_at": None,
        },
    )
    bundle["quality_report"] = harness._quality_report_of(
        bundle,
        summary=harness._summarize_plan(None),
        event_summary=harness._interaction_event_summary(interactions),
        journey={},
        expected=expected,
        output_expectation=None,
    )
    path = tmp_path / "guidance.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")

    # Kills: a no-plan report without the metrics reanalysis requires.
    assert (
        harness._reanalyze_bundles(bundle_paths=[path], output_dir=tmp_path / "re") == 0
    )
    rescored = json.loads(next((tmp_path / "re").iterdir()).read_text())
    checks = {check["name"]: check for check in rescored["quality_report"]["checks"]}
    assert checks["mcp_m4_outcome"]["passed"] is True


# --- case contract -----------------------------------------------------------


def _cases_file(harness: ModuleType, tmp_path: Path, **case: Any) -> Path:
    path = tmp_path / "cases.json"
    body = {"id": "mcp-1", "prompt": "Hämta mätvärden.", **case}
    version = harness.SUPPORTED_CASES_FILE_VERSION
    path.write_text(json.dumps({"version": version, "cases": [body]}), encoding="utf-8")
    return path


def test_tool_answers_and_turns_enter_only_the_contract_of_a_case_that_declares_them(
    harness: ModuleType, tmp_path: Path
) -> None:
    plain = harness._read_cases_file(_cases_file(harness, tmp_path))[0]
    scripted = harness._read_cases_file(
        _cases_file(
            harness,
            tmp_path,
            tool_answers=[{"family": "relevance", "option": "use"}],
            script={"turns": ["Lägg till enheten."]},
        )
    )[0]

    # Kills: the keys written for every case, which would move every sealed hash.
    assert {"tool_answers", "script"}.isdisjoint(harness._case_contract_payload(plain))
    # Kills: a key the record carries that the observed projection drops.
    record = harness._case_record(scripted, file_ids=())
    assert harness._observed_case_contract_payload(record) == (
        harness._case_contract_payload(scripted)
    )
    assert record["tool_answers"] == [{"family": "relevance", "option": "use"}]
    assert record["script"] == {"turns": ["Lägg till enheten."]}


@mark.parametrize(
    "expected_mcp",
    [
        {**_EXPLICIT, "extra": 1},
        {
            **_EXPLICIT,
            "uses": [{**_USE, "arguments": {"unit": {"fixed": 1, "run_input": {}}}}],
        },
        {**_EXPLICIT, "turns": [["relevance", "maybe"]]},
        {
            "outcome": {"kind": "guidance", "refusal_kind": "refused", "refusal": None},
            "turns": [],
            "uses": [],
        },
    ],
    ids=["unknown_key", "two_sources", "unknown_family", "refused_without_reason"],
)
def test_an_mcp_expectation_has_one_closed_shape(
    harness: ModuleType, tmp_path: Path, expected_mcp: dict[str, Any]
) -> None:
    # Kills: an open or partial validator of expected_mcp.
    with raises(ValueError, match="expected_mcp"):
        harness._read_cases_file(
            _cases_file(harness, tmp_path, expected={"expected_mcp": expected_mcp})
        )


@mark.parametrize("check", ["tool_output_reaches_last_step", "keeps_saved_flow"])
def test_an_edit_check_needs_an_edit_case(
    harness: ModuleType, tmp_path: Path, check: str
) -> None:
    # Kills: M7 or M8 accepted on a case with no edit block, where the check
    # could never be measured (one mutant per check).
    with raises(ValueError, match="edit checks need an edit case"):
        harness._read_cases_file(
            _cases_file(
                harness,
                tmp_path,
                apply_plan=True,
                expected={
                    "expected_mcp": {
                        "outcome": {"kind": "applied_plan"},
                        "turns": [],
                        "uses": [],
                        check: True,
                    }
                },
            )
        )


@mark.parametrize(
    ("change", "space"),
    [
        ({"ref": "tool_" + "0" * 12}, _SPACE),
        ({}, "00000000-0000-0000-0000-0000000000ff"),
    ],
    ids=["ref_not_the_tools", "other_space"],
)
def test_a_seed_manifest_must_name_its_tools_by_their_refs_in_the_run_space(
    tmp_path: Path, change: dict[str, Any], space: str
) -> None:
    manifest = _manifest()
    manifest["tools"][0].update(change)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    # Kills: a manifest whose refs or space are taken on trust.
    with raises((ValueError, ValidationError)):
        mcp.load_seed_manifest(path, space_id=space)


# --- scripted tool answers ----------------------------------------------------


def _shown(family: str, options: list[dict[str, Any]], **facts: Any) -> dict[str, Any]:
    return {
        "question_id": "tool_argument:metrics:" + _REF + ":unit",
        "question": "?",
        "options": options,
        "selection_mode": "single",
        "allow_custom": "fixed_value_option_id" in facts,
        "instance_token": "11111111-1111-1111-1111-111111111111",
        "tool_question": {"family": family, "use_ref": "metrics", **facts},
    }


_TWO_PRODUCERS = [
    {"id": "earlier_step:1:anomaly_days", "label": "Steg 1", "value": "1:anomaly_days"},
    {"id": "earlier_step:2:anomaly_days", "label": "Steg 2", "value": "2:anomaly_days"},
]
_ARGUMENT_OPTIONS = [
    {"id": "fixed", "label": "Fast värde", "value": "fixed"},
    {"id": "run_input:unit", "label": "Fråga", "value": "unit"},
    {"id": "earlier_step:1:anomaly_days", "label": "Steg 1", "value": "1:anomaly_days"},
]


@mark.parametrize(
    ("question", "rule", "selected", "custom"),
    [
        (
            _shown("relevance", [{"id": "use", "label": "Ja", "value": "use"}]),
            {"family": "relevance", "option": "use"},
            "use",
            None,
        ),
        (
            _shown(
                "choice",
                [
                    {"id": _REF, "label": "t", "value": _REF},
                    {"id": "no_tool", "label": "Inget", "value": "no_tool"},
                ],
            ),
            {"family": "choice", "tool": _TOOL},
            _REF,
            None,
        ),
        (
            _shown(
                "argument",
                _ARGUMENT_OPTIONS,
                argument_name="unit",
                fixed_value_option_id="fixed",
            ),
            {"family": "argument", "argument": "unit", "source": "fixed", "value": 7},
            "fixed",
            "7",
        ),
        (
            _shown(
                "argument",
                [
                    {"id": "value:0", "label": "day", "value": "day"},
                    {"id": "value:1", "label": "week", "value": "week"},
                ],
                argument_name="unit",
            ),
            {
                "family": "argument",
                "argument": "unit",
                "source": "fixed",
                "value": "week",
            },
            "value:1",
            None,
        ),
        (
            _shown(
                "argument",
                [
                    {
                        "id": "run_input:from_date",
                        "label": "Från",
                        "value": "from_date",
                    },
                    {"id": "run_input:to_date", "label": "Till", "value": "to_date"},
                ],
                argument_name="to_date",
            ),
            {
                "family": "argument",
                "argument": "to_date",
                "source": "run_input",
                "field": "to_date",
            },
            "run_input:to_date",
            None,
        ),
        (
            _shown(
                "argument",
                _ARGUMENT_OPTIONS,
                argument_name="unit",
                fixed_value_option_id="fixed",
            ),
            {
                "family": "argument",
                "argument": "unit",
                "source": "earlier",
                "step": {"tool": _TOOL},
                "field": "anomaly_days",
            },
            "earlier_step:1:anomaly_days",
            None,
        ),
        (
            _shown("argument", _TWO_PRODUCERS, argument_name="unit"),
            {
                "family": "argument",
                "argument": "unit",
                "source": "earlier",
                "step": {"tool": _TOOL},
                "field": "anomaly_days",
            },
            None,
            None,
        ),
        (
            _shown("argument", _TWO_PRODUCERS, argument_name="unit"),
            {
                "family": "argument",
                "argument": "unit",
                "source": "earlier",
                "step": {"order": 2},
                "field": "anomaly_days",
            },
            "earlier_step:2:anomaly_days",
            None,
        ),
        (
            _shown(
                "argument",
                _ARGUMENT_OPTIONS,
                argument_name="days",
                fixed_value_option_id="fixed",
            ),
            {
                "family": "argument",
                "argument": "unit",
                "source": "run_input",
                "field": "unit",
            },
            None,
            None,
        ),
        (
            _shown(
                "argument",
                [
                    {"id": "value:0", "label": "day", "value": "day"},
                    {"id": "run_input:day", "label": "Fråga", "value": "day"},
                ],
                argument_name="unit",
            ),
            {
                "family": "argument",
                "argument": "unit",
                "source": "fixed",
                "value": "day",
            },
            None,
            None,
        ),
        (
            _shown(
                "argument",
                [
                    {"id": "value:0", "label": "day", "value": "day"},
                    {"id": "run_input:day", "label": "Fråga", "value": "day"},
                ],
                argument_name="unit",
            ),
            {
                "family": "argument",
                "argument": "unit",
                "source": "run_input",
                "field": "day",
            },
            "run_input:day",
            None,
        ),
    ],
    ids=[
        "relevance",
        "choice_by_manifest_ref",
        "fixed_typed",
        "fixed_value_option",
        "run_input",
        "earlier_field",
        "earlier_field_of_two_producers",
        "earlier_field_by_producer_order",
        "other_argument",
        "value_offered_twice",
        "run_input_not_a_value_option",
    ],
)
def test_a_tool_question_is_answered_by_the_first_rule_its_typed_facts_match(
    question: dict[str, Any],
    rule: dict[str, Any],
    selected: str | None,
    custom: str | None,
) -> None:
    # Kills: a rule matched on family alone, on the wrong option kind, or a
    # fixed value sent as a selection instead of the typed text.
    rules = mcp.TOOL_ANSWER_RULES.validate_python([rule])
    manifest = mcp.SeedManifest.model_validate(_manifest())

    answer = mcp.scripted_tool_answer(question, rules, manifest)

    if selected is None:
        assert answer is None
        return
    assert answer is not None
    assert answer["answer_source"] == mcp.TOOL_ANSWER_SOURCE
    sent = answer["question_answer"]
    assert sent["selected_option_ids"] == [selected]
    assert sent["instance_token"] == "11111111-1111-1111-1111-111111111111"
    assert sent.get("custom_value") == custom


def test_the_run_answers_tool_questions_and_sends_follow_up_turns(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    sent: list[dict[str, Any]] = []
    replies = [
        {"plan_id": None, "events": [_question("relevance")]},
        {
            "plan_id": "plan-1",
            "events": [{"event": "plan", "data": {"plan_id": "plan-1"}}],
        },
        {"plan_id": "plan-1", "events": []},
    ]
    monkeypatch.setattr(harness, "_create_session", lambda **_: {"session_id": "s-1"})
    monkeypatch.setattr(harness, "_request_json", lambda **_: {})

    def send_and_fetch(**kwargs: Any) -> dict[str, Any]:
        sent.append(kwargs)
        return dict(replies[len(sent) - 1])

    def stop(interactions: list[dict[str, Any]], **_: Any) -> None:
        raise RuntimeError(json.dumps([i.get("scripted_turn") for i in interactions]))

    def apply(**kwargs: Any) -> None:
        raise AssertionError(f"applied {kwargs['plan_id']}")

    monkeypatch.setattr(harness, "_send_and_fetch", send_and_fetch)
    monkeypatch.setattr(harness, "_apply_execute_and_cleanup_flow", apply)
    monkeypatch.setattr(harness, "_journey_summary", stop)
    replies[0]["events"][0]["data"]["options"] = [
        {"id": "use", "label": "Ja", "value": "use"}
    ]
    case = harness._read_cases_file(
        _cases_file(
            harness,
            tmp_path,
            tool_answers=[{"family": "relevance", "option": "use"}],
            script={"turns": ["Lägg till enheten."]},
            apply_plan=True,
        )
    )[0]

    with raises(RuntimeError) as stopped:
        harness._run_case_session(
            case=case,
            config=object(),
            args=SimpleNamespace(
                space_id=_SPACE,
                model_id=None,
                ui_language="sv",
                file_ids=None,
                auto_confirm_requirements=True,
                mcp_seed_manifest=str(manifest_path),
                timeout_seconds=1,
            ),
            existing_session_id=None,
            artifact_output_dir=tmp_path,
            cases_path=None,
            provisioned_fixtures=None,
            seeded_flow=None,
        )

    # Kills: the typed-rule fallback skipped before the unanswered break,
    # follow-up turns not sent or not marked as turns of their own, and a
    # follow-up turn that stalled applying the previous turn's plan.
    assert sent[1]["question_answer"]["selected_option_ids"] == ["use"]
    assert sent[2]["message"] == "Lägg till enheten."
    assert json.loads(str(stopped.value)) == [None, None, 1]


def test_the_call_log_keeps_this_blocks_calls_in_the_observation_window(
    tmp_path: Path,
) -> None:
    log = tmp_path / "calls.jsonl"
    inside = _call("2026-10-18T10:06:00.000001+00:00", days=1)
    other_block = {**inside, "block": "kalender"}
    late = _call("2026-10-18T11:00:00+00:00", days=2)
    log.write_text(
        "\n".join(json.dumps(line) for line in (inside, other_block, late)) + "\n",
        encoding="utf-8",
    )
    manifest = mcp.SeedManifest.model_validate(_manifest(str(log)))
    window = {
        "started": mcp.parse_instant("2026-10-18T10:00:00+00:00"),
        "ended": mcp.parse_instant("2026-10-18T10:30:00+00:00"),
    }

    # Kills: another block's or another observation's calls attributed here.
    assert mcp.observation_calls(manifest, **window) == [inside]
    # Kills: a log line that does not parse dropped instead of voiding the read.
    log.write_text(json.dumps(inside) + "\nnot json\n", encoding="utf-8")
    assert mcp.observation_calls(manifest, **window) is None


def test_the_mcp_corpus_is_placeable_trained_and_measurable(
    harness: ModuleType,
) -> None:
    cases = harness._read_cases_file(_SCRIPTS / "ai_builder_mcp_eval_cases.json")

    def tags(case: Any, prefix: str) -> list[str]:
        return [cohort for cohort in case.cohorts if cohort.startswith(prefix)]

    # Kills: an executed case whose output the binding grader can never
    # measure (two facts or more without a location).
    for case in cases:
        if case.execution is not None:
            gold = harness._scoring_gold(case.execution.expect)
            assert sum(fact.location is None for fact in gold.facts) <= 1, case.case_id
    # Kills: a case a screen cannot place in one seed block or one split, or a
    # family left without a train case.
    assert all(len(tags(c, "mcp_block:")) == 1 for c in cases)
    assert all(
        tags(c, "mcp_train") + tags(c, "mcp_test") in (["mcp_train"], ["mcp_test"])
        for c in cases
    )
    assert {f"mcp_family:{n}" for n in range(1, 10)} == {
        tag for c in cases if "mcp_train" in c.cohorts for tag in tags(c, "mcp_family:")
    }


def test_an_earlier_binding_names_its_producer_by_the_tool_it_reads(
    harness: ModuleType,
) -> None:
    from_tool = {"step": {"tool": _TOOL}, "field": "anomaly_days"}
    expected = {
        "outcome": {"kind": "applied_plan"},
        "turns": [],
        # Listed against the plan's order: uses are matched order aside.
        "uses": [
            {"tool": _TOOL, "arguments": {"days": {"earlier": from_tool}}},
            {"tool": _TOOL, "arguments": {"unit": {"fixed": "day"}}},
        ],
    }

    def chain(producer: str) -> list[dict[str, Any]]:
        steps = [
            {"plan_step_ref": "step_1", "name": "Find", "input_source": "flow_input"},
            _tool_step("step_2", {"unit": "day"}),
            _tool_step(
                "step_3",
                {"days": f"{{{{ {producer}.output.structured.anomaly_days }}}}"},
            ),
        ]
        return [{"events": [], "plan": {"proposal": {"spec": {"steps": steps}}}}]

    # Kills: a producer named by its tool matched on the field alone, and uses
    # matched in plan order.
    assert _states(harness, expected, chain("step_2"), calls=[])["plan"] == "pass"
    assert _states(harness, expected, chain("step_1"), calls=[])["plan"] == "fail"


_ASKED_UNIT = [
    {
        "events": [_question("argument", use_ref="metrics", argument_name="unit")],
        "plan": None,
    },
    {"events": [], "plan": _plan(tool_arguments=_RIGHT_ARGUMENTS)},
]


@mark.parametrize(
    ("turns", "interactions", "model_bindings"),
    [
        ([], [_CHOICE_TURN[1]], True),
        ([["argument"]], _ASKED_UNIT, False),
        ([["choice"]], _CHOICE_TURN, None),
    ],
    ids=["own_draft", "argument_left_to_the_person", "choice_answered"],
)
def test_the_models_own_bindings_are_reported_apart_from_compliance(
    harness: ModuleType,
    turns: list[list[str]],
    interactions: list[dict[str, Any]],
    model_bindings: bool | None,
) -> None:
    report = _scored(
        harness, {**_EXPLICIT, "turns": turns}, interactions, calls=[_PROBE_CALL]
    )["quality_report"]
    measured = {check["name"]: check for check in report["mcp_checks"]}

    # Kills: the final, answered plan counted as the model's own decision.
    assert measured["mcp_m2_model_bindings"]["passed"] is model_bindings
    assert measured["mcp_m3_bindings"]["passed"] is True
    # Kills: a reported-only check that gates, or a check without its evidence.
    assert not {"mcp_m2_model_pick", "mcp_m2_model_bindings"} & {
        check["name"] for check in report["checks"]
    }
    assert all(
        {"actual", "expected", "gating"} <= set(check) for check in measured.values()
    )


def test_a_bundle_ended_by_a_builder_error_is_scored_again_by_reanalysis(
    harness: ModuleType, tmp_path: Path
) -> None:
    case = harness.BattleCase(case_id="ends-in-error", prompt="Bygg ett flöde.")
    bundle = _complete_live_case_bundle(harness, case)
    # A second turn the Builder ended with its own error: it carries no model
    # usage, so the bundle's model provenance cannot be complete.
    error = {"event": "error", "data": {"code": "self_correction_invalid_plan"}}
    interactions = [*bundle["interactions"], {"events": [error]}]
    bundle["interactions"] = interactions
    bundle["quality_report"] = harness._quality_report_of(
        bundle,
        summary=harness._summarize_plan(None),
        event_summary=harness._interaction_event_summary(interactions),
        journey={},
        expected={},
        output_expectation=None,
    )
    path = tmp_path / "error.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")

    # Kills: reanalysis refusing every bundle whose live evidence is invalid,
    # including one the live run judged as error-terminated.
    assert (
        harness._reanalyze_bundles(bundle_paths=[path], output_dir=tmp_path / "re") == 0
    )
    rescored = json.loads(next((tmp_path / "re").iterdir()).read_text())
    assert rescored["journey"]["outcome_class"] == "builder_error"
    # Kills: a terminal error excusing every failed integrity check.
    bundle["case_contract_sha256"] = "0" * 64
    path.write_text(json.dumps(bundle), encoding="utf-8")
    assert (
        harness._reanalyze_bundles(bundle_paths=[path], output_dir=tmp_path / "re2")
        == 1
    )


def test_a_declared_turn_that_never_ran_fails_its_questions(
    harness: ModuleType,
) -> None:
    # Kills: missing declared turns hidden by padding the expected turns.
    expected = {**_EXPLICIT, "turns": [["choice"], []]}
    bundle = _scored(
        harness, expected, _CHOICE_TURN, calls=[_PROBE_CALL], follow_ups=("Mer.",)
    )
    measured = {c["name"]: c for c in bundle["quality_report"]["mcp_checks"]}

    assert measured["mcp_m1_questions"]["passed"] is False


def test_a_correct_run_of_an_mcp_case_passes_its_output_without_placement_gold(
    harness: ModuleType,
) -> None:
    expect = harness.OutputExpectation(
        output_kind="text", required_facts=("2026-09-03", "2026-09-11")
    )

    def output(text: str) -> str:
        bundle = _scored(
            harness,
            _EXPLICIT,
            _CHOICE_TURN,
            calls=[_PROBE_CALL],
            delivered=(text, expect),
        )
        return harness._verdict_states(bundle, observation_status="completed")["output"]

    # Kills: the generic placement grader left unmeasured beside M5, and the
    # fact checks dropped with it.
    assert output("Avvikande: 2026-09-03 och 2026-09-11.") == "pass"
    assert output("Avvikande: 2026-09-03.") == "fail"


def _choice(recommended: str, *offered: str) -> dict[str, Any]:
    question = _question("choice", use_ref="u")
    question["data"]["options"] = [{"id": r, "label": r, "value": r} for r in offered]
    question["data"]["recommended_option_id"] = recommended
    return question


def test_each_recommendation_is_judged_against_the_use_it_was_asked_for(
    harness: ModuleType,
) -> None:
    events = _manifest()["tools"][0] | {
        "name": "query_events",
        "tool_id": str(_EVENTS_ID),
        "ref": _EVENTS_REF,
    }
    manifest = {**_manifest(), "tools": [*_manifest()["tools"], events]}
    expected = harness.McpExpectation.model_validate(
        {
            "outcome": {"kind": "applied_plan"},
            "turns": [],
            "uses": [
                {"tool": _TOOL, "arguments": {}},
                {
                    "tool": {"server": "Driftdata", "name": "query_events"},
                    "arguments": {},
                },
            ],
        }
    )

    def pick(*questions: dict[str, Any]) -> bool | None:
        checks = mcp.mcp_checks(
            expected,
            interactions=[{"events": list(questions), "plan": None}],
            plan=None,
            applied=False,
            evidence={"manifest": manifest, "calls": [], "run_probe_started_at": None},
        )
        return next(c for c in checks if c["name"] == "mcp_m2_model_pick")["passed"]

    # Kills: a recommendation judged by membership in every expected tool.
    assert pick(_choice(_REF, _REF), _choice(_REF, _REF, _EVENTS_REF)) is None
    assert pick(_choice(_REF, _REF), _choice(_REF, _EVENTS_REF)) is False
    assert pick(_choice(_REF, _REF), _choice(_EVENTS_REF, _EVENTS_REF)) is True


def test_a_choice_offering_the_tools_of_two_rules_is_left_unanswered() -> None:
    events = {**_manifest()["tools"][0], "name": "query_events"}
    events |= {"tool_id": str(_EVENTS_ID), "ref": _EVENTS_REF}
    manifest = mcp.SeedManifest.model_validate(
        {**_manifest(), "tools": [*_manifest()["tools"], events]}
    )
    rules = mcp.TOOL_ANSWER_RULES.validate_python(
        [
            {"family": "choice", "tool": _TOOL},
            {
                "family": "choice",
                "tool": {"server": "Driftdata", "name": "query_events"},
            },
        ]
    )
    both = _choice(_REF, _REF, _EVENTS_REF)["data"]

    # Kills: rule order deciding which of two offered tools a use reads.
    assert mcp.scripted_tool_answer(both, rules, manifest) is None
    assert mcp.scripted_tool_answer(
        _choice(_EVENTS_REF, _EVENTS_REF)["data"], rules, manifest
    )


@mark.parametrize(
    ("offered", "selected"),
    [
        (["text", "no_run_input"], "no_run_input"),
        (["documents", "text"], "text"),
        (["documents"], None),
    ],
    ids=["first_preference_offered", "second_preference_offered", "none_offered"],
)
def test_a_preference_answers_with_the_first_listed_option_the_question_offers(
    harness: ModuleType, tmp_path: Path, offered: list[str], selected: str | None
) -> None:
    preference = {"selected_option_preference": ["no_run_input", "text"]}
    case = harness._read_cases_file(
        _cases_file(
            harness,
            tmp_path,
            question_answer_overrides={"primary_runtime_input": preference},
        )
    )[0]
    question = {
        "question_id": "primary_runtime_input",
        "options": [
            {"id": option, "label": option, "value": option} for option in offered
        ],
    }

    answer = harness._configured_question_answer(
        question=question,
        configured_answers=case.configured_question_answers,
        answer_sources=case.question_answer_sources,
    )

    # Kills: the preference read in the shown question's order, or a missing
    # option refused instead of leaving the question unanswered.
    chosen = answer["question_answer"]["selected_option_ids"] if answer else None
    assert chosen == ([selected] if selected else None)


def test_a_preference_is_its_own_answer_shape(
    harness: ModuleType, tmp_path: Path
) -> None:
    mixed = {"selected_option_preference": ["text"], "selected_option_id": "text"}

    # Kills: a preference accepted beside another answer mode.
    with raises(ValueError, match="exactly one valid answer mode"):
        harness._read_cases_file(
            _cases_file(
                harness,
                tmp_path,
                question_answer_overrides={"primary_runtime_input": mixed},
            )
        )


def test_a_follow_up_turn_without_its_own_plan_grades_no_plan_on_reanalysis(
    harness: ModuleType,
) -> None:
    # An old bundle kept the session's previous plan as its final plan.
    stalled = [
        *_CHOICE_TURN,
        {"events": [], "plan": _CHOICE_TURN[1]["plan"], "scripted_turn": 1},
    ]
    expected = {**_EXPLICIT, "turns": [["choice"], []]}
    bundle = _scored(
        harness, expected, stalled, calls=[_PROBE_CALL], follow_ups=("Mer.",)
    )
    measured = {c["name"]: c for c in bundle["quality_report"]["mcp_checks"]}

    # Kills: the shared reader grading bundle["plan"] instead of the last
    # turn's own plan.
    assert measured["mcp_m4_outcome"]["passed"] is False


def test_matching_twenty_uses_is_bounded_and_keeps_duplicates() -> None:
    def use(unit: str) -> Any:
        return mcp.ExpectedUse.model_validate(
            {"tool": _TOOL, "arguments": {"unit": {"fixed": unit}}}
        )

    actual = [{"tool": _TOOL, "arguments": {"unit": {"fixed": "hour"}}}] * 20
    started = time.monotonic()

    # Kills: a permutation search over the uses (20! orders when none fits).
    assert mcp._uses_hold([use("day")] * 20, actual) is False
    assert time.monotonic() - started < 0.5
    twice = [
        {"tool": _TOOL, "arguments": {"unit": {"fixed": u}}} for u in ("day", "day")
    ]
    assert mcp._uses_hold([use("day"), use("day")], twice) is True
    # Kills: a greedy pairing: the untyped expectation must leave the only
    # date field to the typed one.
    untyped, typed = (
        mcp.ExpectedUse.model_validate(
            {"tool": _TOOL, "arguments": {"from_date": {"run_input": field}}}
        )
        for field in ({"field": "from_date"}, {"field": "from_date", "type": "date"})
    )
    fields = [
        {
            "tool": _TOOL,
            "arguments": {
                "from_date": {"run_input": {"field": "from_date", "type": t}}
            },
        }
        for t in ("date", "text")
    ]
    assert mcp._uses_hold([untyped, typed], fields) is True


def test_a_producer_named_by_a_tool_used_twice_is_not_a_pass(
    harness: ModuleType,
) -> None:
    def chain(producer: dict[str, Any]) -> bool | None:
        steps = [
            _tool_step("step_1", {"unit": "day"}),
            _tool_step("step_2", {"unit": "week"}),
            _tool_step(
                "step_3", {"days": "{{ step_2.output.structured.anomaly_days }}"}
            ),
        ]
        expected = {
            "outcome": {"kind": "applied_plan"},
            "turns": [],
            "uses": [
                {"tool": _TOOL, "arguments": {"unit": {"fixed": "day"}}},
                {"tool": _TOOL, "arguments": {"unit": {"fixed": "week"}}},
                {
                    "tool": _TOOL,
                    "arguments": {
                        "days": {"earlier": {"step": producer, "field": "anomaly_days"}}
                    },
                },
            ],
        }
        interactions = [
            {"events": [], "plan": {"proposal": {"spec": {"steps": steps}}}}
        ]
        report = _scored(harness, expected, interactions, calls=[])["quality_report"]
        return next(c for c in report["mcp_checks"] if c["name"] == "mcp_m3_bindings")[
            "passed"
        ]

    # Kills: a tool that names two producing steps passing for either of them.
    assert chain({"tool": _TOOL}) is None
    assert chain({"order": 1}) is False
    assert chain({"order": 2}) is True


_GHOST = {"server": "Missing", "name": "ghost"}


def _ghost_case(where: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    def tool(place: str) -> dict[str, str]:
        return _GHOST if place == where else _TOOL

    producer = {"step": {"tool": tool("binding_producer")}, "field": "anomaly_days"}
    expected = {
        "outcome": {"kind": "applied_plan"},
        "turns": [],
        "uses": [{"tool": tool("use"), "arguments": {"days": {"earlier": producer}}}],
        "calls": [{"tool": tool("call"), "arguments": {}}],
    }
    rules = [
        {"family": "choice", "tool": tool("choice_rule")},
        {
            "family": "argument",
            "argument": "days",
            "source": "earlier",
            "step": {"tool": tool("answer_producer")},
            "field": "anomaly_days",
        },
    ]
    return expected, rules


@mark.parametrize(
    "where", ["choice_rule", "answer_producer", "use", "binding_producer", "call"]
)
def test_every_tool_a_case_names_must_be_seeded_before_any_observation(
    harness: ModuleType, tmp_path: Path, where: str
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    expected, rules = _ghost_case(where)
    case = harness.BattleCase(
        case_id="ghost",
        prompt="Hämta.",
        expected={"expected_mcp": expected},
        tool_answers=tuple(mcp.TOOL_ANSWER_RULES.validate_python(rules)),
    )
    args = SimpleNamespace(mcp_seed_manifest=str(manifest_path), space_id=_SPACE)

    # Kills: a selector source the seed check does not visit.
    with raises(ValueError, match="Missing/ghost"):
        harness._require_mcp_seed(args, [case])


# --- edit cases: the tool's output reaches the output, the saved flow is kept --

_SEED = json.loads(
    (_SCRIPTS / "fixtures" / "ai_builder_battle" / "edit_seed_a.json").read_text(
        encoding="utf-8"
    )
)
_SAVED_FIELDS: list[dict[str, Any]] = _SEED["metadata_json"]["form_schema"]["fields"]
_CASE_ID = {"name": "case_id", "type": "number", "label": "Ärende", "required": True}
_QUESTION = _SEED["steps"][0]["input_bindings"]["question"]


def _snapshot(steps: list[dict[str, Any]], fields: list[Any]) -> dict[str, Any]:
    """A persisted flow as the harness snapshots it."""
    return {
        "flow": {
            "steps": [{**step, "step_order": n} for n, step in enumerate(steps, 1)],
            "metadata_json": {"form_schema": {"fields": fields}},
        },
        "assistants": {
            step["assistant_id"]: {"prompt": {"text": step["instructions"]}}
            for step in steps
        },
    }


def _saved_steps() -> list[dict[str, Any]]:
    return [
        {**step, "assistant_id": f"saved-{n}", "user_description": step["name"]}
        for n, step in enumerate(_SEED["steps"], 1)
    ]


def _lookup_first(
    first_bindings: dict[str, Any],
    fields: list[Any],
    saved_fields: list[Any] = _SAVED_FIELDS,
) -> dict[str, Any]:
    """The seed's edit evidence after a lookup step is inserted first: the
    saved step_N refs renumbered as the apply writes them, step 1's bindings
    and the run form as given (the saved one too, when it is not the seed's)."""
    saved = _saved_steps()
    one, two, three = saved
    shifted = json.dumps(three["input_bindings"]).replace("step_2", "step_3")
    lookup = {
        "assistant_id": "lookup",
        "user_description": "Hämta ärende",
        "instructions": "Hämta ärendet.",
        "input_source": "tool",
        "input_config": _tool_step("x", {"case_id": "{{ flow_input.case_id }}"})[
            "input_config"
        ],
    }
    applied = [
        lookup,
        {**one, "input_bindings": first_bindings},
        two,
        {**three, "input_bindings": json.loads(shifted.replace("step_1", "step_2"))},
    ]
    return {
        "identity": {step["assistant_id"]: f"s{n}" for n, step in enumerate(saved, 1)},
        "baseline": _snapshot(saved, saved_fields),
        "applied": _snapshot(applied, fields),
    }


def _right_with_saved_fields(
    saved_fields: list[Any], kept: list[Any]
) -> dict[str, Any]:
    """The right plan over a run form the editor saved as `saved_fields`,
    written back as `kept` (new field first)."""
    return _lookup_first(
        {
            "question": _QUESTION,
            "source_refs": [{"step_ref": "step_1", "output": "text", "label": "Ä"}],
        },
        [{**_CASE_ID, "order": 1}, *kept],
        saved_fields,
    )


_UNREAD = {"name": "note", "type": "text", "label": "Anteckning", "required": False}
_UNLABELLED = [
    {k: v for k, v in field.items() if k != "label"} if n == 0 else field
    for n, field in enumerate(_SAVED_FIELDS)
]
_EDITS: dict[str, dict[str, Any] | None] = {
    # Positive control: the saved question text kept, the lookup added as a
    # source ref, the new field listed first (every saved field renumbered).
    "right": _lookup_first(
        {
            "question": _QUESTION,
            "source_refs": [{"step_ref": "step_1", "output": "text", "label": "Ä"}],
        },
        [
            {**_CASE_ID, "order": 1},
            *({**field, "order": field["order"] + 1} for field in _SAVED_FIELDS),
        ],
    ),
    # nc4046 luna6 cand2: no step reads the lookup, three saved fields relabelled
    # and made optional.
    "hollow": _lookup_first(
        {"question": _QUESTION},
        [
            *({**field, "label": "x", "required": False} for field in _SAVED_FIELDS),
            _CASE_ID,
        ],
    ),
    # The lookup read in place of the saved read of `ansokan`.
    "dropped_read": _lookup_first(
        {"question": "{{ step_1.output.text }}"}, [*_SAVED_FIELDS, _CASE_ID]
    ),
    # The authoring view reads an unlabelled saved field as its name, and a
    # label's surrounding space away, so neither is a change.
    "unlabelled_kept": _right_with_saved_fields(_UNLABELLED, _UNLABELLED),
    "label_padded": _right_with_saved_fields(
        _SAVED_FIELDS,
        [
            {**_SAVED_FIELDS[0], "label": f" {_SAVED_FIELDS[0]['label']} "},
            *_SAVED_FIELDS[1:],
        ],
    ),
    # A saved field no step reads, gone from the applied flow: only the
    # contract comparison can see it.
    "dropped_field": _right_with_saved_fields([*_SAVED_FIELDS, _UNREAD], _SAVED_FIELDS),
    # A saved field of a type the platform does not accept cannot be compared.
    "unaccepted_type": _right_with_saved_fields(
        [{**_SAVED_FIELDS[0], "type": "bogus"}, *_SAVED_FIELDS[1:]], _SAVED_FIELDS
    ),
    # The saved flow written back with no tool step at all.
    "no_tool_step": {
        "identity": {f"saved-{n}": f"s{n}" for n in (1, 2, 3)},
        "baseline": _snapshot(_saved_steps(), _SAVED_FIELDS),
        "applied": _snapshot(_saved_steps(), _SAVED_FIELDS),
    },
    "no_edit_evidence": None,
}
_M7 = "mcp_m7_tool_output_reaches_last_step"
_M8 = "mcp_m8_saved_flow_kept"


@mark.parametrize(
    ("edit", "reaches", "kept", "plan"),
    [
        ("right", True, True, "pass"),
        ("hollow", False, False, "fail"),
        ("dropped_read", True, False, "fail"),
        ("dropped_field", True, False, "fail"),
        ("unlabelled_kept", True, True, "pass"),
        ("label_padded", True, True, "pass"),
        ("unaccepted_type", True, None, "unmeasured"),
        ("no_tool_step", False, True, "fail"),
        ("no_edit_evidence", None, None, "unmeasured"),
    ],
)
def test_an_edit_adding_a_tool_passes_only_when_its_output_is_used_and_the_saved_flow_kept(
    harness: ModuleType, edit: str, reaches: bool | None, kept: bool | None, plan: str
) -> None:
    expected = {
        **_EXPLICIT,
        "tool_output_reaches_last_step": True,
        "keeps_saved_flow": True,
    }
    bundle = _scored(
        harness, expected, _CHOICE_TURN, calls=[_PROBE_CALL], edit=_EDITS[edit]
    )
    measured = {c["name"]: c for c in bundle["quality_report"]["mcp_checks"]}

    # Kills: an unread lookup counted as used; reach read through the implicit
    # chain a question replaces; a dropped saved read or a changed saved field
    # not caught; a removed saved field not counted as a change, or its absent
    # view raising in the contract reader; a renumbered field order taken for
    # a contract change; a saved field read by a second rule instead of the
    # authoring view (unlabelled or padded label); an unreadable saved type
    # raising or counting as a pass; a flow with no tool step passing M7; the
    # checks not gating the plan; no edit evidence read as a pass.
    assert (measured[_M7]["passed"], measured[_M8]["passed"]) == (reaches, kept)
    assert (
        harness._verdict_states(bundle, observation_status="completed")["plan"] == plan
    )


def test_an_mcp_case_that_declares_no_edit_check_reports_none(
    harness: ModuleType,
) -> None:
    bundle = _scored(
        harness, _EXPLICIT, _CHOICE_TURN, calls=[_PROBE_CALL], edit=_EDITS["hollow"]
    )

    # Kills: the edit checks reported for every case, which would change every
    # recorded report a reanalysis must reproduce.
    names = {c["name"] for c in bundle["quality_report"]["mcp_checks"]}
    assert {_M7, _M8}.isdisjoint(names)


def test_a_live_edit_observation_scores_its_edit_checks_as_reanalysis_does(
    harness: ModuleType, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    _EditApi().install(harness, monkeypatch)
    expected = {"outcome": {"kind": "applied_plan"}, "turns": [], "uses": []}
    case = harness._read_cases_file(
        _cases_file(
            harness,
            tmp_path,
            apply_plan=True,
            expected={"expected_mcp": {**expected, "keeps_saved_flow": True}},
            edit={"seed_flow_fixture": "edit_seed_a.json", "scope": "whole_flow"},
        )
    )[0]

    bundle = _run_edit(harness, case, tmp_path)

    # Kills: the live report scored before the bundle holds its edit evidence,
    # so it leaves M8 unmeasured where a reanalysis measures it.
    measured = {c["name"]: c for c in bundle["quality_report"]["mcp_checks"]}
    assert measured[_M8]["passed"] is True


# --- a run the applied flow's run form refuses -----------------------------

# The body Eneo's run endpoint answered in nc4046 (luna6 base2, mcp_f6).
_RECORDED_REFUSAL = (
    b'{"message":"Missing required input field \'input\'.","eneo_error_code":9007,'
    b'"code":"flow_input_required_field_missing","context":{"field_name":"input",'
    b'"field_type":"text"},"request_id":"4fa0584db72caf5c9c516aab1711f098"}'
)
_STALE_VERSION = b'{"code": "flow_run_stale_version"}'
_FORM_INPUT = {"form_fields": {"query": "Bullerklagomål"}}


def _run_case(inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "apply_plan": True,
        "execution": {
            "inputs": inputs,
            "expect": {"output_kind": "text", "required_facts": ["Hamnen"]},
        },
    }


@mark.parametrize(
    ("inputs", "declared", "body", "code"),
    [
        (
            _FORM_INPUT,
            ["query"],
            _RECORDED_REFUSAL,
            "flow_input_required_field_missing",
        ),
        (_FORM_INPUT, ["sokt"], None, "undeclared_form_field"),
        ({"text": "Bullerklagomål"}, ["query"], None, "free_text_for_form_flow"),
        (_FORM_INPUT, ["query"], _STALE_VERSION, None),
    ],
    ids=["server_refusal", "renamed_field", "free_text_on_form", "other_refusal"],
)
def test_a_run_form_refusing_the_case_input_fails_the_output_and_keeps_the_plan(
    harness: ModuleType,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    inputs: dict[str, Any],
    declared: list[str],
    body: bytes | None,
    code: str | None,
) -> None:
    plan = _plan(tool_arguments=None)
    runs: list[str] = []

    def request(*, method: str, path: str, **_: object) -> object:
        if path.endswith("/runs/"):
            runs.append(path)
            raise HTTPError(path, 400, "Bad Request", None, io.BytesIO(body or b""))  # type: ignore[arg-type]
        return {
            "/flows/ai-builder/plans/plan-1/create": {"flow_id": "flow-1"},
            "/flows/flow-1/": {"id": "flow-1", "steps": []},
            "/flows/flow-1/publish/": {"published_version": 2},
            "/flows/flow-1/run-contract/": {
                "published_flow_version": 2,
                "form_fields": [{"name": name} for name in declared],
            },
            "/flows/ai-builder/sessions/s-1/_diagnostics/classifier-slots": {
                "session_id": "s-1"
            },
        }.get(path, {})

    monkeypatch.setattr(harness, "_create_session", lambda **_: {"session_id": "s-1"})
    monkeypatch.setattr(
        harness,
        "_send_and_fetch",
        lambda **_: {"plan_id": "plan-1", "plan": plan, "events": []},
    )
    monkeypatch.setattr(harness, "_request_json", request)
    monkeypatch.setattr(harness, "_request_no_content", request)
    monkeypatch.setattr(harness, "_optional_request_json", lambda **_: None)
    # The fake session records no telemetry to judge live provenance by.
    monkeypatch.setattr(
        harness, "_quality_report_with_live_provenance", lambda report, **_: report
    )
    case = harness._read_cases_file(
        _cases_file(harness, tmp_path, **_run_case(inputs))
    )[0]

    def observe() -> dict[str, Any]:
        return harness._run_case_session(
            case=case,
            config=harness.ApiConfig(
                base_url="http://localhost:8123/api/v1",
                api_key="test-key",
                timeout_seconds=1,
            ),
            args=SimpleNamespace(
                space_id=_SPACE,
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

    if code is None:
        # Kills: every refused run request taken for the plan's, by status alone.
        with raises(harness.BattleFlowLifecycleError) as raised:
            observe()
        assert harness.harness_failure_class(raised.value) == "harness_configuration"
        return
    bundle = observe()

    # Kills: a refusal of the run form filed as a harness fault (its plan
    # dropped), kept as a harness refusal (an unmeasured output), or without
    # its typed code.
    assert bundle["plan_id"] == "plan-1" and "harness_refusal" not in bundle
    checks = {c["name"]: c for c in bundle["quality_report"]["checks"]}
    assert checks["run_input_accepted"]["actual"] == code
    states = harness._verdict_states(bundle, observation_status="completed")
    assert (states["output"], states["case"]) == ("fail", "fail")
    # Kills: the form's shape checked after the request, so a plan the input
    # cannot fit still starts a run.
    assert bool(runs) == (body is not None)
    # Kills: the refusal read from the live exception only, so a reanalysis
    # of the kept run record no longer fails the output.
    kept_record = {
        **_complete_live_case_bundle(harness, case),
        "flow_lifecycle": bundle["flow_lifecycle"],
    }
    kept_record["quality_report"] = harness._quality_report_of(
        kept_record,
        summary={},
        event_summary={},
        journey={},
        expected=case.expected or {},
        output_expectation=case.execution.expect,
    )
    path = tmp_path / "refused-run.json"
    path.write_text(json.dumps(kept_record), encoding="utf-8")
    assert (
        harness._reanalyze_bundles(bundle_paths=[path], output_dir=tmp_path / "re") == 0
    )
    rescored = json.loads(next((tmp_path / "re").iterdir()).read_text())
    assert rescored["observation"]["verdict_states"]["output"] == "fail"


@mark.parametrize(
    ("inputs", "declared", "payload"),
    [
        ({"text": "Hej"}, [], {"text": "Hej"}),
        ({"form_fields": {"query": "x"}}, ["query", "other"], {"query": "x"}),
        ({}, ["query"], None),
    ],
    ids=["text_for_a_flow_without_form", "subset_of_the_form", "no_input"],
)
def test_a_run_input_the_published_form_takes_is_sent_as_it_is(
    harness: ModuleType, inputs: dict[str, Any], declared: list[str], payload: Any
) -> None:
    contract = {"form_fields": [{"name": name} for name in declared]}

    # Kills: a form field the case leaves out (the server decides if it is
    # required) or free text for a Flow without a form taken for a mismatch.
    assert (
        harness._run_input_payload(
            contract=contract, inputs=harness.ExecutionInputs(**inputs)
        )
        == payload
    )


def test_the_run_form_refusals_are_those_the_run_form_validator_raises(
    harness: ModuleType,
) -> None:
    validator = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "eneo"
        / "flows"
        / "flow_run_input_payload.py"
    )
    raised = {
        FlowApiErrorCode[node.attr]
        for node in ast.walk(ast.parse(validator.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "FlowApiErrorCode"
    }

    # Kills: a code added to (or dropped from) the validator that the hand-kept
    # allowlist of the harness does not follow, so its refusal is a harness fault.
    assert harness._RUN_FORM_REFUSALS == raised
