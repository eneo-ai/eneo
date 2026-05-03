from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from intric.flows.ai_builder.ai_builder_api_models import (
    PlanResponse,
    SessionModelOption,
    SessionModelsResponse,
    SessionTelemetrySummary,
)
from intric.flows.ai_builder.ai_builder_domain_models import FlowDraftSpecCore
from intric.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_DONE,
    SSE_EVENT_ERROR,
    SSE_EVENT_PLAN,
    SSE_EVENT_QUESTION,
    SSE_EVENT_REQUIREMENTS_SUMMARY,
    SSE_EVENT_STATUS,
    SSE_EVENT_TEXT,
    SSE_EVENT_USAGE,
)
from tests.integration.flows.ai_builder.benchmark.cases import (
    MANUAL_API_EVAL_CASE_IDS,
    MANUAL_API_EVAL_SCENARIOS,
    ManualApiEvalScenario,
    ManualApiEvaluationMode,
    ReliabilityCorpusCase,
    manual_api_eval_cases,
)
from tests.integration.flows.ai_builder.benchmark.eval_support import (
    redacted_sha256,
    serialize_dataclass_scorecard,
    utc_now_iso,
)
from tests.integration.flows.ai_builder.benchmark.manual_api_scoring import (
    DERIVATION_RULES_VERSION,
    PlanDerivedMechanics,
    PlanObservedMechanics,
    score_plan_mechanics,
)

ENV_LOCAL_API_BASE = "ENEO_LOCAL_API_BASE"
ENV_LOCAL_SPACE_ID = "ENEO_LOCAL_SPACE_ID"
ENV_LOCAL_API_KEY = "ENEO_LOCAL_API_KEY"
SCORECARD_SCHEMA_VERSION = 1
DEFAULT_RUNS_PER_PROMPT = 3
MAX_SSE_STREAM_BYTES = 2_000_000
AI_BUILDER_OPERATION_IDS = frozenset(
    {
        "create_ai_builder_session",
        "list_ai_builder_sessions",
        "send_ai_builder_message",
        "get_ai_builder_session",
        "get_ai_builder_models",
        "get_ai_builder_plan",
        "list_ai_builder_session_plans",
        "cancel_ai_builder_session",
        "approve_ai_builder_plan",
        "apply_ai_builder_plan",
        "revise_ai_builder_plan",
        "detach_ai_builder_attachment",
    }
)
EXECUTED_RUN_OPERATION_IDS = frozenset(
    {
        "create_flow_run",
        "get_flow_graph",
        "list_flow_run_steps",
        "get_flow_run_evidence_alias",
        "export_flow_run_evidence_alias",
        "generate_flow_run_artifact_signed_url",
    }
)
KNOWN_SSE_EVENTS = frozenset(
    {
        SSE_EVENT_TEXT,
        SSE_EVENT_PLAN,
        SSE_EVENT_QUESTION,
        SSE_EVENT_REQUIREMENTS_SUMMARY,
        SSE_EVENT_ERROR,
        SSE_EVENT_STATUS,
        SSE_EVENT_USAGE,
        SSE_EVENT_DONE,
    }
)


@dataclass(frozen=True, slots=True)
class RedactedLocalApiConfig:
    api_base_sha256: str | None
    space_id_hash: str | None
    api_key_present: bool


@dataclass(frozen=True, slots=True)
class LocalApiConfig:
    api_base: str
    space_id: UUID
    api_key: str
    redacted: RedactedLocalApiConfig


@dataclass(frozen=True, slots=True)
class ManualApiModelSummary:
    id_hash: str | None = None
    name: str | None = None
    provider: str | None = None
    temperature: float | None = None


