"""The edit capability gate (eneo-e7h6): a sealed, finite-corpus STRUCTURAL verdict.

Not the release gate: its Wilson interval is case-level and a 28-case corpus
cannot reach 95% even when perfect, so this gate states exact counts over a
pre-registered corpus instead. The corpus is sealed by
`ai_builder_edit_capability_manifest.json` (case ids, contract hashes,
repetitions, calibration runs, observation deadline); a subset, a changed
case, a different deadline or an uncalibrated seed cannot pass. The receipt
itself is verified by the one receipt owner (`load_release_receipt`) against
the edit corpus file the manifest names.

STRUCTURAL means scope, order, dependencies, postconditions and literal run
facts. Tone and plain language need a blinded human verdict; until one exists
they are unmeasured and no overall capability claim is made.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from ai_builder_edit_expectation import ZERO_CATEGORIES  # noqa: E402
from ai_builder_receipt import (  # noqa: E402
    Observation,
    ReceiptError,
    load_release_receipt,
)

JsonObject = dict[str, Any]

MANIFEST_FILE = Path(__file__).with_name("ai_builder_edit_capability_manifest.json")
CAPABILITY_COHORT = "edit_capability"
MECHANICAL_COHORT = "edit_mechanical"
HUMAN_COHORT = "edit_human"
# Pre-registered floors (edit-benchmark-design-astra.md); the only home of
# these numbers.
OBSERVED_FULFILMENT_FLOOR = 0.95
PER_CASE_PASS_FRACTION = 0.8  # 4 of 5


def edit_capability_report(
    *,
    observations: Sequence[Observation],
    summary: Mapping[str, Any],
    manifest: Mapping[str, Any],
    calibration: Mapping[str, Any] | None,
) -> JsonObject:
    """Judge one verified receipt against the sealed corpus and calibration."""

    inconclusive: list[str] = []
    failures: list[str] = []
    expected = cast(Mapping[str, str], manifest["cases"])
    repetitions = int(manifest["repetitions"])
    by_case: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        if CAPABILITY_COHORT in observation.cohorts:
            by_case[observation.case_id].append(observation)
    if set(by_case) != set(expected):
        inconclusive.append(
            f"corpus differs: missing {sorted(set(expected) - set(by_case))}, "
            f"extra {sorted(set(by_case) - set(expected))}"
        )
    for case_id, contract in expected.items():
        slots = by_case.get(case_id, [])
        if len(slots) != repetitions:
            inconclusive.append(f"{case_id}: {len(slots)} of {repetitions} repetitions")
        if any(slot.case_contract_sha256 != contract for slot in slots):
            inconclusive.append(f"{case_id}: contract differs from the manifest")
    run_context = cast(Mapping[str, Any], summary.get("run_context") or {})
    if (
        run_context.get("observation_deadline_seconds")
        != manifest["observation_deadline_seconds"]
    ):
        inconclusive.append("the run did not use the manifest's observation deadline")
    scored = [slot for slots in by_case.values() for slot in slots]
    unmeasured = sorted(
        f"{slot.case_id} r{slot.repetition}"
        for slot in scored
        if slot.edit is None or slot.edit.verdict not in {"pass", "fail"}
    )
    if unmeasured:
        inconclusive.append(f"unmeasured observations: {unmeasured}")
    edits = [slot.edit for slot in scored if slot.edit is not None]
    runtime_models = {edit.runtime_model_id for edit in edits}
    if len(runtime_models) > 1:
        inconclusive.append(f"mixed runtime models: {sorted(map(str, runtime_models))}")
    inconclusive.extend(
        _calibration_gaps(
            calibration=calibration,
            summary=summary,
            manifest=manifest,
            seeds={edit.seed: edit.seed_sha256 for edit in edits if edit.executes},
            runtime_model=next(iter(runtime_models), None),
        )
    )
    zero_rows = {
        category: sorted(
            f"{slot.case_id} r{slot.repetition}"
            for slot in scored
            if slot.edit is not None and category in slot.edit.categories
        )
        for category in ZERO_CATEGORIES
    }
    failures.extend(
        f"{category}: {slots}" for category, slots in zero_rows.items() if slots
    )
    passed = {
        (slot.case_id, slot.repetition): slot.edit is not None
        and slot.edit.verdict == "pass"
        for slot in scored
    }
    mechanical = {slot.case_id for slot in scored if MECHANICAL_COHORT in slot.cohorts}
    mechanical_failed = sorted(
        f"{case_id} r{repetition}"
        for (case_id, repetition), ok in passed.items()
        if case_id in mechanical and not ok
    )
    if mechanical_failed:
        failures.append(f"mechanical requests below 100%: {mechanical_failed}")
    other = {key: ok for key, ok in passed.items() if key[0] not in mechanical}
    pooled = sum(other.values()) / len(other) if other else None
    if pooled is not None and pooled < OBSERVED_FULFILMENT_FLOOR:
        failures.append(
            f"observed fulfilment {pooled:.3f} < {OBSERVED_FULFILMENT_FLOOR}"
        )
    per_case_floor = math.ceil(PER_CASE_PASS_FRACTION * repetitions)
    for case_id in sorted({key[0] for key in other}):
        count = sum(ok for (c, _), ok in other.items() if c == case_id)
        if count < per_case_floor:
            failures.append(
                f"{case_id}: {count} of {repetitions} passed (< {per_case_floor})"
            )
    verdict = "inconclusive" if inconclusive else ("fail" if failures else "pass")
    semantic = {
        slot.case_id: "unmeasured" for slot in scored if HUMAN_COHORT in slot.cohorts
    }
    return {
        "structural_verdict": verdict,
        "inconclusive": inconclusive,
        "failures": failures,
        "zero_rows": zero_rows,
        "observed_fulfilment": pooled,
        "semantic": dict(sorted(semantic.items())),
        # Tone and plain language have no automated verdict here.
        "overall_capability_claim": verdict == "pass" and not semantic,
    }


def _calibration_gaps(
    *,
    calibration: Mapping[str, Any] | None,
    summary: Mapping[str, Any],
    manifest: Mapping[str, Any],
    seeds: Mapping[str, str],
    runtime_model: object,
) -> list[str]:
    """Every executed seed passed its calibration on this build and target."""

    if not seeds:
        return []
    if calibration is None:
        return ["no seed calibration for the executed seeds"]
    ours = cast(Mapping[str, Any], calibration.get("release_identity") or {})
    theirs = cast(Mapping[str, Any], summary.get("release_identity") or {})
    gaps = [
        f"calibration {component} differs from the receipt"
        for component in ("build", "target")
        if not cast(Mapping[str, Any], ours.get(component) or {}).get("sha256")
        or cast(Mapping[str, Any], ours.get(component) or {}).get("sha256")
        != cast(Mapping[str, Any], theirs.get(component) or {}).get("sha256")
    ]
    if calibration.get("space_id") != summary.get("space_id"):
        gaps.append("calibration space differs from the receipt")
    # The output owner recomputes every run from its kept evidence, against
    # the checked-in seed's own calibration block; no recorded verdict counts.
    harness = importlib.import_module("ai_builder_api_battle_test")
    recorded = cast(Mapping[str, Mapping[str, Any]], calibration.get("seeds") or {})
    for seed, sha256 in sorted(seeds.items()):
        entry = recorded.get(seed) or {}
        runs = cast(list[Mapping[str, Any]], entry.get("runs") or [])
        if (
            entry.get("sha256") != sha256
            or harness._seed_flow_fixture_sha256(seed) != sha256
            or len(runs) < int(manifest["calibration_runs"])
            or not all(
                run.get("runtime_model_id") == runtime_model
                and harness.calibration_run_passed(
                    harness._load_seed_flow_fixture(seed),
                    cast(Mapping[str, Any], run.get("evidence") or {}),
                )
                for run in runs
            )
        ):
            gaps.append(
                f"seed {seed} has no passing calibration on these bytes and model"
            )
    return gaps


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite_dir", type=Path)
    parser.add_argument("--calibration", type=Path, default=None)
    args = parser.parse_args(argv)
    # Only the checked-in manifest can seal a verdict: a caller-supplied
    # corpus would let a subset pass as the gate.
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    try:
        receipt = load_release_receipt(
            args.suite_dir, cases_file=manifest["cases_file"]
        )
    except ReceiptError as error:
        print(f"receipt refused: {error}", file=sys.stderr)
        return 2
    report = edit_capability_report(
        observations=receipt.observations,
        summary=receipt.summary,
        manifest=manifest,
        calibration=(
            json.loads(args.calibration.read_text(encoding="utf-8"))
            if args.calibration
            else None
        ),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["structural_verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
