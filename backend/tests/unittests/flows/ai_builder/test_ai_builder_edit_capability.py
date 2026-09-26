"""The edit capability gate: sealed corpus, calibration, exact counts (eneo-e7h6)."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import eneo.database.tables  # noqa: E402,F401  (tables before the Builder modules)

gate = importlib.import_module("ai_builder_edit_capability")
receipts = importlib.import_module("ai_builder_receipt")
harness = importlib.import_module("ai_builder_api_battle_test")
SEED_G = harness._seed_flow_fixture_sha256("edit_seed_g.json")


def _run(text: str, **extra: Any) -> dict[str, Any]:
    """One calibration run of seed G as the writer keeps it: bounded evidence."""

    evidence = {
        "execution": {"outcome": "completed", "failures": []},
        "run": {"result": {"kind": "inline_text", "text": text}},
        "run_contract": {"final_output": {"output_type": "text"}},
        "final_artifact": {},
    }
    return {"evidence": evidence, "runtime_model_id": "model-1", **extra}


PASSING_RUN = _run("Ärende BAB-2026-0588: 57300 kr, beslut senast 2027-01-15.")

MANIFEST = {
    "cases_file": "ai_builder_api_edit_cases.json",
    "repetitions": 5,
    "calibration_runs": 3,
    "observation_deadline_seconds": 900,
    "cases": {"rename": "c-rename", "tone": "c-tone", "remove": "c-remove"},
}
COHORTS = {
    "rename": ("edit_capability", "edit_mechanical"),
    "tone": ("edit_capability", "edit_human"),
    "remove": ("edit_capability",),
}
IDENTITY = {"build": {"sha256": "b" * 64}, "target": {"sha256": "t" * 64}}
SUMMARY = {
    "run_context": {"observation_deadline_seconds": 900},
    "release_identity": IDENTITY,
    "space_id": "space-1",
}
CALIBRATION = {
    "release_identity": IDENTITY,
    "space_id": "space-1",
    "seeds": {"edit_seed_g.json": {"sha256": SEED_G, "runs": [PASSING_RUN] * 3}},
}


def _observations(**edits: dict[str, Any]) -> list[SimpleNamespace]:
    """Five passing repetitions per case; `edits` overrides one slot's verdict."""

    observations = []
    for case_id, contract in MANIFEST["cases"].items():
        for repetition in range(1, 6):
            verdict = {
                "verdict": "pass",
                "categories": (),
                "seed": "edit_seed_g.json"
                if case_id == "remove"
                else "edit_seed_a.json",
                "seed_sha256": SEED_G if case_id == "remove" else "seed-a",
                "executes": case_id == "remove",
                "runtime_model_id": "model-1",
                **edits.get(f"{case_id}_{repetition}", {}),
            }
            observations.append(
                SimpleNamespace(
                    case_id=case_id,
                    repetition=repetition,
                    cohorts=COHORTS[case_id],
                    case_contract_sha256=contract,
                    edit=receipts.EditVerdict(**verdict),
                )
            )
    return observations


def _report(
    observations: list[SimpleNamespace] | None = None,
    *,
    summary: dict[str, Any] = SUMMARY,
    calibration: dict[str, Any] | None = CALIBRATION,
) -> dict[str, Any]:
    return gate.edit_capability_report(
        observations=observations if observations is not None else _observations(),
        summary=summary,
        manifest=MANIFEST,
        calibration=calibration,
    )


