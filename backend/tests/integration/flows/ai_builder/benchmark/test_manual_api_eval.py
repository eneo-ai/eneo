from __future__ import annotations

import json
from dataclasses import asdict
from uuid import uuid4

import httpx
import pytest

from tests.integration.flows.ai_builder.benchmark.cases import (
    MANUAL_API_EVAL_CASE_IDS,
    MANUAL_API_EVAL_SCENARIOS,
    RELIABILITY_CORPUS_CASES,
    CorpusSource,
    ManualApiEvaluationMode,
    manual_api_eval_cases,
)
from tests.integration.flows.ai_builder.benchmark.manual_api_eval import (
    AI_BUILDER_OPERATION_IDS,
    ENV_LOCAL_API_BASE,
    ENV_LOCAL_API_KEY,
    ENV_LOCAL_SPACE_ID,
    LocalApiConfig,
    RedactedLocalApiConfig,
    build_dry_run_scorecards,
    build_live_scorecards,
    load_live_api_config,
    parse_sse_events,
    serialize_scorecard,
    validate_manual_api_cases,
    validate_openapi_operation_ids,
)


def test_manual_api_eval_cases_reuse_reliability_corpus_owner() -> None:
    cases = manual_api_eval_cases()

    assert tuple(case.case_id for case in cases) == MANUAL_API_EVAL_CASE_IDS
    assert len(cases) == 6
    assert all(case.source == CorpusSource.MANUAL_RUNBOOK for case in cases)
    assert all(
        any(scenario.case_id == case.case_id for scenario in MANUAL_API_EVAL_SCENARIOS)
        for case in cases
    )


def test_manual_api_eval_case_validation_rejects_unknown_scenario_case() -> None:
    case = manual_api_eval_cases()[0]
    bad_scenario = MANUAL_API_EVAL_SCENARIOS[0].__class__(
        scenario_id="missing__create_plan",
        case_id="missing",
        evaluation_mode=ManualApiEvaluationMode.CREATE_PLAN,
    )

    with pytest.raises(ValueError, match="unknown cases"):
        validate_manual_api_cases((case,), (bad_scenario,))


def test_manual_api_eval_case_validation_rejects_case_order_drift() -> None:
    with pytest.raises(ValueError, match="MANUAL_API_EVAL_CASE_IDS"):
        validate_manual_api_cases(
            tuple(reversed(manual_api_eval_cases())),
            MANUAL_API_EVAL_SCENARIOS,
        )


def test_dry_run_scorecards_are_redacted_and_do_not_include_prompts() -> None:
    scorecards = build_dry_run_scorecards(
        prompt_ids=frozenset({"vague_audio_docx_sv"}),
        modes=frozenset({ManualApiEvaluationMode.CREATE_PLAN}),
        runs_per_prompt=1,
    )

    serialized = serialize_scorecard(scorecards[0])
    payload = json.loads(serialized)

    assert payload["live"] is False
    assert payload["prompt_id"] == "vague_audio_docx_sv"
    assert payload["openapi_validation_status"] == "skipped_dry_run"
    assert "Jag vill kunna skicka" not in serialized
    assert "sk_" not in serialized


def test_dry_run_excludes_unsupported_scenarios_by_default() -> None:
    scorecards = build_dry_run_scorecards(runs_per_prompt=1)

    assert len(scorecards) == len(MANUAL_API_EVAL_CASE_IDS)
    assert all(scorecard.scenario_supported_by_current_api for scorecard in scorecards)


def test_dry_run_can_include_unsupported_future_scenarios() -> None:
    scorecards = build_dry_run_scorecards(
        runs_per_prompt=1,
        include_unsupported=True,
    )

    assert len(scorecards) == len(MANUAL_API_EVAL_SCENARIOS)
    assert any(
        not scorecard.scenario_supported_by_current_api for scorecard in scorecards
    )


