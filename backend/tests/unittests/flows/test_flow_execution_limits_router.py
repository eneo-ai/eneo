"""`GET /flows/execution-limits/`: the step timeout limits a flow author needs."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from eneo.authentication.access_denial_code import AccessDenialCode
from eneo.flows.api.flow_router import router as flows_router
from eneo.flows.flow_runtime_policy import (
    apply_flow_runtime_policy_patch,
    flow_runtime_step_timeout_hard_ceiling_seconds,
)
from eneo.roles.permissions import Permission
from eneo.server.exception_handlers import add_exception_handlers
from eneo.settings.setting_service import SettingService
from tests.unit.api_key_test_utils import flatten_routes

_LIMITS = "/execution-limits/"


def _client(*, permissions: list[Permission], tenant: Any) -> TestClient:
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), permissions=permissions)
    # The run resolves a step's timeout through this service; the route must too.
    settings_service = SettingService(
        repo=MagicMock(),
        user=user,
        ai_models_service=MagicMock(),
        feature_flag_service=MagicMock(),
        tenant_repo=SimpleNamespace(tenant=tenant),
        audit_service=MagicMock(),
        data_retention_service=MagicMock(),
        skill_repo=MagicMock(),
    )
    container = MagicMock()
    container.user.return_value = user
    container.settings_service.return_value = settings_service
    app = FastAPI()
    # The whole flows router, so the literal path is not captured by `/{id}/`.
    app.include_router(flows_router)
    add_exception_handlers(app)
    for route in flatten_routes(list(app.routes)):
        if not isinstance(route.route, APIRoute):
            continue
        for dependency in route.dependant.dependencies:
            app.dependency_overrides[dependency.call] = lambda: container
    return TestClient(app, raise_server_exceptions=False)


def test_flow_editor_reads_the_effective_step_timeout_limits_router() -> None:
    tenant = SimpleNamespace(flow_settings=None)
    client = _client(permissions=[Permission.FLOWS_MANAGE], tenant=tenant)
    ceiling = flow_runtime_step_timeout_hard_ceiling_seconds()

    inherited = client.get(_LIMITS)

    assert inherited.status_code == 200, inherited.text
    assert inherited.json() == {
        "default_step_timeout_seconds": ceiling,
        "max_step_timeout_seconds": ceiling,
    }

    tenant.flow_settings = apply_flow_runtime_policy_patch(
        None,
        default_step_timeout_seconds=(ceiling - 1) // 2,
        max_step_timeout_seconds=ceiling - 1,
    )
    changed = client.get(_LIMITS)

    assert changed.status_code == 200, changed.text
    assert changed.json() == {
        "default_step_timeout_seconds": (ceiling - 1) // 2,
        "max_step_timeout_seconds": ceiling - 1,
    }


def test_flow_execution_limits_refuse_a_caller_who_cannot_author_flows_router() -> None:
    client = _client(
        permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_RUN],
        tenant=SimpleNamespace(flow_settings=None),
    )

    refused = client.get(_LIMITS)

    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == AccessDenialCode.INSUFFICIENT_TENANT_PERMISSION
