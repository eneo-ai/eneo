"""What the edit lane delivered, by outcome: no blended score.

One declared slot (an edit case of the corpus times a repetition) is exactly one
of: an executed edit that met its oracle, a plan that passed with no run oracle,
an expected decline, a question the worker should not have needed, a failed edit,
an infrastructure failure (the instrument, re-measurable), invalid evidence or
not observed. The attempted total is never rescaled down: the registered three
repetitions, the suite's recorded plan if larger, or --repetitions (fewer than
the plan is refused). A decline counts only where the corpus declares one.

Verdicts are the edit scorer's, read from the receipt; nothing is scored twice.
The one identity fact refused on is the receipt's own record of its corpus
(build.cases_sha256) against the --cases file the population is read from. Seeds,
attachments and fixture pins decide no bucket: the harness seals them in each
row's case contract (case_contract_sha256), which the release gate and
`ai_builder_battle_compare` compare. Structure only, no integrity: bundles are not
read, and neither is replacements.json, so a recovered slot stays
`infrastructure`. Two arms compare only through `ai_builder_battle_compare`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, Literal, cast, get_args

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from ai_builder_receipt import (  # noqa: E402
    SUITE_SUMMARY_FILE,
    Observation,
    Receipt,
    ReceiptError,
    load_summary_receipt,
    observation_is_replacement_eligible,
)

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
_SCORED: Final = BUCKETS[:3]  # where a pass can land: each has a per-case denominator
DEFAULT_CASES_FILE = Path(__file__).with_name("ai_builder_api_municipal_cases.json")
REGISTERED_REPETITIONS: Final = 3  # the edit lane's registered measurement
MAX_POPULATION: Final = 1000  # slots one report materialises: 50 repetitions of 20


def declared_cases(cases_file: Path) -> dict[str, Bucket | None]:
    """Where a pass belongs, for every case the corpus declares an edit outcome
    for; None for a case this report does not score."""

    declared: dict[str, Bucket | None] = {}
    for case in json.loads(cases_file.read_text(encoding="utf-8"))["cases"]:
        edit: dict[str, Any] = case.get("edit") or {}
        if "expect" not in edit:
            declared[case["id"]] = None
            continue
        try:
            outcome = edit["expect"]["outcome"]
        except (KeyError, TypeError):
            outcome = None
        if outcome not in ("plan", "declined"):
            raise ValueError(
                f"{case['id']}: edit.expect must declare the outcome plan or "
                f"declined, not {outcome!r}"
            )
        declared[case["id"]] = (
            "correct_decline"
            if outcome == "declined"
            else "edit_success"
            if case.get("execution") is not None
            else "structural_pass"
        )
    return declared


def require_recorded_corpus(receipt: Receipt, cases_file: Path) -> None:
    """The corpus the receipt records it ran is the one the population is read from."""

    build: Mapping[str, Any] = receipt.summary["release_identity"].get("build") or {}
    if build.get("cases_sha256") != hashlib.sha256(cases_file.read_bytes()).hexdigest():
        raise ValueError(
            f"the suite was scored on a different corpus than {cases_file.name}"
        )


def edit_outcome(observation: Observation, declared: Bucket) -> tuple[Bucket, str]:
    """A slot's bucket and, when it did not score, its first failure, read from
    what its bucket is about."""

    edit = observation.edit
    failure = observation.failure_class or observation.outcome_class
    if observation_is_replacement_eligible(observation):
        return "infrastructure", failure
    if observation.observation_status == "error_terminated":
        codes = (*observation.error_codes, *observation.failure_codes, failure)
        return "failed_edit", codes[0]
    if observation.observation_status != "completed":
        checks = (*observation.evidence_failed_check_names, observation.outcome_class)
        return "invalid_evidence", checks[0]
    if edit is None or edit.verdict not in {"pass", "fail"}:
        return "invalid_evidence", "no_edit_verdict" if edit is None else edit.verdict
    if edit.verdict == "pass":
        return declared, ""
    asked_only = {"questions"} <= set(edit.categories) <= {"fulfilment", "questions"}
    reasons = (*edit.failed_checks, *observation.failure_codes, failure)
    return ("question" if asked_only else "failed_edit"), reasons[0]


def edit_outcome_report(
    observations: Sequence[Observation],
    *,
    declared: Mapping[str, Bucket | None],
    repetitions: int,
    planned: int,
) -> dict[str, Any]:
    """Every declared slot, the corpus's edit cases times the repetitions asked,
    lands in exactly one bucket; a slot nobody observed is `not_observed`.
    `planned` is the repetitions the suite recorded: asking for fewer would
    rescale a shortfall away."""

    scored: dict[str, Bucket] = {
        case_id: bucket for case_id, bucket in declared.items() if bucket is not None
    }
    if repetitions < planned:
        raise ValueError(
            f"{repetitions} repetitions is below the suite's recorded plan of {planned}"
        )
    if len(scored) * repetitions > MAX_POPULATION:
        raise ValueError(
            f"{repetitions} repetitions of {len(scored)} edit cases is above the "
            f"maximum population of {MAX_POPULATION} slots"
        )
    if unknown := sorted({o.case_id for o in observations} - declared.keys()):
        raise ValueError(
            f"observations of cases the corpus does not declare: {unknown}"
        )
    slots: dict[tuple[str, int], Bucket] = {
        (c, n): b for c, b in scored.items() for n in range(1, repetitions + 1)
    }
    observed = {o.slot: o for o in observations if o.case_id in scored}
    if stray := sorted(observed.keys() - slots.keys()):
        raise ValueError(f"observations outside the declared population: {stray}")
    results: dict[tuple[str, int], tuple[Bucket, str]] = {
        slot: edit_outcome(observed[slot], bucket)
        if slot in observed
        else ("not_observed", "no_observation")
        for slot, bucket in slots.items()
    }
    counts = Counter(bucket for bucket, _ in results.values())
    ignored = sorted(o.case_id for o in observations if o.case_id not in scored)
    return {
        "attempted": len(slots),
        "repetitions": repetitions,
        "recorded_plan": len(scored) * planned,
        "expected": {
            bucket: list(scored.values()).count(bucket) * repetitions
            for bucket in _SCORED
        },
        "buckets": {bucket: counts[bucket] for bucket in BUCKETS},
        "first_failures": [
            {
                "case_id": case_id,
                "repetition": repetition,
                "bucket": bucket,
                "first_failure": first_failure,
            }
            for (case_id, repetition), (bucket, first_failure) in results.items()
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
        require_recorded_corpus(receipt, args.cases)
        report = edit_outcome_report(
            receipt.observations,
            declared=declared_cases(args.cases),
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
