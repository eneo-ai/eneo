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
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

JsonObject = dict[str, Any]
DEFAULT_CASES_FILE = Path(__file__).with_name("ai_builder_api_battle_cases.json")
DEFAULT_CONFIRM_MESSAGE = "Ja, det stämmer. Bygg planen."


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
    file_id_envs: tuple[str, ...] = ()
    runtime_file_path_envs: tuple[str, ...] = ()
    scripted_question_answers: JsonObject | None = None


@dataclass(frozen=True, slots=True)
class ReleaseThresholds:
    max_case_errors: int
    max_quality_failures: int
    max_required_skips: int


@dataclass(frozen=True, slots=True)
class ReleaseGate:
    required_case_ids: tuple[str, ...]
    thresholds: ReleaseThresholds
    artifact_schema_version: str = "ai-builder-live-release.v1"
    require_clean_source: bool = False


def main() -> int:
    args = _parse_args()
    if args.reanalyze_bundle:
        return _reanalyze_bundles(
            bundle_paths=[Path(path) for path in args.reanalyze_bundle],
            output_dir=Path(args.output_dir),
            expected_overrides_by_case_id=_expected_overrides_from_args(args),
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
        if missing_envs := _missing_file_id_envs(case, args):
            skipped = _skipped_case_bundle(
                case=case,
                repetition=None,
                missing_envs=missing_envs,
            )
            skipped_path = _write_bundle(
                output_dir,
                skipped,
                suffix=f"{case.case_id}-skipped",
            )
            print(f"case skipped: {skipped['skip_reason']}")
            print(f"skipped bundle: {skipped_path}")
            return 1 if case.required else 0
        bundle = _run_case(
            case=case,
            config=config,
            args=args,
            existing_session_id=args.session_id,
            artifact_output_dir=output_dir,
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
    if args.run_suite or args.cases_file or args.case_id:
        cases_file = Path(args.cases_file) if args.cases_file else DEFAULT_CASES_FILE
        cases = _read_cases_file(cases_file)
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
        "file_id_envs",
        "runtime_file_path_envs",
        "scripted_question_answers",
    }
)
_EXPECTATION_KEYS = frozenset(
    {
        "allow_question_instead_of_plan",
        "expected_classifier_slots",
        "expected_file_roles",
        "expected_form_field_groups",
        "expected_leaf_output_field_groups",
        "expected_output_modes",
        "expected_question_event_count",
        "expected_question_event_ids",
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
        "max_steps",
        "min_form_field_count",
        "min_json_steps",
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
    raw_cases = payload.get("cases") if isinstance(payload, Mapping) else None
    if not isinstance(raw_cases, list):
        raise ValueError(f"{path} must contain a top-level 'cases' list.")

    cases: list[BattleCase] = []
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
        file_ids = raw_case.get("file_ids")
        if file_ids is None:
            file_ids = []
        if not isinstance(file_ids, list) or not all(
            isinstance(file_id, str) for file_id in file_ids
        ):
            raise ValueError(f"{path} case {case_id}.file_ids must be a string list.")
        file_id_envs = raw_case.get("file_id_envs")
        if file_id_envs is None:
            file_id_envs = []
        if not isinstance(file_id_envs, list) or not all(
            isinstance(env_name, str) for env_name in file_id_envs
        ):
            raise ValueError(
                f"{path} case {case_id}.file_id_envs must be a string list."
            )
        runtime_file_path_envs = raw_case.get("runtime_file_path_envs")
        if runtime_file_path_envs is None:
            runtime_file_path_envs = []
        if not isinstance(runtime_file_path_envs, list) or not all(
            isinstance(env_name, str) for env_name in runtime_file_path_envs
        ):
            raise ValueError(
                f"{path} case {case_id}.runtime_file_path_envs must be a string list."
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
        expected = raw_case.get("expected")
        if expected is not None and not isinstance(expected, Mapping):
            raise ValueError(f"{path} case {case_id}.expected must be an object.")
        if isinstance(expected, Mapping):
            _validate_classifier_expectations(path, case_id, expected)
            _validate_release_expectations(path, case_id, expected)
        scripted_answers = raw_case.get("scripted_question_answers")
        if scripted_answers is not None and not isinstance(scripted_answers, Mapping):
            raise ValueError(
                f"{path} case {case_id}.scripted_question_answers must be an object."
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
            file_id_envs=tuple(file_id_envs),
            runtime_file_path_envs=tuple(runtime_file_path_envs),
            scripted_question_answers=(
                dict(scripted_answers)
                if isinstance(scripted_answers, Mapping)
                else None
            ),
        )
        if case.execute_flow and not case.apply_plan:
            raise ValueError(
                f"{path} case {case_id} cannot execute without apply_plan=true."
            )
        if case.execute_flow and not case.runtime_file_path_envs:
            raise ValueError(
                f"{path} case {case_id} must declare runtime_file_path_envs."
            )
        cases.append(case)
    return cases


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
        "required_case_ids",
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
    raw_required_ids = raw_gate.get("required_case_ids")
    if (
        not isinstance(raw_required_ids, list)
        or not raw_required_ids
        or not all(
            isinstance(case_id, str) and case_id.strip() for case_id in raw_required_ids
        )
    ):
        raise ValueError(f"{path} release_gate.required_case_ids is invalid.")
    required_case_ids = tuple(raw_required_ids)
    if len(set(required_case_ids)) != len(required_case_ids):
        raise ValueError(f"{path} release_gate.required_case_ids contains duplicates.")
    raw_thresholds = raw_gate.get("thresholds")
    expected_threshold_keys = {
        "max_case_errors",
        "max_quality_failures",
        "max_required_skips",
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
    by_id = {case.case_id: case for case in cases}
    missing_case_ids = set(required_case_ids) - set(by_id)
    if missing_case_ids:
        raise ValueError(
            f"{path} release gate references unknown required case(s): "
            + ", ".join(sorted(missing_case_ids))
        )
    not_required = [
        case_id for case_id in required_case_ids if not by_id[case_id].required
    ]
    if not_required:
        raise ValueError(
            f"{path} release gate case(s) are not marked required: "
            + ", ".join(not_required)
        )
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
    release_gate = release_gate or ReleaseGate(
        required_case_ids=tuple(case.case_id for case in cases if case.required),
        thresholds=ReleaseThresholds(
            max_case_errors=0,
            max_quality_failures=0,
            max_required_skips=0,
        ),
    )
    selected_case_ids = {case.case_id for case in cases}
    missing_required_cases = set(release_gate.required_case_ids) - selected_case_ids
    if missing_required_cases:
        raise ValueError(
            "Release suite omitted required case(s): "
            + ", ".join(sorted(missing_required_cases))
        )
    cases_path = Path(getattr(args, "cases_file", None) or DEFAULT_CASES_FILE)
    requested_model_id = getattr(args, "model_id", None)
    release_identity = _release_run_identity(
        cases=cases,
        cases_path=cases_path,
        requested_model_id=requested_model_id,
        require_clean_source=release_gate.require_clean_source,
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
            "required_case_ids": list(release_gate.required_case_ids),
            "thresholds": {
                "max_case_errors": release_gate.thresholds.max_case_errors,
                "max_quality_failures": (release_gate.thresholds.max_quality_failures),
                "max_required_skips": release_gate.thresholds.max_required_skips,
            },
            "selected_cases": [
                {
                    "id": case.case_id,
                    "required": case.required,
                    "release_dimensions": list(case.release_dimensions),
                    "prompt_sha256": hashlib.sha256(
                        case.prompt.encode("utf-8")
                    ).hexdigest(),
                }
                for case in cases
            ],
        },
    )
    results: list[JsonObject] = []
    case_error_count = 0
    quality_failure_run_count = 0
    skipped_run_count = 0
    required_skipped_run_count = 0
    total_runs = len(cases) * args.repetitions

    run_index = 0
    for repetition in range(1, args.repetitions + 1):
        for case_index, case in enumerate(cases, start=1):
            run_index += 1
            repetition_suffix = f"-r{repetition:02d}" if args.repetitions > 1 else ""
            print(
                "\n=== "
                f"run {run_index}/{total_runs}; "
                f"case {case_index}/{len(cases)}: "
                f"{case.case_id} ({case.complexity}) "
                f"repetition {repetition}/{args.repetitions} ==="
            )
            if missing_envs := _missing_file_id_envs(case, args):
                skipped_run_count += 1
                if case.required:
                    required_skipped_run_count += 1
                skipped = _skipped_case_bundle(
                    case=case,
                    repetition=repetition,
                    missing_envs=missing_envs,
                )
                skipped["artifact_schema_version"] = (
                    release_gate.artifact_schema_version
                )
                if case.required:
                    skipped["release_identity"] = release_identity
                skipped_path = _write_bundle(
                    suite_dir,
                    skipped,
                    suffix=f"{case.case_id}{repetition_suffix}-skipped",
                )
                print(f"case skipped: {skipped['skip_reason']}")
                results.append(_suite_result(skipped, skipped_path))
                continue
            try:
                bundle = _run_case(
                    case=case,
                    config=config,
                    args=args,
                    existing_session_id=None,
                    artifact_output_dir=suite_dir,
                )
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
                    if not isinstance(provenance, Mapping) or not isinstance(
                        checks, list
                    ):
                        raise ValueError(
                            f"required case {case.case_id} has no identity evidence."
                        )
                    checks.extend(
                        _required_case_identity_checks(
                            case=case,
                            release_identity=release_identity,
                            provenance=provenance,
                        )
                    )
                    bundle["release_identity"] = release_identity
                bundle_path = _write_bundle(
                    suite_dir,
                    bundle,
                    suffix=f"{case.case_id}{repetition_suffix}",
                )
                _print_summary(bundle["plan_summary"], bundle_path)
                result = _suite_result(bundle, bundle_path)
                results.append(result)
                if (_int_value(result.get("failed_check_count")) or 0) > 0:
                    quality_failure_run_count += 1
                    failed_names = _failed_check_names(result)
                    print(
                        "case quality checks failed: "
                        + ", ".join(failed_names or ["<unknown>"]),
                        file=sys.stderr,
                    )
            except (HTTPError, URLError, TimeoutError, ValueError) as error:
                case_error_count += 1
                failure = {
                    "artifact_schema_version": release_gate.artifact_schema_version,
                    "artifact_mode": "live_execution_failure",
                    "created_at": time.strftime("%Y%m%dT%H%M%S"),
                    "app_version": LOCAL_APP_VERSION,
                    "case_id": case.case_id,
                    "complexity": case.complexity,
                    "domain": case.domain,
                    "repetition": repetition,
                    **_failure_error_fields(error),
                    "release_identity": release_identity,
                }
                failure_path = _write_bundle(
                    suite_dir,
                    failure,
                    suffix=f"{case.case_id}{repetition_suffix}-failure",
                )
                print(f"case failed: {error}", file=sys.stderr)
                print(f"failure bundle: {failure_path}", file=sys.stderr)
                results.append({**failure, "bundle_path": str(failure_path)})

    try:
        release_identity_recheck = _release_run_identity(
            cases=cases,
            cases_path=cases_path,
            requested_model_id=requested_model_id,
            require_clean_source=release_gate.require_clean_source,
        )
        release_identity_recheck_checks = _release_identity_recheck_checks(
            expected=release_identity,
            actual=release_identity_recheck,
        )
    except (subprocess.CalledProcessError, ValueError) as error:
        release_identity_recheck = {"error": str(error)}
        release_identity_recheck_checks = [
            {
                "name": f"suite_{component}_identity_unchanged",
                "passed": False,
                "actual": str(error),
                "expected": release_identity.get(component),
            }
            for component in ("source", "build", "model", "prompts")
        ]
    suite_identity_failure_count = sum(
        1
        for check in release_identity_recheck_checks
        if check.get("passed") is not True
    )
    threshold_checks = _evaluate_release_thresholds(
        release_gate.thresholds,
        case_error_count=case_error_count,
        quality_failure_run_count=quality_failure_run_count,
        required_skipped_run_count=required_skipped_run_count,
    )
    suite_summary: JsonObject = {
        "artifact_schema_version": release_gate.artifact_schema_version,
        "artifact_mode": "live_execution_summary",
        "created_at": started_at,
        "app_version": LOCAL_APP_VERSION,
        "base_url": config.base_url,
        "space_id": args.space_id,
        "case_count": len(cases),
        "repetitions": args.repetitions,
        "run_count": total_runs,
        "failure_count": (
            case_error_count
            + quality_failure_run_count
            + required_skipped_run_count
            + suite_identity_failure_count
        ),
        "case_error_count": case_error_count,
        "quality_failure_run_count": quality_failure_run_count,
        "skipped_run_count": skipped_run_count,
        "required_skipped_run_count": required_skipped_run_count,
        "suite_identity_failure_count": suite_identity_failure_count,
        "release_threshold_checks": threshold_checks,
        "release_identity": release_identity,
        "release_identity_recheck": release_identity_recheck,
        "release_identity_recheck_checks": release_identity_recheck_checks,
        "results": results,
        "reliability": _suite_reliability_summary(results),
    }
    summary_path = suite_dir / "suite-summary.json"
    _write_json_exclusive(summary_path, suite_summary)
    print(f"\nsuite summary: {summary_path}")
    return (
        1
        if suite_identity_failure_count
        or any(check["passed"] is not True for check in threshold_checks)
        else 0
    )


def _release_run_identity(
    *,
    cases: list[BattleCase],
    cases_path: Path,
    requested_model_id: str | None,
    require_clean_source: bool,
) -> JsonObject:
    tracked_status = _git_output("status", "--porcelain", "--untracked-files=no")
    if require_clean_source and tracked_status:
        raise ValueError(
            "Live release execution requires a clean tracked source revision."
        )
    source_revision = _git_output("rev-parse", "HEAD")
    build = {
        "app_version": LOCAL_APP_VERSION,
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
    prompt_hashes = {
        case.case_id: hashlib.sha256(case.prompt.encode("utf-8")).hexdigest()
        for case in cases
    }
    model = {"requested_id": requested_model_id}
    return {
        "source": {
            "revision": source_revision,
            "revision_sha256": hashlib.sha256(
                source_revision.encode("utf-8")
            ).hexdigest(),
            "tracked_clean": not tracked_status,
        },
        "build": {**build, "sha256": _canonical_sha256(build)},
        "model": {**model, "sha256": _canonical_sha256(model)},
        "prompts": {
            "case_sha256_by_id": prompt_hashes,
            "sha256": _canonical_sha256(prompt_hashes),
        },
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
    build_keys = (
        "app_version",
        "source_revision",
        "harness_sha256",
        "cases_sha256",
    )
    release_build_payload = {key: release_build.get(key) for key in build_keys}
    live_build_payload = {key: live_build.get(key) for key in build_keys}
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
    model_identity_matches = release_model.get("sha256") == _canonical_sha256(
        release_model_payload
    ) and release_model.get("requested_id") == live_model.get("requested_id")

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

    return [
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
            "actual": live_model.get("requested_id"),
            "expected": release_model.get("requested_id"),
        },
        {
            "name": "suite_case_prompt_identity",
            "passed": prompt_identity_matches,
            "actual": live_prompt.get("case_sha256"),
            "expected": release_prompt_hashes.get(case.case_id),
        },
    ]


def _release_identity_recheck_checks(
    *,
    expected: Mapping[str, object],
    actual: Mapping[str, object],
) -> list[JsonObject]:
    return [
        {
            "name": f"suite_{component}_identity_unchanged",
            "passed": actual.get(component) == expected.get(component),
            "actual": actual.get(component),
            "expected": expected.get(component),
        }
        for component in ("source", "build", "model", "prompts")
    ]


def _evaluate_release_thresholds(
    thresholds: ReleaseThresholds,
    *,
    case_error_count: int,
    quality_failure_run_count: int,
    required_skipped_run_count: int,
) -> list[JsonObject]:
    return [
        {
            "name": "max_case_errors",
            "passed": case_error_count <= thresholds.max_case_errors,
            "actual": case_error_count,
            "threshold": thresholds.max_case_errors,
        },
        {
            "name": "max_quality_failures",
            "passed": quality_failure_run_count <= thresholds.max_quality_failures,
            "actual": quality_failure_run_count,
            "threshold": thresholds.max_quality_failures,
        },
        {
            "name": "max_required_skips",
            "passed": required_skipped_run_count <= thresholds.max_required_skips,
            "actual": required_skipped_run_count,
            "threshold": thresholds.max_required_skips,
        },
    ]


def _run_case(
    *,
    case: BattleCase,
    config: ApiConfig,
    args: argparse.Namespace,
    existing_session_id: str | None,
    artifact_output_dir: Path,
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

    file_ids = _case_file_ids(case, args)
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

    answered_questions: set[str] = set()
    confirmed_requirement_versions: set[str] = set()
    while interactions[-1].get("plan_id") is None and len(interactions) < 6:
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
            answer = _scripted_question_answer(
                question=question,
                scripted_answers=case.scripted_question_answers or {},
            )
            question_id = _optional_string(question, "question_id")
            if (
                answer is not None
                and question_id is not None
                and question_id not in answered_questions
            ):
                answered_questions.add(question_id)
                interactions.append(
                    _send_and_fetch(
                        config=config,
                        session_id=session_id,
                        message=answer["message"],
                        model_id=args.model_id,
                        file_ids=(),
                        ui_language=args.ui_language,
                        question_answer=answer["question_answer"],
                    )
                )
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
            runtime_file_paths=_case_runtime_file_paths(case),
            timeout_seconds=args.timeout_seconds,
            artifact_output_dir=artifact_output_dir,
            case_id=case.case_id,
        )
    event_summary = _interaction_event_summary(interactions)
    failure_summary = _failure_summary(event_summary)
    classifier_diagnostics = _request_json(
        config=config,
        method="GET",
        path=(f"/flows/ai-builder/sessions/{session_id}/_diagnostics/classifier-slots"),
    )
    quality_report = _quality_report(
        plan=plan,
        summary=plan_summary,
        expected=case.expected or {},
        event_summary=event_summary,
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
        latest_session=(
            final_interaction.get("latest_session")
            if isinstance(final_interaction.get("latest_session"), Mapping)
            else None
        ),
        classifier_diagnostics=classifier_diagnostics,
        requested_model_id=args.model_id,
        event_summary=event_summary,
    )
    if case.required:
        checks = quality_report.get("checks")
        if isinstance(checks, list):
            checks.extend(
                _live_provenance_checks(
                    live_execution_provenance,
                    expected=case.expected or {},
                )
            )

    return {
        "artifact_mode": "live_execution",
        "live_execution_provenance": live_execution_provenance,
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
            "prompt": case.prompt,
            "expected": case.expected or {},
            "file_ids": list(file_ids),
            "file_id_envs": list(case.file_id_envs),
            "runtime_file_path_envs": list(case.runtime_file_path_envs),
            "scripted_question_answers": case.scripted_question_answers or {},
        },
        "session_id": session_id,
        "plan_id": final_interaction.get("plan_id"),
        "initial_session": initial_session,
        "interactions": interactions,
        "latest_session": final_interaction.get("latest_session"),
        "plan": plan,
        "plan_summary": plan_summary,
        "event_summary": event_summary,
        "failure_summary": failure_summary,
        "classifier_diagnostics": classifier_diagnostics,
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


def _upload_runtime_file(
    *,
    config: ApiConfig,
    flow_id: str,
    step_id: str,
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
        f"{config.base_url}/flows/{flow_id}/steps/{step_id}/runtime-files/",
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
        raise ValueError(f"Runtime upload for {source_path.name} returned no object.")
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


def _scripted_question_answer(
    *,
    question: Mapping[str, Any],
    scripted_answers: Mapping[str, Any],
) -> JsonObject | None:
    question_id = _optional_string(question, "question_id")
    if question_id is None or question_id not in scripted_answers:
        return None
    answer_config = scripted_answers[question_id]
    if isinstance(answer_config, str):
        answer_config = {"selected_option_ids": [answer_config]}
    if not isinstance(answer_config, Mapping):
        raise ValueError(f"Scripted answer for {question_id} must be a string/object.")

    custom_value = answer_config.get("custom_value")
    if isinstance(custom_value, str) and custom_value.strip():
        custom_text = custom_value.strip()
        return {
            "message": custom_text,
            "question_answer": {
                "kind": "structured_question_answer",
                "question_id": question_id,
                "custom_value": custom_text,
            },
        }

    selected_ids = _scripted_selected_option_ids(answer_config)
    if not selected_ids:
        return None
    options = _question_options_by_key(question)
    missing = [option_id for option_id in selected_ids if option_id not in options]
    if missing:
        raise ValueError(
            f"Scripted answer for {question_id} references unknown option(s): "
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
        "question_answer": {
            "kind": "structured_question_answer",
            "question_id": question_id,
            "selected_option_ids": selected_ids,
            "selected_values": selected_values,
        },
    }


def _scripted_selected_option_ids(answer_config: Mapping[str, Any]) -> list[str]:
    for key in ("selected_option_ids", "option_ids"):
        value = answer_config.get(key)
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return value
    for key in ("selected_option_id", "option_id"):
        value = answer_config.get(key)
        if isinstance(value, str) and value:
            return [value]
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
        for key in ("id", "value", "label"):
            value = raw_option.get(key)
            if isinstance(value, str) and value:
                options[value] = raw_option
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


def _case_file_ids(case: BattleCase, args: argparse.Namespace) -> tuple[str, ...]:
    cli_file_ids = tuple(getattr(args, "file_ids", None) or ())
    if cli_file_ids:
        return cli_file_ids
    missing_envs = _missing_file_id_envs(case, args)
    if missing_envs:
        raise ValueError(
            f"case {case.case_id} requires file id env var(s): "
            + ", ".join(missing_envs)
        )
    return (*case.file_ids, *_file_ids_from_envs(case.file_id_envs))


def _missing_file_id_envs(
    case: BattleCase,
    args: argparse.Namespace,
) -> tuple[str, ...]:
    if tuple(getattr(args, "file_ids", None) or ()):
        return ()
    return tuple(
        env_name
        for env_name in (*case.file_id_envs, *case.runtime_file_path_envs)
        if not os.getenv(env_name, "").strip()
    )


def _file_ids_from_envs(env_names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        os.environ[env_name].strip()
        for env_name in env_names
        if os.getenv(env_name, "").strip()
    )


def _case_runtime_file_paths(case: BattleCase) -> tuple[Path, ...]:
    paths = tuple(
        Path(os.environ[env_name].strip()) for env_name in case.runtime_file_path_envs
    )
    invalid_paths = [str(path) for path in paths if not path.is_file()]
    if invalid_paths:
        raise ValueError(
            f"case {case.case_id} runtime source path(s) are not readable files: "
            + ", ".join(invalid_paths)
        )
    return paths


def _skipped_case_bundle(
    *,
    case: BattleCase,
    repetition: int | None,
    missing_envs: tuple[str, ...],
) -> JsonObject:
    return {
        "artifact_mode": "live_execution",
        "live_execution_provenance": _live_execution_provenance(
            case=case,
            latest_session=None,
            classifier_diagnostics=None,
            requested_model_id=None,
        ),
        "created_at": time.strftime("%Y%m%dT%H%M%S"),
        "app_version": LOCAL_APP_VERSION,
        "case": {
            "id": case.case_id,
            "complexity": case.complexity,
            "domain": case.domain,
            "required": case.required,
            "file_id_envs": list(case.file_id_envs),
            "runtime_file_path_envs": list(case.runtime_file_path_envs),
        },
        "repetition": repetition,
        "skipped": True,
        "skip_reason": (
            "Missing file-id environment variable(s): " + ", ".join(missing_envs)
        ),
    }


def _write_bundle(output_dir: Path, bundle: JsonObject, *, suffix: str) -> Path:
    created_at = str(bundle.get("created_at") or time.strftime("%Y%m%dT%H%M%S"))
    safe_suffix = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in suffix)
    path = output_dir / f"ai-builder-api-battle-test-{created_at}-{safe_suffix}.json"
    _write_json_exclusive(path, bundle)
    return path


def _live_execution_provenance(
    *,
    case: BattleCase,
    latest_session: Mapping[str, object] | None,
    classifier_diagnostics: Mapping[str, object] | None,
    requested_model_id: str | None,
    event_summary: Mapping[str, object] | None = None,
) -> JsonObject:
    source_revision = _git_output("rev-parse", "HEAD")
    tracked_status = _git_output("status", "--porcelain", "--untracked-files=no")
    source_revision_sha256 = hashlib.sha256(source_revision.encode("utf-8")).hexdigest()
    harness_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    cases_sha256 = hashlib.sha256(DEFAULT_CASES_FILE.read_bytes()).hexdigest()
    build_payload = {
        "app_version": LOCAL_APP_VERSION,
        "source_revision": source_revision,
        "harness_sha256": harness_sha256,
        "cases_sha256": cases_sha256,
    }
    telemetry = (
        latest_session.get("telemetry")
        if isinstance(latest_session, Mapping)
        and isinstance(latest_session.get("telemetry"), Mapping)
        else {}
    )
    model_ids = list(
        dict.fromkeys(
            _clean_strings(
                [
                    requested_model_id,
                    telemetry.get("last_model")
                    if isinstance(telemetry, Mapping)
                    else None,
                    *[
                        run.get("model")
                        for run in _classifier_runs(classifier_diagnostics)
                        if isinstance(run.get("model"), str)
                    ],
                ]
            )
        )
    )
    classifier_prompt_hashes = list(
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
    progress_payload: JsonObject = {
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
            "sha256": _canonical_sha256(build_payload),
        },
        "model": {
            "requested_id": requested_model_id,
            "observed_ids": model_ids,
            "sha256": _canonical_sha256(model_ids),
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
            **progress_payload,
            "fingerprint": _canonical_sha256(progress_payload),
        },
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "model_calls": model_calls,
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
    model_complete = bool(observed_model_ids) and _is_sha256(model.get("sha256"))
    classifier_hashes = _string_list(prompt.get("classifier_hashes"))
    prompt_complete = (
        _is_sha256(prompt.get("case_sha256"))
        and bool(classifier_hashes)
        and all(_is_sha256(item) for item in classifier_hashes)
    )
    usage_complete = all(
        isinstance(usage.get(key), int) and usage.get(key) >= 0
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "model_calls",
        )
    ) and all(
        isinstance(raw_reads.get(key), int) and raw_reads.get(key) >= 0
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
    progress_payload = {
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
    warnings = report.get("warnings") if isinstance(report, Mapping) else []
    metrics = report.get("metrics") if isinstance(report, Mapping) else {}
    event_summary = bundle.get("event_summary")
    event_summary = event_summary if isinstance(event_summary, Mapping) else {}
    failed_checks = [
        check
        for check in checks
        if isinstance(check, Mapping) and check.get("passed") is not True
    ]
    return {
        "case_id": bundle.get("case", {}).get("id")
        if isinstance(bundle.get("case"), Mapping)
        else None,
        "session_id": bundle.get("session_id"),
        "plan_id": bundle.get("plan_id"),
        "repetition": bundle.get("repetition"),
        "bundle_path": str(bundle_path),
        "skipped": bundle.get("skipped") is True,
        "skip_reason": bundle.get("skip_reason")
        if isinstance(bundle.get("skip_reason"), str)
        else None,
        "step_count": bundle.get("plan_summary", {}).get("step_count")
        if isinstance(bundle.get("plan_summary"), Mapping)
        else None,
        "failed_check_count": len(failed_checks),
        "failed_checks": failed_checks,
        "warning_count": len(warnings) if isinstance(warnings, list) else 0,
        "warnings": warnings if isinstance(warnings, list) else [],
        "metrics": metrics if isinstance(metrics, Mapping) else {},
        "event_summary": dict(event_summary),
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
        if result.get("skipped") is True:
            continue
        case_id = result.get("case_id")
        if isinstance(case_id, str):
            grouped.setdefault(case_id, []).append(result)

    summary: JsonObject = {}
    for case_id, case_results in grouped.items():
        run_count = len(case_results)
        plan_count = sum(1 for result in case_results if result.get("plan_id"))
        repair_failure_count = 0
        invalid_plan_count = 0
        text_only_question_count = 0
        assumptions: list[str] = []
        error_code_counts: dict[str, int] = {}
        for result in case_results:
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
            "plan_created_count": plan_count,
            "plan_rate": plan_count / run_count if run_count else None,
            "error_code_counts": error_code_counts,
            "self_correction_invalid_plan_count": invalid_plan_count,
            "self_correction_quality_failure_count": repair_failure_count,
            "server_ask_question_text_only_count": text_only_question_count,
            "assumptions": assumptions,
        }
    return summary


def _reanalyze_bundles(
    *,
    bundle_paths: list[Path],
    output_dir: Path,
    expected_overrides_by_case_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)
    failures = 0
    expected_overrides_by_case_id = expected_overrides_by_case_id or {}
    for bundle_path in bundle_paths:
        try:
            source_bytes = bundle_path.read_bytes()
            bundle = json.loads(source_bytes.decode("utf-8"))
            if not isinstance(bundle, dict):
                raise ValueError(f"{bundle_path} did not contain a JSON object.")
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
            report = _quality_report(
                plan=plan,
                summary=summary,
                expected=expected,
                event_summary=event_summary,
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
            refreshed = {
                **bundle,
                "artifact_mode": "reanalysis",
                "reanalyzed_at": time.strftime("%Y%m%dT%H%M%S"),
                "reanalysis_provenance": {
                    "source_bundle_sha256": hashlib.sha256(source_bytes).hexdigest(),
                    "reanalyzer_source_revision": _git_output("rev-parse", "HEAD"),
                    "reanalyzer_harness_sha256": hashlib.sha256(
                        Path(__file__).read_bytes()
                    ).hexdigest(),
                    "expectations_sha256": _canonical_sha256(expected),
                },
                "plan_summary": summary,
                "event_summary": event_summary,
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
        "question_event_ids": list(dict.fromkeys(question_event_ids)),
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
    classifier_diagnostics: Mapping[str, object] | None = None,
    attached_file_ids: tuple[str, ...] = (),
    applied_flow: Mapping[str, object] | None = None,
    runtime_evidence: Mapping[str, object] | None = None,
) -> JsonObject:
    checks: list[JsonObject] = []
    warnings: list[str] = []
    event_summary = event_summary or {}

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
        file_id = _expected_file_id(expected_role, attached_file_ids)
        if file_id is None:
            add_check(
                "classifier_file_role:<unresolved>",
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
            f"classifier_file_role:{file_id}",
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
    if plan is None:
        return {"checks": checks, "warnings": warnings}

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

    expected_leaf_fields = _field_expectation_groups(expected)
    if expected_leaf_fields:
        actual_leaf_fields = _all_output_fields(summary)
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
            actual_leaf_fields,
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
    model_call_count = 0
    for step in steps:
        _extend_unique_strings(
            runtime_file_ids,
            _string_list(step.get("runtime_input_file_ids")),
        )
        output_payload = step.get("output_payload_json")
        step_documents = _first_mapping_list_for_key(output_payload, "documents")
        if step_documents is not None:
            documents.extend(step_documents)
        parameters = step.get("model_parameters_json")
        per_source_calls = (
            _int_value(parameters.get("per_source_call_count"))
            if isinstance(parameters, Mapping)
            else None
        )
        if per_source_calls is not None and per_source_calls > 0:
            model_call_count += per_source_calls
        elif (_int_value(step.get("num_tokens_input")) or 0) > 0 or (
            _int_value(step.get("num_tokens_output")) or 0
        ) > 0:
            model_call_count += 1

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
                and model_call_count == expected_model_calls
            ),
            "actual": model_call_count,
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


def _all_output_fields(summary: Mapping[str, Any]) -> list[str]:
    fields: list[str] = []
    steps = summary.get("steps")
    if not isinstance(steps, list):
        return fields
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        for key in (
            "output_contract_properties",
            "output_contract_nested_properties",
            "output_contract_leaf_properties",
        ):
            raw = step.get(key)
            if isinstance(raw, list):
                fields.extend(str(field) for field in raw)
    return list(dict.fromkeys(fields))


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
