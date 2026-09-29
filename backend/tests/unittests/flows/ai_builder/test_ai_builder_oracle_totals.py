"""The oracle experiment's totals: separate, never rescaled, one pre-registered rule
that fails closed, and an audit that corrects checks, not slots."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import ai_builder_code_identity as code_identity_module  # noqa: E402
import ai_builder_receipt as rcpt  # noqa: E402

_REAL_LOADED_CODE = code_identity_module.loaded_code


def _load(name: str, filename: str) -> ModuleType:
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def totals() -> ModuleType:
    # The audit re-scores through the harness, which the totals script finds by
    # name; the comparator is found the same way.
    _load("ai_builder_api_battle_test", "ai_builder_api_battle_test.py")
    return _load("ai_builder_oracle_totals", "ai_builder_oracle_totals.py")


CASES = [f"case-{i}" for i in range(20)]
TEXT = "Beslut om bygglov. Ärendenummer IAN-1. Beslutsdatum 2026-10-06."
EXPECT: dict[str, Any] = {
    "output_kind": "text",
    "required_facts": ["IAN-1", "2026-10-06"],
    "forbidden": ["personnummer"],
    "associations": [],
}
HARNESS_SHA = "h" * 64
SCORER_SHA = "d" * 64
SOURCE = "s" * 40
CASES_SHA = "c" * 64
MANIFEST_SHA = "m" * 64
BUILDER_MODEL = "model-luna6"
CONTEXT = {
    "auto_confirm_requirements": True,
    "confirm_message_sha256": "f" * 64,
    "max_concurrency": 4,
    "max_concurrent_observations_per_case": 1,
    "flow_isolation_semantics_version": 1,
    "ui_language": "sv",
}


def _intake_hashes() -> dict[str, str]:
    return {c: hashlib.sha256(c.encode()).hexdigest() for c in CASES}


def _evidence(
    text: str, *, outcome: str = "completed", model: str = "gpt-6-luna"
) -> dict[str, Any]:
    return {
        "execution": {"outcome": outcome, "failures": []},
        "run": {"status": outcome, "result": {"kind": "inline_text", "text": text}},
        "run_contract": {"final_output": {"output_type": "text"}},
        "final_artifact": None,
        "step_attempts": [
            {
                "id": "attempt-1",
                "status": "completed",
                "requested_model": model,
                "response_model": model,
                "provider": "openai",
                "num_tokens_input": 10,
            },
            # A canned step (a renderer): completes with no model and no call.
            {
                "id": "attempt-2",
                "status": "completed",
                "requested_model": None,
                "response_model": None,
                "provider": None,
                "provider_response_id": None,
                "num_tokens_input": 0,
                "num_tokens_output": 0,
            },
        ],
    }


_VERDICTS = {
    # plan, review_edit, output, case
    "pass": ("pass", "not_required", "pass", "pass"),
    "failed": ("pass", "not_required", "fail", "fail"),
    "not_executed": ("fail", "not_required", "unmeasured", "fail"),
    "invalid": ("unmeasured", "not_required", "unmeasured", "unmeasured"),
    # A case that asks for no output: valid to the reader, never a selected case.
    "no_output": ("pass", "not_required", "not_required", "pass"),
}


def _verdict_states(state: str) -> dict[str, str]:
    plan, review_edit, output, case = _VERDICTS[state]
    return {"plan": plan, "review_edit": review_edit, "output": output, "case": case}


def _row(case: str, rep: int, state: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "case_id": case,
        "repetition": rep,
        "observation_status": "completed",
        "outcome_class": "completed",
        "expectation_verdict": "met",
        "output_executed": True,
        "output_success": True,
        "verdict_states": _verdict_states("pass" if state == "pass" else state),
        "bundle_file": f"{case}-r{rep}.json",
    }
    if state == "no_output":
        base.update(output_executed=False, output_success=None)
    elif state == "failed":
        base.update(output_success=False, expectation_verdict="not_met")
    elif state == "not_executed":
        base.update(output_executed=False, output_success=None)
    elif state == "invalid":
        base.update(
            observation_status="execution_failure",
            failure_class="harness_configuration",
            output_executed=False,
            output_success=None,
        )
    return base


def _provenance(
    *, requested: str | None, harness: str, clean: bool = True
) -> dict[str, Any]:
    stable = {
        "source_revision": SOURCE,
        "harness_sha256": harness,
        "cases_sha256": CASES_SHA,
    }
    model = {"requested_id": requested}
    return {
        "source": {
            "revision": SOURCE,
            "revision_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
            "tracked_clean": clean,
        },
        "build": {**stable, "sha256": rcpt.canonical_sha256(stable)},
        "model": {**model, "sha256": rcpt.canonical_sha256(model)},
    }


def _write_receipt(
    directory: Path,
    rows: list[dict[str, Any]],
    bodies: dict[tuple[str, int], dict[str, Any]],
    *,
    run_context: dict[str, Any],
    requested: str | None,
    target: dict[str, Any] | None,
    integrity: str = "complete",
    suite_identity_failures: int = 0,
    created_at: str = "20260929T100000",
    harness: str = HARNESS_SHA,
    legacy: bool = False,
    tracked_clean: bool | None = True,
    bundle_clean: bool = True,
) -> None:
    """A suite directory the receipt reader accepts: a manifest of the expected
    slots, one sealed bundle per row whose digest the row carries, and a summary
    and manifest that agree on the run's identity. A `legacy` receipt is one from
    a scorer that recorded no identity and no verdict states."""

    provenance = _provenance(requested=requested, harness=harness, clean=bundle_clean)
    for row in rows:
        if legacy:
            row.pop("verdict_states", None)
        contract = {"id": row["case_id"]}
        row["case_contract_sha256"] = rcpt.canonical_sha256(contract)
        sealed = {k: v for k, v in row.items() if k not in rcpt.BUNDLE_REFERENCE_FIELDS}
        bundle = {
            **bodies[(row["case_id"], row["repetition"])],
            "repetition": row["repetition"],
            "case_identity": {"id": row["case_id"]},
            "case_contract": contract,
            "case_contract_sha256": row["case_contract_sha256"],
            "live_execution_provenance": provenance,
            "observation": sealed,
        }
        data = json.dumps(bundle).encode()
        (directory / row["bundle_file"]).write_bytes(data)
        row["bundle_sha256"] = hashlib.sha256(data).hexdigest()
    release_identity = {
        # The run's own record of whether its tracked source was clean; None
        # leaves the key out (a receipt that does not say).
        "source": {
            "revision": SOURCE,
            **({} if tracked_clean is None else {"tracked_clean": tracked_clean}),
        },
        "build": {"harness_sha256": harness, "cases_sha256": CASES_SHA},
        "model": {"requested_id": requested},
        **({"target": target} if target else {}),
    }
    evaluator_identity = {
        "question_relevance_semantics_version": 3,
        "outcome_classification_semantics_version": 6,
        "observation_input_identity_semantics_version": 4,
        "requested_model_id": requested,
        "harness_sha256": harness,
        **(
            {}
            if legacy
            else {"scorer_semantics_version": 1, "scorer_sha256": SCORER_SHA}
        ),
        "source_revision": SOURCE,
        "cases_sha256": CASES_SHA,
        "case_contract_sha256_by_id": {c: "k" * 64 for c in CASES},
        "run_context": run_context,
    }
    (directory / "release-manifest.json").write_text(
        json.dumps(
            {
                "artifact_schema_version": "ai-builder-live-release.v6",
                "artifact_mode": "live_execution_manifest",
                "created_at": created_at,
                "release_identity": release_identity,
                "evaluator_identity": evaluator_identity,
                "capacity_preflight": {},
                "expected_observations": [
                    {
                        "case_id": row["case_id"],
                        "repetition": row["repetition"],
                        "case_contract_sha256": row["case_contract_sha256"],
                    }
                    for row in rows
                ],
            }
        )
    )
    (directory / "suite-summary.json").write_text(
        json.dumps(
            {
                "artifact_schema_version": "ai-builder-live-release.v6",
                "artifact_mode": "live_execution_summary",
                "created_at": created_at,
                "repetitions": 3,
                "receipt_integrity": {"status": integrity},
                "suite_identity_failed_check_count": suite_identity_failures,
                "release_identity": release_identity,
                "evaluator_identity": evaluator_identity,
                "capacity_preflight": {},
                **(
                    {}
                    if legacy
                    else {
                        "observation_summary": {
                            "state_counts": rcpt.verdict_state_counts(
                                row["verdict_states"] for row in rows
                            )
                        }
                    }
                ),
                "results": rows,
            }
        )
    )


def _leg_dir(
    tmp_path: Path,
    label: str,
    rows: list[dict[str, Any]],
    *,
    arm: str = "builder",
    texts: dict[tuple[str, int], str] | None = None,
    model: str = "gpt-6-luna",
    integrity: str = "complete",
    context: dict[str, Any] | None = None,
    harness: str = HARNESS_SHA,
    intake: str | None = "upfront",
    requested: str | None | bool = True,
    target: dict[str, Any] | None | bool = True,
    suite_identity_failures: int = 0,
    attempts: dict[tuple[str, int], list[dict[str, Any]]] | None = None,
    evidence: dict[tuple[str, int], dict[str, Any]] | None = None,
    created_at: str = "20260929T100000",
    legacy: bool = False,
    tracked_clean: bool | None = True,
    bundle_clean: bool = True,
) -> str:
    directory = tmp_path / f"{label}-{len(list(tmp_path.glob(label + '-*')))}"
    directory.mkdir()
    bodies: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        key = (row["case_id"], row["repetition"])
        text = (texts or {}).get(key, TEXT)
        bodies[key] = {
            "case": {
                "id": row["case_id"],
                "expected": {},
                "execution": {"expect": EXPECT},
            },
            "runtime_evidence": (evidence or {}).get(key)
            or {
                **_evidence(text, model=model),
                **(
                    {"step_attempts": attempts[key]}
                    if attempts and key in attempts
                    else {}
                ),
            },
        }
    run_context = {
        **(context if context is not None else CONTEXT),
        **({"arm": arm} if arm != "builder" else {}),
        **(
            {"intake_answers": intake, "intake_answers_sha256_by_id": _intake_hashes()}
            if intake
            else {}
        ),
        **({"oracle_manifest_sha256": MANIFEST_SHA} if arm == "oracle" else {}),
    }
    if requested is True:
        requested = BUILDER_MODEL if arm == "builder" else None
    if target is True:
        target = {
            "api_base_url": "http://127.0.0.1:8146/api/v1",
            "version": f"DEV-{SOURCE[:12]}",
            "expected_app_version": f"DEV-{SOURCE[:12]}",
            "expected_source_revision": SOURCE,
            "verified": True,
            "sha256": "t" * 64,
        }
    _write_receipt(
        directory,
        rows,
        bodies,
        run_context=run_context,
        requested=(requested if isinstance(requested, str) else None),
        target=target or None,
        integrity=integrity,
        suite_identity_failures=suite_identity_failures,
        created_at=created_at,
        harness=harness,
        legacy=legacy,
        tracked_clean=tracked_clean,
        bundle_clean=bundle_clean,
    )
    return str(directory)


def _rows(fulfilled: int, *, invalid: int = 0) -> list[dict[str, Any]]:
    """60 slots: the first `fulfilled` pass, the next `invalid` are refused, the rest failed."""
    slots = [(c, r) for r in (1, 2, 3) for c in CASES]
    states = ["pass"] * fulfilled + ["invalid"] * invalid
    states += ["failed"] * (len(slots) - len(states))
    return [_row(c, r, s) for (c, r), s in zip(slots, states)]


def _leg(totals: ModuleType, tmp_path: Path, label: str, arm: str, rows, **kw) -> Any:
    model = kw.get("model", "gpt-6-luna")
    return totals.parse_leg(
        f"{label}:{arm}:{model}={_leg_dir(tmp_path, label, rows, arm=arm, **kw)}"
    )


def _selection(**overrides: Any) -> dict[str, Any]:
    return {
        "repetitions": 3,
        "cases": [
            {"id": c, "held_out": i % 2 == 0, "f18": i == 0, "edit_target": False}
            for i, c in enumerate(CASES)
        ],
        **overrides,
    }


def _freeze(totals: ModuleType, selection_path: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "h1_sha": "1" * 40,
        "scorer_source_revision": SOURCE,
        "harness_sha256": HARNESS_SHA,
        "scorer_semantics_version": 1,
        "scorer_sha256": SCORER_SHA,
        "cases_sha256": CASES_SHA,
        "selection_sha256": hashlib.sha256(selection_path.read_bytes()).hexdigest(),
        "oracle_manifest_sha256": MANIFEST_SHA,
        "totals_sha256": hashlib.sha256(
            (_SCRIPTS / "ai_builder_oracle_totals.py").read_bytes()
        ).hexdigest(),
        "builder_model_id": BUILDER_MODEL,
        "intake_message_sha256_by_id": _intake_hashes(),
        "material_manifest_sha256": "a" * 64,
        "docs_manifest_sha256": "b" * 64,
        "legs": {
            "A_luna6": {"arm": "builder", "runtime_model": "gpt-6-luna"},
            "O_luna6": {"arm": "oracle", "runtime_model": "gpt-6-luna"},
            "O_gemma": {"arm": "oracle", "runtime_model": "gemma4-31b-it"},
        },
    }


class _World:
    """A frozen experiment on disk, ready to be broken one way at a time."""

    def __init__(self, totals: ModuleType, tmp_path: Path) -> None:
        self.totals = totals
        self.tmp = tmp_path
        self.selection = _selection()
        self.selection_path = tmp_path / "selection.json"
        self.selection_path.write_text(json.dumps(self.selection))
        self.freeze = _freeze(totals, self.selection_path)

    def legs(
        self,
        *,
        o: int = 24,
        a: int = 12,
        a_kw: dict | None = None,
        o_kw: dict | None = None,
    ):
        return [
            _leg(self.totals, self.tmp, "A_luna6", "builder", _rows(a), **(a_kw or {})),
            _leg(self.totals, self.tmp, "O_luna6", "oracle", _rows(o), **(o_kw or {})),
        ]

    def decide(
        self, legs, *, corrections=(), selection=None, freeze=None
    ) -> dict[str, Any]:
        selection = selection or self.selection
        path = self.tmp / "sel-decide.json"
        path.write_text(json.dumps(selection))
        return self.totals.decide(
            legs,
            selection,
            freeze or self.freeze,
            selection_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            corrections=corrections,
        )


@pytest.fixture()
def world(totals: ModuleType, tmp_path: Path) -> _World:
    return _World(totals, tmp_path)


# ------------------------------------------------------------------- totals


def test_a_slot_has_exactly_one_state_and_totals_are_never_rescaled(
    totals: ModuleType, tmp_path: Path
) -> None:
    rows = [
        _row("a", 1, "pass"),
        _row("a", 2, "failed"),
        _row("a", 3, "not_executed"),
        _row("b", 1, "invalid"),
        _row("b", 2, "pass"),
        _row("b", 3, "failed"),
    ]
    leg = _leg(totals, tmp_path, "A_luna6", "builder", rows)
    result = totals.leg_totals(leg, {})

    assert result["attempted"] == 6  # every slot stays in the denominator
    assert result["invalid_evidence"] == 1
    assert result["invalid_by_class"] == {"execution_failure:harness_configuration": 1}
    assert result["executed"] == 4 and result["not_executed"] == 1
    assert result["fulfilled_of_attempted"] == "2/6"
    assert result["fulfilled_of_executed"] == "2/4"  # labelled, never the headline
    assert totals.per_case(leg, {}) == {"a": "PF-", "b": "?PF"}


def test_the_rule_at_its_boundaries_is_an_exploratory_pilot_decision(
    world: _World,
) -> None:
    def rule(o: int, a: int) -> dict[str, Any]:
        o_leg = _leg(world.totals, world.tmp, "O", "oracle", _rows(o))
        a_leg = _leg(world.totals, world.tmp, "A", "builder", _rows(a))
        return world.totals.rule(
            world.totals.leg_totals(o_leg, {}), world.totals.leg_totals(a_leg, {})
        )

    assert rule(24, 12)["outcome"] == "ADVANCE_EXPLORATORY_PILOT"  # 40% and +20
    assert "not proof" in rule(24, 12)["meaning"]
    assert rule(24, 13)["outcome"] == "NO_ADVANTAGE_FIX_CONTRACTS_FIRST"
    low = rule(23, 3)  # 38%: a trigger to investigate delivery, not a ceiling
    assert low["outcome"] == "DELIVERY_INVESTIGATION"
    assert low["o_threshold_met"] is False


# ------------------------------------------- the decision fails closed


def test_a_matched_frozen_experiment_can_advance_and_shows_its_interval(
    world: _World,
) -> None:
    decision = world.decide(world.legs(o=24, a=12))
    assert decision["problems"] == []
    assert decision["outcome"] == "ADVANCE_EXPLORATORY_PILOT"
    assert decision["gap_interval"]["clusters"] == 20


@pytest.mark.parametrize(
    "breakage, needle",
    [
        ("seven_invalid_a", "7 invalid slots"),
        ("wrong_runtime_model", "steps ran on ['gpt-5.6-luna']"),
        ("swapped_arm_labels", "differ from the freeze record"),
        ("changed_concurrency", "max_concurrency"),
        ("other_scorer", "harness_sha256 is not the frozen scorer's"),
        ("other_scorer_modules", "scorer_sha256 is not the frozen scorer's"),
        (
            "other_scorer_semantics",
            "scorer_semantics_version is not the frozen scorer's",
        ),
        ("builder_model_not_frozen", "Builder model is not the frozen one"),
        ("oracle_names_builder_model", "names a Builder model"),
        ("manifest_not_frozen", "spec manifest is not the frozen one"),
        ("intake_asked", "intake answers were not given up front"),
        ("intake_other_text", "not the frozen author material"),
        ("partial_receipt", "receipt is not complete"),
        ("missing_slot", "slots are not exactly"),
        ("selection_edit_target", "review-edit"),
        ("selection_changed", "not the frozen one"),
        ("totals_changed", "totals script is not the frozen one"),
        ("no_o_leg", "decision leg O_luna6 is missing"),
        ("duplicate_a_receipt", "duplicate leg label A_luna6"),
        ("label_not_allowed", "not one of the legs the freeze record allows"),
        ("no_target", "no verified deployed revision"),
        ("target_unverified", "deployed API was not verified"),
        ("wrong_deployed_revision", "not the frozen tree's revision"),
        ("identity_changed_during_leg", "identity changed between start and end"),
        ("different_api", "did not run against the same deployed API"),
    ],
)
def test_no_broken_experiment_can_advance(
    world: _World, breakage: str, needle: str
) -> None:
    legs = world.legs(o=24, a=12)
    selection, freeze = None, None
    if breakage == "seven_invalid_a":
        legs[0] = _leg(
            world.totals, world.tmp, "A_luna6", "builder", _rows(12, invalid=7)
        )
    elif breakage == "wrong_runtime_model":
        legs[0] = _leg(
            world.totals,
            world.tmp,
            "A_luna6",
            "builder",
            _rows(12),
            model="gpt-5.6-luna",
        )
        legs[0] = world.totals.Leg(
            "A_luna6",
            "builder",
            "gpt-6-luna",  # declared; the bundles say otherwise
            legs[0].directory,
            legs[0].summary,
            legs[0].rows,
        )
    elif breakage == "swapped_arm_labels":
        legs = [
            _leg(world.totals, world.tmp, "A_luna6", "oracle", _rows(12)),
            _leg(world.totals, world.tmp, "O_luna6", "builder", _rows(24)),
        ]
    elif breakage == "changed_concurrency":
        legs = world.legs(o_kw={"context": {**CONTEXT, "max_concurrency": 2}})
    elif breakage == "other_scorer":
        legs = world.legs(o_kw={"harness": "x" * 64})
    elif breakage == "other_scorer_modules":
        freeze = {**world.freeze, "scorer_sha256": "0" * 64}
    elif breakage == "other_scorer_semantics":
        freeze = {**world.freeze, "scorer_semantics_version": 2}
    elif breakage == "builder_model_not_frozen":
        legs = world.legs(a_kw={"requested": "model-other"})
    elif breakage == "oracle_names_builder_model":
        legs = world.legs(o_kw={"requested": BUILDER_MODEL})
    elif breakage == "manifest_not_frozen":
        freeze = {**world.freeze, "oracle_manifest_sha256": "z" * 64}
    elif breakage == "intake_asked":
        legs = world.legs(a_kw={"intake": None})
    elif breakage == "intake_other_text":
        freeze = {
            **world.freeze,
            "intake_message_sha256_by_id": {**_intake_hashes(), "case-3": "0" * 64},
        }
    elif breakage == "partial_receipt":
        legs = world.legs(o_kw={"integrity": "partial"})
    elif breakage == "missing_slot":
        legs = [
            _leg(world.totals, world.tmp, "A_luna6", "builder", _rows(12)[:-1]),
            _leg(world.totals, world.tmp, "O_luna6", "oracle", _rows(24)),
        ]
    elif breakage == "selection_edit_target":
        selection = _selection()
        selection["cases"][1]["edit_target"] = True
    elif breakage == "selection_changed":
        selection = _selection(cases=list(reversed(_selection()["cases"])))
    elif breakage == "totals_changed":
        freeze = {**world.freeze, "totals_sha256": "q" * 64}
    elif breakage == "no_o_leg":
        legs = legs[:1]
    elif breakage == "duplicate_a_receipt":
        # An undeclared second receipt of A, valid on its own and better than the first.
        legs = [*legs, _leg(world.totals, world.tmp, "A_luna6", "builder", _rows(0))]
    elif breakage == "label_not_allowed":
        legs = [*legs, _leg(world.totals, world.tmp, "O_extra", "oracle", _rows(24))]
    elif breakage == "no_target":
        legs = world.legs(a_kw={"target": False})
    elif breakage == "target_unverified":
        legs = world.legs(
            o_kw={
                "target": {
                    "api_base_url": "http://127.0.0.1:8146/api/v1",
                    "version": f"DEV-{SOURCE[:12]}",
                    "expected_source_revision": SOURCE,
                    "verified": False,
                }
            }
        )
    elif breakage == "wrong_deployed_revision":
        legs = world.legs(
            o_kw={
                "target": {
                    "api_base_url": "http://127.0.0.1:8146/api/v1",
                    "version": "DEV-000000000000",
                    "expected_source_revision": "0" * 40,
                    "verified": True,
                }
            }
        )
    elif breakage == "identity_changed_during_leg":
        legs = world.legs(o_kw={"suite_identity_failures": 1})
    elif breakage == "different_api":
        legs = world.legs(
            o_kw={
                "target": {
                    "api_base_url": "http://127.0.0.1:9999/api/v1",
                    "version": f"DEV-{SOURCE[:12]}",
                    "expected_source_revision": SOURCE,
                    "verified": True,
                }
            }
        )

    decision = world.decide(legs, selection=selection, freeze=freeze)

    assert decision["outcome"] == "NO_DECISION", decision
    assert any(needle in problem for problem in decision["problems"]), decision[
        "problems"
    ]


def test_a_freeze_record_missing_a_key_is_refused_outright(
    totals: ModuleType, tmp_path: Path
) -> None:
    path = tmp_path / "freeze.json"
    path.write_text(json.dumps({"schema_version": 1}))
    with pytest.raises(totals.ExperimentError, match="lacks"):
        totals.load_freeze(path)
    with pytest.raises(totals.ExperimentError, match="required"):
        totals.load_freeze(None)


# ---------------------------------------------------------------- the audit


def _correction(**changes: Any) -> dict[str, Any]:
    return {
        "case_id": "case-0",
        "check": {"name": "required_fact", "fact": "2026-10-06"},
        "action": "remove",
        "class": "OW",
        "evidence": "the rutin sets 2026-10-16, fixture oms09 section 2",
        **changes,
    }


def _audit(totals: ModuleType, tmp_path: Path, *corrections: dict[str, Any]) -> Any:
    path = tmp_path / f"audit-{len(list(tmp_path.glob('audit-*')))}.json"
    path.write_text(json.dumps({"corrections": list(corrections)}))
    return totals.read_corrections(path, _selection())


def _two_check_legs(totals: ModuleType, tmp_path: Path) -> tuple[Any, Any]:
    """case-0 fails BOTH required facts in both arms; every other slot passes."""

    texts = {("case-0", r): "Beslut om bygglov." for r in (1, 2, 3)}
    slots = [(c, r) for r in (1, 2, 3) for c in CASES]
    rows = [_row(c, r, "failed" if c == "case-0" else "pass") for c, r in slots]
    a = _leg(totals, tmp_path, "A_luna6", "builder", rows, texts=texts)
    o = _leg(
        totals, tmp_path, "O_luna6", "oracle", [dict(r) for r in rows], texts=texts
    )
    return a, o


def test_an_audit_naming_one_of_two_failed_checks_lifts_nothing(
    totals: ModuleType, tmp_path: Path
) -> None:
    a, _ = _two_check_legs(totals, tmp_path)
    one = _audit(totals, tmp_path, _correction())  # overturns 2026-10-06 only

    audit = totals.audited_states(a, one)

    assert audit == {}  # IAN-1 is still required and still missing
    assert totals.leg_totals(a, audit)["fulfilled_audited"] == 57


def test_an_audit_overturning_every_failed_check_lifts_the_slot_in_both_arms(
    totals: ModuleType, tmp_path: Path
) -> None:
    a, o = _two_check_legs(totals, tmp_path)
    both = _audit(
        totals,
        tmp_path,
        _correction(),
        _correction(
            check={"name": "required_fact", "fact": "IAN-1"}, evidence="not in fixtures"
        ),
    )

    for leg in (a, o):  # the same correction, applied to each arm
        audit = totals.audited_states(leg, both)
        assert set(audit.values()) == {"lifted"} and len(audit) == 3
        assert totals.leg_totals(leg, audit)["fulfilled_audited"] == 60
        assert totals.leg_totals(leg, audit)["fulfilled"] == 57  # raw stays
        assert totals.per_case(leg, audit)["case-0"] == "ppp"


def test_a_slot_failing_another_check_never_lifts_and_a_stricter_check_drops(
    totals: ModuleType, tmp_path: Path
) -> None:
    # case-0 is wrongly delivered as a run that did not complete: no literal
    # correction can lift it.
    slots = [(c, r) for r in (1, 2, 3) for c in CASES]
    rows = [_row(c, r, "failed" if c == "case-0" else "pass") for c, r in slots]
    leg = _leg(
        totals,
        tmp_path,
        "A_luna6",
        "builder",
        rows,
        evidence={("case-0", r): _evidence(TEXT, outcome="failed") for r in (1, 2, 3)},
    )
    overturn = _audit(
        totals,
        tmp_path,
        _correction(),
        _correction(check={"name": "required_fact", "fact": "IAN-1"}),
    )
    assert totals.audited_states(leg, overturn) == {}  # run_completed still fails

    # A corrected literal that the delivered text lacks drops a slot that passed.
    stricter = _audit(
        totals,
        tmp_path,
        _correction(
            case_id="case-1",
            action="replace",
            check={"name": "required_fact", "fact": "IAN-1"},
            **{"with": "IAN-2"},
        ),
    )
    audit = totals.audited_states(leg, stricter)
    assert set(audit.values()) == {"dropped"} and len(audit) == 3
    assert totals.leg_totals(leg, audit)["fulfilled_audited"] == 60 - 3 - 3
    assert totals.per_case(leg, audit)["case-1"] == "xxx"


def test_a_correction_must_name_an_existing_check_with_class_and_evidence(
    totals: ModuleType, tmp_path: Path
) -> None:
    for bad in (
        _correction(**{"class": "guess"}),
        _correction(evidence=""),
        _correction(action="delete"),
        _correction(action="replace"),  # a replacement needs `with`
        _correction(case_id="not-selected"),
        _correction(check={"name": "run_completed"}),
        _correction(check={"name": "output_association", "fact": "x"}),
        _correction(
            check={"name": "output_association", "fact": "x"},
            action="replace",
            **{"with": "y"},
        ),
    ):
        with pytest.raises(totals.ExperimentError):
            _audit(totals, tmp_path, bad)

    corrections = _audit(
        totals,
        tmp_path,
        _correction(check={"name": "required_fact", "fact": "nowhere"}),
    )
    a, _ = _two_check_legs(totals, tmp_path)
    with pytest.raises(totals.ExperimentError, match="not a check of the case"):
        totals.audited_states(a, corrections)


def _rows_case0_failed(fulfilled: int) -> list[dict[str, Any]]:
    """case-0 fails in all three repetitions; `fulfilled` of the rest pass."""
    slots = [(c, r) for r in (1, 2, 3) for c in CASES]
    others = iter(range(len(slots)))
    rows = []
    passed = 0
    for c, r in slots:
        if c == "case-0":
            rows.append(_row(c, r, "failed"))
        else:
            passed += 1
            rows.append(_row(c, r, "pass" if passed <= fulfilled else "failed"))
    del others
    return rows


def test_the_decision_uses_the_corrected_counts_of_both_arms(world: _World) -> None:
    # case-0 fails in both arms only because its date literal is wrong: the
    # delivered text states the case number and lacks 2026-10-06.
    texts = {("case-0", r): "Beslut. Ärendenummer IAN-1." for r in (1, 2, 3)}
    legs = [
        _leg(
            world.totals,
            world.tmp,
            "A_luna6",
            "builder",
            _rows_case0_failed(3),
            texts=texts,
        ),
        _leg(
            world.totals,
            world.tmp,
            "O_luna6",
            "oracle",
            _rows_case0_failed(23),
            texts=texts,
        ),
    ]
    fix = _audit(world.totals, world.tmp, _correction())  # drop the date literal

    raw = world.decide(legs)
    audited = world.decide(legs, corrections=fix)

    assert raw["outcome"] == "DELIVERY_INVESTIGATION" and raw["o_audited"] == "23/60"
    # Both arms are re-scored with the same corrected check: 3 slots each.
    assert (audited["o_audited"], audited["a_audited"]) == ("26/60", "6/60")
    assert audited["outcome"] == "ADVANCE_EXPLORATORY_PILOT"


# ------------------------------------------------------------ report and CLI


def test_the_markdown_leads_with_the_interval_and_names_the_reasons_when_there_is_no_decision(
    world: _World,
) -> None:
    good = {
        "totals": {},
        "per_case": {"A_luna6": {"c": "PPP"}},
        "decision": {
            "outcome": "ADVANCE_EXPLORATORY_PILOT",
            "rule": "r",
            "meaning": "an exploratory pilot decision on 20 case clusters, not proof",
            "gap_points": 20.0,
            "o_audited": "24/60",
            "a_audited": "12/60",
            "gap_interval": {"level": 90, "clusters": 20, "low": -5.0, "high": 45.0},
        },
    }
    text = world.totals.render_markdown(good)
    assert text.startswith("**Interval (read this first)**")
    assert "-5.0 to 45.0" in text and "not proof" in text
    none = world.totals.render_markdown(
        {
            **good,
            "decision": {
                "outcome": "NO_DECISION",
                "problems": ["A_luna6: 7 invalid slots"],
            },
        }
    )
    assert none.startswith("**NO DECISION.**") and "7 invalid slots" in none


# ------------------------------------------------- the frozen case selection


def _selection_file() -> dict[str, Any]:
    return json.loads((_SCRIPTS / "ai_builder_oracle_cases.json").read_text())


def _corpus() -> dict[str, dict[str, Any]]:
    cases = json.loads((_SCRIPTS / "ai_builder_api_municipal_cases.json").read_text())
    return {case["id"]: case for case in cases["cases"]}


def test_the_selection_is_20_distinct_executing_creates_no_exclusion_touches(
    totals: ModuleType,
) -> None:
    selection, corpus = _selection_file(), _corpus()
    ids = [c["id"] for c in selection["cases"]]
    assert len(ids) == len(set(ids)) == 20 and selection["repetitions"] == 3
    excluded = {cid for group in selection["excluded"].values() for cid in group["ids"]}
    assert not excluded & set(ids)
    for cid in ids:
        case = corpus[cid]
        assert cid.startswith(("mc_", "mb_")) and "edit" not in case
        assert "flow_edit" not in case.get("cohorts", []) and "execution" in case
    assert not set(selection["reserve_in_order"]) & (excluded | set(ids))


def test_no_selected_or_reserve_case_declares_a_review_edit_target(
    totals: ModuleType,
) -> None:
    """The typed H2 check does not exist yet: a differently named review field
    would stop the run as `review_target_missing` and read as a delivery failure."""

    selection, corpus = _selection_file(), _corpus()

    def edit_target(cid: str) -> bool:
        return any(
            c.get("action") == "edit_target"
            for c in corpus[cid]["execution"].get("checkpoints") or []
        )

    assert not any(edit_target(c["id"]) or c["edit_target"] for c in selection["cases"])
    assert not any(edit_target(c) for c in selection["reserve_in_order"])
    every_edit_target = {
        c for c in corpus if c.startswith(("mc_", "mb_")) and edit_target(c)
    }
    listed = {cid for group in selection["excluded"].values() for cid in group["ids"]}
    assert every_edit_target <= listed  # each one is excluded with a reason


def test_coverage_tags_are_mechanical_and_every_category_has_a_quota(
    totals: ModuleType,
) -> None:
    selection, corpus = _selection_file(), _corpus()
    counts: dict[str, int] = {}
    for entry in selection["cases"]:
        for tag in totals.mechanical_tags(corpus[entry["id"]]):
            counts[tag] = counts.get(tag, 0) + 1
    assert all(counts.get(tag, 0) >= 3 for tag in ("IN", "REF", "REV", "TPL", "LOSS"))


def test_held_out_means_no_question_or_classification_screen_used_the_case() -> None:
    selection = _selection_file()
    held = [c for c in selection["cases"] if c["held_out"]]
    assert len(held) >= 10
    for entry in selection["cases"]:
        assert entry["held_out"] == (not entry["tuned_by_question_policy"])
    assert sum(1 for c in selection["cases"] if c["f18"]) == 1  # its own stratum


def test_the_case_cluster_interval_is_seeded_and_reproducible(
    totals: ModuleType,
) -> None:
    o = {f"c{i}": "PPP" if i < 8 else "FFF" for i in range(20)}
    a = {f"c{i}": "PFF" if i < 6 else "FFF" for i in range(20)}
    first, second = totals.bootstrap_gap(o, a), totals.bootstrap_gap(o, a)
    assert first == second and first["low"] <= first["high"]
    assert first["seed"] == totals.BOOTSTRAP_SEED and first["clusters"] == 20


def test_the_cli_exit_code_says_whether_there_was_a_decision(
    world: _World, capsys: pytest.CaptureFixture[str]
) -> None:
    a = _leg_dir(world.tmp, "cliA", _rows(12), arm="builder")
    o = _leg_dir(world.tmp, "cliO", _rows(24), arm="oracle")
    freeze = world.tmp / "freeze.json"
    freeze.write_text(json.dumps(world.freeze))
    argv = [
        "report",
        "--selection",
        str(world.selection_path),
        "--freeze",
        str(freeze),
        "--leg",
        f"A_luna6:builder:gpt-6-luna={a}",
        "--leg",
        f"O_luna6:oracle:gpt-6-luna={o}",
        "--format",
        "json",
    ]
    assert world.totals.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["decision"]["outcome"] == (
        "ADVANCE_EXPLORATORY_PILOT"
    )
    broken = _leg_dir(world.tmp, "cliB", _rows(24, invalid=7), arm="oracle")
    argv[-3] = f"O_luna6:oracle:gpt-6-luna={broken}"
    assert world.totals.main(argv) == 3


def _real_ids() -> list[str]:
    return [
        str(case["id"])
        for case in json.loads((_SCRIPTS / "ai_builder_oracle_cases.json").read_text())[
            "cases"
        ]
    ]


def _git(tree: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(tree), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture(scope="module")
def head_tree_base(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A git repository at HEAD holding this checkout's scripts, its `eneo`
    source (the scripts import it) and every doc source, committed as they are
    now: a frozen tree that does not depend on the state of the developer's
    worktree."""

    stage = importlib.import_module("ai_builder_oracle_stage")
    real = Path(__file__).resolve().parents[5]
    tree = tmp_path_factory.mktemp("frozen-tree")
    for part in ("scripts", "src"):
        shutil.copytree(
            real / "backend" / part,
            tree / "backend" / part,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    (tree / "backend" / "pyproject.toml").write_text("[project]\nname = 'frozen'\n")
    for relative in (doc for doc, _f, _l in stage.AUTHOR_DOCS):
        target = tree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(real / relative, target)
    _git(tree, "init", "-q")
    _git(tree, "add", "-A")
    _git(
        tree,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "commit",
        "-q",
        "-m",
        "frozen tree",
    )
    return tree


@pytest.fixture()
def head_tree(head_tree_base: Path) -> Any:
    """The frozen tree, restored to its commit after each test."""

    original = _git(head_tree_base, "rev-parse", "HEAD")
    yield head_tree_base
    _git(head_tree_base, "reset", "--hard", "-q", original)
    _git(head_tree_base, "clean", "-fdq")


def _stage_from(stage: ModuleType, tree: Path, material: Path) -> None:
    """The author brief for the 20 selected cases, staged from `tree` AS IT IS ON
    DISK (its corpus, fixtures and docs), which is what an author would be given."""

    scripts = tree / "backend" / "scripts"
    cases = stage.load_cases(scripts / "ai_builder_api_municipal_cases.json")
    for case_id in _real_ids():
        stage.stage_case(
            stage.request_material(cases[case_id]),
            material,
            fixtures=scripts / "fixtures" / "ai_builder_battle",
        )
    stage.stage_docs(material, repo=tree)


@pytest.fixture(scope="module")
def staged_base(head_tree_base: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    stage = importlib.import_module("ai_builder_oracle_stage")
    material = tmp_path_factory.mktemp("material-base") / "material"
    material.mkdir()
    _stage_from(stage, head_tree_base, material)
    return material


def _frozen_inputs(
    tmp_path: Path, tree: Path, staged_base: Path | None = None
) -> dict[str, Any]:
    """The tree, the author brief for the 20 selected cases and the specs'
    manifest that says it was authored from that brief."""

    stage = importlib.import_module("ai_builder_oracle_stage")
    selection = tmp_path / "selection.json"
    selection.write_text((_SCRIPTS / "ai_builder_oracle_cases.json").read_text())
    material = tmp_path / "material"
    if staged_base is not None:
        shutil.copytree(staged_base, material)
    else:
        material.mkdir()
        _stage_from(stage, tree, material)
    specs = tmp_path / "specs"
    specs.mkdir()
    _write_specs_manifest(stage, material, specs)
    return {
        "tree": tree,
        "selection": selection,
        "material": material,
        "specs": specs,
        "out": tmp_path / "freeze.json",
    }


def _write_specs_manifest(stage: ModuleType, material: Path, specs: Path) -> None:
    """The specs' manifest of an author who worked from `material` as it is now."""

    authoring = {
        "material_manifest_sha256": stage.material_digest(material, _real_ids()),
        "docs_manifest_sha256": stage.verify_docs(material),
    }
    (specs / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cases": {c: {"authoring": authoring} for c in _real_ids()},
            }
        )
    )


