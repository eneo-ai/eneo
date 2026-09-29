"""Endpoint admission contracts, exercised without a database or a server."""

from typing import Annotated
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    EndpointAccess,
    access_for,
    authenticates,
    authorize_user,
    endpoint_access,
    require_endpoint_access,
)
from eneo.main.exceptions import UnauthorizedException
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleInDB
from eneo.server.endpoint_routes import (
    declare_framework_documentation_access,
    endpoint_routes,
    validate_endpoint_access,
)
from eneo.server.exception_handlers import add_exception_handlers
from eneo.server.middleware.cors import CORSMiddleware
from eneo.tenants.tenant import TenantInDB
from eneo.users.user import UserInDB, UserState
from eneo.users.user_service import UserService
from tests.unit.api_key_test_utils import make_api_key


def make_user(*permissions: Permission) -> UserInDB:
    tenant_id = uuid4()
    return UserInDB(
        id=uuid4(),
        tenant_id=tenant_id,
        username="endpoint-test",
        email="endpoint-test@example.com",
        state=UserState.ACTIVE,
        tenant=TenantInDB(id=tenant_id, name="Endpoint tests", quota_limit=0),
        roles=[
            RoleInDB(
                id=uuid4(),
                tenant_id=tenant_id,
                name="Test",
                permissions=list(permissions),
            )
        ],
    )


def application() -> FastAPI:
    app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        dependencies=[Depends(require_endpoint_access)],
    )

    @app.exception_handler(UnauthorizedException)
    async def forbidden(_request: Request, exc: UnauthorizedException) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    return app


@authenticates(Authentication.USER)
async def user_identity(request: Request) -> UserInDB:
    token = request.headers.get("Authorization")
    if token not in {"Bearer member", "Bearer admin", "Bearer api-key"}:
        raise HTTPException(401, "Authentication required")
    user = make_user(Permission.ADMIN) if token == "Bearer admin" else make_user()
    if token == "Bearer api-key":
        user.active_api_key = make_api_key()
    authorize_user(request, user)
    return user


def test_rejects_undeclared_route_at_validation_and_at_request_time() -> None:
    app = application()
    calls = []

    @app.post("/forgotten")
    async def forgotten() -> str:
        calls.append("side effect")
        return "done"

    with pytest.raises(ValueError, match="/forgotten: missing explicit"):
        validate_endpoint_access(app)
    assert TestClient(app).post("/forgotten").status_code == 403
    assert calls == []


def test_a_declaration_without_real_authentication_is_rejected() -> None:
    app = application()

    @app.get("/misconfigured")
    @endpoint_access(
        authentication=Authentication.USER,
        authorization=Permission.ADMIN,
        reason="Admin operation",
    )
    async def misconfigured() -> str:
        pytest.fail("The handler must not run without authentication")

    with pytest.raises(ValueError, match="does not authenticate"):
        validate_endpoint_access(app)
    assert TestClient(app).get("/misconfigured").status_code == 403


@pytest.mark.parametrize(
    ("token", "status"), [(None, 401), ("member", 403), ("admin", 200)]
)
def test_permission_is_checked_before_side_effects_with_inherited_authentication(
    token: str | None,
    status: int,
) -> None:
    app = application()
    outer = APIRouter()
    inner = APIRouter()
    calls = []

    @inner.post("/probe")
    @endpoint_access(
        authentication=Authentication.USER,
        authorization=Permission.ADMIN,
        reason="Uses provider credentials",
    )
    async def probe() -> str:
        calls.append("provider call")
        return "success"

    outer.include_router(
        inner, prefix="/providers", dependencies=[Depends(user_identity)]
    )
    app.include_router(outer, prefix="/admin")
    validate_endpoint_access(app)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = TestClient(app).post("/admin/providers/probe", headers=headers)
    assert response.status_code == status
    assert calls == (["provider call"] if status == 200 else [])


def test_explicit_authenticated_grant_allows_members_but_not_anonymous() -> None:
    app = application()

    @app.get("/catalogue")
    @endpoint_access(
        authentication=Authentication.USER,
        authorization=Authorization.AUTHENTICATED,
        reason="Tenant members may read the model catalogue",
    )
    async def catalogue(user: Annotated[UserInDB, Depends(user_identity)]) -> str:
        return user.username

    validate_endpoint_access(app)
    client = TestClient(app)
    assert client.get("/catalogue").status_code == 401
    assert (
        client.get("/catalogue", headers={"Authorization": "Bearer member"}).status_code
        == 200
    )


def test_public_grant_is_explicit_and_does_not_require_credentials() -> None:
    app = application()

    @app.get("/livez")
    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason="Deployment liveness probe",
    )
    async def livez() -> str:
        return "ok"

    validate_endpoint_access(app)
    assert TestClient(app).get("/livez").json() == "ok"


