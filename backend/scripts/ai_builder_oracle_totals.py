#!/usr/bin/env python3
"""Totals and the pre-registered decision of the oracle experiment.

Reads the receipts of the experiment's legs (arm A, the Builder; arm O, expert
specs) and reports for each leg attempted, invalid evidence, executed,
unmeasured, decided and fulfilled as separate totals, each rate labelled with
its denominator.

A leg is read only through an integrity-verified receipt (`verified_receipt`):
the manifest's expected slots, every bundle's digest, the bundle's identity and
the summary row equal to the observation the bundle sealed. A receipt that
fails any of it is a leg with no rows and an integrity error, and the decision
is NO_DECISION. Nothing here reads a summary or a bundle any other way.

It computes no verdict of its own. A slot is fulfilled when the scorer's
sealed final-output verdict (`verdict_states.output`) is `pass` on valid
evidence; a row that does not carry a valid one is an invalid slot. A slot
whose run was created and whose output the scorer could not decide
(`unmeasured`) is neither fulfilled, failed nor invalid: it is counted apart.
The decided slots of a leg are its attempted slots less its unmeasured ones
(invalid and not-executed slots stay decided, as not fulfilled), and the rule
divides each arm's audited fulfilment by its decided slots. Because that
denominator moves with the unmeasured count, two decision legs whose
unmeasured counts differ by more than MAX_UNMEASURED_DIFFERENCE are not
measured alike, and a leg with no decided slot has no rate: NO_DECISION.

The decision fails closed. `decide` returns a decision only when the legs are
one experiment: the canonical comparator's identity and run-context rules hold
between every pair of legs, every leg is what the freeze record says it is
(arm, Builder model, runtime model, scorer sha, spec manifest, intake answers),
the runtime model every step actually ran on is the declared one, the case
selection is the frozen one, and no leg has more than MAX_INVALID_SLOTS invalid
slots. Otherwise the outcome is NO_DECISION with the reasons.

The audit overlay is check-level. A correction names one exact oracle check of
one case (a required literal, a forbidden literal or an association), says it is
wrong and what it should have been (or that it has no basis), with a class and
the evidence. It is applied to EVERY leg alike and every stored output of that
case is re-scored through the scorer's own output dimension with the corrected
expectation, so a slot changes state only if all of its checks agree; a slot
with any other failed check stays failed. Fulfilled, failed and unmeasured
executed slots are all re-scored: lifts, drops, decided slots that the
re-score cannot decide (unmeasured) and unmeasured slots it decides are each
counted, in the totals and the per-case vectors alike. The audit re-scores
only with the frozen scorer.

usage:
  ai_builder_oracle_totals.py report --selection ai_builder_oracle_cases.json \\
      --freeze oracle-freeze.json \\
      --leg A_luna6:builder:gpt-6-luna=SUITE_DIR \\
      --leg O_luna6:oracle:gpt-6-luna=SUITE_DIR \\
      --leg O_gemma:oracle:gemma4-31b-it=SUITE_DIR \\
      [--audit audit.json] [--probe-suite SMOKE_SUITE_DIR] [--format markdown|json]

Legs are `label:arm:runtime-model=suite-dir`. The decision reads the legs
labelled `A_luna6` and `O_luna6`; other legs are reported, never decided on.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import random
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

JsonObject = dict[str, Any]

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import ai_builder_code_identity as code_identity  # noqa: E402
import ai_builder_receipt as receipt  # noqa: E402

# The pre-registered rule (decision-builder-strategy-2026-09-29.md, item 3):
# advance a create pilot only if audited O fulfilment is at least 40% AND
# exceeds the matched A by at least 20 points. Integer percents: no float
# comparison decides anything.
MIN_O_PERCENT = 40
MIN_GAP_POINTS = 20
DECISION_O_LEG = "O_luna6"
DECISION_A_LEG = "A_luna6"
# A leg with more invalid slots than this is not a measurement of its arm.
MAX_INVALID_SLOTS = 6
# An unmeasured slot (the scorer ran on the delivered output and could not
# decide it) is neither a fulfilment nor a failure: the rule divides each
# arm's fulfilment by its decided slots. Two arms whose unmeasured counts
# differ by more than this are not measured alike: NO_DECISION.
MAX_UNMEASURED_DIFFERENCE = 6
BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_SEED = 20260929
AUDIT_CLASSES = frozenset({"OW", "OA", "SD", "FD"})
REQUIRED_FREEZE_KEYS = (
    "schema_version",
    "h1_sha",
    "scorer_source_revision",
    "harness_sha256",
    "scorer_semantics_version",
    "scorer_sha256",
    "cases_sha256",
    "selection_sha256",
    "oracle_manifest_sha256",
    "totals_sha256",
    "builder_model_id",
    "intake_message_sha256_by_id",
    "material_manifest_sha256",
    "docs_manifest_sha256",
    "legs",
)

INVALID_STATUSES = frozenset(
    {"invalid_evidence", "acquisition_failure", "execution_failure"}
)


class ExperimentError(ValueError):
    """An input is malformed; nothing is reported."""


def mechanical_tags(case: Mapping[str, Any]) -> list[str]:
    """The coverage tags of a case, from its definition alone (never an outcome).

    IN  input interpretation: three or more runtime files of two or more
        formats, three or more run-form fields, free text, or a structured
        input (xlsx, csv, json, txt).
    REF reference material: an attachment that is not a template (its name
        has no "mall").
    REV a declared review checkpoint.
    TPL the terminal step fills an attached DOCX template.
    LOSS six or more required facts, so a fact has to survive a chain.
    """

    execution = cast(Mapping[str, Any], case.get("execution") or {})
    inputs = cast(Mapping[str, Any], execution.get("inputs") or {})
    files = cast(list[str], inputs.get("files") or [])
    extensions = {Path(name).suffix.lower() for name in files}
    tags: list[str] = []
    if (
        (len(files) >= 3 and len(extensions) >= 2)
        or len(inputs.get("form_fields") or {}) >= 3
        or inputs.get("text") is not None
        or extensions & {".xlsx", ".csv", ".json", ".txt"}
    ):
        tags.append("IN")
    if any("mall" not in name for name in case.get("attachments") or []):
        tags.append("REF")
    if execution.get("checkpoints"):
        tags.append("REV")
    if (case.get("expected") or {}).get(
        "terminal_document_output_mode"
    ) == "template_fill":
        tags.append("TPL")
    if len((execution.get("expect") or {}).get("required_facts") or []) >= 6:
        tags.append("LOSS")
    return tags


@dataclass(frozen=True, slots=True)
class Leg:
    label: str
    arm: str
    runtime_model: str
    directory: Path
    summary: Mapping[str, Any]
    rows: tuple[Mapping[str, Any], ...]
    # What the bundles say about the models the steps ran on; read once when the
    # receipt is parsed (`_scan_runtime`) and computed on demand otherwise.
    scan: Mapping[str, Any] | None = None
    # Why the receipt is not an intact record of its run (`verified_receipt`); a
    # leg with an error has no rows and nothing else about it is believed.
    integrity_error: str | None = None


def _read_json_object(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise receipt.ReceiptError(
            f"{path} could not be read as JSON: {error}"
        ) from error
    if not isinstance(value, Mapping):
        raise receipt.ReceiptError(f"{path} must contain a JSON object.")
    return cast(Mapping[str, Any], value)


def verified_receipt(directory: Path) -> receipt.Receipt:
    """The receipt of a suite directory, or `ReceiptError`: the release reader's
    integrity checks, for an exploratory receipt.

    A summary is the measured party's account of itself. This is the checking
    the release reader does before it believes one (`ai_builder_receipt.py`,
    `_load_integrity_verified_base_receipt`) without the release-only demands
    (a release-mode artifact, a passed capacity preflight): the summary parses
    with its verdict states, the manifest agrees with it on the run's identity,
    the manifest's expected slots are exactly the summary's, every bundle is on
    disk with the digest its row carries, and every row IS the observation its
    bundle sealed, under the identity the run declares. The receipt module's
    own functions do each of them; this only composes them.
    """

    summary_path = directory / receipt.SUITE_SUMMARY_FILE
    manifest_path = directory / receipt.RELEASE_MANIFEST_FILE
    summary = _read_json_object(summary_path)
    manifest = _read_json_object(manifest_path)
    verified = receipt.receipt_from_summary(
        summary, where=str(summary_path), integrity_verified=True
    )
    if manifest.get("artifact_schema_version") != verified.artifact_schema_version:
        raise receipt.ReceiptError(f"{manifest_path}: its schema is not the summary's.")
    for component in ("release_identity", "evaluator_identity"):
        if not manifest.get(component) or manifest.get(component) != summary.get(
            component
        ):
            raise receipt.ReceiptError(
                f"{manifest_path}: {component} differs between the manifest and "
                "the summary; these are not two records of one run."
            )
    if manifest.get("capacity_preflight") != summary.get("capacity_preflight"):
        raise receipt.ReceiptError(
            f"{manifest_path}: capacity_preflight differs from the summary's."
        )
    expected = manifest.get("expected_observations")
    if (
        not isinstance(expected, list)
        or not expected
        or not all(isinstance(entry, Mapping) for entry in expected)
    ):
        raise receipt.ReceiptError(
            f"{manifest_path}: expected_observations must be a non-empty array."
        )
    membership = receipt.receipt_membership_report(
        expected_observations=[dict(entry) for entry in expected],
        results=[dict(observation.row) for observation in verified.observations],
        suite_dir=directory,
    )
    if membership["status"] != "complete":
        raise receipt.ReceiptError(
            f"{summary_path} is not a complete record of its manifest: "
            + json.dumps(
                {k: v for k, v in membership.items() if k != "status" and v},
                ensure_ascii=False,
            )
        )
    identity = cast(Mapping[str, Any], summary.get("release_identity") or {})
    for observation in verified.observations:
        bundle_path = directory / observation.bundle_file
        # The receipt module's own row-versus-bundle equality: the harness seals
        # its judgement inside the bundle before hashing it, so this is an
        # equality check and not a second evaluator.
        receipt._require_row_matches_bundle(  # pyright: ignore[reportPrivateUsage]
            observation,
            bundle=_read_json_object(bundle_path),
            where=f"{summary_path} {observation.slot}",
            identity=identity,
        )
    return verified


def leg_bundle(leg: Leg, row: Mapping[str, Any]) -> Mapping[str, Any]:
    """A slot's bundle, only if it is still the bytes the receipt was verified on."""

    return _read_bundle(leg.directory, row)


