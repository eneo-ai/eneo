from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import get_args
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadGatewayError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
    UnprocessableEntityError,
)

from eneo.completion_models.domain.model_capacity import ModelCapacity
from eneo.completion_models.infrastructure.completion_service import (
    CompletionEvidenceField,
    CompletionRouteEvidence,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AI_BUILDER_PROVIDER_INCIDENT_EVIDENCE_LOG_KEY,
    AIBuilderErrorCode,
    AIBuilderProviderFailure,
    AIBuilderProviderFailureKind,
    AIBuilderProviderRequestEvidence,
    classify_ai_builder_provider_failure,
    record_ai_builder_provider_failure,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    APPLY_TELEMETRY_LOG_KEY,
    APPLY_TELEMETRY_SCHEMA_VERSION,
    FAILED_TURN_EVIDENCE_KEYS,
    PROPOSAL_TELEMETRY_LOG_KEY,
    PROPOSAL_TELEMETRY_SCHEMA_VERSION,
    ChangesetCountSummary,
    MaterializerProgressSnapshot,
    ProposalAttemptFailureKind,
    ProposalCallKind,
    ProposalFailureKind,
    ProposalRepairReason,
    ProposalTurnTelemetry,
    ToolProcessingFailureKind,
    assistant_metadata_with_usage,
    build_proposal_failed_turn_payload,
    log_apply_failed,
    log_proposal_first_attempt,
    log_proposal_repair_invoked,
    proposal_repair_reason_from_tool_failure,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CorrectableFailure,
)
from eneo.flows.ai_builder.ai_builder_provider_call import (
    ProviderCallCeilingExpired,
    ProviderCallTiming,
    ProviderSilenceExpired,
)
from eneo.flows.ai_builder.ai_builder_settings import (
    AIBuilderRequestBudget,
    AIBuilderResolvedRequestBudget,
)
from eneo.flows.ai_builder.ai_builder_telemetry import (
    planner_call_records_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_token_usage import (
    CompletionTokenUsage,
    completion_token_usage_from_response,
)
from eneo.flows.ai_builder.ai_builder_tool_names import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.application.flow_authoring_command import FlowAuthoringPreview
from eneo.observability.failure_events import (
    FAILURE_EVENT_SCHEMA_VERSION,
    make_failure_fingerprint,
)
from tests.unittests.flows.ai_builder.proposal_turn_test_doubles import _make_usage

_REPO_ROOT = Path(__file__).resolve().parents[5]
_FAILURE_KIND_SOURCE_FILES = (
    _REPO_ROOT / "backend/src/eneo/flows/ai_builder/ai_builder_create_proposal.py",
    _REPO_ROOT / "backend/src/eneo/flows/ai_builder/ai_builder_edit_proposal.py",
    _REPO_ROOT
    / "backend/src/eneo/flows/ai_builder/ai_builder_proposal_finalization.py",
)


def _provider_response(status_code: int) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request("POST", "https://provider.invalid/v1/completions"),
    )


def _tool_processing_failure_kinds_from_source() -> set[str]:
    emitted: set[str] = set()
    for path in _FAILURE_KIND_SOURCE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                function_name = func.id
            elif isinstance(func, ast.Attribute):
                function_name = func.attr
            else:
                function_name = None
            if function_name not in {"CorrectableFailure", "TerminalFailure"}:
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "kind"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    emitted.add(keyword.value.value)
    return emitted


def test_proposal_turn_telemetry_extends_canonical_planner_payload() -> None:
    telemetry = ProposalTurnTelemetry(
        request_id="req-telemetry",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )
    telemetry.record_response(
        finish_reason="tool_calls",
        usage=_make_usage(prompt_tokens=10, completion_tokens=3, total_tokens=13),
    )
    assert telemetry.record_first_attempt(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        success=False,
        failure_kind="validation",
    )
    telemetry.record_repair_invocation(reason="validation")

    payload = telemetry.build_planner_telemetry(tool_call_count=1)

    assert payload["request_id"] == "req-telemetry"
    assert payload["total_tokens"] == 13
    assert payload["proposal_first_attempt_tool"] == PROPOSE_FLOW_TOOL_NAME
    assert payload["proposal_target_kind"] == TargetKind.CREATE.value
    assert payload["proposal_first_attempt_success"] is False
    assert payload["proposal_first_attempt_failure_kind"] == "validation"
    assert payload["proposal_repair_invocation_count"] == 1
    assert payload["proposal_repair_invocation_reasons"] == ["validation"]


def test_proposal_turn_telemetry_counts_admission_normalizer_hits() -> None:
    telemetry = ProposalTurnTelemetry(
        request_id="req-normalizer-hits",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )

    telemetry.record_admission_normalization_hit(
        "_discard_punctuation_serialization_artifacts"
    )
    telemetry.record_admission_normalization_hit("_normalize_structured_field_children")
    telemetry.record_admission_normalization_hit("_normalize_structured_field_children")

    payload = telemetry.build_planner_telemetry()

    assert payload["admission_normalization_hits"] == {
        "_discard_punctuation_serialization_artifacts": 1,
        "_normalize_structured_field_children": 2,
    }


def test_turn_call_records_are_the_usage_and_call_count_owner() -> None:
    telemetry = ProposalTurnTelemetry(
        request_id="req-call-family",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )
    usages = (
        CompletionTokenUsage(2, 1, 3, source="provider"),
        CompletionTokenUsage(5, 2, 7, source="litellm_estimate", estimated=True),
        CompletionTokenUsage(),
    )
    kinds: tuple[ProposalCallKind, ...] = (
        "slot_classification",
        "proposal_initial",
        "proposal_repair",
    )
    request_budget = AIBuilderRequestBudget(
        capacity=ModelCapacity(32_000, 16_000),
        safety_buffer_tokens=2_000,
        timeout_seconds=180.0,
    ).resolve_whole(input_tokens=6_000)
    assert request_budget is not None
    for kind, usage in zip(kinds, usages, strict=True):
        call = telemetry.begin_call(
            call_kind=kind,
            request_budget=request_budget,
        )
        telemetry.complete_call(call=call, usage=usage)

    payload = telemetry.build_planner_telemetry()

    assert [record["call_kind"] for record in payload["call_records"]] == list(kinds)
    assert [record["attempt"] for record in payload["call_records"]] == [1, 2, 3]
    assert {record["request_id"] for record in payload["call_records"]} == {
        "req-call-family"
    }
    assert payload["prompt_tokens"] == 7
    assert payload["completion_tokens"] == 3
    assert payload["total_tokens"] == 10
    assert payload["llm_calls_made"] == 3
    assert payload["auxiliary_llm_call_count"] == 1
    assert payload["used_auxiliary_llm"] is True
    assert payload["token_usage_source"] == "litellm_estimate"
    assert payload["token_usage_estimated"] is True
    assert payload["call_records"][-1]["token_usage_source"] == "none"
    assert payload["call_records"][0] == {
        "call_kind": "slot_classification",
        "request_id": "req-call-family",
        "attempt": 1,
        "token_usage_source": "provider",
        "token_usage_estimated": False,
        "request_budget_tokens": 32_000,
        "model_output_ceiling_tokens": 16_000,
        # Half of the room the 6 000-token request leaves in the 30 000 usable
        # tokens was kept for the answer; the model may write its whole ceiling.
        "output_reserve_tokens": 12_000,
        "provider_output_cap_tokens": 16_000,
        "fixed_input_tokens": 6_000,
        "safety_buffer_tokens": 2_000,
        "timeout_seconds": 180.0,
        "prompt_tokens": 2,
        "completion_tokens": 1,
        "total_tokens": 3,
    }
    assert "prompt_tokens" not in payload["call_records"][-1]
    assert "completion_tokens" not in payload["call_records"][-1]
    assert "total_tokens" not in payload["call_records"][-1]
    metadata = assistant_metadata_with_usage(
        conversation=[],
        base_metadata=None,
        usage_tracker=telemetry,
    )
    assert metadata is not None
    assert (
        metadata["planner_telemetry"]["call_records"][0]["provider_output_cap_tokens"]
        == 16_000
    )
    summary = metadata["session_telemetry"]
    assert summary["prompt_tokens_total"] == 7
    assert summary["completion_tokens_total"] == 3
    assert summary["total_tokens_total"] == 10
    assert summary["llm_calls_made_total"] == 3
    assert summary["auxiliary_llm_call_count"] == 1
    assert summary["last_request_id"] == "req-call-family"
    assert summary["last_token_usage_source"] == "litellm_estimate"