@dataclass(frozen=True, slots=True)
class ManualApiWorkspaceFixture:
    space_id_hash: str | None = None
    enabled_resource_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class ManualApiObserved:
    session_id_hash: str | None = None
    plan_id_hash: str | None = None
    flow_id_if_applied_hash: str | None = None
    run_id_if_executed_hash: str | None = None
    asked_follow_up: bool | None = None
    follow_up_topics: tuple[str, ...] = ()
    disallowed_follow_up_topics: tuple[str, ...] = ()
    first_runtime_input_type: str | None = None
    terminal_output_type: str | None = None
    terminal_output_mode: str | None = None
    step_count: int | None = None
    step_roles: tuple[str, ...] = ()
    flow_graph_fetched: bool | None = None
    step_outputs_fetched: bool | None = None
    evidence_trace_fetched: bool | None = None
    evidence_export_available: bool | None = None
    generated_artifact_file_id_hashes: tuple[str, ...] = ()
    repair_invoked: bool | None = None
    sse_events_seen: tuple[str, ...] = ()
    unknown_sse_events: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ManualApiManualScores:
    question_relevance: int | None = None
    flow_correctness: int | None = None
    step_specialization: int | None = None
    output_quality: int | None = None
    input_variable_use: int | None = None
    underlag_till_text_use: int | None = None
    resource_tool_use: int | None = None
    edit_or_revision_adherence: int | None = None


@dataclass(frozen=True, slots=True)
class ManualApiScorecard:
    scorecard_schema_version: int
    schema_bump_policy: str
    generated_at: str
    live: bool
    prompt_id: str
    evaluation_mode: str
    run_index: int
    scenario_supported_by_current_api: bool
    model: ManualApiModelSummary
    workspace_fixture: ManualApiWorkspaceFixture
    openapi_validation_status: str
    openapi_missing_operation_ids: tuple[str, ...]
    live_call_status: str
    live_call_error: str | None
    observed: ManualApiObserved
    derived: PlanDerivedMechanics
    typed_pass_count: int
    typed_fail_count: int
    typed_failures: tuple[str, ...]
    manual_scores: ManualApiManualScores
    regressions_vs_previous_baseline: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SseEvent:
    event: str
    data: str


def load_live_api_config(env: Mapping[str, str] | None = None) -> LocalApiConfig:
    env_values = env or os.environ
    missing = [
        env_key
        for env_key in (ENV_LOCAL_API_BASE, ENV_LOCAL_SPACE_ID, ENV_LOCAL_API_KEY)
        if not env_values.get(env_key)
    ]
    if missing:
        raise ValueError(
            "Live manual API eval requires " + ", ".join(missing) + " to be set."
        )
    api_base = env_values[ENV_LOCAL_API_BASE].rstrip("/")
    space_id = UUID(env_values[ENV_LOCAL_SPACE_ID])
    api_key = env_values[ENV_LOCAL_API_KEY]
    return LocalApiConfig(
        api_base=api_base,
        space_id=space_id,
        api_key=api_key,
        redacted=RedactedLocalApiConfig(
            api_base_sha256=redacted_sha256(api_base),
            space_id_hash=redacted_sha256(space_id),
            api_key_present=True,
        ),
    )


def validate_manual_api_cases(
    cases: Sequence[ReliabilityCorpusCase] = manual_api_eval_cases(),
    scenarios: Sequence[ManualApiEvalScenario] = MANUAL_API_EVAL_SCENARIOS,
) -> None:
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Manual API eval cases must have unique case ids.")
    missing = {scenario.case_id for scenario in scenarios} - set(case_ids)
    if missing:
        raise ValueError(
            "Manual API eval scenarios reference unknown cases: "
            + ", ".join(sorted(missing))
        )
    if tuple(case_ids) != MANUAL_API_EVAL_CASE_IDS:
        raise ValueError(
            "Manual API eval cases must match MANUAL_API_EVAL_CASE_IDS exactly."
        )