def _read_bundle(directory: Path, row: Mapping[str, Any]) -> Mapping[str, Any]:
    path = directory / str(row["bundle_file"])
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ExperimentError(f"{path} could not be read: {error}") from error
    if hashlib.sha256(data).hexdigest() != row.get("bundle_sha256"):
        raise ExperimentError(f"{path} is not the bundle the receipt was verified on.")
    return cast(Mapping[str, Any], json.loads(data))


def parse_leg(text: str) -> Leg:
    spec, _, directory = text.partition("=")
    parts = spec.split(":")
    if len(parts) != 3 or not directory:
        raise ExperimentError(
            f"--leg must be label:arm:runtime-model=dir; got {text!r}."
        )
    label, arm, runtime_model = parts
    if arm not in ("builder", "oracle"):
        raise ExperimentError(f"{label}: arm must be builder or oracle.")
    path = Path(directory)
    try:
        verified = verified_receipt(path)
    except receipt.ReceiptError as error:
        return Leg(
            label,
            arm,
            runtime_model,
            path,
            {},
            (),
            _scan_runtime(path, (), runtime_model),
            str(error),
        )
    rows = tuple(dict(observation.row) for observation in verified.observations)
    return Leg(
        label,
        arm,
        runtime_model,
        path,
        verified.summary,
        rows,
        _scan_runtime(path, rows, runtime_model),
    )


def _identity(leg: Leg) -> Mapping[str, Any]:
    identity = leg.summary.get("evaluator_identity")
    return cast(Mapping[str, Any], identity if isinstance(identity, Mapping) else {})


def _run_context(leg: Leg) -> Mapping[str, Any]:
    context = _identity(leg).get("run_context")
    return cast(Mapping[str, Any], context if isinstance(context, Mapping) else {})


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_freeze(path: Path | None) -> Mapping[str, Any]:
    if path is None:
        raise ExperimentError("a freeze record is required (--freeze).")
    freeze = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED_FREEZE_KEYS if key not in freeze]
    if missing:
        raise ExperimentError(f"the freeze record lacks {', '.join(missing)}.")
    return cast(Mapping[str, Any], freeze)


def _compare_module() -> Any:
    return importlib.import_module("ai_builder_battle_compare")


def _config_key(leg: Leg) -> tuple[Any, ...]:
    """What a receipt measured: its arm, its Builder model and the models its
    steps ran on, all read from the receipt and its bundles, never from the
    label the operator typed."""

    return (
        _run_context(leg).get("arm", "builder"),
        _identity(leg).get("requested_model_id"),
        tuple(runtime_models(leg)["observed"]),
    )


def _label_problems(leg: Leg, *, where: str) -> list[str]:
    """A leg's declared arm and runtime model against its receipt and its bundles.

    Run before any leg is compared with another (sol round 4): a receipt
    labelled as another configuration would otherwise be treated as one.
    """

    problems: list[str] = []
    receipt_arm = _run_context(leg).get("arm", "builder")
    if receipt_arm != leg.arm:
        problems.append(
            f"{where}: declared arm {leg.arm} but the receipt says {receipt_arm}"
        )
    models = runtime_models(leg)
    if not models["observed"]:
        problems.append(f"{where}: no runtime model was observed")
    if models["mismatch"]:
        problems.append(
            f"{where}: steps ran on {models['mismatch']}, not {leg.runtime_model}"
        )
    return problems


def _leg_problems(
    leg: Leg,
    *,
    where: str,
    wanted: Sequence[str],
    repetitions: int,
    freeze: Mapping[str, Any],
    base: Leg | None,
    enforce_invalid_cap: bool,
) -> tuple[list[str], JsonObject]:
    """Everything a receipt must be to stand for its frozen leg.

    Also run on an ORIGINAL receipt that a re-run superseded (with the invalid
    cap off: exceeding it is what made the re-run eligible), so the original
    has to be a genuine receipt of the same leg before a replacement may decide.
    """

    problems: list[str] = []
    frozen_legs = cast(Mapping[str, Mapping[str, Any]], freeze["legs"])
    declared = frozen_legs.get(leg.label)
    if declared is None:
        return [f"{where}: not one of the legs the freeze record allows"], {}
    if leg.integrity_error is not None:
        return [_integrity_problem(leg, where)], {}
    problems += _label_problems(leg, where=where)
    if _dirty_source(leg.summary):
        problems.append(
            f"{where}: the run recorded a dirty (or unknown) tracked source, so it "
            "did not measure the bytes of the commit it names"
        )
    target = _target_problems(leg, freeze, problems, where=where)
    identity, context = _identity(leg), _run_context(leg)
    if (leg.arm, leg.runtime_model) != (
        declared.get("arm"),
        declared.get("runtime_model"),
    ):
        problems.append(f"{where}: arm/runtime model differ from the freeze record")
    requested = identity.get("requested_model_id")
    if leg.arm == "builder" and requested != freeze["builder_model_id"]:
        problems.append(f"{where}: Builder model is not the frozen one")
    if leg.arm == "oracle" and requested is not None:
        problems.append(f"{where}: an oracle leg names a Builder model")
    if leg.arm == "oracle" and (
        context.get("oracle_manifest_sha256") != freeze["oracle_manifest_sha256"]
    ):
        problems.append(f"{where}: spec manifest is not the frozen one")
    for field, key in (
        ("harness_sha256", "harness_sha256"),
        ("scorer_semantics_version", "scorer_semantics_version"),
        ("scorer_sha256", "scorer_sha256"),
        ("source_revision", "scorer_source_revision"),
        ("cases_sha256", "cases_sha256"),
    ):
        if identity.get(field) != freeze[key]:
            problems.append(f"{where}: {field} is not the frozen scorer's")
    # Same answers up front for every arm, byte for byte.
    if context.get("intake_answers") != "upfront":
        problems.append(f"{where}: the intake answers were not given up front")
    if context.get("intake_answers_sha256_by_id") != {
        case_id: freeze["intake_message_sha256_by_id"].get(case_id)
        for case_id in wanted
    }:
        problems.append(f"{where}: intake answers are not the frozen author material")
    # The canonical comparator's identity and run-context rules.
    if base is not None and leg is not base:
        for field in _compare_module()._incompatible_identity_fields(
            dict(base.summary), dict(leg.summary)
        ):
            problems.append(f"{where}: differs from {base.label} on {field}")
    integrity = leg.summary.get("receipt_integrity")
    if not isinstance(integrity, Mapping) or integrity.get("status") != "complete":
        problems.append(f"{where}: receipt is not complete")
    slots = Counter((row.get("case_id"), row.get("repetition")) for row in leg.rows)
    expected = {(c, r) for c in wanted for r in range(1, repetitions + 1)}
    if set(slots) != expected or any(count != 1 for count in slots.values()):
        problems.append(
            f"{where}: slots are not exactly {len(wanted)} cases x {repetitions} repetitions"
        )
    invalid = invalid_slots(leg)
    if enforce_invalid_cap and invalid > MAX_INVALID_SLOTS:
        problems.append(
            f"{where}: {invalid} invalid slots (more than {MAX_INVALID_SLOTS}); not a measurement of the arm"
        )
    return problems, target


def _dirty_source(summary: Mapping[str, Any]) -> bool:
    """Whether a receipt records that its run was not on a clean tracked tree.

    The harness records `release_identity.source.tracked_clean` for every run,
    and an exploratory suite (one that supplies no acquisition contract) does not
    refuse a dirty tree itself; a receipt that does not say `true` did not measure
    the bytes of the commit it names.
    """

    identity = summary.get("release_identity")
    source = (
        cast(Mapping[str, Any], identity).get("source")
        if isinstance(identity, Mapping)
        else None
    )
    return not isinstance(source, Mapping) or source.get("tracked_clean") is not True


def _integrity_problem(leg: Leg, where: str) -> str:
    return f"{where}: the receipt is not an intact record of its run: {leg.integrity_error}"


def invalid_slots(leg: Leg) -> int:
    """Slots that cannot be scored: the row's own invalid states, plus every slot
    with a completed model attempt whose actual model is unknown."""

    return sum(leg_state(leg, row) == "invalid" for row in leg.rows)


def check_experiment(
    legs: Sequence[Leg],
    selection: Mapping[str, Any],
    freeze: Mapping[str, Any],
    *,
    selection_sha256: str,
    reruns: Sequence[Leg] = (),
    evidence: Sequence[Leg] = (),
) -> list[str]:
    """Every reason these legs are not the frozen experiment; empty when they are.

    `reruns` are the ORIGINAL receipts that a replacement in `legs` supersedes,
    each named by the label of the leg it belongs to (`Leg.label`); `evidence`
    are receipts reported and never decided on.
    """

    problems: list[str] = []
    labels = Counter(leg.label for leg in legs)
    # A label names one receipt: a second receipt under the same label would
    # let the last one silently win.
    for label, count in labels.items():
        if count > 1:
            problems.append(f"duplicate leg label {label} ({count} receipts)")
    for needed in (DECISION_A_LEG, DECISION_O_LEG):
        if needed not in labels:
            problems.append(f"decision leg {needed} is missing")
    wanted = [str(case["id"]) for case in selection["cases"]]
    repetitions = int(selection["repetitions"])
    # The case selection is the frozen one, and it holds no case whose
    # measurement depends on a naming difference (review-edit target).
    if selection_sha256 != freeze["selection_sha256"]:
        problems.append("the selection file is not the frozen one")
    if len(wanted) != 20 or len(set(wanted)) != 20 or repetitions != 3:
        problems.append("the selection is not 20 distinct cases x 3 repetitions")
    if any(case.get("edit_target") for case in selection["cases"]):
        problems.append("the selection holds a review-edit (edit_target) case")
    if _sha256_file(Path(__file__)) != freeze["totals_sha256"]:
        problems.append("this totals script is not the frozen one")

    base = next((leg for leg in legs if leg.label == DECISION_A_LEG), None)
    if base is not None and base.integrity_error is not None:
        base = None  # nothing to compare a leg with; its own problem is reported
    targets: dict[str, Any] = {}
    for leg in legs:
        leg_problems, target = _leg_problems(
            leg,
            where=leg.label,
            wanted=wanted,
            repetitions=repetitions,
            freeze=freeze,
            base=base,
            enforce_invalid_cap=True,
        )
        problems += leg_problems
        if leg.integrity_error is None:
            targets[leg.label] = target
    if len({json.dumps(t, sort_keys=True) for t in targets.values()}) > 1:
        problems.append("the legs did not run against the same deployed API")
    contracts = [
        _identity(leg).get("case_contract_sha256_by_id") or {}
        for leg in legs
        if leg.integrity_error is None
    ]
    for case_id in wanted:
        if len({json.dumps(c.get(case_id)) for c in contracts}) != 1:
            problems.append(f"case contract differs across legs for {case_id}")
    problems += _rerun_problems(
        legs,
        reruns,
        evidence,
        wanted=wanted,
        repetitions=repetitions,
        freeze=freeze,
        base=base,
    )
    return problems


