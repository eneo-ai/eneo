"""Fail-closed receipt reading for the AI Builder battle instrument.

Both consumers of a `suite-summary.json` receipt — the harness that writes it
and the comparator that scores it — need the same answer to "is this receipt
readable at all". They did not have one: the comparator's loader skipped every
row that was not a dict or carried no `case_id`, so a truncated or corrupted
receipt compared as a smaller, healthier run. A release verdict computed that
way is worse than no verdict.

Two levels of trust, deliberately separated:

* `load_summary_receipt` reads one summary file, strictly. Nothing is skipped
  and nothing malformed is normalized to an empty value; a field that is
  present but unreadable raises. This is what the comparator needs for
  historical receipts, whose bundles may be long gone.
* `load_release_receipt` reads a whole suite directory and re-derives what the
  summary claims about itself: the manifest's expected slots, each case
  contract hash, every bundle digest, and every derivable acquisition
  projection. The final target recheck remains a trusted measurement payload;
  preventing coordinated artifact rewriting requires signing or immutable
  storage outside this reader's boundary.

This module holds no product judgement — which observations count as a win is
the release gate's arithmetic (`ai_builder_release_gate.py`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

JsonObject = dict[str, Any]

SUITE_SUMMARY_FILE = "suite-summary.json"
RELEASE_MANIFEST_FILE = "release-manifest.json"
REPLACEMENTS_FILE = "replacements.json"
# The artifact contract every consumer of these receipts speaks. It lives here
# because the harness writes it and the release reader refuses anything else;
# two copies of a schema version is how a reader ends up scoring a shape it
# does not understand.
SUPPORTED_RECEIPT_ARTIFACT_VERSION = "ai-builder-live-release.v5"
RELEASE_SUMMARY_ARTIFACT_MODE = "live_execution_summary"
# The two tracked inputs whose digests a release receipt records. Re-hashing
# them at judging time is only meaningful because the evaluator is pinned to
# the receipt's own revision with a clean tree (release gate row 14).
_SCRIPTS_DIR = Path(__file__).resolve().parent
HARNESS_FILE = "ai_builder_api_battle_test.py"
CASES_FILE = "ai_builder_api_battle_cases.json"
BUNDLE_FILE_FIELD = "bundle_file"
BUNDLE_SHA256_FIELD = "bundle_sha256"
# These describe the bundle artifact itself, so they cannot be sealed inside
# the bundle before its filename and digest exist.
BUNDLE_REFERENCE_FIELDS = frozenset({BUNDLE_FILE_FIELD, BUNDLE_SHA256_FIELD})
_REPLACEMENT_FIELDS = frozenset(
    {
        "case_id",
        "repetition",
        "reason",
        "original_bundle_sha256",
        "replacement_bundle_sha256",
    }
)


class ReceiptError(ValueError):
    """A receipt cannot be read as the run it claims to be."""


def _mapping(value: Any, *, where: str, key: str) -> Mapping[str, Any]:
    """A missing object reads as empty; a present non-object is a defect."""

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ReceiptError(f"{where}: {key} must be an object.")
    return cast(Mapping[str, Any], value)


def _sequence(value: Any, *, where: str, key: str) -> tuple[Any, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ReceiptError(f"{where}: {key} must be an array.")
    return tuple(cast(Sequence[Any], value))


def _string_tuple(value: Any, *, where: str, key: str) -> tuple[str, ...]:
    items = _sequence(value, where=where, key=key)
    for item in items:
        if not isinstance(item, str) or not item:
            raise ReceiptError(f"{where}: {key} must contain non-empty strings.")
    return cast(tuple[str, ...], items)


def _optional_int(value: Any, *, where: str, key: str) -> int | None:
    """Measurements are counts, durations and sizes: never negative.

    A negative repair count or token total is not a small anomaly — it makes a
    budget row cheaper, so it has to be refused rather than scored.
    """

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReceiptError(f"{where}: {key} must be an integer.")
    if value < 0:
        raise ReceiptError(f"{where}: {key} must not be negative.")
    return value


def _required_str(payload: Mapping[str, Any], key: str, *, where: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ReceiptError(f"{where}: {key} must be a non-empty string.")
    return value


@dataclass(frozen=True, slots=True)
class Observation:
    """One case repetition, as the receipt recorded it."""

    case_id: str
    repetition: int
    required: bool
    observation_status: str
    outcome_class: str
    expectation_verdict: str
    case_contract_sha256: str
    bundle_file: str
    bundle_sha256: str
    failed_check_names: tuple[str, ...]
    repair_attempts: int | None
    failure_codes: tuple[str, ...]
    # Every rung of the repair ladder, WITH multiplicity: an invariant that
    # fired three times across the ladder is three events, not one.
    ladder_failure_codes: tuple[str, ...]
    chosen_patterns: frozenset[str]
    provider_dispositions: tuple[str, ...]
    model_calls: int | None
    total_tokens: int | None
    elapsed_ms: int | None
    # The row as written. The release gate reads only the typed fields above;
    # the comparator reports on the whole receipt, and giving it the raw row
    # here is what lets it drop its own tolerant loader instead of keeping a
    # second, laxer reading of the same file.
    row: Mapping[str, Any]

    @property
    def slot(self) -> tuple[str, int]:
        return (self.case_id, self.repetition)


@dataclass(frozen=True, slots=True)
class ReplacementDescriptor:
    """One operator-directed substitution of a provider-faulted slot."""

    case_id: str
    repetition: int
    reason: str
    original_bundle_sha256: str
    replacement_bundle_sha256: str

    @property
    def slot(self) -> tuple[str, int]:
        return (self.case_id, self.repetition)

    def as_json(self) -> JsonObject:
        return {
            "case_id": self.case_id,
            "repetition": self.repetition,
            "reason": self.reason,
            "original_bundle_sha256": self.original_bundle_sha256,
            "replacement_bundle_sha256": self.replacement_bundle_sha256,
        }


@dataclass(frozen=True, slots=True)
class Receipt:
    """A suite receipt parsed into the facts a verdict may be built from."""

    artifact_schema_version: str
    artifact_mode: str
    source_revision: str
    repetitions: int
    observations: tuple[Observation, ...]
    # True only when the manifest and bundles were re-verified from disk.
    integrity_verified: bool
    # The decoded receipt, for consumers that report on identity and run
    # context rather than on observations.
    summary: Mapping[str, Any]
    # The base summary remains an immutable historical projection. The typed
    # observations above carry the applied overlay; keeping its descriptors
    # here makes the substitution explicit without manufacturing a new summary.
    replacements: tuple[ReplacementDescriptor, ...] = ()

    @property
    def case_ids(self) -> frozenset[str]:
        return frozenset(observation.case_id for observation in self.observations)

    @property
    def replaced_slots(self) -> tuple[tuple[str, int], ...]:
        return tuple(replacement.slot for replacement in self.replacements)


def observation_from_row(raw_row: Any, *, where: str) -> Observation:
    if not isinstance(raw_row, Mapping):
        raise ReceiptError(f"{where} must be an object; got {type(raw_row).__name__}.")
    row = cast(Mapping[str, Any], raw_row)
    case_id = _required_str(row, "case_id", where=where)
    repetition = _optional_int(row.get("repetition"), where=where, key="repetition")
    if repetition is None or repetition < 1:
        raise ReceiptError(f"{where}: repetition must be an integer >= 1.")
    journey = _mapping(row.get("journey"), where=where, key="journey")
    plan_outcome = _mapping(
        journey.get("plan_outcome"), where=where, key="journey.plan_outcome"
    )
    architecture = _mapping(
        journey.get("architecture"), where=where, key="journey.architecture"
    )
    failure_summary = _mapping(
        row.get("failure_summary"), where=where, key="failure_summary"
    )
    ladder_codes: list[str] = []
    for position, attempt in enumerate(
        _sequence(
            plan_outcome.get("attempt_failure_ladder"),
            where=where,
            key="attempt_failure_ladder",
        )
    ):
        key = f"attempt_failure_ladder[{position}]"
        ladder_codes.extend(
            _string_tuple(
                _mapping(attempt, where=where, key=key).get("failure_codes"),
                where=where,
                key=f"{key}.failure_codes",
            )
        )
    dispositions: list[str] = []
    for position, detail in enumerate(
        _sequence(
            failure_summary.get("error_details"), where=where, key="error_details"
        )
    ):
        key = f"error_details[{position}]"
        disposition = _mapping(
            _mapping(detail, where=where, key=key).get("details"),
            where=where,
            key=f"{key}.details",
        ).get("provider_disposition")
        if disposition is None:
            continue
        if not isinstance(disposition, str) or not disposition:
            raise ReceiptError(f"{where}: {key} provider_disposition must be a string.")
        dispositions.append(disposition)
    usage = _mapping(row.get("authoring_usage"), where=where, key="authoring_usage")
    failed_check_names: list[str] = []
    for position, check in enumerate(
        _sequence(row.get("failed_checks"), where=where, key="failed_checks")
    ):
        key = f"failed_checks[{position}]"
        failed_check_names.append(
            _required_str(_mapping(check, where=where, key=key), "name", where=where)
        )
    return Observation(
        case_id=case_id,
        repetition=repetition,
        required=row.get("required") is True,
        observation_status=_required_str(row, "observation_status", where=where),
        outcome_class=_required_str(row, "outcome_class", where=where),
        expectation_verdict=_required_str(row, "expectation_verdict", where=where),
        case_contract_sha256=_required_str(row, "case_contract_sha256", where=where),
        bundle_file=_required_str(row, BUNDLE_FILE_FIELD, where=where),
        bundle_sha256=_required_str(row, BUNDLE_SHA256_FIELD, where=where),
        failed_check_names=tuple(failed_check_names),
        repair_attempts=_optional_int(
            plan_outcome.get("repair_attempts"), where=where, key="repair_attempts"
        ),
        failure_codes=_string_tuple(
            failure_summary.get("failure_codes"), where=where, key="failure_codes"
        ),
        ladder_failure_codes=tuple(ladder_codes),
        chosen_patterns=frozenset(
            _string_tuple(
                architecture.get("chosen_patterns"), where=where, key="chosen_patterns"
            )
        ),
        provider_dispositions=tuple(dispositions),
        model_calls=_optional_int(
            usage.get("model_calls"), where=where, key="model_calls"
        ),
        total_tokens=_optional_int(
            usage.get("total_tokens"), where=where, key="total_tokens"
        ),
        elapsed_ms=_optional_int(
            usage.get("elapsed_ms"), where=where, key="elapsed_ms"
        ),
        row=row,
    )


def receipt_from_summary(
    payload: Any, *, where: str, integrity_verified: bool = False
) -> Receipt:
    """Parse a decoded `suite-summary.json` payload, or raise.

    Nothing is skipped. A row this reader cannot read is a receipt that cannot
    be scored, because the alternative — dropping it — silently changes the
    denominator of every rate the release gate computes.
    """

    if not isinstance(payload, Mapping):
        raise ReceiptError(f"{where} must contain a JSON object.")
    summary = cast(Mapping[str, Any], payload)
    rows = _sequence(summary.get("results"), where=where, key="results")
    if not rows:
        raise ReceiptError(f"{where}: results must be a non-empty array.")
    observations = tuple(
        observation_from_row(row, where=f"results[{index}]")
        for index, row in enumerate(rows)
    )
    seen: set[tuple[str, int]] = set()
    for observation in observations:
        if observation.slot in seen:
            raise ReceiptError(
                f"{where}: duplicate observation "
                f"{observation.case_id!r} repetition {observation.repetition}."
            )
        seen.add(observation.slot)
    repetitions = _optional_int(
        summary.get("repetitions"), where=where, key="repetitions"
    )
    if repetitions is None or repetitions < 1:
        raise ReceiptError(f"{where}: repetitions must be an integer >= 1.")
    source = _mapping(
        _mapping(
            summary.get("release_identity"), where=where, key="release_identity"
        ).get("source"),
        where=where,
        key="release_identity.source",
    )
    return Receipt(
        artifact_schema_version=_required_str(
            summary, "artifact_schema_version", where=where
        ),
        artifact_mode=_required_str(summary, "artifact_mode", where=where),
        source_revision=_required_str(source, "revision", where=f"{where}.source"),
        repetitions=repetitions,
        observations=observations,
        integrity_verified=integrity_verified,
        summary=summary,
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReceiptError(f"{path} could not be read as JSON: {error}") from error


def load_summary_receipt(path: Path) -> Receipt:
    """Read one summary file. Structure is checked; integrity is not."""

    return receipt_from_summary(_read_json(path), where=str(path))


def load_release_receipt(suite_dir: Path) -> Receipt:
    """Read a suite directory and re-derive its integrity from the artifacts.

    The summary carries a `receipt_integrity` block, but the writer computed it
    about itself. A release verdict is the one place that must not take the
    measured party's word for the shape of the evidence, so the manifest's
    expected slots, the case contract hashes and every bundle digest are
    checked again here against the files on disk. A whole case deleted from
    the summary is the case this defends against: it leaves every rate
    intact-looking and the population quietly smaller.
    """

    summary_path = suite_dir / SUITE_SUMMARY_FILE
    manifest_path = suite_dir / RELEASE_MANIFEST_FILE
    receipt = receipt_from_summary(
        _read_json(summary_path), where=str(summary_path), integrity_verified=True
    )
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, Mapping):
        raise ReceiptError(f"{manifest_path} must contain a JSON object.")
    expected_observations = [
        dict(_mapping(entry, where=str(manifest_path), key="expected_observations"))
        for entry in _sequence(
            cast(Mapping[str, Any], manifest).get("expected_observations"),
            where=str(manifest_path),
            key="expected_observations",
        )
    ]
    if not expected_observations:
        raise ReceiptError(f"{manifest_path}: expected_observations must not be empty.")
    membership = receipt_membership_report(
        expected_observations=expected_observations,
        results=[dict(observation.row) for observation in receipt.observations],
        suite_dir=suite_dir,
    )
    if membership["status"] != "complete":
        raise ReceiptError(
            f"{summary_path} is not a complete record of its manifest: "
            + json.dumps(
                {
                    key: value
                    for key, value in membership.items()
                    if key != "status" and value
                },
                ensure_ascii=False,
            )
        )
    for observation in receipt.observations:
        bundle_path = suite_dir / observation.bundle_file
        try:
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            # An unreadable bundle is an invalid receipt, never a product
            # failure: it must reach the caller as a refusal to judge.
            raise ReceiptError(f"{bundle_path} could not be read: {error}") from error
        _require_row_matches_bundle(
            observation,
            bundle=_mapping(bundle, where=str(bundle_path), key="bundle"),
            where=f"{summary_path} {observation.slot}",
            identity=_mapping(
                receipt.summary.get("release_identity"),
                where=str(summary_path),
                key="release_identity",
            ),
        )
    _require_release_identity(
        receipt,
        manifest=cast(Mapping[str, Any], manifest),
        where=str(manifest_path),
    )
    return _apply_replacements(receipt, suite_dir=suite_dir)


def replacement_descriptors_from_payload(
    payload: Any, *, where: str
) -> tuple[ReplacementDescriptor, ...]:
    raw_descriptors = _sequence(payload, where=where, key="replacements")
    if not raw_descriptors:
        raise ReceiptError(f"{where}: replacements must not be empty.")
    descriptors: list[ReplacementDescriptor] = []
    seen: set[tuple[str, int]] = set()
    for index, raw_descriptor in enumerate(raw_descriptors):
        item_where = f"{where}[{index}]"
        descriptor = _mapping(raw_descriptor, where=item_where, key="replacement")
        if frozenset(descriptor) != _REPLACEMENT_FIELDS:
            raise ReceiptError(
                f"{item_where}: replacement fields must be exactly "
                f"{sorted(_REPLACEMENT_FIELDS)}."
            )
        repetition = _optional_int(
            descriptor.get("repetition"),
            where=item_where,
            key="repetition",
        )
        if repetition is None or repetition < 1:
            raise ReceiptError(f"{item_where}: repetition must be an integer >= 1.")
        replacement = ReplacementDescriptor(
            case_id=_required_str(descriptor, "case_id", where=item_where),
            repetition=repetition,
            reason=_required_str(descriptor, "reason", where=item_where),
            original_bundle_sha256=_required_str(
                descriptor, "original_bundle_sha256", where=item_where
            ),
            replacement_bundle_sha256=_required_str(
                descriptor, "replacement_bundle_sha256", where=item_where
            ),
        )
        if not replacement.reason.strip():
            raise ReceiptError(
                f"{item_where}: reason must contain non-whitespace text."
            )
        for field, digest in (
            ("original_bundle_sha256", replacement.original_bundle_sha256),
            ("replacement_bundle_sha256", replacement.replacement_bundle_sha256),
        ):
            if not is_sha256(digest):
                raise ReceiptError(f"{item_where}: {field} must be a SHA-256 digest.")
        if replacement.slot in seen:
            raise ReceiptError(
                f"{where}: duplicate replacement for {replacement.case_id!r} "
                f"repetition {replacement.repetition}."
            )
        seen.add(replacement.slot)
        descriptors.append(replacement)
    return tuple(descriptors)


def _replacement_files_by_digest(
    suite_dir: Path, *, claimed_bundle_files: frozenset[str]
) -> Mapping[str, tuple[Path, ...]]:
    excluded = claimed_bundle_files | frozenset(
        {SUITE_SUMMARY_FILE, RELEASE_MANIFEST_FILE, REPLACEMENTS_FILE}
    )
    indexed: dict[str, list[Path]] = {}
    try:
        candidates = tuple(suite_dir.iterdir())
    except OSError as error:
        raise ReceiptError(f"{suite_dir} could not be listed: {error}") from error
    for path in candidates:
        if (
            path.name in excluded
            or path.suffix != ".json"
            or path.is_symlink()
            or not path.is_file()
        ):
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise ReceiptError(f"{path} could not be read: {error}") from error
        indexed.setdefault(digest, []).append(path)
    return {digest: tuple(sorted(paths)) for digest, paths in indexed.items()}


def _apply_replacements(receipt: Receipt, *, suite_dir: Path) -> Receipt:
    replacements_path = suite_dir / REPLACEMENTS_FILE
    if not replacements_path.exists():
        return receipt
    descriptors = replacement_descriptors_from_payload(
        _read_json(replacements_path), where=str(replacements_path)
    )
    base_by_slot = {
        observation.slot: observation for observation in receipt.observations
    }
    files_by_digest = _replacement_files_by_digest(
        suite_dir,
        claimed_bundle_files=frozenset(
            observation.bundle_file for observation in receipt.observations
        ),
    )
    identity = _mapping(
        receipt.summary.get("release_identity"),
        where=str(replacements_path),
        key="release_identity",
    )
    overlaid: dict[tuple[str, int], Observation] = {}
    for descriptor in descriptors:
        where = (
            f"{replacements_path}: {descriptor.case_id!r} "
            f"repetition {descriptor.repetition}"
        )
        original = base_by_slot.get(descriptor.slot)
        if original is None:
            raise ReceiptError(f"{where}: no original observation occupies this slot.")
        if not original.provider_dispositions:
            raise ReceiptError(
                f"{where}: the original observation has no provider disposition "
                "and may not be re-measured."
            )
        if original.bundle_sha256 != descriptor.original_bundle_sha256:
            raise ReceiptError(
                f"{where}: original_bundle_sha256 does not match the base slot."
            )
        matching_paths = files_by_digest.get(descriptor.replacement_bundle_sha256, ())
        if len(matching_paths) != 1:
            raise ReceiptError(
                f"{where}: replacement_bundle_sha256 resolves to "
                f"{len(matching_paths)} unclaimed sibling files; expected exactly one."
            )
        bundle_path = matching_paths[0]
        bundle = _mapping(_read_json(bundle_path), where=str(bundle_path), key="bundle")
        if bundle.get("artifact_schema_version") != SUPPORTED_RECEIPT_ARTIFACT_VERSION:
            raise ReceiptError(
                f"{where}: replacement bundle schema must be "
                f"{SUPPORTED_RECEIPT_ARTIFACT_VERSION}."
            )
        sealed = _mapping(
            bundle.get("observation"), where=str(bundle_path), key="observation"
        )
        if not sealed:
            raise ReceiptError(f"{where}: the replacement bundle seals no observation.")
        replacement_row = {
            **dict(sealed),
            BUNDLE_FILE_FIELD: bundle_path.name,
            BUNDLE_SHA256_FIELD: descriptor.replacement_bundle_sha256,
        }
        replacement_observation = observation_from_row(
            replacement_row, where=f"{where} replacement observation"
        )
        if replacement_observation.slot != descriptor.slot:
            raise ReceiptError(
                f"{where}: replacement seals slot {replacement_observation.slot}."
            )
        if (
            replacement_observation.case_contract_sha256
            != original.case_contract_sha256
        ):
            raise ReceiptError(
                f"{where}: replacement case contract differs from the original."
            )
        _require_row_matches_bundle(
            replacement_observation,
            bundle=bundle,
            where=where,
            identity=identity,
        )
        if observation_identity_failure_count(replacement_observation, where=where):
            raise ReceiptError(f"{where}: replacement has a failed identity check.")
        overlaid[descriptor.slot] = replacement_observation
    return replace(
        receipt,
        observations=tuple(
            overlaid.get(observation.slot, observation)
            for observation in receipt.observations
        ),
        replacements=descriptors,
    )


def release_identity_recheck_checks(
    *,
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    require_verified_target: bool = False,
) -> list[JsonObject]:
    """Compare the run's final identity with the identity it started under."""

    components = ["source", "build", "model", "prompts"]
    if "target" in expected or "target" in actual:
        components.append("target")
    checks = [
        {
            "name": f"suite_{component}_identity_unchanged",
            "passed": actual.get(component) == expected.get(component),
            "actual": actual.get(component),
            "expected": expected.get(component),
        }
        for component in components
    ]
    if require_verified_target and "target" in expected:
        target = _mapping(actual.get("target"), where="identity recheck", key="target")
        checks.append(
            {
                "name": "suite_target_runtime_verified",
                "passed": target.get("verified") is True,
                "actual": dict(target),
                "expected": "running backend version matches the local benchmark build",
            }
        )
    return checks


