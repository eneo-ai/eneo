from __future__ import annotations

import json
import logging
from datetime import (
    datetime,
    timezone,
)
from types import SimpleNamespace
from typing import cast
from unittest.mock import (
    AsyncMock,
    MagicMock,
)
from uuid import uuid4

import pytest

import intric.flows.api.flow_trace_audit as flow_trace_audit_module
from intric.actors.actors.space_actor import SpaceRole
from intric.audit.domain.action_types import ActionType
from intric.authentication.auth_dependencies import ScopeFilter
from intric.authentication.signed_urls import verify_signed_token
from intric.flows.api import flow_access_context as flow_access_context_module
from intric.flows.api.flow_run_evidence_router import (
    export_flow_run_evidence,
    get_flow_run_evidence,
)
from intric.flows.api.flow_run_steps_router import (
    generate_flow_run_artifact_signed_url,
    list_flow_run_steps,
)
from intric.flows.application.flow_run_service import FlowRunStepResultWithFiles
from intric.flows.domain.flow import FlowStepResult
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.main.exceptions import (
    ErrorCodes,
    UnauthorizedException,
)
from intric.roles.permissions import Permission
from tests.unittests.flows.test_flow_router import (
    _enable_space_access,
    _evidence_export_payload,
    _flow,
    _result_file,
    _run,
)


@pytest.mark.asyncio
async def test_get_flow_run_evidence_delegates_to_evidence_service(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    evidence = {
        "run": run.model_dump(mode="json"),
        "definition_snapshot": {"steps": []},
        "step_results": [],
        "step_attempts": [],
        "result_files": [],
        "rerun_operations": [],
        "rerun_invalidated_steps": [],
        "review_checkpoints": [],
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
                "mcp_policy_field": "mcp_policy",
            },
        },
    }
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.get_redacted_evidence_bundle.return_value = SimpleNamespace(
        to_dict=lambda: evidence
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

    assert response.run.id == run.id
    run_service.get_run.assert_awaited_once_with(
        run_id=run.id,
        flow_id=flow_id,
        access_kind="evidence_view",
    )
    run_service.get_redacted_evidence_bundle.assert_awaited_once_with(
        run_id=run.id, run=run
    )
    container.audit_service.return_value.log_async.assert_awaited_once()
    assert (
        container.audit_service.return_value.log_async.await_args.kwargs["action"]
        == ActionType.FLOW_EVIDENCE_VIEWED
    )


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
                "mcp_policy_field": "mcp_policy",
            },
        },
    }
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.get_redacted_evidence_bundle.return_value = SimpleNamespace(
        to_dict=lambda: evidence
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
        "definition_snapshot": {"steps": []},
        "step_results": [],
        "step_attempts": [],
        "result_files": [],
        "rerun_operations": [],
        "rerun_invalidated_steps": [],
        "review_checkpoints": [],
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
                "mcp_policy_field": "mcp_policy",
            },
        },
    }
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.get_redacted_evidence_bundle.return_value = SimpleNamespace(
        to_dict=lambda: evidence
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
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    export_payload = _evidence_export_payload(run)
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
    container.audit_service.return_value.log_async.assert_awaited_once()
    assert (
        container.audit_service.return_value.log_async.await_args.kwargs["action"]
        == ActionType.FLOW_EVIDENCE_EXPORTED_JSON
    )
    assert container.audit_service.return_value.log_async.await_args.kwargs["metadata"][
        "extra"
    ] == {
        "evidence_detail": "redacted",
        "export_reason": "support_debug",
    }


@pytest.mark.asyncio
async def test_get_flow_run_evidence_fails_closed_when_audit_write_fails(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    evidence = {
        "run": run.model_dump(mode="json"),
        "definition_snapshot": {"steps": []},
        "step_results": [],
        "step_attempts": [],
        "result_files": [],
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
                "mcp_policy_field": "mcp_policy",
            },
        },
    }
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.get_redacted_evidence_bundle.return_value = SimpleNamespace(
        to_dict=lambda: evidence
    )
    container.flow_run_evidence_service.return_value = run_service
    audit_service = AsyncMock()
    audit_service.log_async.side_effect = RuntimeError("audit unavailable")
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

    response = await get_flow_run_evidence(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.status_code == 503
    assert json.loads(response.body.decode("utf-8")) == {
        "message": "Evidence audit logging is unavailable.",
        "intric_error_code": int(ErrorCodes.INTERNAL_SERVER_ERROR),
        "code": "flow_evidence_audit_logging_failed",
        "context": {"audit_required": True},
    }
    logger.exception.assert_called_once()


@pytest.mark.asyncio
async def test_export_flow_run_evidence_fails_closed_when_audit_write_fails(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    export_payload = _evidence_export_payload(run)
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.export_evidence_json.return_value = export_payload
    container.flow_run_evidence_service.return_value = run_service
    audit_service = AsyncMock()
    audit_service.log_async.side_effect = RuntimeError("audit unavailable")
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

    response = await export_flow_run_evidence(
        id=flow_id,
        run_id=run.id,
        format="json",
        detail="redacted",
        reason="support_debug",
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.status_code == 503
    assert json.loads(response.body.decode("utf-8")) == {
        "message": "Evidence audit logging is unavailable.",
        "intric_error_code": int(ErrorCodes.INTERNAL_SERVER_ERROR),
        "code": "flow_evidence_audit_logging_failed",
        "context": {"audit_required": True},
    }
    logger.exception.assert_called_once()


@pytest.mark.asyncio
async def test_export_flow_run_evidence_passes_raw_detail_and_reason(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    export_payload = _evidence_export_payload(run)
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
    assert container.audit_service.return_value.log_async.await_args.kwargs["metadata"][
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

    response = await export_flow_run_evidence(
        id=flow_id,
        run_id=run.id,
        format="json",
        detail="raw",
        reason=reason,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.status_code == 400
    assert json.loads(response.body.decode("utf-8")) == {
        "message": "Raw evidence export requires an explicit non-default reason.",
        "intric_error_code": int(ErrorCodes.BAD_REQUEST),
        "code": FlowApiErrorCode.EVIDENCE_EXPORT_REASON_REQUIRED.value,
        "context": {
            "detail": "raw",
            "default_reason": "support_debug",
        },
    }
    run_service.get_run.assert_not_awaited()
    run_service.export_evidence_json.assert_not_awaited()
    container.audit_service.return_value.log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_flow_run_steps_projects_typed_diagnostics_and_logs_drops(
    monkeypatch,
    caplog,
):
    caplog.set_level(logging.WARNING, logger="intric.flows.api.flow_assembler")
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

    from intric.files.file_models import SignedURLRequest

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