def test_a_complete_calibrated_passing_corpus_passes_structurally_but_claims_nothing() -> (
    None
):
    report = _report()

    assert report["structural_verdict"] == "pass", report
    assert report["semantic"] == {"tone": "unmeasured"}
    assert report["overall_capability_claim"] is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"observations": [o for o in _observations() if o.case_id != "remove"]},
        {"observations": _observations()[:-1]},
        {
            "observations": [
                SimpleNamespace(**{**vars(o), "case_contract_sha256": "other"})
                for o in _observations()
            ]
        },
        {"summary": {**SUMMARY, "run_context": {"observation_deadline_seconds": 60}}},
        {"calibration": None},
        {
            "calibration": {
                **CALIBRATION,
                "release_identity": {**IDENTITY, "build": {"sha256": "x" * 64}},
            }
        },
        {
            "calibration": {
                **CALIBRATION,
                "release_identity": {**IDENTITY, "target": {"sha256": "x" * 64}},
            }
        },
        {"calibration": {**CALIBRATION, "space_id": "space-2"}},
        {
            "calibration": {
                **CALIBRATION,
                # A run whose kept evidence fails its facts, marked a success.
                "seeds": {
                    "edit_seed_g.json": {
                        "sha256": SEED_G,
                        "runs": [
                            PASSING_RUN,
                            _run(
                                "Ärende BAB-2026-0588: 12400 kr.", output_success=True
                            ),
                            PASSING_RUN,
                        ],
                    }
                },
            }
        },
        {"observations": _observations(tone_1={"runtime_model_id": "model-2"})},
        {"observations": _observations(tone_1={"verdict": "unmeasured"})},
    ],
    ids=[
        "missing-case",
        "missing-repetition",
        "changed-contract",
        "other-deadline",
        "no-calibration",
        "calibration-other-build",
        "calibration-other-target",
        "calibration-other-space",
        "calibration-altered-success",
        "mixed-runtime-models",
        "unmeasured",
    ],
)
def test_an_incomplete_or_unbound_receipt_cannot_pass(kwargs: dict[str, Any]) -> None:
    assert _report(**kwargs)["structural_verdict"] == "inconclusive"


@pytest.mark.parametrize(
    ("edits", "failure"),
    [
        (
            {"remove_1": {"verdict": "fail", "categories": ("dependency_loss",)}},
            "dependency_loss",
        ),
        # Every case keeps 4 of 5, but 9 of 10 pooled is below 95%.
        (
            {"tone_1": {"verdict": "fail", "categories": ("fulfilment",)}},
            "observed fulfilment 0.900",
        ),
        (
            {
                f"tone_{r}": {"verdict": "fail", "categories": ("fulfilment",)}
                for r in (1, 2)
            },
            "tone: 3 of 5 passed",
        ),
        (
            {"rename_1": {"verdict": "fail", "categories": ("fulfilment",)}},
            "mechanical requests",
        ),
    ],
    ids=[
        "one-dependency-loss",
        "pooled-below-floor",
        "three-of-five",
        "mechanical-four-of-five",
    ],
)
def test_exact_counts_decide_the_structural_verdict(
    edits: dict[str, Any], failure: str
) -> None:
    report = _report(_observations(**edits))

    assert report["structural_verdict"] == "fail"
    assert any(item.startswith(failure) for item in report["failures"]), report[
        "failures"
    ]


def test_the_manifest_seals_the_corpus_it_names() -> None:
    harness = importlib.import_module("ai_builder_api_battle_test")
    manifest = json.loads(gate.MANIFEST_FILE.read_text(encoding="utf-8"))
    cases = harness._read_cases_file(_SCRIPTS / manifest["cases_file"])

    sealed = {
        case.case_id: harness._case_contract_sha256(case)
        for case in cases
        if gate.CAPABILITY_COHORT in case.cohorts
    }

    assert sealed == manifest["cases"], "update the manifest in a reviewed change"
    assert all(case.required for case in cases if case.case_id in sealed)


def test_only_the_checked_in_manifest_can_seal_a_verdict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A subset that its own manifest would pass: one mechanical case.
    subset = [o for o in _observations() if o.case_id == "rename"]
    monkeypatch.setattr(
        gate,
        "load_release_receipt",
        lambda _suite_dir, cases_file: SimpleNamespace(
            observations=subset, summary=SUMMARY
        ),
    )
    custom = tmp_path / "subset-manifest.json"
    custom.write_text(json.dumps({**MANIFEST, "cases": {"rename": "c-rename"}}))

    with pytest.raises(SystemExit):
        gate.main([str(tmp_path), "--manifest", str(custom)])
    assert gate.main([str(tmp_path)]) == 1  # judged against the sealed corpus