@pytest.mark.parametrize(
    "call_kind",
    [
        "slot_classification",
        "proposal_initial",
        "forced_tool_continuation",
        "proposal_repair",
    ],
)
def test_every_closed_call_kind_is_aggregated(call_kind: ProposalCallKind) -> None:
    telemetry = ProposalTurnTelemetry(
        request_id="req-kind-closure",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )

    call = telemetry.begin_call(call_kind=call_kind)
    telemetry.complete_call(
        call=call,
        usage=CompletionTokenUsage(1, 2, 3, source="provider"),
    )

    payload = telemetry.build_planner_telemetry()
    assert payload["llm_calls_made"] == 1
    assert payload["total_tokens"] == 3


def test_failed_auxiliary_call_is_finished_once_with_bounded_disposition() -> None:
    telemetry = ProposalTurnTelemetry(
        request_id="req-auxiliary-failure",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )
    call = telemetry.begin_call(call_kind="slot_classification")
    failure = classify_ai_builder_provider_failure(
        APIError(
            503,
            "sensitive-provider-material",
            model="private-model",
            llm_provider="private-provider",
        ),
        stage="slot_classification",
    )

    telemetry.fail_call(call=call, failure=failure)

    payload = telemetry.build_planner_telemetry()
    assert payload["llm_calls_made"] == 1
    assert payload["auxiliary_llm_call_count"] == 1
    assert payload["used_auxiliary_llm"] is True
    assert payload["call_records"] == [
        {
            "call_kind": "slot_classification",
            "request_id": "req-auxiliary-failure",
            "attempt": 1,
            "token_usage_source": "none",
            "token_usage_estimated": False,
            "provider_failure_kind": "transport_ambiguous",
            "provider_status_class": "5xx",
            "provider_turn_state": "provider_outcome_unknown",
        }
    ]
    assert "sensitive-provider-material" not in json.dumps(payload)


def test_failed_auxiliary_call_rejects_a_foreign_record() -> None:
    telemetry = ProposalTurnTelemetry(
        request_id="req-auxiliary-failure",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )
    foreign_call = ProposalTurnTelemetry(
        request_id="req-foreign",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    ).begin_call(call_kind="slot_classification")
    failure = classify_ai_builder_provider_failure(
        APIError(
            503,
            "sensitive-provider-material",
            model="private-model",
            llm_provider="private-provider",
        ),
        stage="slot_classification",
    )

    with pytest.raises(ValueError, match="does not belong to this turn"):
        telemetry.fail_call(call=foreign_call, failure=failure)


def test_proposal_attempt_telemetry_is_bounded_and_content_free() -> None:
    telemetry = ProposalTurnTelemetry(
        request_id="req-attempts",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )

    telemetry.start_attempt(counts_as_repair=False)
    telemetry.record_response(
        finish_reason="tool_calls",
        usage=_make_usage(prompt_tokens=11, completion_tokens=7, total_tokens=18),
    )
    telemetry.record_attempt_failure(
        failure_kind="quality",
        failure_codes=frozenset(
            {
                "duplicate_step_name",
                "named_result_obligations_must_survive",
                "raw user text must never be telemetry",
            }
        ),
        producers=frozenset({"lint"}),
    )

    payload = telemetry.build_planner_telemetry()
    attempts = payload["proposal_attempts"]

    assert attempts == [
        {
            "attempt": 1,
            "kind": "initial",
            "elapsed_ms": attempts[0]["elapsed_ms"],
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
            "token_usage_source": "provider",
            "token_usage_estimated": False,
            "failure_kind": "quality",
            "failure_codes": [
                "duplicate_step_name",
                "named_result_obligations_must_survive",
            ],
            "failure_code_count": 2,
            "producers": ["lint"],
        }
    ]
    assert attempts[0]["elapsed_ms"] >= 0
    assert payload["wall_clock_ms"] >= attempts[0]["elapsed_ms"]
    encoded = json.dumps(payload)
    assert "raw user text must never be telemetry" not in encoded
    assert "prompt" not in attempts[0]
    assert "provider_payload" not in attempts[0]
    assert "secret" not in attempts[0]


