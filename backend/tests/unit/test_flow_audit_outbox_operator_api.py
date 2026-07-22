import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

from eneo.flows.api.flow_run_audit_outbox_operator_router import (
    FlowRunAuditOutboxRedriveRequest,
    list_flow_run_audit_outbox_dead_letters,
    redrive_flow_run_audit_outbox_delivery,
    router,
)
from eneo.flows.application.flow_run_audit_outbox_delivery import (
    FlowRunAuditOutboxGenerationConflictError,
    FlowRunAuditOutboxNotFoundError,
    FlowRunAuditOutboxRedriveResult,
    FlowRunAuditOutboxStateConflictError,
)
from eneo.flows.infrastructure.flow_run_audit_outbox_repo import (
    FlowRunAuditOutboxDeadLetterPage,
    FlowRunAuditOutboxDeadLetterRow,
)
from eneo.main.exceptions import ConflictException, NotFoundException
from eneo.server.exception_handlers import add_exception_handlers

REPO_ROOT = Path(__file__).resolve().parents[3]
FLOW_RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "flows.md"


def _container(service: AsyncMock):
    return SimpleNamespace(flow_run_audit_outbox_delivery_service=lambda: service)


def test_flow_audit_outbox_redrive_reason_is_trimmed_and_bounded() -> None:
    dead_lettered_at = datetime.now(timezone.utc)
    request = FlowRunAuditOutboxRedriveRequest(
        expected_dead_lettered_at=dead_lettered_at,
        reason="  Audit storage recovered.  ",
    )

    assert request.reason == "Audit storage recovered."
    assert request.expected_dead_lettered_at == dead_lettered_at

    for invalid_reason in ("", "   ", "x" * 501):
        with pytest.raises(ValidationError):
            FlowRunAuditOutboxRedriveRequest(
                expected_dead_lettered_at=dead_lettered_at,
                reason=invalid_reason,
            )

    with pytest.raises(ValidationError):
        FlowRunAuditOutboxRedriveRequest(
            expected_dead_lettered_at=datetime.now(),
            reason="Investigated.",
        )


def test_flow_audit_outbox_operator_openapi_exposes_redrive_generation_contract() -> (
    None
):
    app = FastAPI()
    app.include_router(router, prefix="/sysadmin")
    schema = app.openapi()
    request_schema = schema["components"]["schemas"]["FlowRunAuditOutboxRedriveRequest"]

    assert request_schema["required"] == ["expected_dead_lettered_at", "reason"]
    assert request_schema["properties"]["expected_dead_lettered_at"]["format"] == (
        "date-time"
    )
    assert request_schema["properties"]["reason"]["minLength"] == 1
    assert request_schema["properties"]["reason"]["maxLength"] == 500
    assert all(
        property_schema.get("description")
        for property_schema in request_schema["properties"].values()
    )
    for schema_name in (
        "FlowRunAuditOutboxDeadLetterResponse",
        "FlowRunAuditOutboxRedriveResponse",
    ):
        assert all(
            property_schema.get("description")
            for property_schema in schema["components"]["schemas"][schema_name][
                "properties"
            ].values()
        )
    assert (
        schema["paths"]["/sysadmin/flows/audit-outbox/dead-letters/"]["get"][
            "operationId"
        ]
        == "list_flow_run_audit_outbox_dead_letters"
    )
    assert (
        schema["paths"]["/sysadmin/flows/audit-outbox/{outbox_id}/redrive/"]["post"][
            "operationId"
        ]
        == "redrive_flow_run_audit_outbox_delivery"
    )


def test_flow_audit_outbox_runbook_shell_variables_are_declared() -> None:
    runbook = FLOW_RUNBOOK.read_text(encoding="utf-8")
    declared = set(re.findall(r"^export ([A-Z][A-Z0-9_]*)=", runbook, re.MULTILINE))
    referenced = set(re.findall(r"\$\{([^}]+)\}", runbook))

    assert referenced
    assert referenced <= declared


@pytest.mark.asyncio
async def test_flow_audit_outbox_dead_letter_list_returns_bounded_page() -> None:
    outbox_id = uuid4()
    tenant_id = uuid4()
    flow_id = uuid4()
    run_id = uuid4()
    dead_lettered_at = datetime.now(timezone.utc)
    service = AsyncMock()
    service.list_dead_letters.return_value = FlowRunAuditOutboxDeadLetterPage(
        items=(
            FlowRunAuditOutboxDeadLetterRow(
                outbox_id=outbox_id,
                tenant_id=tenant_id,
                flow_id=flow_id,
                flow_run_id=run_id,
                action="flow_run_failed",
                source="task_failure",
                delivery_attempts=5,
                dead_lettered_at=dead_lettered_at,
                delivery_last_error="audit store unavailable",
                created_at=dead_lettered_at,
            ),
        ),
        has_more=True,
    )

    response = await list_flow_run_audit_outbox_dead_letters(
        limit=25,
        offset=50,
        container=_container(service),
    )

    assert response.has_more is True
    assert response.count == 1
    assert response.items[0].model_dump() == {
        "outbox_id": outbox_id,
        "tenant_id": tenant_id,
        "flow_id": flow_id,
        "flow_run_id": run_id,
        "action": "flow_run_failed",
        "source": "task_failure",
        "delivery_attempts": 5,
        "dead_lettered_at": dead_lettered_at,
        "delivery_last_error": "audit store unavailable",
        "created_at": dead_lettered_at,
    }
    service.list_dead_letters.assert_awaited_once_with(limit=25, offset=50)