def test_live_config_requires_local_api_environment() -> None:
    with pytest.raises(ValueError, match=ENV_LOCAL_API_BASE):
        load_live_api_config({})

    with pytest.raises(ValueError, match=ENV_LOCAL_SPACE_ID):
        load_live_api_config({ENV_LOCAL_API_BASE: "http://localhost:8123"})

    with pytest.raises(ValueError, match=ENV_LOCAL_API_KEY):
        load_live_api_config(
            {
                ENV_LOCAL_API_BASE: "http://localhost:8123",
                ENV_LOCAL_SPACE_ID: str(uuid4()),
            }
        )


def test_live_config_redacts_api_key_base_and_space_id() -> None:
    space_id = uuid4()
    api_key = "secret-local-key"
    api_base = "http://localhost:8123"

    config = load_live_api_config(
        {
            ENV_LOCAL_API_BASE: api_base,
            ENV_LOCAL_SPACE_ID: str(space_id),
            ENV_LOCAL_API_KEY: api_key,
        }
    )
    redacted_payload = json.dumps(asdict(config.redacted))

    assert config.api_key == api_key
    assert config.redacted.api_key_present is True
    assert config.redacted.api_base_sha256 is not None
    assert config.redacted.space_id_hash is not None
    assert api_key not in redacted_payload
    assert api_base not in redacted_payload
    assert str(space_id) not in redacted_payload


def test_sse_parser_handles_multiline_comments_error_and_done() -> None:
    events = parse_sse_events(
        ": ping\n"
        "event: text\n"
        "data: första raden\n"
        "data: andra raden\n\n"
        "event: error\n"
        'data: {"code":"planner_stream_failed"}\n\n'
        "event: done\n"
        "data: \n\n"
    )

    assert [event.event for event in events] == ["text", "error", "done"]
    assert events[0].data == "första raden\nandra raden"
    assert events[1].data == '{"code":"planner_stream_failed"}'


def test_openapi_operation_validation_reports_missing_ids() -> None:
    present_operation = next(iter(AI_BUILDER_OPERATION_IDS))
    openapi_payload = {
        "paths": {
            "/ok": {
                "get": {
                    "operationId": present_operation,
                }
            }
        }
    }

    missing = validate_openapi_operation_ids(openapi_payload)

    assert present_operation not in missing
    assert set(missing) == AI_BUILDER_OPERATION_IDS - {present_operation}


