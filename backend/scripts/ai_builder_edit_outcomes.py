"""What the edit lane delivered, by outcome: no blended score.

One declared slot is exactly one of: an executed edit that met its oracle, a
plan that passed with no run oracle to meet, an expected decline, a question
the worker should not have needed, a failed edit, an infrastructure failure (the
instrument, re-measurable), invalid evidence or not observed at all. The
attempted total is the corpus's edit cases times the registered three
repetitions (or the suite's own plan when that is larger, or what --repetitions
asks; fewer than the suite planned is refused): always shown, never rescaled
down, and set against the suite's own plan when it differs; a population above
MAX_POPULATION slots, asked or recorded, is refused. A decline counts only where
the corpus itself declares the case one to decline. A suite of the
whole corpus is read for its edit slots; the rows of every other case are
counted as ignored, and a case the corpus does not declare is refused.

What the suite recorded when it ran is compared with the files as read now, or
the report is refused rather than relabelled: the digest of the corpus, the seed
bytes each verdict was scored on, and the attachments and run files in each
scored row's case contract against those the corpus names for the case and the
pins of the fixture manifest. Verdicts are the edit scorer's, read from the
receipt; nothing here scores a second time. A question is a failure whose only
reasons are asking and not planning: a safety failure beside it makes it a
failed edit.

An engineering report over one suite summary: it reads its structure but does
not re-verify its integrity, as the release and capability gates do, and it does
not read replacements.json, so a slot recovered by a replacement stays
`infrastructure` here (fail-closed). Two arms are compared only through
`ai_builder_battle_compare`, which owns whether they share a harness, model and
run context; this report never judges that.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, Literal, NamedTuple, cast, get_args

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from ai_builder_receipt import (  # noqa: E402
    SUITE_SUMMARY_FILE,
    Observation,
    Receipt,
    ReceiptError,
    canonical_sha256,
    load_summary_receipt,
    observation_is_replacement_eligible,
)

JsonObject = dict[str, Any]
Bucket = Literal[
    "edit_success",
    "structural_pass",
    "correct_decline",
    "question",
    "failed_edit",
    "infrastructure",
    "invalid_evidence",
    "not_observed",
]
BUCKETS: Final[tuple[Bucket, ...]] = get_args(Bucket)
# The buckets a pass can land in: each has a per-case denominator.
_SCORED: Final[tuple[Bucket, ...]] = (
    "edit_success",
    "structural_pass",
    "correct_decline",
)
DEFAULT_CASES_FILE = Path(__file__).with_name("ai_builder_api_municipal_cases.json")
FIXTURE_DIR = Path(__file__).with_name("fixtures") / "ai_builder_battle"
# The edit lane's registered measurement. A suite that planned fewer is read
# against it by default (its shortfall shows as `not_observed`); a one-repetition
# exploratory report says so with --repetitions.
REGISTERED_REPETITIONS: Final = 3
# The most slots one report materialises and prints. The registered plan is 60
# (3 repetitions of the 20 edit cases) and an exploratory run is 5-10 repetitions
# (100-200); 1,000 leaves room for 50 repetitions and bounds the JSON at 1,000
# entries whatever a suite or the command line claims.
MAX_POPULATION: Final = 1000


class Declared(NamedTuple):
    """What the corpus declares of one edit case: where its pass belongs, the
    seed bytes a verdict must have been scored on, and the fixtures its run
    is given, by name."""

    bucket: Bucket
    seed_sha256: str
    attachments: tuple[str, ...] = ()
    runtime_files: tuple[str, ...] = ()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def declared_cases(cases_file: Path) -> dict[str, Declared | None]:
    """Every case the corpus declares: an executed edit, a plan the corpus gives
    no run oracle, a decline, or None for a case this report does not score."""

    declared: dict[str, Declared | None] = {}
    for case in json.loads(cases_file.read_text(encoding="utf-8"))["cases"]:
        edit = case.get("edit")
        if edit is None or "expect" not in edit:
            declared[case["id"]] = None
            continue
        expect: object = edit["expect"]
        outcome = (
            cast(Mapping[str, Any], expect).get("outcome")
            if isinstance(expect, Mapping)
            else None
        )
        if outcome not in ("plan", "declined"):
            raise ValueError(
                f"{case['id']}: edit.expect must declare the outcome plan or "
                f"declined, not {outcome!r}"
            )
        bucket: Bucket = (
            "correct_decline"
            if outcome == "declined"
            else "edit_success"
            if case.get("execution") is not None
            else "structural_pass"
        )
        execution: Mapping[str, Any] = case.get("execution") or {}
        inputs: Mapping[str, Any] = execution.get("inputs") or {}
        declared[case["id"]] = Declared(
            bucket,
            _sha256(FIXTURE_DIR / edit["seed_flow_fixture"]),
            tuple(case.get("attachments") or ()),
            tuple(inputs.get("files") or ()),
        )
    return declared


def fixture_pins(manifest_file: Path) -> dict[str, str]:
    """Fixture name -> the content digest the manifest pins for it."""

    payload: object = json.loads(manifest_file.read_text(encoding="utf-8"))
    fixtures = (
        cast(Mapping[str, object], payload).get("fixtures")
        if isinstance(payload, Mapping)
        else None
    )
    if not isinstance(fixtures, Mapping) or not fixtures:
        raise ValueError(f"{manifest_file.name} pins no fixtures")
    return dict(cast(Mapping[str, str], fixtures))


def _recorded_fixture_pins(
    suite_dir: Path, observation: Observation
) -> dict[str, list[tuple[str, str]]]:
    """The fixture pins, by kind, in the case contract the row's digest is of,
    read from the bundle the run sealed."""

    bundle = json.loads((suite_dir / observation.bundle_file).read_text("utf-8"))
    try:
        contract = bundle["case_contract"]
        if canonical_sha256(contract) != observation.case_contract_sha256:
            raise ValueError(
                f"{observation.slot}: its bundle's case contract is not the one "
                "its row records"
            )
        fixture = contract["attachment_fixture"]
        return {
            kind: [(pin["name"], pin["content_sha256"]) for pin in fixture[kind]]
            for kind in ("attachments", "runtime_files")
        }
    except (KeyError, TypeError) as error:
        raise ValueError(
            f"{observation.slot}: its bundle records no readable fixture pins"
        ) from error


def require_scored_inputs(
    receipt: Receipt,
    suite_dir: Path,
    cases_file: Path,
    declared: Mapping[str, Declared | None],
) -> None:
    """The one owner of identity: what the suite recorded at run time, compared
    with the corpus, seed and fixture files as read now."""

    identity = cast(Mapping[str, Any], receipt.summary.get("release_identity") or {})
    build = cast(Mapping[str, Any], identity.get("build") or {})
    if build.get("cases_sha256") != _sha256(cases_file):
        raise ValueError(
            f"the suite was scored on a different corpus than {cases_file.name}"
        )
    pinned = fixture_pins(FIXTURE_DIR / "manifest.json")
    for observation in receipt.observations:
        case = declared.get(observation.case_id)
        if case is None:
            continue
        edit = observation.edit
        if edit is not None and edit.seed_sha256 != case.seed_sha256:
            raise ValueError(
                f"{observation.slot} was scored on a different seed than the corpus's"
            )
        for kind, pins in _recorded_fixture_pins(suite_dir, observation).items():
            named = tuple(name for name, _ in pins)
            if named != getattr(case, kind):
                raise ValueError(
                    f"{observation.slot} was scored with {kind} {list(named)}, "
                    f"not the corpus's {list(getattr(case, kind))}"
                )
            for name, content_sha256 in pins:
                if pinned.get(name) != content_sha256:
                    raise ValueError(
                        f"{observation.slot} was scored on a different fixture "
                        f"than the manifest's: {name}"
                    )


def edit_bucket(observation: Observation, declared: Declared) -> Bucket:
    edit = observation.edit
    if observation_is_replacement_eligible(observation):
        return "infrastructure"
    if observation.observation_status == "error_terminated":
        return "failed_edit"
    if (
        observation.observation_status != "completed"
        or edit is None
        or edit.verdict not in {"pass", "fail"}
    ):
        return "invalid_evidence"
    if edit.verdict == "pass":
        return declared.bucket
    asked_only = "questions" in edit.categories and set(edit.categories) <= {
        "fulfilment",
        "questions",
    }
    return "question" if asked_only else "failed_edit"


def _first_failure(observation: Observation | None, bucket: Bucket) -> str:
    """The reason a slot did not score, read from what its bucket is about."""

    if observation is None:
        return "no_observation"
    edit = observation.edit
    if bucket == "infrastructure":
        return observation.failure_class or observation.outcome_class
    if bucket == "invalid_evidence":
        if observation.observation_status != "completed":
            return (
                *observation.evidence_failed_check_names,
                observation.outcome_class,
            )[0]
        return "no_edit_verdict" if edit is None else edit.verdict
    if observation.observation_status == "error_terminated":
        return (
            *observation.error_codes,
            *observation.failure_codes,
            observation.failure_class or observation.outcome_class,
        )[0]
    return (
        *(edit.failed_checks if edit is not None else ()),
        *observation.failure_codes,
        observation.failure_class or observation.outcome_class,
    )[0]


def edit_outcome_report(
    observations: Sequence[Observation],
    *,
    declared: Mapping[str, Declared | None],
    repetitions: int,
    planned: int,
) -> JsonObject:
    """Every declared slot, the corpus's edit cases times the repetitions asked,
    lands in exactly one bucket; a slot nobody observed is `not_observed`. Rows
    of the corpus's other cases are counted, not scored. `planned` is the
    repetitions the suite recorded; asking for fewer would rescale a shortfall
    away."""

    scored = {
        case_id: value for case_id, value in declared.items() if value is not None
    }
    for what, count in (
        ("the suite's recorded plan", planned),
        ("the report", repetitions),
    ):
        if len(scored) * count > MAX_POPULATION:
            raise ValueError(
                f"{what} is {count} repetitions of {len(scored)} edit cases, above "
                f"the maximum population of {MAX_POPULATION} slots"
            )
    if repetitions < planned:
        raise ValueError(
            f"{repetitions} repetitions is below the suite's recorded plan of {planned}"
        )
    slots = [
        (case_id, repetition)
        for case_id in scored
        for repetition in range(1, repetitions + 1)
    ]
    if unknown := sorted({o.case_id for o in observations} - declared.keys()):
        raise ValueError(
            f"observations of cases the corpus does not declare: {unknown}"
        )
    observed = {o.slot: o for o in observations if o.case_id in scored}
    if stray := sorted(observed.keys() - set(slots)):
        raise ValueError(f"observations outside the declared population: {stray}")
    ignored = sorted(o.case_id for o in observations if o.case_id not in scored)
    rows: list[tuple[tuple[str, int], Observation | None, Bucket]] = []
    for slot in slots:
        observation = observed.get(slot)
        bucket = (
            "not_observed"
            if observation is None
            else edit_bucket(observation, scored[slot[0]])
        )
        rows.append((slot, observation, bucket))
    counts = Counter(bucket for _, _, bucket in rows)
    return {
        "attempted": len(slots),
        "repetitions": repetitions,
        "recorded_plan": len(scored) * planned,
        "expected": {
            bucket: sum(value.bucket == bucket for value in scored.values())
            * repetitions
            for bucket in _SCORED
        },
        "buckets": {bucket: counts[bucket] for bucket in BUCKETS},
        "first_failures": [
            {
                "case_id": case_id,
                "repetition": repetition,
                "bucket": bucket,
                "first_failure": _first_failure(observation, bucket),
            }
            for (case_id, repetition), observation, bucket in rows
            if bucket not in _SCORED
        ],
        "ignored_not_edit": {"rows": len(ignored), "case_ids": sorted(set(ignored))},
    }


def headline(report: Mapping[str, Any]) -> str:
    buckets = cast(Mapping[str, int], report["buckets"])
    expected = cast(Mapping[str, int], report["expected"])
    parts = [
        f"{bucket} {buckets[bucket]}"
        + (f"/{expected[bucket]}" if bucket in expected else "")
        for bucket in BUCKETS
    ]
    plan = (
        f" (recorded plan {report['recorded_plan']})"
        if report["recorded_plan"] != report["attempted"]
        else ""
    )
    return f"attempted {report['attempted']}{plan}: " + ", ".join(parts)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite_dir", type=Path)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_FILE)
    parser.add_argument(
        "--repetitions",
        type=int,
        help=(
            "repetitions per edit case: at least the suite's recorded plan "
            f"(default {REGISTERED_REPETITIONS}, or the plan if larger)"
        ),
    )
    args = parser.parse_args(argv)
    if args.repetitions is not None and args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    try:
        receipt = load_summary_receipt(args.suite_dir / SUITE_SUMMARY_FILE)
        declared = declared_cases(args.cases)
        require_scored_inputs(receipt, args.suite_dir, args.cases, declared)
        report = edit_outcome_report(
            receipt.observations,
            declared=declared,
            repetitions=args.repetitions
            or max(REGISTERED_REPETITIONS, receipt.repetitions),
            planned=receipt.repetitions,
        )
    except (OSError, ReceiptError, ValueError) as error:
        print(f"report refused: {error}", file=sys.stderr)
        return 2
    print(headline(report))
    print(f"ignored (not edit): {report['ignored_not_edit']['rows']} rows")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