def _require_release_identity(
    receipt: Receipt, *, manifest: Mapping[str, Any], where: str
) -> None:
    """A release receipt is a specific artifact, not any receipt in a folder.

    Without this, an exploratory run — no required cases, no verified target —
    could be handed to the release gate and scored as if it were the real
    thing, and a summary from one run could be judged beside another run's
    manifest.
    """

    if receipt.artifact_schema_version != SUPPORTED_RECEIPT_ARTIFACT_VERSION:
        raise ReceiptError(
            f"{where}: receipt schema is {receipt.artifact_schema_version}; this "
            f"evaluator scores {SUPPORTED_RECEIPT_ARTIFACT_VERSION}."
        )
    if receipt.artifact_mode != RELEASE_SUMMARY_ARTIFACT_MODE:
        raise ReceiptError(
            f"{where}: artifact_mode is {receipt.artifact_mode}; only a "
            f"{RELEASE_SUMMARY_ARTIFACT_MODE} may be judged for release."
        )
    manifest_version = manifest.get("artifact_schema_version")
    if manifest_version != receipt.artifact_schema_version:
        raise ReceiptError(
            f"{where}: manifest schema {manifest_version!r} does not match the "
            f"summary's {receipt.artifact_schema_version!r}."
        )
    for component in ("release_identity", "evaluator_identity"):
        manifest_component = _mapping(
            manifest.get(component), where=where, key=component
        )
        summary_component = _mapping(
            receipt.summary.get(component), where=where, key=component
        )
        if not manifest_component:
            raise ReceiptError(f"{where}: {component} is missing.")
        if manifest_component != summary_component:
            raise ReceiptError(
                f"{where}: {component} differs between the manifest and the "
                "summary; these are not two records of one run."
            )
    identity = _mapping(
        receipt.summary.get("release_identity"), where=where, key="release_identity"
    )
    target = _mapping(
        identity.get("target"), where=where, key="release_identity.target"
    )
    if target.get("verified") is not True:
        raise ReceiptError(f"{where}: the initial release target was not verified.")
    identity_recheck = _mapping(
        receipt.summary.get("release_identity_recheck"),
        where=where,
        key="release_identity_recheck",
    )
    if not identity_recheck:
        raise ReceiptError(f"{where}: release_identity_recheck is missing.")
    expected_recheck_checks = release_identity_recheck_checks(
        expected=identity,
        actual=identity_recheck,
        require_verified_target=True,
    )
    reported_recheck_checks = [
        dict(_mapping(check, where=where, key="release identity recheck"))
        for check in _sequence(
            receipt.summary.get("release_identity_recheck_checks"),
            where=where,
            key="release_identity_recheck_checks",
        )
    ]
    if reported_recheck_checks != expected_recheck_checks:
        failed_names = [
            check["name"]
            for check in expected_recheck_checks
            if check["passed"] is not True
        ]
        raise ReceiptError(
            f"{where}: release_identity_recheck_checks do not match the final "
            f"identity recheck for {failed_names or 'the recorded identity'}."
        )

    execution_failure_count = sum(
        observation.observation_status == "execution_failure"
        for observation in receipt.observations
    )
    invalid_evidence_count = sum(
        observation.observation_status == "invalid_evidence"
        for observation in receipt.observations
    )
    expected_acquisition_checks = acquisition_validity_checks(
        execution_failure_observation_count=execution_failure_count,
        invalid_evidence_observation_count=invalid_evidence_count,
    )
    reported_acquisition_checks = [
        dict(_mapping(check, where=where, key="acquisition check"))
        for check in _sequence(
            receipt.summary.get("sentinel_acquisition_checks"),
            where=where,
            key="sentinel_acquisition_checks",
        )
    ]
    if reported_acquisition_checks != expected_acquisition_checks:
        raise ReceiptError(
            f"{where}: sentinel_acquisition_checks do not match the sealed "
            "observation statuses."
        )

    derived_observation_identity_failure_count = sum(
        observation_identity_failure_count(
            observation, where=f"{where}: observation {observation.slot}"
        )
        for observation in receipt.observations
    )

    suite_identity_failure_count = sum(
        check["passed"] is not True for check in expected_recheck_checks
    )
    identity_failure_count = (
        suite_identity_failure_count + derived_observation_identity_failure_count
    )
    expected_counters = {
        "execution_failure_observation_count": execution_failure_count,
        "invalid_evidence_observation_count": invalid_evidence_count,
        "suite_identity_failed_check_count": suite_identity_failure_count,
        "observation_identity_failed_check_count": (
            derived_observation_identity_failure_count
        ),
        "identity_failed_check_count": identity_failure_count,
    }
    for counter, expected_count in expected_counters.items():
        reported_count = _optional_int(
            receipt.summary.get(counter), where=where, key=counter
        )
        if reported_count != expected_count:
            raise ReceiptError(
                f"{where}: {counter} is {reported_count}, but the sealed "
                f"acquisition evidence requires {expected_count}."
            )

    expected_sentinel = (
        "pass"
        if identity_failure_count == 0
        and all(check["passed"] is True for check in expected_acquisition_checks)
        else "fail"
    )
    reported_sentinel = receipt.summary.get("sentinel_verdict")
    if reported_sentinel != expected_sentinel:
        raise ReceiptError(
            f"{where}: sentinel_verdict is {reported_sentinel!r}, but the sealed "
            f"acquisition evidence requires {expected_sentinel!r}."
        )
    if expected_sentinel != "pass":
        raise ReceiptError(f"{where}: the run failed its acquisition verdict.")
    build = _mapping(identity.get("build"), where=where, key="build")
    model = _mapping(identity.get("model"), where=where, key="model")
    # Equality between two files written by one run proves only that the run
    # wrote both. What a verdict needs is that the identity is PRESENT and
    # names this evaluator's own corpus and harness.
    if not _required_str(model, "requested_id", where=f"{where} model"):
        raise ReceiptError(f"{where}: the run does not name a model.")
    for input_name, path in (
        ("harness_sha256", _SCRIPTS_DIR / HARNESS_FILE),
        ("cases_sha256", _SCRIPTS_DIR / CASES_FILE),
    ):
        recorded = build.get(input_name)
        if not is_sha256(recorded):
            raise ReceiptError(f"{where}: build.{input_name} is not a digest.")
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise ReceiptError(f"{where}: {path} could not be read: {error}") from error
        if recorded != actual:
            raise ReceiptError(
                f"{where}: build.{input_name} is {recorded}, but this checkout's "
                f"{path.name} hashes to {actual}. The receipt was produced by a "
                "different instrument or corpus than the one judging it."
            )