@pytest.mark.parametrize(
    (
        "error",
        "expected_kind",
        "expected_status_code",
        "expected_status_class",
        "expected_exception_class",
        "expected_turn_state",
    ),
    [
        (
            BadRequestError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "rejected",
            400,
            "4xx",
            "bad_request",
            "committed",
        ),
        (
            RateLimitError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "rate_limited",
            429,
            "4xx",
            "rate_limit",
            "committed",
        ),
        (
            AuthenticationError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "rejected",
            401,
            "4xx",
            "authentication",
            "committed",
        ),
        (
            NotFoundError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "rejected",
            404,
            "4xx",
            "not_found",
            "committed",
        ),
        (
            PermissionDeniedError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
                response=_provider_response(403),
            ),
            "rejected",
            403,
            "4xx",
            "permission_denied",
            "committed",
        ),
        (
            UnprocessableEntityError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
                response=_provider_response(422),
            ),
            "rejected",
            422,
            "4xx",
            "unprocessable_entity",
            "committed",
        ),
        (
            Timeout(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "timeout",
            408,
            "4xx",
            "timeout",
            "provider_outcome_unknown",
        ),
        (
            TimeoutError(),
            "timeout",
            None,
            None,
            "timeout",
            "provider_outcome_unknown",
        ),
        (
            APIConnectionError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "transport_ambiguous",
            None,
            None,
            "api_connection",
            "provider_outcome_unknown",
        ),
        (
            BadGatewayError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "transport_ambiguous",
            502,
            "5xx",
            "bad_gateway",
            "provider_outcome_unknown",
        ),
        (
            InternalServerError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "transport_ambiguous",
            500,
            "5xx",
            "internal_server",
            "provider_outcome_unknown",
        ),
        (
            ServiceUnavailableError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "transport_ambiguous",
            503,
            "5xx",
            "service_unavailable",
            "provider_outcome_unknown",
        ),
        (
            APIError(
                400,
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "rejected",
            400,
            "4xx",
            "api_error",
            "committed",
        ),
        (
            APIError(
                503,
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "transport_ambiguous",
            503,
            "5xx",
            "api_error",
            "provider_outcome_unknown",
        ),
        (
            RuntimeError("sensitive-provider-material"),
            "unknown",
            None,
            None,
            "unknown",
            "provider_outcome_unknown",
        ),
    ],
)
def test_provider_failure_classification_uses_only_known_adapter_evidence(
    error: Exception,
    expected_kind: AIBuilderProviderFailureKind,
    expected_status_code: int | None,
    expected_status_class: str | None,
    expected_exception_class: str,
    expected_turn_state: str,
) -> None:
    failure = classify_ai_builder_provider_failure(
        error,
        stage="proposal_completion",
    )

    assert failure.kind == expected_kind
    assert failure.stage == "proposal_completion"
    assert failure.status_code == expected_status_code
    assert failure.status_class == expected_status_class
    assert failure.exception_class == expected_exception_class
    assert failure.turn_state == expected_turn_state
    assert failure.retry_scope == (
        "new_turn" if expected_turn_state == "committed" else "acknowledged_same_turn"
    )
    assert failure.another_call_permitted is False
    assert failure.public_error.code == (
        AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR
        if expected_turn_state == "committed"
        else AIBuilderErrorCode.SESSION_TURN_PROVIDER_OUTCOME_UNKNOWN
    )
    assert failure.fingerprint == make_failure_fingerprint(
        "ai_builder_provider",
        "proposal_completion",
        expected_kind,
        expected_status_code,
    )


def test_provider_failure_unknown_shape_fails_closed_without_status() -> None:
    class UnknownAdapterError(Exception):
        status_code = 429
        response = {"status_code": 429, "body": "sensitive-provider-material"}

    failure = classify_ai_builder_provider_failure(
        UnknownAdapterError("sensitive-provider-material"),
        stage="slot_classification",
    )

    assert failure.kind == "unknown"
    assert failure.status_code is None
    assert failure.status_class is None


def test_provider_failure_event_is_one_bounded_content_free_row() -> None:
    event_logger = MagicMock()
    tenant_id = uuid4()
    telemetry = ProposalTurnTelemetry(
        request_id="req-provider-failure",
        model="private-model",
        target_kind=TargetKind.CREATE,
    )
    telemetry.start_attempt(counts_as_repair=False)

    failure = record_ai_builder_provider_failure(
        RateLimitError(
            "sensitive-provider-material",
            model="private-model",
            llm_provider="private-provider",
        ),
        stage="proposal_completion",
        usage_tracker=telemetry,
        request_id="req-provider-failure",
        tenant_id=tenant_id,
        event_logger=event_logger,
    )

    event_logger.info.assert_called_once()
    assert event_logger.info.call_args.args == ("failure_event",)
    payload = event_logger.info.call_args.kwargs["extra"]
    assert payload == {
        "event": "ai_builder.provider.failure",
        "schema_version": FAILURE_EVENT_SCHEMA_VERSION,
        "component": "ai_builder",
        "operation": "proposal_completion",
        "failure_kind": "rate_limited",
        "failure_code": "4xx",
        "failure_fingerprint": failure.fingerprint,
        "request_id": "req-provider-failure",
        "session_id": None,
        "tenant_id": str(tenant_id),
        "replay_handle": None,
        "safe_detail": {
            "provider_status_code": 429,
            "provider_status_class": "4xx",
            "provider_extraction_source": "response",
            "provider_extraction_status": "absent",
            "provider_elapsed_ms": None,
            "deadline_reached": None,
        },
    }
    attempts = telemetry.build_planner_telemetry()["proposal_attempts"]
    assert attempts[0]["failure_kind"] == "provider_error"
    assert "provider_failure_kind" not in attempts[0]
    assert "provider_status_code" not in attempts[0]
    encoded = json.dumps(payload)
    assert "sensitive-provider-material" not in encoded
    assert "private-model" not in encoded
    assert "private-provider" not in encoded


def test_provider_incident_evidence_drops_untrusted_failure_facts() -> None:
    event_logger = MagicMock()
    request_evidence = AIBuilderProviderRequestEvidence(
        route=CompletionRouteEvidence(
            configuration_fields=(),
            unclassified_configuration_field_count=0,
            model_kwargs_capabilities=(),
        ),
        sdk_input_fields=(
            CompletionEvidenceField(
                name="temperature",
                json_type="number",
                domain="model_control",
            ),
        ),
        unclassified_sdk_input_field_count=0,
    )

    record_ai_builder_provider_failure(
        BadRequestError(
            "sensitive-provider-material",
            model="private-model",
            llm_provider="private-provider",
            body={
                "code": "raw provider body must not survive",
                "param": "unlisted_parameter",
            },
        ),
        stage="proposal_completion",
        request_id="private-request-id",
        tenant_id=uuid4(),
        incident_evidence=request_evidence,
        event_logger=event_logger,
    )

    evidence_calls = [
        call
        for call in event_logger.info.call_args_list
        if call.args == ("ai_builder_provider_incident_evidence",)
    ]
    assert len(evidence_calls) == 1
    assert set(evidence_calls[0].kwargs["extra"]) == {
        AI_BUILDER_PROVIDER_INCIDENT_EVIDENCE_LOG_KEY
    }
    evidence = evidence_calls[0].kwargs["extra"][
        AI_BUILDER_PROVIDER_INCIDENT_EVIDENCE_LOG_KEY
    ]
    assert evidence["failure"] == {
        "kind": "rejected",
        "stage": "proposal_completion",
        "exception_class": "bad_request",
        "status_code": 400,
        "status_class": "4xx",
        "rejection_class": "provider_rejection",
    }
    encoded = json.dumps(evidence)
    for forbidden in (
        "raw provider body must not survive",
        "unlisted_parameter",
        "sensitive-provider-material",
        "private-model",
        "private-provider",
        "private-request-id",
    ):
        assert forbidden not in encoded


@pytest.mark.parametrize(
    "source", ["body", "nested_body", "response", "empty_body", "message_only_body"]
)
def test_classifier_failure_logs_provider_rejection_fields(source: str) -> None:
    provider_error = {
        "code": "unsupported_value",
        "param": "temperature",
        "message": "private prompt and provider credentials",
    }
    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://private-endpoint.example/chat"),
        json={"error": provider_error},
    )
    error = BadRequestError(
        "private prompt and provider credentials",
        model="private-model",
        llm_provider="azure",
        body=(
            provider_error
            if source == "body"
            else {"error": provider_error}
            if source == "nested_body"
            else {}
            if source == "empty_body"
            else {"message": "private prompt and provider credentials"}
            if source == "message_only_body"
            else None
        ),
        response=response,
    )
    event_logger = MagicMock()

    failure = record_ai_builder_provider_failure(
        error, stage="slot_classification", event_logger=event_logger
    )

    payload = event_logger.info.call_args.kwargs["extra"]
    assert payload["safe_detail"] == {
        "provider_status_code": 400,
        "provider_status_class": "4xx",
        "provider_error_code": "unsupported_value",
        "provider_parameter": "temperature",
        "provider_extraction_source": (
            "body"
            if source == "body"
            else "body.error"
            if source == "nested_body"
            else "response.error"
        ),
        "provider_extraction_status": "found",
        "provider_elapsed_ms": None,
        "deadline_reached": None,
    }
    assert failure.parameter == "temperature"
    assert "private" not in json.dumps(payload)


def test_provider_failure_retains_unknown_code_and_reports_suppressed_parameter() -> (
    None
):
    event_logger = MagicMock()
    record_ai_builder_provider_failure(
        BadRequestError(
            "private-message",
            model="private-model",
            llm_provider="azure",
            body={"error": {"code": "future_code", "param": "private-param"}},
        ),
        stage="slot_classification",
        event_logger=event_logger,
    )

    payload = event_logger.info.call_args.kwargs["extra"]
    assert payload["safe_detail"] == {
        "provider_status_code": 400,
        "provider_status_class": "4xx",
        "provider_error_code": "future_code",
        "provider_extraction_source": "body.error",
        "provider_extraction_status": "suppressed",
        "provider_elapsed_ms": None,
        "deadline_reached": None,
    }
    assert "private" not in json.dumps(payload)