@pytest.mark.parametrize(
    "authorization", [Permission.ADMIN, Authorization.AUTHENTICATED]
)
def test_public_authentication_cannot_claim_protected_authorization(
    authorization: Permission | Authorization,
) -> None:
    with pytest.raises(ValueError, match="do not match"):
        EndpointAccess(Authentication.PUBLIC, authorization, "Invalid grant")


@pytest.mark.parametrize(
    ("authentication", "token", "status"),
    [
        (Authentication.USER, "member", 200),
        (Authentication.USER, "api-key", 200),
        (Authentication.SESSION, "member", 200),
        (Authentication.SESSION, "api-key", 403),
        (Authentication.API_KEY, "member", 403),
        (Authentication.API_KEY, "api-key", 200),
    ],
)
def test_credential_kind_is_enforced_before_the_handler(authentication, token, status):
    app = application()
    calls = []

    @app.post("/restricted", dependencies=[Depends(user_identity)])
    @endpoint_access(
        authentication=authentication,
        authorization=Authorization.AUTHENTICATED,
        reason="This operation is restricted to the declared credential kind.",
    )
    async def restricted() -> str:
        calls.append("side effect")
        return "done"

    validate_endpoint_access(app)
    response = TestClient(app).post(
        "/restricted", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == status
    assert calls == (["side effect"] if status == 200 else [])
    if authentication is Authentication.SESSION and status == 403:
        assert response.json()["detail"]["code"] == "session_auth_required"


def test_an_authentication_dependency_for_a_different_identity_is_rejected() -> None:
    app = application()

    @app.get("/sysadmin", dependencies=[Depends(user_identity)])
    @endpoint_access(
        authentication=Authentication.SYSADMIN,
        authorization=Authorization.SYSADMIN,
        reason="Requires a deployment administrator, not a tenant user.",
    )
    async def sysadmin() -> str:
        pytest.fail("A tenant identity must not satisfy deployment authentication")

    with pytest.raises(ValueError, match="does not authenticate that identity"):
        validate_endpoint_access(app)
    assert (
        TestClient(app)
        .get("/sysadmin", headers={"Authorization": "Bearer admin"})
        .status_code
        == 403
    )


def test_cors_preflight_does_not_invoke_the_protected_operation() -> None:
    app = application()
    app.add_middleware(
        CORSMiddleware, allow_origins=["https://app.example"], allow_methods=["POST"]
    )
    calls = []

    @app.post("/protected", dependencies=[Depends(user_identity)])
    @endpoint_access(
        authentication=Authentication.USER,
        authorization=Permission.ADMIN,
        reason="Only administrators may invoke this operation.",
    )
    async def protected() -> str:
        calls.append("side effect")
        return "done"

    validate_endpoint_access(app)
    client = TestClient(app)
    response = client.options(
        "/protected",
        headers={
            "Origin": "https://app.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "https://app.example"
    assert (
        client.post("/protected", headers={"Origin": "https://app.example"}).status_code
        == 401
    )
    assert calls == []


def test_shared_mcp_catalogue_keeps_member_access() -> None:
    from eneo.mcp_servers.presentation.mcp_server_router import (
        get_mcp_server,
        get_mcp_server_tools,
        get_mcp_servers,
        get_tenant_mcp_settings,
    )

    # Workspace/assistant settings consume these reads outside the admin UI.
    for endpoint in (
        get_mcp_servers,
        get_tenant_mcp_settings,
        get_mcp_server,
        get_mcp_server_tools,
    ):
        policy = access_for(endpoint)
        assert policy is not None
        assert policy.authorization is Authorization.AUTHENTICATED


def test_an_access_decision_requires_a_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        EndpointAccess(Authentication.USER, Authorization.AUTHENTICATED, " ")


def test_mounted_api_is_not_exempt_from_validation() -> None:
    app = application()
    mounted = application()

    @mounted.get("/forgotten")
    async def forgotten() -> str:
        return "unprotected"

    app.mount("/mounted", mounted)
    with pytest.raises(ValueError, match="/mounted/forgotten"):
        validate_endpoint_access(app)


def test_websocket_without_access_decision_is_rejected_before_acceptance() -> None:
    app = application()

    @app.websocket("/forgotten")
    async def forgotten(websocket: WebSocket) -> None:
        pytest.fail("The websocket must not be accepted without an access decision")

    with pytest.raises(ValueError, match="/forgotten: missing explicit"):
        validate_endpoint_access(app)
    with pytest.raises(WebSocketDenialResponse) as denied:
        with TestClient(app).websocket_connect("/forgotten"):
            pytest.fail("The undeclared websocket must not connect")
    assert denied.value.status_code == 403


@pytest.mark.parametrize("admin", [False, True])
def test_websocket_permission_is_enforced_by_production_authentication(
    monkeypatch, admin
):
    from eneo.database.database import AsyncSession, get_session
    from eneo.server.dependencies import container as container_dependency
    from eneo.server.dependencies.auth_definitions import (
        get_token_from_websocket_header,
    )

    database = AsyncMock(spec=AsyncSession)
    database.__aenter__.return_value = database
    database.begin.return_value = AsyncMock()
    monkeypatch.setattr(
        container_dependency.sessionmanager, "session", lambda: database
    )

    async def identity(_self: UserService, token: str) -> UserInDB:
        return make_user(Permission.ADMIN) if admin else make_user()

    async def session() -> AsyncSession:
        return database

    monkeypatch.setattr(UserService, "authenticate", identity)
    app = application()
    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_token_from_websocket_header] = lambda: "test-token"
    inner = APIRouter()

    @inner.websocket("/socket")
    @endpoint_access(
        authentication=Authentication.WEBSOCKET,
        authorization=Permission.ADMIN,
        reason="This websocket exposes an administrative operation.",
    )
    async def socket(
        websocket: WebSocket,
        user: Annotated[
            UserInDB, Depends(container_dependency.get_user_from_websocket)
        ],
    ) -> None:
        await websocket.accept()
        await websocket.send_text(user.username)
        await websocket.close()

    app.include_router(inner, prefix="/nested")
    validate_endpoint_access(app)
    client = TestClient(app)
    if admin:
        with client.websocket_connect("/nested/socket") as connection:
            assert connection.receive_text() == "endpoint-test"
    else:
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect("/nested/socket"):
                pytest.fail("A member must not open an administrative websocket")
        assert denied.value.code == 1008


def test_framework_documentation_grants_do_not_cover_other_routes() -> None:
    app = FastAPI()
    declare_framework_documentation_access(app)
    validate_endpoint_access(app)

    @app.get("/docs/private")
    async def private() -> str:
        return "not covered by a prefix exception"

    with pytest.raises(ValueError, match="/docs/private"):
        validate_endpoint_access(app)


def test_all_shipped_endpoints_have_valid_access_contracts() -> None:
    from eneo.server.main import app

    validate_endpoint_access(app)
    paths = {route.path for route in endpoint_routes(app.routes)}
    assert "/api/v1/admin/model-providers/{provider_id}/test/" in paths
    assert "/api/v1/ws" in paths
    assert "/scim/v2/Users" in paths
    assert "/api/livez" in paths


@pytest.mark.parametrize(
    ("method", "path", "payload", "operation", "result"),
    [
        ("GET", "models", None, "list_available_models", []),
        ("POST", "test", None, "test_connection", {"success": True}),
        (
            "POST",
            "validate-model",
            {"model_name": "test", "model_type": "completion"},
            "validate_model",
            {"success": True},
        ),
    ],
)
def test_provider_probes_enforce_policy_through_real_authentication(
    monkeypatch,
    method,
    path,
    payload,
    operation,
    result,
) -> None:
    from eneo.authentication.auth_dependencies import get_current_active_user
    from eneo.database.database import AsyncSession, get_session_with_transaction
    from eneo.model_providers.domain.model_provider_service import ModelProviderService
    from eneo.model_providers.presentation.model_provider_router import router

    users = {"member": make_user(), "admin": make_user(Permission.ADMIN)}

    async def token_user(_self: UserService, token: str) -> UserInDB:
        return users[token]

    async def active_state(
        _self: UserService, _user: UserInDB, correlation_id: str
    ) -> None:
        return None

    monkeypatch.setattr(UserService, "_get_user_from_token", token_user)
    monkeypatch.setattr(UserService, "_check_user_and_tenant_state", active_state)
    service = object.__new__(UserService)

    async def authenticate(request: Request) -> UserInDB:
        # Exercise the production authentication method, including its access
        # policy enforcement. Only credential lookup and live state are stubbed.
        return await service.authenticate(
            token=request.headers.get("X-Test-User"), request=request
        )

    async def session() -> AsyncSession:
        return AsyncMock(spec=AsyncSession)

    calls = []

    async def probe(*_args, **_kwargs):
        calls.append("external provider")
        return result

    monkeypatch.setattr(ModelProviderService, operation, probe)
    app = application()
    add_exception_handlers(app)
    app.include_router(router, prefix="/admin/model-providers")
    app.dependency_overrides[get_current_active_user] = authenticate
    app.dependency_overrides[get_session_with_transaction] = session
    validate_endpoint_access(app)
    client = TestClient(app)
    url = f"/admin/model-providers/{uuid4()}/{path}/"
    assert client.request(method, url, json=payload).status_code == 401
    assert (
        client.request(
            method, url, json=payload, headers={"X-Test-User": "member"}
        ).status_code
        == 403
    )
    assert calls == []
    response = client.request(
        method, url, json=payload, headers={"X-Test-User": "admin"}
    )
    assert response.status_code == 200, response.text
    assert response.json() == result
    assert calls == ["external provider"]
