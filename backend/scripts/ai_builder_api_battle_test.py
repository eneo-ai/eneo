#!/usr/bin/env python3
"""Run a local AI Builder create-session smoke test through the public API.

This script is intentionally API-facing: it exercises the same session/message
flow the UI uses, then saves the raw session, stream events, and stored plan.
Set ENEO_API_KEY in the environment; never commit local keys into this file.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import mimetypes
import os
import subprocess
import sys
import time
import unicodedata
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import uuid4

JsonObject = dict[str, Any]
DEFAULT_CASES_FILE = Path(__file__).with_name("ai_builder_api_battle_cases.json")
FIXTURE_DIR = Path(__file__).with_name("fixtures") / "ai_builder_battle"
FIXTURE_MANIFEST_FILE = FIXTURE_DIR / "manifest.json"
SUPPORTED_FIXTURE_MANIFEST_VERSION = 1
DEFAULT_CONFIRM_MESSAGE = "Ja, det stämmer. Bygg planen."
MAX_INTERACTIONS_PER_CASE = 6
SUPPORTED_CASES_FILE_VERSION = 6
# Bump when the meaning of question-relevance checks changes; receipts
# across different semantics versions must never be compared.
QUESTION_RELEVANCE_SEMANTICS_VERSION = 2
# v2: error-terminated journeys classify as their journey outcome
# (builder_error / provider_outcome_unknown) instead of being masked as
# invalid_evidence — a failed turn has no provenance to validate.
# v3: `fixture_skip` is gone. Fixtures are provisioned from git-pinned bytes,
# so a case can no longer silently drop out of the corpus because someone did
# not export an environment variable — the flagship runtime sentinel skipped
# itself that way through six full suite runs.
OUTCOME_CLASSIFICATION_SEMANTICS_VERSION = 3
SUPPORTED_RECEIPT_ARTIFACT_VERSION = "ai-builder-live-release.v3"


def _local_app_version() -> str:
    backend_src = Path(__file__).resolve().parents[1] / "src"
    sys.path.insert(0, str(backend_src))
    try:
        from eneo.main.config import get_settings

        return get_settings().app_version
    finally:
        try:
            sys.path.remove(str(backend_src))
        except ValueError:
            pass


LOCAL_APP_VERSION = os.getenv("ENEO_APP_VERSION") or _local_app_version()


@dataclass(frozen=True, slots=True)
class ApiConfig:
    base_url: str
    api_key: str
    timeout_seconds: int


class BattleTurnError(ValueError):
    """A failed logical Builder turn whose caller identity must remain recoverable."""

    def __init__(self, *, client_turn_id: str, cause: Exception) -> None:
        super().__init__(str(cause))
        self.client_turn_id = client_turn_id


def _failure_error_fields(error: Exception) -> JsonObject:
    fields: JsonObject = {"error": str(error)}
    if isinstance(error, BattleTurnError):
        fields["client_turn_id"] = error.client_turn_id
    return fields


@dataclass(frozen=True, slots=True)
class BattleCase:
    case_id: str
    prompt: str
    complexity: str = "custom"
    domain: str = "custom"
    required: bool = False
    apply_plan: bool = False
    execute_flow: bool = False
    release_dimensions: tuple[str, ...] = ()
    expected: JsonObject | None = None
    file_ids: tuple[str, ...] = ()
    attachments: tuple[str, ...] = ()
    runtime_files: tuple[str, ...] = ()
    synthetic_user_profile: str | None = None
    cohorts: tuple[str, ...] = ()
    configured_question_answers: JsonObject | None = None
    question_answer_sources: JsonObject | None = None


def _case_identity(case: BattleCase) -> JsonObject:
    return {
        "id": case.case_id,
        "required": case.required,
        "complexity": case.complexity,
        "domain": case.domain,
        "cohorts": list(case.cohorts),
    }


def _case_contract_payload(case: BattleCase) -> JsonObject:
    """Return the portable behavior contract for one selected benchmark case."""
    return {
        "id": case.case_id,
        "prompt": case.prompt,
        "complexity": case.complexity,
        "domain": case.domain,
        "required": case.required,
        "apply_plan": case.apply_plan,
        "execute_flow": case.execute_flow,
        "release_dimensions": list(case.release_dimensions),
        "expected": case.expected or {},
        # Fixtures are hashed by content, not named by environment variable: a
        # case that attaches different bytes is asking a different question and
        # must be rescored. Under the old env-var binding the blob behind a
        # name could change with no movement in this hash at all.
        "attachment_fixture": {
            "direct_file_slot_count": len(case.file_ids),
            "attachments": _fixture_contract(case.attachments),
            "runtime_files": _fixture_contract(case.runtime_files),
        },
        "synthetic_user_profile": case.synthetic_user_profile,
        "cohorts": list(case.cohorts),
        "configured_question_answers": case.configured_question_answers or {},
        "question_answer_sources": case.question_answer_sources or {},
    }


def _case_contract_sha256(case: BattleCase) -> str:
    return _canonical_sha256(_case_contract_payload(case))


def _observed_case_contract_payload(case: Mapping[str, object]) -> JsonObject:
    """Project persisted observation fields onto the authored case contract."""

    def string_list_or_none(value: object) -> list[str] | None:
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            return None
        return list(value)

    expected = case.get("expected")
    configured_answers = case.get("configured_question_answers")
    answer_sources = case.get("question_answer_sources")
    return {
        "id": case.get("id"),
        "prompt": case.get("prompt"),
        "complexity": case.get("complexity"),
        "domain": case.get("domain"),
        "required": case.get("required"),
        "apply_plan": case.get("apply_plan"),
        "execute_flow": case.get("execute_flow"),
        "release_dimensions": string_list_or_none(case.get("release_dimensions")),
        "expected": dict(expected) if isinstance(expected, Mapping) else None,
        "attachment_fixture": {
            "direct_file_slot_count": case.get("direct_file_slot_count"),
            "attachments": _fixture_contract_or_none(case.get("attachments")),
            "runtime_files": _fixture_contract_or_none(case.get("runtime_files")),
        },
        "synthetic_user_profile": case.get("synthetic_user_profile"),
        "cohorts": string_list_or_none(case.get("cohorts")),
        "configured_question_answers": (
            dict(configured_answers)
            if isinstance(configured_answers, Mapping)
            else None
        ),
        "question_answer_sources": (
            dict(answer_sources) if isinstance(answer_sources, Mapping) else None
        ),
    }


def _fixture_manifest(path: Path = FIXTURE_MANIFEST_FILE) -> dict[str, str]:
    """Fixture name -> pinned content SHA-256, read from the git-tracked corpus.

    This is the only place that decides what a fixture name means. Cases name
    fixtures; the harness verifies these bytes and uploads them itself, so a
    fresh checkout can run the suite with no hand-provisioned file ids.
    """

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a top-level JSON object.")
    version = payload.get("version")
    if version != SUPPORTED_FIXTURE_MANIFEST_VERSION:
        raise ValueError(
            f"{path} version must be {SUPPORTED_FIXTURE_MANIFEST_VERSION}; "
            f"got {version!r}."
        )
    fixtures = payload.get("fixtures")
    if not isinstance(fixtures, Mapping) or not fixtures:
        raise ValueError(f"{path} must contain a non-empty 'fixtures' object.")
    manifest: dict[str, str] = {}
    for name, sha256 in fixtures.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{path} fixture names must be non-empty strings.")
        if not _is_sha256(sha256):
            raise ValueError(f"{path} fixture {name} needs a SHA-256 content hash.")
        manifest[name] = sha256
    return manifest


def _fixture_contract(names: tuple[str, ...]) -> list[JsonObject]:
    manifest = _fixture_manifest()
    return [{"name": name, "content_sha256": manifest[name]} for name in names]


def _fixture_contract_or_none(value: object) -> list[JsonObject] | None:
    if not isinstance(value, list):
        return None
    entries: list[JsonObject] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"name", "content_sha256"}:
            return None
        entries.append({"name": item["name"], "content_sha256": item["content_sha256"]})
    return entries


def _verified_fixture_path(name: str, manifest: Mapping[str, str]) -> Path:
    """Resolve a fixture to bytes that still match the manifest.

    Verifying before upload is what makes the corpus portable: the question a
    case asks is pinned to content, so a corrupted or edited fixture stops the
    run instead of silently changing what was measured.
    """

    expected = manifest.get(name)
    if expected is None:
        raise ValueError(f"Unknown battle fixture: {name}")
    path = FIXTURE_DIR / name
    if not path.is_file():
        raise ValueError(f"Battle fixture is missing from the repository: {path}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(
            f"Battle fixture {name} does not match its manifest hash: "
            f"expected {expected}, got {actual}. Regenerate with "
            "scripts/generate_battle_fixtures.py."
        )
    return path


def _provision_fixtures(
    *,
    config: ApiConfig,
    cases: list[BattleCase],
) -> JsonObject:
    """Upload every fixture the selected cases need, once, before any case runs.

    A missing fixture used to surface mid-journey as a misleading builder error
    (an entire diagnostic day was once lost to that shape) or, worse, as a
    silent skip. Both failure modes are gone: provisioning happens up front and
    a failure stops the suite.
    """

    manifest = _fixture_manifest()
    needed = sorted(
        {name for case in cases for name in (*case.attachments, *case.runtime_files)}
    )
    provisioned: JsonObject = {}
    for name in needed:
        path = _verified_fixture_path(name, manifest)
        uploaded = _upload_file(config=config, source_path=path)
        provisioned[name] = {
            "file_id": _required_string(uploaded, "id"),
            "content_sha256": manifest[name],
            "path": str(path.relative_to(FIXTURE_DIR.parents[1])),
        }
    return provisioned


def _fixture_file_ids(
    names: tuple[str, ...],
    provisioned: Mapping[str, object],
) -> tuple[str, ...]:
    resolved: list[str] = []
    for name in names:
        entry = provisioned.get(name)
        if not isinstance(entry, Mapping):
            raise ValueError(f"Fixture {name} was never provisioned for this run.")
        resolved.append(_required_string(entry, "file_id"))
    return tuple(resolved)


@dataclass(frozen=True, slots=True)
class ReleaseThresholds:
    max_required_case_errors: int
    max_required_quality_failures: int


@dataclass(frozen=True, slots=True)
class ReleaseGate:
    required_case_ids: tuple[str, ...]
    thresholds: ReleaseThresholds
    artifact_schema_version: str = SUPPORTED_RECEIPT_ARTIFACT_VERSION
    require_clean_source: bool = False

    def __post_init__(self) -> None:
        if self.artifact_schema_version != SUPPORTED_RECEIPT_ARTIFACT_VERSION:
            raise ValueError(
                "release_gate.artifact_schema_version must be "
                f"{SUPPORTED_RECEIPT_ARTIFACT_VERSION}; got "
                f"{self.artifact_schema_version!r}."
            )


def main() -> int:
    args = _parse_args()
    if args.reanalyze_bundle:
        return _reanalyze_bundles(
            bundle_paths=[Path(path) for path in args.reanalyze_bundle],
            output_dir=Path(args.output_dir),
            expected_overrides_by_case_id=_expected_overrides_from_args(args),
            suite_summary_path=(
                Path(args.suite_summary) if args.suite_summary is not None else None
            ),
        )

    api_key = args.api_key or os.getenv("ENEO_API_KEY")
    if not api_key:
        print("ENEO_API_KEY or --api-key is required.", file=sys.stderr)
        return 2
    if not args.space_id:
        print("ENEO_SPACE_ID or --space-id is required.", file=sys.stderr)
        return 2

    config = ApiConfig(
        base_url=args.base_url.rstrip("/"),
        api_key=api_key,
        timeout_seconds=args.timeout_seconds,
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)

    try:
        cases = _cases_from_args(args)
        if args.run_suite or len(cases) > 1:
            return _run_suite(
                cases=cases,
                config=config,
                args=args,
                output_dir=output_dir,
                release_gate=(
                    _release_gate_from_args(args) if args.run_suite else None
                ),
            )
        case = cases[0]
        cases_path = _cases_path_from_args(args)
        bundle = _run_case(
            case=case,
            config=config,
            args=args,
            existing_session_id=args.session_id,
            artifact_output_dir=output_dir,
            cases_path=cases_path,
            provisioned_fixtures=_provision_fixtures(config=config, cases=[case]),
        )
        bundle_path = _write_bundle(output_dir, bundle, suffix=case.case_id)
        _print_summary(bundle["plan_summary"], bundle_path)
        return 0
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        started_at = time.strftime("%Y%m%dT%H%M%S")
        bundle_path = (
            output_dir / f"ai-builder-api-battle-test-{started_at}-failure.json"
        )
        failure: JsonObject = {
            "created_at": started_at,
            "app_version": LOCAL_APP_VERSION,
            "base_url": config.base_url,
            "space_id": args.space_id,
            **_failure_error_fields(error),
        }
        failure["artifact_mode"] = "live_execution_failure"
        _write_json_exclusive(bundle_path, failure)
        print(f"battle test failed: {error}", file=sys.stderr)
        print(f"failure bundle: {bundle_path}", file=sys.stderr)
        return 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exercise Flow AI Builder create mode through the local API."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("ENEO_API_BASE", "http://localhost:8123/api/v1"),
        help="API base URL, default: %(default)s",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key. Prefer ENEO_API_KEY so shell history does not contain it.",
    )
    parser.add_argument(
        "--space-id",
        default=os.getenv("ENEO_SPACE_ID"),
        help="Target space UUID. Can also be set with ENEO_SPACE_ID.",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help="Prompt text to send. Use --prompt-file for long prompts.",
    )
    parser.add_argument(
        "--prompt-file",
        default=None,
        help="Path to a UTF-8 prompt file.",
    )
    parser.add_argument(
        "--cases-file",
        default=None,
        help=(
            "JSON file with battle cases. Defaults to "
            "backend/scripts/ai_builder_api_battle_cases.json when --run-suite is used."
        ),
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=None,
        help="Run only this case id from --cases-file. Repeat for multiple cases.",
    )
    parser.add_argument(
        "--cohort",
        action="append",
        default=None,
        help=(
            "Run cases carrying this cohort from --cases-file. Repeat to require "
            "all named cohorts."
        ),
    )
    parser.add_argument(
        "--run-suite",
        action="store_true",
        help="Run all selected cases from --cases-file.",
    )
    parser.add_argument(
        "--reanalyze-bundle",
        action="append",
        default=None,
        help=(
            "Recompute summaries/checks for a previously saved bundle without "
            "calling the API. Repeat for multiple bundles."
        ),
    )
    parser.add_argument(
        "--suite-summary",
        default=None,
        help=(
            "Optional suite-summary.json that proves reanalyzed bundles belong "
            "to a completed suite receipt. Without it, reanalysis is explicitly "
            "marked as unverified standalone analysis."
        ),
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Limit the number of suite cases run.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=1,
        help=(
            "Run each selected suite case this many times. Use this to measure "
            "plan-rate / repair-failure-rate for stochastic builder behavior."
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help=(
            "Run this many suite observations at once. Observations are "
            "independent sessions and provider-latency bound, so this is the "
            "only lever that changes wall-clock cost. Recorded in run_context "
            "and gated by the comparator: receipts taken at different "
            "concurrency are not compared until the effect on provider error "
            "rate is measured. Default: %(default)s."
        ),
    )
    parser.add_argument("--model-id", default=None, help="Optional model UUID.")
    parser.add_argument(
        "--file-id",
        action="append",
        dest="file_ids",
        default=None,
        help="Optional attached file UUID. Repeat for multiple files.",
    )
    parser.add_argument("--ui-language", default="sv")
    parser.add_argument(
        "--session-id",
        default=None,
        help="Existing AI Builder session UUID to continue instead of creating a new session.",
    )
    parser.add_argument(
        "--no-auto-confirm-requirements",
        action="store_false",
        dest="auto_confirm_requirements",
        help="Do not send the structured requirements-confirmation turn automatically.",
    )
    parser.set_defaults(auto_confirm_requirements=True)
    parser.add_argument(
        "--confirm-message",
        default=DEFAULT_CONFIRM_MESSAGE,
        help="Message text for the automatic requirements-confirmation turn.",
    )
    parser.add_argument("--force-new", action="store_true")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=900,
        help="HTTP timeout per request/stream.",
    )
    parser.add_argument(
        "--output-dir",
        default=".codex/artifacts/ai-builder-api-battle-tests",
        help="Directory for raw result bundles.",
    )
    return parser.parse_args()


def _read_prompt(args: argparse.Namespace) -> str:
    if args.prompt and args.prompt_file:
        raise ValueError("Use either --prompt or --prompt-file, not both.")
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    elif args.prompt:
        prompt = args.prompt
    else:
        raise ValueError("--prompt or --prompt-file is required.")
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("Prompt must not be empty.")
    return prompt


def _cases_from_args(args: argparse.Namespace) -> list[BattleCase]:
    if getattr(args, "run_suite", False) and (
        getattr(args, "case_id", None)
        or getattr(args, "cohort", None)
        or getattr(args, "max_cases", None) is not None
        or getattr(args, "file_ids", None)
    ):
        raise ValueError(
            "--run-suite is the full benchmark run, including its sentinel gate, "
            "and cannot be filtered. "
            "Omit --run-suite to use --cohort, --case-id, --max-cases, or "
            "--file-id in an exploratory suite."
        )
    cases_file = _cases_path_from_args(args)
    if cases_file is not None:
        cases = _read_cases_file(cases_file)
        selected_cohorts = set(getattr(args, "cohort", None) or ())
        if selected_cohorts:
            known_cohorts = {cohort for case in cases for cohort in case.cohorts}
            missing_cohorts = selected_cohorts - known_cohorts
            if missing_cohorts:
                raise ValueError(
                    "Unknown battle cohort(s): " + ", ".join(sorted(missing_cohorts))
                )
            cases = [case for case in cases if selected_cohorts.issubset(case.cohorts)]
        selected = set(args.case_id or ())
        if selected:
            cases = [case for case in cases if case.case_id in selected]
            missing = selected - {case.case_id for case in cases}
            if missing:
                raise ValueError(
                    f"Unknown battle case id(s): {', '.join(sorted(missing))}"
                )
        if args.max_cases is not None:
            cases = cases[: args.max_cases]
        if not cases:
            raise ValueError("No battle cases selected.")
        return cases

    return [
        BattleCase(
            case_id="custom",
            prompt=_read_prompt(args),
            file_ids=tuple(args.file_ids or ()),
        )
    ]


def _cases_path_from_args(args: argparse.Namespace) -> Path | None:
    cases_file = getattr(args, "cases_file", None)
    if (
        getattr(args, "run_suite", False)
        or cases_file
        or getattr(args, "case_id", None)
        or getattr(args, "cohort", None)
    ):
        return Path(cases_file) if cases_file else DEFAULT_CASES_FILE
    return None


_CLASSIFIER_SLOT_EXPECTATION_KEYS = frozenset(
    {
        "slot_name",
        "value",
        "confidence",
        "confidence_in",
        "evidence_level",
        "source_kinds",
        "required_source_kinds",
        "evidence_quotes",
        "evidence_contains",
    }
)
_CLASSIFIER_FILE_ROLE_EXPECTATION_KEYS = frozenset(
    {
        "file_id",
        "file_index",
        "role",
        "confidence",
        "confidence_in",
        "evidence_level",
        "coverage",
        "coverage_in",
        "source_kinds",
        "required_source_kinds",
        "evidence_quotes",
        "evidence_contains",
    }
)
_CLASSIFIER_EXPECTATION_STRING_LIST_KEYS = frozenset(
    {
        "confidence_in",
        "coverage_in",
        "source_kinds",
        "required_source_kinds",
        "evidence_quotes",
        "evidence_contains",
    }
)
_CLASSIFIER_EXPECTATION_STRING_KEYS = frozenset(
    {
        "slot_name",
        "value",
        "file_id",
        "role",
        "confidence",
        "evidence_level",
        "coverage",
    }
)
_EVIDENCE_POSTURE_EXPECTATION_KEYS = frozenset(
    {
        "expected_classifier_slots",
        "expected_file_roles",
        "forbid_classifier_commit_grade_slots",
        "expected_assumption_topics",
        "forbidden_assumption_topics",
    }
)
_EVIDENCE_POSTURE_EXPECTATION_PREFIXES = (
    "expected_classifier",
    "expected_file_role",
    "forbid_classifier",
    "expected_assumption",
    "forbidden_assumption",
)
_CASE_KEYS = frozenset(
    {
        "id",
        "prompt",
        "complexity",
        "domain",
        "required",
        "apply_plan",
        "execute_flow",
        "release_dimensions",
        "expected",
        "file_ids",
        "attachments",
        "runtime_files",
        "synthetic_user_profile",
        "question_answer_overrides",
        "cohorts",
    }
)
_EXPECTATION_KEYS = frozenset(
    {
        "allow_question_instead_of_plan",
        "expected_classifier_slots",
        "expected_file_roles",
        "expected_form_field_groups",
        "expected_input_contract_schema",
        "expected_leaf_output_field_groups",
        "expected_output_contract_schema",
        "expected_output_modes",
        "expected_persisted_named_results",
        "expected_plan_invariant_vector",
        "expected_primary_input_type",
        "expected_question_event_count",
        "expected_question_event_ids",
        "preferred_question_event_ids",
        "allowed_question_event_ids",
        "expected_first_pass_authoring",
        "expected_review_policy",
        "expected_runtime_evidence",
        "forbid_classifier_commit_grade_slots",
        "forbid_generic_primary_reader_envelope",
        "forbid_input_sources",
        "forbid_primary_material_form_fields",
        "forbidden_form_field_groups",
        "forbidden_assumption_topics",
        "forbidden_question_event_ids",
        "max_all_previous_steps",
        "max_post_json_text_cleanup_steps",
        "max_question_event_count",
        "max_reopened_question_count",
        "max_steps",
        "min_form_field_count",
        "min_json_steps",
        "min_question_event_count",
        "min_source_ref_steps",
        "min_steps",
        "terminal_document_output_mode",
        "terminal_output_type",
        "terminal_output_types",
    }
)
_REVIEW_POLICY_EXPECTATION_KEYS = frozenset(
    {
        "mode",
        "target_output_type",
        "target_field_groups",
        "target_must_be_non_terminal",
    }
)
_FIRST_PASS_AUTHORING_EXPECTATION_KEYS = frozenset(
    {
        "document_writer_count",
        "expected_step_output_modes",
        "expected_step_output_types",
        "forbidden_task_heading_groups",
        "max_repair_attempts",
        "proposal_call_count",
        "provider_failure_status",
        "report_section_groups",
        "require_classifier_request_composite_fingerprint",
        "require_progress_fingerprint",
        "review_targets",
    }
)
_FIRST_PASS_REVIEW_TARGET_KEYS = frozenset({"mode", "output_mode", "output_type"})
_RUNTIME_EVIDENCE_EXPECTATION_KEYS = frozenset(
    {
        "source_file_count",
        "source_record_count",
        "required_final_field_label_groups",
        "required_visible_degradation_markers",
        "source_display_count",
        "model_call_count",
        "max_total_tokens",
    }
)


def _read_cases_file(path: Path) -> list[BattleCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a top-level JSON object.")
    version = payload.get("version")
    if version != SUPPORTED_CASES_FILE_VERSION:
        raise ValueError(
            f"{path} version must be {SUPPORTED_CASES_FILE_VERSION}; got {version!r}."
        )
    raw_cases = payload.get("cases") if isinstance(payload, Mapping) else None
    if not isinstance(raw_cases, list):
        raise ValueError(f"{path} must contain a top-level 'cases' list.")
    profiles = _synthetic_user_profiles(path, payload)
    manifest = _fixture_manifest()

    cases: list[BattleCase] = []
    seen_case_ids: set[str] = set()
    seen_prompts: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, Mapping):
            raise ValueError(f"{path} cases[{index}] must be an object.")
        unknown_case_keys = set(raw_case) - _CASE_KEYS
        if unknown_case_keys:
            raise ValueError(
                f"{path} cases[{index}] has unknown keys: "
                + ", ".join(sorted(str(key) for key in unknown_case_keys))
            )
        case_id = _required_string(raw_case, "id")
        prompt = _required_string(raw_case, "prompt").strip()
        if not prompt:
            raise ValueError(f"{path} case {case_id} has an empty prompt.")
        if case_id in seen_case_ids:
            raise ValueError(f"{path} contains duplicate case id: {case_id}")
        if prompt in seen_prompts:
            raise ValueError(f"{path} contains duplicate prompt in case: {case_id}")
        seen_case_ids.add(case_id)
        seen_prompts.add(prompt)
        file_ids = raw_case.get("file_ids")
        if file_ids is None:
            file_ids = []
        if not isinstance(file_ids, list) or not all(
            isinstance(file_id, str) for file_id in file_ids
        ):
            raise ValueError(f"{path} case {case_id}.file_ids must be a string list.")
        attachments = _case_fixture_names(
            raw_case.get("attachments"),
            manifest=manifest,
            owner=f"{path} case {case_id}.attachments",
        )
        runtime_files = _case_fixture_names(
            raw_case.get("runtime_files"),
            manifest=manifest,
            owner=f"{path} case {case_id}.runtime_files",
        )
        if raw_case.get("execute_flow") is not True and runtime_files:
            raise ValueError(
                f"{path} case {case_id} cannot declare runtime_files without "
                "execute_flow=true."
            )
        release_dimensions = raw_case.get("release_dimensions")
        if release_dimensions is None:
            release_dimensions = []
        if not isinstance(release_dimensions, list) or not all(
            isinstance(dimension, str) and dimension.strip()
            for dimension in release_dimensions
        ):
            raise ValueError(
                f"{path} case {case_id}.release_dimensions must be a string list."
            )
        cohorts = raw_case.get("cohorts")
        if cohorts is None:
            cohorts = []
        if (
            not isinstance(cohorts, list)
            or not all(isinstance(cohort, str) and cohort.strip() for cohort in cohorts)
            or len(set(cohorts)) != len(cohorts)
        ):
            raise ValueError(f"{path} case {case_id}.cohorts must be unique strings.")
        expected = raw_case.get("expected")
        if expected is not None and not isinstance(expected, Mapping):
            raise ValueError(f"{path} case {case_id}.expected must be an object.")
        if isinstance(expected, Mapping):
            _validate_classifier_expectations(path, case_id, expected)
            _validate_release_expectations(path, case_id, expected)
        profile_name = raw_case.get("synthetic_user_profile")
        if profile_name is not None and (
            not isinstance(profile_name, str) or profile_name not in profiles
        ):
            raise ValueError(
                f"{path} case {case_id}.synthetic_user_profile is unknown."
            )
        overrides = raw_case.get("question_answer_overrides")
        if overrides is None:
            overrides = {}
        _validate_question_answers(
            path=path,
            owner=f"case {case_id}.question_answer_overrides",
            value=overrides,
        )
        profile_answers = (
            profiles[profile_name]["question_answers"]
            if isinstance(profile_name, str)
            else {}
        )
        configured_answers = {
            **dict(profile_answers),
            **dict(overrides),
        }
        answer_sources = {
            **{question_id: "profile" for question_id in profile_answers},
            **{question_id: "case_override" for question_id in overrides},
        }
        if (
            isinstance(expected, Mapping)
            and expected.get("allow_question_instead_of_plan") is not True
        ):
            answered_question_ids = set(configured_answers)
            required_answer_ids = {
                question_id
                for key in (
                    "preferred_question_event_ids",
                    "allowed_question_event_ids",
                )
                for question_id in _string_list(expected.get(key))
            }
            missing_answer_ids = required_answer_ids - answered_question_ids
            if missing_answer_ids:
                raise ValueError(
                    f"{path} case {case_id} requires configured answers for: "
                    + ", ".join(sorted(missing_answer_ids))
                )
        case = BattleCase(
            case_id=case_id,
            prompt=prompt,
            complexity=str(raw_case.get("complexity") or "custom"),
            domain=str(raw_case.get("domain") or "custom"),
            required=raw_case.get("required") is True,
            apply_plan=raw_case.get("apply_plan") is True,
            execute_flow=raw_case.get("execute_flow") is True,
            release_dimensions=tuple(release_dimensions),
            expected=dict(expected) if isinstance(expected, Mapping) else None,
            file_ids=tuple(file_ids),
            attachments=attachments,
            runtime_files=runtime_files,
            synthetic_user_profile=(
                profile_name if isinstance(profile_name, str) else None
            ),
            cohorts=tuple(cohorts),
            configured_question_answers=configured_answers,
            question_answer_sources=answer_sources,
        )
        if case.execute_flow and not case.apply_plan:
            raise ValueError(
                f"{path} case {case_id} cannot execute without apply_plan=true."
            )
        if case.execute_flow and not case.runtime_files:
            raise ValueError(f"{path} case {case_id} must declare runtime_files.")
        cases.append(case)
    return cases


def _case_fixture_names(
    value: object,
    *,
    manifest: Mapping[str, str],
    owner: str,
) -> tuple[str, ...]:
    """Validate declared fixture names against the manifest, offline.

    A broken fixture reference now fails when the corpus is read — in the unit
    suite, in a second — instead of 40 minutes into a live run.
    """

    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(name, str) and name.strip() for name in value
    ):
        raise ValueError(f"{owner} must be a list of fixture names.")
    names = tuple(str(name) for name in value)
    unknown = [name for name in names if name not in manifest]
    if unknown:
        raise ValueError(
            f"{owner} names unknown fixture(s): {', '.join(sorted(set(unknown)))}. "
            f"Known fixtures: {', '.join(sorted(manifest))}."
        )
    return names


def _synthetic_user_profiles(
    path: Path,
    payload: object,
) -> dict[str, JsonObject]:
    raw_profiles = (
        payload.get("synthetic_user_profiles") if isinstance(payload, Mapping) else None
    )
    if raw_profiles is None:
        return {}
    if not isinstance(raw_profiles, Mapping):
        raise ValueError(f"{path} synthetic_user_profiles must be an object.")
    profiles: dict[str, JsonObject] = {}
    for raw_name, raw_profile in raw_profiles.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError(f"{path} synthetic user profile names must be strings.")
        if not isinstance(raw_profile, Mapping) or set(raw_profile) != {
            "description",
            "question_answers",
        }:
            raise ValueError(
                f"{path} synthetic user profile {raw_name} has an invalid shape."
            )
        description = raw_profile.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(
                f"{path} synthetic user profile {raw_name} needs a description."
            )
        answers = raw_profile.get("question_answers")
        _validate_question_answers(
            path=path,
            owner=f"synthetic user profile {raw_name}.question_answers",
            value=answers,
        )
        profiles[raw_name] = {
            "description": description.strip(),
            "question_answers": dict(answers),
        }
    return profiles


def _validate_question_answers(
    *,
    path: Path,
    owner: str,
    value: object,
) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} {owner} must be an object.")
    for question_id, answer in value.items():
        if not isinstance(question_id, str) or not question_id.strip():
            raise ValueError(f"{path} {owner} has an invalid question id.")
        if not isinstance(answer, Mapping):
            raise ValueError(f"{path} {owner}.{question_id} must be an object.")
        answer_keys = set(answer)
        valid_shapes = (
            (
                answer_keys == {"selected_option_id"}
                and isinstance(answer.get("selected_option_id"), str)
                and bool(str(answer["selected_option_id"]).strip())
            )
            or (
                answer_keys == {"selected_option_ids"}
                and isinstance(answer.get("selected_option_ids"), list)
                and bool(answer["selected_option_ids"])
                and all(
                    isinstance(option_id, str) and bool(option_id.strip())
                    for option_id in answer["selected_option_ids"]
                )
            )
            or (
                answer_keys == {"custom_value"}
                and isinstance(answer.get("custom_value"), str)
                and bool(str(answer["custom_value"]).strip())
            )
        )
        if not valid_shapes:
            raise ValueError(
                f"{path} {owner}.{question_id} must contain exactly one valid "
                "answer mode."
            )


def _release_gate_from_args(args: argparse.Namespace) -> ReleaseGate:
    path = Path(args.cases_file) if args.cases_file else DEFAULT_CASES_FILE
    return _read_release_gate(path, cases=_read_cases_file(path))


def _read_release_gate(path: Path, *, cases: list[BattleCase]) -> ReleaseGate:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_gate = payload.get("release_gate") if isinstance(payload, Mapping) else None
    if not isinstance(raw_gate, Mapping):
        raise ValueError(f"{path} must contain a top-level 'release_gate' object.")
    expected_gate_keys = {
        "artifact_schema_version",
        "require_clean_source",
        "thresholds",
    }
    if set(raw_gate) != expected_gate_keys:
        raise ValueError(
            f"{path} release_gate must contain exactly: "
            + ", ".join(sorted(expected_gate_keys))
        )
    artifact_schema_version = raw_gate.get("artifact_schema_version")
    if not isinstance(artifact_schema_version, str) or not artifact_schema_version:
        raise ValueError(
            f"{path} release_gate.artifact_schema_version must be a string."
        )
    require_clean_source = raw_gate.get("require_clean_source")
    if not isinstance(require_clean_source, bool):
        raise ValueError(f"{path} release_gate.require_clean_source must be a boolean.")
    required_case_ids = tuple(case.case_id for case in cases if case.required)
    if not required_case_ids:
        raise ValueError(f"{path} must mark at least one case as required.")
    raw_thresholds = raw_gate.get("thresholds")
    expected_threshold_keys = {
        "max_required_case_errors",
        "max_required_quality_failures",
    }
    if not isinstance(raw_thresholds, Mapping) or set(raw_thresholds) != (
        expected_threshold_keys
    ):
        raise ValueError(
            f"{path} release_gate.thresholds must contain exactly: "
            + ", ".join(sorted(expected_threshold_keys))
        )
    threshold_values: dict[str, int] = {}
    for key in sorted(expected_threshold_keys):
        value = raw_thresholds[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"{path} release_gate.thresholds.{key} must be a non-negative integer."
            )
        threshold_values[key] = value
    return ReleaseGate(
        required_case_ids=required_case_ids,
        thresholds=ReleaseThresholds(**threshold_values),
        artifact_schema_version=artifact_schema_version,
        require_clean_source=require_clean_source,
    )


def _validate_release_expectations(
    path: Path,
    case_id: str,
    expected: Mapping[str, object],
) -> None:
    unknown_keys = set(expected) - _EXPECTATION_KEYS
    if unknown_keys:
        raise ValueError(
            f"{path} case {case_id}.expected has unknown expectation keys: "
            + ", ".join(sorted(str(key) for key in unknown_keys))
        )
    expected_primary_input_type = expected.get("expected_primary_input_type")
    if expected_primary_input_type is not None and (
        not isinstance(expected_primary_input_type, str)
        or not expected_primary_input_type.strip()
    ):
        raise ValueError(
            f"{path} case {case_id}.expected_primary_input_type must be a "
            "non-empty string."
        )
    for key in (
        "expected_persisted_named_results",
        "expected_plan_invariant_vector",
    ):
        if key in expected and expected.get(key) is not True:
            raise ValueError(f"{path} case {case_id}.{key} must be true.")
    relevance_sets: dict[str, set[str]] = {}
    for key in (
        "preferred_question_event_ids",
        "allowed_question_event_ids",
        "forbidden_question_event_ids",
    ):
        raw_ids = expected.get(key)
        if raw_ids is None:
            relevance_sets[key] = set()
            continue
        if (
            not isinstance(raw_ids, list)
            or not all(isinstance(item, str) and item.strip() for item in raw_ids)
            or len(set(raw_ids)) != len(raw_ids)
        ):
            raise ValueError(
                f"{path} case {case_id}.{key} must be a list of unique, "
                "non-empty strings."
            )
        relevance_sets[key] = set(raw_ids)
    overlapping_relevance_ids = (
        (
            relevance_sets["preferred_question_event_ids"]
            & relevance_sets["allowed_question_event_ids"]
        )
        | (
            relevance_sets["preferred_question_event_ids"]
            & relevance_sets["forbidden_question_event_ids"]
        )
        | (
            relevance_sets["allowed_question_event_ids"]
            & relevance_sets["forbidden_question_event_ids"]
        )
    )
    if overlapping_relevance_ids:
        raise ValueError(
            f"{path} case {case_id} question relevance sets overlap: "
            + ", ".join(sorted(overlapping_relevance_ids))
        )
    for schema_key in (
        "expected_input_contract_schema",
        "expected_output_contract_schema",
    ):
        schema = expected.get(schema_key)
        if schema is not None and not isinstance(schema, Mapping):
            raise ValueError(
                f"{path} case {case_id}.{schema_key} must be a JSON object."
            )
    first_pass = expected.get("expected_first_pass_authoring")
    if first_pass is not None:
        _validate_first_pass_authoring_expectation(path, case_id, first_pass)
    review_policy = expected.get("expected_review_policy")
    if review_policy is not None:
        if not isinstance(review_policy, Mapping) or set(review_policy) != (
            _REVIEW_POLICY_EXPECTATION_KEYS
        ):
            raise ValueError(
                f"{path} case {case_id}.expected_review_policy has an invalid shape."
            )
        if review_policy.get("mode") not in {"view", "edit"}:
            raise ValueError(
                f"{path} case {case_id}.expected_review_policy.mode is invalid."
            )
        if review_policy.get("target_must_be_non_terminal") is not True:
            raise ValueError(
                f"{path} case {case_id}.expected_review_policy must target a "
                "non-terminal step."
            )
        _require_non_empty_field_groups(
            path,
            case_id,
            "expected_review_policy.target_field_groups",
            review_policy.get("target_field_groups"),
        )
    runtime_evidence = expected.get("expected_runtime_evidence")
    if runtime_evidence is not None:
        if not isinstance(runtime_evidence, Mapping) or set(runtime_evidence) != (
            _RUNTIME_EVIDENCE_EXPECTATION_KEYS
        ):
            raise ValueError(
                f"{path} case {case_id}.expected_runtime_evidence has an invalid shape."
            )
        for key in (
            "source_file_count",
            "source_record_count",
            "source_display_count",
            "model_call_count",
            "max_total_tokens",
        ):
            value = runtime_evidence.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(
                    f"{path} case {case_id}.expected_runtime_evidence.{key} "
                    "must be a positive integer."
                )
        for key in (
            "required_final_field_label_groups",
            "required_visible_degradation_markers",
        ):
            _require_non_empty_field_groups(
                path,
                case_id,
                f"expected_runtime_evidence.{key}",
                runtime_evidence.get(key),
            )


def _validate_first_pass_authoring_expectation(
    path: Path,
    case_id: str,
    value: object,
) -> None:
    if not isinstance(value, Mapping) or set(value) != (
        _FIRST_PASS_AUTHORING_EXPECTATION_KEYS
    ):
        raise ValueError(
            f"{path} case {case_id}.expected_first_pass_authoring has an invalid shape."
        )
    output_types = _string_list(value.get("expected_step_output_types"))
    output_modes = _string_list(value.get("expected_step_output_modes"))
    if not output_types or len(output_types) != len(output_modes):
        raise ValueError(
            f"{path} case {case_id}.expected_first_pass_authoring must declare "
            "matching non-empty step output types and modes."
        )
    for key in ("report_section_groups", "forbidden_task_heading_groups"):
        _require_non_empty_field_groups(
            path,
            case_id,
            f"expected_first_pass_authoring.{key}",
            value.get(key),
        )
    review_targets = value.get("review_targets")
    if not isinstance(review_targets, list) or len(review_targets) != 2:
        raise ValueError(
            f"{path} case {case_id}.expected_first_pass_authoring.review_targets "
            "must contain exactly two targets."
        )
    for target in review_targets:
        if not isinstance(target, Mapping) or set(target) != (
            _FIRST_PASS_REVIEW_TARGET_KEYS
        ):
            raise ValueError(
                f"{path} case {case_id}.expected_first_pass_authoring.review_targets "
                "has an invalid target."
            )
        if target.get("mode") not in {"view", "edit"} or not all(
            isinstance(target.get(key), str) and target.get(key)
            for key in ("output_type", "output_mode")
        ):
            raise ValueError(
                f"{path} case {case_id}.expected_first_pass_authoring.review_targets "
                "has an invalid mode or output target."
            )
    for key in ("document_writer_count", "proposal_call_count"):
        count = value.get(key)
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            raise ValueError(
                f"{path} case {case_id}.expected_first_pass_authoring.{key} "
                "must be a positive integer."
            )
    max_repairs = value.get("max_repair_attempts")
    if (
        not isinstance(max_repairs, int)
        or isinstance(max_repairs, bool)
        or max_repairs < 0
    ):
        raise ValueError(
            f"{path} case {case_id}.expected_first_pass_authoring."
            "max_repair_attempts must be a non-negative integer."
        )
    if any(
        value.get(key) is not True
        for key in (
            "require_classifier_request_composite_fingerprint",
            "require_progress_fingerprint",
        )
    ):
        raise ValueError(
            f"{path} case {case_id}.expected_first_pass_authoring must require "
            "capability and progress fingerprints."
        )
    if value.get("provider_failure_status") != "none":
        raise ValueError(
            f"{path} case {case_id}.expected_first_pass_authoring requires a "
            "failure-free first proposal."
        )


def _require_non_empty_field_groups(
    path: Path,
    case_id: str,
    key: str,
    value: object,
) -> None:
    if (
        not isinstance(value, list)
        or not value
        or not all(
            isinstance(group, list)
            and group
            and all(isinstance(item, str) and item.strip() for item in group)
            for group in value
        )
    ):
        raise ValueError(
            f"{path} case {case_id}.{key} must be non-empty string groups."
        )


def _validate_classifier_expectations(
    path: Path,
    case_id: str,
    expected: Mapping[str, object],
) -> None:
    unknown_evidence_posture_keys = [
        key
        for key in expected
        if isinstance(key, str)
        and key.startswith(_EVIDENCE_POSTURE_EXPECTATION_PREFIXES)
        and key not in _EVIDENCE_POSTURE_EXPECTATION_KEYS
    ]
    if unknown_evidence_posture_keys:
        raise ValueError(
            f"{path} case {case_id}.expected has unknown evidence-posture keys: "
            f"{', '.join(sorted(unknown_evidence_posture_keys))}."
        )
    for key in (
        "forbid_classifier_commit_grade_slots",
        "expected_assumption_topics",
        "forbidden_assumption_topics",
    ):
        value = expected.get(key)
        if value is not None and (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item.strip() for item in value)
        ):
            raise ValueError(
                f"{path} case {case_id}.expected.{key} must be a non-empty string list."
            )
    for key, allowed_keys, required_string in (
        (
            "expected_classifier_slots",
            _CLASSIFIER_SLOT_EXPECTATION_KEYS,
            "slot_name",
        ),
        (
            "expected_file_roles",
            _CLASSIFIER_FILE_ROLE_EXPECTATION_KEYS,
            "role",
        ),
    ):
        raw_rows = expected.get(key)
        if raw_rows is None:
            continue
        if not isinstance(raw_rows, list):
            raise ValueError(f"{path} case {case_id}.{key} must be an object list.")
        for index, raw_row in enumerate(raw_rows):
            if not isinstance(raw_row, Mapping):
                raise ValueError(
                    f"{path} case {case_id}.{key}[{index}] must be an object."
                )
            unknown_keys = set(raw_row) - allowed_keys
            if unknown_keys:
                raise ValueError(
                    f"{path} case {case_id}.{key}[{index}] has unknown keys: "
                    f"{', '.join(sorted(str(item) for item in unknown_keys))}."
                )
            if (
                not isinstance(raw_row.get(required_string), str)
                or not str(raw_row[required_string]).strip()
            ):
                raise ValueError(
                    f"{path} case {case_id}.{key}[{index}].{required_string} "
                    "must be a non-empty string."
                )
            for list_key in _CLASSIFIER_EXPECTATION_STRING_LIST_KEYS.intersection(
                raw_row
            ):
                value = raw_row[list_key]
                if (
                    not isinstance(value, list)
                    or not value
                    or not all(isinstance(item, str) and item.strip() for item in value)
                ):
                    raise ValueError(
                        f"{path} case {case_id}.{key}[{index}].{list_key} "
                        "must be a non-empty string list."
                    )
            for string_key in _CLASSIFIER_EXPECTATION_STRING_KEYS.intersection(raw_row):
                value = raw_row[string_key]
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"{path} case {case_id}.{key}[{index}].{string_key} "
                        "must be a non-empty string."
                    )
            if key == "expected_file_roles":
                file_id = raw_row.get("file_id")
                file_index = raw_row.get("file_index")
                has_file_id = isinstance(file_id, str) and bool(file_id.strip())
                has_file_index = isinstance(file_index, int) and not isinstance(
                    file_index, bool
                )
                if has_file_index and file_index < 0:
                    raise ValueError(
                        f"{path} case {case_id}.{key}[{index}].file_index must "
                        "be non-negative."
                    )
                if has_file_id == has_file_index:
                    raise ValueError(
                        f"{path} case {case_id}.{key}[{index}] must set exactly one "
                        "of file_id or file_index."
                    )


def _expected_overrides_from_args(args: argparse.Namespace) -> dict[str, JsonObject]:
    if not args.cases_file:
        return {}
    overrides: dict[str, JsonObject] = {}
    for case in _read_cases_file(Path(args.cases_file)):
        if case.expected is not None:
            overrides[case.case_id] = dict(case.expected)
    return overrides


def _expected_observations(
    cases: list[BattleCase], repetitions: int
) -> list[JsonObject]:
    return [
        {
            "case_id": case.case_id,
            "repetition": repetition,
            "case_contract_sha256": _case_contract_sha256(case),
        }
        for repetition in range(1, repetitions + 1)
        for case in cases
    ]


def _max_concurrency(args: argparse.Namespace) -> int:
    value = getattr(args, "concurrency", 1)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("--concurrency must be a positive integer.")
    return value


def _suite_run_context(args: argparse.Namespace) -> JsonObject:
    confirm_message = getattr(args, "confirm_message", DEFAULT_CONFIRM_MESSAGE)
    return {
        "ui_language": getattr(args, "ui_language", "sv"),
        "auto_confirm_requirements": getattr(
            args,
            "auto_confirm_requirements",
            True,
        ),
        "confirm_message_sha256": hashlib.sha256(
            str(confirm_message).encode("utf-8")
        ).hexdigest(),
        "repetitions": args.repetitions,
        # Concurrency is recorded and gated, not merely reported: parallel
        # sessions share provider capacity, and provider_outcome_unknown is
        # already 3-5 cases per pass. Whether that rate moves with load is an
        # open question, so receipts taken under different concurrency are not
        # assumed comparable until someone measures it.
        "max_concurrency": _max_concurrency(args),
    }


def _suite_evaluator_identity(
    *,
    release_identity: Mapping[str, object],
    run_context: Mapping[str, object],
    expected_observations: list[JsonObject],
) -> JsonObject:
    build = release_identity.get("build")
    build = build if isinstance(build, Mapping) else {}
    model = release_identity.get("model")
    model = model if isinstance(model, Mapping) else {}
    target = release_identity.get("target")
    target = target if isinstance(target, Mapping) else {}
    selected_case_contracts = {
        str(observation["case_id"]): observation["case_contract_sha256"]
        for observation in expected_observations
    }
    payload = {
        "question_relevance_semantics_version": (QUESTION_RELEVANCE_SEMANTICS_VERSION),
        "outcome_classification_semantics_version": (
            OUTCOME_CLASSIFICATION_SEMANTICS_VERSION
        ),
        "source_revision": build.get("source_revision"),
        "harness_sha256": build.get("harness_sha256"),
        "cases_sha256": build.get("cases_sha256"),
        "requested_model_id": model.get("requested_id"),
        "target_sha256": target.get("sha256"),
        "run_context": dict(run_context),
        "case_contract_sha256_by_id": selected_case_contracts,
    }
    return {**payload, "sha256": _canonical_sha256(payload)}


def _run_suite(
    *,
    cases: list[BattleCase],
    config: ApiConfig,
    args: argparse.Namespace,
    output_dir: Path,
    release_gate: ReleaseGate | None = None,
) -> int:
    if args.repetitions < 1:
        raise ValueError("--repetitions must be >= 1.")
    release_gate_supplied = release_gate is not None
    release_gate = release_gate or ReleaseGate(
        required_case_ids=tuple(case.case_id for case in cases if case.required),
        thresholds=ReleaseThresholds(
            max_required_case_errors=0,
            max_required_quality_failures=0,
        ),
    )
    is_release_run = release_gate_supplied and bool(release_gate.required_case_ids)
    selected_case_ids = {case.case_id for case in cases}
    missing_required_cases = set(release_gate.required_case_ids) - selected_case_ids
    if missing_required_cases:
        raise ValueError(
            "Release suite omitted required case(s): "
            + ", ".join(sorted(missing_required_cases))
        )
    cases_path = _cases_path_from_args(args) or DEFAULT_CASES_FILE
    requested_model_id = getattr(args, "model_id", None)
    if is_release_run and (
        not isinstance(requested_model_id, str) or not requested_model_id.strip()
    ):
        raise ValueError("Release suite requires --model-id before execution.")
    release_identity = _release_run_identity(
        cases=cases,
        cases_path=cases_path,
        requested_model_id=requested_model_id,
        require_clean_source=release_gate.require_clean_source,
        config=config if is_release_run else None,
    )
    provisioned_fixtures = _provision_fixtures(config=config, cases=cases)
    expected_observations = _expected_observations(cases, args.repetitions)
    run_context = _suite_run_context(args)
    evaluator_identity = _suite_evaluator_identity(
        release_identity=release_identity,
        run_context=run_context,
        expected_observations=expected_observations,
    )
    started_at = time.strftime("%Y%m%dT%H%M%S")
    suite_dir = output_dir / f"ai-builder-api-battle-suite-{started_at}"
    suite_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(suite_dir, 0o700)
    _write_json_exclusive(
        suite_dir / "release-manifest.json",
        {
            "artifact_schema_version": release_gate.artifact_schema_version,
            "artifact_mode": "live_execution_manifest",
            "created_at": started_at,
            "release_identity": release_identity,
            "evaluator_identity": evaluator_identity,
            "run_context": run_context,
            "expected_observations": expected_observations,
            "required_case_ids": list(release_gate.required_case_ids),
            "thresholds": {
                "max_required_case_errors": (
                    release_gate.thresholds.max_required_case_errors
                ),
                "max_required_quality_failures": (
                    release_gate.thresholds.max_required_quality_failures
                ),
            },
            "selected_cases": [
                {
                    "case_identity": _case_identity(case),
                    "release_dimensions": list(case.release_dimensions),
                    "case_contract_sha256": _case_contract_sha256(case),
                    "prompt_sha256": hashlib.sha256(
                        case.prompt.encode("utf-8")
                    ).hexdigest(),
                }
                for case in cases
            ],
        },
    )
    total_runs = len(cases) * args.repetitions
    max_concurrency = _max_concurrency(args)
    observations = [
        (repetition, case_index, case)
        for repetition in range(1, args.repetitions + 1)
        for case_index, case in enumerate(cases, start=1)
    ]

    def run_observation(
        item: tuple[int, int, BattleCase],
    ) -> JsonObject:
        repetition, case_index, case = item
        repetition_suffix = f"-r{repetition:02d}" if args.repetitions > 1 else ""
        label = (
            f"case {case_index}/{len(cases)}: {case.case_id} ({case.complexity}) "
            f"repetition {repetition}/{args.repetitions}"
        )
        try:
            bundle = _run_case(
                case=case,
                config=config,
                args=args,
                existing_session_id=None,
                artifact_output_dir=suite_dir,
                cases_path=cases_path,
                provisioned_fixtures=provisioned_fixtures,
            )
            bundle["case_identity"] = _case_identity(case)
            bundle["case_contract"] = _case_contract_payload(case)
            bundle["case_contract_sha256"] = _case_contract_sha256(case)
            bundle["artifact_schema_version"] = release_gate.artifact_schema_version
            bundle["repetition"] = repetition
            if case.required:
                provenance = bundle.get("live_execution_provenance")
                quality_report = bundle.get("quality_report")
                checks = (
                    quality_report.get("checks")
                    if isinstance(quality_report, Mapping)
                    else None
                )
                if not isinstance(provenance, Mapping) or not isinstance(checks, list):
                    raise ValueError(
                        f"required case {case.case_id} has no evaluable evidence."
                    )
                bundle["release_identity_checks"] = _required_case_identity_checks(
                    case=case,
                    release_identity=release_identity,
                    provenance=provenance,
                    observation_input_identity=(
                        bundle.get("observation_input_identity")
                        if isinstance(bundle.get("observation_input_identity"), Mapping)
                        else None
                    ),
                )
                bundle["release_identity"] = release_identity
            bundle_path = _write_bundle(
                suite_dir,
                bundle,
                suffix=f"{case.case_id}{repetition_suffix}",
            )
            result = _suite_result(bundle, bundle_path)
            _print_observation(label=label, result=result, bundle_path=bundle_path)
            return result
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            failure = {
                "artifact_schema_version": release_gate.artifact_schema_version,
                "artifact_mode": "live_execution_failure",
                "created_at": time.strftime("%Y%m%dT%H%M%S"),
                "app_version": LOCAL_APP_VERSION,
                "case_identity": _case_identity(case),
                "case_contract": _case_contract_payload(case),
                "case_contract_sha256": _case_contract_sha256(case),
                "repetition": repetition,
                **_failure_error_fields(error),
                "release_identity": release_identity,
            }
            failure_path = _write_bundle(
                suite_dir,
                failure,
                suffix=f"{case.case_id}{repetition_suffix}-failure",
            )
            print(f"\n=== {label} ===\ncase failed: {error}", file=sys.stderr)
            print(f"failure bundle: {failure_path}", file=sys.stderr)
            return _suite_result(failure, failure_path)

    print(f"\nrunning {total_runs} observation(s) with concurrency {max_concurrency}")
    if max_concurrency == 1:
        results = [run_observation(item) for item in observations]
    else:
        # Cases are independent sessions and provider-latency bound: the
        # median observation spent 21 of its 23 seconds waiting. Order is
        # restored from the submitted order so the receipt does not depend on
        # which observation happened to finish first.
        with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
            results = list(executor.map(run_observation, observations))

    case_error_count = sum(
        1
        for result in results
        if result.get("observation_status") == "execution_failure"
    )
    required_case_error_count = sum(
        1
        for result in results
        if result.get("observation_status") == "execution_failure"
        and result.get("required") is True
    )
    evidence_failure_run_count = sum(
        1 for result in results if result.get("evidence_valid") is False
    )
    required_evidence_failure_run_count = sum(
        1
        for result in results
        if result.get("evidence_valid") is False and result.get("required") is True
    )
    quality_failure_run_count = sum(
        1
        for result in results
        if (_int_value(result.get("failed_expectation_check_count")) or 0) > 0
    )
    required_quality_failure_run_count = sum(
        1
        for result in results
        if (_int_value(result.get("failed_expectation_check_count")) or 0) > 0
        and result.get("required") is True
    )

    try:
        release_identity_recheck = _release_run_identity(
            cases=cases,
            cases_path=cases_path,
            requested_model_id=requested_model_id,
            require_clean_source=release_gate.require_clean_source,
            config=config if is_release_run else None,
        )
        release_identity_recheck_checks = _release_identity_recheck_checks(
            expected=release_identity,
            actual=release_identity_recheck,
            require_verified_target=is_release_run,
        )
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        subprocess.CalledProcessError,
        ValueError,
    ) as error:
        release_identity_recheck = {"error": str(error)}
        release_identity_recheck_checks = [
            {
                "name": f"suite_{component}_identity_unchanged",
                "passed": False,
                "actual": str(error),
                "expected": release_identity.get(component),
            }
            for component in ("source", "build", "model", "prompts", "target")
        ]
    suite_identity_failure_count = sum(
        1
        for check in release_identity_recheck_checks
        if check.get("passed") is not True
    )
    observation_identity_failure_count = sum(
        _int_value(result.get("identity_failed_check_count")) or 0 for result in results
    )
    identity_failure_count = (
        suite_identity_failure_count + observation_identity_failure_count
    )
    threshold_checks = _evaluate_release_thresholds(
        release_gate.thresholds,
        required_case_error_count=required_case_error_count,
        required_quality_failure_run_count=required_quality_failure_run_count,
    )
    receipt_integrity = _suite_receipt_integrity(
        expected_observations=expected_observations,
        results=results,
        suite_dir=suite_dir,
    )
    receipt_complete = receipt_integrity["status"] == "complete"
    sentinel_checks_pass = (
        identity_failure_count == 0
        and required_evidence_failure_run_count == 0
        and all(check["passed"] is True for check in threshold_checks)
    )
    sentinel_verdict = (
        ("pass" if sentinel_checks_pass else "fail")
        if receipt_complete and is_release_run
        else None
    )
    sentinel_gate_scope = {
        "case_count": len(release_gate.required_case_ids),
        "selected_case_count": len(cases),
        "observation_count": len(release_gate.required_case_ids) * args.repetitions,
        "selected_observation_count": total_runs,
        "case_ids": list(release_gate.required_case_ids),
    }
    suite_summary: JsonObject = {
        "artifact_schema_version": release_gate.artifact_schema_version,
        "artifact_mode": (
            "live_execution_partial_summary"
            if not receipt_complete
            else (
                "live_execution_summary"
                if is_release_run
                else "live_execution_exploratory_summary"
            )
        ),
        "created_at": started_at,
        "app_version": LOCAL_APP_VERSION,
        "base_url": config.base_url,
        "space_id": args.space_id,
        "case_count": len(cases),
        "repetitions": args.repetitions,
        "run_count": total_runs,
        "sentinel_verdict": sentinel_verdict,
        "sentinel_gate_scope": sentinel_gate_scope,
        "receipt_integrity": receipt_integrity,
        "execution_failure_observation_count": case_error_count,
        "invalid_evidence_observation_count": evidence_failure_run_count,
        "expectation_failed_observation_count": quality_failure_run_count,
        "required_execution_failure_observation_count": required_case_error_count,
        "required_invalid_evidence_observation_count": (
            required_evidence_failure_run_count
        ),
        "required_expectation_failed_observation_count": (
            required_quality_failure_run_count
        ),
        "identity_failed_check_count": identity_failure_count,
        "observation_identity_failed_check_count": (observation_identity_failure_count),
        "suite_identity_failed_check_count": suite_identity_failure_count,
        "sentinel_threshold_checks": threshold_checks,
        "release_identity": release_identity,
        "release_identity_recheck": release_identity_recheck,
        "release_identity_recheck_checks": release_identity_recheck_checks,
        "evaluator_identity": evaluator_identity,
        "run_context": run_context,
        "results": results,
        "observation_summary": _suite_observation_summary(results),
        "outcome_class_summary": _suite_outcome_summary(results),
        "reliability": _suite_reliability_summary(results),
    }
    summary_path = suite_dir / "suite-summary.json"
    _write_json_exclusive(summary_path, suite_summary)
    print(f"\nsuite summary: {summary_path}")
    return 1 if not receipt_complete or not sentinel_checks_pass else 0


def _release_run_identity(
    *,
    cases: list[BattleCase],
    cases_path: Path,
    requested_model_id: str | None,
    require_clean_source: bool,
    config: ApiConfig | None = None,
) -> JsonObject:
    tracked_status = _git_output("status", "--porcelain", "--untracked-files=no")
    if require_clean_source and tracked_status:
        raise ValueError(
            "Live release execution requires a clean tracked source revision."
        )
    source_revision = _git_output("rev-parse", "HEAD")
    stable_build = {
        "source_revision": source_revision,
        "harness_sha256": _release_input_sha256(
            Path(__file__),
            label="battle harness",
        ),
        "cases_sha256": _release_input_sha256(
            cases_path,
            label="battle cases",
        ),
    }
    build = {
        "app_version": LOCAL_APP_VERSION,
        **stable_build,
    }
    prompt_hashes = {
        case.case_id: hashlib.sha256(case.prompt.encode("utf-8")).hexdigest()
        for case in cases
    }
    model = {"requested_id": requested_model_id}
    identity = {
        "source": {
            "revision": source_revision,
            "revision_sha256": hashlib.sha256(
                source_revision.encode("utf-8")
            ).hexdigest(),
            "tracked_clean": not tracked_status,
        },
        "build": {**build, "sha256": _canonical_sha256(stable_build)},
        "model": {**model, "sha256": _canonical_sha256(model)},
        "prompts": {
            "case_sha256_by_id": prompt_hashes,
            "sha256": _canonical_sha256(prompt_hashes),
        },
    }
    if config is not None:
        target = _target_runtime_identity(
            config,
            expected_source_revision=source_revision,
        )
        if target.get("verified") is not True:
            raise ValueError(
                "Release target /version does not match the local source revision."
            )
        identity["target"] = target
    return identity


def _target_runtime_identity(
    config: ApiConfig,
    *,
    expected_source_revision: str,
) -> JsonObject:
    if len(expected_source_revision) < 12:
        raise ValueError(
            "Expected source revision must contain at least 12 characters."
        )
    expected_app_version = f"DEV-{expected_source_revision[:12]}"
    parsed_base = urlsplit(config.base_url.rstrip("/"))
    if not parsed_base.path.endswith("/api/v1"):
        raise ValueError(
            "--base-url must end in /api/v1 so the backend /version endpoint "
            "can be verified."
        )
    root_path = parsed_base.path[: -len("/api/v1")]
    version_url = urlunsplit(
        (parsed_base.scheme, parsed_base.netloc, f"{root_path}/version", "", "")
    )
    request = Request(
        version_url,
        headers={"Accept": "application/json", "X-API-Key": config.api_key},
        method="GET",
    )
    with urlopen(request, timeout=config.timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    version = payload.get("version") if isinstance(payload, Mapping) else None
    version = version.strip() if isinstance(version, str) else None
    comparable = {
        "api_base_url": config.base_url,
        "version": version,
        "expected_app_version": expected_app_version,
        "expected_source_revision": expected_source_revision,
        "source_revision_verification": "git_commit_prefix_via_app_version",
    }
    verified = bool(version) and version == expected_app_version
    return {
        **comparable,
        "verified": verified,
        "sha256": _canonical_sha256(comparable),
    }


def _release_input_sha256(path: Path, *, label: str) -> str:
    repository_root = Path(__file__).resolve().parents[2]
    resolved_path = path.resolve()
    try:
        repository_path = resolved_path.relative_to(repository_root)
    except ValueError as error:
        raise ValueError(f"{label} must be a tracked repository input.") from error
    try:
        _git_output(
            "ls-files",
            "--error-unmatch",
            "--",
            repository_path.as_posix(),
        )
    except subprocess.CalledProcessError as error:
        raise ValueError(f"{label} must be a tracked repository input.") from error
    return hashlib.sha256(resolved_path.read_bytes()).hexdigest()


def _required_case_identity_checks(
    *,
    case: BattleCase,
    release_identity: Mapping[str, object],
    provenance: Mapping[str, object],
    observation_input_identity: Mapping[str, object] | None = None,
) -> list[JsonObject]:
    release_source = release_identity.get("source")
    release_source = release_source if isinstance(release_source, Mapping) else {}
    live_source = provenance.get("source")
    live_source = live_source if isinstance(live_source, Mapping) else {}
    release_revision = release_source.get("revision")
    live_revision = live_source.get("revision")
    source_identity_matches = (
        isinstance(release_revision, str)
        and release_revision == live_revision
        and release_source.get("revision_sha256")
        == hashlib.sha256(release_revision.encode("utf-8")).hexdigest()
        and live_source.get("revision_sha256")
        == hashlib.sha256(release_revision.encode("utf-8")).hexdigest()
    )

    release_build = release_identity.get("build")
    release_build = release_build if isinstance(release_build, Mapping) else {}
    live_build = provenance.get("build")
    live_build = live_build if isinstance(live_build, Mapping) else {}
    stable_build_keys = (
        "source_revision",
        "harness_sha256",
        "cases_sha256",
    )
    release_build_payload = {key: release_build.get(key) for key in stable_build_keys}
    live_build_payload = {key: live_build.get(key) for key in stable_build_keys}
    build_identity_matches = (
        release_build_payload == live_build_payload
        and release_build.get("sha256") == _canonical_sha256(release_build_payload)
        and live_build.get("sha256") == _canonical_sha256(live_build_payload)
    )

    release_model = release_identity.get("model")
    release_model = release_model if isinstance(release_model, Mapping) else {}
    live_model = provenance.get("model")
    live_model = live_model if isinstance(live_model, Mapping) else {}
    release_model_payload = {"requested_id": release_model.get("requested_id")}
    requested_model_id = release_model.get("requested_id")
    model_identity_matches = (
        isinstance(requested_model_id, str)
        and bool(requested_model_id)
        and release_model.get("sha256") == _canonical_sha256(release_model_payload)
        and requested_model_id == live_model.get("requested_id")
        and requested_model_id == live_model.get("resolved_id")
        and live_model.get("observed_matches_resolved") is True
    )

    release_prompts = release_identity.get("prompts")
    release_prompts = release_prompts if isinstance(release_prompts, Mapping) else {}
    release_prompt_hashes = release_prompts.get("case_sha256_by_id")
    release_prompt_hashes = (
        release_prompt_hashes if isinstance(release_prompt_hashes, Mapping) else {}
    )
    live_prompt = provenance.get("prompt")
    live_prompt = live_prompt if isinstance(live_prompt, Mapping) else {}
    case_prompt_sha256 = hashlib.sha256(case.prompt.encode("utf-8")).hexdigest()
    prompt_identity_matches = (
        release_prompts.get("sha256") == _canonical_sha256(dict(release_prompt_hashes))
        and release_prompt_hashes.get(case.case_id) == case_prompt_sha256
        and live_prompt.get("case_sha256") == case_prompt_sha256
    )

    checks = [
        {
            "name": "suite_source_revision_identity",
            "passed": source_identity_matches,
            "actual": live_source,
            "expected": release_source,
        },
        {
            "name": "suite_build_input_identity",
            "passed": build_identity_matches,
            "actual": live_build_payload,
            "expected": release_build_payload,
        },
        {
            "name": "suite_requested_model_identity",
            "passed": model_identity_matches,
            "actual": dict(live_model),
            "expected": requested_model_id,
        },
        {
            "name": "suite_case_prompt_identity",
            "passed": prompt_identity_matches,
            "actual": live_prompt.get("case_sha256"),
            "expected": release_prompt_hashes.get(case.case_id),
        },
    ]
    observation_input_identity = observation_input_identity or {}
    checks.append(
        {
            "name": "suite_observation_input_identity",
            "passed": observation_input_identity.get("verified") is True
            and _is_sha256(observation_input_identity.get("sha256")),
            "actual": dict(observation_input_identity),
            "expected": (
                "declared attachment evidence-text and runtime file checksums "
                "match observed evidence"
            ),
        }
    )
    return checks


def _release_identity_recheck_checks(
    *,
    expected: Mapping[str, object],
    actual: Mapping[str, object],
    require_verified_target: bool = False,
) -> list[JsonObject]:
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
        target = actual.get("target")
        target = target if isinstance(target, Mapping) else {}
        checks.append(
            {
                "name": "suite_target_runtime_verified",
                "passed": target.get("verified") is True,
                "actual": dict(target),
                "expected": "running backend version matches the local benchmark build",
            }
        )
    return checks


def _evaluate_release_thresholds(
    thresholds: ReleaseThresholds,
    *,
    required_case_error_count: int,
    required_quality_failure_run_count: int,
) -> list[JsonObject]:
    return [
        {
            "name": "max_required_case_errors",
            "passed": (
                required_case_error_count <= thresholds.max_required_case_errors
            ),
            "actual": required_case_error_count,
            "threshold": thresholds.max_required_case_errors,
        },
        {
            "name": "max_required_quality_failures",
            "passed": required_quality_failure_run_count
            <= thresholds.max_required_quality_failures,
            "actual": required_quality_failure_run_count,
            "threshold": thresholds.max_required_quality_failures,
        },
    ]


def _run_case(
    *,
    case: BattleCase,
    config: ApiConfig,
    args: argparse.Namespace,
    existing_session_id: str | None,
    artifact_output_dir: Path,
    cases_path: Path | None = DEFAULT_CASES_FILE,
    provisioned_fixtures: Mapping[str, object] | None = None,
) -> JsonObject:
    started_at = time.strftime("%Y%m%dT%H%M%S")
    if existing_session_id:
        session_id = existing_session_id
        initial_session = _request_json(
            config=config,
            method="GET",
            path=f"/flows/ai-builder/sessions/{session_id}",
        )
        print(f"resumed session {session_id}")
    else:
        initial_session = _create_session(
            config=config,
            space_id=args.space_id,
            force_new=args.force_new,
        )
        session_id = _required_string(initial_session, "session_id")
        print(f"created session {session_id}")

    session_models = _request_json(
        config=config,
        method="GET",
        path=f"/flows/ai-builder/sessions/{session_id}/models",
    )

    file_ids = tuple(getattr(args, "file_ids", None) or ()) or _case_file_ids(
        case, provisioned_fixtures or {}
    )
    runtime_file_paths = _case_runtime_file_paths(case)
    interactions: list[JsonObject] = []
    first = _send_and_fetch(
        config=config,
        session_id=session_id,
        message=case.prompt,
        model_id=args.model_id,
        file_ids=file_ids,
        ui_language=args.ui_language,
        question_answer=None,
    )
    interactions.append(first)

    confirmed_requirement_versions: set[str] = set()
    while (
        interactions[-1].get("plan_id") is None
        and len(interactions) < MAX_INTERACTIONS_PER_CASE
    ):
        current = interactions[-1]
        if (
            args.auto_confirm_requirements
            and (requirements_summary := _latest_requirements_summary(current))
            is not None
        ):
            version = str(requirements_summary.get("requirements_version") or "")
            if version and version not in confirmed_requirement_versions:
                confirmed_requirement_versions.add(version)
                interactions.append(
                    _send_and_fetch(
                        config=config,
                        session_id=session_id,
                        message=args.confirm_message,
                        model_id=args.model_id,
                        file_ids=(),
                        ui_language=args.ui_language,
                        question_answer=_requirements_confirmation_payload(
                            requirements_summary=requirements_summary,
                            ui_language=args.ui_language,
                        ),
                    )
                )
                continue

        if (question := _latest_structured_question(current)) is not None:
            answer = _configured_question_answer(
                question=question,
                configured_answers=case.configured_question_answers or {},
                answer_sources=case.question_answer_sources or {},
            )
            if answer is not None:
                response = _send_and_fetch(
                    config=config,
                    session_id=session_id,
                    message=answer["message"],
                    model_id=args.model_id,
                    file_ids=(),
                    ui_language=args.ui_language,
                    question_answer=answer["question_answer"],
                )
                response["configured_answer_source"] = answer["answer_source"]
                interactions.append(response)
                continue
        break

    final_interaction = interactions[-1]
    plan = final_interaction.get("plan")
    plan = plan if isinstance(plan, dict) else None
    plan_summary = _summarize_plan(plan)
    applied_flow_evidence = None
    plan_id = _optional_string(final_interaction, "plan_id")
    if case.apply_plan and plan_id is not None:
        applied_flow_evidence = _apply_and_fetch_flow(
            config=config,
            plan_id=plan_id,
        )
    runtime_evidence = None
    if case.execute_flow:
        if not isinstance(applied_flow_evidence, Mapping):
            raise ValueError(f"case {case.case_id} requires an applied flow.")
        apply_result = applied_flow_evidence.get("apply_result")
        if not isinstance(apply_result, Mapping):
            raise ValueError(f"case {case.case_id} has no apply result.")
        runtime_evidence = _execute_and_collect_runtime_evidence(
            config=config,
            flow_id=_required_string(apply_result, "flow_id"),
            runtime_file_paths=runtime_file_paths,
            timeout_seconds=args.timeout_seconds,
            artifact_output_dir=artifact_output_dir,
            case_id=case.case_id,
        )
    event_summary = _interaction_event_summary(interactions)
    journey = _journey_summary(
        interactions,
        expected=case.expected or {},
        interaction_limit=MAX_INTERACTIONS_PER_CASE,
    )
    failure_summary = _failure_summary(event_summary)
    classifier_diagnostics = _request_json(
        config=config,
        method="GET",
        path=(f"/flows/ai-builder/sessions/{session_id}/_diagnostics/classifier-slots"),
    )
    proposal_telemetry_diagnostics = _optional_request_json(
        config=config,
        path=(
            f"/flows/ai-builder/sessions/{session_id}/_diagnostics/proposal-telemetry"
        ),
    )
    journey = _journey_with_proposal_economics(
        journey,
        diagnostics=proposal_telemetry_diagnostics,
    )
    observation_input_identity = _observation_input_identity(
        case=case,
        attached_file_ids=file_ids,
        classifier_diagnostics=classifier_diagnostics,
        runtime_evidence=runtime_evidence,
    )
    quality_report = _quality_report(
        plan=plan,
        summary=plan_summary,
        expected=case.expected or {},
        event_summary=event_summary,
        journey=journey,
        classifier_diagnostics=classifier_diagnostics,
        attached_file_ids=file_ids,
        applied_flow=(
            applied_flow_evidence.get("flow")
            if isinstance(applied_flow_evidence, Mapping)
            and isinstance(applied_flow_evidence.get("flow"), Mapping)
            else None
        ),
        runtime_evidence=runtime_evidence,
    )
    live_execution_provenance = _live_execution_provenance(
        case=case,
        cases_path=cases_path,
        latest_session=(
            final_interaction.get("latest_session")
            if isinstance(final_interaction.get("latest_session"), Mapping)
            else None
        ),
        classifier_diagnostics=classifier_diagnostics,
        requested_model_id=args.model_id,
        session_models=session_models,
        event_summary=event_summary,
        interactions=interactions,
    )
    quality_report = _quality_report_with_live_provenance(
        quality_report,
        provenance=live_execution_provenance,
        expected=case.expected or {},
    )

    return {
        "artifact_mode": "live_execution",
        "case_identity": _case_identity(case),
        "live_execution_provenance": live_execution_provenance,
        "observation_input_identity": observation_input_identity,
        "created_at": started_at,
        "app_version": LOCAL_APP_VERSION,
        "base_url": config.base_url,
        "space_id": args.space_id,
        "case": {
            "id": case.case_id,
            "complexity": case.complexity,
            "domain": case.domain,
            "required": case.required,
            "apply_plan": case.apply_plan,
            "execute_flow": case.execute_flow,
            "release_dimensions": list(case.release_dimensions),
            "prompt": case.prompt,
            "expected": case.expected or {},
            "file_ids": list(file_ids),
            "direct_file_slot_count": len(case.file_ids),
            "attachments": _fixture_contract(case.attachments),
            "runtime_files": _fixture_contract(case.runtime_files),
            "synthetic_user_profile": case.synthetic_user_profile,
            "cohorts": list(case.cohorts),
            "configured_question_answers": case.configured_question_answers or {},
            "question_answer_sources": case.question_answer_sources or {},
        },
        "session_id": session_id,
        "plan_id": final_interaction.get("plan_id"),
        "initial_session": initial_session,
        "interactions": interactions,
        "latest_session": final_interaction.get("latest_session"),
        "plan": plan,
        "plan_summary": plan_summary,
        "event_summary": event_summary,
        "journey": journey,
        "failure_summary": failure_summary,
        "classifier_diagnostics": classifier_diagnostics,
        "proposal_telemetry_diagnostics": proposal_telemetry_diagnostics,
        "applied_flow_evidence": applied_flow_evidence,
        "runtime_evidence": runtime_evidence,
        "runtime_metrics": _runtime_metrics_from_quality_report(quality_report),
        "quality_report": quality_report,
    }


def _apply_and_fetch_flow(*, config: ApiConfig, plan_id: str) -> JsonObject:
    apply_result = _request_json(
        config=config,
        method="POST",
        path=f"/flows/ai-builder/plans/{plan_id}/create",
    )
    flow_id = _required_string(apply_result, "flow_id")
    flow = _request_json(
        config=config,
        method="GET",
        path=f"/flows/{flow_id}/",
    )
    return {
        "apply_result": apply_result,
        "flow": flow,
        "evidence_scope": (
            "compiled_proposal_and_applied_draft_only; "
            "does_not_prove_runtime_checkpoint_pause_or_resume"
        ),
    }


def _execute_and_collect_runtime_evidence(
    *,
    config: ApiConfig,
    flow_id: str,
    runtime_file_paths: tuple[Path, ...],
    timeout_seconds: int,
    artifact_output_dir: Path,
    case_id: str,
) -> JsonObject:
    published_flow = _request_json(
        config=config,
        method="POST",
        path=f"/flows/{flow_id}/publish/",
    )
    contract = _request_json(
        config=config,
        method="GET",
        path=f"/flows/{flow_id}/run-contract/",
    )
    input_steps = contract.get("steps_requiring_input")
    if not isinstance(input_steps, list) or len(input_steps) != 1:
        raise ValueError(
            f"case {case_id} requires exactly one runtime file-input step."
        )
    input_step = input_steps[0]
    if not isinstance(input_step, Mapping):
        raise ValueError(f"case {case_id} runtime input contract is malformed.")
    step_id = _required_string(input_step, "step_id")
    uploaded_files = [
        _upload_runtime_file(
            config=config,
            flow_id=flow_id,
            step_id=step_id,
            source_path=source_path,
        )
        for source_path in runtime_file_paths
    ]
    uploaded_file_ids = [
        _required_string(uploaded_file, "id") for uploaded_file in uploaded_files
    ]
    published_version = _int_value(contract.get("published_flow_version"))
    if published_version is None:
        raise ValueError(f"case {case_id} run contract has no published version.")
    created_run = _request_json(
        config=config,
        method="POST",
        path=f"/flows/{flow_id}/runs/",
        payload={
            "expected_flow_version": published_version,
            "input_payload_json": None,
            "step_inputs": {step_id: {"file_ids": uploaded_file_ids}},
        },
    )
    run_id = _required_string(created_run, "id")
    deadline = time.monotonic() + timeout_seconds
    while True:
        run = _request_json(
            config=config,
            method="GET",
            path=f"/flows/{flow_id}/runs/{run_id}/",
        )
        status = _optional_string(run, "status")
        if status in {"completed", "failed", "cancelled"}:
            break
        if status == "awaiting_review":
            raise ValueError(
                f"case {case_id} unexpectedly reached a runtime review checkpoint."
            )
        if time.monotonic() >= deadline:
            raise TimeoutError(f"case {case_id} runtime execution timed out.")
        time.sleep(1)
    evidence = _request_json(
        config=config,
        method="GET",
        path=f"/flows/{flow_id}/runs/{run_id}/evidence/",
    )
    evidence["run"] = run
    evidence["final_artifact"] = _download_final_artifact(
        config=config,
        flow_id=flow_id,
        run_id=run_id,
        run=run,
        output_dir=artifact_output_dir,
        case_id=case_id,
    )
    evidence["published_flow"] = published_flow
    evidence["run_contract"] = contract
    evidence["uploaded_files"] = uploaded_files
    return evidence


def _upload_file(*, config: ApiConfig, source_path: Path) -> JsonObject:
    """Upload a fixture into the space and return its file record."""

    return _post_multipart_file(config=config, path="/files/", source_path=source_path)


def _upload_runtime_file(
    *,
    config: ApiConfig,
    flow_id: str,
    step_id: str,
    source_path: Path,
) -> JsonObject:
    return _post_multipart_file(
        config=config,
        path=f"/flows/{flow_id}/steps/{step_id}/runtime-files/",
        source_path=source_path,
    )


def _post_multipart_file(
    *,
    config: ApiConfig,
    path: str,
    source_path: Path,
) -> JsonObject:
    content = source_path.read_bytes()
    boundary = (
        "eneo-battle-"
        + hashlib.sha256(
            f"{source_path.name}:{len(content)}:{time.time_ns()}".encode("utf-8")
        ).hexdigest()[:32]
    )
    content_type = (
        mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
    )
    safe_name = source_path.name.replace('"', "_")
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="upload_file"; filename="{safe_name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    body = prefix + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    request = Request(
        f"{config.base_url}{path}",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-API-Key": config.api_key,
        },
        method="POST",
    )
    with urlopen(request, timeout=config.timeout_seconds) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"Upload of {source_path.name} returned no object.")
    return parsed


def _download_final_artifact(
    *,
    config: ApiConfig,
    flow_id: str,
    run_id: str,
    run: Mapping[str, object],
    output_dir: Path,
    case_id: str,
) -> JsonObject | None:
    result = run.get("result")
    if not isinstance(result, Mapping) or result.get("kind") != "artifact":
        return None
    files = result.get("files")
    if (
        not isinstance(files, list)
        or len(files) != 1
        or not isinstance(files[0], Mapping)
    ):
        raise ValueError(f"case {case_id} expected exactly one final artifact.")
    artifact = files[0]
    file_id = _required_string(artifact, "file_id")
    signed_url = _request_json(
        config=config,
        method="POST",
        path=f"/flows/{flow_id}/runs/{run_id}/artifacts/{file_id}/signed-url/",
        payload={"expires_in": 3600, "content_disposition": "attachment"},
    )
    url = _required_string(signed_url, "url")
    with urlopen(url, timeout=config.timeout_seconds) as response:
        content = response.read()
    name = _optional_string(artifact, "name") or f"{file_id}.pdf"
    suffix = Path(name).suffix.casefold()
    if suffix != ".pdf":
        raise ValueError(f"case {case_id} expected a PDF final artifact, got {name}.")
    safe_case_id = "".join(
        char if char.isalnum() or char in "-_" else "-" for char in case_id
    )
    safe_run_id = "".join(
        char if char.isalnum() or char in "-_" else "-" for char in run_id
    )
    artifact_path = output_dir / f"{safe_case_id}-{safe_run_id}-final-artifact.pdf"
    _write_bytes_exclusive(artifact_path, content)
    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    return {
        "file_id": file_id,
        "name": name,
        "path": str(artifact_path),
        "byte_count": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "text": text,
    }


def _send_and_fetch(
    *,
    config: ApiConfig,
    session_id: str,
    message: str,
    model_id: str | None,
    file_ids: tuple[str, ...],
    ui_language: str,
    question_answer: JsonObject | None,
) -> JsonObject:
    client_turn_id = str(uuid4())
    payload: JsonObject = {
        "client_turn_id": client_turn_id,
        "message": message,
        "model_id": model_id,
        "file_ids": list(file_ids) or None,
        "question_answer": question_answer,
        "ui_language": ui_language,
    }
    try:
        events = list(
            _send_message_stream(
                config=config,
                session_id=session_id,
                payload=payload,
            )
        )
        print(f"received {len(events)} stream events")

        latest_session = _request_json(
            config=config,
            method="GET",
            path=f"/flows/ai-builder/sessions/{session_id}",
        )
        plan_id = _last_plan_id(events) or _optional_string(
            latest_session,
            "latest_plan_id",
        )
        plan = (
            _request_json(
                config=config,
                method="GET",
                path=f"/flows/ai-builder/plans/{plan_id}",
            )
            if plan_id
            else None
        )
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        raise BattleTurnError(
            client_turn_id=client_turn_id,
            cause=error,
        ) from error
    return {
        "client_turn_id": client_turn_id,
        "message": message,
        "question_answer": question_answer,
        "events": events,
        "latest_session": latest_session,
        "plan_id": plan_id,
        "plan": plan,
        "plan_summary": _summarize_plan(plan),
    }


def _latest_requirements_summary(interaction: Mapping[str, Any]) -> JsonObject | None:
    events = interaction.get("events")
    if isinstance(events, list):
        for event in reversed(events):
            if (
                not isinstance(event, Mapping)
                or event.get("event") != "requirements_summary"
            ):
                continue
            data = event.get("data")
            if isinstance(data, Mapping):
                return dict(data)

    latest_session = interaction.get("latest_session")
    if not isinstance(latest_session, Mapping):
        return None
    conversation = latest_session.get("conversation")
    if not isinstance(conversation, list):
        return None
    for message in reversed(conversation):
        if not isinstance(message, Mapping):
            continue
        metadata = message.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        summary = metadata.get("requirements_summary")
        if isinstance(summary, Mapping):
            return dict(summary)
    return None


def _latest_structured_question(interaction: Mapping[str, Any]) -> JsonObject | None:
    events = interaction.get("events")
    if not isinstance(events, list):
        return None
    for event in reversed(events):
        if not isinstance(event, Mapping) or event.get("event") != "question":
            continue
        data = event.get("data")
        if isinstance(data, Mapping):
            return dict(data)
    return None


def _configured_question_answer(
    *,
    question: Mapping[str, Any],
    configured_answers: Mapping[str, Any],
    answer_sources: Mapping[str, Any],
) -> JsonObject | None:
    question_id = _optional_string(question, "question_id")
    if question_id is None or question_id not in configured_answers:
        return None
    answer_config = configured_answers[question_id]
    if not isinstance(answer_config, Mapping):
        raise ValueError(f"Configured answer for {question_id} must be an object.")
    answer_source = answer_sources.get(question_id)
    if answer_source not in {"profile", "case_override"}:
        raise ValueError(f"Configured answer for {question_id} has no valid source.")

    custom_value = answer_config.get("custom_value")
    if isinstance(custom_value, str) and custom_value.strip():
        if question.get("allow_custom") is not True:
            raise ValueError(f"Question {question_id} does not allow a custom answer.")
        custom_text = custom_value.strip()
        return {
            "message": custom_text,
            "answer_source": answer_source,
            "question_answer": {
                "kind": "structured_question_answer",
                "question_id": question_id,
                "custom_value": custom_text,
            },
        }

    selected_ids = _configured_selected_option_ids(answer_config)
    if not selected_ids:
        return None
    options = _question_options_by_key(question)
    missing = [option_id for option_id in selected_ids if option_id not in options]
    if missing:
        raise ValueError(
            f"Configured answer for {question_id} references unknown option(s): "
            + ", ".join(missing)
        )
    selected_options = [options[option_id] for option_id in selected_ids]
    selected_values = [
        option.get("value") if option.get("value") is not None else option.get("id")
        for option in selected_options
    ]
    message = ", ".join(
        str(option.get("label") or option.get("value") or option.get("id"))
        for option in selected_options
    )
    return {
        "message": message,
        "answer_source": answer_source,
        "question_answer": {
            "kind": "structured_question_answer",
            "question_id": question_id,
            "selected_option_ids": selected_ids,
            "selected_values": selected_values,
        },
    }


def _configured_selected_option_ids(answer_config: Mapping[str, Any]) -> list[str]:
    selected_option_ids = answer_config.get("selected_option_ids")
    if isinstance(selected_option_ids, list) and all(
        isinstance(item, str) for item in selected_option_ids
    ):
        return selected_option_ids
    selected_option_id = answer_config.get("selected_option_id")
    if isinstance(selected_option_id, str) and selected_option_id:
        return [selected_option_id]
    return []


def _question_options_by_key(
    question: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    raw_options = question.get("options")
    if not isinstance(raw_options, list):
        return {}
    options: dict[str, Mapping[str, Any]] = {}
    for raw_option in raw_options:
        if not isinstance(raw_option, Mapping):
            continue
        option_id = raw_option.get("id")
        if isinstance(option_id, str) and option_id:
            options[option_id] = raw_option
    return options


def _requirements_confirmation_payload(
    *,
    requirements_summary: Mapping[str, Any],
    ui_language: str,
) -> JsonObject:
    payload: JsonObject = {
        "kind": "requirements_confirmation",
        "requirements_confirmed": True,
        "ui_language": ui_language,
    }
    version = requirements_summary.get("requirements_version")
    if isinstance(version, str) and version:
        payload["requirements_version"] = version
    return payload


def _optional_request_json(*, config: ApiConfig, path: str) -> JsonObject | None:
    """Fetch a diagnostics endpoint that older backends may not serve yet."""

    try:
        return _request_json(config=config, method="GET", path=path)
    except HTTPError as error:
        if error.code in {404, 405}:
            return None
        raise


def _journey_with_proposal_economics(
    journey: JsonObject,
    *,
    diagnostics: JsonObject | None,
) -> JsonObject:
    """Attach per-attempt repair economics and the architecture snapshot.

    The receipt is the improvement engine between runs: knowing WHICH
    failure codes each repair burned tokens on turns outcome counts into
    ranked engineering targets.
    """

    if not isinstance(diagnostics, Mapping):
        return journey
    enriched = dict(journey)
    architecture = diagnostics.get("architecture")
    if isinstance(architecture, Mapping):
        enriched["architecture"] = dict(architecture)
    raw_turns = diagnostics.get("proposal_turns")
    turns = (
        [dict(turn) for turn in raw_turns if isinstance(turn, Mapping)]
        if (isinstance(raw_turns, list))
        else []
    )
    attempt_ladder: list[JsonObject] = []
    initial_token_cost = 0
    repair_token_cost = 0
    for turn in turns:
        attempts = turn.get("attempts")
        if not isinstance(attempts, list):
            continue
        for attempt in attempts:
            if not isinstance(attempt, Mapping):
                continue
            kind = attempt.get("kind")
            total_tokens = attempt.get("total_tokens")
            tokens = (
                total_tokens
                if isinstance(total_tokens, int) and not isinstance(total_tokens, bool)
                else 0
            )
            if kind == "repair":
                repair_token_cost += tokens
            else:
                initial_token_cost += tokens
            attempt_ladder.append(
                {
                    "message_id": turn.get("message_id"),
                    "attempt": attempt.get("attempt"),
                    "kind": kind,
                    "failure_kind": attempt.get("failure_kind"),
                    "failure_codes": _string_list(attempt.get("failure_codes")),
                    "total_tokens": total_tokens,
                }
            )
    plan_outcome = enriched.get("plan_outcome")
    plan_outcome = dict(plan_outcome) if isinstance(plan_outcome, Mapping) else {}
    plan_outcome["proposal_turns"] = turns
    plan_outcome["attempt_failure_ladder"] = attempt_ladder
    plan_outcome["initial_token_cost"] = initial_token_cost
    plan_outcome["repair_token_cost"] = repair_token_cost
    enriched["plan_outcome"] = plan_outcome
    return enriched


def _case_file_ids(
    case: BattleCase,
    provisioned_fixtures: Mapping[str, object],
) -> tuple[str, ...]:
    return (*case.file_ids, *_fixture_file_ids(case.attachments, provisioned_fixtures))


def _case_runtime_file_paths(case: BattleCase) -> tuple[Path, ...]:
    manifest = _fixture_manifest()
    return tuple(_verified_fixture_path(name, manifest) for name in case.runtime_files)


def _attachment_evidence_sha256s(
    *,
    attached_file_ids: tuple[str, ...],
    classifier_diagnostics: Mapping[str, object] | None,
) -> list[str | None]:
    source_sha256s_by_file_id: dict[str, set[str]] = {}
    for run in _classifier_runs(classifier_diagnostics):
        inventory = run.get("source_inventory")
        if not isinstance(inventory, list):
            continue
        for source in inventory:
            if not isinstance(source, Mapping) or source.get("kind") != "uploaded_file":
                continue
            file_id = _optional_string(source, "file_id")
            source_sha256 = _optional_string(source, "source_sha256")
            if file_id is not None and _is_sha256(source_sha256):
                source_sha256s_by_file_id.setdefault(file_id, set()).add(source_sha256)
    return [
        next(iter(source_sha256s_by_file_id.get(file_id, set())), None)
        if len(source_sha256s_by_file_id.get(file_id, set())) == 1
        else None
        for file_id in attached_file_ids
    ]


def _observation_input_identity(
    *,
    case: BattleCase,
    attached_file_ids: tuple[str, ...],
    classifier_diagnostics: Mapping[str, object] | None,
    runtime_evidence: Mapping[str, object] | None,
) -> JsonObject:
    # What the attached bytes were is settled offline, by the manifest hash the
    # harness verified before uploading. The extracted-text digest below is an
    # observation of what the server made of those bytes: recorded per run and
    # compared across runs by the comparator, never pinned to a constant some
    # operator captured by hand months ago.
    observed_attachment_evidence_sha256s = _attachment_evidence_sha256s(
        attached_file_ids=attached_file_ids,
        classifier_diagnostics=classifier_diagnostics,
    )
    attachment_evidence_complete = all(
        _is_sha256(value) for value in observed_attachment_evidence_sha256s
    )
    manifest = _fixture_manifest()
    declared_runtime_sha256s = [manifest[name] for name in case.runtime_files]
    runtime_sha256s, runtime_evidence_status = _runtime_lineage_sha256s(
        runtime_evidence,
        expected_count=len(declared_runtime_sha256s),
    )

    mismatches: list[str] = []
    if attached_file_ids and not attachment_evidence_complete:
        mismatches.append("attachment_evidence")
    if declared_runtime_sha256s and runtime_evidence_status != "complete":
        mismatches.append("runtime_evidence")
    if runtime_evidence_status == "complete" and runtime_sha256s != (
        declared_runtime_sha256s
    ):
        mismatches.append("runtime_content")

    fingerprint_payload = {
        "attachment_evidence_sha256s": observed_attachment_evidence_sha256s,
        "runtime_source_sha256s": runtime_sha256s,
    }
    fingerprint_complete = all(
        value is not None for value in observed_attachment_evidence_sha256s
    ) and all(_is_sha256(value) for value in runtime_sha256s)
    return {
        **fingerprint_payload,
        "attachment_fixtures": _fixture_contract(case.attachments),
        "declared_runtime_sha256s": declared_runtime_sha256s,
        "runtime_evidence_status": runtime_evidence_status,
        "verified": not mismatches and fingerprint_complete,
        "mismatches": mismatches,
        "sha256": (
            _canonical_sha256(fingerprint_payload) if fingerprint_complete else None
        ),
    }


def _runtime_lineage_sha256s(
    runtime_evidence: Mapping[str, object] | None,
    *,
    expected_count: int,
) -> tuple[list[str | None], str]:
    if expected_count == 0:
        return [], "not_required"
    if runtime_evidence is None:
        return [None] * expected_count, "missing"
    contract = runtime_evidence.get("run_contract")
    contract = contract if isinstance(contract, Mapping) else {}
    input_steps = _mapping_list(contract.get("steps_requiring_input"))
    if len(input_steps) != 1:
        return [None] * expected_count, "input_step_ambiguous"
    input_step_id = _optional_string(input_steps[0], "step_id")
    if input_step_id is None:
        return [None] * expected_count, "input_step_missing"

    uploaded_files = _mapping_list(runtime_evidence.get("uploaded_files"))
    uploaded_file_ids = [
        _optional_string(uploaded_file, "id") for uploaded_file in uploaded_files
    ]
    if (
        len(uploaded_file_ids) != expected_count
        or any(file_id is None for file_id in uploaded_file_ids)
        or len(set(uploaded_file_ids)) != expected_count
    ):
        return [None] * expected_count, "uploaded_files_invalid"

    current_step_results = [
        result
        for result in _mapping_list(runtime_evidence.get("step_results"))
        if result.get("step_id") == input_step_id
    ]
    if len(current_step_results) != 1:
        return [None] * expected_count, "current_step_ambiguous"
    current_step = current_step_results[0]
    current_attempt_no = current_step.get("current_attempt_no")
    if (
        not isinstance(current_attempt_no, int)
        or isinstance(current_attempt_no, bool)
        or current_attempt_no < 1
        or current_step.get("status") != "completed"
        or _string_list(current_step.get("runtime_input_file_ids")) != uploaded_file_ids
    ):
        return [None] * expected_count, "current_step_invalid"

    current_attempts = [
        attempt
        for attempt in _mapping_list(runtime_evidence.get("step_attempts"))
        if attempt.get("step_id") == input_step_id
        and attempt.get("attempt_no") == current_attempt_no
    ]
    if len(current_attempts) != 1:
        return [None] * expected_count, "current_attempt_ambiguous"
    current_attempt = current_attempts[0]
    if (
        current_attempt.get("status") != "completed"
        or current_attempt.get("superseded_by_attempt_id") is not None
    ):
        return [None] * expected_count, "current_attempt_invalid"
    lineage = current_attempt.get("resolved_input_lineage")
    if not isinstance(lineage, Mapping):
        return [None] * expected_count, "current_lineage_missing"
    lineage_status = lineage.get("status")
    if lineage_status != "tracked":
        return [None] * expected_count, str(lineage_status or "invalid")
    edges = lineage.get("edges")
    if not isinstance(edges, list):
        return [None] * expected_count, "current_lineage_invalid"

    checksum_by_ordinal: dict[int, str] = {}
    for edge in edges:
        if not isinstance(edge, Mapping):
            return [None] * expected_count, "current_lineage_invalid"
        source = edge.get("source")
        if not isinstance(source, Mapping) or source.get("kind") != "runtime_file":
            continue
        ordinal = source.get("input_file_ordinal")
        checksum = source.get("checksum")
        if (
            not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or ordinal not in range(expected_count)
            or source.get("file_id") != uploaded_file_ids[ordinal]
            or not _is_sha256(checksum)
            or ordinal in checksum_by_ordinal
        ):
            return [None] * expected_count, "current_lineage_invalid"
        checksum_by_ordinal[ordinal] = checksum

    expected_ordinals = set(range(expected_count))
    if set(checksum_by_ordinal) != expected_ordinals:
        return [None] * expected_count, "incomplete"
    return [checksum_by_ordinal[index] for index in range(expected_count)], "complete"


def _write_bundle(output_dir: Path, bundle: JsonObject, *, suffix: str) -> Path:
    created_at = str(bundle.get("created_at") or time.strftime("%Y%m%dT%H%M%S"))
    safe_suffix = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in suffix)
    path = output_dir / f"ai-builder-api-battle-test-{created_at}-{safe_suffix}.json"
    _write_json_exclusive(path, bundle)
    return path


def _resolved_model_identity(
    *,
    session_models: Mapping[str, object] | None,
    requested_model_id: str | None,
    planner_observed_model_ids: list[str],
    classifier_observed_model_ids: list[str],
    planner_interaction_count: int | None = None,
    planner_observations: list[JsonObject] | None = None,
    missing_planner_interaction_indices: list[int] | None = None,
) -> JsonObject:
    session_models = session_models or {}
    raw_models = session_models.get("models")
    models = (
        [model for model in raw_models if isinstance(model, Mapping)]
        if isinstance(raw_models, list)
        else []
    )
    selected_id = requested_model_id or _optional_string(
        session_models, "default_model_id"
    )
    selected_model = next(
        (model for model in models if _optional_string(model, "id") == selected_id),
        None,
    )
    resolved_name = (
        _optional_string(selected_model, "name") if selected_model is not None else None
    )
    resolved_provider = (
        _optional_string(selected_model, "provider")
        if selected_model is not None
        else None
    )
    expected_observed_ids = _clean_strings(
        [
            (
                f"{resolved_provider}/{resolved_name}"
                if resolved_provider is not None and resolved_name is not None
                else None
            )
        ]
    )
    observed_model_ids = list(
        dict.fromkeys([*planner_observed_model_ids, *classifier_observed_model_ids])
    )
    planner_observations = planner_observations or []
    missing_planner_interaction_indices = missing_planner_interaction_indices or []
    planner_evidence_complete = bool(planner_observed_model_ids)
    if planner_interaction_count is not None:
        planner_evidence_complete = (
            planner_interaction_count > 0
            and len(planner_observations) == planner_interaction_count
            and not missing_planner_interaction_indices
        )
    return {
        "requested_id": requested_model_id,
        "resolved_id": selected_id if selected_model is not None else None,
        "resolved_name": resolved_name,
        "resolved_provider": resolved_provider,
        "expected_observed_ids": expected_observed_ids,
        "planner_interaction_count": planner_interaction_count,
        "planner_observations": planner_observations,
        "missing_planner_interaction_indices": (missing_planner_interaction_indices),
        "planner_observed_ids": planner_observed_model_ids,
        "classifier_observed_ids": classifier_observed_model_ids,
        "observed_ids": observed_model_ids,
        "observed_matches_resolved": planner_evidence_complete
        and bool(expected_observed_ids)
        and all(item in expected_observed_ids for item in observed_model_ids),
    }


def _planner_model_evidence_from_interactions(
    interactions: object,
) -> tuple[list[str], list[JsonObject], list[int], int]:
    if not isinstance(interactions, list):
        return [], [], [], 0
    observed: list[str] = []
    observations: list[JsonObject] = []
    missing_indices: list[int] = []
    for interaction_index, interaction in enumerate(interactions, start=1):
        if not isinstance(interaction, Mapping):
            missing_indices.append(interaction_index)
            continue
        events = interaction.get("events")
        if not isinstance(events, list):
            missing_indices.append(interaction_index)
            continue
        interaction_models: list[str] = []
        usage_event_count = 0
        for event in events:
            if not isinstance(event, Mapping) or event.get("event") != "usage":
                continue
            usage_event_count += 1
            data = event.get("data")
            model = (
                _optional_string(data, "last_model")
                if isinstance(data, Mapping)
                else None
            )
            if model is not None and model not in interaction_models:
                interaction_models.append(model)
        if usage_event_count == 0:
            # Server-resolved turns (auto-resolved slots, confirmations)
            # legitimately make zero planner calls: identity-neutral, not
            # identity-missing. A bundle observing no planner model at all
            # still fails closed downstream.
            continue
        if len(interaction_models) != 1:
            missing_indices.append(interaction_index)
            continue
        model = interaction_models[0]
        observations.append({"interaction_index": interaction_index, "model_id": model})
        if model not in observed:
            observed.append(model)
    return observed, observations, missing_indices, len(interactions)


def _classifier_model_ids(
    classifier_diagnostics: Mapping[str, object] | None,
) -> list[str]:
    return list(
        dict.fromkeys(
            _clean_strings(
                [
                    (
                        str(run["model"])
                        if "/" in str(run["model"])
                        else f"{run['provider']}/{run['model']}"
                    )
                    for run in _classifier_runs(classifier_diagnostics)
                    if isinstance(run.get("model"), str)
                    and isinstance(run.get("provider"), str)
                ]
            )
        )
    )


def _classifier_prompt_hashes(
    classifier_diagnostics: Mapping[str, object] | None,
) -> list[str]:
    return list(
        dict.fromkeys(
            _clean_strings(
                [
                    run.get("prompt_hash")
                    for run in _classifier_runs(classifier_diagnostics)
                    if isinstance(run.get("prompt_hash"), str)
                ]
            )
        )
    )


def _proposal_progress_payload(progress: Mapping[str, object]) -> JsonObject:
    return {
        key: progress.get(key)
        for key in (
            "source",
            "call_count",
            "repair_attempts",
            "parse_repair_attempts",
            "attempts",
            "provider_failure_status",
            "public_error_code_count",
        )
    }


def _live_execution_provenance(
    *,
    case: BattleCase,
    cases_path: Path | None = DEFAULT_CASES_FILE,
    latest_session: Mapping[str, object] | None,
    classifier_diagnostics: Mapping[str, object] | None,
    requested_model_id: str | None,
    session_models: Mapping[str, object] | None = None,
    event_summary: Mapping[str, object] | None = None,
    interactions: object = None,
) -> JsonObject:
    source_revision = _git_output("rev-parse", "HEAD")
    tracked_status = _git_output("status", "--porcelain", "--untracked-files=no")
    source_revision_sha256 = hashlib.sha256(source_revision.encode("utf-8")).hexdigest()
    harness_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    cases_sha256 = (
        hashlib.sha256(cases_path.read_bytes()).hexdigest()
        if cases_path is not None
        else None
    )
    stable_build_payload = {
        "source_revision": source_revision,
        "harness_sha256": harness_sha256,
        "cases_sha256": cases_sha256,
    }
    build_payload = {
        "app_version": LOCAL_APP_VERSION,
        **stable_build_payload,
    }
    telemetry = (
        latest_session.get("telemetry")
        if isinstance(latest_session, Mapping)
        and isinstance(latest_session.get("telemetry"), Mapping)
        else {}
    )
    (
        planner_observed_model_ids,
        planner_observations,
        missing_planner_interaction_indices,
        planner_interaction_count,
    ) = _planner_model_evidence_from_interactions(interactions)
    if interactions is None:
        planner_observed_model_ids = _clean_strings([telemetry.get("last_model")])
        planner_observations = (
            [{"interaction_index": 1, "model_id": planner_observed_model_ids[0]}]
            if planner_observed_model_ids
            else []
        )
        planner_interaction_count = 1
        missing_planner_interaction_indices = [] if planner_observed_model_ids else [1]
    classifier_observed_model_ids = _classifier_model_ids(classifier_diagnostics)
    model_identity = _resolved_model_identity(
        session_models=session_models,
        requested_model_id=requested_model_id,
        planner_observed_model_ids=planner_observed_model_ids,
        classifier_observed_model_ids=classifier_observed_model_ids,
        planner_interaction_count=planner_interaction_count,
        planner_observations=planner_observations,
        missing_planner_interaction_indices=(missing_planner_interaction_indices),
    )
    classifier_prompt_hashes = _classifier_prompt_hashes(classifier_diagnostics)
    classifier_request_composite_fingerprint = (
        _canonical_sha256({"classifier_prompt_hashes": classifier_prompt_hashes})
        if classifier_prompt_hashes
        and all(_is_sha256(item) for item in classifier_prompt_hashes)
        else None
    )

    def telemetry_metric(key: str) -> int | None:
        value = telemetry.get(key)
        return (
            value
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
            else None
        )

    model_calls = telemetry_metric("llm_calls_made_total")
    repair_attempts = telemetry_metric("repair_attempts_total")
    parse_repair_attempts = telemetry_metric("parse_repair_attempts_total")
    prompt_tokens = telemetry_metric("prompt_tokens_total")
    completion_tokens = telemetry_metric("completion_tokens_total")
    total_tokens = telemetry_metric("total_tokens_total")
    elapsed_ms = telemetry_metric("wall_clock_ms_total")
    event_counts = (
        event_summary.get("event_counts")
        if isinstance(event_summary, Mapping)
        and isinstance(event_summary.get("event_counts"), Mapping)
        else None
    )
    error_count = None
    if isinstance(event_counts, Mapping):
        raw_error_count = event_counts.get("error")
        if (
            isinstance(raw_error_count, int)
            and not isinstance(raw_error_count, bool)
            and raw_error_count >= 0
        ):
            error_count = raw_error_count
    raw_error_codes = (
        event_summary.get("error_codes") if isinstance(event_summary, Mapping) else None
    )
    error_codes_complete = isinstance(raw_error_codes, list) and all(
        isinstance(code, str) and bool(code) for code in raw_error_codes
    )
    error_codes = _string_list(raw_error_codes) if error_codes_complete else []
    if (
        error_count is None
        or not error_codes_complete
        or error_count != len(error_codes)
    ):
        provider_failure_status = "unclassified"
    elif "session_turn_provider_outcome_unknown" in error_codes:
        provider_failure_status = "outcome_unknown"
    elif error_codes:
        provider_failure_status = "classified_public_error"
    else:
        provider_failure_status = "none"
    token_usage_source = telemetry.get("last_token_usage_source")
    token_usage_estimated = telemetry.get("last_token_usage_estimated")
    token_usage_posture_complete = (
        token_usage_source == "provider" and token_usage_estimated is False
    ) or (token_usage_source == "litellm_estimate" and token_usage_estimated is True)
    token_counts_complete = (
        prompt_tokens is not None
        and completion_tokens is not None
        and total_tokens is not None
        and total_tokens > 0
        and total_tokens == prompt_tokens + completion_tokens
    )
    attempt_evidence_complete = (
        model_calls == 1
        and repair_attempts is not None
        and parse_repair_attempts is not None
        and token_counts_complete
        and elapsed_ms is not None
        and elapsed_ms > 0
        and token_usage_posture_complete
    )
    attempts: list[JsonObject] = []
    if attempt_evidence_complete:
        attempts.append(
            {
                "attempt": 1,
                "kind": (
                    "initial"
                    if repair_attempts == 0 and parse_repair_attempts == 0
                    else "unresolved"
                ),
                "call_count": 1,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "elapsed_ms": elapsed_ms,
                "elapsed_scope": "proposal_turn_upper_bound",
                "token_usage_source": token_usage_source,
                "token_usage_estimated": token_usage_estimated,
            }
        )
    progress_values: JsonObject = {
        "source": "single_call_committed_session_summary",
        "call_count": model_calls,
        "repair_attempts": repair_attempts,
        "parse_repair_attempts": parse_repair_attempts,
        "attempts": attempts,
        "provider_failure_status": provider_failure_status,
        "public_error_code_count": len(error_codes) if error_codes_complete else None,
    }
    return {
        "mode": "live_execution",
        "source": {
            "revision": source_revision,
            "revision_sha256": source_revision_sha256,
            "tracked_clean": not tracked_status,
        },
        "build": {
            **build_payload,
            "sha256": _canonical_sha256(stable_build_payload),
        },
        "model": {
            **model_identity,
            "sha256": _canonical_sha256(model_identity),
        },
        "prompt": {
            "case_sha256": hashlib.sha256(case.prompt.encode("utf-8")).hexdigest(),
            "classifier_hashes": classifier_prompt_hashes,
        },
        "capability": {
            "source": "slot_classification_prompt_hash_composite",
            "classifier_prompt_hashes": classifier_prompt_hashes,
            "classifier_request_composite_fingerprint": (
                classifier_request_composite_fingerprint
            ),
        },
        "proposal_progress": {
            **progress_values,
            "fingerprint": _canonical_sha256(progress_values),
        },
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "model_calls": model_calls,
            "repair_attempts": repair_attempts,
            "parse_repair_attempts": parse_repair_attempts,
            "elapsed_ms": elapsed_ms,
            "raw_reads": _classifier_raw_read_metrics(classifier_diagnostics),
        },
    }


def _classifier_raw_read_metrics(
    classifier_diagnostics: Mapping[str, object] | None,
) -> JsonObject:
    inventories = [
        inventory
        for run in _classifier_runs(classifier_diagnostics)
        for inventory in [run.get("source_inventory")]
        if isinstance(inventory, list)
    ]
    sources = [
        source
        for inventory in inventories
        for source in inventory
        if isinstance(source, Mapping)
    ]
    uploaded_sources = [
        source for source in sources if source.get("kind") == "uploaded_file"
    ]
    uploaded_file_ids = _clean_strings(
        [source.get("file_id") for source in uploaded_sources]
    )
    coverage_counts: dict[str, int] = {}
    for source in uploaded_sources:
        coverage = source.get("coverage")
        if isinstance(coverage, str) and coverage:
            coverage_counts[coverage] = coverage_counts.get(coverage, 0) + 1
    return {
        "classifier_run_count": len(_classifier_runs(classifier_diagnostics)),
        "source_inventory_entry_count": len(sources),
        "uploaded_file_raw_read_count": len(uploaded_sources),
        "distinct_uploaded_file_count": len(set(uploaded_file_ids)),
        "uploaded_file_reread_count": max(
            0,
            len(uploaded_sources) - len(set(uploaded_file_ids)),
        ),
        "truncated_source_count": sum(
            1 for source in sources if source.get("truncated") is True
        ),
        "uploaded_file_coverage_counts": coverage_counts,
    }


def _live_provenance_checks(
    provenance: Mapping[str, object],
    *,
    expected: Mapping[str, object] | None = None,
) -> list[JsonObject]:
    source = provenance.get("source")
    source = source if isinstance(source, Mapping) else {}
    build = provenance.get("build")
    build = build if isinstance(build, Mapping) else {}
    model = provenance.get("model")
    model = model if isinstance(model, Mapping) else {}
    prompt = provenance.get("prompt")
    prompt = prompt if isinstance(prompt, Mapping) else {}
    usage = provenance.get("usage")
    usage = usage if isinstance(usage, Mapping) else {}
    raw_reads = usage.get("raw_reads")
    raw_reads = raw_reads if isinstance(raw_reads, Mapping) else {}
    source_complete = (
        isinstance(source.get("revision"), str)
        and _is_sha256(source.get("revision_sha256"))
        and source.get("tracked_clean") is True
    )
    build_complete = all(
        _is_sha256(build.get(key))
        for key in ("harness_sha256", "cases_sha256", "sha256")
    ) and isinstance(build.get("app_version"), str)
    observed_model_ids = _string_list(model.get("observed_ids"))
    model_complete = (
        bool(observed_model_ids)
        and isinstance(model.get("resolved_id"), str)
        and model.get("observed_matches_resolved") is True
        and _is_sha256(model.get("sha256"))
    )
    classifier_hashes = _string_list(prompt.get("classifier_hashes"))
    prompt_complete = (
        _is_sha256(prompt.get("case_sha256"))
        and bool(classifier_hashes)
        and all(_is_sha256(item) for item in classifier_hashes)
    )
    usage_complete = all(
        isinstance(usage.get(key), int)
        and not isinstance(usage.get(key), bool)
        and usage.get(key) >= 0
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "model_calls",
        )
    ) and all(
        isinstance(raw_reads.get(key), int)
        and not isinstance(raw_reads.get(key), bool)
        and raw_reads.get(key) >= 0
        for key in (
            "classifier_run_count",
            "source_inventory_entry_count",
            "uploaded_file_raw_read_count",
            "distinct_uploaded_file_count",
            "uploaded_file_reread_count",
            "truncated_source_count",
        )
    )
    checks: list[JsonObject] = [
        {
            "name": "live_source_provenance_complete",
            "passed": source_complete,
            "actual": dict(source),
            "expected": "clean immutable source revision and hash",
        },
        {
            "name": "live_build_provenance_complete",
            "passed": build_complete,
            "actual": dict(build),
            "expected": "app version plus harness, cases, and build hashes",
        },
        {
            "name": "live_model_provenance_complete",
            "passed": model_complete,
            "actual": dict(model),
            "expected": "observed model identity and hash",
        },
        {
            "name": "live_prompt_provenance_complete",
            "passed": prompt_complete,
            "actual": dict(prompt),
            "expected": "case and classifier prompt hashes",
        },
        {
            "name": "live_usage_provenance_complete",
            "passed": usage_complete,
            "actual": dict(usage),
            "expected": "token, model-call, and classifier raw-read metrics",
        },
    ]
    first_pass = (
        expected.get("expected_first_pass_authoring")
        if isinstance(expected, Mapping)
        else None
    )
    if isinstance(first_pass, Mapping):
        checks.extend(
            _first_pass_provenance_checks(
                provenance=provenance,
                expected=first_pass,
            )
        )
    return checks


def _quality_report_with_live_provenance(
    report: JsonObject,
    *,
    provenance: Mapping[str, object],
    expected: Mapping[str, object],
) -> JsonObject:
    """Return one complete report for both live execution and reanalysis."""

    checks = report.get("checks")
    if not isinstance(checks, list):
        raise ValueError("quality report has no checks collection")
    return {
        **report,
        "checks": [
            *checks,
            *_live_provenance_checks(provenance, expected=expected),
        ],
    }


def _observation_evidence_report(bundle: Mapping[str, object]) -> JsonObject:
    """Recompute whether a completed observation is safe to evaluate."""

    case = bundle.get("case")
    case = case if isinstance(case, Mapping) else {}
    case_identity = bundle.get("case_identity")
    case_identity = case_identity if isinstance(case_identity, Mapping) else {}
    case_contract = bundle.get("case_contract")
    case_contract = case_contract if isinstance(case_contract, Mapping) else {}
    expected_case_identity = {
        "id": case_contract.get("id"),
        "required": case_contract.get("required"),
        "complexity": case_contract.get("complexity"),
        "domain": case_contract.get("domain"),
        "cohorts": case_contract.get("cohorts"),
    }
    case_contract_complete = (
        bool(case_contract)
        and _observed_case_contract_payload(case) == dict(case_contract)
        and dict(case_identity) == expected_case_identity
        and bundle.get("case_contract_sha256") == _canonical_sha256(dict(case_contract))
    )
    attachment_fixture = case_contract.get("attachment_fixture")
    attachment_fixture = (
        attachment_fixture if isinstance(attachment_fixture, Mapping) else {}
    )
    file_ids = case.get("file_ids")
    declared_attachments = attachment_fixture.get("attachments")
    direct_file_slot_count = attachment_fixture.get("direct_file_slot_count")
    resolved_attachment_count_complete = (
        isinstance(file_ids, list)
        and isinstance(declared_attachments, list)
        and isinstance(direct_file_slot_count, int)
        and not isinstance(direct_file_slot_count, bool)
        and len(file_ids) == direct_file_slot_count + len(declared_attachments)
    )
    case_contract_complete = (
        case_contract_complete and resolved_attachment_count_complete
    )

    provenance = bundle.get("live_execution_provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    source = provenance.get("source")
    source = source if isinstance(source, Mapping) else {}
    revision = _optional_string(source, "revision")
    source_complete = (
        revision is not None
        and source.get("revision_sha256")
        == hashlib.sha256(revision.encode("utf-8")).hexdigest()
        and source.get("tracked_clean") is True
    )

    build = provenance.get("build")
    build = build if isinstance(build, Mapping) else {}
    stable_build_payload = {
        key: build.get(key)
        for key in ("source_revision", "harness_sha256", "cases_sha256")
    }
    build_complete = (
        build.get("source_revision") == revision
        and all(
            _is_sha256(build.get(key)) for key in ("harness_sha256", "cases_sha256")
        )
        and isinstance(build.get("app_version"), str)
        and build.get("sha256") == _canonical_sha256(stable_build_payload)
    )

    interactions = bundle.get("interactions")
    (
        planner_model_ids,
        planner_observations,
        missing_planner_indices,
        planner_interaction_count,
    ) = _planner_model_evidence_from_interactions(interactions)
    classifier_diagnostics = bundle.get("classifier_diagnostics")
    classifier_diagnostics = (
        classifier_diagnostics if isinstance(classifier_diagnostics, Mapping) else None
    )
    classifier_contract_complete = _classifier_evidence_contract_is_valid(
        classifier_diagnostics
    )
    classifier_model_ids = _classifier_model_ids(classifier_diagnostics)
    model = provenance.get("model")
    model = model if isinstance(model, Mapping) else {}
    model_payload = dict(model)
    model_sha256 = model_payload.pop("sha256", None)
    resolved_name = _optional_string(model, "resolved_name")
    resolved_provider = _optional_string(model, "resolved_provider")
    expected_model_ids = (
        [f"{resolved_provider}/{resolved_name}"]
        if resolved_provider is not None and resolved_name is not None
        else []
    )
    observed_model_ids = list(
        dict.fromkeys([*planner_model_ids, *classifier_model_ids])
    )
    model_complete = (
        bool(expected_model_ids)
        and classifier_contract_complete
        and isinstance(model.get("resolved_id"), str)
        and model.get("expected_observed_ids") == expected_model_ids
        and model_sha256 == _canonical_sha256(model_payload)
        and model.get("planner_interaction_count") == planner_interaction_count
        and model.get("planner_observations") == planner_observations
        and model.get("missing_planner_interaction_indices") == missing_planner_indices
        and model.get("planner_observed_ids") == planner_model_ids
        and model.get("classifier_observed_ids") == classifier_model_ids
        and model.get("observed_ids") == observed_model_ids
        and model.get("observed_matches_resolved") is True
        and not missing_planner_indices
        and planner_interaction_count > 0
        and all(model_id in expected_model_ids for model_id in observed_model_ids)
    )

    prompt = provenance.get("prompt")
    prompt = prompt if isinstance(prompt, Mapping) else {}
    prompt_text = _optional_string(case, "prompt")
    classifier_hashes = _classifier_prompt_hashes(classifier_diagnostics)
    prompt_complete = (
        prompt_text is not None
        and prompt.get("case_sha256")
        == hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
        and bool(classifier_hashes)
        and all(_is_sha256(value) for value in classifier_hashes)
        and prompt.get("classifier_hashes") == classifier_hashes
    )

    capability = provenance.get("capability")
    capability = capability if isinstance(capability, Mapping) else {}
    capability_complete = (
        capability.get("source") == "slot_classification_prompt_hash_composite"
        and capability.get("classifier_prompt_hashes") == classifier_hashes
        and capability.get("classifier_request_composite_fingerprint")
        == _canonical_sha256({"classifier_prompt_hashes": classifier_hashes})
    )

    progress = provenance.get("proposal_progress")
    progress = progress if isinstance(progress, Mapping) else {}
    progress_complete = set(progress) == set(_proposal_progress_payload(progress)) | {
        "fingerprint"
    } and progress.get("fingerprint") == _canonical_sha256(
        _proposal_progress_payload(progress)
    )

    observation_input = bundle.get("observation_input_identity")
    observation_input = (
        observation_input if isinstance(observation_input, Mapping) else {}
    )
    attachment_sha256s = observation_input.get("attachment_evidence_sha256s")
    runtime_sha256s = observation_input.get("runtime_source_sha256s")
    declared_runtime_sha256s = observation_input.get("declared_runtime_sha256s")
    attached_file_ids = tuple(_string_list(case.get("file_ids")))
    # The receipt carries the fixture contract it ran against, so this recompute
    # stays offline even when the repository has since moved on: the digests
    # come from the bundle, not from whatever manifest is on disk today.
    declared_attachments = _fixture_contract_or_none(
        attachment_fixture.get("attachments")
    )
    expected_runtime_fixtures = _fixture_contract_or_none(
        attachment_fixture.get("runtime_files")
    )
    expected_runtime_digest_count = len(expected_runtime_fixtures or [])
    recomputed_attachment_sha256s = _attachment_evidence_sha256s(
        attached_file_ids=attached_file_ids,
        classifier_diagnostics=classifier_diagnostics,
    )
    runtime_evidence = bundle.get("runtime_evidence")
    recomputed_runtime_sha256s, recomputed_runtime_status = _runtime_lineage_sha256s(
        runtime_evidence if isinstance(runtime_evidence, Mapping) else None,
        expected_count=expected_runtime_digest_count,
    )
    expected_declared_runtime_sha256s = [
        entry["content_sha256"] for entry in expected_runtime_fixtures or []
    ]
    fingerprint_payload = {
        "attachment_evidence_sha256s": recomputed_attachment_sha256s,
        "runtime_source_sha256s": recomputed_runtime_sha256s,
    }
    expected_mismatches: list[str] = []
    attachment_evidence_complete = all(
        _is_sha256(value) for value in recomputed_attachment_sha256s
    )
    if attached_file_ids and not attachment_evidence_complete:
        expected_mismatches.append("attachment_evidence")
    if expected_declared_runtime_sha256s and recomputed_runtime_status != "complete":
        expected_mismatches.append("runtime_evidence")
    if recomputed_runtime_status == "complete" and recomputed_runtime_sha256s != (
        expected_declared_runtime_sha256s
    ):
        expected_mismatches.append("runtime_content")
    fingerprint_complete = all(
        _is_sha256(value) for value in recomputed_attachment_sha256s
    ) and all(_is_sha256(value) for value in recomputed_runtime_sha256s)
    input_complete = (
        isinstance(attachment_sha256s, list)
        and isinstance(runtime_sha256s, list)
        and declared_attachments is not None
        and observation_input.get("attachment_fixtures") == declared_attachments
        and declared_runtime_sha256s == expected_declared_runtime_sha256s
        and all(_is_sha256(value) for value in attachment_sha256s)
        and all(_is_sha256(value) for value in runtime_sha256s)
        and attachment_sha256s == recomputed_attachment_sha256s
        and runtime_sha256s == recomputed_runtime_sha256s
        and observation_input.get("runtime_evidence_status")
        == recomputed_runtime_status
        and observation_input.get("mismatches") == expected_mismatches
        and observation_input.get("verified")
        == (not expected_mismatches and fingerprint_complete)
        and observation_input.get("sha256") == _canonical_sha256(fingerprint_payload)
    )

    provenance_shape_complete = all(
        check.get("passed") is True for check in _live_provenance_checks(provenance)
    )
    checks: list[JsonObject] = [
        {
            "name": "observation_case_contract_consistent",
            "passed": case_contract_complete,
            "actual": {
                "case_contract_sha256": bundle.get("case_contract_sha256"),
                "case_identity": dict(case_identity),
            },
            "expected": {
                "case_contract_sha256": (
                    _canonical_sha256(dict(case_contract)) if case_contract else None
                ),
                "case_identity": expected_case_identity,
            },
        },
        {
            "name": "observation_source_provenance_consistent",
            "passed": source_complete,
            "actual": dict(source),
            "expected": "revision hash recomputes and tracked source is clean",
        },
        {
            "name": "observation_build_provenance_consistent",
            "passed": build_complete,
            "actual": dict(build),
            "expected": "build hash recomputes from the observed source and inputs",
        },
        {
            "name": "observation_model_provenance_consistent",
            "passed": model_complete,
            "actual": dict(model),
            "expected": {
                "planner_interaction_count": planner_interaction_count,
                "planner_observations": planner_observations,
                "missing_planner_interaction_indices": missing_planner_indices,
                "classifier_observed_ids": classifier_model_ids,
            },
        },
        {
            "name": "observation_prompt_provenance_consistent",
            "passed": prompt_complete,
            "actual": dict(prompt),
            "expected": {
                "case_sha256": (
                    hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
                    if prompt_text is not None
                    else None
                ),
                "classifier_hashes": classifier_hashes,
            },
        },
        {
            "name": "observation_capability_provenance_consistent",
            "passed": capability_complete,
            "actual": dict(capability),
            "expected": "classifier prompt composite recomputes",
        },
        {
            "name": "observation_progress_provenance_consistent",
            "passed": progress_complete,
            "actual": dict(progress),
            "expected": "proposal progress fingerprint recomputes",
        },
        {
            "name": "observation_input_identity_consistent",
            "passed": input_complete,
            "actual": dict(observation_input),
            "expected": "declared and observed input hashes match and recompute",
        },
        {
            "name": "observation_provenance_shape_complete",
            "passed": provenance_shape_complete,
            "actual": _live_provenance_checks(provenance),
            "expected": "all required live provenance fields are complete",
        },
    ]
    failed_checks = [check for check in checks if check.get("passed") is not True]
    return {
        "valid": not failed_checks,
        "failed_check_count": len(failed_checks),
        "failed_checks": failed_checks,
        "checks": checks,
    }


def _first_pass_provenance_checks(
    *,
    provenance: Mapping[str, object],
    expected: Mapping[str, object],
) -> list[JsonObject]:
    capability = provenance.get("capability")
    capability = capability if isinstance(capability, Mapping) else {}
    classifier_hashes = _string_list(capability.get("classifier_prompt_hashes"))
    classifier_request_composite_fingerprint = capability.get(
        "classifier_request_composite_fingerprint"
    )
    capability_complete = (
        expected.get("require_classifier_request_composite_fingerprint") is True
        and capability.get("source") == "slot_classification_prompt_hash_composite"
        and bool(classifier_hashes)
        and all(_is_sha256(item) for item in classifier_hashes)
        and _is_sha256(classifier_request_composite_fingerprint)
        and classifier_request_composite_fingerprint
        == _canonical_sha256({"classifier_prompt_hashes": classifier_hashes})
    )
    progress = provenance.get("proposal_progress")
    progress = progress if isinstance(progress, Mapping) else {}
    progress_payload = _proposal_progress_payload(progress)
    progress_fingerprint = progress.get("fingerprint")
    progress_complete = (
        expected.get("require_progress_fingerprint") is True
        and progress.get("source") == "single_call_committed_session_summary"
        and _is_sha256(progress_fingerprint)
        and progress_fingerprint == _canonical_sha256(progress_payload)
    )
    expected_calls = _int_value(expected.get("proposal_call_count"))
    expected_max_repairs = _int_value(expected.get("max_repair_attempts"))
    repair_attempts = _int_value(progress.get("repair_attempts"))
    parse_repair_attempts = _int_value(progress.get("parse_repair_attempts"))
    attempts = _mapping_list(progress.get("attempts"))
    attempt = attempts[0] if len(attempts) == 1 else None
    attempt_complete = (
        expected_calls == 1
        and attempt is not None
        and attempt.get("attempt") == 1
        and attempt.get("kind") == "initial"
        and attempt.get("call_count") == 1
        and attempt.get("elapsed_scope") == "proposal_turn_upper_bound"
        and all(
            isinstance(attempt.get(key), int)
            and not isinstance(attempt.get(key), bool)
            and attempt.get(key) >= 0
            for key in (
                "prompt_tokens",
                "completion_tokens",
            )
        )
        and isinstance(attempt.get("total_tokens"), int)
        and not isinstance(attempt.get("total_tokens"), bool)
        and attempt.get("total_tokens") > 0
        and attempt.get("total_tokens")
        == attempt.get("prompt_tokens") + attempt.get("completion_tokens")
        and isinstance(attempt.get("elapsed_ms"), int)
        and not isinstance(attempt.get("elapsed_ms"), bool)
        and attempt.get("elapsed_ms") > 0
        and (
            (
                attempt.get("token_usage_source") == "provider"
                and attempt.get("token_usage_estimated") is False
            )
            or (
                attempt.get("token_usage_source") == "litellm_estimate"
                and attempt.get("token_usage_estimated") is True
            )
        )
    )
    expected_failure_status = expected.get("provider_failure_status")
    return [
        {
            "name": "first_pass_classifier_request_composite_fingerprint",
            "passed": capability_complete,
            "actual": dict(capability),
            "expected": (
                "source-labelled capability-sensitive classifier request composite"
            ),
        },
        {
            "name": "first_pass_progress_fingerprint",
            "passed": progress_complete,
            "actual": progress_fingerprint,
            "expected": _canonical_sha256(progress_payload),
        },
        {
            "name": "first_pass_proposal_call_count",
            "passed": progress.get("call_count") == expected_calls,
            "actual": progress.get("call_count"),
            "expected": expected_calls,
        },
        {
            "name": "first_pass_zero_repairs",
            "passed": (
                repair_attempts is not None
                and parse_repair_attempts is not None
                and expected_max_repairs is not None
                and repair_attempts <= expected_max_repairs
                and parse_repair_attempts <= expected_max_repairs
            ),
            "actual": {
                "repair_attempts": repair_attempts,
                "parse_repair_attempts": parse_repair_attempts,
            },
            "expected": {"maximum_each": expected_max_repairs},
        },
        {
            "name": "first_pass_attempt_evidence",
            "passed": attempt_complete,
            "actual": [dict(item) for item in attempts],
            "expected": "one bounded initial call/token/elapsed record",
        },
        {
            "name": "first_pass_provider_failure_provenance",
            "passed": progress.get("provider_failure_status")
            == expected_failure_status,
            "actual": progress.get("provider_failure_status"),
            "expected": expected_failure_status,
        },
    ]


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _git_output(*args: str) -> str:
    repository_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["git", *args],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_bytes_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _suite_result(bundle: JsonObject, bundle_path: Path) -> JsonObject:
    report = bundle.get("quality_report")
    checks = report.get("checks") if isinstance(report, Mapping) else []
    identity_checks = bundle.get("release_identity_checks")
    identity_checks = identity_checks if isinstance(identity_checks, list) else []
    warnings = report.get("warnings") if isinstance(report, Mapping) else []
    metrics = report.get("metrics") if isinstance(report, Mapping) else {}
    event_summary = bundle.get("event_summary")
    event_summary = event_summary if isinstance(event_summary, Mapping) else {}
    journey = bundle.get("journey")
    journey = dict(journey) if isinstance(journey, Mapping) else {}
    case_identity = bundle.get("case_identity")
    case_identity = dict(case_identity) if isinstance(case_identity, Mapping) else {}
    observation_input_identity = bundle.get("observation_input_identity")
    observation_input_identity = (
        observation_input_identity
        if isinstance(observation_input_identity, Mapping)
        else {}
    )
    provenance = bundle.get("live_execution_provenance")
    usage = (
        provenance.get("usage")
        if isinstance(provenance, Mapping)
        and isinstance(provenance.get("usage"), Mapping)
        else {}
    )
    raw_failed_checks = [
        check
        for check in checks
        if isinstance(check, Mapping) and check.get("passed") is not True
    ]
    failed_identity_checks = [
        check
        for check in identity_checks
        if isinstance(check, Mapping) and check.get("passed") is not True
    ]
    completed_live_execution = bundle.get("artifact_mode") == "live_execution"
    evidence_report = (
        _observation_evidence_report(bundle) if completed_live_execution else {}
    )
    evidence_valid = (
        evidence_report.get("valid") is True if completed_live_execution else None
    )
    evidence_failed_checks = evidence_report.get("failed_checks")
    evidence_failed_checks = (
        evidence_failed_checks if isinstance(evidence_failed_checks, list) else []
    )
    if bundle.get("artifact_mode") == "live_execution_failure":
        outcome_class = "execution_failure"
        observation_status = "execution_failure"
        expectation_verdict = "not_evaluated"
    elif completed_live_execution and evidence_valid is not True:
        journey_outcome = journey.get("outcome_class")
        if journey_outcome in {"builder_error", "provider_outcome_unknown"}:
            # An error-terminated turn has no provenance to validate; the
            # journey outcome is the truth and must not be masked as an
            # observation problem (13 masked rows in the 2026-08-06 run).
            outcome_class = journey_outcome
            observation_status = "error_terminated"
            expectation_verdict = "not_evaluated"
        else:
            outcome_class = "invalid_evidence"
            observation_status = "invalid_evidence"
            expectation_verdict = "not_evaluated"
    elif isinstance(journey.get("outcome_class"), str):
        outcome_class = journey["outcome_class"]
        observation_status = "completed"
        expectation_verdict = "fail" if raw_failed_checks else "pass"
    else:
        outcome_class = "unclassified"
        observation_status = "completed"
        expectation_verdict = "fail" if raw_failed_checks else "pass"
    failed_checks = raw_failed_checks if expectation_verdict in {"pass", "fail"} else []
    bundle_bytes = bundle_path.read_bytes()
    return {
        "artifact_mode": bundle.get("artifact_mode"),
        "case_identity": case_identity,
        "case_id": case_identity.get("id"),
        "required": case_identity.get("required") is True,
        "complexity": case_identity.get("complexity"),
        "domain": case_identity.get("domain"),
        "cohorts": _string_list(case_identity.get("cohorts")),
        "session_id": bundle.get("session_id"),
        "plan_id": bundle.get("plan_id"),
        "repetition": bundle.get("repetition"),
        "case_contract_sha256": bundle.get("case_contract_sha256"),
        "observation_input_sha256": observation_input_identity.get("sha256"),
        "observation_input_verified": (
            observation_input_identity.get("verified") is True
        ),
        "bundle_file": bundle_path.name,
        "bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        "observation_status": observation_status,
        "expectation_verdict": expectation_verdict,
        "outcome_class": outcome_class,
        "evidence_valid": evidence_valid,
        "evidence_failed_check_count": len(evidence_failed_checks),
        "evidence_failed_checks": evidence_failed_checks,
        "error": bundle.get("error") if isinstance(bundle.get("error"), str) else None,
        "client_turn_id": (
            bundle.get("client_turn_id")
            if isinstance(bundle.get("client_turn_id"), str)
            else None
        ),
        "step_count": bundle.get("plan_summary", {}).get("step_count")
        if isinstance(bundle.get("plan_summary"), Mapping)
        else None,
        "failed_expectation_check_count": len(failed_checks),
        "failed_checks": failed_checks,
        "identity_failed_check_count": len(failed_identity_checks),
        "identity_failed_checks": failed_identity_checks,
        "warning_count": len(warnings) if isinstance(warnings, list) else 0,
        "warnings": warnings if isinstance(warnings, list) else [],
        "metrics": metrics if isinstance(metrics, Mapping) else {},
        "event_summary": dict(event_summary),
        "journey": journey,
        "authoring_usage": dict(usage),
        "assumptions": _string_list(event_summary.get("assumptions")),
        "failure_summary": bundle.get("failure_summary")
        if isinstance(bundle.get("failure_summary"), Mapping)
        else _failure_summary(event_summary),
    }


def _failed_check_names(result: Mapping[str, Any]) -> list[str]:
    failed_checks = result.get("failed_checks")
    if not isinstance(failed_checks, list):
        return []
    names: list[str] = []
    for failed_check in failed_checks:
        if not isinstance(failed_check, Mapping):
            continue
        name = failed_check.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _suite_reliability_summary(results: list[JsonObject]) -> JsonObject:
    grouped: dict[str, list[JsonObject]] = {}
    for result in results:
        case_id = result.get("case_id")
        if isinstance(case_id, str):
            grouped.setdefault(case_id, []).append(result)

    summary: JsonObject = {}
    for case_id, case_results in grouped.items():
        completed_results = [
            result
            for result in case_results
            if result.get("observation_status") == "completed"
        ]
        run_count = len(completed_results)
        execution_failure_count = sum(
            1
            for result in case_results
            if result.get("observation_status") == "execution_failure"
        )
        plan_count = sum(1 for result in completed_results if result.get("plan_id"))
        repair_failure_count = 0
        invalid_plan_count = 0
        text_only_question_count = 0
        assumptions: list[str] = []
        error_code_counts: dict[str, int] = {}
        for result in completed_results:
            _extend_unique_strings(assumptions, _string_list(result.get("assumptions")))
            event_summary = result.get("event_summary")
            if not isinstance(event_summary, Mapping):
                continue
            error_codes = _string_list(event_summary.get("error_codes"))
            for code in error_codes:
                error_code_counts[code] = error_code_counts.get(code, 0) + 1
            repair_failure_count += (
                _int_value(event_summary.get("self_correction_quality_failure_count"))
                or 0
            )
            invalid_plan_count += error_codes.count("self_correction_invalid_plan")
            text_only_question_count += (
                _int_value(event_summary.get("server_ask_question_text_only_count"))
                or 0
            )
        summary[case_id] = {
            "run_count": run_count,
            "execution_failure_observation_count": execution_failure_count,
            "plan_created_count": plan_count,
            "plan_rate": plan_count / run_count if run_count else None,
            "error_code_counts": error_code_counts,
            "self_correction_invalid_plan_count": invalid_plan_count,
            "self_correction_quality_failure_count": repair_failure_count,
            "server_ask_question_text_only_count": text_only_question_count,
            "assumptions": assumptions,
        }
    return summary


def _suite_outcome_summary(results: list[JsonObject]) -> JsonObject:
    counts: dict[str, int] = {}
    by_cohort: dict[str, dict[str, int]] = {}
    for result in results:
        outcome_class = result.get("outcome_class")
        if not isinstance(outcome_class, str) or not outcome_class:
            outcome_class = "unclassified"
        counts[outcome_class] = counts.get(outcome_class, 0) + 1
        for cohort in _string_list(result.get("cohorts")):
            cohort_counts = by_cohort.setdefault(cohort, {})
            cohort_counts[outcome_class] = cohort_counts.get(outcome_class, 0) + 1
    return {
        "counts": dict(sorted(counts.items())),
        "by_cohort": {
            cohort: dict(sorted(cohort_counts.items()))
            for cohort, cohort_counts in sorted(by_cohort.items())
        },
        "conformance": _suite_conformance_summary(results),
    }


def _suite_conformance_summary(results: list[JsonObject]) -> JsonObject:
    """Cross-tab proposal mechanics against authored-rubric conformance.

    `outcome_class` says whether a plan was produced and how many repairs it
    cost; it says nothing about whether the plan satisfies the case. Reading
    first-pass as a quality score overstated the product for a full day of
    work (2026-08-06), so the summary now publishes both together, plus the
    failed checks ranked by how many unique cases they block.
    """

    matrix: dict[str, dict[str, int]] = {}
    # Case ids, not observation counts: with repetitions one case would
    # otherwise contribute once per repetition to a "unique cases" figure.
    failed_check_case_ids: dict[str, set[str]] = {}
    verdicts: dict[str, int] = {}
    for index, result in enumerate(results):
        case_id = result.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            case_id = f"__row_{index}"
        outcome_class = result.get("outcome_class")
        if not isinstance(outcome_class, str) or not outcome_class:
            outcome_class = "unclassified"
        verdict = result.get("expectation_verdict")
        if not isinstance(verdict, str) or not verdict:
            verdict = "unknown"
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
        row = matrix.setdefault(outcome_class, {})
        row[verdict] = row.get(verdict, 0) + 1
        for check in result.get("failed_checks") or []:
            if not isinstance(check, Mapping):
                continue
            name = check.get("name")
            if isinstance(name, str) and name:
                failed_check_case_ids.setdefault(name, set()).add(case_id)
    evaluated = verdicts.get("pass", 0) + verdicts.get("fail", 0)
    return {
        "expectation_verdict_counts": dict(sorted(verdicts.items())),
        "conformance_rate": (
            round(verdicts.get("pass", 0) / evaluated, 4) if evaluated else None
        ),
        "outcome_by_expectation": {
            outcome: dict(sorted(row.items()))
            for outcome, row in sorted(matrix.items())
        },
        "failed_checks_by_unique_cases": dict(
            sorted(
                ((name, len(ids)) for name, ids in failed_check_case_ids.items()),
                key=lambda item: (-item[1], item[0]),
            )
        ),
    }


def _suite_observation_summary(results: list[JsonObject]) -> JsonObject:
    status_counts: dict[str, int] = {}
    verdict_counts: dict[str, int] = {}
    for result in results:
        status = result.get("observation_status")
        if not isinstance(status, str) or not status:
            status = "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        verdict = result.get("expectation_verdict")
        if not isinstance(verdict, str) or not verdict:
            verdict = "unknown"
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
    return {
        "status_counts": dict(sorted(status_counts.items())),
        "verdict_counts": dict(sorted(verdict_counts.items())),
    }


def _observation_key(value: Mapping[str, object]) -> tuple[str, int] | None:
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


def _observation_key_payload(key: tuple[str, int]) -> JsonObject:
    return {"case_id": key[0], "repetition": key[1]}


def _suite_receipt_integrity(
    *,
    expected_observations: list[JsonObject],
    results: list[JsonObject],
    suite_dir: Path,
) -> JsonObject:
    expected_by_key: dict[tuple[str, int], str] = {}
    invalid_expected_keys: list[JsonObject] = []
    for expected in expected_observations:
        key = _observation_key(expected)
        contract_sha256 = expected.get("case_contract_sha256")
        if key is None or not _is_sha256(contract_sha256) or key in expected_by_key:
            invalid_expected_keys.append(dict(expected))
            continue
        expected_by_key[key] = str(contract_sha256)

    actual_counts: dict[tuple[str, int], int] = {}
    actual_results: dict[tuple[str, int], JsonObject] = {}
    invalid_actual_keys: list[JsonObject] = []
    for result in results:
        key = _observation_key(result)
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
            case_contract_mismatches.append(_observation_key_payload(key))
        bundle_file = result.get("bundle_file")
        bundle_sha256 = result.get("bundle_sha256")
        if (
            not isinstance(bundle_file, str)
            or not bundle_file
            or Path(bundle_file).is_absolute()
            or Path(bundle_file).name != bundle_file
        ):
            invalid_bundle_references.append(
                {**_observation_key_payload(key), "reason": "invalid_relative_path"}
            )
            continue
        if not _is_sha256(bundle_sha256):
            invalid_bundle_references.append(
                {**_observation_key_payload(key), "reason": "invalid_sha256"}
            )
            continue
        bundle_path = suite_dir / bundle_file
        if not bundle_path.is_file():
            invalid_bundle_references.append(
                {**_observation_key_payload(key), "reason": "missing_bundle"}
            )
            continue
        if hashlib.sha256(bundle_path.read_bytes()).hexdigest() != bundle_sha256:
            invalid_bundle_references.append(
                {**_observation_key_payload(key), "reason": "sha256_mismatch"}
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
            _observation_key_payload(key) for key in missing_keys
        ],
        "unexpected_observation_keys": [
            _observation_key_payload(key) for key in unexpected_keys
        ],
        "duplicate_observation_keys": [
            _observation_key_payload(key) for key in duplicate_keys
        ],
        "invalid_expected_observation_keys": invalid_expected_keys,
        "invalid_actual_observation_keys": invalid_actual_keys,
        "case_contract_mismatches": case_contract_mismatches,
        "invalid_bundle_references": invalid_bundle_references,
    }


def _verified_suite_receipt_membership(
    *,
    suite_summary_path: Path,
    bundle_path: Path,
    bundle: Mapping[str, object],
    bundle_sha256: str,
) -> JsonObject:
    try:
        summary_bytes = suite_summary_path.read_bytes()
        summary = json.loads(summary_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"invalid suite receipt {suite_summary_path}: {error}"
        ) from error
    if not isinstance(summary, Mapping):
        raise ValueError(f"{suite_summary_path} did not contain a suite receipt")
    receipt_integrity = summary.get("receipt_integrity")
    if (
        not isinstance(receipt_integrity, Mapping)
        or receipt_integrity.get("status") != "complete"
    ):
        raise ValueError(f"{suite_summary_path} is not a complete suite receipt")
    if bundle_path.resolve().parent != suite_summary_path.resolve().parent:
        raise ValueError(f"{bundle_path} is not stored beside {suite_summary_path}")
    case = bundle.get("case")
    case_id = _optional_string(case, "id") if isinstance(case, Mapping) else None
    repetition = bundle.get("repetition")
    results = summary.get("results")
    matching_results = (
        [
            result
            for result in results
            if isinstance(result, Mapping)
            and result.get("case_id") == case_id
            and result.get("repetition") == repetition
            and result.get("bundle_file") == bundle_path.name
        ]
        if isinstance(results, list)
        else []
    )
    if len(matching_results) != 1:
        raise ValueError(f"{bundle_path} has no unique suite receipt membership")
    result = matching_results[0]
    if result.get("bundle_sha256") != bundle_sha256 or result.get(
        "case_contract_sha256"
    ) != bundle.get("case_contract_sha256"):
        raise ValueError(f"{bundle_path} does not match its suite receipt digest")
    return {
        "source_authenticity": "suite_receipt_verified",
        "suite_summary_file": suite_summary_path.name,
        "suite_summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
    }


def _reanalyze_bundles(
    *,
    bundle_paths: list[Path],
    output_dir: Path,
    expected_overrides_by_case_id: Mapping[str, Mapping[str, Any]] | None = None,
    suite_summary_path: Path | None = None,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)
    failures = 0
    expected_overrides_by_case_id = expected_overrides_by_case_id or {}
    for bundle_path in bundle_paths:
        try:
            source_bytes = bundle_path.read_bytes()
            bundle = _validated_reanalysis_bundle(
                bundle_path,
                json.loads(source_bytes.decode("utf-8")),
            )
            source_bundle_sha256 = hashlib.sha256(source_bytes).hexdigest()
            source_authenticity = (
                _verified_suite_receipt_membership(
                    suite_summary_path=suite_summary_path,
                    bundle_path=bundle_path,
                    bundle=bundle,
                    bundle_sha256=source_bundle_sha256,
                )
                if suite_summary_path is not None
                else {"source_authenticity": "unverified_standalone"}
            )
            case = bundle.get("case")
            case_id = (
                _optional_string(case, "id") if isinstance(case, Mapping) else None
            )
            expected = (
                dict(expected_overrides_by_case_id[case_id])
                if case_id is not None and case_id in expected_overrides_by_case_id
                else (
                    case.get("expected")
                    if isinstance(case, Mapping)
                    and isinstance(case.get("expected"), Mapping)
                    else {}
                )
            )
            plan = bundle.get("plan")
            plan = plan if isinstance(plan, dict) else None
            summary = _summarize_plan(plan)
            event_summary = _interaction_event_summary(
                bundle.get("interactions")
                if isinstance(bundle.get("interactions"), list)
                else []
            )
            journey = _journey_summary(
                bundle.get("interactions")
                if isinstance(bundle.get("interactions"), list)
                else [],
                expected=expected,
                interaction_limit=MAX_INTERACTIONS_PER_CASE,
            )
            report = _quality_report(
                plan=plan,
                summary=summary,
                expected=expected,
                event_summary=event_summary,
                journey=journey,
                classifier_diagnostics=(
                    bundle.get("classifier_diagnostics")
                    if isinstance(bundle.get("classifier_diagnostics"), Mapping)
                    else None
                ),
                attached_file_ids=tuple(
                    _string_list(case.get("file_ids"))
                    if isinstance(case, Mapping)
                    else ()
                ),
                applied_flow=(
                    bundle["applied_flow_evidence"].get("flow")
                    if isinstance(bundle.get("applied_flow_evidence"), Mapping)
                    and isinstance(bundle["applied_flow_evidence"].get("flow"), Mapping)
                    else None
                ),
                runtime_evidence=(
                    bundle.get("runtime_evidence")
                    if isinstance(bundle.get("runtime_evidence"), Mapping)
                    else None
                ),
            )
            provenance = bundle.get("live_execution_provenance")
            if not isinstance(provenance, Mapping):
                raise ValueError(f"{bundle_path} has no live execution provenance")
            report = _quality_report_with_live_provenance(
                report,
                provenance=provenance,
                expected=expected,
            )
            refreshed = {
                **{
                    key: value
                    for key, value in bundle.items()
                    if key != "evidence_report"
                },
                "artifact_mode": "reanalysis",
                "reanalyzed_at": time.strftime("%Y%m%dT%H%M%S"),
                "reanalysis_provenance": {
                    "source_bundle_sha256": source_bundle_sha256,
                    **source_authenticity,
                    "reanalyzer_source_revision": _git_output("rev-parse", "HEAD"),
                    "reanalyzer_harness_sha256": hashlib.sha256(
                        Path(__file__).read_bytes()
                    ).hexdigest(),
                    "expectations_sha256": _canonical_sha256(expected),
                },
                "plan_summary": summary,
                "event_summary": event_summary,
                "journey": journey,
                "failure_summary": _failure_summary(event_summary),
                "runtime_metrics": _runtime_metrics_from_quality_report(report),
                "quality_report": report,
            }
            output_path = _write_reanalysis_bundle(output_dir, bundle_path, refreshed)
            _print_summary(summary, output_path)
            for warning in report.get("warnings", []):
                print(f"  warning: {warning}")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            failures += 1
            print(f"reanalyze failed for {bundle_path}: {error}", file=sys.stderr)
    return 1 if failures else 0


def _validated_reanalysis_bundle(path: Path, value: object) -> JsonObject:
    if not isinstance(value, dict):
        raise ValueError(f"{path} did not contain a JSON object.")
    if value.get("artifact_schema_version") != SUPPORTED_RECEIPT_ARTIFACT_VERSION:
        raise ValueError(
            f"{path} is not a {SUPPORTED_RECEIPT_ARTIFACT_VERSION} artifact."
        )
    if value.get("artifact_mode") != "live_execution":
        raise ValueError(
            f"{path} is not a completed live-execution observation bundle."
        )
    case = value.get("case")
    case_identity = value.get("case_identity")
    if not isinstance(case, Mapping) or not isinstance(case_identity, Mapping):
        raise ValueError(f"{path} has no complete case identity.")
    case_id = _optional_string(case, "id")
    if case_id is None or case_id != _optional_string(case_identity, "id"):
        raise ValueError(f"{path} has inconsistent case identity.")
    if not isinstance(case.get("expected"), Mapping):
        raise ValueError(f"{path} has no case expectation contract.")
    if not isinstance(value.get("case_contract"), Mapping) or not _is_sha256(
        value.get("case_contract_sha256")
    ):
        raise ValueError(f"{path} has no valid case contract fingerprint.")
    repetition = value.get("repetition")
    if (
        not isinstance(repetition, int)
        or isinstance(repetition, bool)
        or repetition < 1
    ):
        raise ValueError(f"{path} has no valid repetition identity.")
    interactions = value.get("interactions")
    if (
        not isinstance(interactions, list)
        or not interactions
        or not all(isinstance(interaction, Mapping) for interaction in interactions)
    ):
        raise ValueError(f"{path} has no complete interaction evidence.")
    if value.get("plan") is not None and not isinstance(value.get("plan"), dict):
        raise ValueError(f"{path} has an invalid plan payload.")
    for key in (
        "live_execution_provenance",
        "observation_input_identity",
        "classifier_diagnostics",
        "quality_report",
    ):
        if not isinstance(value.get(key), Mapping):
            raise ValueError(f"{path} has no valid {key} evidence.")
    classifier_runs = value["classifier_diagnostics"].get("classifier_runs")
    if (
        not isinstance(classifier_runs, list)
        or not classifier_runs
        or not all(isinstance(run, Mapping) for run in classifier_runs)
    ):
        raise ValueError(f"{path} has incomplete classifier diagnostics.")
    source_quality_report = value["quality_report"]
    checks = source_quality_report.get("checks")
    warnings = source_quality_report.get("warnings")
    metrics = source_quality_report.get("metrics")
    if (
        not isinstance(checks, list)
        or not checks
        or not all(
            isinstance(check, Mapping)
            and isinstance(check.get("name"), str)
            and isinstance(check.get("passed"), bool)
            for check in checks
        )
        or not isinstance(warnings, list)
        or not isinstance(metrics, Mapping)
    ):
        raise ValueError(f"{path} has incomplete source quality evidence.")
    evidence_report = _observation_evidence_report(value)
    if evidence_report.get("valid") is not True:
        failed_names = _failed_check_names(
            {"failed_checks": evidence_report.get("failed_checks")}
        )
        raise ValueError(
            f"{path} has internally inconsistent live evidence: "
            + ", ".join(failed_names or ["unknown evidence check"])
        )
    return value


def _write_reanalysis_bundle(
    output_dir: Path,
    source_path: Path,
    bundle: JsonObject,
) -> Path:
    reanalyzed_at = str(bundle.get("reanalyzed_at") or time.strftime("%Y%m%dT%H%M%S"))
    path = output_dir / f"{source_path.stem}-reanalyzed-{reanalyzed_at}.json"
    _write_json_exclusive(path, bundle)
    return path


def _create_session(
    *,
    config: ApiConfig,
    space_id: str,
    force_new: bool,
) -> JsonObject:
    return _request_json(
        config=config,
        method="POST",
        path="/flows/ai-builder/sessions",
        payload={
            "target_kind": "create",
            "space_id": space_id,
            "force_new": force_new,
        },
    )


def _send_message_stream(
    *,
    config: ApiConfig,
    session_id: str,
    payload: JsonObject,
) -> Iterator[JsonObject]:
    request = _request(
        config=config,
        method="POST",
        path=f"/flows/ai-builder/sessions/{session_id}/messages",
        payload={key: value for key, value in payload.items() if value is not None},
        accept="text/event-stream",
    )
    with urlopen(request, timeout=config.timeout_seconds) as response:
        yield from _iter_sse_events(response)


def _request_json(
    *,
    config: ApiConfig,
    method: str,
    path: str,
    payload: JsonObject | None = None,
) -> JsonObject:
    request = _request(
        config=config,
        method=method,
        path=path,
        payload=payload,
        accept="application/json",
    )
    with urlopen(request, timeout=config.timeout_seconds) as response:
        body = response.read().decode("utf-8")
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected object response from {path}.")
    return parsed


def _request(
    *,
    config: ApiConfig,
    method: str,
    path: str,
    payload: JsonObject | None,
    accept: str,
) -> Request:
    url = f"{config.base_url}{path}"
    body = None
    headers = {
        "Accept": accept,
        "X-API-Key": config.api_key,
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    return Request(url, data=body, headers=headers, method=method)


def _iter_sse_events(response: Any) -> Iterator[JsonObject]:
    current_event = "message"
    data_lines: list[str] = []
    for raw_line in response:
        line = raw_line.decode("utf-8").rstrip("\r\n")
        if line == "":
            if data_lines:
                yield _decode_sse_event(current_event, data_lines)
            current_event = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            current_event = line.removeprefix("event:").strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").lstrip())
    if data_lines:
        yield _decode_sse_event(current_event, data_lines)


def _decode_sse_event(event: str, data_lines: list[str]) -> JsonObject:
    raw_data = "\n".join(data_lines)
    if raw_data:
        try:
            data: Any = json.loads(raw_data)
        except json.JSONDecodeError:
            data = raw_data
    else:
        data = ""
    result: JsonObject = {"event": event, "data": data}
    if event in {"status", "question", "requirements_summary", "plan", "error"}:
        print(f"event: {event}")
    return result


def _last_plan_id(events: list[JsonObject]) -> str | None:
    for event in reversed(events):
        if event.get("event") != "plan":
            continue
        data = event.get("data")
        if isinstance(data, Mapping):
            plan_id = data.get("plan_id")
            if isinstance(plan_id, str) and plan_id:
                return plan_id
    return None


def _summarize_plan(plan: JsonObject | None) -> JsonObject:
    if plan is None:
        return {"has_plan": False}
    spec = _plan_spec(plan)
    steps = spec.get("steps") if isinstance(spec, Mapping) else None
    if not isinstance(steps, list):
        return {"has_plan": True, "has_steps": False}

    form_fields = spec.get("form_fields")
    form_field_names: list[str] = []
    if isinstance(form_fields, list):
        form_field_names = [
            str(field.get("name"))
            for field in form_fields
            if isinstance(field, Mapping) and isinstance(field.get("name"), str)
        ]
    step_summaries: list[JsonObject] = []
    for index, raw_step in enumerate(steps, start=1):
        if not isinstance(raw_step, Mapping):
            continue
        bindings = raw_step.get("input_bindings")
        refs = _source_refs(bindings)
        assistant_spec = raw_step.get("assistant_spec")
        instructions = (
            assistant_spec.get("instructions")
            if isinstance(assistant_spec, Mapping)
            else None
        )
        step_summaries.append(
            {
                "order": index,
                "plan_step_ref": raw_step.get("plan_step_ref"),
                "name": raw_step.get("name"),
                "input_source": raw_step.get("input_source"),
                "input_type": raw_step.get("input_type"),
                "output_type": raw_step.get("output_type"),
                "output_mode": raw_step.get("output_mode"),
                "review_policy": (
                    dict(raw_step["review_policy"])
                    if isinstance(raw_step.get("review_policy"), Mapping)
                    else None
                ),
                "review_mode": (
                    raw_step["review_policy"].get("mode")
                    if isinstance(raw_step.get("review_policy"), Mapping)
                    else None
                ),
                "has_question": _has_question(bindings),
                "source_ref_count": len(refs),
                "source_refs": refs,
                "duplicate_source_ref_expressions": _duplicate_source_ref_expressions(
                    refs
                ),
                "implicit_previous_step": (
                    raw_step.get("input_source") == "previous_step" and bindings is None
                ),
                "output_contract_properties": _schema_property_names(
                    raw_step.get("output_contract")
                ),
                "output_contract_nested_properties": _schema_nested_property_names(
                    raw_step.get("output_contract")
                ),
                "output_contract_leaf_properties": _schema_leaf_property_names(
                    raw_step.get("output_contract")
                ),
                "input_contract_properties": _schema_property_names(
                    raw_step.get("input_contract")
                ),
                "instruction_bytes": (
                    len(instructions.encode("utf-8"))
                    if isinstance(instructions, str)
                    else 0
                ),
                "instruction_excerpt": (
                    _collapse_whitespace(instructions)[:360]
                    if isinstance(instructions, str)
                    else ""
                ),
                "instruction_has_template": (
                    "{{" in instructions or "}}" in instructions
                    if isinstance(instructions, str)
                    else False
                ),
                "has_assistant_spec": isinstance(assistant_spec, Mapping),
            }
        )
    terminal_step = step_summaries[-1] if step_summaries else {}
    return {
        "has_plan": True,
        "flow_name": spec.get("flow_name"),
        "form_field_names": form_field_names,
        "step_count": len(step_summaries),
        "json_step_count": sum(
            1 for step in step_summaries if step["output_type"] == "json"
        ),
        "all_previous_step_count": sum(
            1 for step in step_summaries if step["input_source"] == "all_previous_steps"
        ),
        "question_binding_steps": sum(
            1 for step in step_summaries if step["has_question"]
        ),
        "source_ref_steps": sum(
            1 for step in step_summaries if step["source_ref_count"]
        ),
        "implicit_previous_step_steps": sum(
            1 for step in step_summaries if step["implicit_previous_step"]
        ),
        "terminal_output_type": terminal_step.get("output_type"),
        "terminal_output_mode": terminal_step.get("output_mode"),
        "duplicate_source_ref_steps": [
            step["order"]
            for step in step_summaries
            if step["duplicate_source_ref_expressions"]
        ],
        "instruction_template_steps": [
            step["order"] for step in step_summaries if step["instruction_has_template"]
        ],
        "steps": step_summaries,
    }


def _plan_spec(plan: JsonObject) -> JsonObject:
    proposal = plan.get("proposal")
    if not isinstance(proposal, Mapping):
        return {}
    spec = proposal.get("spec")
    return dict(spec) if isinstance(spec, Mapping) else {}


def _plan_contract(
    plan: JsonObject | None,
    contract_key: str,
) -> tuple[int, JsonObject] | None:
    if plan is None:
        return None
    steps = _plan_spec(plan).get("steps")
    if not isinstance(steps, list):
        return None
    return _directional_contract(steps, contract_key)


def _applied_flow_contract(
    flow: Mapping[str, object] | None,
    contract_key: str,
) -> tuple[int, JsonObject] | None:
    if not isinstance(flow, Mapping):
        return None
    raw_steps = flow.get("steps")
    if not isinstance(raw_steps, list):
        return None
    steps = [step for step in raw_steps if isinstance(step, Mapping)]
    steps.sort(key=lambda step: _int_value(step.get("step_order")) or 0)
    return _directional_contract(steps, contract_key)


def _directional_contract(
    steps: list[object] | list[Mapping[str, object]],
    contract_key: str,
) -> tuple[int, JsonObject] | None:
    indexed_steps = [
        (step_index, step)
        for step_index, step in enumerate(steps, start=1)
        if isinstance(step, Mapping)
    ]
    if contract_key == "input_contract":
        candidates = [
            (step_index, step)
            for step_index, step in indexed_steps
            if step.get("input_source") == "flow_input"
            and step.get("input_type") == "json"
        ]
    else:
        candidates = [
            (step_index, step)
            for step_index, step in indexed_steps
            if step.get("output_type") == "json"
        ]
        candidates.reverse()
    if not candidates:
        return None
    step_index, step = candidates[0]
    contract = step.get(contract_key)
    return (step_index, dict(contract)) if isinstance(contract, Mapping) else None


def _json_subset_matches(
    expected: object,
    actual: object,
    *,
    schema_keyword: str | None = None,
) -> bool:
    if schema_keyword == "type":
        return _json_schema_types(expected) == _json_schema_types(actual)
    if schema_keyword == "required":
        return (
            isinstance(expected, list)
            and isinstance(actual, list)
            and set(_string_list(expected)).issubset(_string_list(actual))
        )
    if schema_keyword == "additionalProperties" and expected is True:
        return actual is not False
    if isinstance(expected, Mapping):
        return isinstance(actual, Mapping) and all(
            (
                key == "additionalProperties"
                and value is True
                and _json_subset_matches(
                    value,
                    actual.get(key),
                    schema_keyword=key,
                )
            )
            or (
                key in actual
                and _json_subset_matches(
                    value,
                    actual[key],
                    schema_keyword=key,
                )
            )
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and all(
            any(
                _json_subset_matches(expected_item, actual_item)
                for actual_item in actual
            )
            for expected_item in expected
        )
    return expected == actual


def _json_schema_types(value: object) -> frozenset[str] | None:
    if isinstance(value, str):
        return frozenset({value})
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return frozenset(value)
    return None


def _source_refs(input_bindings: object) -> list[JsonObject]:
    if not isinstance(input_bindings, Mapping):
        return []
    refs = input_bindings.get("source_refs")
    if not isinstance(refs, list):
        return []
    return [dict(ref) for ref in refs if isinstance(ref, Mapping)]


def _source_ref_expression(ref: Mapping[str, Any]) -> str:
    step_ref = ref.get("step_ref")
    output = ref.get("output")
    field_path = ref.get("field_path")
    if not isinstance(step_ref, str) or not isinstance(output, str):
        return json.dumps(ref, ensure_ascii=False, sort_keys=True)
    path = f"output.{output}"
    if isinstance(field_path, str) and field_path.strip():
        path = f"{path}.{field_path.strip()}"
    return f"{step_ref}.{path}"


def _duplicate_source_ref_expressions(refs: list[JsonObject]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for ref in refs:
        expression = _source_ref_expression(ref)
        if expression in seen and expression not in duplicates:
            duplicates.append(expression)
        seen.add(expression)
    return duplicates


def _has_question(input_bindings: object) -> bool:
    return (
        isinstance(input_bindings, Mapping)
        and isinstance(input_bindings.get("question"), str)
        and bool(input_bindings.get("question", "").strip())
    )


def _schema_property_names(schema: object) -> list[str]:
    if not isinstance(schema, Mapping):
        return []
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return []
    return [str(name) for name in properties]


def _schema_leaf_property_names(schema: object) -> list[str]:
    names: list[str] = []
    _collect_schema_leaf_names(schema, names)
    return names


def _schema_nested_property_names(schema: object) -> list[str]:
    names: list[str] = []
    _collect_schema_property_names(schema, names)
    return list(dict.fromkeys(names))


def _collect_schema_property_names(schema: object, names: list[str]) -> None:
    if not isinstance(schema, Mapping):
        return
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        for name, child in properties.items():
            names.append(str(name))
            _collect_schema_property_names(child, names)
        return
    items = schema.get("items")
    if isinstance(items, Mapping):
        _collect_schema_property_names(items, names)


def _collect_schema_leaf_names(schema: object, names: list[str]) -> None:
    if not isinstance(schema, Mapping):
        return
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        for name, child in properties.items():
            if isinstance(child, Mapping) and (
                isinstance(child.get("properties"), Mapping)
                or isinstance(child.get("items"), Mapping)
            ):
                before = len(names)
                _collect_schema_leaf_names(child, names)
                if len(names) == before:
                    names.append(str(name))
            else:
                names.append(str(name))
        return
    items = schema.get("items")
    if isinstance(items, Mapping):
        _collect_schema_leaf_names(items, names)


def _interaction_event_summary(interactions: object) -> JsonObject:
    if not isinstance(interactions, list):
        return {}

    event_counts: dict[str, int] = {}
    question_event_ids: list[str] = []
    error_codes: list[str] = []
    error_details: list[JsonObject] = []
    failure_codes: list[str] = []
    critic_issue_ids: list[str] = []
    repair_feedback_texts: list[str] = []
    question_like_text_events: list[str] = []
    assumptions: list[str] = []
    server_ask_question_text_only_count = 0
    self_correction_quality_failure_count = 0

    for interaction in interactions:
        if not isinstance(interaction, Mapping):
            continue
        saw_question_event = False
        saw_server_ask_question_usage = False
        events = interaction.get("events")
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, Mapping):
                continue
            event_name = event.get("event")
            if isinstance(event_name, str):
                event_counts[event_name] = event_counts.get(event_name, 0) + 1
            data = event.get("data")
            if event_name == "question" and isinstance(data, Mapping):
                saw_question_event = True
                question_id = data.get("question_id")
                if isinstance(question_id, str) and question_id:
                    question_event_ids.append(question_id)
            elif event_name == "requirements_summary" and isinstance(data, Mapping):
                _extend_unique_strings(
                    assumptions, _clean_strings(data.get("assumptions"))
                )
            elif event_name == "plan" and isinstance(data, Mapping):
                proposal = data.get("proposal")
                if isinstance(proposal, Mapping):
                    _extend_unique_strings(
                        assumptions, _clean_strings(proposal.get("assumptions"))
                    )
            elif event_name == "text":
                text = _event_text(data)
                if text and _looks_like_question_text(text):
                    question_like_text_events.append(text[:400])
            elif event_name == "error" and isinstance(data, Mapping):
                code = data.get("code")
                if isinstance(code, str) and code:
                    error_codes.append(code)
                    if code == "self_correction_quality_failure":
                        self_correction_quality_failure_count += 1
                error_details.append(_error_event_detail(data))
                _extend_failure_observability(
                    data,
                    failure_codes=failure_codes,
                    critic_issue_ids=critic_issue_ids,
                    repair_feedback_texts=repair_feedback_texts,
                )
            elif event_name == "usage" and isinstance(data, Mapping):
                if data.get("last_outcome_kind") == "server_ask_question":
                    saw_server_ask_question_usage = True
        if saw_server_ask_question_usage and not saw_question_event:
            server_ask_question_text_only_count += 1

    return {
        "event_counts": event_counts,
        "question_event_count": len(question_event_ids),
        "question_event_ids": question_event_ids,
        "unique_question_event_ids": list(dict.fromkeys(question_event_ids)),
        "repeated_question_event_count": (
            len(question_event_ids) - len(set(question_event_ids))
        ),
        "question_like_text_event_count": len(question_like_text_events),
        "question_like_text_events": question_like_text_events[:5],
        "server_ask_question_text_only_count": server_ask_question_text_only_count,
        "assumptions": assumptions,
        "error_codes": error_codes,
        "self_correction_quality_failure_count": (
            self_correction_quality_failure_count
        ),
        "error_details": error_details,
        "failure_codes": failure_codes,
        "critic_issue_ids": critic_issue_ids,
        "repair_feedback_texts": repair_feedback_texts[:5],
    }


def _journey_summary(
    interactions: object,
    *,
    expected: Mapping[str, Any],
    interaction_limit: int,
) -> JsonObject:
    if not isinstance(interactions, list):
        interactions = []
    preferred_ids = set(_string_list(expected.get("preferred_question_event_ids")))
    allowed_ids = set(_string_list(expected.get("allowed_question_event_ids")))
    forbidden_ids = set(_string_list(expected.get("forbidden_question_event_ids")))
    relevance_rubric_declared = any(
        key in expected
        for key in (
            "preferred_question_event_ids",
            "allowed_question_event_ids",
            "forbidden_question_event_ids",
        )
    )
    occurrences: list[tuple[int, JsonObject]] = []
    for interaction_index, interaction in enumerate(interactions):
        if not isinstance(interaction, Mapping):
            continue
        events = interaction.get("events")
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, Mapping) or event.get("event") != "question":
                continue
            data = event.get("data")
            if isinstance(data, Mapping):
                occurrences.append((interaction_index, dict(data)))

    question_ids = [
        question_id
        for _interaction_index, question in occurrences
        for question_id in [_optional_string(question, "question_id")]
        if question_id is not None
    ]
    questions: list[JsonObject] = []
    for ordinal, (interaction_index, question) in enumerate(occurrences, start=1):
        question_id = _optional_string(question, "question_id")
        if question_id is None:
            continue
        relevance = _question_relevance(
            question_id,
            preferred_ids=preferred_ids,
            allowed_ids=allowed_ids,
            forbidden_ids=forbidden_ids,
            rubric_declared=relevance_rubric_declared,
        )
        answer_interaction = (
            interactions[interaction_index + 1]
            if interaction_index + 1 < len(interactions)
            and isinstance(interactions[interaction_index + 1], Mapping)
            else None
        )
        answer = (
            answer_interaction.get("question_answer")
            if isinstance(answer_interaction, Mapping)
            and isinstance(answer_interaction.get("question_answer"), Mapping)
            and answer_interaction["question_answer"].get("question_id") == question_id
            else None
        )
        reopened = answer is not None and any(
            later_question_id == question_id
            for later_question_id in question_ids[ordinal:]
        )
        if answer is None:
            resolution = (
                "indeterminate"
                if len(interactions) >= interaction_limit
                else "unanswered"
            )
        else:
            resolution = "reopened" if reopened else "resolved"
        selected_option_ids = (
            _string_list(answer.get("selected_option_ids"))
            if isinstance(answer, Mapping)
            else []
        )
        custom_value = (
            _optional_string(answer, "custom_value")
            if isinstance(answer, Mapping)
            else None
        )
        next_question = (
            _latest_structured_question(answer_interaction)
            if isinstance(answer_interaction, Mapping)
            else None
        )
        if answer is None or not isinstance(answer_interaction, Mapping):
            next_outcome = None
        elif answer_interaction.get("plan_id") is not None:
            next_outcome = "plan_created"
        elif next_question is not None:
            next_outcome = "next_question"
        elif _latest_requirements_summary(answer_interaction) is not None:
            next_outcome = "requirements_summary"
        elif _interaction_has_error(answer_interaction):
            next_outcome = "error"
        else:
            next_outcome = "no_terminal_event"
        questions.append(
            {
                "ordinal": ordinal,
                "turn": interaction_index + 1,
                "question_id": question_id,
                "question": _optional_string(question, "question"),
                "option_ids": [
                    option_id
                    for option in _mapping_list(question.get("options"))
                    for option_id in [_optional_string(option, "id")]
                    if option_id is not None
                ],
                "selection_mode": _optional_string(question, "selection_mode"),
                "allow_custom": question.get("allow_custom") is True,
                "relevance": relevance,
                "answerable": answer is not None,
                "answer_turn": interaction_index + 2 if answer is not None else None,
                "answer_source": (
                    answer_interaction.get("configured_answer_source")
                    if isinstance(answer_interaction, Mapping)
                    else None
                ),
                "answer_mode": (
                    "custom"
                    if custom_value is not None
                    else ("option" if selected_option_ids else None)
                ),
                "selected_option_ids": selected_option_ids,
                "custom_value": custom_value,
                "next_outcome": next_outcome,
                "next_question_id": (
                    _optional_string(next_question, "question_id")
                    if next_question is not None
                    else None
                ),
                "resolution": resolution,
            }
        )

    has_plan = any(
        isinstance(interaction, Mapping) and interaction.get("plan_id") is not None
        for interaction in interactions
    )
    event_summary = _interaction_event_summary(interactions)
    if has_plan:
        termination = "plan_created"
    elif _string_list(event_summary.get("error_codes")):
        termination = "turn_error"
    elif questions and questions[-1]["resolution"] == "unanswered":
        termination = "unanswered_question"
    elif len(interactions) >= interaction_limit:
        termination = "interaction_limit"
    else:
        termination = "requirements_unconfirmed"

    telemetry = _latest_telemetry(interactions)
    repair_attempts = _int_value(telemetry.get("repair_attempts_total")) or 0
    parse_repair_attempts = (
        _int_value(telemetry.get("parse_repair_attempts_total")) or 0
    )
    error_codes = _string_list(event_summary.get("error_codes"))
    if not has_plan:
        plan_outcome_kind = "terminal_failure"
    elif repair_attempts or parse_repair_attempts or error_codes:
        plan_outcome_kind = "repaired_success"
    else:
        plan_outcome_kind = "first_pass_success"
    reopened_ids = list(
        dict.fromkeys(
            str(question["question_id"])
            for question in questions
            if question.get("resolution") == "reopened"
        )
    )
    if has_plan:
        if repair_attempts or parse_repair_attempts:
            outcome_class = "plan_repaired"
        elif error_codes:
            outcome_class = "plan_with_error"
        else:
            outcome_class = "plan_first_pass"
    elif "session_turn_provider_outcome_unknown" in error_codes:
        outcome_class = "provider_outcome_unknown"
    elif error_codes:
        outcome_class = "builder_error"
    elif (
        termination == "unanswered_question"
        and expected.get("allow_question_instead_of_plan") is True
        and questions
        and not reopened_ids
        and all(
            question.get("relevance") in {"preferred", "allowed"}
            for question in questions
        )
    ):
        outcome_class = "clarification_stop_intended"
    elif termination == "unanswered_question":
        outcome_class = "stalled_unanswered_question"
    elif termination == "interaction_limit":
        outcome_class = "interaction_limit_reached"
    else:
        outcome_class = "requirements_unconfirmed"
    resolved_count = sum(
        question.get("resolution") == "resolved" for question in questions
    )
    return {
        "termination": termination,
        "outcome_class": outcome_class,
        "turn_count": len(interactions),
        "question_event_count": len(questions),
        "question_event_ids": [question["question_id"] for question in questions],
        "unique_question_event_ids": list(
            dict.fromkeys(str(question["question_id"]) for question in questions)
        ),
        "reopened_question_ids": reopened_ids,
        "reopened_question_count": len(reopened_ids),
        "answerable_question_count": sum(
            question.get("answerable") is True for question in questions
        ),
        "resolved_question_count": resolved_count,
        "unanswered_question_count": sum(
            question.get("resolution") == "unanswered" for question in questions
        ),
        "indeterminate_question_count": sum(
            question.get("resolution") == "indeterminate" for question in questions
        ),
        "first_question_relevance": (questions[0]["relevance"] if questions else None),
        "question_relevance_counts": {
            relevance: sum(
                question.get("relevance") == relevance for question in questions
            )
            for relevance in (
                "preferred",
                "allowed",
                "forbidden",
                "unclassified",
                "unassessed",
            )
        },
        "questions": questions,
        "plan_outcome": {
            "kind": plan_outcome_kind,
            "repair_attempts": repair_attempts,
            "parse_repair_attempts": parse_repair_attempts,
            "failure_codes": _string_list(event_summary.get("failure_codes")),
        },
    }


def _question_relevance(
    question_id: str,
    *,
    preferred_ids: set[str],
    allowed_ids: set[str],
    forbidden_ids: set[str],
    rubric_declared: bool,
) -> str:
    if not rubric_declared:
        return "unassessed"
    if question_id in preferred_ids:
        return "preferred"
    if question_id in allowed_ids:
        return "allowed"
    if question_id in forbidden_ids:
        return "forbidden"
    return "unclassified"


def _latest_telemetry(interactions: list[object]) -> Mapping[str, object]:
    for interaction in reversed(interactions):
        if not isinstance(interaction, Mapping):
            continue
        session = interaction.get("latest_session")
        if isinstance(session, Mapping) and isinstance(
            session.get("telemetry"), Mapping
        ):
            return session["telemetry"]
    return {}


def _interaction_has_error(interaction: Mapping[str, object]) -> bool:
    events = interaction.get("events")
    return isinstance(events, list) and any(
        isinstance(event, Mapping) and event.get("event") == "error" for event in events
    )


def _error_event_detail(data: Mapping[str, Any]) -> JsonObject:
    detail: JsonObject = {}
    for key in ("code", "message", "phase", "request_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            detail[key] = value
    details = data.get("details")
    if isinstance(details, Mapping):
        detail["details"] = dict(details)
    diagnostic_context = data.get("diagnostic_context")
    if isinstance(diagnostic_context, Mapping):
        detail["diagnostic_context"] = dict(diagnostic_context)
    return detail


def _extend_failure_observability(
    data: Mapping[str, Any],
    *,
    failure_codes: list[str],
    critic_issue_ids: list[str],
    repair_feedback_texts: list[str],
) -> None:
    sources = [data]
    details = data.get("details")
    if isinstance(details, Mapping):
        sources.append(details)
    diagnostic_context = data.get("diagnostic_context")
    if isinstance(diagnostic_context, Mapping):
        sources.append(diagnostic_context)

    for source in sources:
        _extend_unique_strings(
            failure_codes,
            _string_values_from_keys(
                source,
                ("failure_codes", "quality_failure_codes"),
            ),
        )
        _extend_unique_strings(
            critic_issue_ids,
            _string_values_from_keys(source, ("critic_issue_ids",)),
        )
        _extend_unique_strings(
            repair_feedback_texts,
            _string_values_from_keys(
                source,
                ("repair_feedback", "retry_feedback", "feedback"),
            ),
        )


def _failure_summary(event_summary: Mapping[str, Any]) -> JsonObject:
    return {
        "error_codes": _string_list(event_summary.get("error_codes")),
        "failure_codes": _string_list(event_summary.get("failure_codes")),
        "critic_issue_ids": _string_list(event_summary.get("critic_issue_ids")),
        "repair_feedback_texts": _string_list(
            event_summary.get("repair_feedback_texts")
        ),
        "error_details": event_summary.get("error_details")
        if isinstance(event_summary.get("error_details"), list)
        else [],
    }


def _event_text(data: object) -> str:
    if isinstance(data, str):
        return data
    if isinstance(data, Mapping):
        value = data.get("text") or data.get("message")
        if isinstance(value, str):
            return value
    return ""


def _looks_like_question_text(text: str) -> bool:
    folded = text.casefold()
    return "?" in text or folded.startswith(
        (
            "ska ",
            "vilken ",
            "vilket ",
            "vilka ",
            "hur ",
            "what ",
            "which ",
            "how ",
            "should ",
        )
    )


def _mapping_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _classifier_runs(
    diagnostics: Mapping[str, object] | None,
) -> list[Mapping[str, object]]:
    if diagnostics is None:
        return []
    return _mapping_list(diagnostics.get("classifier_runs"))


def _persisted_named_result_names(
    diagnostics: Mapping[str, object] | None,
) -> list[str]:
    names: list[str] = []
    for run in _classifier_runs(diagnostics):
        snapshot = run.get("named_result_evidence")
        if not isinstance(snapshot, Mapping):
            continue
        snapshot = cast(Mapping[str, object], snapshot)
        operation = snapshot.get("operation")
        if operation == "clear":
            names = []
        elif operation == "replace":
            names = [
                name
                for named_result in _mapping_list(snapshot.get("named_results"))
                for name in [named_result.get("name")]
                if isinstance(name, str) and name
            ]
    return names


def _classifier_evidence_contract_is_valid(
    diagnostics: Mapping[str, object] | None,
) -> bool:
    """Validate raw diagnostics through the product-owned response contract."""

    if diagnostics is None:
        return False
    try:
        from eneo.flows.ai_builder.ai_builder_api_models import (
            AIBuilderClassifierDiagnosticsResponse,
        )

        AIBuilderClassifierDiagnosticsResponse.model_validate(diagnostics)
    except (ImportError, ValueError):
        return False
    return True


def _latest_classifier_claim(
    runs: list[Mapping[str, object]],
    *,
    collection_name: str,
    identity_name: str,
    identity_value: str,
) -> tuple[Mapping[str, object], Mapping[str, object]] | None:
    for run in reversed(runs):
        claims = _mapping_list(run.get(collection_name))
        for claim in reversed(claims):
            if claim.get(identity_name) == identity_value:
                return run, claim
    return None


def _classifier_claim_summary(
    run: Mapping[str, object],
    claim: Mapping[str, object],
) -> JsonObject:
    source_kinds_by_id = {
        source_id: source.get("kind")
        for source in _mapping_list(run.get("source_inventory"))
        if (source_id := _optional_string(source, "source_id")) is not None
    }
    evidence = _mapping_list(claim.get("evidence"))
    source_ids = [
        source_id
        for item in evidence
        if (source_id := _optional_string(item, "source_id")) is not None
    ]
    source_kinds = list(
        dict.fromkeys(
            str(source_kinds_by_id[source_id])
            for source_id in source_ids
            if source_id in source_kinds_by_id
        )
    )
    summary: JsonObject = {
        key: claim.get(key)
        for key in (
            "slot_name",
            "value",
            "file_id",
            "role",
            "confidence",
            "evidence_level",
        )
        if claim.get(key) is not None
    }
    summary.update(
        {
            "source_ids": source_ids,
            "source_kinds": source_kinds,
            "evidence_quotes": [
                quote
                for item in evidence
                if (quote := _optional_string(item, "quote")) is not None
            ],
        }
    )
    return summary


def _classifier_claim_matches(
    actual: Mapping[str, object],
    expected: Mapping[str, object],
) -> bool:
    for key in (
        "slot_name",
        "value",
        "file_id",
        "role",
        "confidence",
        "evidence_level",
        "coverage",
    ):
        if key in expected and actual.get(key) != expected.get(key):
            return False
    for key, actual_key in (
        ("confidence_in", "confidence"),
        ("coverage_in", "coverage"),
    ):
        allowed_values = _string_list(expected.get(key))
        if allowed_values and actual.get(actual_key) not in allowed_values:
            return False
    expected_source_kinds = _string_list(expected.get("source_kinds"))
    if expected_source_kinds and set(_string_list(actual.get("source_kinds"))) != set(
        expected_source_kinds
    ):
        return False
    required_source_kinds = set(_string_list(expected.get("required_source_kinds")))
    if required_source_kinds and not required_source_kinds.issubset(
        _string_list(actual.get("source_kinds"))
    ):
        return False
    expected_quotes = _string_list(expected.get("evidence_quotes"))
    if (
        expected_quotes
        and _string_list(actual.get("evidence_quotes")) != expected_quotes
    ):
        return False
    required_quote_fragments = _string_list(expected.get("evidence_contains"))
    actual_quotes = _string_list(actual.get("evidence_quotes"))
    if any(
        not _contains_topic(actual_quotes, fragment)
        for fragment in required_quote_fragments
    ):
        return False
    return True


def _invalid_classifier_evidence_sources(
    runs: list[Mapping[str, object]],
) -> list[str]:
    invalid: list[str] = []
    for run_index, run in enumerate(runs):
        source_ids = {
            source_id
            for source in _mapping_list(run.get("source_inventory"))
            if (source_id := _optional_string(source, "source_id")) is not None
        }
        claims = [
            *_mapping_list(run.get("slots")),
            *_mapping_list(run.get("file_roles")),
        ]
        form_intake = run.get("form_intake")
        if isinstance(form_intake, Mapping):
            claims.append(form_intake)
        for claim_index, claim in enumerate(claims):
            for evidence in _mapping_list(claim.get("evidence")):
                source_id = _optional_string(evidence, "source_id")
                if source_id is None or source_id not in source_ids:
                    invalid.append(f"run:{run_index}:claim:{claim_index}:{source_id}")
    return invalid


def _expected_file_id(
    expected: Mapping[str, object],
    attached_file_ids: tuple[str, ...],
) -> str | None:
    explicit_file_id = _optional_string(expected, "file_id")
    if explicit_file_id is not None:
        return explicit_file_id
    file_index = _int_value(expected.get("file_index"))
    if file_index is None or not 0 <= file_index < len(attached_file_ids):
        return None
    return attached_file_ids[file_index]


def _classifier_file_coverage(
    run: Mapping[str, object],
    file_id: str,
) -> str | None:
    for source in _mapping_list(run.get("source_inventory")):
        if source.get("file_id") != file_id:
            continue
        return _optional_string(source, "coverage")
    return None


def _first_run_commit_grade_slot_names(
    runs: list[Mapping[str, object]],
) -> set[str]:
    """Slot names the FIRST classifier result already resolved commit-grade.

    The first-question rule is state-aware: what the classifier resolved
    from the opening message is already answered, so asking it again is
    stale and it no longer counts as an unresolved preferred slot.
    """

    if not runs:
        return set()
    first_run = runs[0]
    names: set[str] = set()
    for claim in _mapping_list(first_run.get("slots")):
        slot_name = _optional_string(claim, "slot_name")
        if slot_name is None:
            continue
        summary = _classifier_claim_summary(first_run, claim)
        if (
            summary.get("value") != "unknown"
            and summary.get("confidence") in {"high", "medium"}
            and bool(_string_list(summary.get("evidence_quotes")))
        ):
            names.add(slot_name)
    return names


def _first_question_relevance_verdict(
    question_id: str,
    *,
    preferred_ids: set[str],
    allowed_ids: set[str],
    forbidden_ids: set[str],
    first_run_commit_grade_slots: set[str],
) -> tuple[bool, str]:
    """Semantics v2: judge the first question against resolved state.

    1. Forbidden or unclassified targets always fail.
    2. Asking a slot the first classifier result already resolved
       commit-grade is stale and fails.
    3. Commit-grade slots leave the preferred set; an unresolved
       primary_runtime_input counts as preferred when purpose was
       fixture-preferred (the documented primary-input exception).
    4. While preferred unresolved slots remain the question must target
       one of them; otherwise any fixture-allowed target passes.
    """

    if question_id in forbidden_ids:
        return False, "forbidden"
    if question_id not in preferred_ids | allowed_ids:
        return False, "unclassified"
    if question_id in first_run_commit_grade_slots:
        return False, "stale_commit_grade"
    remaining_preferred = preferred_ids - first_run_commit_grade_slots
    if (
        "post_processing_goal" in preferred_ids
        and question_id == "primary_runtime_input"
    ):
        return True, "primary_input_exception"
    if remaining_preferred:
        if question_id in remaining_preferred:
            return True, "preferred"
        return False, "preferred_unresolved_remaining"
    return True, "allowed"


def _classifier_slot_is_commit_grade(
    runs: list[Mapping[str, object]],
    slot_name: str,
) -> bool:
    claim = _latest_classifier_claim(
        runs,
        collection_name="slots",
        identity_name="slot_name",
        identity_value=slot_name,
    )
    if claim is None:
        return False
    summary = _classifier_claim_summary(*claim)
    return (
        summary.get("value") != "unknown"
        and summary.get("confidence") in {"high", "medium"}
        and bool(_string_list(summary.get("evidence_quotes")))
    )


def _classifier_assumptions(
    runs: list[Mapping[str, object]],
    event_summary: Mapping[str, object],
) -> list[str]:
    assumptions = _string_list(event_summary.get("assumptions"))
    for run in runs:
        _extend_unique_strings(assumptions, _string_list(run.get("assumptions")))
    return assumptions


def _contains_topic(values: list[str], topic: str) -> bool:
    folded_topic = topic.casefold()
    return any(folded_topic in value.casefold() for value in values)


def _quality_report(
    *,
    plan: JsonObject | None,
    summary: JsonObject,
    expected: Mapping[str, Any],
    event_summary: Mapping[str, Any] | None = None,
    journey: Mapping[str, Any] | None = None,
    classifier_diagnostics: Mapping[str, object] | None = None,
    attached_file_ids: tuple[str, ...] = (),
    applied_flow: Mapping[str, object] | None = None,
    runtime_evidence: Mapping[str, object] | None = None,
) -> JsonObject:
    checks: list[JsonObject] = []
    warnings: list[str] = []
    event_summary = event_summary or {}
    journey = journey or {}

    def add_check(
        name: str, passed: bool, actual: object, expected_value: object
    ) -> None:
        checks.append(
            {
                "name": name,
                "passed": passed,
                "actual": actual,
                "expected": expected_value,
            }
        )

    allows_structured_question = expected.get("allow_question_instead_of_plan") is True
    question_event_ids = _string_list(event_summary.get("question_event_ids"))
    question_event_count = _int_value(event_summary.get("question_event_count"))
    if question_event_count is None:
        question_event_count = len(question_event_ids)
    if allows_structured_question:
        add_check(
            "plan_or_structured_question",
            plan is not None or bool(question_event_ids),
            {
                "plan_created": plan is not None,
                "question_event_ids": question_event_ids,
            },
            "plan or structured question event",
        )
    else:
        add_check("plan_created", plan is not None, plan is not None, True)
    text_only_questions = (
        _int_value(event_summary.get("server_ask_question_text_only_count")) or 0
    )
    add_check(
        "question_event_contract",
        text_only_questions == 0,
        text_only_questions,
        0,
    )
    if expected_question_ids := _string_list(
        expected.get("expected_question_event_ids")
    ):
        add_check(
            "expected_question_event_ids",
            question_event_ids == expected_question_ids,
            question_event_ids,
            expected_question_ids,
        )
    if forbidden_question_ids := set(
        _string_list(expected.get("forbidden_question_event_ids"))
    ):
        matched_forbidden = [
            question_id
            for question_id in question_event_ids
            if question_id in forbidden_question_ids
        ]
        add_check(
            "forbidden_question_event_ids",
            matched_forbidden == [],
            matched_forbidden,
            sorted(forbidden_question_ids),
        )
    preferred_question_ids = set(
        _string_list(expected.get("preferred_question_event_ids"))
    )
    relevance_rubric_declared = any(
        key in expected
        for key in (
            "preferred_question_event_ids",
            "allowed_question_event_ids",
            "forbidden_question_event_ids",
        )
    )
    if relevance_rubric_declared:
        relevance_counts = journey.get("question_relevance_counts")
        relevance_counts = (
            relevance_counts if isinstance(relevance_counts, Mapping) else {}
        )
        if preferred_question_ids and question_event_ids:
            first_run_commit_grade_slots = _first_run_commit_grade_slot_names(
                _classifier_runs(classifier_diagnostics)
            )
            first_passed, first_reason = _first_question_relevance_verdict(
                str(question_event_ids[0]),
                preferred_ids=preferred_question_ids,
                allowed_ids=set(
                    _string_list(expected.get("allowed_question_event_ids"))
                ),
                forbidden_ids=set(
                    _string_list(expected.get("forbidden_question_event_ids"))
                ),
                first_run_commit_grade_slots=first_run_commit_grade_slots,
            )
            add_check(
                "first_question_relevance",
                first_passed,
                {
                    "question_id": question_event_ids[0],
                    "reason": first_reason,
                    "first_run_commit_grade_slots": sorted(
                        first_run_commit_grade_slots
                    ),
                },
                "state-aware preferred-first (semantics v2)",
            )
        add_check(
            "question_relevance_complete",
            (_int_value(relevance_counts.get("unclassified")) or 0) == 0,
            relevance_counts,
            {"unclassified": 0},
        )
    if (
        expected_question_count := _int_value(
            expected.get("expected_question_event_count")
        )
    ) is not None:
        add_check(
            "expected_question_event_count",
            question_event_count == expected_question_count,
            question_event_count,
            expected_question_count,
        )
    if (
        max_question_count := _int_value(expected.get("max_question_event_count"))
    ) is not None:
        add_check(
            "max_question_event_count",
            question_event_count <= max_question_count,
            question_event_count,
            max_question_count,
        )
    if (
        min_question_count := _int_value(expected.get("min_question_event_count"))
    ) is not None:
        add_check(
            "min_question_event_count",
            question_event_count >= min_question_count,
            question_event_count,
            min_question_count,
        )
    if (
        max_reopened_question_count := _int_value(
            expected.get("max_reopened_question_count")
        )
    ) is not None:
        reopened_question_count = (
            _int_value(journey.get("reopened_question_count")) or 0
        )
        add_check(
            "max_reopened_question_count",
            reopened_question_count <= max_reopened_question_count,
            reopened_question_count,
            max_reopened_question_count,
        )

    diagnostic_expectation_keys = {
        "expected_classifier_slots",
        "expected_file_roles",
        "forbid_classifier_commit_grade_slots",
    }
    classifier_runs = _classifier_runs(classifier_diagnostics)
    if diagnostic_expectation_keys.intersection(expected):
        add_check(
            "classifier_diagnostics_present",
            bool(classifier_runs),
            len(classifier_runs),
            ">= 1",
        )
    if classifier_runs:
        invalid_evidence_sources = _invalid_classifier_evidence_sources(classifier_runs)
        add_check(
            "classifier_evidence_sources",
            invalid_evidence_sources == [],
            invalid_evidence_sources,
            [],
        )

    for expected_slot in _mapping_list(expected.get("expected_classifier_slots")):
        slot_name = _optional_string(expected_slot, "slot_name")
        if slot_name is None:
            continue
        actual_slot = _latest_classifier_claim(
            classifier_runs,
            collection_name="slots",
            identity_name="slot_name",
            identity_value=slot_name,
        )
        actual_summary = (
            _classifier_claim_summary(*actual_slot) if actual_slot is not None else None
        )
        add_check(
            f"classifier_slot:{slot_name}",
            actual_summary is not None
            and _classifier_claim_matches(actual_summary, expected_slot),
            actual_summary,
            dict(expected_slot),
        )

    for expected_role in _mapping_list(expected.get("expected_file_roles")):
        # The check is named by what the case declares, never by the resolved
        # file id: provisioned ids are minted per run, so a name carrying one
        # can never aggregate across runs in the comparator's blocker ranking.
        declared_file_id = _optional_string(expected_role, "file_id")
        declared_index = _int_value(expected_role.get("file_index"))
        if declared_file_id is not None:
            check_name = f"classifier_file_role:{declared_file_id}"
        elif declared_index is not None:
            check_name = f"classifier_file_role:file_index_{declared_index}"
        else:
            check_name = "classifier_file_role:<unresolved>"
        file_id = _expected_file_id(expected_role, attached_file_ids)
        if file_id is None:
            add_check(
                check_name,
                False,
                None,
                dict(expected_role),
            )
            continue
        actual_role = _latest_classifier_claim(
            classifier_runs,
            collection_name="file_roles",
            identity_name="file_id",
            identity_value=file_id,
        )
        actual_summary = None
        if actual_role is not None:
            actual_summary = _classifier_claim_summary(*actual_role)
            actual_summary["coverage"] = _classifier_file_coverage(
                actual_role[0],
                file_id,
            )
        expected_summary = {**expected_role, "file_id": file_id}
        add_check(
            check_name,
            actual_summary is not None
            and _classifier_claim_matches(actual_summary, expected_summary),
            actual_summary,
            dict(expected_summary),
        )

    forbidden_commit_grade_slots = set(
        _string_list(expected.get("forbid_classifier_commit_grade_slots"))
    )
    if forbidden_commit_grade_slots:
        matched_commit_grade = [
            slot_name
            for slot_name in sorted(forbidden_commit_grade_slots)
            if _classifier_slot_is_commit_grade(classifier_runs, slot_name)
        ]
        add_check(
            "forbid_classifier_commit_grade_slots",
            matched_commit_grade == [],
            matched_commit_grade,
            [],
        )

    assumptions = _classifier_assumptions(classifier_runs, event_summary)
    expected_assumption_topics = _string_list(
        expected.get("expected_assumption_topics")
    )
    if expected_assumption_topics:
        missing_topics = [
            topic
            for topic in expected_assumption_topics
            if not _contains_topic(assumptions, topic)
        ]
        add_check(
            "expected_assumption_topics",
            missing_topics == [],
            assumptions,
            expected_assumption_topics,
        )
    forbidden_assumption_topics = _string_list(
        expected.get("forbidden_assumption_topics")
    )
    if forbidden_assumption_topics:
        matched_topics = [
            topic
            for topic in forbidden_assumption_topics
            if _contains_topic(assumptions, topic)
        ]
        add_check(
            "forbidden_assumption_topics",
            matched_topics == [],
            matched_topics,
            [],
        )
    expected_review_policy = expected.get("expected_review_policy")
    if isinstance(expected_review_policy, Mapping):
        checks.extend(
            _review_policy_checks(
                scope="proposed",
                summary=summary,
                expected=expected_review_policy,
            )
        )
        if applied_flow is not None:
            checks.extend(
                _review_policy_checks(
                    scope="applied",
                    summary=_summarize_applied_flow(applied_flow),
                    expected=expected_review_policy,
                )
            )
    expected_first_pass = expected.get("expected_first_pass_authoring")
    if isinstance(expected_first_pass, Mapping):
        checks.extend(
            _first_pass_authoring_plan_checks(
                summary=summary,
                expected=expected_first_pass,
                analysis_field_groups=_field_groups_from_expected_key(
                    expected,
                    "expected_leaf_output_field_groups",
                ),
            )
        )
        review_targets = _mapping_list(expected_first_pass.get("review_targets"))
        checks.extend(
            _first_pass_review_policy_checks(
                scope="proposed",
                summary=summary,
                expected_targets=review_targets,
            )
        )
        if applied_flow is not None:
            checks.extend(
                _first_pass_review_policy_checks(
                    scope="applied",
                    summary=_summarize_applied_flow(applied_flow),
                    expected_targets=review_targets,
                )
            )
    expected_runtime_evidence = expected.get("expected_runtime_evidence")
    if isinstance(expected_runtime_evidence, Mapping):
        checks.extend(
            _runtime_evidence_checks(
                evidence=runtime_evidence,
                expected=expected_runtime_evidence,
            )
        )
    if expected.get("expected_persisted_named_results") is True:
        persisted_named_results = _persisted_named_result_names(classifier_diagnostics)
        add_check(
            "sentinel_named_result_evidence",
            bool(persisted_named_results),
            persisted_named_results,
            "at least one persisted named result",
        )

    if expected.get("expected_plan_invariant_vector") is True:
        steps = _step_summaries(summary)
        minimum_steps = _int_value(expected.get("min_steps"))
        maximum_steps = _int_value(expected.get("max_steps"))
        expected_terminal_type = expected.get("terminal_output_type")
        expected_terminal_mode = expected.get("terminal_document_output_mode")
        step_count = _int_value(summary.get("step_count"))
        renderer_step_present = any(
            step.get("output_type") == expected_terminal_type
            and step.get("output_mode") == expected_terminal_mode
            for step in steps
        )
        per_source_reader_present = any(
            step.get("input_source") == "flow_input"
            and step.get("input_type") in {"document", "file"}
            and step.get("output_type") == "json"
            for step in steps
        )
        actual_invariants = {
            "terminal_output_type": summary.get("terminal_output_type"),
            "terminal_output_mode": summary.get("terminal_output_mode"),
            "renderer_step_present": renderer_step_present,
            "per_source_reader_present": per_source_reader_present,
            "step_count": step_count,
        }
        expected_invariants = {
            "terminal_output_type": expected_terminal_type,
            "terminal_output_mode": expected_terminal_mode,
            "renderer_step_present": True,
            "per_source_reader_present": True,
            "step_count": {"min": minimum_steps, "max": maximum_steps},
        }
        add_check(
            "sentinel_invariant_vector",
            isinstance(expected_terminal_type, str)
            and isinstance(expected_terminal_mode, str)
            and minimum_steps is not None
            and maximum_steps is not None
            and actual_invariants["terminal_output_type"] == expected_terminal_type
            and actual_invariants["terminal_output_mode"] == expected_terminal_mode
            and renderer_step_present
            and per_source_reader_present
            and step_count is not None
            and minimum_steps <= step_count <= maximum_steps,
            actual_invariants,
            expected_invariants,
        )
    if plan is None:
        return {"checks": checks, "warnings": warnings}

    if expected_primary_input_type := _optional_string(
        expected,
        "expected_primary_input_type",
    ):
        input_type_summaries = [("expected_primary_input_type", summary)]
        if applied_flow is not None:
            input_type_summaries.append(
                (
                    "applied_expected_primary_input_type",
                    _summarize_applied_flow(applied_flow),
                )
            )
        for check_name, input_type_summary in input_type_summaries:
            primary_flow_input_step = next(
                (
                    step
                    for step in _step_summaries(input_type_summary)
                    if step.get("input_source") == "flow_input"
                ),
                None,
            )
            actual_primary_input_type = (
                primary_flow_input_step.get("input_type")
                if primary_flow_input_step is not None
                else None
            )
            add_check(
                check_name,
                actual_primary_input_type == expected_primary_input_type,
                actual_primary_input_type,
                expected_primary_input_type,
            )

    step_count = _int_value(summary.get("step_count"))
    if (minimum := _int_value(expected.get("min_steps"))) is not None:
        add_check(
            "min_steps",
            step_count is not None and step_count >= minimum,
            step_count,
            minimum,
        )
    if (maximum := _int_value(expected.get("max_steps"))) is not None:
        add_check(
            "max_steps",
            step_count is not None and step_count <= maximum,
            step_count,
            maximum,
        )
    if expected_output_modes := _string_list(expected.get("expected_output_modes")):
        actual_output_modes = [
            str(step.get("output_mode"))
            for step in _step_summaries(summary)
            if isinstance(step.get("output_mode"), str)
        ]
        add_check(
            "expected_output_modes",
            actual_output_modes == expected_output_modes,
            actual_output_modes,
            expected_output_modes,
        )
    if forbidden_input_sources := set(
        _string_list(expected.get("forbid_input_sources"))
    ):
        forbidden_step_orders = [
            step.get("order")
            for step in _step_summaries(summary)
            if step.get("input_source") in forbidden_input_sources
        ]
        add_check(
            "forbid_input_sources",
            forbidden_step_orders == [],
            forbidden_step_orders,
            sorted(forbidden_input_sources),
        )
    if (terminal := expected.get("terminal_output_type")) is not None:
        add_check(
            "terminal_output_type",
            summary.get("terminal_output_type") == terminal,
            summary.get("terminal_output_type"),
            terminal,
        )
    if allowed_terminal_types := _string_list(expected.get("terminal_output_types")):
        add_check(
            "terminal_output_type_allowed",
            summary.get("terminal_output_type") in set(allowed_terminal_types),
            summary.get("terminal_output_type"),
            allowed_terminal_types,
        )
    expected_terminal_types = set(_string_list(expected.get("terminal_output_types")))
    document_terminal_types = {"pdf", "docx"}
    if (
        summary.get("terminal_output_type") in document_terminal_types
        or expected.get("terminal_output_type") in document_terminal_types
        or expected_terminal_types & document_terminal_types
    ):
        expected_output_mode = expected.get("terminal_document_output_mode")
        if not isinstance(expected_output_mode, str):
            expected_output_mode = "render_verbatim"
        add_check(
            "terminal_document_output_mode",
            summary.get("terminal_output_mode") == expected_output_mode,
            summary.get("terminal_output_mode"),
            expected_output_mode,
        )
        if expected_output_mode == "render_verbatim":
            renderer_is_previous_step_bound = _source_context_metrics(summary)[
                "renderer_is_previous_step_bound"
            ]
            add_check(
                "renderer_previous_step_bound",
                renderer_is_previous_step_bound is True,
                renderer_is_previous_step_bound,
                True,
            )
    if (minimum_json := _int_value(expected.get("min_json_steps"))) is not None:
        actual_json = _int_value(summary.get("json_step_count"))
        add_check(
            "min_json_steps",
            actual_json is not None and actual_json >= minimum_json,
            actual_json,
            minimum_json,
        )
    if (
        minimum_source_refs := _int_value(expected.get("min_source_ref_steps"))
    ) is not None:
        actual_source_refs = _int_value(summary.get("source_ref_steps"))
        add_check(
            "min_source_ref_steps",
            actual_source_refs is not None
            and actual_source_refs >= minimum_source_refs,
            actual_source_refs,
            minimum_source_refs,
        )
    max_all_previous = _int_value(expected.get("max_all_previous_steps"))
    if max_all_previous is not None:
        actual_all_previous = _int_value(summary.get("all_previous_step_count"))
        add_check(
            "max_all_previous_steps",
            actual_all_previous is not None and actual_all_previous <= max_all_previous,
            actual_all_previous,
            max_all_previous,
        )
    if (
        max_post_json_text := _int_value(
            expected.get("max_post_json_text_cleanup_steps")
        )
    ) is not None:
        metrics = _source_context_metrics(summary)
        actual_post_json_text = _int_value(
            metrics.get("post_json_text_cleanup_step_count")
        )
        add_check(
            "max_post_json_text_cleanup_steps",
            actual_post_json_text is not None
            and actual_post_json_text <= max_post_json_text,
            actual_post_json_text,
            max_post_json_text,
        )

    duplicate_steps = summary.get("duplicate_source_ref_steps")
    add_check("no_duplicate_source_refs", duplicate_steps == [], duplicate_steps, [])
    template_steps = summary.get("instruction_template_steps")
    add_check(
        "no_template_variables_in_instructions",
        template_steps == [],
        template_steps,
        [],
    )

    for expectation_key, contract_key in (
        ("expected_input_contract_schema", "input_contract"),
        ("expected_output_contract_schema", "output_contract"),
    ):
        expected_schema = expected.get(expectation_key)
        if not isinstance(expected_schema, Mapping):
            continue
        contract_target = _plan_contract(plan, contract_key)
        matching_step = (
            contract_target[0]
            if contract_target is not None
            and _json_subset_matches(expected_schema, contract_target[1])
            else None
        )
        add_check(
            expectation_key,
            matching_step is not None,
            {
                "matching_step_index": matching_step,
                "target": contract_target[1] if contract_target is not None else None,
            },
            dict(expected_schema),
        )
        applied_target = _applied_flow_contract(applied_flow, contract_key)
        if applied_flow is not None:
            applied_matches = applied_target is not None and _json_subset_matches(
                expected_schema,
                applied_target[1] if applied_target is not None else None,
            )
            add_check(
                f"applied_{expectation_key}",
                applied_matches,
                {
                    "matching_step_index": (
                        applied_target[0]
                        if applied_matches and applied_target is not None
                        else None
                    ),
                    "target": (
                        applied_target[1] if applied_target is not None else None
                    ),
                },
                dict(expected_schema),
            )

    expected_leaf_fields = _field_expectation_groups(expected)
    if expected_leaf_fields:
        field_evidence = _output_field_evidence(summary, expected_leaf_fields)
        actual_leaf_fields = _string_list(field_evidence.get("fields"))
        missing_groups = [
            group
            for group in expected_leaf_fields
            if not any(
                _field_name_matches(expected_name, actual_name)
                for expected_name in group
                for actual_name in actual_leaf_fields
            )
        ]
        add_check(
            "expected_leaf_output_fields",
            not missing_groups,
            field_evidence,
            expected_leaf_fields,
        )

    expected_form_fields = _field_groups_from_expected_key(
        expected,
        "expected_form_field_groups",
    )
    if (
        min_form_fields := _int_value(expected.get("min_form_field_count"))
    ) is not None:
        form_field_names = _string_list(summary.get("form_field_names"))
        add_check(
            "min_form_field_count",
            len(form_field_names) >= min_form_fields,
            len(form_field_names),
            min_form_fields,
        )
    if expected_form_fields:
        form_field_names = _string_list(summary.get("form_field_names"))
        missing_form_groups = [
            group
            for group in expected_form_fields
            if not any(
                _field_name_matches(expected_name, actual_name)
                for expected_name in group
                for actual_name in form_field_names
            )
        ]
        add_check(
            "expected_form_fields",
            not missing_form_groups,
            form_field_names,
            expected_form_fields,
        )

    forbidden_form_fields = _field_groups_from_expected_key(
        expected,
        "forbidden_form_field_groups",
    )
    if forbidden_form_fields:
        form_field_names = _string_list(summary.get("form_field_names"))
        matched_forbidden_groups = [
            group
            for group in forbidden_form_fields
            if any(
                _field_name_matches(forbidden_name, actual_name)
                for forbidden_name in group
                for actual_name in form_field_names
            )
        ]
        add_check(
            "no_forbidden_form_fields",
            not matched_forbidden_groups,
            matched_forbidden_groups,
            [],
        )

    if expected.get("forbid_primary_material_form_fields", True):
        suspicious = _primary_material_form_fields(summary.get("form_field_names"))
        add_check("no_primary_material_form_fields", not suspicious, suspicious, [])
    if expected.get("forbid_generic_primary_reader_envelope"):
        generic_primary_readers = _generic_primary_reader_envelope_steps(summary)
        add_check(
            "no_generic_primary_reader_envelope",
            not generic_primary_readers,
            generic_primary_readers,
            [],
        )

    if summary.get("source_ref_steps") == 0 and summary.get("step_count", 0) > 2:
        warnings.append(
            "multi-step plan has no typed source_refs; inspect implicit dataflow carefully"
        )
    if summary.get("json_step_count") == 0 and expected.get("min_json_steps"):
        warnings.append(
            "expected structured extraction, but no JSON-producing step was generated"
        )
    artifact_confusion_steps = _non_terminal_artifact_confusion_steps(summary)
    if artifact_confusion_steps:
        warnings.append(
            "non-terminal text step appears to create/render the final artifact: "
            + ", ".join(str(step) for step in artifact_confusion_steps)
        )
    warnings.extend(_source_context_warnings(summary))
    generic_primary_readers = _generic_primary_reader_envelope_steps(summary)
    if generic_primary_readers:
        warnings.append(
            "primary source reader uses the generic source_facts/uncertainties "
            "envelope; inspect whether downstream requested fields are "
            f"contractually preserved: {generic_primary_readers}"
        )

    return {
        "checks": checks,
        "warnings": warnings,
        "metrics": _source_context_metrics(summary),
    }


def _summarize_applied_flow(flow: Mapping[str, object] | None) -> JsonObject:
    if not isinstance(flow, Mapping):
        return {"has_flow": False, "step_count": 0, "steps": []}
    raw_steps = flow.get("steps")
    if not isinstance(raw_steps, list):
        return {"has_flow": True, "step_count": 0, "steps": []}
    steps: list[JsonObject] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, Mapping):
            continue
        review_policy = raw_step.get("review_policy")
        steps.append(
            {
                "order": _int_value(raw_step.get("step_order")) or index,
                "plan_step_ref": raw_step.get("plan_step_ref"),
                "name": raw_step.get("user_description") or raw_step.get("name"),
                "input_source": raw_step.get("input_source"),
                "input_type": raw_step.get("input_type"),
                "output_type": raw_step.get("output_type"),
                "output_mode": raw_step.get("output_mode"),
                "review_policy": (
                    dict(review_policy) if isinstance(review_policy, Mapping) else None
                ),
                "review_mode": (
                    review_policy.get("mode")
                    if isinstance(review_policy, Mapping)
                    else None
                ),
                "output_contract_leaf_properties": _schema_leaf_property_names(
                    raw_step.get("output_contract")
                ),
            }
        )
    steps.sort(key=lambda step: _int_value(step.get("order")) or 0)
    return {
        "has_flow": True,
        "step_count": len(steps),
        "steps": steps,
    }


def _review_policy_checks(
    *,
    scope: str,
    summary: Mapping[str, object],
    expected: Mapping[str, object],
) -> list[JsonObject]:
    steps = _step_summaries(summary)
    review_steps = [
        step for step in steps if isinstance(step.get("review_policy"), Mapping)
    ]
    target = review_steps[0] if len(review_steps) == 1 else None
    expected_mode = _optional_string(expected, "mode")
    expected_output_type = _optional_string(expected, "target_output_type")
    expected_field_groups = _field_groups_from_expected_key(
        expected,
        "target_field_groups",
    )
    target_fields = (
        _string_list(target.get("output_contract_leaf_properties"))
        if target is not None
        else []
    )
    missing_field_groups = [
        group
        for group in expected_field_groups
        if not any(
            _field_name_matches(expected_name, actual_name)
            for expected_name in group
            for actual_name in target_fields
        )
    ]
    target_matches = (
        target is not None
        and (
            expected_output_type is None
            or target.get("output_type") == expected_output_type
        )
        and not missing_field_groups
    )
    target_position = steps.index(target) if target is not None else None
    next_step = (
        steps[target_position + 1]
        if target_position is not None and target_position + 1 < len(steps)
        else None
    )
    review_bypass_step = (
        next_step
        if target is not None
        and next_step is not None
        and not isinstance(next_step.get("review_policy"), Mapping)
        and next_step.get("output_type") == target.get("output_type")
        and next_step.get("output_mode") == "pass_through"
        else None
    )
    structural_topology = [
        {
            "order": step.get("order"),
            "output_type": step.get("output_type"),
            "output_mode": step.get("output_mode"),
            "has_review_policy": isinstance(step.get("review_policy"), Mapping),
        }
        for step in steps
    ]
    target_order = _int_value(target.get("order")) if target is not None else None
    target_is_terminal_or_delivery = target is None or (
        expected.get("target_must_be_non_terminal") is True
        and target_order == len(steps)
    )
    if target is not None and (
        target.get("output_type") in {"pdf", "docx"}
        or target.get("output_mode") in {"render_verbatim", "http_post"}
    ):
        target_is_terminal_or_delivery = True
    actual_target = (
        {
            "order": target.get("order"),
            "plan_step_ref": target.get("plan_step_ref"),
            "name": target.get("name"),
            "output_type": target.get("output_type"),
            "output_mode": target.get("output_mode"),
            "output_contract_leaf_properties": target_fields,
        }
        if target is not None
        else None
    )
    return [
        {
            "name": f"{scope}_review_policy_count",
            "passed": len(review_steps) == 1,
            "actual": len(review_steps),
            "expected": 1,
        },
        {
            "name": f"{scope}_review_policy_mode",
            "passed": target is not None and target.get("review_mode") == expected_mode,
            "actual": target.get("review_mode") if target is not None else None,
            "expected": expected_mode,
        },
        {
            "name": f"{scope}_review_policy_target",
            "passed": target_matches,
            "actual": actual_target,
            "expected": {
                "output_type": expected_output_type,
                "field_groups": expected_field_groups,
            },
        },
        {
            "name": f"{scope}_review_policy_topology",
            "passed": target is not None and review_bypass_step is None,
            "actual": structural_topology,
            "expected": (
                "reviewed structured output is consumed without an unreviewed "
                "same-type pass-through"
            ),
        },
        {
            "name": f"{scope}_review_policy_not_terminal_or_delivery",
            "passed": not target_is_terminal_or_delivery,
            "actual": actual_target,
            "expected": "non-terminal non-delivery step",
        },
    ]


def _first_pass_authoring_plan_checks(
    *,
    summary: Mapping[str, object],
    expected: Mapping[str, object],
    analysis_field_groups: list[list[str]],
) -> list[JsonObject]:
    steps = _step_summaries(summary)
    expected_types = _string_list(expected.get("expected_step_output_types"))
    expected_modes = _string_list(expected.get("expected_step_output_modes"))
    actual_pipeline = [
        {
            "output_type": step.get("output_type"),
            "output_mode": step.get("output_mode"),
        }
        for step in steps
    ]
    expected_pipeline = [
        {"output_type": output_type, "output_mode": output_mode}
        for output_type, output_mode in zip(expected_types, expected_modes, strict=True)
    ]
    writer_steps = [
        step
        for step in steps
        if step.get("has_assistant_spec") is True
        and step.get("output_type") == "text"
        and step.get("output_mode") == "pass_through"
    ]
    expected_writer_count = _int_value(expected.get("document_writer_count"))
    names = _clean_strings([step.get("name") for step in steps])
    normalized_names = [_normalized_field_name(name) for name in names]
    analysis_steps = [step for step in steps if step.get("output_type") == "json"]
    analysis_fields = _clean_strings(
        [
            field
            for step in analysis_steps
            for field in _string_list(step.get("output_contract_leaf_properties"))
        ]
    )
    normalized_analysis_fields = {
        _normalized_field_name(field) for field in analysis_fields
    }
    missing_analysis_field_groups = [
        group
        for group in analysis_field_groups
        if not any(
            _normalized_field_name(label) in normalized_analysis_fields
            for label in group
        )
    ]
    outline_groups = _field_groups_from_expected_key(
        expected,
        "report_section_groups",
    )
    writer_text = " ".join(
        str(step.get(key) or "")
        for step in writer_steps
        for key in (
            "name",
            "instruction_excerpt",
            "output_contract_leaf_properties",
        )
    )
    normalized_writer_text = _normalized_field_name(writer_text)
    missing_outline_groups = [
        group
        for group in outline_groups
        if not any(
            _normalized_field_name(label) in normalized_writer_text for label in group
        )
    ]
    forbidden_heading_groups = _field_groups_from_expected_key(
        expected,
        "forbidden_task_heading_groups",
    )
    promoted_heading_groups = [
        group
        for group in forbidden_heading_groups
        if any(
            _normalized_field_name(label) in normalized_writer_text for label in group
        )
    ]
    return [
        {
            "name": "first_pass_pipeline",
            "passed": actual_pipeline == expected_pipeline,
            "actual": actual_pipeline,
            "expected": expected_pipeline,
        },
        {
            "name": "first_pass_typed_analysis_contract",
            "passed": (
                len(analysis_steps) == 1 and missing_analysis_field_groups == []
            ),
            "actual": {
                "json_step_count": len(analysis_steps),
                "fields": analysis_fields,
                "missing_groups": missing_analysis_field_groups,
            },
            "expected": analysis_field_groups,
        },
        {
            "name": "first_pass_document_writer_count",
            "passed": len(writer_steps) == expected_writer_count,
            "actual": len(writer_steps),
            "expected": expected_writer_count,
        },
        {
            "name": "first_pass_unique_step_names",
            "passed": (
                len(names) == len(steps)
                and len(normalized_names) == len(set(normalized_names))
            ),
            "actual": names,
            "expected": "unique non-empty step names",
        },
        {
            "name": "first_pass_report_outline",
            "passed": missing_outline_groups == [],
            "actual": {"missing_groups": missing_outline_groups},
            "expected": outline_groups,
        },
        {
            "name": "first_pass_task_headings_not_promoted",
            "passed": promoted_heading_groups == [],
            "actual": promoted_heading_groups,
            "expected": [],
        },
    ]


def _first_pass_review_policy_checks(
    *,
    scope: str,
    summary: Mapping[str, object],
    expected_targets: list[Mapping[str, object]],
) -> list[JsonObject]:
    steps = _step_summaries(summary)
    review_steps = [
        step for step in steps if isinstance(step.get("review_policy"), Mapping)
    ]
    unmatched_steps = list(review_steps)
    missing_targets: list[JsonObject] = []
    for target in expected_targets:
        matching_index = next(
            (
                index
                for index, step in enumerate(unmatched_steps)
                if step.get("review_mode") == target.get("mode")
                and step.get("output_type") == target.get("output_type")
                and step.get("output_mode") == target.get("output_mode")
            ),
            None,
        )
        if matching_index is None:
            missing_targets.append(dict(target))
        else:
            unmatched_steps.pop(matching_index)
    actual_targets = [
        {
            "order": step.get("order"),
            "mode": step.get("review_mode"),
            "output_type": step.get("output_type"),
            "output_mode": step.get("output_mode"),
        }
        for step in review_steps
    ]
    producing_steps_only = all(
        step.get("output_type") not in {"pdf", "docx"}
        and step.get("output_mode") not in {"render_verbatim", "http_post"}
        and (_int_value(step.get("order")) or len(steps)) < len(steps)
        for step in review_steps
    )
    return [
        {
            "name": f"first_pass_{scope}_review_policy_count",
            "passed": len(review_steps) == len(expected_targets),
            "actual": len(review_steps),
            "expected": len(expected_targets),
        },
        {
            "name": f"first_pass_{scope}_review_policy_targets",
            "passed": not missing_targets and not unmatched_steps,
            "actual": actual_targets,
            "expected": [dict(target) for target in expected_targets],
        },
        {
            "name": f"first_pass_{scope}_review_policy_producing_steps",
            "passed": producing_steps_only and bool(review_steps),
            "actual": actual_targets,
            "expected": "non-terminal producing steps only",
        },
    ]


def _runtime_evidence_checks(
    *,
    evidence: Mapping[str, object] | None,
    expected: Mapping[str, object],
) -> list[JsonObject]:
    evidence = evidence or {}
    run = evidence.get("run")
    run = run if isinstance(run, Mapping) else {}
    raw_steps = evidence.get("step_results")
    steps = (
        [step for step in raw_steps if isinstance(step, Mapping)]
        if isinstance(raw_steps, list)
        else []
    )
    artifact = evidence.get("final_artifact")
    artifact = artifact if isinstance(artifact, Mapping) else {}
    artifact_text = _optional_string(artifact, "text") or ""
    artifact_sha256 = _optional_string(artifact, "sha256")
    result = run.get("result")
    result = result if isinstance(result, Mapping) else {}
    final_artifact_present = (
        run.get("status") == "completed"
        and result.get("kind") == "artifact"
        and isinstance(artifact_sha256, str)
        and len(artifact_sha256) == 64
        and bool(artifact_text)
    )

    runtime_file_ids: list[str] = []
    documents: list[Mapping[str, object]] = []
    for step in steps:
        _extend_unique_strings(
            runtime_file_ids,
            _string_list(step.get("runtime_input_file_ids")),
        )
        output_payload = step.get("output_payload_json")
        step_documents = _first_mapping_list_for_key(output_payload, "documents")
        if step_documents is not None:
            documents.extend(step_documents)

    provider_calls = evidence.get("provider_calls")
    provider_calls = provider_calls if isinstance(provider_calls, Mapping) else None
    total_count_truncated = (
        provider_calls.get("total_count_truncated")
        if provider_calls is not None
        else None
    )
    raw_provider_call_count = (
        provider_calls.get("total_count") if provider_calls is not None else None
    )
    provider_call_count = (
        raw_provider_call_count
        if isinstance(raw_provider_call_count, int)
        and not isinstance(raw_provider_call_count, bool)
        and raw_provider_call_count >= 0
        and total_count_truncated is False
        else None
    )
    if provider_calls is None:
        provider_call_evidence_status = "missing"
    elif total_count_truncated is True:
        provider_call_evidence_status = "truncated"
    elif total_count_truncated is not False or provider_call_count is None:
        provider_call_evidence_status = "invalid"
    else:
        provider_call_evidence_status = "complete"

    source_labels = list(
        dict.fromkeys(
            _clean_strings([document.get("source_label") for document in documents])
        )
    )
    record_source_file_ids = _clean_strings(
        [document.get("source_file_id") for document in documents]
    )
    record_count_by_source_file_id = {
        file_id: record_source_file_ids.count(file_id)
        for file_id in dict.fromkeys(record_source_file_ids)
    }
    one_record_per_source_file = set(record_count_by_source_file_id) == set(
        runtime_file_ids
    ) and all(count == 1 for count in record_count_by_source_file_id.values())
    expected_source_files = _int_value(expected.get("source_file_count"))
    expected_source_records = _int_value(expected.get("source_record_count"))
    expected_source_displays = _int_value(expected.get("source_display_count"))
    expected_model_calls = _int_value(expected.get("model_call_count"))
    token_usage = run.get("token_usage")
    total_tokens = (
        _int_value(token_usage.get("num_tokens_total"))
        if isinstance(token_usage, Mapping)
        else None
    )
    max_total_tokens = _int_value(expected.get("max_total_tokens"))

    expected_field_groups = _field_groups_from_expected_key(
        expected,
        "required_final_field_label_groups",
    )
    missing_record_field_groups: dict[str, list[list[str]]] = {}
    for index, document in enumerate(documents, start=1):
        record_label = _optional_string(document, "source_label") or f"record-{index}"
        present_fields = [
            str(key)
            for key, value in document.items()
            if isinstance(key, str)
            and (
                (isinstance(value, str) and bool(value.strip()))
                or (isinstance(value, (int, float)) and not isinstance(value, bool))
            )
        ]
        missing_groups = [
            group
            for group in expected_field_groups
            if not any(
                _field_name_matches(expected_name, actual_name)
                for expected_name in group
                for actual_name in present_fields
            )
        ]
        if missing_groups:
            missing_record_field_groups[record_label] = missing_groups
    artifact_labels = _artifact_labels(artifact_text)
    missing_field_groups = [
        group
        for group in expected_field_groups
        if not any(
            _field_name_matches(expected_label, actual_label)
            for expected_label in group
            for actual_label in artifact_labels
        )
    ]
    degradation_groups = _field_groups_from_expected_key(
        expected,
        "required_visible_degradation_markers",
    )
    missing_degradation_groups = [
        group
        for group in degradation_groups
        if not any(marker.casefold() in artifact_text.casefold() for marker in group)
    ]
    artifact_source_sections = _artifact_source_sections(artifact_text, source_labels)
    missing_artifact_field_groups_by_source: dict[str, list[list[str]]] = {}
    for label in source_labels:
        section_labels = _artifact_labels(artifact_source_sections.get(label, ""))
        section_missing_groups = [
            group
            for group in expected_field_groups
            if not any(
                _field_name_matches(expected_label, actual_label)
                for expected_label in group
                for actual_label in section_labels
            )
        ]
        if section_missing_groups:
            missing_artifact_field_groups_by_source[label] = section_missing_groups
    associated_artifact_text = "\n".join(artifact_source_sections.values())
    missing_associated_degradation_groups = [
        group
        for group in degradation_groups
        if not any(
            marker.casefold() in associated_artifact_text.casefold() for marker in group
        )
    ]
    missing_source_labels = [
        label
        for label in source_labels
        if label.casefold() not in artifact_text.casefold()
    ]
    return [
        {
            "name": "runtime_final_artifact",
            "passed": final_artifact_present,
            "actual": {
                "run_status": run.get("status"),
                "result_kind": result.get("kind"),
                "artifact_sha256": artifact_sha256,
                "artifact_text_chars": len(artifact_text),
            },
            "expected": "completed artifact with immutable bytes and extracted text",
        },
        {
            "name": "runtime_source_file_count",
            "passed": (
                expected_source_files is not None
                and len(runtime_file_ids) == expected_source_files
            ),
            "actual": len(runtime_file_ids),
            "expected": expected_source_files,
        },
        {
            "name": "runtime_source_record_count",
            "passed": (
                expected_source_records is not None
                and len(documents) == expected_source_records
            ),
            "actual": len(documents),
            "expected": expected_source_records,
        },
        {
            "name": "runtime_one_record_per_source_file",
            "passed": (
                expected_source_records is not None
                and len(documents) == expected_source_records
                and one_record_per_source_file
            ),
            "actual": record_count_by_source_file_id,
            "expected": {
                "source_file_ids": runtime_file_ids,
                "records_per_source_file": 1,
            },
        },
        {
            "name": "runtime_source_record_fields",
            "passed": missing_record_field_groups == {},
            "actual": missing_record_field_groups,
            "expected": expected_field_groups,
        },
        {
            "name": "runtime_final_field_labels",
            "passed": missing_field_groups == [],
            "actual": artifact_labels,
            "expected": expected_field_groups,
        },
        {
            "name": "runtime_per_source_artifact_fields",
            "passed": (
                len(artifact_source_sections) == len(source_labels)
                and missing_artifact_field_groups_by_source == {}
            ),
            "actual": {
                "associated_source_labels": list(artifact_source_sections),
                "missing_field_groups_by_source": (
                    missing_artifact_field_groups_by_source
                ),
            },
            "expected": {
                "source_labels": source_labels,
                "field_groups_per_source": expected_field_groups,
            },
        },
        {
            "name": "runtime_visible_degradation",
            "passed": missing_degradation_groups == [],
            "actual": artifact_text[:2000],
            "expected": degradation_groups,
        },
        {
            "name": "runtime_degradation_source_association",
            "passed": (
                len(artifact_source_sections) == len(source_labels)
                and missing_associated_degradation_groups == []
            ),
            "actual": {
                "associated_source_labels": list(artifact_source_sections),
                "missing_marker_groups": missing_associated_degradation_groups,
            },
            "expected": degradation_groups,
        },
        {
            "name": "runtime_source_display",
            "passed": (
                expected_source_displays is not None
                and len(source_labels) == expected_source_displays
                and missing_source_labels == []
            ),
            "actual": {
                "source_labels": source_labels,
                "missing_from_artifact": missing_source_labels,
            },
            "expected": expected_source_displays,
        },
        {
            "name": "runtime_model_call_count",
            "passed": (
                expected_model_calls is not None
                and provider_call_evidence_status == "complete"
                and provider_call_count == expected_model_calls
            ),
            "actual": {
                "count": provider_call_count,
                "evidence_status": provider_call_evidence_status,
                "total_count_truncated": total_count_truncated,
            },
            "expected": expected_model_calls,
        },
        {
            "name": "runtime_total_tokens",
            "passed": (
                total_tokens is not None
                and max_total_tokens is not None
                and total_tokens <= max_total_tokens
            ),
            "actual": total_tokens,
            "expected": {"max": max_total_tokens},
        },
    ]


def _runtime_metrics_from_quality_report(report: Mapping[str, object]) -> JsonObject:
    checks = report.get("checks")
    if not isinstance(checks, list):
        return {}
    return {
        str(check["name"]): check.get("actual")
        for check in checks
        if isinstance(check, Mapping)
        and isinstance(check.get("name"), str)
        and str(check["name"]).startswith("runtime_")
    }


def _first_mapping_list_for_key(
    value: object,
    key: str,
) -> list[Mapping[str, object]] | None:
    if isinstance(value, Mapping):
        candidate = value.get(key)
        if isinstance(candidate, list) and all(
            isinstance(item, Mapping) for item in candidate
        ):
            return [item for item in candidate if isinstance(item, Mapping)]
        for child in value.values():
            found = _first_mapping_list_for_key(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_mapping_list_for_key(child, key)
            if found is not None:
                return found
    return None


def _artifact_labels(text: str) -> list[str]:
    labels: list[str] = []
    for line in text.splitlines():
        label, separator, _value = line.partition(":")
        if separator and label.strip():
            labels.append(label.strip())
    return labels


def _artifact_source_sections(
    text: str,
    source_labels: list[str],
) -> dict[str, str]:
    lines = text.splitlines()
    anchors: dict[str, int] = {}
    for index, line in enumerate(lines):
        matching_labels = [
            label for label in source_labels if label.casefold() in line.casefold()
        ]
        if len(matching_labels) == 1 and matching_labels[0] not in anchors:
            anchors[matching_labels[0]] = index
    if len(anchors) != len(source_labels):
        return {}
    ordered_anchors = sorted(anchors.items(), key=lambda item: item[1])
    sections: dict[str, str] = {}
    for position, (label, start) in enumerate(ordered_anchors):
        end = (
            ordered_anchors[position + 1][1]
            if position + 1 < len(ordered_anchors)
            else len(lines)
        )
        sections[label] = "\n".join(lines[start:end])
    return sections


def _output_fields(steps: list[Mapping[str, Any]]) -> list[str]:
    fields: list[str] = []
    for step in steps:
        for key in (
            "output_contract_properties",
            "output_contract_nested_properties",
            "output_contract_leaf_properties",
        ):
            raw = step.get(key)
            if isinstance(raw, list):
                fields.extend(str(field) for field in raw)
    return list(dict.fromkeys(fields))


def _output_field_evidence(
    summary: Mapping[str, Any],
    expected_groups: list[list[str]],
) -> JsonObject:
    steps = _step_summaries(summary)
    all_fields = _output_fields(steps)
    if summary.get("terminal_output_type") != "json" or not steps:
        return {
            "boundary": "all_steps",
            "fields": all_fields,
            "intermediate_only_matches": [],
        }

    terminal_fields = _output_fields([steps[-1]])
    intermediate_only_matches = [
        actual_name
        for actual_name in all_fields
        if actual_name not in terminal_fields
        and any(
            _field_name_matches(expected_name, actual_name)
            for group in expected_groups
            for expected_name in group
        )
    ]
    return {
        "boundary": "terminal_json",
        "fields": terminal_fields,
        "intermediate_only_matches": intermediate_only_matches,
    }


def _step_summaries(summary: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    steps = summary.get("steps")
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, Mapping)]


def _field_expectation_groups(expected: Mapping[str, Any]) -> list[list[str]]:
    raw_groups = expected.get("expected_leaf_output_field_groups")
    if isinstance(raw_groups, list):
        return _field_groups(raw_groups)
    return [
        [field] for field in _string_list(expected.get("expected_leaf_output_fields"))
    ]


def _field_groups_from_expected_key(
    expected: Mapping[str, Any],
    key: str,
) -> list[list[str]]:
    raw_groups = expected.get(key)
    if isinstance(raw_groups, list):
        return _field_groups(raw_groups)
    return []


def _field_groups(raw_groups: list[object]) -> list[list[str]]:
    groups: list[list[str]] = []
    for raw_group in raw_groups:
        if isinstance(raw_group, list):
            group = [item for item in raw_group if isinstance(item, str)]
            if group:
                groups.append(group)
        elif isinstance(raw_group, str):
            groups.append([raw_group])
    return groups


def _field_name_matches(expected_name: str, actual_name: str) -> bool:
    expected = _normalized_field_name(expected_name)
    actual = _normalized_field_name(actual_name)
    return expected == actual


def _normalized_field_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return "".join(ch for ch in ascii_value.casefold() if ch.isalnum())


def _normalized_words(value: str) -> set[str]:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    normalized = "".join(ch.casefold() if ch.isalnum() else " " for ch in ascii_value)
    return {word for word in normalized.split() if word}


def _primary_material_form_fields(value: object) -> list[str]:
    names = _string_list(value)
    suspicious_tokens = (
        "audio",
        "document",
        "documents",
        "file",
        "files",
        "fil",
        "filer",
        "dokument",
        "ljud",
        "text",
        "transcript",
        "transkription",
    )
    return [
        name
        for name in names
        if any(token in name.casefold() for token in suspicious_tokens)
    ]


def _non_terminal_artifact_confusion_steps(summary: Mapping[str, Any]) -> list[int]:
    terminal_output = summary.get("terminal_output_type")
    if terminal_output not in {"pdf", "docx"}:
        return []
    steps = summary.get("steps")
    if not isinstance(steps, list) or len(steps) < 2:
        return []
    artifact_token = _normalized_field_name(str(terminal_output))
    mechanical_tokens = {
        "create",
        "generate",
        "generera",
        "make",
        "render",
        "rendera",
        "skapa",
    }
    confused_steps: list[int] = []
    for raw_step in steps[:-1]:
        if not isinstance(raw_step, Mapping) or raw_step.get("output_type") != "text":
            continue
        haystack = " ".join(
            str(raw_step.get(key) or "") for key in ("name", "instruction_excerpt")
        )
        words = _normalized_words(haystack)
        if artifact_token in words and words.intersection(mechanical_tokens):
            order = raw_step.get("order")
            if isinstance(order, int):
                confused_steps.append(order)
    return confused_steps


def _source_context_warnings(summary: Mapping[str, Any]) -> list[str]:
    warnings: list[str] = []
    steps = _summary_steps(summary)
    if not steps:
        return warnings

    first_step = steps[0]
    if (
        first_step.get("input_source") == "flow_input"
        and first_step.get("input_type") in {"document", "file"}
        and first_step.get("output_type") == "json"
    ):
        warnings.append(
            "primary document material is narrowed to JSON in the first step; "
            "inspect whether the source-reader captures all downstream fields"
        )

    json_laundering_steps = [
        step.get("order")
        for step in steps[1:]
        if step.get("input_type") == "json"
        and step.get("output_type") == "json"
        and step.get("source_ref_count") == 0
    ]
    if json_laundering_steps:
        warnings.append(
            "JSON-to-JSON step without explicit refs may launder or over-compress "
            f"source detail: {json_laundering_steps}"
        )

    high_fanout_steps = [
        step.get("order")
        for step in steps
        if _int_value(step.get("source_ref_count")) is not None
        and _int_value(step.get("source_ref_count")) >= 6
    ]
    if high_fanout_steps:
        warnings.append(
            "high source_ref fan-out can pollute model context on large runs; "
            f"inspect channel budgets for steps: {high_fanout_steps}"
        )

    if summary.get("all_previous_step_count", 0):
        warnings.append(
            "all_previous_steps fan-out can grow with every step; prefer typed "
            "source_refs unless the broad context is intentional"
        )

    cleanup_chain = _post_json_text_cleanup_steps(steps)
    if len(cleanup_chain) > 1:
        warnings.append(
            "multiple text cleanup/finalization steps after structured extraction "
            f"may add lossy hops and token cost: {cleanup_chain}"
        )
    return warnings


def _generic_primary_reader_envelope_steps(summary: Mapping[str, Any]) -> list[int]:
    steps = _summary_steps(summary)
    matching_steps: list[int] = []
    for step in steps:
        properties = step.get("output_contract_properties")
        property_names = set(properties) if isinstance(properties, list) else set()
        if not {"source_facts", "uncertainties"}.issubset(property_names):
            continue
        if step.get("input_source") != "flow_input":
            continue
        if step.get("input_type") not in {"document", "file", "audio"}:
            continue
        order = _int_value(step.get("order"))
        if order is not None:
            matching_steps.append(order)
    return matching_steps


def _source_context_metrics(summary: Mapping[str, Any]) -> JsonObject:
    steps = _summary_steps(summary)
    source_ref_counts = [
        _int_value(step.get("source_ref_count")) or 0 for step in steps
    ]
    instruction_bytes = [
        _int_value(step.get("instruction_bytes")) or 0 for step in steps
    ]
    terminal_step = steps[-1] if steps else {}
    return {
        "total_source_ref_count": sum(source_ref_counts),
        "max_source_ref_count": max(source_ref_counts, default=0),
        "max_instruction_bytes": max(instruction_bytes, default=0),
        "json_to_json_step_count": sum(
            1
            for step in steps
            if step.get("input_type") == "json" and step.get("output_type") == "json"
        ),
        "post_json_text_cleanup_step_count": len(_post_json_text_cleanup_steps(steps)),
        "primary_reader_outputs_json": bool(
            steps
            and steps[0].get("input_source") == "flow_input"
            and steps[0].get("input_type") in {"document", "file"}
            and steps[0].get("output_type") == "json"
        ),
        "renderer_is_previous_step_bound": (
            terminal_step.get("output_mode") == "render_verbatim"
            and terminal_step.get("input_source") == "previous_step"
            and terminal_step.get("implicit_previous_step") is True
        ),
    }


def _post_json_text_cleanup_steps(steps: list[Mapping[str, Any]]) -> list[int]:
    json_orders = [
        _int_value(step.get("order"))
        for step in steps
        if step.get("output_type") == "json"
    ]
    last_json_order = max(
        (order for order in json_orders if order is not None),
        default=None,
    )
    if last_json_order is None:
        return []
    terminal_order = _int_value(steps[-1].get("order")) if steps else None
    return [
        order
        for step in steps
        if (order := _int_value(step.get("order"))) is not None
        and order > last_json_order
        and order != terminal_order
        and step.get("output_type") == "text"
    ]


def _summary_steps(summary: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    steps = summary.get("steps")
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, Mapping)]


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _clean_strings(value: object) -> list[str]:
    return [item.strip() for item in _string_list(value) if item.strip()]


def _string_values_from_keys(
    payload: Mapping[str, Any],
    keys: tuple[str, ...],
) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            values.extend(part.strip() for part in value.split(",") if part.strip())
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str) and item)
    return values


def _extend_unique_strings(target: list[str], values: list[str]) -> None:
    seen = set(target)
    for value in values:
        if value in seen:
            continue
        target.append(value)
        seen.add(value)


def _int_value(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing string field: {key}")
    return value


def _optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _print_observation(
    *,
    label: str,
    result: Mapping[str, object],
    bundle_path: Path,
) -> None:
    """Report one finished observation as a single block.

    Concurrent observations interleave, so per-line progress printing would
    shred the log. One block per observation stays readable at any concurrency
    and reports the primary metric — conformance — beside the mechanics.
    """

    print(
        f"\n=== {label} ===\n"
        f"outcome={result.get('outcome_class')} "
        f"conformance={result.get('expectation_verdict')} "
        f"steps={result.get('step_count')}\n"
        f"saved bundle {bundle_path}"
    )
    # Failures stay on stderr, where every other failure in this script goes.
    failures = [
        f"{label_text}: {', '.join(names)}"
        for label_text, key in (
            ("case quality checks failed", "failed_checks"),
            ("case evidence checks failed", "evidence_failed_checks"),
            ("case identity checks failed", "identity_failed_checks"),
        )
        if (names := _failed_check_names({"failed_checks": result.get(key)}))
    ]
    if failures:
        print("\n".join(failures), file=sys.stderr)


def _print_summary(summary: object, bundle_path: Path) -> None:
    print(f"saved bundle {bundle_path}")
    if not isinstance(summary, Mapping):
        return
    print(
        "plan summary: "
        f"steps={summary.get('step_count')} "
        f"question_steps={summary.get('question_binding_steps')} "
        f"source_ref_steps={summary.get('source_ref_steps')} "
        f"implicit_previous_steps={summary.get('implicit_previous_step_steps')}"
    )
    steps = summary.get("steps")
    if not isinstance(steps, list):
        return
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        print(
            f"  {step.get('order')}. {step.get('name')} "
            f"{step.get('input_type')}->{step.get('output_type')} "
            f"source={step.get('input_source')} "
            f"refs={step.get('source_ref_count')} "
            f"question={step.get('has_question')}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