@pytest.fixture()
def stub_scorer_identity(
    totals: ModuleType, monkeypatch: pytest.MonkeyPatch, head_tree: Path
) -> tuple[int, str]:
    """The freeze environment of a frozen-tree test. The scorer identity is asked
    of a subprocess that imports the whole harness (several seconds); here it is
    answered in process, and the real subprocess is tested on this checkout in its
    own test. And this process loaded its code from the developer's checkout, not
    from the committed copy the test freezes, so the code the freeze sees is the
    process's own re-rooted into that copy (the path identity check itself is
    tested with code that really is another tree's)."""

    harness = sys.modules["ai_builder_api_battle_test"]
    identity = (harness.SCORER_SEMANTICS_VERSION, harness._scorer_sha256())
    monkeypatch.setattr(totals, "_tree_scorer_identity", lambda _tree: identity)
    _load_code_from(monkeypatch, head_tree)
    return identity


CHECKOUT = Path(__file__).resolve().parents[5]


def _load_code_from(monkeypatch: pytest.MonkeyPatch, tree: Path) -> None:
    """Make the freeze see this process's repository code as loaded from `tree`:
    what lives in this checkout is re-rooted into it; anything that lives
    elsewhere (another tree's module a test loaded) is left where it is."""

    def loaded() -> list[tuple[str, Path]]:
        found = []
        for name, path in _REAL_LOADED_CODE():
            try:
                found.append((name, tree / path.relative_to(CHECKOUT)))
            except ValueError:
                found.append((name, path))
        return found

    monkeypatch.setattr(code_identity_module, "loaded_code", loaded)


