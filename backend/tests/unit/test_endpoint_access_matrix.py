"""Exercise the shipped HTTP dependency graphs, before any business handler.

Credential lookup, storage configuration refresh and the database are substituted.
UserService's actual authentication and admission checks run. A tripwire replaces
final handler dispatch, preventing business handlers from running if admission regresses.
"""

import re
from dataclasses import dataclass
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from eneo.authentication.auth_models import ApiKeyPermission, ApiKeyV2InDB
from eneo.authentication.endpoint_access import (
    Authentication,
    EndpointAccess,
    access_for,
)
from eneo.database.database import (
    AsyncSession,
    get_session,
    get_session_with_transaction,
)
from eneo.object_content.runtime import object_content_runtime
from eneo.roles.permissions import Permission
from eneo.security_classifications.presentation.security_classification_router import (
    toggle_security_classifications,
)
from eneo.server.endpoint_routes import (
    EndpointRoute,
    endpoint_routes,
    validate_endpoint_access,
)
from eneo.server.exception_handlers import add_exception_handlers
from eneo.server.main import app as production_app
from eneo.tenants.presentation.tenant_self_credentials_router import (
    check_feature_enabled,
)
from eneo.users.user import UserInDB
from eneo.users.user_service import UserService
from tests.unit.api_key_test_utils import make_api_key
from tests.unit.test_endpoint_access import make_user


@dataclass(frozen=True)
class ProtectedOperation:
    route: EndpointRoute
    method: str
    policy: EndpointAccess

    @property
    def identity(self) -> str:
        return f"{self.method} {self.route.path}"


def protected_operations() -> list[ProtectedOperation]:
    result = []
    for route in endpoint_routes(production_app.routes):
        policy = access_for(route.endpoint)
        assert policy is not None
        if not isinstance(
            route.context.original_route, APIRoute
        ) or policy.authentication not in {
            Authentication.USER,
            Authentication.SESSION,
            Authentication.ASSISTANT,
            Authentication.API_KEY,
        }:
            continue
        for method in sorted(route.context.methods or set()):
            result.append(ProtectedOperation(route, method, policy))
    return result


OPERATIONS = protected_operations()


def request_operation(
    monkeypatch: pytest.MonkeyPatch,
    operation: ProtectedOperation,
    *,
    user: UserInDB | None,
    use_key: bool = False,
    expect_admission: bool = False,
    body: dict[str, object] | None = None,
):
    async def token_user(_self: UserService, token: str) -> UserInDB:
        assert user is not None
        return user

    async def key_user(
        _self: UserService, secret: str, *, request: Request | None = None
    ) -> tuple[UserInDB, ApiKeyV2InDB]:
        assert user is not None and request is not None
        key = make_api_key(default_permission=ApiKeyPermission.ADMIN)
        user.active_api_key = key
        request.state.api_key = key
        return user, key

    async def session() -> AsyncSession:
        database = AsyncMock(spec=AsyncSession)
        database.in_transaction.return_value = True
        return database

    monkeypatch.setattr(UserService, "_get_user_from_token", token_user)
    monkeypatch.setattr(UserService, "_resolve_api_key", key_user)
    monkeypatch.setattr(
        object_content_runtime,
        "refresh_object_store_configuration",
        AsyncMock(return_value=None),
    )
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    add_exception_handlers(app)
    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_session_with_transaction] = session
    # Test this optional feature in its enabled state; disabling a feature is
    # an independent 404 gate, not proof that authorization works.
    app.dependency_overrides[check_feature_enabled] = lambda: None

    source = operation.route.context
    endpoint = source.endpoint
    assert endpoint is not None
    route = APIRoute(
        operation.route.path,
        endpoint,
        methods=[operation.method],
        dependencies=source.dependencies,
        response_model=None,
        dependency_overrides_provider=app,
    )

    async def dispatch(**_arguments: object) -> str:
        if not expect_admission:
            pytest.fail(f"Unauthorized request reached {operation.identity}")
        return "admitted"

    # Keep the real endpoint and its already-built dependency graph. Replace
    # only final dispatch, after dependency solving, to safely observe denial.
    route.dependant.call = dispatch
    app.router.routes.append(route)
    validate_endpoint_access(app)
    path = re.sub(r"\{[^}]+\}", str(uuid4()), operation.route.path)
    headers = {}
    if user is not None:
        headers = (
            {"X-API-Key": "test-key"}
            if use_key
            else {"Authorization": "Bearer test-token"}
        )
    return TestClient(app).request(
        operation.method, path, headers=headers, json=body if body is not None else {}
    )


@pytest.mark.parametrize("operation", OPERATIONS, ids=lambda case: case.identity)
def test_every_user_endpoint_rejects_anonymous_callers(monkeypatch, operation):
    response = request_operation(monkeypatch, operation, user=None)
    assert response.status_code == 401, (operation.identity, response.text)


@pytest.mark.parametrize(
    "operation",
    [case for case in OPERATIONS if isinstance(case.policy.authorization, Permission)],
    ids=lambda case: case.identity,
)
@pytest.mark.parametrize("use_key", [False, True], ids=["session", "api-key"])
def test_every_permission_endpoint_rejects_a_user_missing_its_permission(
    monkeypatch, operation, use_key
):
    # Possessing all OTHER permissions must not satisfy this one.
    user = make_user(
        *(
            permission
            for permission in Permission
            if permission != operation.policy.authorization
        )
    )
    response = request_operation(monkeypatch, operation, user=user, use_key=use_key)
    assert response.status_code == 403, (operation.identity, response.text)


@pytest.mark.parametrize(
    "operation",
    [
        case
        for case in OPERATIONS
        if case.policy.authentication is Authentication.SESSION
    ],
    ids=lambda case: case.identity,
)
def test_every_session_endpoint_rejects_even_an_administrative_api_key(
    monkeypatch, operation
):
    response = request_operation(
        monkeypatch, operation, user=make_user(*Permission), use_key=True
    )
    assert response.status_code == 403, (operation.identity, response.text)
    assert "session_auth_required" in response.text


@pytest.mark.parametrize("use_key", [False, True], ids=["session", "api-key"])
@pytest.mark.parametrize(
    "permission,expected", [(Permission.ADMIN, 200), (Permission.STORAGE, 403)]
)
def test_storage_settings_read_preserves_admin_access(
    monkeypatch, use_key, permission, expected
):
    from eneo.object_content.deployment_policy_router import get_deployment_policy

    operation = next(
        case for case in OPERATIONS if case.route.endpoint is get_deployment_policy
    )
    response = request_operation(
        monkeypatch,
        operation,
        user=make_user(permission),
        use_key=use_key,
        expect_admission=expected == 200,
    )
    assert response.status_code == expected, response.text
    if expected == 200:
        assert response.json() == "admitted"


@pytest.mark.parametrize("use_key", [False, True], ids=["session", "api-key"])
@pytest.mark.parametrize(
    "permission,expected", [(Permission.ADMIN, 200), (Permission.INSIGHTS, 403)]
)
def test_toggling_security_classifications_requires_admin_before_dispatch(
    monkeypatch, use_key, permission, expected
):
    operation = next(
        case
        for case in OPERATIONS
        if case.route.endpoint is toggle_security_classifications
    )
    response = request_operation(
        monkeypatch,
        operation,
        user=make_user(permission),
        use_key=use_key,
        expect_admission=expected == 200,
        body={"enabled": True},
    )
    assert response.status_code == expected, response.text
    if expected == 200:
        assert response.json() == "admitted"