def _rerun_problems(
    legs: Sequence[Leg],
    reruns: Sequence[Leg],
    evidence: Sequence[Leg],
    *,
    wanted: Sequence[str],
    repetitions: int,
    freeze: Mapping[str, Any],
    base: Leg | None,
) -> list[str]:
    """The re-run contract: an explicit original/replacement pair, and nothing else.

    A leg with more than MAX_INVALID_SLOTS invalid slots may be re-run once. The
    replacement decides only if the receipt it replaces is supplied as its
    original, is a genuine receipt of the same leg (same frozen identity, same
    receipt rules, earlier than the replacement), and really exceeded the cap.
    A receipt of a decision leg's configuration that is not so declared cannot
    be passed off as separate evidence: that would let a favourable second
    receipt displace a valid first one.
    """

    problems: list[str] = []
    by_label = {leg.label: leg for leg in legs}
    for label, count in Counter(o.label for o in reruns).items():
        if count > 1:
            problems.append(f"{label}: more than one re-run (at most one per leg)")
    for original in reruns:
        label = original.label
        replacement = by_label.get(label)
        if replacement is None:
            problems.append(f"{label}: a re-run original for a leg that is not decided")
            continue
        where = f"{label} (original)"
        if original.directory == replacement.directory:
            problems.append(f"{where}: is the replacement's own receipt")
        if (original.arm, original.runtime_model) != (
            replacement.arm,
            replacement.runtime_model,
        ):
            problems.append(f"{where}: is not the same arm and runtime model")
        original_problems, _ = _leg_problems(
            original,
            where=where,
            wanted=wanted,
            repetitions=repetitions,
            freeze=freeze,
            base=None,  # its replacement was compared with the base; pair them below
            enforce_invalid_cap=False,
        )
        problems += original_problems
        if (
            original.integrity_error is not None
            or replacement.integrity_error is not None
        ):
            continue  # nothing of either is believed, so nothing is compared
        for field in _compare_module()._incompatible_identity_fields(
            dict(original.summary), dict(replacement.summary)
        ):
            problems.append(f"{where}: differs from its replacement on {field}")
        if str(original.summary.get("created_at")) >= str(
            replacement.summary.get("created_at")
        ):
            problems.append(f"{where}: is not earlier than its replacement")
        invalid = invalid_slots(original)
        if invalid <= MAX_INVALID_SLOTS:
            problems.append(
                f"{where}: not eligible for a re-run: {invalid} invalid slots "
                f"(a re-run needs more than {MAX_INVALID_SLOTS})"
            )
    declared = {o.directory for o in reruns}
    decided = {
        _config_key(leg): leg.label for leg in legs if leg.integrity_error is None
    }
    for leg in evidence:
        where = f"evidence receipt {leg.label}"
        # First what the receipt itself says it is, then, and only for a receipt
        # that is what its label says, whether it is a decision leg's configuration.
        if leg.integrity_error is not None:
            problems.append(_integrity_problem(leg, where))
            continue
        if _dirty_source(leg.summary):
            # Refused evidence: a diagnostic of the report (`refused_evidence`),
            # not a decision problem. It measured no commit's bytes, so it can
            # neither decide nor be the valid first receipt a re-run displaces.
            continue
        problems += _label_problems(leg, where=where)
        owner = decided.get(_config_key(leg))
        if owner is not None and leg.directory not in declared:
            problems.append(
                f"{where} is a receipt of {owner}'s configuration; "
                f"declare it with --rerun-of {owner}=<dir> or leave it out"
            )
    return problems


def refused_evidence(evidence: Sequence[Leg]) -> dict[str, str]:
    """Evidence receipts that are reported as refused, and why: a receipt that
    records a dirty (or unknown) tracked source is not evidence of any commit."""

    return {
        leg.label: "the run recorded a dirty (or unknown) tracked source"
        for leg in evidence
        if leg.integrity_error is None and _dirty_source(leg.summary)
    }


def _target_problems(
    leg: Leg, freeze: Mapping[str, Any], problems: list[str], *, where: str
) -> JsonObject:
    """The deployed revision a leg's receipt proves, checked against the freeze.

    The harness verified `GET /version` before the leg's first case and again
    at its end (`--verify-target`, always on for the oracle arm) and recorded
    the result; a receipt without it, unverified, for another revision, or
    whose final recheck disagreed cannot be part of the decision.
    """

    identity = leg.summary.get("release_identity")
    target = (
        cast(Mapping[str, Any], identity).get("target")
        if isinstance(identity, Mapping)
        else None
    )
    if not isinstance(target, Mapping):
        problems.append(f"{where}: the receipt carries no verified deployed revision")
        return {}
    revision = str(freeze["scorer_source_revision"])
    if target.get("verified") is not True:
        problems.append(f"{where}: the deployed API was not verified")
    if (
        target.get("expected_source_revision") != revision
        or target.get("version") != f"DEV-{revision[:12]}"
    ):
        problems.append(f"{where}: the deployed API is not the frozen tree's revision")
    if leg.summary.get("suite_identity_failed_check_count") != 0:
        problems.append(f"{where}: the run's identity changed between start and end")
    return {
        "api_base_url": target.get("api_base_url"),
        "version": target.get("version"),
    }


def _is_model_attempt(attempt: Mapping[str, Any], ledger: set[Any]) -> bool:
    """Whether a step attempt made a model call.

    A canned step (a renderer, a template fill) completes with no model, no
    provider, no tokens and no entry in the run's provider-call ledger; every
    attempt that carries any trace of a call is a model attempt.
    """

    if attempt.get("id") in ledger:
        return True
    if any(
        attempt.get(key) not in (None, "")
        for key in (
            "requested_model",
            "response_model",
            "provider",
            "provider_response_id",
        )
    ):
        return True
    return any(
        isinstance(attempt.get(key), int) and attempt[key] > 0
        for key in ("num_tokens_input", "num_tokens_output")
    )


def _known(model: object) -> bool:
    return isinstance(model, str) and bool(model.strip())


def _scan_runtime(
    directory: Path, rows: Sequence[Mapping[str, Any]], declared: str
) -> JsonObject:
    """Which models the steps ran on, and which slots cannot prove it.

    Read from every bundle, both arms alike. A COMPLETED model attempt must
    carry both its requested and its actual (response) model; one that does not
    (the evidence contract allows null) makes its whole slot invalid, never a
    silent skip, because a slot whose runtime cannot be established cannot be
    compared with one whose runtime can.
    """

    seen: Counter[str] = Counter()
    unknown: list[SlotKey] = []
    model_attempts = 0
    for row in rows:
        bundle = _read_bundle(directory, row)
        evidence = cast(Mapping[str, Any], bundle.get("runtime_evidence") or {})
        ledger = {
            item.get("attempt_id")
            for item in (evidence.get("provider_calls") or {}).get("items") or []
            if item.get("call_kind") == "completion"
        }
        slot_unknown = False
        for attempt in evidence.get("step_attempts") or []:
            requested, response = (
                attempt.get("requested_model"),
                attempt.get("response_model"),
            )
            for model in (requested, response):
                if _known(model):
                    seen[cast(str, model)] += 1
            if attempt.get("status") == "completed" and _is_model_attempt(
                attempt, ledger
            ):
                model_attempts += 1
                if not (_known(requested) and _known(response)):
                    slot_unknown = True
        if slot_unknown:
            unknown.append((str(row["case_id"]), int(row["repetition"])))
    return {
        "observed": dict(sorted(seen.items())),
        "declared": declared,
        "mismatch": sorted(model for model in seen if model != declared),
        "model_attempts": model_attempts,
        "unknown_model_slots": sorted(unknown),
    }


def runtime_models(leg: Leg) -> Mapping[str, Any]:
    """The models a leg's steps ran on (see `_scan_runtime`)."""

    return (
        leg.scan
        if leg.scan is not None
        else _scan_runtime(leg.directory, leg.rows, leg.runtime_model)
    )


def leg_state(leg: Leg, row: Mapping[str, Any]) -> str:
    """One slot's state in its leg: the sealed row's, unless the leg's bundle
    shows a completed model attempt with no actual model, which is invalid."""

    unknown = {tuple(k) for k in runtime_models(leg)["unknown_model_slots"]}
    if (str(row["case_id"]), int(row["repetition"])) in unknown:
        return "invalid"
    return slot_state(row)


def leg_invalid_class(leg: Leg, row: Mapping[str, Any]) -> str:
    if slot_state(row) != "invalid":
        return "runtime_model_unknown"
    return invalid_class(row)


OUTPUT_VERDICTS = ("pass", "fail", "unmeasured")


def _output_verdict(row: Mapping[str, Any]) -> str | None:
    """The scorer's final-output verdict of a row, or None when the row does not
    carry a valid one (absent `verdict_states`, no `output`, or a value that is
    not pass, fail or unmeasured; a selected case always requires an output)."""

    states = row.get("verdict_states")
    if not isinstance(states, Mapping):
        return None
    output = cast(Mapping[str, Any], states).get("output")
    return output if output in OUTPUT_VERDICTS else None