def _write_freeze(totals: ModuleType, inputs: dict[str, Any]) -> dict[str, Any]:
    return totals.write_freeze_record(
        out=inputs["out"],
        tree=inputs["tree"],
        h1_sha="1" * 40,
        selection_path=inputs["selection"],
        specs_dir=inputs["specs"],
        material_dir=inputs["material"],
        builder_model_id=BUILDER_MODEL,
    )


def test_the_scorer_identity_of_a_tree_is_its_own_harnesss(
    totals: ModuleType,
) -> None:
    harness = sys.modules["ai_builder_api_battle_test"]
    tree = Path(harness.__file__).resolve().parents[2]

    assert totals._tree_scorer_identity(tree) == (
        harness.SCORER_SEMANTICS_VERSION,
        harness._scorer_sha256(),
    )


def test_the_freeze_record_is_written_once_from_disk_and_satisfies_the_loader(
    totals: ModuleType,
    tmp_path: Path,
    head_tree: Path,
    staged_base: Path,
    stub_scorer_identity: tuple[int, str],
) -> None:
    inputs = _frozen_inputs(tmp_path, head_tree, staged_base)
    stage = importlib.import_module("ai_builder_oracle_stage")
    intake = importlib.import_module("ai_builder_intake_answers")

    record = _write_freeze(totals, inputs)

    loaded = totals.load_freeze(inputs["out"])
    scripts = head_tree / "backend" / "scripts"
    assert (
        loaded["harness_sha256"]
        == hashlib.sha256(
            (scripts / "ai_builder_api_battle_test.py").read_bytes()
        ).hexdigest()
    )
    assert (loaded["scorer_semantics_version"], loaded["scorer_sha256"]) == (
        stub_scorer_identity
    )
    assert loaded["scorer_source_revision"] == _git(head_tree, "rev-parse", "HEAD")
    assert (
        loaded["selection_sha256"]
        == hashlib.sha256(inputs["selection"].read_bytes()).hexdigest()
    )
    assert len(record["scorer_source_revision"]) == 40
    ids = _real_ids()
    assert set(loaded["intake_message_sha256_by_id"]) == set(ids)
    # The digests are the ones a Builder first message hashes to, for the real cases.
    case = stage.load_cases(_SCRIPTS / "ai_builder_api_municipal_cases.json")[ids[3]]
    assert (
        loaded["intake_message_sha256_by_id"][ids[3]]
        == hashlib.sha256(
            intake.intake_message(
                case.prompt, dict(case.configured_question_answers or {})
            ).encode()
        ).hexdigest()
    )
    assert loaded["material_manifest_sha256"] == stage.material_digest(
        inputs["material"], ids
    )
    with pytest.raises(FileExistsError):
        _write_freeze(totals, inputs)