@pytest.mark.asyncio
async def test_flow_audit_outbox_redrive_endpoint_returns_typed_transition() -> None:
    outbox_id = uuid4()
    run_id = uuid4()
    audit_id = uuid4()
    now = datetime.now(timezone.utc)
    service = AsyncMock()
    service.redrive_dead_lettered.return_value = FlowRunAuditOutboxRedriveResult(
        outbox_id=outbox_id,
        flow_run_id=run_id,
        delivery_status="pending",
        delivery_attempts=0,
        next_delivery_at=now,
        operator_audit_id=audit_id,
    )

    response = await redrive_flow_run_audit_outbox_delivery(
        outbox_id=outbox_id,
        request=FlowRunAuditOutboxRedriveRequest(
            expected_dead_lettered_at=now,
            reason="  Storage recovered.  ",
        ),
        container=_container(service),
    )

    assert response.model_dump() == {
        "outbox_id": outbox_id,
        "flow_run_id": run_id,
        "delivery_status": "pending",
        "delivery_attempts": 0,
        "next_delivery_at": now,
        "operator_audit_id": audit_id,
    }
    service.redrive_dead_lettered.assert_awaited_once()
    assert service.redrive_dead_lettered.await_args.kwargs["outbox_id"] == outbox_id
    assert (
        service.redrive_dead_lettered.await_args.kwargs["reason"]
        == "Storage recovered."
    )
    assert (
        service.redrive_dead_lettered.await_args.kwargs["expected_dead_lettered_at"]
        == now
    )


@pytest.mark.parametrize(
    ("error", "expected_exception", "expected_code"),
    [
        (
            FlowRunAuditOutboxNotFoundError("missing"),
            NotFoundException,
            "flow_audit_outbox_delivery_not_found",
        ),
        (
            FlowRunAuditOutboxStateConflictError(delivery_status="pending"),
            ConflictException,
            "flow_audit_outbox_redrive_conflict",
        ),
        (
            FlowRunAuditOutboxGenerationConflictError(
                current_dead_lettered_at=datetime.now(timezone.utc)
            ),
            ConflictException,
            "flow_audit_outbox_redrive_conflict",
        ),
    ],
)
@pytest.mark.asyncio
async def test_flow_audit_outbox_redrive_endpoint_translates_application_errors(
    error: Exception,
    expected_exception: type[Exception],
    expected_code: str,
) -> None:
    service = AsyncMock()
    service.redrive_dead_lettered.side_effect = error
    outbox_id = uuid4()

    with pytest.raises(expected_exception) as exc_info:
        await redrive_flow_run_audit_outbox_delivery(
            outbox_id=outbox_id,
            request=FlowRunAuditOutboxRedriveRequest(
                expected_dead_lettered_at=datetime.now(timezone.utc),
                reason="Investigated.",
            ),
            container=_container(service),
        )

    assert getattr(exc_info.value, "code") == expected_code
    assert getattr(exc_info.value, "context") == {"outbox_id": str(outbox_id)}


def test_flow_audit_outbox_redrive_errors_match_declared_general_error_shape() -> None:
    service = AsyncMock()
    service.redrive_dead_lettered.side_effect = FlowRunAuditOutboxNotFoundError(
        "missing"
    )
    app = FastAPI()
    add_exception_handlers(app)
    app.include_router(router, prefix="/sysadmin")
    redrive_route = next(
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == "/sysadmin/flows/audit-outbox/{outbox_id}/redrive/"
    )
    container_dependency = next(
        dependency
        for dependency in redrive_route.dependant.dependencies
        if dependency.name == "container"
    )
    assert container_dependency.call is not None
    app.dependency_overrides[container_dependency.call] = lambda: _container(service)

    response = TestClient(app).post(
        f"/sysadmin/flows/audit-outbox/{uuid4()}/redrive/",
        json={
            "expected_dead_lettered_at": datetime.now(timezone.utc).isoformat(),
            "reason": "Investigated.",
        },
    )

    assert response.status_code == 404
    assert response.json()["code"] == "flow_audit_outbox_delivery_not_found"
    assert "message" in response.json()
    assert "eneo_error_code" in response.json()
    assert "detail" not in response.json()
