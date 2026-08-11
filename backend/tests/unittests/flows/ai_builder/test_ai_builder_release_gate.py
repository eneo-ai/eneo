"""Behavior tests for the release gate — the instrument that judges a build.

A wrong verdict here is worse than no verdict: it either ships a build that
was never measured to be releasable, or it blocks one that was. The cases
below are the ones the design brief froze, and each names the failure it
exists to prevent.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
_MATRIX_STATE = _SCRIPTS / "ai_builder_release_matrix_state.json"
_DERIVATION = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "eneo"
    / "flows"
    / "ai_builder"
    / "ai_builder_architecture_derivation.py"
)
_REVISION = "0" * 40
_ROW = "document_to_structured_report"


def _script(name: str) -> ModuleType:
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_RECEIPTS = _script("ai_builder_receipt")


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    return _script("ai_builder_release_gate")


@pytest.fixture(scope="module")
def receipts() -> ModuleType:
    return _RECEIPTS


def _tracked_digest(name: str) -> str:
    """The real digest of a tracked instrument input, as the harness records it."""

    return hashlib.sha256((_SCRIPTS / name).read_bytes()).hexdigest()


def _case_contract(case_id: str) -> dict[str, Any]:
    return {"id": case_id, "required": True, "prompt": f"prompt for {case_id}"}


def _provenance(revision: str) -> dict[str, Any]:
    """The identity a bundle seals with digests, as the harness writes it."""

    build = {
        "source_revision": revision,
        "harness_sha256": _tracked_digest(_RECEIPTS.HARNESS_FILE),
        "cases_sha256": _tracked_digest(_RECEIPTS.CASES_FILE),
    }
    model = {"requested_id": "model-under-test", "resolved_id": "model-under-test"}
    return {
        "source": {
            "revision": revision,
            "revision_sha256": hashlib.sha256(revision.encode()).hexdigest(),
            "tracked_clean": True,
        },
        "build": {**build, "sha256": _RECEIPTS.canonical_sha256(build)},
        "model": {**model, "sha256": _RECEIPTS.canonical_sha256(model)},
    }


def _observation(
    case_id: str,
    repetition: int,
    *,
    outcome: str = "plan_first_pass",
    verdict: str = "pass",
    repairs: int = 0,
    failed_checks: tuple[str, ...] = (),
    failure_codes: tuple[str, ...] = (),
    ladder_codes: tuple[str, ...] = (),
    patterns: tuple[str, ...] = (_ROW,),
    provider_disposition: str | None = None,
    status: str = "completed",
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "repetition": repetition,
        "required": True,
        "artifact_mode": "live_execution",
        "observation_status": status,
        "outcome_class": outcome,
        "expectation_verdict": verdict,
        "case_contract_sha256": _RECEIPTS.canonical_sha256(_case_contract(case_id)),
        _RECEIPTS.BUNDLE_FILE_FIELD: f"{case_id}-r{repetition}.json",
        _RECEIPTS.BUNDLE_SHA256_FIELD: hashlib.sha256(
            f"{case_id}-{repetition}".encode()
        ).hexdigest(),
        "failed_checks": [{"name": name} for name in failed_checks],
        "failure_summary": {
            "failure_codes": list(failure_codes),
            "error_details": (
                [{"details": {"provider_disposition": provider_disposition}}]
                if provider_disposition
                else []
            ),
        },
        "journey": {
            "outcome_class": outcome,
            "architecture": {"chosen_patterns": list(patterns)},
            "plan_outcome": {
                "repair_attempts": repairs,
                "attempt_failure_ladder": [{"failure_codes": list(ladder_codes)}],
            },
        },
        "authoring_usage": {
            "model_calls": 2,
            "total_tokens": 10_000,
            "elapsed_ms": 20_000,
        },
        "evidence_valid": True,
        "evidence_failed_check_count": 0,
        "identity_failed_check_count": 0,
        "identity_failed_checks": [],
    }


def _bundle_for(row: dict[str, Any], *, revision: str) -> dict[str, Any]:
    """The artifact the row is derived from, as `_suite_result` derives it."""

    return {
        "artifact_mode": row["artifact_mode"],
        "case_identity": {"id": row["case_id"]},
        "repetition": row["repetition"],
        "case_contract": _case_contract(str(row["case_id"])),
        "case_contract_sha256": row["case_contract_sha256"],
        "live_execution_provenance": {
            **_provenance(revision),
            "usage": row["authoring_usage"],
        },
        "journey": row["journey"],
        "failure_summary": row["failure_summary"],
        "quality_report": {
            "checks": [
                {"name": check["name"], "passed": False}
                for check in row["failed_checks"]
            ]
            + [{"name": "some_other_check", "passed": True}]
        },
        "observation": {
            key: value
            for key, value in row.items()
            if key not in _RECEIPTS.BUNDLE_REFERENCE_FIELDS
        },
    }


def _summary(
    rows: list[dict[str, Any]], *, revision: str = _REVISION
) -> dict[str, Any]:
    build = {
        "source_revision": revision,
        "harness_sha256": _tracked_digest(_RECEIPTS.HARNESS_FILE),
        "cases_sha256": _tracked_digest(_RECEIPTS.CASES_FILE),
    }
    model = {"requested_id": "model-under-test"}
    prompt_hashes = {
        str(row["case_id"]): hashlib.sha256(
            str(_case_contract(str(row["case_id"]))["prompt"]).encode()
        ).hexdigest()
        for row in rows
        if isinstance(row.get("case_id"), str)
    }
    target = {
        "expected_source_revision": revision,
        "verified": True,
    }
    release_identity = {
        "source": {
            "revision": revision,
            "revision_sha256": hashlib.sha256(revision.encode()).hexdigest(),
            "tracked_clean": True,
        },
        "model": {**model, "sha256": _RECEIPTS.canonical_sha256(model)},
        "build": {**build, "sha256": _RECEIPTS.canonical_sha256(build)},
        "prompts": {
            "case_sha256_by_id": prompt_hashes,
            "sha256": _RECEIPTS.canonical_sha256(prompt_hashes),
        },
        "target": target,
    }
    execution_failure_count = sum(
        row["observation_status"] == "execution_failure" for row in rows
    )
    invalid_evidence_count = sum(
        row["observation_status"] == "invalid_evidence" for row in rows
    )
    observation_identity_failure_count = sum(
        int(row["identity_failed_check_count"]) for row in rows
    )
    acquisition_checks = _RECEIPTS.acquisition_validity_checks(
        execution_failure_observation_count=execution_failure_count,
        invalid_evidence_observation_count=invalid_evidence_count,
    )
    sentinel = (
        "pass"
        if observation_identity_failure_count == 0
        and all(check["passed"] is True for check in acquisition_checks)
        else "fail"
    )
    return {
        "artifact_schema_version": "ai-builder-live-release.v5",
        "artifact_mode": "live_execution_summary",
        "repetitions": 5,
        "sentinel_verdict": sentinel,
        "execution_failure_observation_count": execution_failure_count,
        "invalid_evidence_observation_count": invalid_evidence_count,
        "identity_failed_check_count": observation_identity_failure_count,
        "suite_identity_failed_check_count": 0,
        "observation_identity_failed_check_count": (observation_identity_failure_count),
        "sentinel_acquisition_checks": acquisition_checks,
        "release_identity": release_identity,
        "release_identity_recheck": release_identity,
        "release_identity_recheck_checks": [
            {
                "name": f"suite_{component}_identity_unchanged",
                "passed": True,
                "actual": release_identity[component],
                "expected": release_identity[component],
            }
            for component in ("source", "build", "model", "prompts", "target")
        ]
        + [
            {
                "name": "suite_target_runtime_verified",
                "passed": True,
                "actual": target,
                "expected": "running backend version matches the local benchmark build",
            }
        ],
        "evaluator_identity": {"requested_model_id": "model-under-test"},
        "results": rows,
    }


def _perfect_rows(case_count: int = 10) -> list[dict[str, Any]]:
    return [
        _observation(f"case_{index}", repetition)
        for index in range(case_count)
        for repetition in range(1, 6)
    ]


def _suite_dir(
    tmp_path: Path, rows: list[dict[str, Any]], *, revision: str = _REVISION
) -> Path:
    """Write a receipt the way the harness writes one: bundles and manifest."""

    suite_dir = tmp_path / "ai-builder-api-battle-suite-test"
    suite_dir.mkdir(exist_ok=True, parents=True)
    summary = _summary(rows, revision=revision)
    for row in rows:
        bundle = suite_dir / str(row["bundle_file"])
        bundle.write_text(
            json.dumps(_bundle_for(row, revision=revision)), encoding="utf-8"
        )
        row["bundle_sha256"] = hashlib.sha256(bundle.read_bytes()).hexdigest()
    (suite_dir / "release-manifest.json").write_text(
        json.dumps(
            {
                "artifact_schema_version": summary["artifact_schema_version"],
                "release_identity": summary["release_identity"],
                "evaluator_identity": summary["evaluator_identity"],
                "expected_observations": [
                    {
                        "case_id": row["case_id"],
                        "repetition": row["repetition"],
                        "case_contract_sha256": row["case_contract_sha256"],
                    }
                    for row in rows
                ],
            }
        ),
        encoding="utf-8",
    )
    (suite_dir / "suite-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return suite_dir


def _write_replacements(
    suite_dir: Path,
    replacements: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    revision: str = _REVISION,
) -> None:
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    original_by_slot = {
        (row["case_id"], row["repetition"]): row for row in summary["results"]
    }
    descriptors: list[dict[str, Any]] = []
    for position, (replacement_row, overrides) in enumerate(replacements, start=1):
        case_id = str(replacement_row["case_id"])
        repetition = int(replacement_row["repetition"])
        bundle_path = suite_dir / f"replacement-{position}-{case_id}-r{repetition}.json"
        bundle = _bundle_for(replacement_row, revision=revision)
        bundle["artifact_schema_version"] = _RECEIPTS.SUPPORTED_RECEIPT_ARTIFACT_VERSION
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
        original = original_by_slot[(case_id, repetition)]
        descriptors.append(
            {
                "case_id": case_id,
                "repetition": repetition,
                "reason": "provider disposition in original observation",
                "original_bundle_sha256": original["bundle_sha256"],
                "replacement_bundle_sha256": hashlib.sha256(
                    bundle_path.read_bytes()
                ).hexdigest(),
                **overrides,
            }
        )
    (suite_dir / "replacements.json").write_text(
        json.dumps(descriptors), encoding="utf-8"
    )


def _rewrite_replacement_bundle(
    suite_dir: Path, mutate: Callable[[dict[str, Any]], None]
) -> None:
    bundle_path = next(suite_dir.glob("replacement-*.json"))
    bundle = json.loads(bundle_path.read_text())
    mutate(bundle)
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    descriptors = json.loads((suite_dir / "replacements.json").read_text())
    descriptors[0]["replacement_bundle_sha256"] = hashlib.sha256(
        bundle_path.read_bytes()
    ).hexdigest()
    (suite_dir / "replacements.json").write_text(
        json.dumps(descriptors), encoding="utf-8"
    )


def _matrix(
    gate: ModuleType,
    rows: dict[str, str] | None = None,
    modifiers: list[str] | None = None,
) -> Any:
    return gate.matrix_state_from_payload(
        {
            "artifact_schema_version": gate.MATRIX_STATE_SCHEMA_VERSION,
            "rows": rows or {_ROW: "supported"},
            "modifiers": modifiers or ["form_field_runtime_inputs"],
        },
        where="test matrix",
    )


def _pin(gate: ModuleType, *, revision: str = _REVISION, clean: bool = True) -> Any:
    return gate.EvaluatorPin(revision=revision, evaluator_tree_clean=clean)


def _receipt(receipts: ModuleType, rows: list[dict[str, Any]], **kwargs: Any) -> Any:
    return receipts.receipt_from_summary(
        _summary(rows, **kwargs), where="test receipt", integrity_verified=True
    )


def _evaluate(
    gate: ModuleType,
    receipts: ModuleType,
    rows: list[dict[str, Any]],
    *,
    matrix_rows: dict[str, str] | None = None,
    revision: str = _REVISION,
    pin_revision: str | None = None,
    evaluator_clean: bool = True,
) -> Any:
    return gate.evaluate(
        _receipt(receipts, rows, revision=revision),
        _matrix(gate, matrix_rows),
        _pin(gate, revision=pin_revision or revision, clean=evaluator_clean),
    )


def _row(verdict: Any, number: int) -> Any:
    return next(row for row in verdict.rows if row.number == number)


def test_a_flawless_run_is_a_go(gate: ModuleType, receipts: ModuleType) -> None:
    # 80 cases: below ~73 the Wilson bound on a perfect run cannot reach 95%,
    # which is the corpus-size limit CP0 recorded and the feasibility audit
    # exists to name.
    verdict = _evaluate(gate, receipts, _perfect_rows(80))
    assert verdict.receipt_valid
    assert verdict.release == "go"
    assert [row.verdict for row in verdict.rows if row.gating] == ["pass"] * 13


def test_adverse_clustering_is_inconclusive_not_a_pass(
    gate: ModuleType, receipts: ModuleType
) -> None:
    """CP0 finding 3, the worked counterexample.

    136 of 138 cases succeed in every repetition and 2 fail in every one:
    98.55% of ATTEMPTS, which sails past a 95% attempt-level bar. Treating
    cases as the independent unit refuses to call that a pass.
    """

    rows = [
        _observation(f"case_{index}", repetition)
        for index in range(136)
        for repetition in range(1, 6)
    ] + [
        _observation(f"dead_{index}", repetition, outcome="builder_error")
        for index in range(2)
        for repetition in range(1, 6)
    ]
    verdict = _evaluate(gate, receipts, rows)
    accepted = _row(verdict, 1)
    assert accepted.actual > gate.ACCEPTED_TARGET
    assert accepted.verdict == "inconclusive"
    assert verdict.release == "no_go"


def test_a_plan_with_an_error_event_is_still_an_accepted_plan(
    gate: ModuleType, receipts: ModuleType
) -> None:
    """CP0 row 1 is "plan produced", which the harness decides from has_plan.

    `plan_with_error` carries a plan the user received. Counting it as
    non-acceptance would measure a different thing than the inventory says.
    """

    rows = _perfect_rows(80)
    for row in rows[:40]:
        row["outcome_class"] = "plan_with_error"
    verdict = _evaluate(gate, receipts, rows)
    assert _row(verdict, 1).actual == 1.0
    assert _row(verdict, 2).actual == 0.9
    assert _row(verdict, 1).verdict == "pass"


def test_a_provider_marked_receipt_is_not_scored(
    gate: ModuleType, receipts: ModuleType
) -> None:
    """CP0 finding 4: provider faults are not product failures.

    Scoring one as a product outcome would charge the build for the
    provider's rate limit — and re-running the whole ~14M-token suite for it
    is not viable either, which is why the slot is re-measured (CP8c).
    """

    rows = _perfect_rows()
    rows[3] = _observation(
        "case_0",
        4,
        outcome="provider_outcome_unknown",
        status="error_terminated",
        provider_disposition="provider_outcome_unknown",
    )
    verdict = _evaluate(gate, receipts, rows)
    assert not verdict.receipt_valid
    assert verdict.release == "invalid"
    assert verdict.rows == ()
    assert any("provider disposition" in reason for reason in verdict.invalidity)


def test_a_valid_provider_slot_replacement_is_merged_and_counted(
    gate: ModuleType, receipts: ModuleType, tmp_path: Path
) -> None:
    rows = _perfect_rows(4)
    rows[0] = _observation(
        "case_0",
        1,
        outcome="provider_outcome_unknown",
        verdict="not_evaluated",
        provider_disposition="provider_outcome_unknown",
        status="error_terminated",
    )
    suite_dir = _suite_dir(tmp_path, rows)
    replacement = _observation("case_0", 1)
    _write_replacements(suite_dir, [(replacement, {})])

    receipt = receipts.load_release_receipt(suite_dir)
    verdict = gate.evaluate(receipt, _matrix(gate), _pin(gate))

    assert receipt.replaced_slots == (("case_0", 1),)
    assert receipt.observations[0].outcome_class == "plan_first_pass"
    assert verdict.receipt_valid
    assert verdict.diagnostics["replacement_count"] == 1
    assert verdict.diagnostics["replacement_limit"] == 1


def test_a_replacement_from_another_revision_is_refused(
    receipts: ModuleType, tmp_path: Path
) -> None:
    rows = _perfect_rows(4)
    rows[0] = _observation(
        "case_0",
        1,
        outcome="provider_outcome_unknown",
        verdict="not_evaluated",
        provider_disposition="provider_outcome_unknown",
        status="error_terminated",
    )
    suite_dir = _suite_dir(tmp_path, rows)
    _write_replacements(
        suite_dir,
        [(_observation("case_0", 1), {})],
        revision="e" * 40,
    )

    with pytest.raises(receipts.ReceiptError, match="was produced at"):
        receipts.load_release_receipt(suite_dir)


def test_a_replacement_measured_against_another_model_is_refused(
    receipts: ModuleType, tmp_path: Path
) -> None:
    rows = _perfect_rows(4)
    rows[0] = _observation(
        "case_0",
        1,
        outcome="provider_outcome_unknown",
        verdict="not_evaluated",
        provider_disposition="provider_outcome_unknown",
        status="error_terminated",
    )
    suite_dir = _suite_dir(tmp_path, rows)
    _write_replacements(suite_dir, [(_observation("case_0", 1), {})])

    def change_model(bundle: dict[str, Any]) -> None:
        model = {"requested_id": "some-other-model", "resolved_id": "other-model"}
        bundle["live_execution_provenance"]["model"] = {
            **model,
            "sha256": receipts.canonical_sha256(model),
        }

    _rewrite_replacement_bundle(suite_dir, change_model)

    with pytest.raises(receipts.ReceiptError, match="but the run declares"):
        receipts.load_release_receipt(suite_dir)


def test_replacing_more_than_five_percent_invalidates_the_receipt(
    gate: ModuleType, receipts: ModuleType, tmp_path: Path
) -> None:
    rows = _perfect_rows(4)
    for index in range(2):
        rows[index] = _observation(
            "case_0",
            index + 1,
            outcome="provider_outcome_unknown",
            verdict="not_evaluated",
            provider_disposition="provider_outcome_unknown",
            status="error_terminated",
        )
    suite_dir = _suite_dir(tmp_path, rows)
    _write_replacements(
        suite_dir,
        [(_observation("case_0", repetition), {}) for repetition in (1, 2)],
    )

    receipt = receipts.load_release_receipt(suite_dir)
    verdict = gate.evaluate(receipt, _matrix(gate), _pin(gate))

    assert verdict.release == "invalid"
    assert verdict.rows == ()
    assert verdict.diagnostics["replacement_count"] == 2
    assert verdict.diagnostics["replacement_limit"] == 1
    assert any("replacement" in reason for reason in verdict.invalidity)


def test_a_product_failure_cannot_be_rerolled_as_a_replacement(
    receipts: ModuleType, tmp_path: Path
) -> None:
    rows = _perfect_rows(4)
    rows[0] = _observation("case_0", 1, outcome="builder_error", verdict="fail")
    suite_dir = _suite_dir(tmp_path, rows)
    _write_replacements(suite_dir, [(_observation("case_0", 1), {})])

    with pytest.raises(receipts.ReceiptError, match="provider disposition"):
        receipts.load_release_receipt(suite_dir)


def test_a_replacement_with_a_sealed_identity_failure_is_refused(
    receipts: ModuleType, tmp_path: Path
) -> None:
    rows = _perfect_rows(4)
    rows[0] = _observation(
        "case_0",
        1,
        outcome="provider_outcome_unknown",
        verdict="not_evaluated",
        provider_disposition="provider_outcome_unknown",
        status="error_terminated",
    )
    suite_dir = _suite_dir(tmp_path, rows)
    replacement = _observation("case_0", 1)
    replacement["identity_failed_check_count"] = 1
    replacement["identity_failed_checks"] = [
        {
            "name": "suite_requested_model_identity",
            "passed": False,
            "actual": "other-model",
            "expected": "model-under-test",
        }
    ]
    _write_replacements(suite_dir, [(replacement, {})])

    with pytest.raises(receipts.ReceiptError, match="identity check"):
        receipts.load_release_receipt(suite_dir)


def test_a_replacement_acquisition_fault_is_not_scored(
    gate: ModuleType, receipts: ModuleType, tmp_path: Path
) -> None:
    rows = _perfect_rows(4)
    rows[0] = _observation(
        "case_0",
        1,
        outcome="provider_outcome_unknown",
        verdict="not_evaluated",
        provider_disposition="provider_outcome_unknown",
        status="error_terminated",
    )
    suite_dir = _suite_dir(tmp_path, rows)
    _write_replacements(
        suite_dir,
        [(_observation("case_0", 1, status="execution_failure"), {})],
    )

    receipt = receipts.load_release_receipt(suite_dir)
    verdict = gate.evaluate(receipt, _matrix(gate), _pin(gate))

    assert verdict.release == "invalid"
    assert verdict.rows == ()
    assert any("acquisition fault" in reason for reason in verdict.invalidity)


def test_a_replacement_must_seal_the_original_repetition(
    receipts: ModuleType, tmp_path: Path
) -> None:
    rows = _perfect_rows(4)
    rows[0] = _observation(
        "case_0",
        1,
        outcome="provider_outcome_unknown",
        verdict="not_evaluated",
        provider_disposition="provider_outcome_unknown",
        status="error_terminated",
    )
    suite_dir = _suite_dir(tmp_path, rows)
    _write_replacements(suite_dir, [(_observation("case_0", 1), {})])

    def change_repetition(bundle: dict[str, Any]) -> None:
        bundle["repetition"] = 2
        bundle["observation"]["repetition"] = 2

    _rewrite_replacement_bundle(suite_dir, change_repetition)

    with pytest.raises(receipts.ReceiptError, match="seals slot"):
        receipts.load_release_receipt(suite_dir)


def test_a_replacement_must_match_the_original_case_contract(
    receipts: ModuleType, tmp_path: Path
) -> None:
    rows = _perfect_rows(4)
    rows[0] = _observation(
        "case_0",
        1,
        outcome="provider_outcome_unknown",
        verdict="not_evaluated",
        provider_disposition="provider_outcome_unknown",
        status="error_terminated",
    )
    suite_dir = _suite_dir(tmp_path, rows)
    _write_replacements(suite_dir, [(_observation("case_0", 1), {})])

    def change_contract(bundle: dict[str, Any]) -> None:
        contract = {"id": "case_0", "required": True, "prompt": "changed"}
        digest = receipts.canonical_sha256(contract)
        bundle["case_contract"] = contract
        bundle["case_contract_sha256"] = digest
        bundle["observation"]["case_contract_sha256"] = digest

    _rewrite_replacement_bundle(suite_dir, change_contract)

    with pytest.raises(receipts.ReceiptError, match="case contract differs"):
        receipts.load_release_receipt(suite_dir)


def test_a_replacement_bundle_must_declare_the_v5_schema(
    receipts: ModuleType, tmp_path: Path
) -> None:
    rows = _perfect_rows(4)
    rows[0] = _observation(
        "case_0",
        1,
        outcome="provider_outcome_unknown",
        verdict="not_evaluated",
        provider_disposition="provider_outcome_unknown",
        status="error_terminated",
    )
    suite_dir = _suite_dir(tmp_path, rows)
    _write_replacements(suite_dir, [(_observation("case_0", 1), {})])
    _rewrite_replacement_bundle(
        suite_dir,
        lambda bundle: bundle.__setitem__(
            "artifact_schema_version", "ai-builder-live-release.v4"
        ),
    )

    with pytest.raises(receipts.ReceiptError, match="bundle schema"):
        receipts.load_release_receipt(suite_dir)


def test_duplicate_replacements_for_one_slot_are_invalid(
    receipts: ModuleType, tmp_path: Path
) -> None:
    rows = _perfect_rows(4)
    rows[0] = _observation(
        "case_0",
        1,
        outcome="provider_outcome_unknown",
        verdict="not_evaluated",
        provider_disposition="provider_outcome_unknown",
        status="error_terminated",
    )
    suite_dir = _suite_dir(tmp_path, rows)
    _write_replacements(suite_dir, [(_observation("case_0", 1), {})])
    path = suite_dir / "replacements.json"
    descriptors = json.loads(path.read_text())
    path.write_text(json.dumps([descriptors[0], descriptors[0]]), encoding="utf-8")

    with pytest.raises(receipts.ReceiptError, match="duplicate replacement"):
        receipts.load_release_receipt(suite_dir)


def test_a_replacement_reason_must_explain_the_operator_action(
    receipts: ModuleType, tmp_path: Path
) -> None:
    rows = _perfect_rows(4)
    rows[0] = _observation(
        "case_0",
        1,
        outcome="provider_outcome_unknown",
        verdict="not_evaluated",
        provider_disposition="provider_outcome_unknown",
        status="error_terminated",
    )
    suite_dir = _suite_dir(tmp_path, rows)
    _write_replacements(
        suite_dir,
        [(_observation("case_0", 1), {"reason": "   "})],
    )

    with pytest.raises(receipts.ReceiptError, match="reason must contain"):
        receipts.load_release_receipt(suite_dir)


def test_a_replacement_digest_must_resolve_to_one_unclaimed_sibling(
    receipts: ModuleType, tmp_path: Path
) -> None:
    rows = _perfect_rows(4)
    rows[0] = _observation(
        "case_0",
        1,
        outcome="provider_outcome_unknown",
        verdict="not_evaluated",
        provider_disposition="provider_outcome_unknown",
        status="error_terminated",
    )
    suite_dir = _suite_dir(tmp_path, rows)
    _write_replacements(suite_dir, [(_observation("case_0", 1), {})])
    bundle_path = next(suite_dir.glob("replacement-*.json"))
    (suite_dir / "duplicate-replacement.json").write_bytes(bundle_path.read_bytes())

    with pytest.raises(receipts.ReceiptError, match="2 unclaimed sibling files"):
        receipts.load_release_receipt(suite_dir)


def test_an_undeclared_pattern_id_is_not_guessed(
    gate: ModuleType, receipts: ModuleType
) -> None:
    """A cascade row added without updating the policy must not read as a modifier.

    Silently treating it as one would drop its observations out of the
    supported population and out of row 14's closure check at once.
    """

    rows = _perfect_rows()
    rows[0]["journey"]["architecture"]["chosen_patterns"] = [_ROW, "brand_new_shape"]
    verdict = _evaluate(gate, receipts, rows)
    assert verdict.release == "invalid"
    assert any("brand_new_shape" in reason for reason in verdict.invalidity)


def test_a_declared_modifier_is_not_a_row(
    gate: ModuleType, receipts: ModuleType
) -> None:
    rows = _perfect_rows(80)
    for row in rows:
        row["journey"]["architecture"]["chosen_patterns"] = [
            _ROW,
            "form_field_runtime_inputs",
        ]
    verdict = _evaluate(gate, receipts, rows)
    assert verdict.release == "go"
    assert _row(verdict, 14).detail["cases_per_row"].keys() == {_ROW}


@pytest.mark.parametrize(
    ("repairs_over_budget", "expected"),
    [(0, "pass"), (1, "fail")],
)
def test_the_repair_budget_is_derived_and_exact(
    gate: ModuleType,
    receipts: ModuleType,
    repairs_over_budget: int,
    expected: str,
) -> None:
    # 20 cases x 5 repetitions = 100 eligible attempts, so the ceiling is
    # floor(0.05 x 100) = 5 — derived from the manifest, never restated.
    rows = _perfect_rows(20)
    budget = 5 + repairs_over_budget
    for index in range(budget):
        rows[index]["journey"]["plan_outcome"]["repair_attempts"] = 1
        rows[index]["outcome_class"] = "plan_repaired"
    verdict = _evaluate(gate, receipts, rows)
    repair_row = _row(verdict, 3)
    assert repair_row.threshold == 5
    assert repair_row.actual == budget
    assert repair_row.verdict == expected


def test_missing_repair_evidence_is_fail_closed(
    gate: ModuleType, receipts: ModuleType
) -> None:
    rows = _perfect_rows()
    del rows[0]["journey"]["plan_outcome"]["repair_attempts"]
    with pytest.raises(gate.ReleaseGateError, match="repair_attempts"):
        _evaluate(gate, receipts, rows)


def test_a_malformed_row_makes_the_receipt_unreadable(receipts: ModuleType) -> None:
    """The regression this reader exists for: a dropped row shrank the run.

    The old comparator loader skipped rows it could not read, so a truncated
    receipt scored as a smaller, healthier one.
    """

    rows = _perfect_rows()
    rows[7].pop("case_id")
    with pytest.raises(receipts.ReceiptError, match="case_id"):
        receipts.receipt_from_summary(_summary(rows), where="test receipt")


def test_a_malformed_nested_field_is_a_defect_not_an_empty_value(
    receipts: ModuleType,
) -> None:
    rows = _perfect_rows()
    rows[2]["journey"]["architecture"]["chosen_patterns"] = "document_to_pdf_report"
    with pytest.raises(receipts.ReceiptError, match="chosen_patterns"):
        receipts.receipt_from_summary(_summary(rows), where="test receipt")


def test_a_summary_alone_cannot_produce_a_release_verdict(
    gate: ModuleType, receipts: ModuleType
) -> None:
    receipt = receipts.receipt_from_summary(
        _summary(_perfect_rows()), where="test receipt"
    )
    verdict = gate.evaluate(receipt, _matrix(gate), _pin(gate))
    assert verdict.release == "invalid"
    assert any("integrity" in reason for reason in verdict.invalidity)


def test_a_deleted_case_fails_the_manifest_check(
    receipts: ModuleType, tmp_path: Path
) -> None:
    """The quiet corruption: every rate still looks healthy on fewer cases."""

    rows = _perfect_rows()
    suite_dir = _suite_dir(tmp_path, rows)
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    summary["results"] = [
        row for row in summary["results"] if row["case_id"] != "case_3"
    ]
    (suite_dir / "suite-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(receipts.ReceiptError, match="missing_observation_keys"):
        receipts.load_release_receipt(suite_dir)


def test_an_edited_bundle_fails_its_digest(
    receipts: ModuleType, tmp_path: Path
) -> None:
    rows = _perfect_rows()
    suite_dir = _suite_dir(tmp_path, rows)
    bundle = suite_dir / str(rows[0]["bundle_file"])
    bundle.write_text(json.dumps({"case_id": "tampered"}), encoding="utf-8")
    with pytest.raises(receipts.ReceiptError, match="sha256_mismatch"):
        receipts.load_release_receipt(suite_dir)


@pytest.mark.parametrize(
    ("field", "value"),
    [("outcome_class", "plan_first_pass"), ("expectation_verdict", "pass")],
)
def test_editing_only_the_summary_is_caught_by_the_bundle(
    receipts: ModuleType, tmp_path: Path, field: str, value: str
) -> None:
    """Digests protect the bundles; the SUMMARY is what gets scored.

    Without binding the two, a failure can be rewritten as a pass in the
    summary while every bundle digest still matches.
    """

    rows = _perfect_rows(4)
    rows[0]["outcome_class"] = "builder_error"
    rows[0]["journey"]["outcome_class"] = "builder_error"
    rows[0]["expectation_verdict"] = "fail"
    rows[0]["failed_checks"] = [{"name": "expected_leaf_output_fields"}]
    suite_dir = _suite_dir(tmp_path, rows)
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    summary["results"][0][field] = value
    (suite_dir / "suite-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(
        receipts.ReceiptError, match=f"sealed in its bundle on \\['{field}'\\]"
    ):
        receipts.load_release_receipt(suite_dir)


def test_relabelling_invalid_evidence_as_a_pass_is_refused(
    receipts: ModuleType, tmp_path: Path
) -> None:
    """The cheapest way to turn a broken measurement into a release.

    `completed` is a claim that the observation's provenance validated, so it
    has to be checked against the bundle rather than accepted from the summary.
    """

    rows = _perfect_rows(4)
    rows[0]["observation_status"] = "invalid_evidence"
    rows[0]["outcome_class"] = "invalid_evidence"
    rows[0]["expectation_verdict"] = "not_evaluated"
    rows[0]["evidence_valid"] = False
    rows[0]["evidence_failed_check_count"] = 2
    suite_dir = _suite_dir(tmp_path, rows)
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    summary["results"][0]["evidence_valid"] = True
    summary["results"][0]["evidence_failed_check_count"] = 0
    summary["results"][0]["observation_status"] = "completed"
    summary["results"][0]["outcome_class"] = "plan_first_pass"
    summary["results"][0]["expectation_verdict"] = "pass"
    (suite_dir / "suite-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(receipts.ReceiptError, match="sealed in its bundle"):
        receipts.load_release_receipt(suite_dir)


def test_a_bundle_that_forged_its_own_identity_is_refused(
    receipts: ModuleType, tmp_path: Path
) -> None:
    rows = _perfect_rows(4)
    suite_dir = _suite_dir(tmp_path, rows)
    bundle_path = suite_dir / str(rows[0]["bundle_file"])
    bundle = json.loads(bundle_path.read_text())
    bundle["live_execution_provenance"]["source"]["tracked_clean"] = False
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    summary["results"][0]["bundle_sha256"] = hashlib.sha256(
        bundle_path.read_bytes()
    ).hexdigest()
    (suite_dir / "suite-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(receipts.ReceiptError, match="dirty tree"):
        receipts.load_release_receipt(suite_dir)


def test_a_receipt_from_another_corpus_is_refused(
    receipts: ModuleType, tmp_path: Path
) -> None:
    """Identity equality across two files proves only that one run wrote both."""

    suite_dir = _suite_dir(tmp_path, _perfect_rows(4))
    for name in ("suite-summary.json", "release-manifest.json"):
        payload = json.loads((suite_dir / name).read_text())
        payload["release_identity"]["build"]["cases_sha256"] = "9" * 64
        (suite_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(receipts.ReceiptError, match="different instrument or corpus"):
        receipts.load_release_receipt(suite_dir)


def test_a_bundle_measured_against_another_model_is_refused(
    receipts: ModuleType, tmp_path: Path
) -> None:
    """A self-consistent bundle from another run is still not this run's."""

    rows = _perfect_rows(4)
    suite_dir = _suite_dir(tmp_path, rows)
    bundle_path = suite_dir / str(rows[0]["bundle_file"])
    bundle = json.loads(bundle_path.read_text())
    model = {"requested_id": "some-other-model", "resolved_id": "some-other-model"}
    bundle["live_execution_provenance"]["model"] = {
        **model,
        "sha256": _RECEIPTS.canonical_sha256(model),
    }
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    summary["results"][0]["bundle_sha256"] = hashlib.sha256(
        bundle_path.read_bytes()
    ).hexdigest()
    (suite_dir / "suite-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(receipts.ReceiptError, match="but the run declares"):
        receipts.load_release_receipt(suite_dir)


def test_a_run_that_failed_its_own_acquisition_verdict_is_not_scored(
    receipts: ModuleType, tmp_path: Path
) -> None:
    """CP8a's verdict is authoritative; a later evaluator must not overrule it."""

    suite_dir = _suite_dir(tmp_path, _perfect_rows(4))
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    summary["identity_failed_check_count"] = 1
    (suite_dir / "suite-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(receipts.ReceiptError, match="identity_failed_check_count"):
        receipts.load_release_receipt(suite_dir)


def test_a_failed_final_target_recheck_cannot_be_relabelled_as_acquisition_pass(
    receipts: ModuleType, tmp_path: Path
) -> None:
    suite_dir = _suite_dir(tmp_path, _perfect_rows(4))
    summary_path = suite_dir / "suite-summary.json"
    summary = json.loads(summary_path.read_text())
    summary["release_identity_recheck"]["target"]["verified"] = False
    summary["release_identity_recheck_checks"] = (
        receipts.release_identity_recheck_checks(
            expected=summary["release_identity"],
            actual=summary["release_identity_recheck"],
            require_verified_target=True,
        )
    )
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(
        receipts.ReceiptError, match="suite_identity_failed_check_count"
    ):
        receipts.load_release_receipt(suite_dir)


def test_a_final_identity_probe_error_is_a_failed_acquisition(
    receipts: ModuleType, tmp_path: Path
) -> None:
    suite_dir = _suite_dir(tmp_path, _perfect_rows(4))
    summary_path = suite_dir / "suite-summary.json"
    summary = json.loads(summary_path.read_text())
    summary["release_identity_recheck"] = {"error": "target unavailable"}
    recheck_failures = receipts.release_identity_recheck_checks(
        expected=summary["release_identity"],
        actual=summary["release_identity_recheck"],
        require_verified_target=True,
    )
    summary["release_identity_recheck_checks"] = recheck_failures
    failure_count = sum(check["passed"] is not True for check in recheck_failures)
    summary["suite_identity_failed_check_count"] = failure_count
    summary["identity_failed_check_count"] = failure_count
    summary["sentinel_verdict"] = "fail"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(receipts.ReceiptError, match="failed its acquisition verdict"):
        receipts.load_release_receipt(suite_dir)


def test_a_sealed_observation_identity_failure_cannot_be_hidden_by_summary_counts(
    receipts: ModuleType, tmp_path: Path
) -> None:
    rows = _perfect_rows(4)
    rows[0]["identity_failed_check_count"] = 1
    rows[0]["identity_failed_checks"] = [
        {
            "name": "suite_requested_model_identity",
            "passed": False,
            "actual": "other-model",
            "expected": "model-under-test",
        }
    ]
    suite_dir = _suite_dir(tmp_path, rows)
    summary_path = suite_dir / "suite-summary.json"
    summary = json.loads(summary_path.read_text())
    summary["identity_failed_check_count"] = 0
    summary["observation_identity_failed_check_count"] = 0
    summary["sentinel_verdict"] = "pass"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(
        receipts.ReceiptError, match="observation_identity_failed_check_count"
    ):
        receipts.load_release_receipt(suite_dir)


def test_an_unreadable_bundle_is_a_refusal_not_a_crash(
    receipts: ModuleType, tmp_path: Path
) -> None:
    rows = _perfect_rows(4)
    suite_dir = _suite_dir(tmp_path, rows)
    bundle_path = suite_dir / str(rows[0]["bundle_file"])
    bundle_path.write_bytes(b"\xff\xfe not json")
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    summary["results"][0]["bundle_sha256"] = hashlib.sha256(
        bundle_path.read_bytes()
    ).hexdigest()
    (suite_dir / "suite-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(receipts.ReceiptError, match="could not be read"):
        receipts.load_release_receipt(suite_dir)


def test_an_exploratory_receipt_may_not_be_judged_for_release(
    receipts: ModuleType, tmp_path: Path
) -> None:
    suite_dir = _suite_dir(tmp_path, _perfect_rows(4))
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    summary["artifact_mode"] = "live_execution_exploratory_summary"
    (suite_dir / "suite-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(receipts.ReceiptError, match="artifact_mode"):
        receipts.load_release_receipt(suite_dir)


def test_a_summary_judged_beside_another_runs_manifest_is_refused(
    receipts: ModuleType, tmp_path: Path
) -> None:
    suite_dir = _suite_dir(tmp_path, _perfect_rows(4))
    manifest = json.loads((suite_dir / "release-manifest.json").read_text())
    manifest["release_identity"] = {"source": {"revision": "e" * 40}}
    (suite_dir / "release-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    with pytest.raises(receipts.ReceiptError, match="release_identity differs"):
        receipts.load_release_receipt(suite_dir)


def test_a_duplicated_manifest_slot_is_refused(
    receipts: ModuleType, tmp_path: Path
) -> None:
    suite_dir = _suite_dir(tmp_path, _perfect_rows(4))
    manifest = json.loads((suite_dir / "release-manifest.json").read_text())
    manifest["expected_observations"].append(manifest["expected_observations"][0])
    (suite_dir / "release-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    with pytest.raises(
        receipts.ReceiptError, match="invalid_expected_observation_keys"
    ):
        receipts.load_release_receipt(suite_dir)


def test_a_negative_measurement_is_refused(receipts: ModuleType) -> None:
    """A negative repair count or token total makes a budget row cheaper."""

    rows = _perfect_rows(4)
    rows[0]["journey"]["plan_outcome"]["repair_attempts"] = -3
    with pytest.raises(receipts.ReceiptError, match="must not be negative"):
        receipts.receipt_from_summary(_summary(rows), where="test receipt")


def test_a_case_that_sometimes_stops_as_intended_is_unstable_not_stable(
    gate: ModuleType, receipts: ModuleType
) -> None:
    """The predicate CP0 does not state directly, and the reason it matters.

    Judging case-level rows on the eligible subset alone would let a case that
    asks its contract's question in some repetitions and produces a plan in
    others look stable in both directions.
    """

    rows = _perfect_rows(80)
    rows[0]["outcome_class"] = "clarification_stop_intended"
    rows[0]["journey"]["outcome_class"] = "clarification_stop_intended"
    rows[1]["outcome_class"] = "builder_error"
    rows[1]["journey"]["outcome_class"] = "builder_error"
    verdict = _evaluate(gate, receipts, rows)
    assert _row(verdict, 8).detail["cases"] == ["case_0"]
    assert _row(verdict, 6).actual == 0


def test_a_whole_suite_directory_reads_and_passes(
    gate: ModuleType, receipts: ModuleType, tmp_path: Path
) -> None:
    suite_dir = _suite_dir(tmp_path, _perfect_rows(80))
    receipt = receipts.load_release_receipt(suite_dir)
    assert receipt.integrity_verified
    assert gate.evaluate(receipt, _matrix(gate), _pin(gate)).release == "go"


def test_a_receipt_that_ran_a_different_design_is_invalid(
    gate: ModuleType, receipts: ModuleType
) -> None:
    rows = [
        _observation(f"case_{index}", repetition)
        for index in range(4)
        for repetition in range(1, 4)
    ]
    summary = _summary(rows)
    summary["repetitions"] = 3
    receipt = receipts.receipt_from_summary(
        summary, where="test receipt", integrity_verified=True
    )
    verdict = gate.evaluate(receipt, _matrix(gate), _pin(gate))
    assert verdict.release == "invalid"
    assert any("repetitions" in reason for reason in verdict.invalidity)


def test_semantic_critic_events_are_counted_and_architecture_reported_apart(
    gate: ModuleType, receipts: ModuleType
) -> None:
    semantic = sorted(gate.SEMANTIC_INVARIANT_IDS)[0]
    architecture = sorted(gate.ARCHITECTURE_INVARIANT_IDS)[0]
    rows = _perfect_rows()
    rows[0]["failure_summary"]["failure_codes"] = [semantic]
    rows[1]["journey"]["plan_outcome"]["attempt_failure_ladder"] = [
        {"failure_codes": [semantic, architecture]}
    ]
    verdict = _evaluate(gate, receipts, rows)
    critic_row = _row(verdict, 11)
    assert critic_row.actual == 2
    assert critic_row.verdict == "fail"
    assert critic_row.detail["architecture_events"] == {architecture: 1}


def test_an_uncovered_supported_row_fails_the_matrix_gate(
    gate: ModuleType, receipts: ModuleType
) -> None:
    verdict = _evaluate(
        gate,
        receipts,
        _perfect_rows(),
        matrix_rows={_ROW: "supported", "audio_transcription": "supported"},
    )
    matrix_row = _row(verdict, 14)
    assert matrix_row.verdict == "fail"
    assert any(
        "audio_transcription" in item for item in matrix_row.detail["violations"]
    )


def test_measuring_a_removed_row_fails_the_matrix_gate(
    gate: ModuleType, receipts: ModuleType
) -> None:
    rows = _perfect_rows()
    for row in rows[:5]:
        row["journey"]["architecture"]["chosen_patterns"] = ["json_to_text_summary"]
    verdict = _evaluate(
        gate,
        receipts,
        rows,
        matrix_rows={_ROW: "supported", "json_to_text_summary": "removed"},
    )
    assert _row(verdict, 14).verdict == "fail"


def test_judging_a_receipt_from_another_revision_fails_the_matrix_gate(
    gate: ModuleType, receipts: ModuleType
) -> None:
    verdict = _evaluate(gate, receipts, _perfect_rows(), pin_revision="f" * 40)
    assert _row(verdict, 14).verdict == "fail"
    assert verdict.release == "no_go"


def test_an_uncommitted_evaluator_edit_fails_the_matrix_gate(
    gate: ModuleType, receipts: ModuleType
) -> None:
    """Pre-registration: the whole evaluator must predate the run it judges."""

    verdict = _evaluate(gate, receipts, _perfect_rows(), evaluator_clean=False)
    assert _row(verdict, 14).verdict == "fail"


def test_conformance_instability_is_pass_versus_non_pass(
    gate: ModuleType, receipts: ModuleType
) -> None:
    """Two different FAILURE labels are not instability — the case failed both times.

    The ceiling is the program's frozen 10% of the corpus's cases, the same
    bar as the mixed-first-pass gate.
    """

    rows = _perfect_rows(20)
    for repetition in range(2, 6):
        rows[repetition - 1]["expectation_verdict"] = "fail"
    for repetition in range(1, 6):
        rows[4 + repetition]["expectation_verdict"] = (
            "fail" if repetition % 2 else "not_evaluated"
        )
    trajectory = _evaluate(gate, receipts, rows).trajectory
    instability = trajectory["conformance_instability"]
    assert instability["unstable_cases"] == ["case_0"]
    assert instability["ceiling"] == 2
    assert trajectory["complete"] is False


def test_the_feasibility_audit_rejects_a_corpus_too_small_to_pass(
    gate: ModuleType, receipts: ModuleType
) -> None:
    """A gate a perfect product cannot pass is a plan defect (CP0 finding 1).

    Resolution is governed by CASES, not repetitions, so a 95% bound is
    unreachable below ~73 cases however flawlessly the product behaves. The
    audit must say so before anyone tries to fix the product to satisfy it.
    """

    assert (
        gate.feasibility_audit(
            _receipt(receipts, _perfect_rows(80)), _matrix(gate), _pin(gate)
        )["feasible"]
        is True
    )
    audit = gate.feasibility_audit(
        _receipt(receipts, _perfect_rows(10)), _matrix(gate), _pin(gate)
    )
    assert audit["feasible"] is False
    assert [row["row"] for row in audit["unpassable_rows"]] == [1, 2]


def test_the_tracked_matrix_state_lists_exactly_the_cascade_rows(
    gate: ModuleType,
) -> None:
    """The matrix state is the gate's only row vocabulary.

    A cascade branch added without re-affirming this file would fail closed at
    the receipt, which is safe but late; comparing the two mechanically fails
    it at the commit that introduced the branch.
    """

    tree = ast.parse(_DERIVATION.read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_primary_pattern_id"
    )
    cascade_rows = {
        node.value.value
        for node in ast.walk(function)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    state = gate.matrix_state_from_payload(
        json.loads(_MATRIX_STATE.read_text(encoding="utf-8")), where=str(_MATRIX_STATE)
    )
    assert set(state.rows) == cascade_rows


def _release_verdict_cli(
    suite_dir: Path, tmp_path: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "ai_builder_battle_compare.py"),
            "release-verdict",
            str(suite_dir),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )


def test_the_release_cli_reports_go_no_go_and_invalid_in_its_exit_code(
    tmp_path: Path,
) -> None:
    """Whatever consumes this runs it, it does not import it.

    The exit code IS the verdict for that caller. GO is pinned through the
    mapping itself because a real GO also requires a committed evaluator, which
    a working tree mid-slice is not; NO-GO, gate-invalid and unreadable are
    driven all the way through the process.
    """

    comparator = _script("ai_builder_battle_compare")
    assert comparator._release_exit_code({"release": "go"}) == 0
    assert comparator._release_exit_code({"release": "no_go"}) == 1
    assert comparator._release_exit_code({"release": "invalid"}) == 2
    assert (
        comparator._release_exit_code(
            {"release": "go", "feasibility": {"feasible": False}}
        )
        == 2
    )

    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=_SCRIPTS,
        check=True,
    ).stdout.strip()
    rows = _perfect_rows(80)
    rows[0]["outcome_class"] = "builder_error"
    rows[0]["journey"]["outcome_class"] = "builder_error"
    no_go = _release_verdict_cli(
        _suite_dir(tmp_path / "no-go", rows, revision=revision), tmp_path
    )
    assert no_go.returncode == 1, no_go.stdout
    assert json.loads(no_go.stdout)["release"] == "no_go"

    short = _perfect_rows(4)
    short_dir = _suite_dir(tmp_path / "invalid", short, revision=revision)
    summary = json.loads((short_dir / "suite-summary.json").read_text())
    summary["repetitions"] = 3
    (short_dir / "suite-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    invalid = _release_verdict_cli(short_dir, tmp_path)
    assert invalid.returncode == 2, invalid.stdout
    assert json.loads(invalid.stdout)["release"] == "invalid"

    unreadable = _suite_dir(
        tmp_path / "unreadable", _perfect_rows(4), revision=revision
    )
    (unreadable / "suite-summary.json").write_text("{}", encoding="utf-8")
    refused = _release_verdict_cli(unreadable, tmp_path)
    # A receipt that cannot be read is invalid, not a NO-GO.
    assert refused.returncode == 2, refused.stderr


def test_the_compare_entry_point_still_runs(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "ai_builder_battle_compare.py"),
            "compare",
            "-h",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode == 0, result.stderr
