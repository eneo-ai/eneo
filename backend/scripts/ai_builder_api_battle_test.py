#!/usr/bin/env python3
"""Run a local AI Builder create-session smoke test through the public API.

This script is intentionally API-facing: it exercises the same session/message
flow the UI uses, then saves the raw session, stream events, and stored plan.
Set ENEO_API_KEY in the environment; never commit local keys into this file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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


@dataclass(frozen=True, slots=True)
class BattleCase:
    case_id: str
    prompt: str
    complexity: str = "custom"
    domain: str = "custom"
    expected: JsonObject | None = None
    file_ids: tuple[str, ...] = ()
    file_id_envs: tuple[str, ...] = ()
    scripted_question_answers: JsonObject | None = None


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

    try:
        cases = _cases_from_args(args)
        if args.run_suite or len(cases) > 1:
            return _run_suite(
                cases=cases,
                config=config,
                args=args,
                output_dir=output_dir,
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
            return 0
        bundle = _run_case(
            case=case,
            config=config,
            args=args,
            existing_session_id=args.session_id,
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
            "error": str(error),
        }
        bundle_path.write_text(
            json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
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


def _read_cases_file(path: Path) -> list[BattleCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases") if isinstance(payload, Mapping) else None
    if not isinstance(raw_cases, list):
        raise ValueError(f"{path} must contain a top-level 'cases' list.")

    cases: list[BattleCase] = []
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, Mapping):
            raise ValueError(f"{path} cases[{index}] must be an object.")
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
        expected = raw_case.get("expected")
        if expected is not None and not isinstance(expected, Mapping):
            raise ValueError(f"{path} case {case_id}.expected must be an object.")
        scripted_answers = raw_case.get("scripted_question_answers")
        if scripted_answers is not None and not isinstance(scripted_answers, Mapping):
            raise ValueError(
                f"{path} case {case_id}.scripted_question_answers must be an object."
            )
        cases.append(
            BattleCase(
                case_id=case_id,
                prompt=prompt,
                complexity=str(raw_case.get("complexity") or "custom"),
                domain=str(raw_case.get("domain") or "custom"),
                expected=dict(expected) if isinstance(expected, Mapping) else None,
                file_ids=tuple(file_ids),
                file_id_envs=tuple(file_id_envs),
                scripted_question_answers=(
                    dict(scripted_answers)
                    if isinstance(scripted_answers, Mapping)
                    else None
                ),
            )
        )
    return cases


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
) -> int:
    if args.repetitions < 1:
        raise ValueError("--repetitions must be >= 1.")
    started_at = time.strftime("%Y%m%dT%H%M%S")
    suite_dir = output_dir / f"ai-builder-api-battle-suite-{started_at}"
    suite_dir.mkdir(parents=True, exist_ok=True)
    results: list[JsonObject] = []
    case_error_count = 0
    quality_failure_run_count = 0
    skipped_run_count = 0
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
                skipped = _skipped_case_bundle(
                    case=case,
                    repetition=repetition,
                    missing_envs=missing_envs,
                )
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
                )
                bundle["repetition"] = repetition
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
                    "created_at": time.strftime("%Y%m%dT%H%M%S"),
                    "app_version": LOCAL_APP_VERSION,
                    "case_id": case.case_id,
                    "complexity": case.complexity,
                    "domain": case.domain,
                    "repetition": repetition,
                    "error": str(error),
                }
                failure_path = _write_bundle(
                    suite_dir,
                    failure,
                    suffix=f"{case.case_id}{repetition_suffix}-failure",
                )
                print(f"case failed: {error}", file=sys.stderr)
                print(f"failure bundle: {failure_path}", file=sys.stderr)
                results.append({**failure, "bundle_path": str(failure_path)})

    suite_summary: JsonObject = {
        "created_at": started_at,
        "app_version": LOCAL_APP_VERSION,
        "base_url": config.base_url,
        "space_id": args.space_id,
        "case_count": len(cases),
        "repetitions": args.repetitions,
        "run_count": total_runs,
        "failure_count": case_error_count + quality_failure_run_count,
        "case_error_count": case_error_count,
        "quality_failure_run_count": quality_failure_run_count,
        "skipped_run_count": skipped_run_count,
        "results": results,
        "reliability": _suite_reliability_summary(results),
    }
    summary_path = suite_dir / "suite-summary.json"
    summary_path.write_text(
        json.dumps(suite_summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"\nsuite summary: {summary_path}")
    return 1 if case_error_count or quality_failure_run_count else 0


def _run_case(
    *,
    case: BattleCase,
    config: ApiConfig,
    args: argparse.Namespace,
    existing_session_id: str | None,
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
    event_summary = _interaction_event_summary(interactions)
    failure_summary = _failure_summary(event_summary)
    quality_report = _quality_report(
        plan=plan,
        summary=plan_summary,
        expected=case.expected or {},
        event_summary=event_summary,
    )

    return {
        "created_at": started_at,
        "app_version": LOCAL_APP_VERSION,
        "base_url": config.base_url,
        "space_id": args.space_id,
        "case": {
            "id": case.case_id,
            "complexity": case.complexity,
            "domain": case.domain,
            "prompt": case.prompt,
            "expected": case.expected or {},
            "file_ids": list(file_ids),
            "file_id_envs": list(case.file_id_envs),
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
        "quality_report": quality_report,
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
    payload: JsonObject = {
        "message": message,
        "model_id": model_id,
        "file_ids": list(file_ids) or None,
        "question_answer": question_answer,
        "ui_language": ui_language,
    }
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
    return {
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
        for env_name in case.file_id_envs
        if not os.getenv(env_name, "").strip()
    )


def _file_ids_from_envs(env_names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        os.environ[env_name].strip()
        for env_name in env_names
        if os.getenv(env_name, "").strip()
    )


def _skipped_case_bundle(
    *,
    case: BattleCase,
    repetition: int | None,
    missing_envs: tuple[str, ...],
) -> JsonObject:
    return {
        "created_at": time.strftime("%Y%m%dT%H%M%S"),
        "app_version": LOCAL_APP_VERSION,
        "case": {
            "id": case.case_id,
            "complexity": case.complexity,
            "domain": case.domain,
            "file_id_envs": list(case.file_id_envs),
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
    path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


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
    failures = 0
    expected_overrides_by_case_id = expected_overrides_by_case_id or {}
    for bundle_path in bundle_paths:
        try:
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
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
            )
            refreshed = {
                **bundle,
                "reanalyzed_at": time.strftime("%Y%m%dT%H%M%S"),
                "plan_summary": summary,
                "event_summary": event_summary,
                "failure_summary": _failure_summary(event_summary),
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
    path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
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


def _quality_report(
    *,
    plan: JsonObject | None,
    summary: JsonObject,
    expected: Mapping[str, Any],
    event_summary: Mapping[str, Any] | None = None,
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