@pytest.mark.asyncio
async def test_live_scorecard_uses_api_plan_model_and_sse_transport() -> None:
    session_id = uuid4()
    plan_id = uuid4()
    model_id = uuid4()
    space_id = uuid4()
    requests_seen: list[tuple[str, str]] = []

    spec_payload = {
        "flow_name": "Mötesprotokoll från ljud till Word",
        "flow_description": "Test fixture.",
        "steps": [
            {
                "plan_step_ref": "step_a",
                "name": "Transkribera ljud",
                "assistant_spec": {"instructions": "Transkribera ljud."},
                "input_source": "flow_input",
                "input_type": "audio",
                "output_type": "text",
                "output_mode": "transcribe_only",
            },
            {
                "plan_step_ref": "step_b",
                "name": "Strukturera transkription",
                "assistant_spec": {"instructions": "Strukturera text."},
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_mode": "pass_through",
            },
            {
                "plan_step_ref": "step_c",
                "name": "Skapa DOCX",
                "assistant_spec": {"instructions": "Skriv dokument."},
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "docx",
                "output_mode": "pass_through",
                "input_bindings": {
                    "question": (
                        "{{ step_b.output.structured }}\n\n"
                        "Källmaterial: {{ step_a.output.text }}"
                    )
                },
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/openapi.json":
            return httpx.Response(200, json=_openapi_payload(AI_BUILDER_OPERATION_IDS))
        if (
            request.method == "POST"
            and request.url.path == "/api/v1/flows/ai-builder/sessions"
        ):
            return httpx.Response(200, json={"session_id": str(session_id)})
        if (
            request.method == "POST"
            and request.url.path
            == f"/api/v1/flows/ai-builder/sessions/{session_id}/messages"
        ):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text="event: plan\ndata: {}\n\nevent: done\ndata: \n\n",
            )
        if (
            request.method == "GET"
            and request.url.path == f"/api/v1/flows/ai-builder/sessions/{session_id}"
        ):
            return httpx.Response(
                200,
                json={
                    "session_id": str(session_id),
                    "status": "awaiting_approval",
                    "target_kind": "create",
                    "latest_plan_id": str(plan_id),
                    "telemetry": {
                        "repair_attempts_total": 0,
                        "last_model": "openai/gpt-test",
                    },
                },
            )
        if (
            request.method == "GET"
            and request.url.path
            == f"/api/v1/flows/ai-builder/sessions/{session_id}/models"
        ):
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "id": str(model_id),
                            "name": "gpt-test",
                            "provider": "openai",
                        }
                    ],
                    "default_model_id": str(model_id),
                },
            )
        if (
            request.method == "GET"
            and request.url.path == f"/api/v1/flows/ai-builder/plans/{plan_id}"
        ):
            return httpx.Response(
                200,
                json={
                    "plan_id": str(plan_id),
                    "session_id": str(session_id),
                    "status": "proposed",
                    "spec_hash": "test-spec-hash",
                    "envelope": {
                        "spec": spec_payload,
                        "assumptions": [],
                        "lint_warnings": [],
                        "risk_acknowledgments": [],
                        "plan_rationale": "test",
                    },
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    scorecards = await build_live_scorecards(
        config=LocalApiConfig(
            api_base="http://local.test",
            space_id=space_id,
            api_key="local-secret",
            redacted=RedactedLocalApiConfig(
                api_base_sha256="redacted-base",
                space_id_hash="redacted-space",
                api_key_present=True,
            ),
        ),
        prompt_ids=frozenset({"advanced_audio_meeting_docx_sv"}),
        runs_per_prompt=1,
        transport=httpx.MockTransport(handler),
    )

    scorecard = scorecards[0]

    assert scorecard.live_call_status == "completed"
    assert scorecard.openapi_validation_status == "passed"
    assert scorecard.model.name == "gpt-test"
    assert scorecard.model.provider == "openai"
    assert scorecard.model.id_hash is not None
    assert scorecard.observed.session_id_hash is not None
    assert scorecard.observed.plan_id_hash is not None
    assert scorecard.derived.uses_underlag_till_text_correctly is True
    assert ("GET", f"/api/v1/flows/ai-builder/sessions/{session_id}/models") in (
        requests_seen
    )


@pytest.mark.asyncio
async def test_live_scorecard_records_redacted_failure_status() -> None:
    space_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/openapi.json":
            return httpx.Response(200, json=_openapi_payload(AI_BUILDER_OPERATION_IDS))
        if (
            request.method == "POST"
            and request.url.path == "/api/v1/flows/ai-builder/sessions"
        ):
            return httpx.Response(500, json={"detail": "local failure"})
        return httpx.Response(404, json={"detail": "not found"})

    scorecards = await build_live_scorecards(
        config=LocalApiConfig(
            api_base="http://local.test",
            space_id=space_id,
            api_key="local-secret",
            redacted=RedactedLocalApiConfig(
                api_base_sha256="redacted-base",
                space_id_hash="redacted-space",
                api_key_present=True,
            ),
        ),
        prompt_ids=frozenset({"advanced_audio_meeting_docx_sv"}),
        runs_per_prompt=1,
        transport=httpx.MockTransport(handler),
    )

    serialized = serialize_scorecard(scorecards[0])

    assert scorecards[0].live_call_status == "failed"
    assert scorecards[0].live_call_error == "HTTPStatusError"
    assert "local failure" not in serialized


def test_all_manual_prompt_ids_exist_in_reliability_corpus() -> None:
    reliability_case_ids = {case.case_id for case in RELIABILITY_CORPUS_CASES}

    assert set(MANUAL_API_EVAL_CASE_IDS) <= reliability_case_ids


def _openapi_payload(operation_ids: frozenset[str]) -> dict[str, object]:
    return {
        "paths": {
            f"/test/{operation_id}": {
                "get": {
                    "operationId": operation_id,
                }
            }
            for operation_id in operation_ids
        }
    }
