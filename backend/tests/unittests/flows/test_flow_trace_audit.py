"""The trace audit reads only a run's identity, so the content-free status
projection a route authorizes with writes the audit the full run would."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import eneo.flows.application.flow_trace_audit as flow_trace_audit_module
from eneo.audit.domain.action_types import ActionType
from eneo.authentication.principal_types import PrincipalType
from eneo.flows.application.flow_trace_audit import (
    log_flow_trace_audit_or_raise,
    raise_flow_trace_audit_unavailable,
)
from eneo.flows.domain.flow import FlowRun, FlowRunStatus, FlowRunStatusSnapshot
from eneo.main.exceptions import AuditLoggingUnavailableException


def _runs() -> tuple[FlowRunStatusSnapshot, FlowRun]:
    now = datetime.now(timezone.utc)
    snapshot = FlowRunStatusSnapshot(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        run_label="Kommunstyrelsen",
        created_at=now,
        updated_at=now,
    )
    full = FlowRun(
        **snapshot.model_dump(),
        input_payload_json={"text": "Protected transcript"},
        output_payload_json={"text": "Protected transcript"},
    )
    return snapshot, full


def _user(tenant_id) -> Any:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        username="granskare",
        email="granskare@example.com",
        active_api_key=None,
    )


async def test_status_projection_writes_the_audit_of_the_full_run() -> None:
    snapshot, full = _runs()
    user = _user(snapshot.tenant_id)
    logged: list[dict[str, Any]] = []
    for run in (full, snapshot):
        audit_service = AsyncMock()
        container = MagicMock()
        container.audit_service.return_value = audit_service
        await log_flow_trace_audit_or_raise(
            container=container,
            user=user,
            run=run,
            action=ActionType.FLOW_EVIDENCE_VIEWED,
            description=f"Viewed transcript source for flow run {run.id}",
            extra={"evidence_detail": "transcript_source", "attempt_no": 1},
        )
        logged.append(audit_service.log.await_args.kwargs)

    assert logged[0] == logged[1]
    assert logged[1]["entity_id"] == snapshot.id
    assert logged[1]["metadata"]["target"] == {"id": str(snapshot.id), "name": None}
    assert logged[1]["metadata"]["extra"] == {
        "evidence_detail": "transcript_source",
        "attempt_no": 1,
        "flow_id": str(snapshot.flow_id),
        "run_id": str(snapshot.id),
    }


def test_status_projection_reports_an_unavailable_audit_like_the_full_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, full = _runs()
    user = _user(snapshot.tenant_id)
    reported: list[object] = []
    for run in (full, snapshot):
        logger = MagicMock()
        monkeypatch.setattr(flow_trace_audit_module, "logger", logger)
        with pytest.raises(AuditLoggingUnavailableException) as exc_info:
            raise_flow_trace_audit_unavailable(
                user=user,
                run=run,
                action=ActionType.FLOW_EVIDENCE_VIEWED,
                cause=RuntimeError("audit down"),
            )
        reported.append(
            (logger.exception.call_args, exc_info.value.code, exc_info.value.context)
        )

    assert reported[0] == reported[1]