def test_the_freeze_refuses_an_altered_brief_whatever_the_manifest_claims(
    totals: ModuleType,
    tmp_path: Path,
    head_tree: Path,
    staged_base: Path,
    stub_scorer_identity: tuple[int, str],
) -> None:
    stage = importlib.import_module("ai_builder_oracle_stage")
    inputs = _frozen_inputs(tmp_path, head_tree, staged_base)
    case_id = next(c for c in _real_ids() if c.startswith("mb_int09"))
    request = inputs["material"] / case_id / "request.md"
    request.write_text(request.read_text() + " Lägg till en extra rad.")

    with pytest.raises(
        stage.MaterialError, match=f"{case_id}.*differ from MATERIAL.json"
    ):
        _write_freeze(totals, inputs)
    assert not inputs["out"].exists()

    # Even with the manifest rewritten to match the new bytes, the brief is not
    # what the frozen corpus produces, and the freeze says so.
    manifest_path = inputs["material"] / case_id / "MATERIAL.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["request.md"] = hashlib.sha256(request.read_bytes()).hexdigest()
    manifest["intake_message_sha256"] = stage.staged_intake_sha256(
        request.read_bytes(), (inputs["material"] / case_id / "answers.md").read_bytes()
    )
    manifest_path.write_text(json.dumps(manifest))
    _write_specs_manifest(stage, inputs["material"], inputs["specs"])
    with pytest.raises(stage.MaterialError, match="not what the frozen corpus"):
        _write_freeze(totals, inputs)
    assert not inputs["out"].exists()


def test_the_freeze_refuses_a_replaced_attachment_rendering_with_every_declaration_updated(
    totals: ModuleType,
    tmp_path: Path,
    head_tree: Path,
    staged_base: Path,
    stub_scorer_identity: tuple[int, str],
) -> None:
    """Sol round 4, F2: the staged tree agreeing with its own manifests, and the
    specs' manifest agreeing with those, proves nothing about where the bytes
    came from. The attachment's text rendering is what an author reads."""

    stage = importlib.import_module("ai_builder_oracle_stage")
    inputs = _frozen_inputs(tmp_path, head_tree, staged_base)
    case_id = "mc_int12_tjansteskrivelse"
    case_dir = inputs["material"] / case_id
    rendering = case_dir / "attachments" / "int12_mall_tjansteskrivelse_bun.docx.txt"
    rendering.write_text(rendering.read_text() + "\nHemlig ledtråd om rätt svar.")
    manifest_path = case_dir / "MATERIAL.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["attachments/int12_mall_tjansteskrivelse_bun.docx.txt"] = (
        hashlib.sha256(rendering.read_bytes()).hexdigest()
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True)
    )
    _write_specs_manifest(stage, inputs["material"], inputs["specs"])
    # Every self-consistency check the freeze had passes ...
    stage.verify_staged_case(case_dir)
    stage.verify_docs(inputs["material"])

    # ... and the source comparison refuses it, naming the file.
    with pytest.raises(
        stage.MaterialError, match="int12_mall_tjansteskrivelse_bun.docx.txt"
    ):
        _write_freeze(totals, inputs)
    assert not inputs["out"].exists()


def test_the_freeze_refuses_an_altered_doc_slice_with_every_declaration_updated(
    totals: ModuleType,
    tmp_path: Path,
    head_tree: Path,
    staged_base: Path,
    stub_scorer_identity: tuple[int, str],
) -> None:
    stage = importlib.import_module("ai_builder_oracle_stage")
    inputs = _frozen_inputs(tmp_path, head_tree, staged_base)
    docs = inputs["material"] / "docs"
    doc = next(p for p in sorted(docs.iterdir()) if p.name != "DOCS.json")
    doc.write_text(doc.read_text() + "\nEn rad som inte finns i dokumentationen.\n")
    listed = json.loads((docs / "DOCS.json").read_text())
    listed[doc.name] = hashlib.sha256(doc.read_bytes()).hexdigest()
    (docs / "DOCS.json").write_text(json.dumps(listed, indent=1, sort_keys=True))
    _write_specs_manifest(stage, inputs["material"], inputs["specs"])

    with pytest.raises(stage.MaterialError, match=doc.name):
        _write_freeze(totals, inputs)