def slot_state(row: Mapping[str, Any]) -> str:
    """One slot, one state. Reads only what the sealed row says.

    The final-output verdict is the scorer's own (`verdict_states.output`, scorer
    semantics 2): `pass` is fulfilment, `fail` an executed slot that did not
    deliver, and `unmeasured` on a run that was created is an output the scorer
    could not decide (no gold decides it, the harness stopped the run, or it
    delivered nothing to check): an `unmeasured` slot of its own, never a
    failure, never a pass and never an invalid slot (`MAX_INVALID_SLOTS`
    counts invalid evidence only).

    Where a row without a valid verdict is refused. For a receipt whose scorer
    recorded its identity (the frozen H1 scorer, which the freeze requires of
    every decision leg) `verified_receipt` refuses the WHOLE receipt before any
    slot is classified: `receipt_from_summary` requires `verdict_states` on every
    row and validates its dimensions and vocabulary, so a stripped or malformed
    verdict is an integrity error and the decision is NO_DECISION, not an invalid
    slot. The branch below is defence in depth and is reached only by a receipt
    with no scorer identity (which the frozen identity refuses in a decision leg
    but which can still be reported) and by a `not_required` output, which the
    reader accepts and a selected case never has. Either way there is no
    fallback to the legacy `output_success`.
    """

    if row.get("observation_status") in INVALID_STATUSES:
        return "invalid"
    output = _output_verdict(row)
    if output == "pass":
        return "fulfilled"
    if output == "fail":
        return "executed_not_fulfilled"
    if output == "unmeasured":
        return "unmeasured" if row.get("output_executed") is True else "not_executed"
    return "invalid"


def invalid_class(row: Mapping[str, Any]) -> str:
    status = str(row.get("observation_status"))
    if status not in INVALID_STATUSES:
        return (
            "verdict_states_missing"
            if not isinstance(row.get("verdict_states"), Mapping)
            else "verdict_states_invalid"
        )
    if status == "invalid_evidence":
        names = [str(c.get("name")) for c in row.get("evidence_failed_checks") or []]
        return "invalid_evidence:" + (",".join(sorted(set(names))) or "unnamed")
    return f"{status}:{row.get('failure_class')}"


# ---------------------------------------------------------------- the audit

SlotKey = tuple[str, int]


@dataclass(frozen=True, slots=True)
class Correction:
    case_id: str
    kind: str  # required_fact | forbidden_literal
    subject: str
    action: str  # remove | replace
    replacement: str | None
    audit_class: str
    evidence: str


def read_corrections(
    path: Path | None, selection: Mapping[str, Any]
) -> list[Correction]:
    if path is None:
        return []
    known = {str(c["id"]) for c in selection["cases"]}
    corrections: list[Correction] = []
    for raw in json.loads(path.read_text(encoding="utf-8")).get("corrections", []):
        check = cast(Mapping[str, Any], raw.get("check") or {})
        kind = check.get("name")
        subject = check.get("fact") if kind == "required_fact" else check.get("literal")
        action, replacement = raw.get("action"), raw.get("with")
        problems = []
        if raw.get("case_id") not in known:
            problems.append("its case is not in the selection")
        if kind not in ("required_fact", "forbidden_literal"):
            problems.append("check.name must be required_fact or forbidden_literal")
        if not isinstance(subject, str) or not subject:
            problems.append("the check must name its literal (`fact` or `literal`)")
        if action not in ("remove", "replace"):
            problems.append("action must be remove or replace")
        if action == "replace" and (
            not isinstance(replacement, str) or not replacement
        ):
            problems.append("a replacement needs `with`")
        if raw.get("class") not in AUDIT_CLASSES:
            problems.append(f"class must be one of {sorted(AUDIT_CLASSES)}")
        if not str(raw.get("evidence") or "").strip():
            problems.append("evidence is required")
        if problems:
            raise ExperimentError(f"audit correction {raw}: " + "; ".join(problems))
        corrections.append(
            Correction(
                str(raw["case_id"]),
                str(kind),
                str(subject),
                str(action),
                cast("str | None", replacement),
                str(raw["class"]),
                str(raw["evidence"]),
            )
        )
    return corrections


def _harness() -> Any:
    """The harness module, for the one scoring the audit recomputes through.

    Loaded like `run_harness.py` loads it: the table modules first, because the
    harness imports a Builder module whose import chain reaches them.
    """

    name = "ai_builder_api_battle_test"
    if name in sys.modules:
        return sys.modules[name]
    importlib.import_module("eneo.database.tables")
    return importlib.import_module(name)


def corrected_expectation(expect: Any, corrections: Sequence[Correction]) -> Any:
    """A stored output expectation with its corrections applied to the gold it
    was scored by (`_scoring_gold`: the authored gold, or the case's literals).

    A required-fact correction names the check's `fact`: the gold fact id,
    which for a case literal is the literal. A replacement keeps the fact's
    typed contract (type, unit, location) and is validated as that type. A correction that names a check
    the case does not have is refused: an audit corrects an existing check, it
    never invents one.
    """

    gold = _harness()._scoring_gold(expect)
    facts, forbidden = list(gold.facts), list(gold.forbidden)
    for correction in corrections:
        names = (
            [fact.id for fact in facts]
            if correction.kind == "required_fact"
            else forbidden
        )
        if correction.subject not in names:
            raise ExperimentError(
                f"{correction.case_id}: {correction.kind} {correction.subject!r} is not a check of the case"
            )
        index = names.index(correction.subject)
        if correction.kind == "forbidden_literal":
            if correction.action == "remove":
                del forbidden[index]
            else:
                forbidden[index] = cast(str, correction.replacement)
        elif correction.action == "remove":
            location = facts[index].location
            if location is not None and location.kind == "field":
                # Its labels bound the other fields' spans: removing the fact
                # would hand its value to a neighbouring field.
                raise ExperimentError(
                    f"{correction.case_id}: {correction.subject!r} has a field "
                    "location; removing it would move the other fields' "
                    "boundaries, so this audit cannot remove it"
                )
            del facts[index]
        else:
            literal = cast(str, correction.replacement)
            fact = facts[index]
            try:
                # The corrected fact keeps its typed contract (type, unit,
                # location); its value and only form are the replacement,
                # validated as that type. A case literal is its own id.
                facts[index] = type(fact).model_validate(
                    {
                        **fact.model_dump(by_alias=True),
                        "id": literal if fact.id == fact.value else fact.id,
                        "value": literal,
                        "forms": [literal],
                    }
                )
            except ValueError as error:
                raise ExperimentError(
                    f"{correction.case_id}: {literal!r} is no {fact.type} value "
                    f"of {correction.subject!r}: {error}"
                ) from error
    return replace(
        expect, gold=gold.model_copy(update={"facts": facts, "forbidden": forbidden})
    )


def audited_states(leg: Leg, corrections: Sequence[Correction]) -> dict[SlotKey, str]:
    """Per slot, the transition re-scoring its stored output makes, or nothing.

    Every executed, valid slot of a corrected case (fulfilled, failed or
    unmeasured) is re-scored on its stored runtime evidence, with the corrected
    expectation, by the scorer's own output dimension
    (`_rescored_output_state`: `_final_output_scoring` read by
    `_verdict_states`, so a run the harness stopped stays unmeasured); every
    check that is not a corrected literal is recomputed as it was, so a slot
    with any other failed check cannot lift. A pass `lifted` a failed or unmeasured slot,
    a failure `dropped` a fulfilled one or `decided_failed` an unmeasured one,
    and a re-score that cannot decide makes a decided slot `unmeasured`,
    counted apart: never a drop and never a lift (`audited_slot_state`). The
    caller has checked that the harness is the frozen scorer
    (`audit_scorer_problems`).
    """

    by_case: dict[str, list[Correction]] = {}
    for correction in corrections:
        by_case.setdefault(correction.case_id, []).append(correction)
    changes: dict[SlotKey, str] = {}
    if not by_case:
        return changes
    harness = _harness()
    for row in leg.rows:
        case_id = str(row["case_id"])
        state = leg_state(leg, row)
        if case_id not in by_case or state not in (
            "fulfilled",
            "executed_not_fulfilled",
            "unmeasured",
        ):
            continue
        bundle = leg_bundle(leg, row)
        case = cast(Mapping[str, Any], bundle["case"])
        # The gold the stored verdict was scored by, then corrected.
        expect = corrected_expectation(
            harness._observed_output_expectation(case, owner=f"audit {case_id}"),
            by_case[case_id],
        )
        output = harness._rescored_output_state(
            bundle, expect, observation_status=str(row.get("observation_status"))
        )
        key = (case_id, int(row["repetition"]))
        if output not in ("pass", "fail"):
            if state != "unmeasured":
                changes[key] = "unmeasured"
        elif output == "pass" and state != "fulfilled":
            changes[key] = "lifted"
        elif output == "fail" and state == "fulfilled":
            changes[key] = "dropped"
        elif output == "fail" and state == "unmeasured":
            changes[key] = "decided_failed"
    return changes


# A slot's state once the audit re-scored it: one table for the totals and the
# per-case vectors, so both count every transition alike.
_AUDITED_STATE = {
    "lifted": "fulfilled",
    "dropped": "executed_not_fulfilled",
    "decided_failed": "executed_not_fulfilled",
    "unmeasured": "unmeasured",
}


def audited_slot_state(state: str, change: str | None) -> str:
    return _AUDITED_STATE.get(change or "", state)


def audit_scorer_problems(
    freeze: Mapping[str, Any], corrections: Sequence[Correction]
) -> list[str]:
    """Why the audit may not re-score: the harness it would re-score with is
    not the frozen scorer (semantics version and module digest)."""

    if not corrections:
        return []
    harness = _harness()
    ambient = (harness.SCORER_SEMANTICS_VERSION, harness._scorer_sha256())
    frozen = (freeze["scorer_semantics_version"], freeze["scorer_sha256"])
    if ambient != frozen:
        return [
            f"the audit would re-score with scorer {ambient[0]} ({ambient[1]}), "
            f"not the frozen scorer {frozen[0]} ({frozen[1]})"
        ]
    return []