def build_dry_run_scorecards(
    *,
    cases: Sequence[ReliabilityCorpusCase] = manual_api_eval_cases(),
    scenarios: Sequence[ManualApiEvalScenario] = MANUAL_API_EVAL_SCENARIOS,
    modes: frozenset[ManualApiEvaluationMode] | None = None,
    prompt_ids: frozenset[str] | None = None,
    runs_per_prompt: int = DEFAULT_RUNS_PER_PROMPT,
    include_unsupported: bool = False,
) -> tuple[ManualApiScorecard, ...]:
    validate_manual_api_cases(cases, scenarios)
    selected = _select_scenarios(
        scenarios=scenarios,
        modes=modes,
        prompt_ids=prompt_ids,
        include_unsupported=include_unsupported,
    )
    return tuple(
        _empty_scorecard(
            corpus_case=_case_by_id(cases, scenario.case_id),
            scenario=scenario,
            run_index=run_index,
        )
        for scenario in selected
        for run_index in range(1, runs_per_prompt + 1)
    )


def scorecard_from_plan(
    *,
    corpus_case: ReliabilityCorpusCase,
    scenario: ManualApiEvalScenario,
    run_index: int,
    spec: FlowDraftSpecCore,
    session_id: str | None = None,
    plan_id: str | None = None,
    telemetry: SessionTelemetrySummary | None = None,
    sse_events: Sequence[SseEvent] = (),
    model: ManualApiModelSummary | None = None,
    workspace_fixture: ManualApiWorkspaceFixture | None = None,
    openapi_validation_status: str = "passed",
    openapi_missing_operation_ids: Sequence[str] = (),
    live_call_status: str = "completed",
    live_call_error: str | None = None,
) -> ManualApiScorecard:
    plan_score = score_plan_mechanics(spec=spec, corpus_case=corpus_case)
    observed = _observed_from_plan(
        plan_observed=plan_score.observed,
        session_id=session_id,
        plan_id=plan_id,
        telemetry=telemetry,
        sse_events=sse_events,
    )
    return ManualApiScorecard(
        scorecard_schema_version=SCORECARD_SCHEMA_VERSION,
        schema_bump_policy=_schema_bump_policy(),
        generated_at=utc_now_iso(),
        live=True,
        prompt_id=corpus_case.case_id,
        evaluation_mode=scenario.evaluation_mode.value,
        run_index=run_index,
        scenario_supported_by_current_api=scenario.supported_by_current_api,
        model=model or ManualApiModelSummary(),
        workspace_fixture=workspace_fixture or ManualApiWorkspaceFixture(),
        openapi_validation_status=openapi_validation_status,
        openapi_missing_operation_ids=tuple(sorted(openapi_missing_operation_ids)),
        live_call_status=live_call_status,
        live_call_error=live_call_error,
        observed=observed,
        derived=plan_score.derived,
        typed_pass_count=plan_score.typed_pass_count,
        typed_fail_count=plan_score.typed_fail_count,
        typed_failures=plan_score.typed_failures,
        manual_scores=ManualApiManualScores(),
        regressions_vs_previous_baseline=(),
    )


def parse_sse_events(stream_text: str) -> tuple[SseEvent, ...]:
    events: list[SseEvent] = []
    event_name = "message"
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal event_name, data_lines
        if not data_lines and event_name == "message":
            return
        events.append(SseEvent(event=event_name, data="\n".join(data_lines)))
        event_name = "message"
        data_lines = []

    for raw_line in stream_text.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            flush()
            continue
        if line.startswith(":"):
            continue
        field_name, separator, field_value = line.partition(":")
        if not separator:
            continue
        if field_value.startswith(" "):
            field_value = field_value[1:]
        if field_name == "event":
            event_name = field_value
        elif field_name == "data":
            data_lines.append(field_value)
    flush()
    return tuple(events)


def validate_openapi_operation_ids(
    openapi_payload: Mapping[str, Any],
    *,
    include_executed_run: bool = False,
) -> tuple[str, ...]:
    required = set(AI_BUILDER_OPERATION_IDS)
    if include_executed_run:
        required.update(EXECUTED_RUN_OPERATION_IDS)
    observed = {
        operation.get("operationId")
        for path_item in openapi_payload.get("paths", {}).values()
        if isinstance(path_item, Mapping)
        for operation in path_item.values()
        if isinstance(operation, Mapping)
    }
    missing = sorted(required - {item for item in observed if isinstance(item, str)})
    return tuple(missing)


