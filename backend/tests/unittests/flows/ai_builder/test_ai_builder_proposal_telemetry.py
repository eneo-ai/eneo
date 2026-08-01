from __future__ import annotations

import ast
import json
from pathlib import Path
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
from pydantic import ValidationError

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
    AIBuilderProviderFailureKind,
    AIBuilderProviderRequestEvidence,
    classify_ai_builder_provider_failure,
    record_ai_builder_provider_failure,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    APPLY_TELEMETRY_LOG_KEY,
    APPLY_TELEMETRY_SCHEMA_VERSION,
    PROPOSAL_TELEMETRY_LOG_KEY,
    PROPOSAL_TELEMETRY_SCHEMA_VERSION,
    ApplyFailureTelemetryPayload,
    ChangesetCountSummary,
    MaterializerProgressSnapshot,
    ProposalAttemptTelemetryPayload,
    ProposalCallKind,
    ProposalFailureKind,
    ProposalRepairReason,
    ProposalTurnTelemetry,
    ToolProcessingFailureKind,
    assistant_metadata_with_usage,
    log_apply_failed,
    log_proposal_first_attempt,
    log_proposal_repair_invoked,
    proposal_repair_reason_from_tool_failure,
)
from eneo.flows.ai_builder.ai_builder_token_usage import CompletionTokenUsage
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
    _REPO_ROOT / "backend/src/eneo/flows/ai_builder/ai_builder_scoped_plan_revision.py",
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
            if function_name != "ToolProcessingResult":
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "failure_kind"
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
    for kind, usage in zip(kinds, usages, strict=True):
        call = telemetry.begin_call(call_kind=kind)
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
    assert "prompt_tokens" not in payload["call_records"][-1]
    assert "completion_tokens" not in payload["call_records"][-1]
    assert "total_tokens" not in payload["call_records"][-1]
    metadata = assistant_metadata_with_usage(
        conversation=[],
        base_metadata=None,
        usage_tracker=telemetry,
    )
    assert metadata is not None
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
                "requested_output_sections_require_section_writers",
                "raw user text must never be telemetry",
            }
        ),
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
                "requested_output_sections_require_section_writers",
            ],
            "failure_code_count": 2,
        }
    ]
    assert attempts[0]["elapsed_ms"] >= 0
    assert payload["wall_clock_ms"] >= attempts[0]["elapsed_ms"]
    encoded = json.dumps(payload)
    assert "raw user text must never be telemetry" not in encoded
    assert "prompt" not in attempts[0]
    assert "provider_payload" not in attempts[0]
    assert "secret" not in attempts[0]


def test_proposal_attempt_payload_forbids_raw_content_fields() -> None:
    with pytest.raises(ValidationError):
        ProposalAttemptTelemetryPayload(
            attempt=1,
            kind="initial",
            elapsed_ms=1,
            token_usage_source="provider",
            prompt="raw prompt must not be accepted",
        )


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
        outgoing_fields=(
            CompletionEvidenceField(
                name="temperature",
                json_type="number",
                domain="model_control",
            ),
        ),
        unclassified_outgoing_field_count=0,
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
            assistants_to_delete=0,
        ),
        materializer_progress=MaterializerProgressSnapshot(
            stage="flow_updated",
            assistants_created=1,
            assistants_configured=1,
            assistants_updated=2,
            assistants_deleted=0,
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
            "assistants_to_delete": 0,
        },
        "materializer_progress": {
            "stage": "flow_updated",
            "assistants_created": 1,
            "assistants_configured": 1,
            "assistants_updated": 2,
            "assistants_deleted": 0,
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
        assistants_to_delete=6,
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
        "assistants_to_delete": 6,
    }


def test_compile_apply_failure_payload_omits_execute_only_fields() -> None:
    payload = ApplyFailureTelemetryPayload(
        phase="prepare_authoring",
        plan_id=str(uuid4()),
        session_id=str(uuid4()),
        target_kind="create",
        flow_id=None,
        exception_class="RuntimeError",
        code=None,
        changeset_counts=None,
        materializer_progress=None,
    ).model_dump(exclude_none=True)

    assert payload["phase"] == "prepare_authoring"
    assert "code" not in payload
    assert "changeset_counts" not in payload
    assert "materializer_progress" not in payload


def test_apply_failure_payload_forbids_extra_raw_material_fields() -> None:
    with pytest.raises(ValidationError):
        ApplyFailureTelemetryPayload(
            phase="prepare_authoring",
            plan_id=str(uuid4()),
            session_id=str(uuid4()),
            target_kind="edit",
            flow_id=None,
            exception_class="RuntimeError",
            prompt="raw prompt must not be accepted",
        )


def test_apply_failure_payload_json_excludes_sensitive_material() -> None:
    sensitive_values = [
        "sensitive prompt text",
        "{{ step_a.output.secret }}",
        "raw source transcript",
    ]

    payload = ApplyFailureTelemetryPayload(
        phase="apply_authoring",
        plan_id=str(uuid4()),
        session_id=str(uuid4()),
        target_kind="edit",
        flow_id=str(uuid4()),
        exception_class="RuntimeError",
        code=None,
        changeset_counts=ChangesetCountSummary(
            steps_created=0,
            steps_updated=1,
            steps_removed=0,
            assistants_to_create=0,
            assistants_to_update=1,
            assistants_to_delete=0,
        ),
        materializer_progress=MaterializerProgressSnapshot(
            stage="assistants_updated",
            assistants_created=0,
            assistants_configured=0,
            assistants_updated=1,
            assistants_deleted=0,
            flow_created=False,
            flow_updated=False,
        ),
    ).model_dump_json(exclude_none=True)

    json.loads(payload)
    for value in sensitive_values:
        assert value not in payload


def test_emitted_failure_kinds_are_a_subset_of_the_taxonomy() -> None:
    emitted = _tool_processing_failure_kinds_from_source()

    assert emitted
    assert emitted <= set(get_args(ToolProcessingFailureKind))


class BadRequestLike(Exception):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code