@pytest.mark.parametrize(
    ("body", "status", "code", "parameter"),
    [
        ({"message": "private prose"}, "absent", None, None),
        ({"error": []}, "malformed", None, None),
        ({"code": "future_code_2"}, "found", "future_code_2", None),
        ({"code": "x" * 64}, "found", "x" * 64, None),
        ({"code": "x" * 65}, "suppressed", None, None),
        ({"code": "private prose"}, "suppressed", None, None),
        ({"code": "cödé"}, "suppressed", None, None),
        ({"code": ["unsupported_value"]}, "suppressed", None, None),
        ({"param": "temperature"}, "found", None, "temperature"),
        ({"param": "tools[0].function.parameters"}, "found", None, "tools"),
        ({"param": "messages.0.content"}, "found", None, "messages"),
        (
            {"param": "response_format.json_schema.schema"},
            "found",
            None,
            "response_format",
        ),
        (
            {"param": "tools[0].function.parameters.properties.private_schema_name"},
            "suppressed",
            None,
            None,
        ),
        ({"param": "temperature.private_suffix"}, "suppressed", None, None),
    ],
)
def test_provider_rejection_extraction_status(
    body: dict[str, object], status: str, code: str | None, parameter: str | None
) -> None:
    event_logger = MagicMock()
    error = BadRequestError(
        "private prose",
        model="test",
        llm_provider="azure",
        body=body,
        response=httpx.Response(
            400, json={}, request=httpx.Request("POST", "https://provider.example")
        ),
    )

    failure = record_ai_builder_provider_failure(
        error, stage="slot_classification", event_logger=event_logger
    )

    detail = event_logger.info.call_args.kwargs["extra"]["safe_detail"]
    assert detail["provider_extraction_status"] == status
    assert detail.get("provider_error_code") == code
    assert detail.get("provider_parameter") == parameter
    assert failure.parameter == parameter
    assert "private" not in json.dumps(detail)


@pytest.mark.parametrize("header", ["x-request-id", "apim-request-id"])
def test_message_only_rejection_retains_provider_correlation_id(header: str) -> None:
    event_logger = MagicMock()
    error = BadRequestError(
        "private prose",
        model="test",
        llm_provider="azure",
        body={"message": "private prose"},
        response=httpx.Response(
            400,
            json={},
            headers={header: "req-1234"},
            request=httpx.Request("POST", "https://provider.example"),
        ),
    )

    record_ai_builder_provider_failure(
        error, stage="slot_classification", event_logger=event_logger
    )

    detail = event_logger.info.call_args.kwargs["extra"]["safe_detail"]
    assert detail["provider_extraction_status"] == "absent"
    assert detail["provider_correlation_id"] == "req-1234"
    assert "private" not in json.dumps(detail)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, text="not JSON"),
        httpx.Response(400, stream=httpx.ByteStream(b"unread")),
        httpx.Response(400, json=["unexpected shape"]),
        httpx.Response(400, json={"error": {"param": "x" * 65_536}}),
    ],
)
def test_unusable_provider_body_preserves_original_failure(
    response: httpx.Response,
) -> None:
    response.request = httpx.Request("POST", "https://provider.example/chat")
    error = BadRequestError(
        "rejected", model="test", llm_provider="azure", response=response
    )

    failure = record_ai_builder_provider_failure(
        error, stage="slot_classification", event_logger=MagicMock()
    )

    assert failure.kind == "rejected"
    assert failure.parameter is None
    assert failure.another_call_permitted is False


def test_proposal_turn_telemetry_first_attempt_is_first_write_wins() -> None:
    telemetry = ProposalTurnTelemetry(
        request_id="req-first-write",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )

    assert telemetry.record_first_attempt(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        success=False,
        failure_kind="missing_submission_tool",
    )
    assert not telemetry.record_first_attempt(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        success=True,
    )

    payload = telemetry.build_planner_telemetry()
    assert payload["proposal_first_attempt_success"] is False
    assert payload["proposal_first_attempt_failure_kind"] == "missing_submission_tool"


def test_proposal_repair_reason_maps_tool_failures() -> None:
    assert proposal_repair_reason_from_tool_failure("parse") == "parse"
    assert proposal_repair_reason_from_tool_failure("validation") == "validation"
    assert proposal_repair_reason_from_tool_failure("quality") == "quality"
    assert proposal_repair_reason_from_tool_failure(None) == "validation"


def test_architecture_failure_kind_is_not_a_repair_reason() -> None:
    assert "architecture" in get_args(ProposalFailureKind)
    assert "architecture" not in get_args(ProposalRepairReason)


def test_proposal_first_attempt_log_uses_nested_payload() -> None:
    event_logger = MagicMock()

    log_proposal_first_attempt(
        request_id="req-log",
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        success=False,
        failure_kind="quality",
        event_logger=event_logger,
    )

    event_logger.info.assert_called_once()
    (message,) = event_logger.info.call_args.args
    assert message == "ai_builder_proposal_first_attempt"
    payload = event_logger.info.call_args.kwargs["extra"][PROPOSAL_TELEMETRY_LOG_KEY]
    assert payload == {
        "event": "ai_builder.proposal.first_attempt",
        "schema_version": PROPOSAL_TELEMETRY_SCHEMA_VERSION,
        "operation": "first_attempt",
        "request_id": "req-log",
        "tool_name": PROPOSE_FLOW_TOOL_NAME,
        "success": False,
        "failure_kind": "quality",
    }


def test_successful_proposal_first_attempt_log_omits_failure_kind() -> None:
    event_logger = MagicMock()

    log_proposal_first_attempt(
        request_id="req-log",
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        success=True,
        failure_kind=None,
        event_logger=event_logger,
    )

    payload = event_logger.info.call_args.kwargs["extra"][PROPOSAL_TELEMETRY_LOG_KEY]
    assert "failure_kind" not in payload


def test_proposal_repair_log_uses_nested_payload() -> None:
    event_logger = MagicMock()

    log_proposal_repair_invoked(
        request_id="req-log",
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        reason="parse",
        event_logger=event_logger,
    )

    event_logger.info.assert_called_once()
    (message,) = event_logger.info.call_args.args
    assert message == "ai_builder_proposal_repair_invoked"
    payload = event_logger.info.call_args.kwargs["extra"][PROPOSAL_TELEMETRY_LOG_KEY]
    assert payload == {
        "event": "ai_builder.proposal.repair_invoked",
        "schema_version": PROPOSAL_TELEMETRY_SCHEMA_VERSION,
        "operation": "repair_invoked",
        "request_id": "req-log",
        "tool_name": PROPOSE_FLOW_TOOL_NAME,
        "reason": "parse",
    }


def test_apply_failure_log_uses_typed_apply_payload() -> None:
    event_logger = MagicMock()
    session_id = uuid4()
    plan_id = uuid4()
    flow_id = uuid4()

    log_apply_failed(
        phase="apply_authoring",
        plan_id=plan_id,
        session_id=session_id,
        target_kind=TargetKind.EDIT,
        flow_id=flow_id,
        exception=BadRequestLike("stale", code="stale_revision"),
        changeset_counts=ChangesetCountSummary(
            steps_created=1,
            steps_updated=2,
            steps_removed=0,
            assistants_to_create=1,
            assistants_to_update=2,
        ),
        materializer_progress=MaterializerProgressSnapshot(
            stage="flow_updated",
            assistants_created=1,
            assistants_configured=1,
            assistants_updated=2,
            flow_created=False,
            flow_updated=True,
        ),
        event_logger=event_logger,
    )

    event_logger.info.assert_called_once()
    (message,) = event_logger.info.call_args.args
    assert message == "ai_builder_apply_failed"
    payload = event_logger.info.call_args.kwargs["extra"][APPLY_TELEMETRY_LOG_KEY]
    assert payload == {
        "event": "ai_builder.apply.failed",
        "schema_version": APPLY_TELEMETRY_SCHEMA_VERSION,
        "operation": "apply_failed",
        "phase": "apply_authoring",
        "plan_id": str(plan_id),
        "session_id": str(session_id),
        "target_kind": "edit",
        "flow_id": str(flow_id),
        "exception_class": "BadRequestLike",
        "code": "stale_revision",
        "changeset_counts": {
            "steps_created": 1,
            "steps_updated": 2,
            "steps_removed": 0,
            "assistants_to_create": 1,
            "assistants_to_update": 2,
        },
        "materializer_progress": {
            "stage": "flow_updated",
            "assistants_created": 1,
            "assistants_configured": 1,
            "assistants_updated": 2,
            "flow_created": False,
            "flow_updated": True,
        },
    }