def observation_identity_failure_count(observation: Observation, *, where: str) -> int:
    identity_checks = [
        _mapping(check, where=where, key="identity_failed_checks")
        for check in _sequence(
            observation.row.get("identity_failed_checks"),
            where=where,
            key="identity_failed_checks",
        )
    ]
    derived_count = sum(check.get("passed") is not True for check in identity_checks)
    reported_count = _optional_int(
        observation.row.get("identity_failed_check_count"),
        where=where,
        key="identity_failed_check_count",
    )
    if reported_count != derived_count:
        raise ReceiptError(
            f"{where}: identity_failed_check_count is {reported_count}, "
            f"but the sealed checks contain {derived_count} failures."
        )
    return derived_count


def _require_row_matches_bundle(
    observation: Observation,
    *,
    bundle: Mapping[str, Any],
    where: str,
    identity: Mapping[str, Any],
) -> None:
    """The row must BE the observation the bundle sealed.

    The harness derives status, outcome, expectation verdict and evidence
    validity from the whole bundle and seals that judgement inside it before
    hashing (`seal_observation`). So this is an equality check, not a second
    evaluator: re-deriving the judgement here would be the duplicate ownership
    the instrument keeps paying for, and checking only some fields is how a
    relabelled observation gets scored.
    """

    _require_bundle_identity(bundle, where=where, identity=identity)
    sealed = _mapping(bundle.get("observation"), where=where, key="observation")
    if not sealed:
        raise ReceiptError(f"{where}: the bundle seals no observation.")
    recorded = {
        key: value
        for key, value in observation.row.items()
        if key not in BUNDLE_REFERENCE_FIELDS
    }
    if recorded != dict(sealed):
        differing = sorted(
            key
            for key in set(recorded) | set(sealed)
            if recorded.get(key) != sealed.get(key)
        )
        raise ReceiptError(
            f"{where}: the summary row disagrees with the observation sealed in "
            f"its bundle on {differing}."
        )