def leg_totals(leg: Leg, audit: Mapping[SlotKey, str]) -> JsonObject:
    states = [leg_state(leg, row) for row in leg.rows]
    counts = Counter(states)
    changes = [
        audit.get((str(row["case_id"]), int(row["repetition"]))) for row in leg.rows
    ]
    audited_counts = Counter(
        audited_slot_state(state, change)
        for state, change in zip(states, changes, strict=True)
    )
    transitions = Counter(change for change in changes if change)
    unmeasured = audited_counts["unmeasured"]
    invalid_classes = Counter(
        leg_invalid_class(leg, row)
        for row, state in zip(leg.rows, states, strict=True)
        if state == "invalid"
    )
    attempted = len(leg.rows)
    executed = (
        counts["fulfilled"] + counts["executed_not_fulfilled"] + counts["unmeasured"]
    )
    audited = audited_counts["fulfilled"]
    decided = attempted - unmeasured
    return {
        "leg": leg.label,
        "arm": leg.arm,
        "runtime_model": leg.runtime_model,
        "receipt_integrity_error": leg.integrity_error,
        "attempted": attempted,
        "invalid_evidence": counts["invalid"],
        "invalid_by_class": dict(sorted(invalid_classes.items())),
        "invalid_but_executed": sum(
            1
            for row, state in zip(leg.rows, states, strict=True)
            if state == "invalid" and row.get("output_executed") is True
        ),
        "executed": executed,
        "not_executed": counts["not_executed"],
        "unmeasured": unmeasured,
        "decided": decided,
        "fulfilled": counts["fulfilled"],
        "audit_lifted": transitions["lifted"],
        "audit_dropped": transitions["dropped"],
        "audit_unmeasured": transitions["unmeasured"],
        # Unmeasured slots the audit decided (lifted or decided_failed).
        "audit_decided": sum(
            1
            for state, change in zip(states, changes, strict=True)
            if state == "unmeasured" and change in ("lifted", "decided_failed")
        ),
        "fulfilled_audited": audited,
        "fulfilled_of_attempted": f"{counts['fulfilled']}/{attempted}",
        "fulfilled_audited_of_attempted": f"{audited}/{attempted}",
        "fulfilled_audited_of_decided": f"{audited}/{decided}",
        "fulfilled_of_executed": f"{counts['fulfilled']}/{executed}",
    }


def per_case(leg: Leg, audit: Mapping[SlotKey, str]) -> dict[str, str]:
    """P fulfilled, p lifted by audit, x dropped by audit, F executed and failed,
    f failed once the audit decided an unmeasured slot, u unmeasured (by the
    scorer or the audit), - not executed, ? invalid. Read with
    `audited_slot_state`, as the totals are."""

    letters: dict[str, list[tuple[int, str]]] = {}
    for row in leg.rows:
        state = leg_state(leg, row)
        key = (str(row["case_id"]), int(row["repetition"]))
        change = audit.get(key)
        letter = {"lifted": "p", "dropped": "x", "decided_failed": "f"}.get(
            change or "",
            {
                "fulfilled": "P",
                "executed_not_fulfilled": "F",
                "unmeasured": "u",
                "not_executed": "-",
                "invalid": "?",
            }[audited_slot_state(state, change)],
        )
        letters.setdefault(key[0], []).append((key[1], letter))
    return {
        case_id: "".join(letter for _, letter in sorted(reps))
        for case_id, reps in letters.items()
    }


def audited_count(vector: str) -> int:
    return sum(1 for letter in vector if letter in "Pp")


def decided_count(vector: str) -> int:
    return sum(1 for letter in vector if letter != "u")


def rule(o: JsonObject, a: JsonObject) -> JsonObject:
    """The pre-registered rule on two legs' audited totals. Callers gate on
    `check_experiment`; use `decide`.

    Each arm's fulfilment is over its decided slots (attempted less
    unmeasured): an unmeasured slot is neither a fulfilment nor a failure.
    Both arms need a decided slot (`_decision_from`). Integer cross-products:
    no float comparison decides anything.
    """

    do, da = o["decided"], a["decided"]
    fo, fa = o["fulfilled_audited"], a["fulfilled_audited"]
    o_ok = 100 * fo >= MIN_O_PERCENT * do
    gap_ok = 100 * (fo * da - fa * do) >= MIN_GAP_POINTS * do * da
    if o_ok and gap_ok:
        outcome = "ADVANCE_EXPLORATORY_PILOT"
    elif not o_ok:
        outcome = "DELIVERY_INVESTIGATION"  # low O is a trigger, not a proven ceiling
    else:
        outcome = "NO_ADVANTAGE_FIX_CONTRACTS_FIRST"
    return {
        "rule": f"audited O >= {MIN_O_PERCENT}% and O - A >= {MIN_GAP_POINTS} points",
        "o_audited": f"{fo}/{do}",
        "a_audited": f"{fa}/{da}",
        "o_percent": round(100 * fo / do, 1),
        "a_percent": round(100 * fa / da, 1),
        "gap_points": round(100 * fo / do - 100 * fa / da, 1),
        "o_threshold_met": o_ok,
        "gap_threshold_met": gap_ok,
        "outcome": outcome,
        "meaning": (
            "an exploratory pilot decision on 20 case clusters, not proof of a "
            "general 20-point advantage"
        ),
    }


def bootstrap_gap(
    o_vectors: Mapping[str, str], a_vectors: Mapping[str, str]
) -> JsonObject:
    """A 90% case-cluster interval of O - A in points. Reported, never gating.

    The three repetitions of one case are not independent, so cases are
    resampled with their repetitions; the draw is seeded, so it is a fact of
    the receipts and not of the run of this script.
    """

    ids = sorted(o_vectors)
    rng = random.Random(BOOTSTRAP_SEED)
    gaps: list[float] = []
    for _ in range(BOOTSTRAP_DRAWS):
        drawn = [ids[rng.randrange(len(ids))] for _ in ids]
        # Each arm over its decided slots in the draw, as the rule divides.
        do = sum(decided_count(o_vectors[c]) for c in drawn)
        da = sum(decided_count(a_vectors[c]) for c in drawn)
        if do and da:
            o = sum(audited_count(o_vectors[c]) for c in drawn)
            a = sum(audited_count(a_vectors[c]) for c in drawn)
            gaps.append(100 * o / do - 100 * a / da)
    gaps.sort()
    return {
        "level": 90,
        "clusters": len(ids),
        "low": round(gaps[int(0.05 * len(gaps))], 1) if gaps else None,
        "high": round(gaps[int(0.95 * len(gaps))], 1) if gaps else None,
        "draws": len(gaps),
        "seed": BOOTSTRAP_SEED,
    }


def strata(
    selection: Mapping[str, Any],
    legs: Sequence[Leg],
    audits: Mapping[str, Mapping[SlotKey, str]],
) -> JsonObject:
    by_id = {str(c["id"]): c for c in selection["cases"]}
    out: JsonObject = {}
    for name, keep in (
        ("held_out", lambda c: c["held_out"] is True),
        ("visible", lambda c: c["held_out"] is not True),
        ("without_input_refusal_class", lambda c: not c.get("f18")),
    ):
        ids = {case_id for case_id, case in by_id.items() if keep(case)}
        row: JsonObject = {"cases": len(ids)}
        for leg in legs:
            vectors = per_case(leg, audits[leg.label])
            row[leg.label] = (
                f"{sum(audited_count(v) for c, v in vectors.items() if c in ids)}"
                f"/{sum(decided_count(v) for c, v in vectors.items() if c in ids)}"
            )
        out[name] = row
    return out


def _decision_from(
    legs: Sequence[Leg], audits: Mapping[str, Mapping[SlotKey, str]]
) -> JsonObject:
    """The rule on a VALID experiment's audited totals, with its interval.

    The rule divides each arm by its decided slots, so the two decision legs'
    unmeasured counts are reported beside it; legs whose counts differ by more
    than MAX_UNMEASURED_DIFFERENCE, or a leg with no decided slot, get
    NO_DECISION with that reason.
    """

    by_label = {leg.label: leg for leg in legs}
    totals = {label: leg_totals(leg, audits[label]) for label, leg in by_label.items()}
    o, a = totals[DECISION_O_LEG], totals[DECISION_A_LEG]
    unmeasured = {DECISION_O_LEG: o["unmeasured"], DECISION_A_LEG: a["unmeasured"]}
    difference = abs(o["unmeasured"] - a["unmeasured"])
    problems = [
        f"{label}: no decided slot (every slot is unmeasured)"
        for label, leg in ((DECISION_O_LEG, o), (DECISION_A_LEG, a))
        if not leg["decided"]
    ]
    if difference > MAX_UNMEASURED_DIFFERENCE:
        problems.append(
            f"unmeasured slots differ between {DECISION_O_LEG} ({o['unmeasured']}) "
            f"and {DECISION_A_LEG} ({a['unmeasured']}) by {difference}, more than "
            f"{MAX_UNMEASURED_DIFFERENCE}: the rule divides each arm by its decided "
            "slots, so the arms are not measured alike"
        )
    if problems:
        return {
            "outcome": "NO_DECISION",
            "problems": problems,
            "unmeasured": unmeasured,
        }
    result = rule(o, a)
    result["unmeasured"] = unmeasured
    result["gap_interval"] = bootstrap_gap(
        per_case(by_label[DECISION_O_LEG], audits[DECISION_O_LEG]),
        per_case(by_label[DECISION_A_LEG], audits[DECISION_A_LEG]),
    )
    result["problems"] = []
    return result


def decide(
    legs: Sequence[Leg],
    selection: Mapping[str, Any],
    freeze: Mapping[str, Any],
    *,
    selection_sha256: str,
    corrections: Sequence[Correction] = (),
    reruns: Sequence[Leg] = (),
    evidence: Sequence[Leg] = (),
) -> JsonObject:
    """The decision, or NO_DECISION with every reason the legs are not the experiment."""

    problems = check_experiment(
        legs,
        selection,
        freeze,
        selection_sha256=selection_sha256,
        reruns=reruns,
        evidence=evidence,
    )
    problems += audit_scorer_problems(freeze, corrections)
    if problems:
        return {"outcome": "NO_DECISION", "problems": problems}
    audits = {leg.label: audited_states(leg, corrections) for leg in legs}
    return _decision_from(legs, audits)


def parse_rerun(text: str, legs: Sequence[Leg]) -> Leg:
    """`LABEL=DIR`: the original receipt a decision leg's replacement supersedes.

    It takes the arm and runtime model of the leg it belongs to; whether it is a
    genuine, eligible original is `check_experiment`'s question.
    """

    label, _, directory = text.partition("=")
    owner = next((leg for leg in legs if leg.label == label), None)
    if owner is None or not directory:
        raise ExperimentError(
            f"--rerun-of must be LABEL=DIR for a decision leg; got {text!r}."
        )
    return parse_leg(f"{label}:{owner.arm}:{owner.runtime_model}={directory}")