def test_changeset_count_summary_maps_preview_counts_to_log_projection() -> None:
    preview = FlowAuthoringPreview(
        kind="edit",
        flow_id=uuid4(),
        base_revision=42,
        spec_hash="spec-hash",
        steps_created=1,
        steps_updated=2,
        steps_removed=3,
        assistants_to_create=4,
        assistants_to_update=5,
        resource_bindings_count=7,
        step_changes=(),
    )

    summary = ChangesetCountSummary.from_preview(preview)

    assert summary.model_dump() == {
        "steps_created": 1,
        "steps_updated": 2,
        "steps_removed": 3,
        "assistants_to_create": 4,
        "assistants_to_update": 5,
    }


def test_emitted_failure_kinds_are_a_subset_of_the_taxonomy() -> None:
    emitted = _tool_processing_failure_kinds_from_source()

    assert emitted
    assert emitted <= set(get_args(ToolProcessingFailureKind))


class BadRequestLike(Exception):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def test_persisted_call_records_read_back_through_the_typed_model() -> None:
    """The writer and the reader share one shape; a classifier-only turn is visible."""

    telemetry = ProposalTurnTelemetry(
        request_id="req-classifier-only",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )
    call = telemetry.begin_call(call_kind="slot_classification")
    telemetry.complete_call(
        call=call, usage=CompletionTokenUsage(9_000, 400, 9_400, source="provider")
    )

    metadata = {"planner_telemetry": telemetry.build_planner_telemetry()}
    read = planner_call_records_from_metadata(metadata)

    assert [(r.call_kind, r.attempt, r.total_tokens) for r in read.records] == [
        ("slot_classification", 1, 9_400)
    ]
    assert read.records[0].prompt_tokens == 9_000
    assert read.records[0].provider_failure_kind is None
    assert read.records[0].classification_outcome is None
    assert read.skipped == 0


def test_a_reasked_classification_persists_the_outcome_of_each_ask() -> None:
    telemetry = ProposalTurnTelemetry(
        request_id="req-reask", model="private-model", target_kind=TargetKind.CREATE
    )
    for outcome in ("output_limit_exceeded", "resolved"):
        call = telemetry.begin_call(call_kind="slot_classification")
        telemetry.complete_call(
            call=call, usage=CompletionTokenUsage(900, 40, 940, source="provider")
        )
        telemetry.record_classification_outcome(attempt=call.attempt, outcome=outcome)

    read = planner_call_records_from_metadata(
        {"planner_telemetry": telemetry.build_planner_telemetry()}
    )

    assert [(r.attempt, r.classification_outcome) for r in read.records] == [
        (1, "output_limit_exceeded"),
        (2, "resolved"),
    ]
    assert read.skipped == 0


def test_a_classification_outcome_belongs_to_a_classification_call_only() -> None:
    telemetry = ProposalTurnTelemetry(
        request_id="req-reask", model="private-model", target_kind=TargetKind.CREATE
    )
    call = telemetry.begin_call(call_kind="proposal_initial")

    with pytest.raises(ValueError):
        telemetry.record_classification_outcome(
            attempt=call.attempt, outcome="resolved"
        )
    with pytest.raises(ValueError):
        telemetry.record_classification_outcome(attempt=2, outcome="resolved")
    with pytest.raises(ValueError):
        telemetry.record_classification_outcome(attempt=0, outcome="resolved")


@pytest.mark.parametrize("stored", ["skipped_context_budget", "bogus", 3, []])
def test_a_stored_classification_outcome_outside_the_per_call_set_is_skipped(
    stored: object,
) -> None:
    record: dict[str, object] = {
        "call_kind": "slot_classification",
        "request_id": "r",
        "attempt": 1,
        "token_usage_source": "provider",
        "token_usage_estimated": False,
        "classification_outcome": stored,
    }

    read = planner_call_records_from_metadata(
        {"planner_telemetry": {"call_records": [record]}}
    )

    assert (read.records, read.skipped) == ((), 1)


def test_call_records_an_older_build_wrote_in_another_shape_are_counted_as_skipped() -> (
    None
):
    metadata = {
        "planner_telemetry": {
            "call_records": [
                {"call_kind": "not_a_kind", "request_id": "r", "attempt": 1},
                {
                    "call_kind": "proposal_initial",
                    "request_id": "r",
                    "attempt": 2,
                    "token_usage_source": "provider",
                    "token_usage_estimated": False,
                    "total_tokens": 12,
                },
                "garbage",
            ]
        }
    }

    read = planner_call_records_from_metadata(metadata)

    assert [(r.call_kind, r.attempt) for r in read.records] == [("proposal_initial", 2)]
    assert read.skipped == 2
    assert planner_call_records_from_metadata(None).skipped == 0
    assert planner_call_records_from_metadata({"planner_telemetry": {}}).skipped == 1
    assert planner_call_records_from_metadata({"planner_telemetry": []}).skipped == 1


def _classification_budget_at_the_gateway() -> AIBuilderResolvedRequestBudget:
    resolved = AIBuilderRequestBudget(
        capacity=ModelCapacity(131_072, 16_384),
        safety_buffer_tokens=2_000,
        timeout_seconds=180.0,
    ).resolve_whole(input_tokens=112_688)
    assert resolved is not None
    return resolved


def test_a_gateway_status_before_the_deadline_is_named_as_an_upstream_timeout() -> None:
    event_logger = MagicMock()

    failure = record_ai_builder_provider_failure(
        APIError(
            504,
            "sensitive-provider-material",
            model="private-model",
            llm_provider="private-provider",
        ),
        stage="slot_classification",
        request_id="req-upstream-timeout",
        request_budget=_classification_budget_at_the_gateway(),
        timing=ProviderCallTiming(provider_elapsed_ms=125_172),
        event_logger=event_logger,
    )

    assert failure.turn_state == "provider_outcome_unknown"
    safe_detail = event_logger.info.call_args.kwargs["extra"]["safe_detail"]
    assert safe_detail["request_budget_tokens"] == 131_072
    assert safe_detail["provider_status_code"] == 504
    assert safe_detail["provider_elapsed_ms"] == 125_172
    assert safe_detail["deadline_reached"] is False
    assert safe_detail["upstream_timeout_suspected"] is True
    event_logger.warning.assert_called_once()
    assert "sensitive-provider-material" not in str(event_logger.warning.call_args)


def test_a_call_that_ran_into_the_silence_deadline_is_not_blamed_on_a_proxy() -> None:
    event_logger = MagicMock()

    record_ai_builder_provider_failure(
        ProviderSilenceExpired(300.0),
        stage="slot_classification",
        request_id="req-local-deadline",
        request_budget=_classification_budget_at_the_gateway(),
        timing=ProviderCallTiming(provider_elapsed_ms=180_004),
        event_logger=event_logger,
    )

    safe_detail = event_logger.info.call_args.kwargs["extra"]["safe_detail"]
    assert safe_detail["deadline_reached"] is True
    assert safe_detail["local_deadline"] == "silence"
    assert "upstream_timeout_suspected" not in safe_detail
    event_logger.warning.assert_not_called()


def test_a_provider_error_after_long_healthy_streaming_is_not_a_deadline() -> None:
    # 350 s of arriving chunks, then a provider error: no local timer expired,
    # so the elapsed time says nothing about the silence deadline.
    event_logger = MagicMock()

    record_ai_builder_provider_failure(
        APIError(
            500,
            "sensitive-provider-material",
            model="private-model",
            llm_provider="private-provider",
        ),
        stage="proposal_completion",
        request_id="req-long-stream",
        request_budget=_classification_budget_at_the_gateway(),
        timing=ProviderCallTiming(provider_elapsed_ms=350_000),
        event_logger=event_logger,
    )

    safe_detail = event_logger.info.call_args.kwargs["extra"]["safe_detail"]
    assert safe_detail["deadline_reached"] is False
    assert "local_deadline" not in safe_detail
    assert "upstream_timeout_suspected" not in safe_detail


