from __future__ import annotations

import logging
from datetime import (
    datetime,
    timezone,
)
from types import SimpleNamespace
from typing import TypedDict, cast
from unittest.mock import (
    AsyncMock,
    MagicMock,
)
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import eneo.flows.api.flow_trace_audit as flow_trace_audit_module
from eneo.actors.actors.space_actor import SpaceRole
from eneo.audit.domain.action_types import ActionType
from eneo.authentication.auth_dependencies import ScopeFilter
from eneo.authentication.signed_urls import verify_signed_token
from eneo.flows.api import flow_access_context as flow_access_context_module
from eneo.flows.api.flow_run_contract_models import (
    FlowFinalOutputContractPublic,
    FlowOutputDelivery,
)
from eneo.flows.api.flow_run_evidence_router import (
    export_flow_run_evidence,
    get_flow_run_evidence,
)
from eneo.flows.api.flow_run_steps_router import (
    generate_flow_run_artifact_signed_url,
    list_flow_run_steps,
)
from eneo.flows.application.flow_run_service import FlowRunStepResultWithFiles
from eneo.flows.domain.flow import FlowRunStatus, FlowStepResult
from eneo.flows.enums import (
    FlowOutputMode,
    FlowOutputType,
    FlowRunLifecycleSource,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.flow_run_redaction import redact_payload
from eneo.main.exceptions import (
    AuditLoggingUnavailableException,
    BadRequestException,
    ErrorCodes,
    UnauthorizedException,
)
from eneo.main.models import GeneralError
from eneo.roles.permissions import Permission
from eneo.server.exception_handlers import add_exception_handlers
from tests.unittests.flows.test_flow_router import (
    _enable_space_access,
    _evidence_export_payload,
    _flow,
    _result_file,
    _run,
)


class FlowErrorResponse(TypedDict):
    status_code: int
    payload: dict[str, object]


class _EvidenceTransaction:
    def __init__(
        self, events: list[str], *, exit_error: Exception | None = None
    ) -> None:
        self._events = events
        self._exit_error = exit_error

    async def __aenter__(self):
        self._events.append("transaction_enter")

    async def __aexit__(self, exc_type: object, exc: object, tb: object):
        self._events.append("transaction_exit")
        if self._exit_error is not None:
            raise self._exit_error
        return False


def _flow_error_response(
    exc: Exception, *, request_id: str | None = None
) -> FlowErrorResponse:
    app = FastAPI()
    add_exception_handlers(app)

    @app.get("/flow-error")
    async def _raise_flow_error():
        raise exc

    headers = {"x-correlation-id": request_id} if request_id is not None else {}
    with TestClient(app) as client:
        response = client.get("/flow-error", headers=headers)

    payload = response.json()
    assert isinstance(payload, dict)
    return {
        "status_code": response.status_code,
        "payload": {str(key): value for key, value in payload.items()},
    }


def test_flow_evidence_raw_reason_error_response_includes_request_id():
    response = _flow_error_response(
        BadRequestException(
            "Raw evidence export requires an explicit non-default reason.",
            code=FlowApiErrorCode.EVIDENCE_EXPORT_REASON_REQUIRED.value,
            context={
                "detail": "raw",
                "default_reason": "support_debug",
            },
        ),
        request_id="raw-evidence-reason-required-test",
    )

    assert response["status_code"] == 400
    payload = response["payload"]
    error = GeneralError.model_validate(payload)
    assert (
        error.message == "Raw evidence export requires an explicit non-default reason."
    )
    assert error.eneo_error_code == ErrorCodes.BAD_REQUEST
    assert error.code == FlowApiErrorCode.EVIDENCE_EXPORT_REASON_REQUIRED.value
    assert error.context == {
        "detail": "raw",
        "default_reason": "support_debug",
    }
    assert error.request_id == "raw-evidence-reason-required-test"


def test_flow_evidence_audit_failure_error_response_includes_request_id():
    response = _flow_error_response(
        AuditLoggingUnavailableException(
            "Evidence audit logging is unavailable.",
            code=FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED.value,
            context={"audit_required": True},
        ),
        request_id="evidence-audit-failure-test",
    )

    assert response["status_code"] == 503
    payload = response["payload"]
    error = GeneralError.model_validate(payload)
    assert error.message == "Evidence audit logging is unavailable."
    assert error.eneo_error_code == ErrorCodes.INTERNAL_SERVER_ERROR
    assert error.code == FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED.value
    assert error.context == {"audit_required": True}
    assert error.request_id == "evidence-audit-failure-test"


def test_flow_evidence_error_response_omits_request_id_when_absent():
    response = _flow_error_response(
        BadRequestException(
            "Raw evidence export requires an explicit non-default reason.",
            code=FlowApiErrorCode.EVIDENCE_EXPORT_REASON_REQUIRED.value,
            context={
                "detail": "raw",
                "default_reason": "support_debug",
            },
        )
    )

    assert response["status_code"] == 400
    payload = response["payload"]
    GeneralError.model_validate(payload)
    assert "request_id" not in payload


@pytest.mark.asyncio
async def test_get_flow_run_evidence_delegates_to_evidence_service(monkeypatch):
    container = MagicMock()
    events: list[str] = []
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    evidence = {
        "run": run.model_dump(mode="json"),
        "definition_integrity": {
            "status": "verified",
            "expected_checksum": "abc",
            "current_checksum": "abc",
        },
        "definition_snapshot": {"steps": []},
        "step_results": [],
        "step_attempts": [],
        "result_files": [],
        "rerun_operations": [],
        "rerun_invalidated_steps": [],
        "review_checkpoints": [],
        "webhook_deliveries": [],
        "debug_export": {
            "schema_version": "eneo.flow.debug-export.v2",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run": {
                "run_id": str(run.id),
                "flow_id": str(run.flow_id),
                "flow_version": run.flow_version,
                "status": run.status.value,
            },
            "definition": {
                "flow_id": str(run.flow_id),
                "version": 1,
                "checksum": "abc",
                "steps_count": 0,
            },
            "definition_snapshot": {"steps": []},
            "steps": [],
            "security": {
                "redaction_applied": True,
                "classification_field": "output_classification_override",
            },
        },
    }
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.get_redacted_evidence_bundle.return_value = SimpleNamespace(
        run=evidence["run"],
        final_output=None,
        result_files=evidence["result_files"],
        to_dict=lambda: evidence,
    )
    container.flow_run_evidence_service.return_value = run_service
    audit_service = AsyncMock()

    def _record_audit(**_kwargs: object) -> object:
        events.append("audit_log")
        return object()

    audit_service.log.side_effect = _record_audit
    container.audit_service.return_value = audit_service
    session = MagicMock()
    session._is_explicit_tx_test_session = True
    session.begin.return_value = _EvidenceTransaction(events)
    container.session.return_value = session
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(
        container,
        user_permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
    )

    response = await get_flow_run_evidence(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.run.id == run.id
    run_service.get_run.assert_awaited_once_with(
        run_id=run.id,
        flow_id=flow_id,
        access_kind="evidence_view",
    )
    run_service.get_redacted_evidence_bundle.assert_awaited_once_with(
        run_id=run.id, run=run
    )
    audit_service.log.assert_awaited_once()
    assert (
        audit_service.log.await_args.kwargs["action"] == ActionType.FLOW_EVIDENCE_VIEWED
    )
    assert events == ["transaction_enter", "audit_log", "transaction_exit"]
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_get_flow_run_evidence_returns_failed_run_retryability(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    secret = "worker-secret-token"
    run = _run(flow_id=flow_id, tenant_id=uuid4()).model_copy(
        update={
            "status": FlowRunStatus.FAILED,
            "error": FlowRunError.from_source(
                FlowRunLifecycleSource.TASK_FAILURE,
                code=FlowApiErrorCode.RUN_WORKER_STALLED,
                message=f"Authorization: Bearer {secret}",
            ),
        }
    )
    redacted_run = cast(dict[str, object], redact_payload(run.model_dump(mode="json")))
    evidence = {
        "run": redacted_run,
        "definition_integrity": {
            "status": "verified",
            "expected_checksum": "abc",
            "current_checksum": "abc",
        },
        "definition_snapshot": {"steps": []},
        "step_results": [],
        "step_attempts": [],
        "result_files": [],
        "rerun_operations": [],
        "rerun_invalidated_steps": [],
        "review_checkpoints": [],
        "webhook_deliveries": [],
        "debug_export": {
            "schema_version": "eneo.flow.debug-export.v2",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run": {
                "run_id": str(run.id),
                "flow_id": str(run.flow_id),
                "flow_version": run.flow_version,
                "status": run.status.value,
            },
            "definition": {
                "flow_id": str(run.flow_id),
                "version": 1,
                "checksum": "abc",
                "steps_count": 0,
            },
            "definition_snapshot": {"steps": []},
            "steps": [],
            "security": {
                "redaction_applied": True,
                "classification_field": "output_classification_override",
            },
        },
    }
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.get_redacted_evidence_bundle.return_value = SimpleNamespace(
        run=redacted_run,
        final_output=None,
        result_files=evidence["result_files"],
        to_dict=lambda: evidence,
    )
    container.flow_run_evidence_service.return_value = run_service
    container.audit_service.return_value = AsyncMock()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(
        container,
        user_permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
    )

    response = await get_flow_run_evidence(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.run.status is FlowRunStatus.FAILED
    assert response.run.error is not None
    assert response.run.error.code is FlowApiErrorCode.RUN_WORKER_STALLED
    assert response.run.error.retryable is False
    assert response.run.error.message == "Authorization: Bearer [REDACTED]"
    assert secret not in response.run.error.message


@pytest.mark.asyncio
async def test_get_flow_run_evidence_projects_redacted_artifact_result_files(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    final_step_id = uuid4()
    artifact_file = _result_file(run=run).model_copy(
        update={
            "step_id": final_step_id,
            "name": "Bearer [REDACTED]",
        }
    )
    artifact_payload = artifact_file.model_dump(mode="json")
    evidence = {
        "run": run.model_dump(mode="json"),
        "definition_integrity": {
            "status": "verified",
            "expected_checksum": "abc",
            "current_checksum": "abc",
        },
        "definition_snapshot": {"steps": []},
        "step_results": [],
        "step_attempts": [],
        "result_files": [artifact_payload],
        "rerun_operations": [],
        "rerun_invalidated_steps": [],
        "review_checkpoints": [],
        "webhook_deliveries": [],
        "debug_export": {
            "schema_version": "eneo.flow.debug-export.v2",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run": {
                "run_id": str(run.id),
                "flow_id": str(run.flow_id),
                "flow_version": run.flow_version,
                "status": run.status.value,
            },
            "definition": {
                "flow_id": str(run.flow_id),
                "version": 1,
                "checksum": "abc",
                "steps_count": 0,
            },
            "definition_snapshot": {"steps": []},
            "steps": [],
            "security": {
                "redaction_applied": True,
                "classification_field": "output_classification_override",
            },
        },
    }
    evidence_service = AsyncMock()
    evidence_service.get_run.return_value = run
    evidence_service.get_redacted_evidence_bundle.return_value = SimpleNamespace(
        run=evidence["run"],
        final_output=FlowFinalOutputContractPublic(
            step_id=final_step_id,
            step_order=1,
            output_type=FlowOutputType.PDF,
            output_mode=FlowOutputMode.RENDER_VERBATIM,
            delivery=FlowOutputDelivery.ARTIFACT,
        ),
        result_files=evidence["result_files"],
        to_dict=lambda: evidence,
    )
    container.flow_run_evidence_service.return_value = evidence_service
    container.audit_service.return_value = AsyncMock()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(
        container,
        user_permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
    )

    response = await get_flow_run_evidence(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.run.result is not None
    assert response.run.result.model_dump(mode="json") == {
        "kind": "artifact",
        "files": [artifact_payload],
    }


@pytest.mark.asyncio
async def test_get_flow_run_evidence_enriches_service_principal_actor_summaries(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    tenant_id = uuid4()
    requester_service_id = uuid4()
    rerun_service_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=tenant_id)
    evidence = {
        "run": run.model_dump(mode="json"),
        "definition_integrity": {
            "status": "verified",
            "expected_checksum": "abc",
            "current_checksum": "abc",
        },
        "definition_snapshot": {"steps": []},
        "step_results": [],
        "step_attempts": [],
        "result_files": [],
        "rerun_operations": [
            {
                "id": str(uuid4()),
                "tenant_id": str(tenant_id),
                "flow_id": str(flow_id),
                "flow_run_id": str(run.id),
                "rerun_step_id": str(uuid4()),
                "rerun_step_order": 1,
                "root_attempt_no": 2,
                "status": "completed",
                "request_fingerprint": "fingerprint",
                "expected_run_revision": 1,
                "accepted_run_revision": 2,
                "reason": "Refresh output",
                "root_step_input_override_requested": False,
                "requested_by_principal_type": "service_key",
                "requested_by_service_id": str(rerun_service_id),
                "created_at": "2026-03-20T12:00:00Z",
                "updated_at": "2026-03-20T12:00:00Z",
            }
        ],
        "rerun_invalidated_steps": [],
        "review_checkpoints": [
            {
                "id": str(uuid4()),
                "tenant_id": str(tenant_id),
                "flow_id": str(flow_id),
                "flow_run_id": str(run.id),
                "step_id": str(uuid4()),
                "step_order": 1,
                "attempt_no": 1,
                "state": "resumed",
                "revision": 4,
                "schema_version": 1,
                "review_mode": "edit",
                "output_type": "json",
                "decision": "approved",
                "resume_key_present": True,
                "requester_principal_type": "service_key",
                "requester_service_id": str(requester_service_id),
                "decided_by_principal_type": None,
                "created_at": "2026-03-20T12:00:00Z",
                "updated_at": "2026-03-20T12:00:00Z",
            }
        ],
        "webhook_deliveries": [],
        "debug_export": {
            "schema_version": "eneo.flow.debug-export.v2",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run": {
                "run_id": str(run.id),
                "flow_id": str(run.flow_id),
                "flow_version": run.flow_version,
                "status": run.status.value,
            },
            "definition": {
                "flow_id": str(run.flow_id),
                "version": 1,
                "checksum": "abc",
                "steps_count": 0,
            },
            "definition_snapshot": {"steps": []},
            "steps": [],
            "security": {
                "redaction_applied": True,
                "classification_field": "output_classification_override",
            },
        },
    }
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.get_redacted_evidence_bundle.return_value = SimpleNamespace(
        run=evidence["run"],
        final_output=None,
        result_files=evidence["result_files"],
        to_dict=lambda: evidence,
    )
    container.flow_run_evidence_service.return_value = run_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
    )
    api_key_repo = AsyncMock()
    api_key_repo.list_service_principals_by_ids.return_value = {
        requester_service_id: SimpleNamespace(
            id=requester_service_id,
            display_name="Requester service",
        ),
        rerun_service_id: SimpleNamespace(
            id=rerun_service_id,
            display_name="Rerun service",
        ),
    }
    container.api_key_v2_repo.return_value = api_key_repo
    container.audit_service.return_value = AsyncMock()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(
        container,
        user_permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
    )

    response = await get_flow_run_evidence(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    checkpoint = response.review_checkpoints[0]
    assert checkpoint.requester_service_principal is not None
    assert checkpoint.requester_service_principal.id == requester_service_id
    assert checkpoint.requester_service_principal.display_name == "Requester service"
    rerun_operation = response.rerun_operations[0]
    assert rerun_operation.requested_by_service_principal is not None
    assert rerun_operation.requested_by_service_principal.id == rerun_service_id
    assert (
        rerun_operation.requested_by_service_principal.display_name == "Rerun service"
    )


@pytest.mark.asyncio
async def test_get_flow_run_evidence_requires_trace_permission(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    container.flow_run_evidence_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container, user_permissions=[Permission.FLOWS_VIEW])

    run_service.get_redacted_evidence_bundle.side_effect = UnauthorizedException(
        "You do not have permission to view flow trace.",
        code="insufficient_tenant_permission",
    )

    with pytest.raises(UnauthorizedException, match="view flow trace"):
        await get_flow_run_evidence(
            id=flow_id,
            run_id=run.id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
        )

    run_service.get_redacted_evidence_bundle.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_flow_run_evidence_allows_space_admin_without_trace_permission(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    evidence = {
        "run": run.model_dump(mode="json"),
        "definition_integrity": {
            "status": "verified",
            "expected_checksum": "abc",
            "current_checksum": "abc",
        },
        "definition_snapshot": {"steps": []},
        "step_results": [],
        "step_attempts": [],
        "result_files": [],
        "rerun_operations": [],
        "rerun_invalidated_steps": [],
        "review_checkpoints": [],
        "webhook_deliveries": [],
        "debug_export": {
            "schema_version": "eneo.flow.debug-export.v2",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run": {
                "run_id": str(run.id),
                "flow_id": str(run.flow_id),
                "flow_version": run.flow_version,
                "status": run.status.value,
            },
            "definition": {
                "flow_id": str(run.flow_id),
                "version": 1,
                "checksum": "abc",
                "steps_count": 0,
            },
            "definition_snapshot": {"steps": []},
            "steps": [],
            "security": {
                "redaction_applied": True,
                "classification_field": "output_classification_override",
            },
        },
    }
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.get_redacted_evidence_bundle.return_value = SimpleNamespace(
        run=evidence["run"],
        final_output=None,
        result_files=evidence["result_files"],
        to_dict=lambda: evidence,
    )
    container.flow_run_evidence_service.return_value = run_service
    container.audit_service.return_value = AsyncMock()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    actor = _enable_space_access(container, user_permissions=[Permission.FLOWS_VIEW])
    actor.get_current_role.return_value = SpaceRole.ADMIN

    response = await get_flow_run_evidence(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.run.id == run.id
    run_service.get_redacted_evidence_bundle.assert_awaited_once()


@pytest.mark.asyncio
async def test_export_flow_run_evidence_returns_json_attachment(monkeypatch):
    container = MagicMock()
    events: list[str] = []
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    caller_user_id = uuid4()
    assert caller_user_id != run.principal_user_id
    export_payload = _evidence_export_payload(run, actor_user_id=caller_user_id)
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.export_evidence_json.return_value = export_payload
    container.flow_run_evidence_service.return_value = run_service
    audit_service = AsyncMock()

    def _record_audit(**_kwargs: object) -> object:
        events.append("audit_log")
        return object()

    audit_service.log.side_effect = _record_audit
    container.audit_service.return_value = audit_service
    session = MagicMock()
    session._is_explicit_tx_test_session = True
    session.begin.return_value = _EvidenceTransaction(events)
    container.session.return_value = session
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(
        container,
        user_permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
    )

    response = await export_flow_run_evidence(
        id=flow_id,
        run_id=run.id,
        format="json",
        detail="redacted",
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.media_type == "application/json"
    assert "attachment;" in response.headers["content-disposition"]
    assert str(run.id) in response.body.decode("utf-8")
    run_service.export_evidence_json.assert_awaited_once_with(
        run_id=run.id,
        detail="redacted",
        run=run,
        export_reason="support_debug",
    )
    audit_service.log.assert_awaited_once()
    assert (
        audit_service.log.await_args.kwargs["action"]
        == ActionType.FLOW_EVIDENCE_EXPORTED_JSON
    )
    assert audit_service.log.await_args.kwargs["metadata"]["extra"] == {
        "evidence_detail": "redacted",
        "export_reason": "support_debug",
    }
    assert events == ["transaction_enter", "audit_log", "transaction_exit"]
    session.commit.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("audit_outcome", ["none", "exception", "commit"])
async def test_get_flow_run_evidence_fails_closed_when_required_audit_is_unavailable(
    monkeypatch, audit_outcome: str
):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    evidence = {
        "run": run.model_dump(mode="json"),
        "definition_integrity": {
            "status": "verified",
            "expected_checksum": "abc",
            "current_checksum": "abc",
        },
        "definition_snapshot": {"steps": []},
        "step_results": [],
        "step_attempts": [],
        "result_files": [],
        "rerun_operations": [],
        "rerun_invalidated_steps": [],
        "review_checkpoints": [],
        "webhook_deliveries": [],
        "debug_export": {
            "schema_version": "eneo.flow.debug-export.v2",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run": {
                "run_id": str(run.id),
                "flow_id": str(run.flow_id),
                "flow_version": run.flow_version,
                "trace_id": str(run.trace_id),
                "status": run.status.value,
            },
            "definition": {
                "flow_id": str(run.flow_id),
                "version": 1,
                "checksum": "abc",
                "steps_count": 0,
            },
            "definition_snapshot": {"steps": []},
            "steps": [],
            "security": {
                "redaction_applied": True,
                "classification_field": "output_classification_override",
            },
        },
    }
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.get_redacted_evidence_bundle.return_value = SimpleNamespace(
        run=evidence["run"],
        final_output=None,
        result_files=evidence["result_files"],
        to_dict=lambda: evidence,
    )
    container.flow_run_evidence_service.return_value = run_service
    audit_service = AsyncMock()
    if audit_outcome == "none":
        audit_service.log.return_value = None
    elif audit_outcome == "exception":
        audit_service.log.side_effect = RuntimeError("audit unavailable")
    else:
        audit_service.log.return_value = object()
    container.audit_service.return_value = audit_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service
    logger = MagicMock()

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    monkeypatch.setattr(flow_trace_audit_module, "logger", logger)
    _enable_space_access(
        container,
        user_permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
    )
    if audit_outcome == "commit":
        session = MagicMock()
        session.begin.return_value = _EvidenceTransaction(
            [], exit_error=RuntimeError("commit unavailable")
        )
        container.session.return_value = session

    with pytest.raises(AuditLoggingUnavailableException) as exc_info:
        await get_flow_run_evidence(
            id=flow_id,
            run_id=run.id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
        )

    error = exc_info.value
    assert str(error) == "Evidence audit logging is unavailable."
    assert error.code == FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED.value
    assert error.context == {"audit_required": True}
    if audit_outcome == "none":
        logger.error.assert_called_once()
        logger.exception.assert_not_called()
    else:
        logger.exception.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("audit_outcome", ["none", "exception", "commit"])
async def test_export_flow_run_evidence_fails_closed_when_required_audit_is_unavailable(
    monkeypatch, audit_outcome: str
):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    export_payload = _evidence_export_payload(run, actor_user_id=uuid4())
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.export_evidence_json.return_value = export_payload
    container.flow_run_evidence_service.return_value = run_service
    audit_service = AsyncMock()
    if audit_outcome == "none":
        audit_service.log.return_value = None
    elif audit_outcome == "exception":
        audit_service.log.side_effect = RuntimeError("audit unavailable")
    else:
        audit_service.log.return_value = object()
    container.audit_service.return_value = audit_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service
    logger = MagicMock()

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    monkeypatch.setattr(flow_trace_audit_module, "logger", logger)
    _enable_space_access(
        container,
        user_permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
    )
    if audit_outcome == "commit":
        session = MagicMock()
        session.begin.return_value = _EvidenceTransaction(
            [], exit_error=RuntimeError("commit unavailable")
        )
        container.session.return_value = session

    with pytest.raises(AuditLoggingUnavailableException) as exc_info:
        await export_flow_run_evidence(
            id=flow_id,
            run_id=run.id,
            format="json",
            detail="redacted",
            reason="support_debug",
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
        )

    error = exc_info.value
    assert str(error) == "Evidence audit logging is unavailable."
    assert error.code == FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED.value
    assert error.context == {"audit_required": True}
    if audit_outcome == "none":
        logger.error.assert_called_once()
        logger.exception.assert_not_called()
    else:
        logger.exception.assert_called_once()


@pytest.mark.asyncio
async def test_export_flow_run_evidence_passes_raw_detail_and_reason(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    export_payload = _evidence_export_payload(run, actor_user_id=uuid4())
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.export_evidence_json.return_value = export_payload
    container.flow_run_evidence_service.return_value = run_service
    container.audit_service.return_value = AsyncMock()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(
        container,
        user_permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
    )

    await export_flow_run_evidence(
        id=flow_id,
        run_id=run.id,
        format="json",
        detail="raw",
        reason="government_audit_request",
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    run_service.get_run.assert_awaited_once_with(
        run_id=run.id,
        flow_id=flow_id,
        access_kind="evidence_export_raw",
    )
    run_service.export_evidence_json.assert_awaited_once_with(
        run_id=run.id,
        detail="raw",
        run=run,
        export_reason="government_audit_request",
    )
    assert container.audit_service.return_value.log.await_args.kwargs["metadata"][
        "extra"
    ] == {
        "evidence_detail": "raw",
        "export_reason": "government_audit_request",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason", ["support_debug", "   "], ids=["default_sentinel", "whitespace_only"]
)
async def test_export_flow_run_evidence_rejects_raw_invalid_reason(
    monkeypatch,
    reason,
):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    container.flow_run_evidence_service.return_value = run_service
    container.audit_service.return_value = AsyncMock()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(
        container,
        user_permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
    )

    with pytest.raises(BadRequestException) as exc_info:
        await export_flow_run_evidence(
            id=flow_id,
            run_id=run.id,
            format="json",
            detail="raw",
            reason=reason,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
        )

    error = exc_info.value
    assert str(error) == "Raw evidence export requires an explicit non-default reason."
    assert error.code == FlowApiErrorCode.EVIDENCE_EXPORT_REASON_REQUIRED.value
    assert error.context == {
        "detail": "raw",
        "default_reason": "support_debug",
    }
    run_service.get_run.assert_not_awaited()
    run_service.export_evidence_json.assert_not_awaited()
    container.audit_service.return_value.log.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_flow_run_steps_projects_typed_diagnostics_and_logs_drops(
    monkeypatch,
    caplog,
):
    caplog.set_level(logging.WARNING, logger="eneo.flows.api.flow_assembler")
    container = MagicMock()
    flow_id = uuid4()
    run_id = uuid4()
    tenant_id = uuid4()
    run_service = AsyncMock()
    step_result = cast(
        FlowStepResult,
        SimpleNamespace(
            id=uuid4(),
            flow_run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            step_id=uuid4(),
            step_order=1,
            assistant_id=uuid4(),
            status="completed",
            input_payload_json={
                "diagnostics": [
                    {
                        "code": "typed_io_transcript_near_limit",
                        "message": "Transcript is near the configured limit.",
                        "severity": "info",
                    },
                    "ignore-me",
                    {"code": "missing_message", "severity": "info"},
                    {
                        "code": "audio_transcribe_only_used",
                        "message": "Audio was transcribed without an assistant call.",
                        "severity": "info",
                        "unexpected_runtime_debug_key": True,
                    },
                ]
            },
            output_payload_json={"text": "ok"},
            num_tokens_input=10,
            num_tokens_output=20,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
    )
    run_service.list_step_results_with_files.return_value = (
        FlowRunStepResultWithFiles(
            step_result=step_result,
            runtime_input_file_ids=(),
            result_files=(),
        ),
    )
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    response = await list_flow_run_steps(
        id=flow_id,
        run_id=run_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert len(response) == 1
    assert [diagnostic.model_dump() for diagnostic in response[0].diagnostics] == [
        {
            "code": "typed_io_transcript_near_limit",
            "message": "Transcript is near the configured limit.",
            "severity": "info",
        },
        {
            "code": "audio_transcribe_only_used",
            "message": "Audio was transcribed without an assistant call.",
            "severity": "info",
        },
    ]
    trimmed_records = [
        record
        for record in caplog.records
        if record.message == "flow_step_diagnostics_projection_trimmed"
    ]
    assert len(trimmed_records) == 1
    assert trimmed_records[0].run_id == str(run_id)
    assert trimmed_records[0].trimmed_count == 1
    assert trimmed_records[0].trimmed_keys == ["unexpected_runtime_debug_key"]
    dropped_records = [
        record
        for record in caplog.records
        if record.message == "flow_step_diagnostics_projection_dropped"
    ]
    assert len(dropped_records) == 1
    assert dropped_records[0].run_id == str(run_id)
    assert dropped_records[0].dropped_count == 2
    assert dropped_records[0].error_types == ["not_mapping", "missing"]


@pytest.mark.asyncio
async def test_list_flow_run_steps_handles_non_list_diagnostics(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run_id = uuid4()
    run_service = AsyncMock()
    step_result_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    result_file = _result_file(run=run, step_result_id=step_result_id)
    first_step_result = cast(
        FlowStepResult,
        SimpleNamespace(
            id=step_result_id,
            flow_run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_id=uuid4(),
            step_order=1,
            assistant_id=uuid4(),
            status="completed",
            input_payload_json={"diagnostics": {"code": "not-a-list"}},
            output_payload_json={"text": "ok"},
            num_tokens_input=10,
            num_tokens_output=20,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
    )
    second_step_result = cast(
        FlowStepResult,
        SimpleNamespace(
            id=uuid4(),
            flow_run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_id=uuid4(),
            step_order=2,
            assistant_id=uuid4(),
            status="completed",
            input_payload_json=None,
            output_payload_json={"text": "ok"},
            num_tokens_input=10,
            num_tokens_output=20,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
    )
    run_service.list_step_results_with_files.return_value = (
        FlowRunStepResultWithFiles(
            step_result=first_step_result,
            runtime_input_file_ids=(),
            result_files=(result_file,),
        ),
        FlowRunStepResultWithFiles(
            step_result=second_step_result,
            runtime_input_file_ids=(),
            result_files=(),
        ),
    )
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    response = await list_flow_run_steps(
        id=flow_id,
        run_id=run_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert len(response) == 2
    assert response[0].diagnostics == []
    assert response[0].result_files == [result_file]
    assert response[1].diagnostics == []
    assert response[1].result_files == []


@pytest.mark.asyncio
async def test_artifact_signed_url_delegates_to_service_and_audits(monkeypatch):
    """Artifact endpoint calls service.get_run_artifact_file, generates signed URL, and audits."""
    container = MagicMock()
    flow_id = uuid4()
    run_id = uuid4()
    file_id = uuid4()
    user = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), username="tester", email="t@e.com"
    )
    container.user.return_value = user
    file_tenant_id = uuid4()

    file_obj = SimpleNamespace(
        id=file_id,
        name="report.docx",
        tenant_id=file_tenant_id,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size=2048,
    )
    run_service = AsyncMock()
    run_service.get_run_artifact_file.return_value = file_obj
    container.flow_run_evidence_service.return_value = run_service
    container.flow_service.return_value = AsyncMock()
    audit_service = AsyncMock()
    container.audit_service.return_value = audit_service

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    from eneo.files.file_models import SignedURLRequest

    signed_req = SignedURLRequest(expires_in=300)

    response = await generate_flow_run_artifact_signed_url(
        id=flow_id,
        run_id=run_id,
        file_id=file_id,
        request=SimpleNamespace(
            state=SimpleNamespace(), base_url="https://app.example.com/"
        ),
        signed_url_req=signed_req,
        container=container,
    )

    run_service.get_run_artifact_file.assert_awaited_once_with(
        run_id=run_id,
        flow_id=flow_id,
        file_id=file_id,
    )
    assert response.url.startswith("https://app.example.com/api/v1/files/")
    assert str(file_id) in response.url
    assert response.expires_at > 0
    token = response.url.split("token=", 1)[1]
    payload = verify_signed_token(token)
    assert payload is not None
    assert payload["tenant_id"] == str(file_tenant_id)

    audit_service.log_async.assert_awaited_once()
    call_kwargs = audit_service.log_async.call_args[1]
    assert call_kwargs["action"] == ActionType.FLOW_RUN_ARTIFACT_DOWNLOADED
    assert call_kwargs["entity_id"] == file_id
    assert call_kwargs["metadata"]["extra"]["flow_id"] == str(flow_id)
    assert call_kwargs["metadata"]["extra"]["run_id"] == str(run_id)