EVIDENCE_SUFFIX = " (evidence, not decided on)"


def question_counts(leg: Leg) -> dict[str, JsonObject]:
    """Per case, the question events the leg's VERIFIED rows carry, by question id.

    A row is read only through `verified_receipt`, so a leg whose receipt fails
    it has no rows and no counts (its integrity error is in its totals). A row
    that carries no question record (an oracle-arm row asks nothing) is counted
    apart, never as zero questions.
    """

    counts: dict[str, JsonObject] = {}
    for row in leg.rows:
        entry = counts.setdefault(
            str(row["case_id"]),
            {"rows": 0, "questions": 0, "by_question_id": {}, "rows_without_record": 0},
        )
        entry["rows"] += 1
        ids = (row.get("event_summary") or {}).get("question_event_ids")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            entry["rows_without_record"] += 1
            continue
        entry["questions"] += len(ids)
        for question_id in ids:
            by_id = cast(dict[str, int], entry["by_question_id"])
            by_id[question_id] = by_id.get(question_id, 0) + 1
    return {
        case_id: {
            **entry,
            "by_question_id": dict(sorted(entry["by_question_id"].items())),
        }
        for case_id, entry in sorted(counts.items())
    }


def _display_labels(legs: Sequence[Leg]) -> list[str]:
    """Unique keys for a report; a repeated label shows its receipt's position."""

    counts = Counter(leg.label for leg in legs)
    return [
        leg.label if counts[leg.label] == 1 else f"{leg.label}[{index}]"
        for index, leg in enumerate(legs)
    ]


def report(args: argparse.Namespace) -> JsonObject:
    """Totals for every leg and the decision, from one validation of the legs.

    The audit is computed once, after the experiment is validated: an invalid
    experiment is reported on its raw counts and gets no decision. Original
    receipts of a re-run and evidence receipts are reported beside the decision
    legs, never instead of them.
    """

    selection_path = Path(args.selection)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    freeze = load_freeze(Path(args.freeze) if getattr(args, "freeze", None) else None)
    legs = [parse_leg(text) for text in args.leg]
    reruns = [parse_rerun(text, legs) for text in getattr(args, "rerun_of", None) or []]
    evidence = [parse_leg(text) for text in getattr(args, "evidence_leg", None) or []]
    corrections = read_corrections(Path(args.audit) if args.audit else None, selection)
    problems = check_experiment(
        legs,
        selection,
        freeze,
        selection_sha256=_sha256_file(selection_path),
        reruns=reruns,
        evidence=evidence,
    )
    clash = {leg.label for leg in legs} & {leg.label for leg in evidence}
    duplicate_evidence = [
        label for label, n in Counter(e.label for e in evidence).items() if n > 1
    ]
    problems += [
        f"evidence label {label} repeats a decision leg" for label in sorted(clash)
    ]
    problems += [f"duplicate evidence label {label}" for label in duplicate_evidence]
    problems += audit_scorer_problems(freeze, corrections)
    keys = _display_labels(legs)
    if problems:
        audits: dict[str, Mapping[SlotKey, str]] = {k: {} for k in keys}
        decision: JsonObject = {"outcome": "NO_DECISION", "problems": problems}
    else:
        audits = {leg.label: audited_states(leg, corrections) for leg in legs}
        decision = _decision_from(legs, audits)
    result: JsonObject = {
        "totals": {key: leg_totals(leg, audits[key]) for key, leg in zip(keys, legs)},
        "per_case": {key: per_case(leg, audits[key]) for key, leg in zip(keys, legs)},
        "strata": strata(
            selection, legs, {leg.label: audits[key] for key, leg in zip(keys, legs)}
        )
        if not problems
        else {},
        "runtime_models": {key: runtime_models(leg) for key, leg in zip(keys, legs)},
        # The receipts a re-run superseded, first-class in the report: a reader
        # sees both, and the decision names which one decided.
        "superseded_receipts": {
            f"{leg.label} (original)": leg_totals(leg, {}) for leg in reruns
        },
        "evidence_legs": {
            leg.label: leg_totals(leg, {})
            for leg in evidence
            if leg.label not in refused_evidence(evidence)
        },
        "refused_evidence": refused_evidence(evidence),
        # The questions the Builder raised, reported and never gating: the
        # extra questions a complete brief still draws are part of what arm A
        # measures.
        # Evidence legs live under their own display keys, so an evidence leg
        # that shares a decision leg's label never replaces its counts.
        "question_counts": {
            **{key: question_counts(leg) for key, leg in zip(keys, legs)},
            **{
                f"{key}{EVIDENCE_SUFFIX}": question_counts(leg)
                for key, leg in zip(_display_labels(evidence), evidence)
                if leg.label not in refused_evidence(evidence)
            },
        },
        "corrections": [
            {
                "case_id": c.case_id,
                "check": {"name": c.kind, "subject": c.subject},
                "action": c.action,
                "with": c.replacement,
                "class": c.audit_class,
                "evidence": c.evidence,
            }
            for c in corrections
        ],
        "decision": decision,
    }
    probe_suite = getattr(args, "probe_suite", None)
    if probe_suite:
        result["intake_probe"] = probe_builder_intake(Path(probe_suite), freeze=freeze)
    return result


def render_markdown(result: Mapping[str, Any]) -> str:
    lines: list[str] = []
    decision = result["decision"]
    if decision["outcome"] == "NO_DECISION":
        lines += ["**NO DECISION.** The legs are not the frozen experiment:"]
        lines += [f"- {problem}" for problem in decision["problems"]]
        lines += [""]
    if decision.get("unmeasured"):
        lines += [
            "Unmeasured slots (neither fulfilled nor failed; the rule divides each "
            "arm by its decided slots): "
            + ", ".join(f"{k} {v}" for k, v in decision["unmeasured"].items()),
            "",
        ]
    if decision["outcome"] != "NO_DECISION":
        interval = decision["gap_interval"]
        lines += [
            f"**Interval (read this first)**: O - A is {decision['gap_points']} points "
            f"(audited {decision['o_audited']} against {decision['a_audited']}); the "
            f"{interval['level']}% case-cluster interval over {interval['clusters']} "
            f"cases is {interval['low']} to {interval['high']} points.",
            "",
            f"Decision ({decision['rule']}): **{decision['outcome']}**, "
            f"{decision['meaning']}.",
            "",
        ]
    lines += [
        "| leg | arm | runtime | attempted | invalid | executed | unmeasured | fulfilled | audited (lifted/dropped/unmeasured/decided) | audited of decided | of executed |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    rows = [
        (name, total)
        for name, total in (
            *result["totals"].items(),
            *(result.get("superseded_receipts") or {}).items(),
            *(
                (f"{name}{EVIDENCE_SUFFIX}", total)
                for name, total in (result.get("evidence_legs") or {}).items()
            ),
        )
    ]
    for name, total in rows:
        if total.get("receipt_integrity_error"):
            name = f"{name} (RECEIPT REFUSED)"
        lines.append(
            f"| {name} | {total['arm']} | {total['runtime_model']} | {total['attempted']} "
            f"| {total['invalid_evidence']} | {total['executed']} | {total['unmeasured']} "
            f"| {total['fulfilled_of_attempted']} "
            f"| {total['fulfilled_audited_of_attempted']} ({total['audit_lifted']}/{total['audit_dropped']}"
            f"/{total['audit_unmeasured']}/{total['audit_decided']}) "
            f"| {total['fulfilled_audited_of_decided']} "
            f"| {total['fulfilled_of_executed']} |"
        )
    refused = result.get("refused_evidence") or {}
    if refused:
        lines += [""]
        lines += [
            f"Refused evidence receipt {name} (never decided on): {why}"
            for name, why in refused.items()
        ]
    lines += [
        "",
        "Invalid evidence by class: "
        + json.dumps(
            {name: t["invalid_by_class"] for name, t in rows},
            ensure_ascii=False,
        ),
        "",
        "Per case (P fulfilled, p lifted by audit, x dropped by audit, F executed and failed, f failed once the audit decided it, u unmeasured, - not executed, ? invalid):",
    ]
    labels = list(result["per_case"])
    lines += ["| case | " + " | ".join(labels) + " |", "|---|" + "---|" * len(labels)]
    case_ids = sorted({c for vector in result["per_case"].values() for c in vector})
    for case_id in case_ids:
        lines.append(
            f"| {case_id} | "
            + " | ".join(
                result["per_case"][label].get(case_id, " ") for label in labels
            )
            + " |"
        )
    counts = result.get("question_counts") or {}
    if any(counts.values()):
        lines += [
            "",
            "Questions the Builder raised (verified rows: asked over rows with a record, by question id; UNKNOWN when no row has a record):",
        ]
        count_labels = list(counts)
        lines += [
            "| case | " + " | ".join(count_labels) + " |",
            "|---|" + "---|" * len(count_labels),
        ]
        for case_id in sorted({c for per in counts.values() for c in per}):
            lines.append(
                f"| {case_id} | "
                + " | ".join(
                    _question_cell(counts[label].get(case_id)) for label in count_labels
                )
                + " |"
            )
    probe = result.get("intake_probe")
    if probe:
        lines += ["", *_probe_lines(probe)]
    return "\n".join(lines) + "\n"


def _question_cell(entry: Mapping[str, Any] | None) -> str:
    if not entry:
        return " "
    missing = entry["rows_without_record"]
    recorded = entry["rows"] - missing
    if recorded == 0:
        # A row with no record says nothing about its questions: not a zero.
        return "UNKNOWN"
    detail = ", ".join(f"{qid} x{n}" for qid, n in entry["by_question_id"].items())
    return (
        f"{entry['questions']}/{recorded}"
        + (f" ({detail})" if detail else "")
        + (f", {missing} of {entry['rows']} rows without a record" if missing else "")
    )


def _probe_lines(probe: Mapping[str, Any]) -> list[str]:
    if probe["refusals"]:
        return [
            "Intake probe REFUSED (not evaluated): " + "; ".join(probe["refusals"]),
        ]
    original = probe["original_criterion"]
    return [
        f"Intake probe, claim: {probe['claim']}",
        f"- amended criterion ({probe['criterion']}): "
        f"**{'PASS' if probe['passed'] else 'FAIL'}**",
        f"- original criterion ({original['criterion']}): "
        f"**{'PASS' if original['passed'] else 'FAIL'}**",
        f"- first-message uptake: **{str(probe['first_message_uptake']).upper()}**",
    ]