def test_a_503_before_the_deadline_is_an_upstream_failure_not_a_timeout() -> None:
    event_logger = MagicMock()

    record_ai_builder_provider_failure(
        APIError(
            503,
            "sensitive-provider-material",
            model="private-model",
            llm_provider="private-provider",
        ),
        stage="slot_classification",
        request_id="req-upstream-503",
        request_budget=_classification_budget_at_the_gateway(),
        timing=ProviderCallTiming(provider_elapsed_ms=2_000),
        event_logger=event_logger,
    )

    safe_detail = event_logger.info.call_args.kwargs["extra"]["safe_detail"]
    assert safe_detail["provider_status_code"] == 503
    assert safe_detail["deadline_reached"] is False
    assert "upstream_timeout_suspected" not in safe_detail
    event_logger.warning.assert_not_called()


def test_a_refused_request_is_a_failed_call_and_its_replacement() -> None:
    tracker = ProposalTurnTelemetry(
        request_id="req-retry", model="gpt-test", target_kind=TargetKind.CREATE
    )
    refused = tracker.begin_call(call_kind="slot_classification")
    failure = classify_ai_builder_provider_failure(
        BadRequestError(
            message="temperature",
            model="gpt-test",
            llm_provider="azure",
            body={"error": {"param": "temperature", "code": "unsupported_value"}},
        ),
        stage="slot_classification",
    )

    replacement = tracker.retry_call(call=refused, failure=failure)

    assert tracker.llm_calls_made == 2
    assert tracker.call_records[0].provider_failure_kind == "rejected"
    assert tracker.call_records[0].provider_status_class == "4xx"
    assert replacement.attempt == 2
    assert replacement.call_kind == "slot_classification"


def _failed_turn_tracker() -> tuple[
    ProposalTurnTelemetry, AIBuilderResolvedRequestBudget
]:
    request_budget = AIBuilderRequestBudget(
        capacity=ModelCapacity(32_000, 16_000),
        safety_buffer_tokens=2_000,
        timeout_seconds=180.0,
    ).resolve_whole(input_tokens=6_000)
    assert request_budget is not None
    return (
        ProposalTurnTelemetry(
            request_id="req-failed-turn",
            model="openai/gpt-5.4-nano",
            target_kind=TargetKind.EDIT,
        ),
        request_budget,
    )


def test_a_truncated_call_reports_its_usage_provenance_and_cap() -> None:
    telemetry, request_budget = _failed_turn_tracker()
    telemetry.start_attempt(counts_as_repair=False, request_budget=request_budget)
    telemetry.record_response(
        finish_reason="length",
        usage=CompletionTokenUsage(
            9_000, 4_000, 13_000, source="provider", reasoning_tokens=3_900
        ),
    )
    telemetry.record_attempt_failure(
        failure_kind="provider_truncation", producers=frozenset()
    )

    assert telemetry.failed_turn_details() == {
        "llm_calls": 1,
        "calls_without_usage": 0,
        "token_usage_source": "provider",
        "turn_prompt_tokens": 9_000,
        "turn_completion_tokens": 4_000,
        "turn_reasoning_tokens": 3_900,
        "last_response_finish_reason": "length",
        "last_call_output_cap_tokens": request_budget.provider_output_cap_tokens,
    }


def test_a_call_without_provider_usage_is_reported_unknown_never_zero() -> None:
    telemetry, request_budget = _failed_turn_tracker()
    telemetry.start_attempt(counts_as_repair=False, request_budget=request_budget)
    telemetry.record_attempt_failure(
        failure_kind="internal_error", producers=frozenset()
    )

    details = telemetry.failed_turn_details()

    assert details == {
        "llm_calls": 1,
        "calls_without_usage": 1,
        "token_usage_source": "none",
        "last_call_output_cap_tokens": request_budget.provider_output_cap_tokens,
    }


def test_an_estimated_usage_is_labelled_and_reports_no_reasoning() -> None:
    telemetry, request_budget = _failed_turn_tracker()
    telemetry.start_attempt(counts_as_repair=False, request_budget=request_budget)
    telemetry.record_response(
        finish_reason="length",
        usage=CompletionTokenUsage(5, 2, 7, source="litellm_estimate", estimated=True),
    )

    details = telemetry.failed_turn_details()

    assert details["token_usage_source"] == "litellm_estimate"
    # An estimate counts as reported usage; only a call with no counts is missing.
    assert details["calls_without_usage"] == 0
    assert details["turn_prompt_tokens"] == 5
    assert "turn_reasoning_tokens" not in details


def test_a_turn_that_never_called_the_provider_has_no_call_details() -> None:
    telemetry, _ = _failed_turn_tracker()

    assert telemetry.failed_turn_details() == {}


def _record_call(
    telemetry: ProposalTurnTelemetry,
    request_budget: AIBuilderResolvedRequestBudget,
    usage: CompletionTokenUsage | None,
    *,
    finish_reason: str | None = "stop",
) -> None:
    telemetry.start_attempt(counts_as_repair=False, request_budget=request_budget)
    if usage is None:
        telemetry.record_attempt_failure(
            failure_kind="internal_error", producers=frozenset()
        )
    else:
        telemetry.record_response(finish_reason=finish_reason, usage=usage)


def test_a_total_only_usage_publishes_no_prompt_or_completion_counts() -> None:
    telemetry, request_budget = _failed_turn_tracker()
    _record_call(
        telemetry,
        request_budget,
        CompletionTokenUsage(None, None, 140, source="provider"),
    )

    details = telemetry.failed_turn_details()

    assert details["token_usage_source"] == "provider"
    assert "turn_prompt_tokens" not in details
    assert "turn_completion_tokens" not in details


def test_a_count_is_published_only_when_every_observed_call_reported_it() -> None:
    telemetry, request_budget = _failed_turn_tracker()
    _record_call(
        telemetry,
        request_budget,
        CompletionTokenUsage(10, 5, 15, source="provider", reasoning_tokens=3),
    )
    _record_call(
        telemetry, request_budget, CompletionTokenUsage(20, 8, 28, source="provider")
    )
    _record_call(telemetry, request_budget, None)

    details = telemetry.failed_turn_details()

    assert details["llm_calls"] == 3
    assert details["calls_without_usage"] == 1
    assert details["turn_prompt_tokens"] == 30
    assert details["turn_completion_tokens"] == 13
    assert "turn_reasoning_tokens" not in details


def test_reasoning_tokens_are_summed_when_every_observed_call_reported_them() -> None:
    telemetry, request_budget = _failed_turn_tracker()
    for reasoning in (3, 4):
        _record_call(
            telemetry,
            request_budget,
            CompletionTokenUsage(
                10, 5, 15, source="provider", reasoning_tokens=reasoning
            ),
        )

    assert telemetry.failed_turn_details()["turn_reasoning_tokens"] == 7


def test_an_unrecognised_finish_reason_is_published_as_other() -> None:
    telemetry, request_budget = _failed_turn_tracker()
    _record_call(
        telemetry,
        request_budget,
        CompletionTokenUsage(10, 5, 15, source="provider"),
        finish_reason="the provider wrote a sentence here",
    )

    assert telemetry.failed_turn_details()["last_response_finish_reason"] == "other"


def test_a_negative_provider_count_is_never_published_as_call_evidence() -> None:
    telemetry, request_budget = _failed_turn_tracker()
    _record_call(
        telemetry,
        request_budget,
        CompletionTokenUsage(10, 5, 15, source="provider", reasoning_tokens=3),
    )
    malformed = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=-4_000,
            completion_tokens=4_000,
            total_tokens=-1,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=-1),
        )
    )
    _record_call(
        telemetry,
        request_budget,
        completion_token_usage_from_response(
            malformed, model_name="openai/gpt-5.4", messages=[]
        ),
    )

    details = telemetry.failed_turn_details()
    per_call = telemetry.build_planner_telemetry()["call_records"][-1]

    assert details["turn_completion_tokens"] == 4_005
    assert "turn_prompt_tokens" not in details
    assert "turn_reasoning_tokens" not in details
    assert "prompt_tokens" not in per_call
    assert per_call["completion_tokens"] == 4_000
    assert all(
        value >= 0 for value in details.values() if isinstance(value, int | float)
    )


