"""The shared role-permission guard answers in the documented error envelope.

Operations behind `require_permission` declare `GeneralError` for their 403, so
the denial has to carry the string code and the numeric category. These cases go
through the application handler rather than the guard's return value, because a
guard-level assertion cannot see what the handler puts on the wire.
"""

from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from eneo.authentication.auth_dependencies import (
    get_current_active_user,
    require_permission,
)
from eneo.main.exceptions import ErrorCodes
from eneo.main.models import GeneralError
from eneo.roles.permissions import Permission
from eneo.server.main import get_application

ENDPOINT_LEVEL = "/_test-permission-endpoint"
ROUTER_LEVEL = "/_test-permission-router"


def _client(*, permissions: set[Permission]) -> tuple[TestClient, list[str]]:
    """An app carrying the guard both ways routers apply it, endpoint and router."""
    reached: list[str] = []
    app = get_application()

    @app.get(
        ENDPOINT_LEVEL, dependencies=[Depends(require_permission(Permission.ADMIN))]
    )
    async def _endpoint_level():
        reached.append(ENDPOINT_LEVEL)
        return {"ok": True}

    router = APIRouter(dependencies=[Depends(require_permission(Permission.ADMIN))])

    @router.get(ROUTER_LEVEL)
    async def _router_level():
        reached.append(ROUTER_LEVEL)
        return {"ok": True}

    app.include_router(router)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(
        permissions=permissions
    )
    return TestClient(app), reached


@pytest.mark.parametrize("path", [ENDPOINT_LEVEL, ROUTER_LEVEL])
def test_denial_answers_the_envelope_and_stops_the_endpoint(path):
    client, reached = _client(permissions=set())

    response = client.get(path, headers={"X-Correlation-ID": "denial-1"})

    assert response.status_code == 403
    error = GeneralError.model_validate(response.json())
    assert error.code == "insufficient_permission"
    assert error.eneo_error_code == ErrorCodes.UNAUTHORIZED
    assert error.message == "Need permission admin in order to access"
    assert error.request_id == "denial-1"
    assert reached == []


@pytest.mark.parametrize("path", [ENDPOINT_LEVEL, ROUTER_LEVEL])
def test_a_permitted_user_reaches_the_endpoint(path):
    client, reached = _client(permissions={Permission.ADMIN})

    response = client.get(path)

    assert response.status_code == 200
    assert reached == [path]