def _tree_scorer_identity(tree: Path) -> tuple[int, str]:
    """The scorer identity a leg run from `tree` will record in its receipt.

    Asked of that tree's own harness (`SCORER_SEMANTICS_VERSION`,
    `_scorer_sha256`), in a child process loaded as `run_harness.py` loads it, so
    the freeze never restates how the harness digests its scoring modules.
    """

    import subprocess

    code = (
        "import eneo.database.tables, ai_builder_api_battle_test as h;"
        "print(h.SCORER_SEMANTICS_VERSION, h._scorer_sha256())"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tree / "backend" / "scripts",
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [str(tree / "backend" / "src"), str(tree / "backend" / "scripts")]
            ),
        },
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    return int(out[-2]), out[-1]


_SCRIPTS_DIR = "backend/scripts"
# The code and data roots the freeze reads from, in one place: the harness and
# everything it imports (some by a computed name), the fixtures the corpus names,
# the docs an author is given. No untracked file may sit under any of them.
SOURCE_ROOTS = (
    "backend/src",
    "backend/scripts",
    "backend/tests/fixtures",
    "docs",
    "frontend/apps/docs-site/src",
)


def require_clean_tree(tree: Path) -> None:
    """The whole worktree is its HEAD, and nothing untracked sits in a source root.

    The freeze records `git rev-parse HEAD` and stages, authors and regenerates
    from files in `tree`. The bytes it read are the commit's only if the tree is:
    a tracked file modified or staged anywhere, or a file untracked under a code
    or data root (a new module the harness imports, a new fixture, a scratch doc),
    could otherwise be read, authored against and reset before the legs run,
    under a commit id that does not contain it. The guard is deliberately the
    plain one: it needs no list of what the code imports (a computed import name
    defeats such a list), and it names every path that refuses the freeze.
    """

    import subprocess

    def status(*args: str) -> list[str]:
        shown = subprocess.run(
            ["git", "-C", str(tree), "status", "--porcelain", *args],
            capture_output=True,
            text=True,
        )
        if shown.returncode != 0:
            raise ExperimentError(
                f"{tree} is not a git worktree: {shown.stderr.strip()}"
            )
        return [line for line in shown.stdout.splitlines() if line]

    tracked = status("--untracked-files=no")
    untracked = [
        line
        for line in status("--untracked-files=all", "--", *SOURCE_ROOTS)
        if line.startswith("?? ")
    ]
    dirty = [*tracked, *untracked]
    if dirty:
        shown = ", ".join(e[3:] for e in dirty[:10])
        more = f" and {len(dirty) - 10} more" if len(dirty) > 10 else ""
        raise ExperimentError(
            f"the tree {tree} is not clean at HEAD: {shown}{more}. Commit, restore "
            f"or remove them (untracked files are refused under {', '.join(SOURCE_ROOTS)}), "
            "then freeze."
        )


def _head_blob_ids(tree: Path) -> dict[str, str]:
    """Path -> blob id of every file at the tree's HEAD (empty if it is no repository)."""

    import subprocess

    shown = subprocess.run(
        ["git", "-C", str(tree), "ls-tree", "-r", "-z", "HEAD"], capture_output=True
    )
    if shown.returncode != 0:
        return {}
    ids: dict[str, str] = {}
    for entry in shown.stdout.split(b"\0"):
        if entry:
            meta, _, path = entry.partition(b"\t")
            ids[path.decode()] = meta.split()[2].decode()
    return ids


def _git_blob_id(data: bytes) -> str:
    return hashlib.sha1(
        b"blob %d\0" % len(data) + data, usedforsecurity=False
    ).hexdigest()


def require_bytes_at_head(tree: Path, used: Mapping[str, bytes]) -> None:
    """Every source the freeze used is, byte for byte, its blob at `tree`'s HEAD.

    The freeze records `git rev-parse HEAD`; that is only true of the bytes it
    read if they ARE that commit's. A modified or untracked source (a doc, a
    fixture, the corpus, the code that stages, renders or totals) could otherwise
    be staged from, authored against and frozen under a commit id that does not
    contain it, then reset before the legs run. `used` maps a tree-relative path
    to the bytes that were read; a blob id is what `git show HEAD:<path>` hashes to.
    """

    committed = _head_blob_ids(tree)
    stale = sorted(
        relative
        for relative, data in used.items()
        if committed.get(relative) != _git_blob_id(data)
    )
    if stale:
        raise ExperimentError(
            f"these sources are not the bytes of HEAD in {tree} (modified, untracked "
            f"or from another tree): {stale[:10]}"
            + (f" and {len(stale) - 10} more" if len(stale) > 10 else "")
            + ". Commit or restore them, then freeze."
        )


def write_freeze_record(
    *,
    out: Path,
    tree: Path,
    h1_sha: str,
    selection_path: Path,
    specs_dir: Path,
    material_dir: Path,
    builder_model_id: str,
) -> JsonObject:
    """The freeze record, once, from the tree the legs will run on.

    Everything in it is read from disk: the scorer's revision and harness digest
    from `tree`, the frozen selection, the spec manifest, this script, and the
    intake text digest of every case, RECOMPUTED from the staged `request.md`
    and `answers.md` (`verify_staged_case`); a manifest's own claim is never
    trusted. The tree must be clean at HEAD (`require_clean_tree`), so the commit
    the record names IS the bytes read; the scripts running the freeze and the
    selection must be that commit's too. The staged material and docs are verified
    against their manifests, and then against their SOURCES: every file is
    regenerated from the tree's own corpus, fixtures and docs and compared byte
    for byte (`verify_against_source`), because a manifest can be edited together
    with the file it describes. The specs' manifest must say it was authored from
    exactly this material and these docs.
    """

    import subprocess

    stage = importlib.import_module("ai_builder_oracle_stage")
    require_clean_tree(tree)
    # The code running this freeze is the tree's own, by path (not by bytes: two
    # clean checkouts can hold equal scripts and different modules under them).
    try:
        code_identity.require_code_from_tree(tree, what="The freeze")
    except code_identity.CodeIdentityError as error:
        raise ExperimentError(str(error)) from error
    require_bytes_at_head(
        tree,
        {f"{_SCRIPTS_DIR}/ai_builder_oracle_cases.json": selection_path.read_bytes()},
    )
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    case_ids = [str(case["id"]) for case in selection["cases"]]
    material = {
        case_id: stage.verify_staged_case(material_dir / case_id)
        for case_id in case_ids
    }
    material_sha256 = stage.material_digest(material_dir, case_ids)
    docs_sha256 = stage.verify_docs(material_dir)
    cases_file = tree / "backend" / "scripts" / "ai_builder_api_municipal_cases.json"
    fixtures = tree / "backend" / "scripts" / "fixtures" / "ai_builder_battle"
    stage.verify_against_source(
        material_dir, case_ids, cases_file=cases_file, fixtures=fixtures, repo=tree
    )
    specs = json.loads((specs_dir / "manifest.json").read_text(encoding="utf-8"))
    if set(specs["cases"]) != set(case_ids):
        raise ExperimentError("the spec manifest is not for exactly the selection.")
    for case_id, entry in specs["cases"].items():
        authoring = cast(Mapping[str, Any], entry.get("authoring") or {})
        if (
            authoring.get("material_manifest_sha256") != material_sha256
            or authoring.get("docs_manifest_sha256") != docs_sha256
        ):
            raise ExperimentError(
                f"{case_id}: the spec was not authored from this staged material and docs."
            )
    scripts = tree / "backend" / "scripts"
    scorer_version, scorer_sha256 = _tree_scorer_identity(tree)
    record: JsonObject = {
        "schema_version": 1,
        "h1_sha": h1_sha,
        "scorer_source_revision": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tree,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "harness_sha256": _sha256_file(scripts / "ai_builder_api_battle_test.py"),
        "scorer_semantics_version": scorer_version,
        "scorer_sha256": scorer_sha256,
        "cases_sha256": _sha256_file(scripts / "ai_builder_api_municipal_cases.json"),
        "selection_sha256": _sha256_file(selection_path),
        "oracle_manifest_sha256": _sha256_file(specs_dir / "manifest.json"),
        "totals_sha256": _sha256_file(Path(__file__)),
        "builder_model_id": builder_model_id,
        "intake_message_sha256_by_id": material,
        "material_manifest_sha256": material_sha256,
        "docs_manifest_sha256": docs_sha256,
        "legs": {
            "A_luna6": {"arm": "builder", "runtime_model": "gpt-6-luna"},
            "O_luna6": {"arm": "oracle", "runtime_model": "gpt-6-luna"},
            "O_gemma": {"arm": "oracle", "runtime_model": "gemma4-31b-it"},
        },
    }
    with out.open("x", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=1, sort_keys=True)
    return record


DESIGNATED_PROBE_CASE = "mc_nar07_arbetsgivarintyg"
PROBE_REPETITIONS = 3