def test_a_provider_and_an_estimate_are_summed_and_labelled_as_an_estimate() -> None:
    telemetry, request_budget = _failed_turn_tracker()
    _record_call(
        telemetry,
        request_budget,
        CompletionTokenUsage(1_000, 500, 1_500, source="provider", reasoning_tokens=9),
    )
    _record_call(
        telemetry,
        request_budget,
        CompletionTokenUsage(50, 20, 70, source="litellm_estimate", estimated=True),
    )

    details = telemetry.failed_turn_details()

    assert details["token_usage_source"] == "litellm_estimate"
    assert details["calls_without_usage"] == 0
    assert details["turn_prompt_tokens"] == 1_050
    assert details["turn_completion_tokens"] == 520
    assert "turn_reasoning_tokens" not in details


def test_the_evidence_is_a_closed_set_published_in_priority_order() -> None:
    # The order is the priority a shared details bound keeps: the per-call
    # facts, then the qualifiers every token sum needs, then the sums, then the
    # call count. A sum is what gets dropped under key pressure, never the
    # source and missing-usage qualifier it is read with.
    assert FAILED_TURN_EVIDENCE_KEYS == (
        "last_response_finish_reason",
        "last_call_output_cap_tokens",
        "token_usage_source",
        "calls_without_usage",
        "turn_reasoning_tokens",
        "turn_completion_tokens",
        "turn_prompt_tokens",
        "llm_calls",
    )
    telemetry, request_budget = _failed_turn_tracker()
    _record_call(
        telemetry,
        request_budget,
        CompletionTokenUsage(
            9_000, 4_000, 13_000, source="provider", reasoning_tokens=1
        ),
        finish_reason="length",
    )
    assert tuple(telemetry.failed_turn_details()) == FAILED_TURN_EVIDENCE_KEYS


def test_absent_figures_leave_the_remaining_evidence_in_priority_order() -> None:
    telemetry, request_budget = _failed_turn_tracker()
    _record_call(
        telemetry,
        request_budget,
        CompletionTokenUsage(None, None, 140, source="provider"),
        finish_reason="length",
    )

    details = telemetry.failed_turn_details()

    assert "turn_prompt_tokens" not in details
    assert list(details) == [key for key in FAILED_TURN_EVIDENCE_KEYS if key in details]


def test_the_output_cap_is_the_last_calls_and_the_finish_reason_the_last_response() -> (
    None
):
    telemetry, first_budget = _failed_turn_tracker()
    second_budget = AIBuilderRequestBudget(
        capacity=ModelCapacity(32_000, 8_000),
        safety_buffer_tokens=2_000,
        timeout_seconds=180.0,
    ).resolve_whole(input_tokens=6_000)
    assert second_budget is not None
    assert second_budget.provider_output_cap_tokens != (
        first_budget.provider_output_cap_tokens
    )
    _record_call(
        telemetry,
        first_budget,
        CompletionTokenUsage(9_000, 4_000, 13_000, source="provider"),
        finish_reason="length",
    )
    telemetry.start_attempt(counts_as_repair=True, request_budget=second_budget)
    pending = telemetry.call_records[-1]
    telemetry.fail_call(
        call=pending,
        failure=classify_ai_builder_provider_failure(
            RateLimitError(message="slow down", llm_provider="openai", model="gpt"),
            stage="proposal_completion",
        ),
    )

    details = telemetry.failed_turn_details()

    assert details["llm_calls"] == 2
    assert details["calls_without_usage"] == 1
    assert details["last_response_finish_reason"] == "length"
    assert (
        details["last_call_output_cap_tokens"]
        == second_budget.provider_output_cap_tokens
    )
    assert details["turn_prompt_tokens"] == 9_000


def test_an_oversized_provider_count_is_never_published_as_call_evidence() -> None:
    telemetry, request_budget = _failed_turn_tracker()
    oversized = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=10**200,
            completion_tokens=10**30,
            total_tokens=10**200,
        )
    )
    _record_call(
        telemetry,
        request_budget,
        completion_token_usage_from_response(
            oversized,
            model_name="openai/gpt-5.4",
            messages=[{"role": "user", "content": "Build a flow"}],
        ),
    )

    details = telemetry.failed_turn_details()

    assert details["token_usage_source"] == "litellm_estimate"
    assert all(value < 10**6 for value in details.values() if isinstance(value, int))


def test_a_correctable_failure_names_the_owner_that_wrote_its_feedback() -> None:
    with pytest.raises(ValueError, match="producer"):
        CorrectableFailure(feedback="fix it", kind="validation", producers=frozenset())
    with pytest.raises(TypeError):
        CorrectableFailure(feedback="fix it", kind="validation")  # type: ignore[call-arg]

    failure = CorrectableFailure(
        feedback="fix it", kind="quality", producers=frozenset({"lint", "critic"})
    )

    assert failure.producers == {"lint", "critic"}


def test_a_failed_attempt_carries_the_producers_to_every_sink() -> None:
    telemetry, request_budget = _failed_turn_tracker()
    telemetry.start_attempt(counts_as_repair=False, request_budget=request_budget)
    telemetry.record_response(
        finish_reason="tool_calls",
        usage=CompletionTokenUsage(10, 5, 15, source="provider"),
    )
    telemetry.record_attempt_failure(
        failure_kind="quality",
        failure_codes=frozenset({"vague_step_name"}),
        producers=frozenset({"platform_validator", "lint", "critic"}),
    )
    telemetry.start_attempt(counts_as_repair=True, request_budget=request_budget)
    telemetry.record_attempt_failure(
        failure_kind="missing_submission_tool", producers=frozenset()
    )

    attempts = telemetry.build_planner_telemetry()["proposal_attempts"]
    logged = build_proposal_failed_turn_payload(
        usage_tracker=telemetry,
        session_id=uuid4(),
        branch="self_correction_invalid_tool_result",
        final_failure_kind="repair_quality_failure",
        final_error_code="self_correction_quality_failure",
    ).model_dump(mode="json", exclude_none=True)

    assert [attempt["producers"] for attempt in attempts] == [
        ["critic", "lint", "platform_validator"],
        [],
    ]
    assert logged["schema_version"] == PROPOSAL_TELEMETRY_SCHEMA_VERSION == 3
    assert [attempt["producers"] for attempt in logged["proposal_attempts"]] == [
        ["critic", "lint", "platform_validator"],
        [],
    ]


@pytest.mark.parametrize(
    ("error", "local_deadline"),
    [
        (ProviderSilenceExpired(0.05), "silence"),
        (ProviderCallCeilingExpired(1.0), "ceiling"),
        (TimeoutError("raised by the SDK"), None),
        (
            Timeout("sdk", model="private-model", llm_provider="private-provider"),
            None,
        ),
    ],
)
def test_the_classifier_names_the_local_deadline_that_expired(
    error: Exception, local_deadline: str | None
) -> None:
    failure = classify_ai_builder_provider_failure(error, stage="proposal_completion")

    assert failure.kind == "timeout"
    assert failure.local_deadline == local_deadline


def test_a_failed_call_record_is_final() -> None:
    telemetry, request_budget = _failed_turn_tracker()
    call = telemetry.begin_call(
        call_kind="slot_classification", request_budget=request_budget
    )
    telemetry.fail_call(
        call=call,
        failure=classify_ai_builder_provider_failure(
            ProviderSilenceExpired(0.05), stage="slot_classification"
        ),
        timing=ProviderCallTiming(
            provider_elapsed_ms=90, first_chunk_ms=10, max_gap_ms=60
        ),
    )
    failed = telemetry.call_records[0]

    with pytest.raises(ValueError):
        telemetry.complete_call(
            call=failed, usage=CompletionTokenUsage(1, 1, 2, source="provider")
        )

    record = telemetry.build_planner_telemetry()["call_records"][0]
    assert record["provider_failure_kind"] == "timeout"
    assert record["local_deadline"] == "silence"
    assert (
        record["first_chunk_ms"],
        record["max_gap_ms"],
        record["provider_elapsed_ms"],
    ) == (10, 60, 90)
    assert "prompt_tokens" not in record