def _require_bundle_identity(
    bundle: Mapping[str, Any], *, where: str, identity: Mapping[str, Any]
) -> None:
    """This bundle belongs to THIS run, and says so consistently.

    Self-consistent hashes only prove a bundle is internally coherent — a
    coherent bundle measured against a different model or corpus can still be
    dropped into another run's directory, so each component is also compared
    to the identity the receipt declares.
    """

    declared_source = _mapping(identity.get("source"), where=where, key="source")
    source_revision = _required_str(declared_source, "revision", where=where)
    contract = _mapping(bundle.get("case_contract"), where=where, key="case_contract")
    if not contract:
        raise ReceiptError(f"{where}: the bundle carries no case contract.")
    if bundle.get("case_contract_sha256") != canonical_sha256(dict(contract)):
        raise ReceiptError(f"{where}: the case contract does not match its digest.")
    provenance = _mapping(
        bundle.get("live_execution_provenance"),
        where=where,
        key="live_execution_provenance",
    )
    source = _mapping(provenance.get("source"), where=where, key="source")
    revision = source.get("revision")
    if revision != source_revision:
        raise ReceiptError(
            f"{where}: the bundle was produced at {revision!r}, not the "
            f"receipt's {source_revision!r}."
        )
    if (
        source.get("revision_sha256")
        != hashlib.sha256(str(revision).encode("utf-8")).hexdigest()
    ):
        raise ReceiptError(f"{where}: the source revision does not match its digest.")
    if source.get("tracked_clean") is not True:
        raise ReceiptError(f"{where}: the bundle was measured on a dirty tree.")
    build = _mapping(provenance.get("build"), where=where, key="build")
    stable_build = {
        key: build.get(key)
        for key in ("source_revision", "harness_sha256", "cases_sha256")
    }
    if build.get("sha256") != canonical_sha256(stable_build):
        raise ReceiptError(f"{where}: the build identity does not match its digest.")
    if build.get("source_revision") != revision:
        raise ReceiptError(f"{where}: the build names a different revision.")
    declared_build = _mapping(identity.get("build"), where=where, key="build")
    for field in ("harness_sha256", "cases_sha256"):
        if build.get(field) != declared_build.get(field):
            raise ReceiptError(
                f"{where}: the bundle's {field} is not the run's; this bundle "
                "was produced by a different instrument or corpus."
            )
    model = dict(_mapping(provenance.get("model"), where=where, key="model"))
    model_digest = model.pop("sha256", None)
    if model_digest != canonical_sha256(model):
        raise ReceiptError(f"{where}: the model identity does not match its digest.")
    declared_model = _mapping(identity.get("model"), where=where, key="model")
    if model.get("requested_id") != declared_model.get("requested_id"):
        raise ReceiptError(
            f"{where}: the bundle was measured against "
            f"{model.get('requested_id')!r}, but the run declares "
            f"{declared_model.get('requested_id')!r}."
        )