def _probe_refusals(
    summary: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    freeze: Mapping[str, Any],
) -> list[str]:
    """Why a verified receipt is not the one the smoke is defined on.

    The criterion is a statement about ONE complete, verified, up-front,
    three-repetition Builder receipt of the ONE preregistered case
    (`DESIGNATED_PROBE_CASE`, not selectable); anything else is refused before
    any bundle is looked at. The receipt's integrity (manifest membership,
    bundle digests, sealed rows) was verified by `verified_receipt` already.
    """

    case_id = DESIGNATED_PROBE_CASE
    refusals: list[str] = []
    identity = cast(Mapping[str, Any], summary.get("evaluator_identity") or {})
    context = cast(Mapping[str, Any], identity.get("run_context") or {})
    reps = sorted(int(r["repetition"]) for r in rows if "repetition" in r)
    if (
        len(rows) != PROBE_REPETITIONS
        or reps != list(range(1, PROBE_REPETITIONS + 1))
        or {r.get("case_id") for r in rows} != {case_id}
    ):
        refusals.append(
            f"the receipt is not exactly {PROBE_REPETITIONS} distinct repetitions "
            f"(1..{PROBE_REPETITIONS}) of {case_id}"
        )
    claimed = cast(Mapping[str, Any], summary.get("receipt_integrity") or {})
    if claimed.get("status") != "complete":
        refusals.append("the receipt does not claim to be complete")
    if context.get("arm", "builder") != "builder":
        refusals.append("the receipt is not a Builder receipt")
    if context.get("intake_answers") != "upfront":
        refusals.append("the answers were not given up front")
    digest = cast(Mapping[str, Any], context.get("intake_answers_sha256_by_id") or {})
    if digest.get(case_id) != freeze["intake_message_sha256_by_id"].get(case_id):
        refusals.append("the text sent is not the frozen author material for the case")
    if identity.get("requested_model_id") != freeze["builder_model_id"]:
        refusals.append("the Builder model is not the frozen one")
    for field, key in (
        ("harness_sha256", "harness_sha256"),
        ("scorer_semantics_version", "scorer_semantics_version"),
        ("scorer_sha256", "scorer_sha256"),
        ("source_revision", "scorer_source_revision"),
    ):
        if identity.get(field) != freeze[key]:
            refusals.append(f"{field} is not the frozen scorer's")
    if _dirty_source(summary):
        refusals.append("the probe run recorded a dirty (or unknown) tracked source")
    target = cast(
        Mapping[str, Any], (summary.get("release_identity") or {}).get("target") or {}
    )
    revision = str(freeze["scorer_source_revision"])
    if (
        target.get("verified") is not True
        or target.get("expected_source_revision") != revision
        or target.get("version") != f"DEV-{revision[:12]}"
        or summary.get("suite_identity_failed_check_count") != 0
    ):
        refusals.append("the deployed revision was not verified as the frozen tree's")
    return refusals


# The Builder's field-collection question: the turn controller asks it while
# the confirmed input fields are absent (`_runtime_input_field_details_required`
# in ai_builder_turn_controller.py), and the harness answers it from the
# case's configured answers (`_configured_question_answer`).
FIELD_COLLECTION_QUESTION_ID = "runtime_metadata_field_details"

PROBE_CLAIM = (
    "eventual field correctness: the plan's form fields equal the configured "
    "answers. It says nothing about whether the first message alone was read."
)
PROBE_CRITERION = (
    "the plan's form fields equal the answer's fields (names and types) in all "
    "three repetitions, and every field-collection question the Builder asked "
    "was answered from the same configured answers"
)
PROBE_ORIGINAL_CRITERION = (
    "the plan's form fields equal the answer's fields (names and types) and "
    "the Builder did not ask for them again, in all three repetitions"
)


def _probe_outcome(
    refusals: list[str], results: list[JsonObject], *, passed: bool
) -> JsonObject:
    """The probe's answer: the amended criterion, and beside it the original one.

    The original criterion (fields equal AND no field question asked) is kept
    in every answer so a reader still sees that the Builder asked again.
    """

    uptakes = {str(r["first_message_uptake"]) for r in results}
    return {
        "claim": PROBE_CLAIM,
        "criterion": PROBE_CRITERION,
        "refusals": refusals,
        "results": results,
        "passed": passed,
        # Known only when no structured answer preceded the plan; a mix of
        # states establishes nothing.
        "first_message_uptake": uptakes.pop() if len(uptakes) == 1 else "unknown",
        "original_criterion": {
            "criterion": PROBE_ORIGINAL_CRITERION,
            "passed": bool(results) and all(r["original_passed"] for r in results),
        },
    }


def _journey_questions(bundle: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    journey = cast(Mapping[str, Any], bundle.get("journey") or {})
    return [
        q
        for q in cast(list[Any], journey.get("questions") or [])
        if isinstance(q, dict)
    ]


def _answered_from_configured_answers(question: Mapping[str, Any]) -> bool:
    """The harness answered this question, and from the case's configured answers
    (`configured_answer_source` is set only on that path)."""

    return (
        question.get("answer_source") is not None
        and question.get("answer_turn") is not None
    )


def probe_builder_intake(suite_dir: Path, *, freeze: Mapping[str, Any]) -> JsonObject:
    """The behavioural check of the Builder smoke with answers up front.

    Defined on one suite directory: the Builder's complete, verified, up-front
    receipt of three repetitions of the preregistered case
    `mc_nar07_arbetsgivarintyg` (`_probe_refusals`; a receipt that is not that,
    or that fails the receipt reader's integrity checks, is refused, not
    evaluated, and no other case can be probed).

    The claim is eventual field correctness, not prose uptake. The harness
    answers a field-collection question the Builder asks from the same
    configured answers the first message states, so a plan whose fields equal
    the answers after that structured answer does not show what the first
    message alone carried. A bundle passes when its plan's form fields are
    exactly the fields the case's answer names, with their types, and every
    field-collection question the Builder asked was answered from the
    configured answers. First-message uptake is reported `unknown` whenever a
    structured answer preceded the plan. The original criterion (the same
    fields and no question asked) is reported beside it, per bundle and overall.
    """

    case_id = DESIGNATED_PROBE_CASE
    try:
        verified = verified_receipt(suite_dir)
    except receipt.ReceiptError as error:
        return _probe_outcome(
            [f"the receipt is not an intact record of its run: {error}"],
            [],
            passed=False,
        )
    summary = verified.summary
    rows = [dict(observation.row) for observation in verified.observations]
    refusals = _probe_refusals(summary, rows, freeze=freeze)
    if refusals:
        return _probe_outcome(refusals, [], passed=False)
    results: list[JsonObject] = []
    for row in sorted(rows, key=lambda r: int(r["repetition"])):
        bundle = _read_bundle(suite_dir, row)
        case = cast(Mapping[str, Any], bundle["case"])
        answered = cast(
            Mapping[str, Any],
            (case.get("configured_question_answers") or {}).get(
                FIELD_COLLECTION_QUESTION_ID
            )
            or {},
        )
        wanted = {
            str(f["value"]["name"]): str(f["value"]["type"])
            for f in answered.get("input_fields") or []
        }
        spec = ((bundle.get("plan") or {}).get("proposal") or {}).get("spec") or {}
        planned = {
            str(f["name"]): str(f["type"]) for f in spec.get("form_fields") or []
        }
        asked = list(
            (bundle.get("event_summary") or {}).get("question_event_ids") or []
        )
        field_questions = [
            q
            for q in _journey_questions(bundle)
            if q.get("question_id") == FIELD_COLLECTION_QUESTION_ID
        ]
        asked_field_question = FIELD_COLLECTION_QUESTION_ID in asked
        # Every occurrence in the event record needs its own answered record.
        field_answered = (
            len(field_questions) == asked.count(FIELD_COLLECTION_QUESTION_ID)
            and all(_answered_from_configured_answers(q) for q in field_questions)
            if asked_field_question
            else None
        )
        structured_answer_first = any(
            _answered_from_configured_answers(q) for q in _journey_questions(bundle)
        )
        identified = (
            case.get("id") == case_id
            and bundle.get("repetition") == row["repetition"]
            and bool(wanted)
        )
        fields_match = identified and planned == wanted
        prompt = str(case.get("prompt") or "")
        results.append(
            {
                "repetition": int(row["repetition"]),
                "bundle": row["bundle_file"],
                "answer_names": sorted(wanted),
                "names_absent_from_prompt": sorted(
                    n for n in wanted if n not in prompt
                ),
                "planned": planned,
                "eventual_fields_match": fields_match,
                "asked_again": asked_field_question,
                "field_question_answered_from_configured_answers": field_answered,
                "first_message_uptake": (
                    "unknown"
                    if structured_answer_first
                    else ("observed" if fields_match else "not_observed")
                ),
                "original_passed": fields_match and not asked_field_question,
                "passed": fields_match and field_answered is not False,
            }
        )
    return _probe_outcome(
        [], results, passed=bool(results) and all(r["passed"] for r in results)
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report")
    rep.add_argument("--selection", required=True)
    rep.add_argument("--freeze", required=True)
    rep.add_argument("--leg", action="append", required=True)
    rep.add_argument(
        "--evidence-leg",
        action="append",
        default=None,
        help="an extra receipt, reported under its own label and never decided on",
    )
    rep.add_argument(
        "--rerun-of",
        action="append",
        default=None,
        metavar="LABEL=DIR",
        help=(
            "the ORIGINAL receipt of a leg whose replacement is passed as --leg "
            "(needs more than 6 invalid slots; at most one per leg)"
        ),
    )
    rep.add_argument("--audit", default=None)
    rep.add_argument(
        "--probe-suite",
        default=None,
        help="the Builder smoke's suite directory: its intake probe is reported, never decided on",
    )
    rep.add_argument("--format", choices=("markdown", "json"), default="markdown")
    probe = sub.add_parser(
        "intake-probe", help="the behavioural check of the Builder smoke"
    )
    probe.add_argument("--suite", required=True, help="the smoke's suite directory")
    probe.add_argument("--freeze", required=True)
    frz = sub.add_parser("freeze", help="write the freeze record, once")
    frz.add_argument("--out", required=True)
    frz.add_argument("--tree", required=True)
    frz.add_argument("--h1-sha", required=True)
    frz.add_argument("--selection", required=True)
    frz.add_argument("--specs-dir", required=True)
    frz.add_argument("--material-dir", required=True)
    frz.add_argument("--builder-model-id", required=True)
    args = parser.parse_args(argv)
    if args.command == "intake-probe":
        outcome = probe_builder_intake(
            Path(args.suite), freeze=load_freeze(Path(args.freeze))
        )
        print(json.dumps(outcome, ensure_ascii=False, indent=1))
        return 0 if outcome["passed"] else 4
    if args.command == "freeze":
        write_freeze_record(
            out=Path(args.out),
            tree=Path(args.tree),
            h1_sha=args.h1_sha,
            selection_path=Path(args.selection),
            specs_dir=Path(args.specs_dir),
            material_dir=Path(args.material_dir),
            builder_model_id=args.builder_model_id,
        )
        print(f"froze {args.out}")
        return 0
    try:
        result = report(args)
    except ExperimentError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(result, ensure_ascii=False, indent=1)
        if args.format == "json"
        else render_markdown(result)
    )
    return 3 if result["decision"]["outcome"] == "NO_DECISION" else 0


if __name__ == "__main__":
    raise SystemExit(main())