def test_the_freeze_refuses_specs_authored_from_other_material(
    totals: ModuleType,
    tmp_path: Path,
    head_tree: Path,
    staged_base: Path,
    stub_scorer_identity: tuple[int, str],
) -> None:
    inputs = _frozen_inputs(tmp_path, head_tree, staged_base)
    manifest_path = inputs["specs"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    first = next(iter(manifest["cases"]))
    manifest["cases"][first]["authoring"]["material_manifest_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(totals.ExperimentError, match="not authored from this staged"):
        _write_freeze(totals, inputs)


# ------------- a decision leg must have measured a clean tracked source (round 3)


@pytest.mark.parametrize(
    "kwargs, needle",
    [
        ({"tracked_clean": False}, "dirty (or unknown) tracked source"),
        ({"tracked_clean": None}, "dirty (or unknown) tracked source"),
        # The bundle's own provenance says so too: the receipt reader refuses it.
        ({"bundle_clean": False}, "measured on a dirty tree"),
    ],
)
def test_a_decision_leg_whose_receipt_records_a_dirty_source_is_refused(
    world: _World, kwargs: dict[str, Any], needle: str
) -> None:
    """Commit gate round 3, P1(b): an exploratory suite (the case-id path) does
    not itself refuse a dirty tree, so the receipt says whether it was clean and
    a leg that was not, or does not say, cannot decide."""

    a, o = world.legs(o=24, a=12)
    assert world.decide([a, o])["outcome"] == "ADVANCE_EXPLORATORY_PILOT"  # control
    for label, arm, rows in (
        ("A_luna6", "builder", _rows(12)),
        ("O_luna6", "oracle", _rows(24)),
    ):
        dirty = _leg(world.totals, world.tmp, label, arm, rows, **kwargs)
        legs = [dirty, o] if label == "A_luna6" else [a, dirty]

        decision = world.decide(legs)

        assert decision["outcome"] == "NO_DECISION", (label, decision)
        assert any(label in p and needle in p for p in decision["problems"]), decision[
            "problems"
        ]

    # As the ORIGINAL of a re-run it does not make its replacement eligible.
    original = _leg_dir(
        world.tmp, "A-first", _rows(12, invalid=7), arm="builder", **kwargs
    )
    replacement, o2 = world.legs(o=24, a=12, a_kw={"created_at": "20260929T120000"})
    result = world.totals.report(
        _report_args(world, replacement, o2, rerun_of=[f"A_luna6={original}"])
    )
    assert result["decision"]["outcome"] == "NO_DECISION"
    assert any(
        "A_luna6 (original)" in p and needle in p
        for p in result["decision"]["problems"]
    )


# ---------- the source bytes are the recorded commit's (commit gate round 2, P1)


def _commit(tree: Path, message: str) -> None:
    _git(tree, "add", "-A")
    _git(
        tree,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "commit",
        "-q",
        "-m",
        message,
    )


def _dirty_source_case(head_tree: Path, kind: str) -> str:
    """Make the worktree differ from its HEAD in one way, uncommitted; the path
    the freeze must name."""

    if kind == "doc":
        # A line inside the first slice an author is given.
        relative = "docs/flows/flow-developer-quickstart.md"
        target = head_tree / relative
        lines = target.read_text().splitlines()
        lines[30] += " (en ändring som bara finns i arbetskopian)"
        target.write_text("\n".join(lines) + "\n")
    elif kind == "fixture":
        relative = "backend/scripts/fixtures/ai_builder_battle/int12_mall_tjansteskrivelse_bun.docx"
        target = head_tree / relative
        target.write_bytes(target.read_bytes() + b"\x00")
    elif kind == "corpus":
        relative = "backend/scripts/ai_builder_api_municipal_cases.json"
        target = head_tree / relative
        target.write_text(target.read_text().replace("Beslut", "Beslut ", 1))
    elif kind == "staging_script":
        relative = "backend/scripts/ai_builder_oracle_stage.py"
        target = head_tree / relative
        target.write_text(target.read_text() + "\n# a local edit\n")
    elif kind == "dynamic_module":
        # A table module `eneo.database.tables` imports by a computed name
        # (`import_module(module_name)`), which no scan of import statements sees.
        relative = "backend/src/eneo/database/tables/assistant_table.py"
        target = head_tree / relative
        target.write_text(target.read_text() + "\n# a local edit\n")
    elif kind == "staged_change":
        # A tracked file outside every source root, modified and staged.
        relative = "backend/pyproject.toml"
        (head_tree / relative).write_text("[project]\nname = 'edited'\n")
        _git(head_tree, "add", relative)
    elif kind == "untracked_in_src":
        relative = "backend/src/eneo/flows/a_local_helper.py"
        (head_tree / relative).write_text("VALUE = 1\n")
    elif kind == "untracked_fixture_dir":
        relative = "backend/scripts/fixtures/ai_builder_battle/extra_local.docx"
        (head_tree / relative).write_bytes(b"not committed")
    elif kind == "forgotten_doc":
        relative = "docs/flows/flow-developer-quickstart.md"
        _git(head_tree, "rm", "--cached", "-q", relative)
        _git(
            head_tree,
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "commit",
            "-q",
            "-m",
            "forget the doc",
        )
    else:
        raise AssertionError(kind)
    return relative


@pytest.mark.parametrize(
    "kind",
    [
        "doc",
        "fixture",
        "corpus",
        "staging_script",
        "dynamic_module",
        "staged_change",
        "untracked_in_src",
        "untracked_fixture_dir",
        "forgotten_doc",
    ],
)
def test_a_worktree_that_is_not_clean_at_head_is_refused_naming_the_path_even_when_staged_from(
    totals: ModuleType,
    tmp_path: Path,
    head_tree: Path,
    stub_scorer_identity: tuple[int, str],
    kind: str,
) -> None:
    """Commit gate rounds 2 to 4: the freeze records HEAD, so the tree it read
    must BE HEAD. A source edited in the worktree, staged from, authored against
    (every manifest and declaration agreeing) and frozen under a commit id that
    does not contain it would pass a regeneration that reads the same worktree;
    a dependency the code imports by a computed name would slip past any scan of
    import statements. The guard is the plain one: a tracked file changed anywhere,
    or an untracked file under a code or data root, refuses the freeze."""

    relative = _dirty_source_case(head_tree, kind)
    # The brief is staged from the tree AS IT IS ON DISK, so the staged bytes,
    # the manifests and the specs' declarations all agree with the edited source.
    inputs = _frozen_inputs(tmp_path, head_tree)

    with pytest.raises(totals.ExperimentError, match="not clean at HEAD") as info:
        _write_freeze(totals, inputs)

    assert relative in str(info.value)
    assert not inputs["out"].exists()


def test_a_clean_tree_passes_and_an_untracked_file_outside_the_source_roots_does_not_refuse(
    totals: ModuleType,
    tmp_path: Path,
    head_tree: Path,
    staged_base: Path,
    stub_scorer_identity: tuple[int, str],
) -> None:
    (head_tree / "scratch-notes.txt").write_text("not a source")
    (head_tree / "backend" / "local-run.log").write_text("not a source either")
    inputs = _frozen_inputs(tmp_path, head_tree, staged_base)

    record = _write_freeze(totals, inputs)

    assert record["scorer_source_revision"] == _git(head_tree, "rev-parse", "HEAD")
    assert inputs["out"].exists()
    assert set(totals.SOURCE_ROOTS) >= {
        "backend/src",
        "backend/scripts",
        "backend/tests/fixtures",
        "frontend/apps/docs-site/src",
    }


def test_code_loaded_from_another_checkout_is_refused_by_path_and_the_same_checkout_passes(
    totals: ModuleType,
    tmp_path: Path,
    head_tree: Path,
    head_tree_base: Path,
    stub_scorer_identity: tuple[int, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Commit gate round 5: two clean checkouts can hold equal scripts and
    different modules under them (here the question catalog an author's answers
    are rendered from). The freeze requires every loaded repository module to
    live inside the tree it freezes, by path, not by bytes."""

    other = tmp_path / "other-checkout"
    shutil.copytree(head_tree_base, other, symlinks=True)
    catalog = other / "backend/src/eneo/flows/ai_builder/question_catalog.py"
    catalog.write_text(
        catalog.read_text().replace(
            'label_sv="DOCX-dokument"', 'label_sv="DOCX-dokument (annan utcheckning)"'
        )
    )
    _commit(other, "another checkout's catalog")
    # This process loads THAT checkout's catalog, as a PYTHONPATH or an editable
    # install of it would.
    name = "eneo.flows.ai_builder.question_catalog"
    spec = importlib.util.spec_from_file_location(name, catalog)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)  # keep that tree clean
    spec.loader.exec_module(module)
    # The author's brief is staged with it: the answers carry its label.
    inputs = _frozen_inputs(tmp_path, other)
    assert any(
        "annan utcheckning" in path.read_text()
        for path in (inputs["material"]).glob("*/answers.md")
    )

    # `--tree` is a different (clean, committed) checkout: refused by path,
    # naming the foreign module.
    with pytest.raises(totals.ExperimentError, match="another checkout") as info:
        _write_freeze(totals, {**inputs, "tree": head_tree})
    assert str(catalog) in str(info.value)
    assert not inputs["out"].exists()

    # `--tree` is the checkout the code came from: passes.
    _load_code_from(monkeypatch, other)
    record = _write_freeze(totals, inputs)
    assert record["scorer_source_revision"] == _git(other, "rev-parse", "HEAD")
    assert inputs["out"].exists()


def test_the_selection_must_be_the_frozen_commits_own_file(
    totals: ModuleType,
    tmp_path: Path,
    head_tree: Path,
    staged_base: Path,
    stub_scorer_identity: tuple[int, str],
) -> None:
    inputs = _frozen_inputs(tmp_path, head_tree, staged_base)
    # The selection is the one input that need not live in the tree.
    inputs["selection"].write_text(inputs["selection"].read_text() + " ")

    with pytest.raises(totals.ExperimentError, match="ai_builder_oracle_cases.json"):
        _write_freeze(totals, inputs)


def test_a_directory_that_is_not_a_git_tree_cannot_be_frozen(
    totals: ModuleType,
    tmp_path: Path,
    head_tree: Path,
    staged_base: Path,
    stub_scorer_identity: tuple[int, str],
) -> None:
    inputs = {**_frozen_inputs(tmp_path, head_tree, staged_base), "tree": tmp_path}
    with pytest.raises(totals.ExperimentError, match="not a git worktree"):
        _write_freeze(totals, inputs)


def _report_args(
    world: _World,
    a: Any,
    o: Any,
    *,
    rerun_of: list[str] | None = None,
    evidence: list[str] | None = None,
) -> argparse.Namespace:
    freeze = world.tmp / "freeze.json"
    freeze.write_text(json.dumps(world.freeze))
    return argparse.Namespace(
        selection=str(world.selection_path),
        freeze=str(freeze),
        leg=[
            f"A_luna6:builder:gpt-6-luna={a.directory}",
            f"O_luna6:oracle:gpt-6-luna={o.directory}",
        ],
        rerun_of=rerun_of,
        evidence_leg=evidence,
        audit=None,
    )


def test_a_rerun_is_an_explicit_original_replacement_pair_and_both_are_reported(
    world: _World,
) -> None:
    # The first A receipt had 7 refused slots (over the cap of 6); the second is clean.
    first = _leg_dir(
        world.tmp,
        "A-first",
        _rows(12, invalid=7),
        arm="builder",
        created_at="20260929T100000",
    )
    a2, o = world.legs(o=24, a=12, a_kw={"created_at": "20260929T120000"})

    result = world.totals.report(
        _report_args(world, a2, o, rerun_of=[f"A_luna6={first}"])
    )

    assert result["decision"]["outcome"] == "ADVANCE_EXPLORATORY_PILOT"
    superseded = result["superseded_receipts"]["A_luna6 (original)"]
    assert superseded["invalid_evidence"] == 7 and superseded["fulfilled"] == 12
    text = world.totals.render_markdown(result)
    assert "A_luna6 (original)" in text  # the default report shows the first receipt


@pytest.mark.parametrize(
    "breakage, needle",
    [
        ("original_not_over_the_cap", "not eligible for a re-run"),
        ("two_reruns", "more than one re-run"),
        ("original_after_replacement", "not earlier than its replacement"),
        ("original_is_another_scorer", "not the frozen scorer's"),
        ("original_incomplete", "receipt is not complete"),
        ("original_is_the_replacement", "is the replacement's own receipt"),
        ("original_for_undecided_leg", "a leg that is not decided"),
    ],
)
def test_a_replacement_cannot_decide_unless_its_original_makes_it_eligible(
    world: _World, breakage: str, needle: str
) -> None:
    kw: dict[str, Any] = {"arm": "builder", "created_at": "20260929T100000"}
    rows = _rows(12, invalid=7)
    a2, o = world.legs(o=24, a=12, a_kw={"created_at": "20260929T120000"})
    original_dir = None
    if breakage == "original_not_over_the_cap":
        rows = _rows(12, invalid=6)  # exactly at the cap: eligible only above it
    elif breakage == "original_after_replacement":
        kw["created_at"] = "20260929T130000"
    elif breakage == "original_is_another_scorer":
        kw["harness"] = "x" * 64
    elif breakage == "original_incomplete":
        kw["integrity"] = "partial"
    elif breakage == "original_is_the_replacement":
        original_dir = str(a2.directory)
    original_dir = original_dir or _leg_dir(world.tmp, "A-first", rows, **kw)
    reruns = [f"A_luna6={original_dir}"]
    if breakage == "two_reruns":
        reruns.append(
            f"A_luna6={_leg_dir(world.tmp, 'A-second', _rows(12, invalid=7), arm='builder')}"
        )
    if breakage == "original_for_undecided_leg":
        reruns = [f"O_gemma={original_dir}"]
    args = _report_args(world, a2, o, rerun_of=reruns)

    if breakage == "original_for_undecided_leg":
        with pytest.raises(world.totals.ExperimentError, match="for a decision leg"):
            world.totals.report(args)
        return
    result = world.totals.report(args)

    assert result["decision"]["outcome"] == "NO_DECISION", result["decision"]
    assert any(needle in p for p in result["decision"]["problems"]), result["decision"][
        "problems"
    ]


def test_a_second_receipt_cannot_displace_a_valid_first_one_as_evidence(
    world: _World,
) -> None:
    """A valid first A receipt passed as `--evidence-leg` and a better second as `--leg`."""

    first_valid = _leg_dir(world.tmp, "A-first", _rows(3), arm="builder")
    a_better, o = world.legs(o=24, a=12, a_kw={"created_at": "20260929T120000"})

    result = world.totals.report(
        _report_args(
            world, a_better, o, evidence=[f"A_first:builder:gpt-6-luna={first_valid}"]
        )
    )

    assert result["decision"]["outcome"] == "NO_DECISION"
    assert any(
        "receipt of A_luna6's configuration" in p and "--rerun-of" in p
        for p in result["decision"]["problems"]
    )


def test_an_evidence_receipt_of_another_configuration_is_reported_and_never_decides(
    world: _World,
) -> None:
    a, o = world.legs(o=24, a=12)
    gemma_a = _leg_dir(
        world.tmp, "A-gemma", _rows(1), arm="builder", model="gemma4-31b-it"
    )

    result = world.totals.report(
        _report_args(
            world, a, o, evidence=[f"A_gemma_runtime:builder:gemma4-31b-it={gemma_a}"]
        )
    )

    assert result["decision"]["outcome"] == "ADVANCE_EXPLORATORY_PILOT"
    assert result["evidence_legs"]["A_gemma_runtime"]["fulfilled"] == 1
    assert "A_gemma_runtime (evidence, not decided on)" in world.totals.render_markdown(
        result
    )

    clash = world.totals.report(
        _report_args(world, a, o, evidence=[f"A_luna6:builder:gpt-6-luna={gemma_a}"])
    )
    assert clash["decision"]["outcome"] == "NO_DECISION"
    assert any("repeats a decision leg" in p for p in clash["decision"]["problems"])


# ------------------------------- a leg is read only through a verified receipt


def _edit_json(path: Path, edit: Any) -> None:
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))


def _flip_a_failed_row_to_pass(data: dict[str, Any]) -> None:
    """The summary alone claims a slot passed, with every count kept coherent."""

    row = next(r for r in data["results"] if r["verdict_states"]["output"] == "fail")
    row.update(
        output_success=True,
        expectation_verdict="met",
        verdict_states=_verdict_states("pass"),
    )
    data["observation_summary"]["state_counts"] = rcpt.verdict_state_counts(
        r["verdict_states"] for r in data["results"]
    )


def _drop_a_row(data: dict[str, Any]) -> None:
    data["results"].pop()
    data["observation_summary"]["state_counts"] = rcpt.verdict_state_counts(
        r["verdict_states"] for r in data["results"]
    )


def _tamper(directory: str, how: str) -> None:
    path = Path(directory)
    summary, manifest = path / "suite-summary.json", path / "release-manifest.json"
    if how == "bundle_bytes":
        bundle = next(path.glob("case-*-r*.json"))
        bundle.write_text(bundle.read_text().replace("Beslut", "Beslut om", 1))
    elif how == "bundle_deleted":
        next(path.glob("case-*-r*.json")).unlink()
    elif how == "summary_verdict":
        _edit_json(summary, _flip_a_failed_row_to_pass)
    elif how == "summary_row_dropped":
        _edit_json(summary, _drop_a_row)
    elif how == "summary_identity":
        _edit_json(
            summary,
            lambda d: d["evaluator_identity"]["run_context"].update(max_concurrency=1),
        )
    elif how == "summary_unreadable":
        summary.write_text("{not json")
    elif how == "manifest_missing":
        manifest.unlink()
    else:
        raise AssertionError(how)


@pytest.mark.parametrize(
    "how, needle",
    [
        ("bundle_bytes", "sha256_mismatch"),
        ("bundle_deleted", "missing_bundle"),
        ("summary_verdict", "disagrees with the observation sealed in its bundle"),
        ("summary_row_dropped", "not a complete record of its manifest"),
        ("summary_identity", "not two records of one run"),
        ("summary_unreadable", "could not be read"),
        ("manifest_missing", "could not be read"),
    ],
)
def test_a_tampered_receipt_is_refused_whole_and_the_decision_is_no_decision(
    world: _World, how: str, needle: str
) -> None:
    """Sol round 4, F1: a summary is the measured party's account of itself. A
    leg is read through the receipt reader's checks (manifest membership, bundle
    digests, the row equal to the observation its bundle sealed); one that fails
    is a leg with no rows, never a leg read from raw JSON."""

    a, o = world.legs(o=24, a=12)
    assert world.decide([a, o])["outcome"] == "ADVANCE_EXPLORATORY_PILOT"  # control
    tampered = _leg_dir(world.tmp, "A_luna6", _rows(12), arm="builder")
    _tamper(tampered, how)
    leg = world.totals.parse_leg(f"A_luna6:builder:gpt-6-luna={tampered}")

    assert leg.integrity_error is not None and needle in leg.integrity_error
    assert leg.rows == ()  # nothing of it is believed
    decision = world.decide([leg, o])
    assert decision["outcome"] == "NO_DECISION", decision
    assert any(
        "not an intact record of its run" in p and needle in p
        for p in decision["problems"]
    ), decision["problems"]
    # The report says so, per leg, and still reports the other leg's totals.
    result = world.totals.report(_report_args(world, leg, o))
    assert result["decision"]["outcome"] == "NO_DECISION"
    assert result["totals"]["A_luna6"]["attempted"] == 0
    assert needle in result["totals"]["A_luna6"]["receipt_integrity_error"]
    assert "RECEIPT REFUSED" in world.totals.render_markdown(result)


def test_a_tampered_bundle_is_never_read_for_the_runtime_scan_or_the_audit(
    world: _World,
) -> None:
    """The bytes verified are the bytes used: a bundle changed after the leg was
    read is refused at the moment it is read again."""

    a, _ = world.legs(o=24, a=12)
    bundle = a.directory / str(a.rows[0]["bundle_file"])
    bundle.write_text(bundle.read_text().replace("Beslut", "Beslut om", 1))

    with pytest.raises(
        world.totals.ExperimentError, match="not the bundle the receipt"
    ):
        world.totals.leg_bundle(a, a.rows[0])


def test_the_real_receipt_of_a_suite_passes_the_reader_and_a_tampered_one_does_not(
    world: _World,
) -> None:
    good = _leg_dir(world.tmp, "A_luna6", _rows(12), arm="builder")
    assert world.totals.verified_receipt(Path(good)).observations
    _tamper(good, "summary_verdict")
    # The module the totals script reads with (other test files reload the
    # receipt module, so the class is asked of the script, not imported here).
    with pytest.raises(
        world.totals.receipt.ReceiptError, match="disagrees with the observation"
    ):
        world.totals.verified_receipt(Path(good))


# ------------------------------ the decision reads the scorer's output verdict


def test_a_row_without_a_valid_output_verdict_is_an_invalid_slot_not_the_legacy_success(
    totals: ModuleType,
) -> None:
    """Sol round 4, F5: no fallback to `output_success`. This is the slot-level
    guard, defence in depth: for a receipt that records its scorer identity the
    reader refuses such a row as a whole-receipt integrity error before any slot
    is classified (`test_a_frozen_h1_receipt_without_valid_verdict_states_is_
    refused_whole_not_counted_invalid`), so these rows reach `slot_state` only in
    a receipt without a scorer identity, or with a `not_required` output."""

    legacy = {
        "observation_status": "completed",
        "output_executed": True,
        "output_success": True,
    }
    assert totals.slot_state(legacy) == "invalid"
    assert totals.invalid_class(legacy) == "verdict_states_missing"
    for bad in (
        {"plan": "pass", "case": "pass"},  # no output dimension
        {"plan": "pass", "output": "banana", "case": "pass"},
        {"plan": "pass", "output": None, "case": "pass"},
        {"plan": "pass", "output": "not_required", "case": "pass"},  # a selected
        # case always requires an output
    ):
        row = {**legacy, "verdict_states": bad}
        assert totals.slot_state(row) == "invalid", bad
        assert totals.invalid_class(row) == "verdict_states_invalid"
    assert totals.slot_state({**legacy, "verdict_states": "pass"}) == "invalid"


def test_an_output_that_the_case_does_not_require_is_an_invalid_slot_not_a_pass(
    world: _World,
) -> None:
    """The one malformed-looking verdict the reader accepts (`not_required` is a
    valid state): a selected case always executes, so it is not fulfilment."""

    rows = _rows(12)
    rows[0] = _row(rows[0]["case_id"], rows[0]["repetition"], "no_output")
    leg = _leg(world.totals, world.tmp, "A_luna6", "builder", rows)

    assert leg.integrity_error is None
    assert world.totals.slot_state(leg.rows[0]) == "invalid"
    totals = world.totals.leg_totals(leg, {})
    assert totals["invalid_by_class"] == {"verdict_states_invalid": 1}
    assert totals["fulfilled"] == 11


def test_a_leg_of_rows_without_verdict_states_counts_none_fulfilled_and_cannot_decide(
    world: _World,
) -> None:
    """A receipt from a scorer that recorded no identity is readable (nothing
    requires states of it), every row is an invalid slot, and the frozen scorer
    identity refuses it in a decision leg anyway."""

    old = _leg(world.totals, world.tmp, "A_luna6", "builder", _rows(12), legacy=True)
    o = _leg(world.totals, world.tmp, "O_luna6", "oracle", _rows(24))

    totals = world.totals.leg_totals(old, {})
    assert totals["fulfilled"] == 0 and totals["invalid_evidence"] == 60
    assert totals["invalid_by_class"] == {"verdict_states_missing": 60}
    decision = world.decide([old, o])
    assert decision["outcome"] == "NO_DECISION"
    assert any("not the frozen scorer's" in p for p in decision["problems"])
    assert any("60 invalid slots" in p for p in decision["problems"])


def _damage_verdicts(directory: str, how: str) -> None:
    path = Path(directory)
    summary = path / "suite-summary.json"

    def edit(data: dict[str, Any]) -> None:
        results = data["results"]
        failed = next(r for r in results if r["verdict_states"]["output"] == "fail")
        if how == "stripped_row":
            del results[0]["verdict_states"]
        elif how == "unknown_state":
            results[0]["verdict_states"]["output"] = "banana"
        elif how == "missing_dimension":
            del results[0]["verdict_states"]["review_edit"]
        elif how == "case_contradicts":
            failed["verdict_states"]["case"] = "pass"
        elif how == "counts_do_not_follow":
            data["observation_summary"]["state_counts"]["output"]["pass"] += 1
        else:
            raise AssertionError(how)

    _edit_json(summary, edit)


def _strip_verdicts_coherently(directory: str) -> None:
    """The forgery a careful tamperer would make: no verdict states anywhere, in
    the rows AND in every bundle's sealed observation, with each digest updated."""

    path = Path(directory)
    digests: dict[str, str] = {}
    for bundle in path.glob("case-*-r*.json"):
        body = json.loads(bundle.read_text())
        body["observation"].pop("verdict_states", None)
        data = json.dumps(body).encode()
        bundle.write_bytes(data)
        digests[bundle.name] = hashlib.sha256(data).hexdigest()

    def edit(data: dict[str, Any]) -> None:
        for row in data["results"]:
            row.pop("verdict_states", None)
            row["bundle_sha256"] = digests[row["bundle_file"]]

    _edit_json(path / "suite-summary.json", edit)


@pytest.mark.parametrize(
    "how, needle",
    [
        ("stripped_row", "verdict_states is required"),
        ("coherent_forgery", "verdict_states is required"),
        ("unknown_state", "is not one of"),
        ("missing_dimension", "must name exactly"),
        ("case_contradicts", "contradicts its dimensions"),
        ("counts_do_not_follow", "do not follow the rows"),
    ],
)
def test_a_frozen_h1_receipt_without_valid_verdict_states_is_refused_whole_not_counted_invalid(
    world: _World, how: str, needle: str
) -> None:
    """Commit gate round 2, P2: the real path. A scorer that recorded its identity
    (the frozen H1 scorer, which every decision leg must carry) states a verdict
    for every row; the receipt reader refuses the whole receipt otherwise, so the
    leg is an integrity error and the decision NO_DECISION. It is never a leg of
    'invalid slots' (which would count toward the cap and could be re-run)."""

    a, o = world.legs(o=24, a=12)
    directory = _leg_dir(world.tmp, "A_luna6", _rows(12), arm="builder")
    if how == "coherent_forgery":
        _strip_verdicts_coherently(directory)
    else:
        _damage_verdicts(directory, how)
    leg = world.totals.parse_leg(f"A_luna6:builder:gpt-6-luna={directory}")

    assert leg.integrity_error is not None and needle in leg.integrity_error
    assert leg.rows == ()
    decision = world.decide([leg, o])
    assert decision["outcome"] == "NO_DECISION"
    assert any("not an intact record of its run" in p for p in decision["problems"])
    assert not any("invalid slots" in p for p in decision["problems"])
    totals = world.totals.report(_report_args(world, leg, o))["totals"]["A_luna6"]
    assert totals["attempted"] == 0 and totals["invalid_by_class"] == {}

    # As the ORIGINAL of a re-run it is a refused receipt, not one "over the cap".
    replacement, _ = world.legs(o=24, a=12, a_kw={"created_at": "20260929T120000"})
    result = world.totals.report(
        _report_args(world, replacement, o, rerun_of=[f"A_luna6={directory}"])
    )
    assert result["decision"]["outcome"] == "NO_DECISION"
    assert any(
        "A_luna6 (original)" in p and "not an intact record" in p
        for p in result["decision"]["problems"]
    )


# ------------------------- evidence legs are what their labels say they are


@pytest.mark.parametrize(
    "label, needle",
    [
        (
            "A_first:builder:gemma4-31b-it",
            "steps ran on ['gpt-6-luna'], not gemma4-31b-it",
        ),
        (
            "A_first:oracle:gpt-6-luna",
            "declared arm oracle but the receipt says builder",
        ),
    ],
)
def test_a_mislabelled_evidence_leg_is_refused_before_any_configuration_comparison(
    world: _World, label: str, needle: str
) -> None:
    """Sol round 4, F3: a valid first A receipt labelled as another
    configuration must not slip past the duplicate-configuration guard while a
    second A receipt decides."""

    first_valid = _leg_dir(world.tmp, "A-first", _rows(3), arm="builder")
    a_better, o = world.legs(o=24, a=12, a_kw={"created_at": "20260929T120000"})

    result = world.totals.report(
        _report_args(world, a_better, o, evidence=[f"{label}={first_valid}"])
    )

    assert result["decision"]["outcome"] == "NO_DECISION"
    problems = result["decision"]["problems"]
    assert any(needle in p and "evidence receipt A_first" in p for p in problems), (
        problems
    )
    # The configuration it measured is read from the receipt, so the receipt is
    # also recognised as A_luna6's own configuration, whatever the label says.
    assert any("receipt of A_luna6's configuration" in p for p in problems), problems


def test_an_evidence_leg_with_a_tampered_receipt_is_refused(world: _World) -> None:
    a, o = world.legs(o=24, a=12)
    evidence = _leg_dir(
        world.tmp, "A-gemma", _rows(1), arm="builder", model="gemma4-31b-it"
    )
    _tamper(evidence, "bundle_bytes")

    result = world.totals.report(
        _report_args(
            world, a, o, evidence=[f"A_gemma:builder:gemma4-31b-it={evidence}"]
        )
    )

    assert result["decision"]["outcome"] == "NO_DECISION"
    assert any(
        "evidence receipt A_gemma" in p and "not an intact record" in p
        for p in result["decision"]["problems"]
    )


def test_a_dirty_evidence_receipt_is_reported_as_refused_evidence_and_never_decides(
    world: _World,
) -> None:
    """Commit gate round 4: the same source-state check as a decision leg. A
    receipt that records a dirty (or unknown) tracked source is not evidence of
    any commit: it is listed apart as refused, left out of the evidence totals,
    and does not touch the decision."""

    a, o = world.legs(o=24, a=12)
    dirty = _leg_dir(world.tmp, "A-dirty", _rows(3), arm="builder", tracked_clean=False)
    unknown = _leg_dir(
        world.tmp, "A-unknown", _rows(3), arm="builder", tracked_clean=None
    )
    gemma = _leg_dir(
        world.tmp, "A-gemma", _rows(1), arm="builder", model="gemma4-31b-it"
    )

    result = world.totals.report(
        _report_args(
            world,
            a,
            o,
            evidence=[
                f"A_dirty:builder:gpt-6-luna={dirty}",
                f"A_unknown:builder:gpt-6-luna={unknown}",
                f"A_gemma:builder:gemma4-31b-it={gemma}",
            ],
        )
    )

    assert result["decision"]["outcome"] == "ADVANCE_EXPLORATORY_PILOT"
    assert set(result["refused_evidence"]) == {"A_dirty", "A_unknown"}
    assert set(result["evidence_legs"]) == {"A_gemma"}  # the clean one is evidence
    text = world.totals.render_markdown(result)
    assert "Refused evidence receipt A_dirty (never decided on)" in text
    assert "dirty (or unknown) tracked source" in text


# ---------------------------------------- the runtime model of every attempt


def _attempt(**changes: Any) -> dict[str, Any]:
    return {
        "id": "a",
        "status": "completed",
        "requested_model": "gpt-6-luna",
        "response_model": "gpt-6-luna",
        "provider": "openai",
        "num_tokens_input": 10,
        **changes,
    }


def test_a_completed_model_attempt_with_no_actual_model_makes_its_slot_invalid(
    totals: ModuleType, tmp_path: Path
) -> None:
    key = ("case-2", 1)
    attempts = {
        key: [
            _attempt(id="ok"),  # a correctly labelled attempt in the same run
            _attempt(id="unknown", response_model=None),  # the actual model is null
        ],
        ("case-3", 1): [
            _attempt(id="ok"),
            # A canned step: completed, no model, no call. Not a model attempt.
            _attempt(
                id="canned",
                requested_model=None,
                response_model=None,
                provider=None,
                num_tokens_input=0,
            ),
        ],
        ("case-4", 1): [
            _attempt(id="ok"),
            # A failed attempt with no model does not invalidate the slot.
            _attempt(id="failed", status="failed", response_model=None),
        ],
        ("case-5", 1): [
            _attempt(id="ok"),
            # No requested model either, but a trace of a call (tokens): a model attempt.
            _attempt(id="blank", requested_model="", response_model=None),
        ],
    }
    leg = _leg(totals, tmp_path, "A_luna6", "builder", _rows(12), attempts=attempts)

    states = {
        (r["case_id"], r["repetition"]): totals.leg_state(leg, r) for r in leg.rows
    }
    assert states[key] == "invalid"
    assert states[("case-5", 1)] == "invalid"
    assert states[("case-3", 1)] != "invalid" and states[("case-4", 1)] != "invalid"
    scan = totals.runtime_models(leg)
    assert scan["unknown_model_slots"] == [("case-2", 1), ("case-5", 1)]
    assert scan["mismatch"] == []  # the models it did name are the declared one

    result = totals.leg_totals(leg, {})
    assert result["invalid_evidence"] == 2
    assert result["invalid_by_class"] == {"runtime_model_unknown": 2}
    # The slot is not silently skipped: it stays in the attempted total.
    assert result["attempted"] == 60


def test_seven_slots_with_an_unknown_actual_model_take_a_leg_past_the_invalid_cap(
    world: _World,
) -> None:
    attempts = {(f"case-{i}", 1): [_attempt(response_model=None)] for i in range(1, 8)}
    a = _leg(
        world.totals, world.tmp, "A_luna6", "builder", _rows(12), attempts=attempts
    )
    o = _leg(world.totals, world.tmp, "O_luna6", "oracle", _rows(24))

    decision = world.decide([a, o])

    assert decision["outcome"] == "NO_DECISION"
    assert any("7 invalid slots" in p for p in decision["problems"])
    six = {(f"case-{i}", 1): [_attempt(response_model=None)] for i in range(1, 7)}
    a6 = _leg(world.totals, world.tmp, "A_luna6", "builder", _rows(12), attempts=six)
    assert world.decide([a6, o])["outcome"] == "ADVANCE_EXPLORATORY_PILOT"


def test_an_unknown_model_slot_is_never_audited_into_fulfilment(
    totals: ModuleType, tmp_path: Path
) -> None:
    texts = {("case-0", r): "Beslut om bygglov." for r in (1, 2, 3)}
    slots = [(c, r) for r in (1, 2, 3) for c in CASES]
    rows = [_row(c, r, "failed" if c == "case-0" else "pass") for c, r in slots]
    attempts = {("case-0", 1): [_attempt(response_model=None)]}
    leg = _leg(
        totals, tmp_path, "A_luna6", "builder", rows, texts=texts, attempts=attempts
    )
    both = _audit(
        totals,
        tmp_path,
        _correction(),
        _correction(check={"name": "required_fact", "fact": "IAN-1"}),
    )

    audit = totals.audited_states(leg, both)

    assert ("case-0", 1) not in audit  # invalid slots are neither lifted nor dropped
    assert {k for k, v in audit.items() if v == "lifted"} == {
        ("case-0", 2),
        ("case-0", 3),
    }


def test_an_invalid_experiment_is_reported_raw_and_never_re_scored(
    world: _World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The audit runs once, after validation: a broken experiment costs no re-scoring."""

    a, o = world.legs(o=24, a=12, o_kw={"harness": "x" * 64})
    freeze = tmp_path / "freeze.json"
    freeze.write_text(json.dumps(world.freeze))
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"corrections": [_correction()]}))

    def never(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the audit must not run for an invalid experiment")

    monkeypatch.setattr(world.totals, "audited_states", never)
    result = world.totals.report(
        argparse.Namespace(
            selection=str(world.selection_path),
            freeze=str(freeze),
            leg=[
                f"A_luna6:builder:gpt-6-luna={a.directory}",
                f"O_luna6:oracle:gpt-6-luna={o.directory}",
            ],
            audit=str(audit),
        )
    )
    assert result["decision"]["outcome"] == "NO_DECISION"
    assert result["totals"]["A_luna6"]["fulfilled"] == 12  # raw counts still shown


def test_the_selection_has_no_association_check_so_the_audit_needs_none() -> None:
    corpus = _corpus()
    for entry in _selection_file()["cases"]:
        assert not corpus[entry["id"]]["execution"]["expect"].get("associations")


PROBE_CASE = "mc_nar07_arbetsgivarintyg"
PROBE_FIELDS = {"bestallare_namn": "text", "anstallning": "text", "intygsdatum": "date"}


def _probe_suite(
    tmp_path: Path,
    name: str,
    *,
    plans: list[dict[str, str]] | None = None,
    asked: list[list[str]] | None = None,
    case_ids: list[str] | None = None,
    repetitions: list[int] | None = None,
    context: dict[str, Any] | None = None,
    target: dict[str, Any] | None = None,
    requested: str = BUILDER_MODEL,
    harness: str = HARNESS_SHA,
    integrity: str = "complete",
    tamper: bool = False,
    tracked_clean: bool | None = True,
) -> Path:
    """A Builder suite directory of the smoke: receipt, rows and sealed-looking bundles."""

    directory = tmp_path / name
    directory.mkdir()
    repetitions = repetitions or [1, 2, 3]
    plans = plans or [PROBE_FIELDS] * len(repetitions)
    asked = asked or [[]] * len(repetitions)
    case_ids = case_ids or [PROBE_CASE] * len(repetitions)
    answer = [
        {"value": {"name": n, "type": t, "label": n, "required": True, "options": []}}
        for n, t in PROBE_FIELDS.items()
    ]
    rows: list[dict[str, Any]] = []
    bodies: dict[tuple[str, int], dict[str, Any]] = {}
    for index, rep in enumerate(repetitions):
        row = _row(case_ids[index], rep, "pass")
        rows.append(row)
        bodies[(case_ids[index], rep)] = {
            "case": {
                "id": case_ids[index],
                "prompt": "Beställarens namn och personnummer, vilken anställning.",
                "configured_question_answers": {
                    "runtime_metadata_field_details": {"input_fields": answer}
                },
            },
            "plan": {
                "proposal": {
                    "spec": {
                        "form_fields": [
                            {"name": n, "type": t} for n, t in plans[index].items()
                        ]
                    }
                }
            },
            "event_summary": {"question_event_ids": asked[index]},
        }
    revision = SOURCE
    _write_receipt(
        directory,
        rows,
        bodies,
        run_context=context
        if context is not None
        else {
            "intake_answers": "upfront",
            "intake_answers_sha256_by_id": _intake_hashes(),
        },
        requested=requested,
        target=target
        or {
            "verified": True,
            "expected_source_revision": revision,
            "version": f"DEV-{revision[:12]}",
        },
        integrity=integrity,
        harness=harness,
        tracked_clean=tracked_clean,
    )
    if tamper:
        # A bundle altered after the receipt was written: the row's digest no longer holds.
        path = directory / rows[0]["bundle_file"]
        path.write_text(path.read_text().replace('"pass"', '"fail"', 1))
    return directory


@pytest.fixture()
def probe_freeze(totals: ModuleType) -> dict[str, Any]:
    return {
        "scorer_source_revision": SOURCE,
        "harness_sha256": HARNESS_SHA,
        "scorer_semantics_version": 1,
        "scorer_sha256": SCORER_SHA,
        "builder_model_id": BUILDER_MODEL,
        "intake_message_sha256_by_id": {
            PROBE_CASE: hashlib.sha256(PROBE_CASE.encode()).hexdigest()
        },
    }


def _probe_context(**changes: Any) -> dict[str, Any]:
    return {
        "intake_answers": "upfront",
        "intake_answers_sha256_by_id": {
            PROBE_CASE: hashlib.sha256(PROBE_CASE.encode()).hexdigest()
        },
        **changes,
    }


def test_the_builder_smoke_passes_on_the_one_receipt_it_is_defined_on(
    totals: ModuleType, tmp_path: Path, probe_freeze: dict[str, Any]
) -> None:
    suite = _probe_suite(tmp_path, "ok", context=_probe_context())

    outcome = totals.probe_builder_intake(suite, freeze=probe_freeze)

    assert outcome["refusals"] == [] and outcome["passed"] is True
    assert [r["repetition"] for r in outcome["results"]] == [1, 2, 3]
    # The names are ones the prompt does not contain: the answer was read.
    assert outcome["results"][0]["names_absent_from_prompt"] == [
        "anstallning",
        "bestallare_namn",
        "intygsdatum",
    ]


def test_the_smoke_fails_when_any_repetition_loses_the_prose_answer(
    totals: ModuleType, tmp_path: Path, probe_freeze: dict[str, Any]
) -> None:
    for name, plans, asked in (
        (
            "invented",
            [
                PROBE_FIELDS,
                {
                    "namn": "text",
                    **{k: v for k, v in PROBE_FIELDS.items() if k != "bestallare_namn"},
                },
                PROBE_FIELDS,
            ],
            None,
        ),
        (
            "type",
            [PROBE_FIELDS, PROBE_FIELDS, {**PROBE_FIELDS, "intygsdatum": "text"}],
            None,
        ),
        ("asked", None, [[], ["runtime_metadata_field_details"], []]),
    ):
        suite = _probe_suite(
            tmp_path, name, plans=plans, asked=asked, context=_probe_context()
        )
        outcome = totals.probe_builder_intake(suite, freeze=probe_freeze)
        assert outcome["refusals"] == []  # a valid receipt that shows prose was lost
        assert outcome["passed"] is False, name


@pytest.mark.parametrize(
    "kwargs, needle",
    [
        ({"repetitions": [1]}, "exactly 3 distinct repetitions"),
        ({"repetitions": [1, 1, 2]}, "not an intact record"),
        ({"repetitions": [1, 2, 4]}, "exactly 3 distinct repetitions"),
        (
            {"case_ids": [PROBE_CASE, PROBE_CASE, "mc_other"]},
            "exactly 3 distinct repetitions",
        ),
        ({"context": _probe_context(intake_answers="asked")}, "not given up front"),
        ({"context": {}}, "not given up front"),
        ({"context": _probe_context(arm="oracle")}, "not a Builder receipt"),
        (
            {
                "context": _probe_context(
                    intake_answers_sha256_by_id={PROBE_CASE: "0" * 64}
                )
            },
            "not the frozen author material",
        ),
        ({"requested": "model-other"}, "Builder model is not the frozen one"),
        ({"harness": "x" * 64}, "harness_sha256 is not the frozen scorer's"),
        ({"integrity": "partial"}, "does not claim to be complete"),
        ({"tamper": True}, "not an intact record"),
        ({"tracked_clean": False}, "dirty (or unknown) tracked source"),
        ({"tracked_clean": None}, "dirty (or unknown) tracked source"),
        (
            {
                "target": {
                    "verified": False,
                    "expected_source_revision": SOURCE,
                    "version": f"DEV-{SOURCE[:12]}",
                }
            },
            "deployed revision was not verified",
        ),
        (
            {
                "target": {
                    "verified": True,
                    "expected_source_revision": "0" * 40,
                    "version": "DEV-000000000000",
                }
            },
            "deployed revision was not verified",
        ),
    ],
)
def test_the_smoke_refuses_anything_but_one_complete_verified_upfront_three_repetition_receipt(
    totals: ModuleType,
    tmp_path: Path,
    probe_freeze: dict[str, Any],
    kwargs: dict[str, Any],
    needle: str,
) -> None:
    kwargs = {"context": _probe_context(), **kwargs}
    suite = _probe_suite(tmp_path, "refused", **kwargs)

    outcome = totals.probe_builder_intake(suite, freeze=probe_freeze)

    assert outcome["passed"] is False and outcome["results"] == []
    assert any(needle in r for r in outcome["refusals"]), outcome["refusals"]


def test_the_probe_is_defined_on_the_preregistered_case_only(
    totals: ModuleType,
    tmp_path: Path,
    probe_freeze: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Sol round 4, F4: there is no way to ask about another case."""

    other = "mc_other"
    suite = _probe_suite(
        tmp_path, "other", case_ids=[other] * 3, context=_probe_context()
    )
    freeze = {
        **probe_freeze,
        "intake_message_sha256_by_id": {
            PROBE_CASE: hashlib.sha256(PROBE_CASE.encode()).hexdigest(),
            other: hashlib.sha256(PROBE_CASE.encode()).hexdigest(),
        },
    }

    outcome = totals.probe_builder_intake(suite, freeze=freeze)

    assert outcome["passed"] is False and outcome["results"] == []
    assert any(PROBE_CASE in r for r in outcome["refusals"]), outcome["refusals"]
    with pytest.raises(TypeError):
        totals.probe_builder_intake(suite, freeze=freeze, case_id=other)
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(json.dumps(freeze))
    with pytest.raises(SystemExit):
        totals.main(
            [
                "intake-probe",
                "--suite",
                str(suite),
                "--freeze",
                str(freeze_path),
                "--case-id",
                other,
            ]
        )
    assert "--case-id" in capsys.readouterr().err


def test_one_matching_bundle_alone_can_no_longer_pass_the_smoke(
    totals: ModuleType, tmp_path: Path, probe_freeze: dict[str, Any]
) -> None:
    suite = _probe_suite(tmp_path, "single", repetitions=[1], context=_probe_context())
    outcome = totals.probe_builder_intake(suite, freeze=probe_freeze)
    assert outcome["passed"] is False
    assert outcome["refusals"]


def test_the_probe_command_exits_4_on_a_refusal_and_0_on_a_pass(
    totals: ModuleType,
    tmp_path: Path,
    probe_freeze: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    freeze = tmp_path / "freeze.json"
    freeze.write_text(
        json.dumps(
            {
                **probe_freeze,
                **{
                    k: "x" for k in totals.REQUIRED_FREEZE_KEYS if k not in probe_freeze
                },
            }
        )
    )
    good = _probe_suite(tmp_path, "good", context=_probe_context())
    bad = _probe_suite(tmp_path, "bad", repetitions=[1], context=_probe_context())

    assert (
        totals.main(["intake-probe", "--suite", str(good), "--freeze", str(freeze)])
        == 0
    )
    capsys.readouterr()
    assert (
        totals.main(["intake-probe", "--suite", str(bad), "--freeze", str(freeze)]) == 4
    )


# ------------------------------------- a scorer that states each dimension


def _states(plan: str, review_edit: str, output: str) -> dict[str, str]:
    return {"plan": plan, "review_edit": review_edit, "output": output, "case": "x"}


def test_a_row_is_read_by_its_final_output_verdict_when_the_scorer_states_one(
    totals: ModuleType,
) -> None:
    def row(output: str, *, executed: bool = True, **extra: Any) -> dict[str, Any]:
        return {
            "observation_status": "completed",
            "output_executed": executed,
            "output_success": None,
            "verdict_states": _states("pass", "not_required", output),
            **extra,
        }

    assert totals.slot_state(row("pass")) == "fulfilled"
    assert totals.slot_state(row("fail")) == "executed_not_fulfilled"
    # Executed, and the harness could not judge the output: never a pass or a
    # quiet failure; the slot is invalid and counts toward the cap.
    assert totals.slot_state(row("unmeasured")) == "invalid"
    assert totals.invalid_class(row("unmeasured")) == "output_unmeasured"
    # Nothing ran (a Builder that made no plan): not executed, not invalid.
    assert totals.slot_state(row("unmeasured", executed=False)) == "not_executed"
    # The row's own invalid statuses still win.
    assert (
        totals.slot_state(row("pass", observation_status="invalid_evidence"))
        == "invalid"
    )
    # A dimension is read as stated, whatever the legacy field says.
    assert (
        totals.slot_state(row("fail", output_success=True)) == "executed_not_fulfilled"
    )