def failure_summary_from_events(event_summary: Mapping[str, Any]) -> JsonObject:
    """The failure vocabulary a bundle carries, projected from its events.

    One owner: the harness writes rows with this projection and the release
    reader re-derives them with it, so a row cannot claim failure codes its
    bundle never recorded.
    """

    return {
        "error_codes": list(
            _string_tuple(
                event_summary.get("error_codes"),
                where="event_summary",
                key="error_codes",
            )
        ),
        "failure_codes": list(
            _string_tuple(
                event_summary.get("failure_codes"),
                where="event_summary",
                key="failure_codes",
            )
        ),
        "critic_issue_ids": list(
            _string_tuple(
                event_summary.get("critic_issue_ids"),
                where="event_summary",
                key="critic_issue_ids",
            )
        ),
        "repair_feedback_texts": list(
            _string_tuple(
                event_summary.get("repair_feedback_texts"),
                where="event_summary",
                key="repair_feedback_texts",
            )
        ),
        "error_details": list(
            _sequence(
                event_summary.get("error_details"),
                where="event_summary",
                key="error_details",
            )
        ),
    }


def is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def canonical_sha256(value: object) -> str:
    """The digest shape every identity field in a receipt is built from."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def observation_key(value: Mapping[str, object]) -> tuple[str, int] | None:
    case_id = value.get("case_id")
    repetition = value.get("repetition")
    if (
        not isinstance(case_id, str)
        or not case_id
        or not isinstance(repetition, int)
        or isinstance(repetition, bool)
        or repetition < 1
    ):
        return None
    return case_id, repetition


def observation_key_payload(key: tuple[str, int]) -> JsonObject:
    return {"case_id": key[0], "repetition": key[1]}


def receipt_membership_report(
    *,
    expected_observations: list[JsonObject],
    results: list[JsonObject],
    suite_dir: Path,
) -> JsonObject:
    """Does this receipt hold exactly the run its manifest declared?

    ONE implementation with two consumers and two reactions: the harness
    renders the report into the summary it writes, and the release reader
    refuses anything whose status is not `complete`. They used to answer this
    question separately and had already drifted on sha-shape validation, which
    is how a receipt can be complete to its writer and incomplete to its
    judge.
    """
    expected_by_key: dict[tuple[str, int], str] = {}
    invalid_expected_keys: list[JsonObject] = []
    for expected in expected_observations:
        key = observation_key(expected)
        contract_sha256 = expected.get("case_contract_sha256")
        if key is None or not is_sha256(contract_sha256) or key in expected_by_key:
            invalid_expected_keys.append(dict(expected))
            continue
        expected_by_key[key] = str(contract_sha256)

    actual_counts: dict[tuple[str, int], int] = {}
    actual_results: dict[tuple[str, int], JsonObject] = {}
    invalid_actual_keys: list[JsonObject] = []
    for result in results:
        key = observation_key(result)
        if key is None:
            invalid_actual_keys.append(
                {
                    "case_id": result.get("case_id"),
                    "repetition": result.get("repetition"),
                }
            )
            continue
        actual_counts[key] = actual_counts.get(key, 0) + 1
        actual_results.setdefault(key, result)

    expected_keys = set(expected_by_key)
    actual_keys = set(actual_counts)
    missing_keys = sorted(expected_keys - actual_keys)
    unexpected_keys = sorted(actual_keys - expected_keys)
    duplicate_keys = sorted(key for key, count in actual_counts.items() if count > 1)
    case_contract_mismatches: list[JsonObject] = []
    invalid_bundle_references: list[JsonObject] = []
    for key in sorted(expected_keys & actual_keys):
        result = actual_results[key]
        if result.get("case_contract_sha256") != expected_by_key[key]:
            case_contract_mismatches.append(observation_key_payload(key))
        bundle_file = result.get(BUNDLE_FILE_FIELD)
        bundle_sha256 = result.get(BUNDLE_SHA256_FIELD)
        if (
            not isinstance(bundle_file, str)
            or not bundle_file
            or Path(bundle_file).is_absolute()
            or Path(bundle_file).name != bundle_file
        ):
            invalid_bundle_references.append(
                {**observation_key_payload(key), "reason": "invalid_relative_path"}
            )
            continue
        if not is_sha256(bundle_sha256):
            invalid_bundle_references.append(
                {**observation_key_payload(key), "reason": "invalid_sha256"}
            )
            continue
        bundle_path = suite_dir / bundle_file
        if not bundle_path.is_file():
            invalid_bundle_references.append(
                {**observation_key_payload(key), "reason": "missing_bundle"}
            )
            continue
        try:
            digest = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
        except OSError:
            invalid_bundle_references.append(
                {**observation_key_payload(key), "reason": "unreadable_bundle"}
            )
            continue
        if digest != bundle_sha256:
            invalid_bundle_references.append(
                {**observation_key_payload(key), "reason": "sha256_mismatch"}
            )

    complete = not any(
        (
            invalid_expected_keys,
            invalid_actual_keys,
            missing_keys,
            unexpected_keys,
            duplicate_keys,
            case_contract_mismatches,
            invalid_bundle_references,
        )
    )
    return {
        "status": "complete" if complete else "partial",
        "expected_observation_count": len(expected_observations),
        "actual_observation_count": len(results),
        "missing_observation_keys": [
            observation_key_payload(key) for key in missing_keys
        ],
        "unexpected_observation_keys": [
            observation_key_payload(key) for key in unexpected_keys
        ],
        "duplicate_observation_keys": [
            observation_key_payload(key) for key in duplicate_keys
        ],
        "invalid_expected_observation_keys": invalid_expected_keys,
        "invalid_actual_observation_keys": invalid_actual_keys,
        "case_contract_mismatches": case_contract_mismatches,
        "invalid_bundle_references": invalid_bundle_references,
    }


def acquisition_validity_checks(
    *,
    execution_failure_observation_count: int,
    invalid_evidence_observation_count: int,
) -> list[JsonObject]:
    """Acquisition validity only: did we MEASURE cleanly, not did the product win.

    Both invariants are status-based and span EVERY selected observation, so a
    corrupt observation cannot ride through on a non-required case:

    * `execution_failure` - a caught HTTP, timeout or harness error written as
      a `live_execution_failure` bundle. It can still satisfy bundle-count and
      hash completeness and leaves `evidence_valid` unset, so completeness
      alone would not catch it.
    * `invalid_evidence` - provenance that failed its own checks.

    Deliberately absent: product expectation failures (the release evaluator
    scores those), and `error_terminated` observations, whose journey outcome
    IS the product truth and which have no provenance to validate.
    """
    return [
        {
            "name": "execution_failure_observations",
            "passed": execution_failure_observation_count == 0,
            "actual": execution_failure_observation_count,
            "threshold": 0,
        },
        {
            "name": "invalid_evidence_observations",
            "passed": invalid_evidence_observation_count == 0,
            "actual": invalid_evidence_observation_count,
            "threshold": 0,
        },
    ]