# Every construction site of a correctable failure, by the owner of the rule
# that wrote its feedback (not by the module that returns it). A merged failure
# is attributed where it is built, from the parts that contributed.
_CORRECTABLE_FAILURE_PRODUCERS: dict[tuple[str, str], list[str]] = {
    ("ai_builder_architecture_errors.py", "architecture_failure_outcome"): [
        "frozenset({_PRODUCER_BY_ARCHITECTURE_CODE[error.public_code]})"
    ],
    ("ai_builder_compiled_spec_preparation.py", "authored_knowledge_ref_repair"): [
        "platform_validator"
    ],
    ("ai_builder_create_proposal.py", "_process_create_spec"): [
        "platform_validator",
        "scope_guard",
    ],
    ("ai_builder_create_proposal.py", "process_create_intent_arguments"): ["parse"],
    ("ai_builder_edit_proposal.py", "_validate_saved_step_consumers"): [
        "platform_validator",
        "scope_guard",
    ],
    ("ai_builder_edit_proposal.py", "compile_and_prepare"): [
        "assembly",
        "platform_validator",
    ],
    ("ai_builder_edit_proposal.py", "process_edit_arguments"): [
        "parse",
        "review_guard",
        "scope_guard",
        "review_guard",
        "platform_validator",
        "critic",
        "scope_guard",
    ],
    ("ai_builder_proposal_finalization.py", "_create_quality_result"): [
        "merged",
        "merged",
    ],
    ("ai_builder_proposal_finalization.py", "_edit_quality_result"): ["merged"],
    ("ai_builder_proposal_retry.py", "_process_tool_call"): ["parse"],
    ("ai_builder_proposal_submission.py", "_handle_propose_flow_tool_call"): ["parse"],
    ("ai_builder_proposal_submission.py", "_process_submission_invocation"): ["parse"],
}


def _correctable_failure_sites() -> dict[tuple[str, str], list[str]]:
    sites: dict[tuple[str, str], list[str]] = {}
    source_root = _REPO_ROOT / "backend/src/eneo/flows"
    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(function):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "CorrectableFailure"
                ):
                    continue
                owner = min(
                    (
                        inner
                        for inner in ast.walk(function)
                        if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node in list(ast.walk(inner))
                    ),
                    key=lambda inner: len(list(ast.walk(inner))),
                )
                if owner is not function:
                    continue
                producers = next(
                    (kw.value for kw in node.keywords if kw.arg == "producers"), None
                )
                if producers is None:
                    label = "missing"
                elif (
                    isinstance(producers, ast.Call)
                    and isinstance(producers.func, ast.Name)
                    and producers.func.id == "frozenset"
                    and len(producers.args) == 1
                    and isinstance(producers.args[0], ast.Set)
                    and all(
                        isinstance(element, ast.Constant)
                        for element in producers.args[0].elts
                    )
                ):
                    label = "+".join(
                        sorted(ast.literal_eval(producers.args[0]))  # type: ignore[arg-type]
                    )
                elif isinstance(producers, ast.Name) and producers.id == "producers":
                    label = "merged"
                else:
                    label = ast.unparse(producers)
                sites.setdefault((path.name, function.name), []).append(label)
    return sites


def test_every_correctable_failure_site_names_its_rule_owner() -> None:
    sites = _correctable_failure_sites()

    assert sum(len(labels) for labels in sites.values()) == 22
    assert {site: sorted(labels) for site, labels in sites.items()} == {
        site: sorted(labels) for site, labels in _CORRECTABLE_FAILURE_PRODUCERS.items()
    }


def _rate_limited() -> AIBuilderProviderFailure:
    return classify_ai_builder_provider_failure(
        RateLimitError("limited", model="gpt-test", llm_provider="azure"),
        stage="proposal_completion",
    )


def test_a_refused_request_keeps_the_timing_of_its_own_request() -> None:
    tracker = ProposalTurnTelemetry(
        request_id="req-retry-timing", model="gpt-test", target_kind=TargetKind.CREATE
    )
    tracker.start_attempt(counts_as_repair=False)

    tracker.retry_call(
        failure=_rate_limited(), timing=ProviderCallTiming(provider_elapsed_ms=400)
    )
    tracker.record_response(
        finish_reason="stop",
        usage=CompletionTokenUsage(1, 1, 2, source="provider"),
        timing=ProviderCallTiming(
            provider_elapsed_ms=30, first_chunk_ms=10, max_gap_ms=5
        ),
    )

    refused, replacement = tracker.call_records
    assert (refused.provider_elapsed_ms, refused.first_chunk_ms) == (400, None)
    assert (replacement.provider_elapsed_ms, replacement.first_chunk_ms) == (30, 10)


def test_a_failure_without_an_open_attempt_changes_no_recorded_attempt() -> None:
    tracker = ProposalTurnTelemetry(
        request_id="req-closed", model="gpt-test", target_kind=TargetKind.CREATE
    )
    tracker.start_attempt(counts_as_repair=False)
    tracker.record_response(
        finish_reason="stop", usage=CompletionTokenUsage(1, 1, 2, source="provider")
    )
    tracker.record_attempt_failure(
        failure_kind="validation",
        failure_codes=frozenset({"c1"}),
        producers=frozenset({"critic"}),
    )
    before = tracker.build_planner_telemetry()

    with pytest.raises(ValueError, match="open attempt"):
        tracker.fail_attempt(failure=_rate_limited())

    assert tracker.build_planner_telemetry() == before


@pytest.mark.parametrize("failure_kind", ["parse", "validation", "quality"])
def test_a_correctable_failure_is_never_recorded_without_its_producers(
    failure_kind: ProposalAttemptFailureKind,
) -> None:
    tracker = ProposalTurnTelemetry(
        request_id="req-producers", model="gpt-test", target_kind=TargetKind.CREATE
    )
    tracker.start_attempt(counts_as_repair=False)

    with pytest.raises(ValueError, match="producer"):
        tracker.record_attempt_failure(failure_kind=failure_kind, producers=frozenset())

    assert tracker.proposal_attempts == []


@pytest.mark.parametrize(
    "failure_kind",
    [
        "missing_submission_tool",
        "architecture",
        "provider_truncation",
        "internal_error",
    ],
)
def test_a_failure_nobody_corrects_may_name_no_producer(
    failure_kind: ProposalAttemptFailureKind,
) -> None:
    tracker = ProposalTurnTelemetry(
        request_id="req-no-producers", model="gpt-test", target_kind=TargetKind.CREATE
    )
    tracker.start_attempt(counts_as_repair=False)

    tracker.record_attempt_failure(failure_kind=failure_kind, producers=frozenset())

    assert tracker.proposal_attempts[-1].failure_kind == failure_kind
    assert tracker.proposal_attempts[-1].producers == ()


def test_a_provider_failure_log_keeps_its_shape_when_the_seam_never_timed_it() -> None:
    event_logger = MagicMock()

    record_ai_builder_provider_failure(
        RateLimitError("limited", model="gpt-test", llm_provider="azure"),
        stage="proposal_completion",
        request_id="req-untimed",
        timing=None,
        event_logger=event_logger,
    )

    safe_detail = event_logger.info.call_args.kwargs["extra"]["safe_detail"]
    assert safe_detail["provider_elapsed_ms"] is None
    assert safe_detail["deadline_reached"] is None
    assert "local_deadline" not in safe_detail