def serialize_scorecard(scorecard: ManualApiScorecard) -> str:
    return serialize_dataclass_scorecard(scorecard)


def write_scorecards(
    scorecards: Sequence[ManualApiScorecard],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for scorecard in scorecards:
        filename = (
            f"{scorecard.prompt_id}__{scorecard.evaluation_mode}"
            f"__run_{scorecard.run_index}.json"
        )
        (output_dir / filename).write_text(
            serialize_scorecard(scorecard),
            encoding="utf-8",
        )


async def build_live_scorecards(
    *,
    config: LocalApiConfig,
    cases: Sequence[ReliabilityCorpusCase] = manual_api_eval_cases(),
    scenarios: Sequence[ManualApiEvalScenario] = MANUAL_API_EVAL_SCENARIOS,
    modes: frozenset[ManualApiEvaluationMode] | None = None,
    prompt_ids: frozenset[str] | None = None,
    runs_per_prompt: int = DEFAULT_RUNS_PER_PROMPT,
    include_unsupported: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[ManualApiScorecard, ...]:
    validate_manual_api_cases(cases, scenarios)
    selected = _select_scenarios(
        scenarios=scenarios,
        modes=modes,
        prompt_ids=prompt_ids,
        include_unsupported=include_unsupported,
    )
    async with httpx.AsyncClient(
        base_url=config.api_base,
        headers={"X-API-Key": config.api_key},
        timeout=120.0,
        transport=transport,
    ) as client:
        openapi_status, missing_operation_ids = await _validate_live_openapi(client)
        scorecards: list[ManualApiScorecard] = []
        for scenario in selected:
            corpus_case = _case_by_id(cases, scenario.case_id)
            for run_index in range(1, runs_per_prompt + 1):
                if scenario.evaluation_mode != ManualApiEvaluationMode.CREATE_PLAN:
                    scorecards.append(
                        _empty_scorecard(
                            corpus_case=corpus_case,
                            scenario=scenario,
                            run_index=run_index,
                            live=True,
                            workspace_fixture=ManualApiWorkspaceFixture(
                                space_id_hash=config.redacted.space_id_hash,
                            ),
                            openapi_validation_status=openapi_status,
                            openapi_missing_operation_ids=missing_operation_ids,
                        )
                    )
                    continue
                try:
                    scorecards.append(
                        await _run_create_plan(
                            client=client,
                            config=config,
                            corpus_case=corpus_case,
                            scenario=scenario,
                            run_index=run_index,
                            openapi_validation_status=openapi_status,
                            openapi_missing_operation_ids=missing_operation_ids,
                        )
                    )
                except (httpx.HTTPError, KeyError, ValueError) as exc:
                    scorecards.append(
                        _empty_scorecard(
                            corpus_case=corpus_case,
                            scenario=scenario,
                            run_index=run_index,
                            live=True,
                            workspace_fixture=ManualApiWorkspaceFixture(
                                space_id_hash=config.redacted.space_id_hash,
                            ),
                            openapi_validation_status=openapi_status,
                            openapi_missing_operation_ids=missing_operation_ids,
                            live_call_status="failed",
                            live_call_error=type(exc).__name__,
                        )
                    )
        return tuple(scorecards)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the local AI Builder manual API eval harness.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call the configured local API. Omit for deterministic dry-run.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Write redacted scorecard JSON files to this directory.",
    )
    parser.add_argument(
        "--prompt-id",
        action="append",
        dest="prompt_ids",
        help="Restrict to one prompt id. Repeat for multiple ids.",
    )
    parser.add_argument(
        "--mode",
        action="append",
        choices=[mode.value for mode in ManualApiEvaluationMode],
        help="Restrict to one evaluation mode. Repeat for multiple modes.",
    )
    parser.add_argument(
        "--runs-per-prompt",
        type=int,
        default=DEFAULT_RUNS_PER_PROMPT,
        help="Number of scorecards to produce per selected prompt/mode.",
    )
    parser.add_argument(
        "--include-unsupported",
        action="store_true",
        help="Include revise/edit scenarios that are documented but not API-backed yet.",
    )
    args = parser.parse_args(argv)

    modes = (
        frozenset(ManualApiEvaluationMode(mode) for mode in args.mode)
        if args.mode
        else None
    )
    prompt_ids = frozenset(args.prompt_ids) if args.prompt_ids else None
    if args.live:
        try:
            config = load_live_api_config()
        except ValueError as exc:
            parser.error(str(exc))
        scorecards = asyncio.run(
            build_live_scorecards(
                config=config,
                modes=modes,
                prompt_ids=prompt_ids,
                runs_per_prompt=args.runs_per_prompt,
                include_unsupported=args.include_unsupported,
            )
        )
    else:
        scorecards = build_dry_run_scorecards(
            modes=modes,
            prompt_ids=prompt_ids,
            runs_per_prompt=args.runs_per_prompt,
            include_unsupported=args.include_unsupported,
        )

    if args.output_dir is not None:
        write_scorecards(scorecards, args.output_dir)
    else:
        for scorecard in scorecards:
            print(serialize_scorecard(scorecard), end="")
    return 0


async def _validate_live_openapi(
    client: httpx.AsyncClient,
) -> tuple[str, tuple[str, ...]]:
    try:
        response = await client.get("/openapi.json")
        response.raise_for_status()
    except httpx.HTTPError:
        return "skipped_unreachable", ()
    missing = validate_openapi_operation_ids(response.json())
    return ("passed" if not missing else "failed", missing)


async def _run_create_plan(
    *,
    client: httpx.AsyncClient,
    config: LocalApiConfig,
    corpus_case: ReliabilityCorpusCase,
    scenario: ManualApiEvalScenario,
    run_index: int,
    openapi_validation_status: str,
    openapi_missing_operation_ids: Sequence[str],
) -> ManualApiScorecard:
    session_response = await client.post(
        "/api/v1/flows/ai-builder/sessions",
        json={
            "target_kind": "create",
            "space_id": str(config.space_id),
            "force_new": True,
        },
    )
    session_response.raise_for_status()
    session_payload = session_response.json()
    session_id = session_payload["session_id"]
    sse_events = await _send_message_and_parse_sse(
        client=client,
        session_id=session_id,
        corpus_case=corpus_case,
    )
    session_after_response = await client.get(
        f"/api/v1/flows/ai-builder/sessions/{session_id}"
    )
    session_after_response.raise_for_status()
    session_after = session_after_response.json()
    telemetry = (
        SessionTelemetrySummary.model_validate(session_after["telemetry"])
        if session_after.get("telemetry") is not None
        else None
    )
    model = await _fetch_model_summary(
        client=client,
        session_id=session_id,
        telemetry=telemetry,
    )
    plan_id = session_after.get("latest_plan_id")
    if plan_id is None:
        return _empty_scorecard(
            corpus_case=corpus_case,
            scenario=scenario,
            run_index=run_index,
            live=True,
            session_id=session_id,
            workspace_fixture=ManualApiWorkspaceFixture(
                space_id_hash=config.redacted.space_id_hash,
            ),
            openapi_validation_status=openapi_validation_status,
            openapi_missing_operation_ids=openapi_missing_operation_ids,
            sse_events=sse_events,
            model=model,
            live_call_status="completed_without_plan",
        )
    plan_response = await client.get(f"/api/v1/flows/ai-builder/plans/{plan_id}")
    plan_response.raise_for_status()
    plan = PlanResponse.model_validate(plan_response.json())
    return scorecard_from_plan(
        corpus_case=corpus_case,
        scenario=scenario,
        run_index=run_index,
        spec=plan.envelope.spec,
        session_id=session_id,
        plan_id=str(plan.plan_id),
        telemetry=telemetry,
        sse_events=sse_events,
        model=model,
        workspace_fixture=ManualApiWorkspaceFixture(
            space_id_hash=config.redacted.space_id_hash,
        ),
        openapi_validation_status=openapi_validation_status,
        openapi_missing_operation_ids=openapi_missing_operation_ids,
    )


async def _send_message_and_parse_sse(
    *,
    client: httpx.AsyncClient,
    session_id: str,
    corpus_case: ReliabilityCorpusCase,
) -> tuple[SseEvent, ...]:
    chunks: list[str] = []
    byte_count = 0
    async with client.stream(
        "POST",
        f"/api/v1/flows/ai-builder/sessions/{session_id}/messages",
        headers={"accept": "text/event-stream"},
        json={"message": corpus_case.prompt, "ui_language": corpus_case.ui_language},
    ) as response:
        response.raise_for_status()
        async for chunk in response.aiter_text():
            byte_count += len(chunk.encode("utf-8"))
            if byte_count > MAX_SSE_STREAM_BYTES:
                raise ValueError("AI Builder SSE response exceeded local eval limit.")
            chunks.append(chunk)
    return parse_sse_events("".join(chunks))


async def _fetch_model_summary(
    *,
    client: httpx.AsyncClient,
    session_id: str,
    telemetry: SessionTelemetrySummary | None,
) -> ManualApiModelSummary:
    telemetry_model = telemetry.last_model if telemetry is not None else None
    try:
        response = await client.get(
            f"/api/v1/flows/ai-builder/sessions/{session_id}/models"
        )
        response.raise_for_status()
        models_response = SessionModelsResponse.model_validate(response.json())
    except (httpx.HTTPError, ValueError):
        provider, name = _split_provider_model_name(telemetry_model)
        return ManualApiModelSummary(name=name, provider=provider)

    selected = _select_model_option(
        models_response=models_response,
        telemetry_model=telemetry_model,
    )
    if selected is None:
        provider, name = _split_provider_model_name(telemetry_model)
        return ManualApiModelSummary(name=name, provider=provider)
    return ManualApiModelSummary(
        id_hash=redacted_sha256(selected.id),
        name=selected.name,
        provider=selected.provider,
    )


def _select_model_option(
    *,
    models_response: SessionModelsResponse,
    telemetry_model: str | None,
) -> SessionModelOption | None:
    if telemetry_model:
        telemetry_provider, telemetry_name = _split_provider_model_name(telemetry_model)
        if telemetry_provider:
            for model in models_response.models:
                if f"{model.provider}/{model.name}" == telemetry_model:
                    return model
        for model in models_response.models:
            if model.name == telemetry_model or model.name == telemetry_name:
                return model
    if models_response.default_model_id is None:
        return None
    return next(
        (
            model
            for model in models_response.models
            if model.id == models_response.default_model_id
        ),
        None,
    )


def _split_provider_model_name(model_name: str | None) -> tuple[str | None, str | None]:
    if model_name is None:
        return None, None
    provider, separator, name = model_name.partition("/")
    if separator:
        return provider or None, name or None
    return None, model_name


def _empty_scorecard(
    *,
    corpus_case: ReliabilityCorpusCase,
    scenario: ManualApiEvalScenario,
    run_index: int,
    live: bool = False,
    session_id: str | None = None,
    workspace_fixture: ManualApiWorkspaceFixture | None = None,
    openapi_validation_status: str = "skipped_dry_run",
    openapi_missing_operation_ids: Sequence[str] = (),
    sse_events: Sequence[SseEvent] = (),
    model: ManualApiModelSummary | None = None,
    live_call_status: str = "not_run",
    live_call_error: str | None = None,
) -> ManualApiScorecard:
    return ManualApiScorecard(
        scorecard_schema_version=SCORECARD_SCHEMA_VERSION,
        schema_bump_policy=_schema_bump_policy(),
        generated_at=utc_now_iso(),
        live=live,
        prompt_id=corpus_case.case_id,
        evaluation_mode=scenario.evaluation_mode.value,
        run_index=run_index,
        scenario_supported_by_current_api=scenario.supported_by_current_api,
        model=model or ManualApiModelSummary(),
        workspace_fixture=workspace_fixture or ManualApiWorkspaceFixture(),
        openapi_validation_status=openapi_validation_status,
        openapi_missing_operation_ids=tuple(sorted(openapi_missing_operation_ids)),
        live_call_status=live_call_status,
        live_call_error=live_call_error,
        observed=ManualApiObserved(
            session_id_hash=redacted_sha256(session_id),
            sse_events_seen=tuple(event.event for event in sse_events),
            unknown_sse_events=_unknown_sse_events(sse_events),
        ),
        derived=PlanDerivedMechanics(
            derivation_rules_version=DERIVATION_RULES_VERSION,
            has_transcription_step=None,
            has_sectioning_step=None,
            has_source_grounding_step=None,
            has_docx_template_fill=None,
            uses_underlag_till_text_correctly=None,
            uses_runtime_input_fields_correctly=None,
            all_step_input_output_pairs_compatible=None,
            revision_preserved_unrelated_mechanics=None,
            revision_applied_requested_change=None,
        ),
        typed_pass_count=0,
        typed_fail_count=0,
        typed_failures=(),
        manual_scores=ManualApiManualScores(),
        regressions_vs_previous_baseline=(),
    )


def _observed_from_plan(
    *,
    plan_observed: PlanObservedMechanics,
    session_id: str | None,
    plan_id: str | None,
    telemetry: SessionTelemetrySummary | None,
    sse_events: Sequence[SseEvent],
) -> ManualApiObserved:
    return ManualApiObserved(
        session_id_hash=redacted_sha256(session_id),
        plan_id_hash=redacted_sha256(plan_id),
        asked_follow_up=any(event.event == SSE_EVENT_QUESTION for event in sse_events),
        first_runtime_input_type=plan_observed.first_runtime_input_type,
        terminal_output_type=plan_observed.terminal_output_type,
        terminal_output_mode=plan_observed.terminal_output_mode,
        step_count=plan_observed.step_count,
        step_roles=plan_observed.step_roles,
        repair_invoked=(
            telemetry.repair_attempts_total > 0 if telemetry is not None else None
        ),
        sse_events_seen=tuple(event.event for event in sse_events),
        unknown_sse_events=_unknown_sse_events(sse_events),
    )


def _select_scenarios(
    *,
    scenarios: Sequence[ManualApiEvalScenario],
    modes: frozenset[ManualApiEvaluationMode] | None,
    prompt_ids: frozenset[str] | None,
    include_unsupported: bool,
) -> tuple[ManualApiEvalScenario, ...]:
    return tuple(
        scenario
        for scenario in scenarios
        if (include_unsupported or scenario.supported_by_current_api)
        and (modes is None or scenario.evaluation_mode in modes)
        and (prompt_ids is None or scenario.case_id in prompt_ids)
    )


def _case_by_id(
    cases: Sequence[ReliabilityCorpusCase],
    case_id: str,
) -> ReliabilityCorpusCase:
    return next(case for case in cases if case.case_id == case_id)


def _unknown_sse_events(events: Iterable[SseEvent]) -> tuple[str, ...]:
    return tuple(
        sorted({event.event for event in events if event.event not in KNOWN_SSE_EVENTS})
    )


def _schema_bump_policy() -> str:
    return (
        "scorecard_schema_version changes invalidate all prior baselines; "
        "derivation_rules_version changes invalidate derived-field comparison only."
    )


if __name__ == "__main__":
    raise SystemExit(main())
