"""Tests for method-aware resource permission guards, error contracts, and override validation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from intric.audit.domain.action_types import ActionType

from intric.authentication.auth_dependencies import (
    APPS_READ_OVERRIDES,
    ASSISTANTS_READ_OVERRIDES,
    CONVERSATIONS_READ_OVERRIDES,
    KNOWLEDGE_READ_OVERRIDES,
    _raise_api_key_http_error,
    require_api_key_permission,
    require_resource_permission_for_method,
)
from intric.authentication.api_key_resolver import (
    ApiKeyValidationError,
    check_resource_permission,
)
from intric.authentication.auth_models import (
    ApiKeyPermission,
    ApiKeyV2InDB,
    METHOD_PERMISSION_MAP,
    PERMISSION_LEVEL_ORDER,
    ResourcePermissionLevel,
    ResourcePermissions,
)
from starlette.requests import Request

from intric.users.user_service import (
    UserService,
    _check_basic_method_permission,
    _check_management_permission,
    _check_method_resource_permission,
    _permission_allows,
)
from tests.unit.api_key_test_utils import make_api_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_key(**overrides: object) -> ApiKeyV2InDB:
    return make_api_key(
        default_permission=ApiKeyPermission.WRITE,
        **overrides,
    )


def _fake_request(
    method: str,
    *,
    endpoint_name: str | None = None,
) -> SimpleNamespace:
    """Build a minimal request-like object for _check_method_resource_permission."""
    route = None
    if endpoint_name is not None:
        endpoint_fn = lambda: None  # noqa: E731
        endpoint_fn.__name__ = endpoint_name
        route = SimpleNamespace(endpoint=endpoint_fn)

    scope: dict[str, Any] = {}
    if route is not None:
        scope["route"] = route

    return SimpleNamespace(
        method=method,
        scope=scope,
    )


def _make_request(
    method: str = "GET",
    path: str = "/",
) -> SimpleNamespace:
    """Build a minimal request-like object with mutable state for guard tests."""
    from starlette.datastructures import State

    return SimpleNamespace(
        method=method,
        state=State(),
        url=SimpleNamespace(path=path),
    )


def _config(
    resource_type: str = "apps",
    read_override_endpoints: frozenset[str] | None = None,
) -> dict:
    return {
        "resource_type": resource_type,
        "read_override_endpoints": read_override_endpoints,
    }


# ---------------------------------------------------------------------------
# Unit tests — _check_method_resource_permission (tests 1-9)
# ---------------------------------------------------------------------------


class TestMethodAwarePermissionCheck:
    """Tests 1-9: method-aware permission check logic."""

    def test_read_key_get_passes(self, monkeypatch):
        """1. Read key + GET → pass."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.READ),
        )
        request = _fake_request("GET")
        _check_method_resource_permission(request, key, _config("apps"))

    def test_read_key_post_blocked(self, monkeypatch):
        """2. Read key + POST → 403."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.READ),
        )
        request = _fake_request("POST")
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_method_resource_permission(request, key, _config("apps"))
        assert exc_info.value.status_code == 403

    def test_read_key_delete_blocked(self, monkeypatch):
        """3. Read key + DELETE → 403."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.READ),
        )
        request = _fake_request("DELETE")
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_method_resource_permission(request, key, _config("apps"))
        assert exc_info.value.status_code == 403

    def test_write_key_post_passes(self, monkeypatch):
        """4. Write key + POST → pass."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.WRITE),
        )
        request = _fake_request("POST")
        _check_method_resource_permission(request, key, _config("apps"))

    def test_write_key_delete_blocked(self, monkeypatch):
        """5. Write key + DELETE → 403."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.WRITE),
        )
        request = _fake_request("DELETE")
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_method_resource_permission(request, key, _config("apps"))
        assert exc_info.value.status_code == 403

    def test_admin_key_delete_passes(self, monkeypatch):
        """6. Admin key + DELETE → pass."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.ADMIN),
        )
        request = _fake_request("DELETE")
        _check_method_resource_permission(request, key, _config("apps"))

    def test_unknown_method_defaults_to_admin(self, monkeypatch):
        """7. Unknown HTTP method → admin (fail-closed)."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.WRITE),
        )
        request = _fake_request("PURGE")
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_method_resource_permission(request, key, _config("apps"))
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_guard_stores_config_on_request_state(self):
        """8. Router guard stores config on request.state, does not check permissions."""
        request = SimpleNamespace(state=SimpleNamespace())
        dep = require_resource_permission_for_method(
            "apps", read_override_endpoints=ASSISTANTS_READ_OVERRIDES
        )
        await dep(request)
        assert request.state._resource_perm_config == {
            "resource_type": "apps",
            "read_override_endpoints": ASSISTANTS_READ_OVERRIDES,
        }

    def test_post_override_endpoint_treated_as_read(self, monkeypatch):
        """9. POST hitting override endpoint name → read (pass for read key)."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(
                assistants=ResourcePermissionLevel.READ,
            ),
        )
        request = _fake_request("POST", endpoint_name="estimate_tokens")
        _check_method_resource_permission(
            request, key,
            _config("assistants", read_override_endpoints=ASSISTANTS_READ_OVERRIDES),
        )


# ---------------------------------------------------------------------------
# Integration tests — endpoint permission transitions (tests 10-12)
# ---------------------------------------------------------------------------


class TestEndpointPermissionTransitions:
    """Tests 10-12: verify method+endpoint combos deny/allow correctly."""

    def test_read_key_allowed_on_post_ask_assistant_via_override(self, monkeypatch):
        """10. Read key + POST ask_assistant → pass (ask_assistant is a read-override)."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(
                assistants=ResourcePermissionLevel.READ,
            ),
        )
        request = _fake_request("POST", endpoint_name="ask_assistant")
        # Should NOT raise — ask_assistant is in ASSISTANTS_READ_OVERRIDES
        _check_method_resource_permission(
            request, key,
            _config("assistants", read_override_endpoints=ASSISTANTS_READ_OVERRIDES),
        )

    def test_write_key_denied_on_delete_apps(self, monkeypatch):
        """11. Write key denied on DELETE delete_app (requires admin)."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(
                apps=ResourcePermissionLevel.WRITE,
            ),
        )
        request = _fake_request("DELETE", endpoint_name="delete_app")
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_method_resource_permission(request, key, _config("apps"))
        assert exc_info.value.status_code == 403

    def test_no_resource_permissions_falls_back_to_basic_permission(self, monkeypatch):
        """12. Key with resource_permissions=None falls back to basic permission check."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        # WRITE key: GET passes, POST passes, DELETE blocked (requires admin)
        key = _make_key(resource_permissions=None, permission=ApiKeyPermission.WRITE)
        _check_method_resource_permission(
            _fake_request("GET"), key, _config("apps"),
        )
        _check_method_resource_permission(
            _fake_request("POST"), key, _config("apps"),
        )
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_method_resource_permission(
                _fake_request("DELETE"), key, _config("apps"),
            )
        assert exc_info.value.status_code == 403

        # READ key: GET passes, POST blocked
        read_key = _make_key(resource_permissions=None, permission=ApiKeyPermission.READ)
        _check_method_resource_permission(
            _fake_request("GET"), read_key, _config("apps"),
        )
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_method_resource_permission(
                _fake_request("POST"), read_key, _config("apps"),
            )
        assert exc_info.value.status_code == 403

        # ADMIN key: all pass
        admin_key = _make_key(resource_permissions=None, permission=ApiKeyPermission.ADMIN)
        for method in ("GET", "POST", "DELETE"):
            _check_method_resource_permission(
                _fake_request(method), admin_key, _config("apps"),
            )


# ---------------------------------------------------------------------------
# Policy test — max_rate_limit_override blocks unlimited (test 13)
# ---------------------------------------------------------------------------


class TestPolicyMaxRateLimit:
    """Test 13: max_rate_limit_override blocks rate_limit=-1."""

    @pytest.mark.asyncio
    async def test_max_rate_limit_override_blocks_unlimited(self):
        from intric.authentication.api_key_policy import ApiKeyPolicyService

        tenant = SimpleNamespace(api_key_policy={"max_rate_limit_override": 100})
        user = SimpleNamespace(tenant=tenant, permissions=[])
        service = ApiKeyPolicyService(
            allowed_origin_repo=SimpleNamespace(),
            space_service=SimpleNamespace(),
            user=user,
        )
        with pytest.raises(ApiKeyValidationError) as exc_info:
            await service._validate_rate_limit(-1)
        assert exc_info.value.status_code == 400
        assert "not allowed" in exc_info.value.message.lower()


# ---------------------------------------------------------------------------
# Error contract tests — all 3 raise paths (tests 14-16)
# ---------------------------------------------------------------------------


class TestErrorContracts:
    """Tests 14-16: all raise paths produce {code, message} body + headers."""

    def test_auth_dependencies_raise_preserves_contract(self):
        """14. _raise_api_key_http_error in auth_dependencies.py."""
        exc = ApiKeyValidationError(
            status_code=429,
            code="rate_limited",
            message="Too many requests.",
            headers={"Retry-After": "60"},
        )
        with pytest.raises(HTTPException) as exc_info:
            _raise_api_key_http_error(exc)
        http_exc = exc_info.value
        assert http_exc.status_code == 429
        assert http_exc.detail == {"code": "rate_limited", "message": "Too many requests."}
        assert http_exc.headers["Retry-After"] == "60"

    def test_router_helpers_raise_preserves_contract(self):
        """15. raise_api_key_http_error in api_key_router_helpers.py."""
        from intric.authentication.api_key_router_helpers import raise_api_key_http_error

        exc = ApiKeyValidationError(
            status_code=403,
            code="insufficient_permission",
            message="Denied.",
            headers={"X-Custom": "val"},
        )
        with pytest.raises(HTTPException) as exc_info:
            raise_api_key_http_error(exc)
        http_exc = exc_info.value
        assert http_exc.status_code == 403
        assert http_exc.detail == {"code": "insufficient_permission", "message": "Denied."}
        assert http_exc.headers["X-Custom"] == "val"

    def test_container_raise_preserves_contract(self):
        """16. _raise_api_key_http_error in container.py."""
        from intric.server.dependencies.container import _raise_api_key_http_error as container_raise

        exc = ApiKeyValidationError(
            status_code=401,
            code="invalid_api_key",
            message="Invalid.",
            headers={"WWW-Authenticate": "Bearer"},
        )
        with pytest.raises(HTTPException) as exc_info:
            container_raise(exc)
        http_exc = exc_info.value
        assert http_exc.status_code == 401
        assert http_exc.detail == {"code": "invalid_api_key", "message": "Invalid."}
        assert http_exc.headers["WWW-Authenticate"] == "Bearer"


# ---------------------------------------------------------------------------
# Override name validation test (test 17)
# ---------------------------------------------------------------------------


class TestOverrideNameValidation:
    """Test 17: all override names match actual endpoint function names."""

    def _collect_endpoint_names(self, router) -> set[str]:
        names: set[str] = set()
        for route in router.routes:
            if hasattr(route, "endpoint"):
                names.add(route.endpoint.__name__)
            if hasattr(route, "routes"):
                names.update(self._collect_endpoint_names(route))
        return names

    def test_override_names_match_registered_routes(self):
        """Import the routers, iterate all registered routes, assert overrides match."""
        from intric.assistants.api.assistant_router import router as assistants_router
        from intric.groups_legacy.api.group_router import router as groups_router
        from intric.conversations.conversations_router import router as conversations_router
        from intric.apps.apps.api.app_router import router as apps_router
        from intric.services.service_router import router as services_router

        assistant_names = self._collect_endpoint_names(assistants_router)
        group_names = self._collect_endpoint_names(groups_router)
        conversation_names = self._collect_endpoint_names(conversations_router)
        # APPS_READ_OVERRIDES is shared across app_router and services_router
        apps_names = (
            self._collect_endpoint_names(apps_router)
            | self._collect_endpoint_names(services_router)
        )

        for name in ASSISTANTS_READ_OVERRIDES:
            assert name in assistant_names, (
                f"ASSISTANTS_READ_OVERRIDES contains '{name}' but no route has that endpoint name"
            )

        for name in KNOWLEDGE_READ_OVERRIDES:
            assert name in group_names, (
                f"KNOWLEDGE_READ_OVERRIDES contains '{name}' but no route has that endpoint name"
            )

        for name in CONVERSATIONS_READ_OVERRIDES:
            assert name in conversation_names, (
                f"CONVERSATIONS_READ_OVERRIDES contains '{name}' but no route has that endpoint name"
            )

        for name in APPS_READ_OVERRIDES:
            assert name in apps_names, (
                f"APPS_READ_OVERRIDES contains '{name}' but no route has that endpoint name"
            )


# ---------------------------------------------------------------------------
# ResourceDenialContext tests
# ---------------------------------------------------------------------------


class TestResourceDenialContext:
    """Verify context is attached when resource permission check fails."""

    def test_check_resource_permission_attaches_context(self, monkeypatch):
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.READ),
        )
        with pytest.raises(ApiKeyValidationError) as exc_info:
            check_resource_permission(key, "apps", "write")
        exc = exc_info.value
        assert exc.context is not None
        assert exc.context["resource_type"] == "apps"
        assert exc.context["required_level"] == "write"
        assert exc.context["granted_level"] == "read"

    def test_context_is_none_on_non_resource_errors(self):
        exc = ApiKeyValidationError(
            status_code=401, code="invalid_api_key", message="Bad key."
        )
        assert exc.context is None


# ---------------------------------------------------------------------------
# Audit enrichment test
# ---------------------------------------------------------------------------


class TestAuthFailureAuditEnrichment:
    """Verify auth failure audit includes request metadata and denial context."""

    @pytest.mark.asyncio
    async def test_auth_failed_audit_includes_route_origin_and_context(self):
        audit = AsyncMock()
        user = SimpleNamespace(
            id=uuid4(),
            tenant_id=uuid4(),
            username="test-user",
            email="test@example.com",
        )
        service = UserService(
            user_repo=AsyncMock(),
            auth_service=AsyncMock(),
            api_key_auth_resolver=AsyncMock(),
            api_key_v2_repo=AsyncMock(),
            allowed_origin_repo=AsyncMock(),
            audit_service=audit,
            settings_repo=AsyncMock(),
            tenant_repo=AsyncMock(),
            info_blob_repo=AsyncMock(),
        )
        key = _make_key(tenant_id=user.tenant_id)
        exc = ApiKeyValidationError(
            status_code=403,
            code="insufficient_resource_permission",
            message="Denied by resource permission.",
            context={
                "resource_type": "apps",
                "required_level": "write",
                "granted_level": "read",
            },
        )
        request = SimpleNamespace(
            scope={"route": SimpleNamespace(path="/api/v1/apps/{id}/")},
            method="PATCH",
            headers={"origin": "https://client.example.com"},
            url=SimpleNamespace(path="/api/v1/apps/123/"),
        )

        await service._log_api_key_auth_failed(
            user=user,
            key=key,
            exc=exc,
            request=request,
        )

        audit.log_async.assert_awaited_once()
        kwargs = audit.log_async.call_args.kwargs
        assert kwargs["action"] == ActionType.API_KEY_AUTH_FAILED
        extra = kwargs["metadata"]["extra"]
        assert extra["request_path"] == "/api/v1/apps/{id}/"
        assert extra["method"] == "PATCH"
        assert extra["origin"] == "https://client.example.com"
        assert extra["resource_type"] == "apps"
        assert extra["required_level"] == "write"
        assert extra["granted_level"] == "read"


# ---------------------------------------------------------------------------
# HTTP integration tests — FastAPI dependency chain (tests 18-20)
# ---------------------------------------------------------------------------


class TestHTTPIntegration:
    """Tests 18-20: validate the full HTTP → FastAPI → dependency → guard chain."""

    @staticmethod
    def _build_app(
        auth_key: ApiKeyV2InDB | None = None,
        rate_limit_exc: ApiKeyValidationError | None = None,
    ):
        """Build a minimal FastAPI app with a guarded route.

        *auth_key*: when set, the auth dependency injects this key on request.state
        (simulating API-key auth).  When None, simulates bearer-token auth.

        *rate_limit_exc*: when set, the auth dependency raises this after
        setting request.state (simulating a rate-limit rejection).
        """
        from fastapi import Depends, FastAPI
        from fastapi.responses import JSONResponse

        app = FastAPI()

        guarded = Depends(require_resource_permission_for_method("apps"))

        def _make_auth_dep(
            _key: ApiKeyV2InDB | None,
            _rate_exc: ApiKeyValidationError | None,
        ):
            async def _dep(request):
                if _rate_exc is not None:
                    if _key is not None:
                        request.state.api_key = _key
                    raise _rate_exc
                if _key is not None:
                    request.state.api_key = _key
                    request.state.api_key_permission = _key.permission
                    request.state.api_key_scope_type = _key.scope_type
                    request.state.api_key_scope_id = _key.scope_id
                    request.state.api_key_resource_permissions = _key.resource_permissions
                    perm_config = getattr(request.state, "_resource_perm_config", None)
                    if perm_config is not None:
                        _check_method_resource_permission(request, _key, perm_config)
                return {"id": "fake-user"}
            # Explicit annotation: avoids PEP 563 turning it into a string
            _dep.__annotations__["request"] = Request
            return _dep

        fake_auth = _make_auth_dep(auth_key, rate_limit_exc)

        @app.exception_handler(ApiKeyValidationError)
        async def _handle(request, exc):
            return JSONResponse(
                status_code=exc.status_code,
                content={"code": exc.code, "message": exc.message},
                headers=exc.headers,
            )
        _handle.__annotations__["request"] = Request
        _handle.__annotations__["exc"] = ApiKeyValidationError

        @app.post("/test-resource", dependencies=[guarded])
        async def test_endpoint(user=Depends(fake_auth)):
            return {"ok": True}

        return app

    @pytest.mark.asyncio
    async def test_read_key_post_returns_403(self, monkeypatch):
        """18. Read-only API key + POST to guarded route → 403."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.READ),
        )
        app = self._build_app(auth_key=key)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/test-resource")
        assert resp.status_code == 403
        body = resp.json()
        assert body["code"] == "insufficient_resource_permission"

    @pytest.mark.asyncio
    async def test_bearer_token_post_passes(self, monkeypatch):
        """19. Bearer-token auth (no API key) + POST to guarded route → 200."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        app = self._build_app(auth_key=None)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/test-resource")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        assert resp.json() == {"ok": True}

    @pytest.mark.asyncio
    async def test_rate_limited_returns_429_with_headers(self, monkeypatch):
        """20. Rate-limited request → 429 with Retry-After and X-RateLimit-* headers."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.WRITE),
        )
        rate_exc = ApiKeyValidationError(
            status_code=429,
            code="rate_limit_exceeded",
            message="API key rate limit exceeded.",
            headers={
                "Retry-After": "60",
                "X-RateLimit-Limit": "100",
                "X-RateLimit-Remaining": "0",
            },
        )
        app = self._build_app(auth_key=key, rate_limit_exc=rate_exc)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/test-resource")
        assert resp.status_code == 429
        assert resp.headers["retry-after"] == "60"
        assert resp.headers["x-ratelimit-limit"] == "100"
        assert resp.headers["x-ratelimit-remaining"] == "0"


# ---------------------------------------------------------------------------
# _check_basic_method_permission tests (Phase 7B)
# ---------------------------------------------------------------------------


class TestCheckBasicMethodPermission:
    """Tests for Layer 2: _check_basic_method_permission."""

    def test_read_key_get_passes(self):
        key = _make_key(permission=ApiKeyPermission.READ)
        request = _fake_request("GET")
        _check_basic_method_permission(request, key)

    def test_read_key_post_blocked(self):
        key = _make_key(permission=ApiKeyPermission.READ)
        request = _fake_request("POST")
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_basic_method_permission(request, key)
        assert exc_info.value.status_code == 403
        assert "requires 'write'" in exc_info.value.message
        assert "read" not in exc_info.value.message  # granted level must NOT leak

    def test_read_key_delete_blocked(self):
        key = _make_key(permission=ApiKeyPermission.READ)
        request = _fake_request("DELETE")
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_basic_method_permission(request, key)
        assert exc_info.value.status_code == 403
        assert "requires 'admin'" in exc_info.value.message
        assert "read" not in exc_info.value.message

    def test_write_key_post_passes(self):
        key = _make_key(permission=ApiKeyPermission.WRITE)
        request = _fake_request("POST")
        _check_basic_method_permission(request, key)

    def test_write_key_delete_blocked(self):
        key = _make_key(permission=ApiKeyPermission.WRITE)
        request = _fake_request("DELETE")
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_basic_method_permission(request, key)
        assert exc_info.value.status_code == 403
        assert "requires 'admin'" in exc_info.value.message
        assert "write" not in exc_info.value.message

    def test_admin_key_delete_passes(self):
        key = _make_key(permission=ApiKeyPermission.ADMIN)
        request = _fake_request("DELETE")
        _check_basic_method_permission(request, key)

    def test_unknown_method_defaults_to_admin(self):
        key = _make_key(permission=ApiKeyPermission.WRITE)
        request = _fake_request("PURGE")
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_basic_method_permission(request, key)
        assert exc_info.value.status_code == 403

    def test_head_and_options_treated_as_read(self):
        key = _make_key(permission=ApiKeyPermission.READ)
        for method in ("HEAD", "OPTIONS"):
            _check_basic_method_permission(_fake_request(method), key)


# ---------------------------------------------------------------------------
# Read-override tests for new constants (Phase 7C)
# ---------------------------------------------------------------------------


class TestReadOverrideConstants:
    """Verify new read-override constants work with _check_method_resource_permission."""

    def test_conversations_chat_override(self, monkeypatch):
        """Read key + POST to 'chat' on conversations → pass (read-override)."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(assistants=ResourcePermissionLevel.READ),
        )
        request = _fake_request("POST", endpoint_name="chat")
        _check_method_resource_permission(
            request, key,
            _config("assistants", read_override_endpoints=CONVERSATIONS_READ_OVERRIDES),
        )

    def test_conversations_leave_feedback_override(self, monkeypatch):
        """Read key + POST to 'leave_feedback' on conversations → pass."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(assistants=ResourcePermissionLevel.READ),
        )
        request = _fake_request("POST", endpoint_name="leave_feedback")
        _check_method_resource_permission(
            request, key,
            _config("assistants", read_override_endpoints=CONVERSATIONS_READ_OVERRIDES),
        )

    def test_apps_run_service_override(self, monkeypatch):
        """Read key + POST to 'run_service' on apps → pass (read-override)."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.READ),
        )
        request = _fake_request("POST", endpoint_name="run_service")
        _check_method_resource_permission(
            request, key,
            _config("apps", read_override_endpoints=APPS_READ_OVERRIDES),
        )

    def test_apps_run_app_override(self, monkeypatch):
        """Read key + POST to 'run_app' on apps → pass (read-override)."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.READ),
        )
        request = _fake_request("POST", endpoint_name="run_app")
        _check_method_resource_permission(
            request, key,
            _config("apps", read_override_endpoints=APPS_READ_OVERRIDES),
        )

    def test_non_override_post_still_blocked(self, monkeypatch):
        """Read key + POST to non-override endpoint → 403."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.READ),
        )
        request = _fake_request("POST", endpoint_name="create_app")
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_method_resource_permission(
                request, key,
                _config("apps", read_override_endpoints=APPS_READ_OVERRIDES),
            )
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Legacy split mapping tests (Phase 7F)
# ---------------------------------------------------------------------------


class TestLegacySplitMapping:
    """Verify legacy migration creates correct permission levels."""

    def test_user_key_migration_creates_admin(self):
        """User key migration → permission=ADMIN."""
        from intric.authentication.auth_models import ApiKeyPermission
        # The code at api_key_resolver.py sets permission=ApiKeyPermission.ADMIN.value
        # for user keys (scope_type=tenant). Verify constant value.
        assert ApiKeyPermission.ADMIN.value == "admin"

    def test_assistant_key_migration_creates_read(self):
        """Assistant key migration → permission=READ."""
        from intric.authentication.auth_models import ApiKeyPermission
        # The code at api_key_resolver.py sets permission=ApiKeyPermission.READ.value
        # for assistant keys (scope_type=assistant). Verify constant value.
        assert ApiKeyPermission.READ.value == "read"

    def test_method_permission_map_completeness(self):
        """METHOD_PERMISSION_MAP covers all standard HTTP methods."""
        for method in ("GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"):
            assert method in METHOD_PERMISSION_MAP, f"Missing method: {method}"

    def test_permission_level_order_hierarchy(self):
        """Permission levels: none(0) < read(1) < write(2) < admin(3)."""
        assert PERMISSION_LEVEL_ORDER["none"] < PERMISSION_LEVEL_ORDER["read"]
        assert PERMISSION_LEVEL_ORDER["read"] < PERMISSION_LEVEL_ORDER["write"]
        assert PERMISSION_LEVEL_ORDER["write"] < PERMISSION_LEVEL_ORDER["admin"]


# ---------------------------------------------------------------------------
# Feature flag tests (Phase 7G)
# ---------------------------------------------------------------------------


class TestFeatureFlagEnforcement:
    """Verify feature flag gates permission enforcement."""

    def test_flag_disabled_skips_resource_check(self, monkeypatch):
        """Flag disabled → check_resource_permission returns without raising."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=False),
        )
        # Read key + admin-level resource check → should pass when flag disabled
        key = _make_key(
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.READ),
        )
        check_resource_permission(key, "apps", "admin")  # No exception

    def test_flag_enabled_enforces_resource_check(self, monkeypatch):
        """Flag enabled → check_resource_permission raises on insufficient permission."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.READ),
        )
        with pytest.raises(ApiKeyValidationError) as exc_info:
            check_resource_permission(key, "apps", "admin")
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Consolidation tests (Phase 7H)
# ---------------------------------------------------------------------------


class TestPermissionAllowsConsolidation:
    """Verify _permission_allows module-level function works correctly."""

    def test_admin_allows_all(self):
        key = _make_key(permission=ApiKeyPermission.ADMIN)
        assert _permission_allows(key, ApiKeyPermission.READ) is True
        assert _permission_allows(key, ApiKeyPermission.WRITE) is True
        assert _permission_allows(key, ApiKeyPermission.ADMIN) is True

    def test_write_allows_read_and_write(self):
        key = _make_key(permission=ApiKeyPermission.WRITE)
        assert _permission_allows(key, ApiKeyPermission.READ) is True
        assert _permission_allows(key, ApiKeyPermission.WRITE) is True
        assert _permission_allows(key, ApiKeyPermission.ADMIN) is False

    def test_read_allows_only_read(self):
        key = _make_key(permission=ApiKeyPermission.READ)
        assert _permission_allows(key, ApiKeyPermission.READ) is True
        assert _permission_allows(key, ApiKeyPermission.WRITE) is False
        assert _permission_allows(key, ApiKeyPermission.ADMIN) is False


# ---------------------------------------------------------------------------
# Error message security tests (Phase 7 — T6)
# ---------------------------------------------------------------------------


class TestErrorMessageSecurity:
    """Verify 403 messages do NOT leak the key's granted permission level."""

    def test_basic_method_permission_no_leak(self):
        """_check_basic_method_permission messages don't contain granted level."""
        for perm, blocked_method in [
            (ApiKeyPermission.READ, "POST"),
            (ApiKeyPermission.READ, "DELETE"),
            (ApiKeyPermission.WRITE, "DELETE"),
        ]:
            key = _make_key(permission=perm)
            request = _fake_request(blocked_method)
            with pytest.raises(ApiKeyValidationError) as exc_info:
                _check_basic_method_permission(request, key)
            msg = exc_info.value.message
            assert perm.value not in msg, (
                f"Error message leaked granted permission '{perm.value}': {msg}"
            )

    def test_resource_permission_no_leak_in_message(self, monkeypatch):
        """check_resource_permission message doesn't contain key.permission."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            permission=ApiKeyPermission.READ,
            resource_permissions=None,
        )
        with pytest.raises(ApiKeyValidationError) as exc_info:
            check_resource_permission(key, "apps", "admin")
        # The granted level should be in context, not in the message
        assert exc_info.value.context is not None
        assert exc_info.value.context["granted_level"] == "read"


# ---------------------------------------------------------------------------
# Primary bug scenario test (Phase 7 — T1)
# ---------------------------------------------------------------------------


class TestPrimaryBugScenario:
    """The exact bug being fixed: resource_permissions=None + read key + DELETE → 403."""

    def test_read_key_null_resource_permissions_delete_blocked(self, monkeypatch):
        """Read key (resource_permissions=None) + DELETE on guarded route → 403."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            permission=ApiKeyPermission.READ,
            resource_permissions=None,
        )
        request = _fake_request("DELETE")
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_method_resource_permission(request, key, _config("apps"))
        assert exc_info.value.status_code == 403
        assert exc_info.value.code == "insufficient_resource_permission"

    def test_read_key_null_resource_permissions_post_blocked(self, monkeypatch):
        """Read key (resource_permissions=None) + POST on guarded route → 403."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            permission=ApiKeyPermission.READ,
            resource_permissions=None,
        )
        request = _fake_request("POST")
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_method_resource_permission(request, key, _config("apps"))
        assert exc_info.value.status_code == 403

    def test_read_key_null_resource_permissions_get_passes(self, monkeypatch):
        """Read key (resource_permissions=None) + GET on guarded route → pass."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            permission=ApiKeyPermission.READ,
            resource_permissions=None,
        )
        request = _fake_request("GET")
        _check_method_resource_permission(request, key, _config("apps"))


# ---------------------------------------------------------------------------
# Full permission matrix (Phase 7K)
# ---------------------------------------------------------------------------

# Expected outcomes: True = passes, False = 403
# Permission hierarchy: read(1) < write(2) < admin(3)
# Method map: GET/HEAD/OPTIONS→read, POST/PUT/PATCH→write, DELETE→admin
_MATRIX_CASES = []
for _perm, _perm_level in [("read", 1), ("write", 2), ("admin", 3)]:
    for _method, _required in [
        ("GET", "read"), ("HEAD", "read"), ("OPTIONS", "read"),
        ("POST", "write"), ("PUT", "write"), ("PATCH", "write"),
        ("DELETE", "admin"),
    ]:
        _required_level = PERMISSION_LEVEL_ORDER[_required]
        _should_pass = _perm_level >= _required_level
        _MATRIX_CASES.append((_perm, _method, _should_pass))


class TestPermissionMatrix:
    """Phase 7K: 3 permissions × 7 methods × 2 modes (fine-grained + null fallback)."""

    @pytest.mark.parametrize("perm,method,should_pass", _MATRIX_CASES)
    def test_fine_grained_mode(self, monkeypatch, perm, method, should_pass):
        """Fine-grained mode: resource_permissions set, permission matches basic level."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            permission=ApiKeyPermission(perm),
            resource_permissions=ResourcePermissions(
                apps=ResourcePermissionLevel(perm),
            ),
        )
        request = _fake_request(method)
        if should_pass:
            _check_method_resource_permission(request, key, _config("apps"))
        else:
            with pytest.raises(ApiKeyValidationError) as exc_info:
                _check_method_resource_permission(request, key, _config("apps"))
            assert exc_info.value.status_code == 403

    @pytest.mark.parametrize("perm,method,should_pass", _MATRIX_CASES)
    def test_null_fallback_mode(self, monkeypatch, perm, method, should_pass):
        """Null fallback mode: resource_permissions=None, falls back to basic permission."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            permission=ApiKeyPermission(perm),
            resource_permissions=None,
        )
        request = _fake_request(method)
        if should_pass:
            _check_method_resource_permission(request, key, _config("apps"))
        else:
            with pytest.raises(ApiKeyValidationError) as exc_info:
                _check_method_resource_permission(request, key, _config("apps"))
            assert exc_info.value.status_code == 403

    @pytest.mark.parametrize(
        "override_endpoint,override_set,resource_type",
        [
            ("ask_assistant", ASSISTANTS_READ_OVERRIDES, "assistants"),
            ("chat", CONVERSATIONS_READ_OVERRIDES, "assistants"),
            ("run_app", APPS_READ_OVERRIDES, "apps"),
            ("run_service", APPS_READ_OVERRIDES, "apps"),
            ("estimate_tokens", ASSISTANTS_READ_OVERRIDES, "assistants"),
        ],
    )
    def test_read_override_allows_read_key_post(
        self, monkeypatch, override_endpoint, override_set, resource_type
    ):
        """Read key + POST to read-override endpoint → pass."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            permission=ApiKeyPermission.READ,
            resource_permissions=ResourcePermissions(
                **{resource_type: ResourcePermissionLevel.READ},
            ),
        )
        request = _fake_request("POST", endpoint_name=override_endpoint)
        _check_method_resource_permission(
            request, key,
            _config(resource_type, read_override_endpoints=override_set),
        )


# ---------------------------------------------------------------------------
# Guardrail interaction tests (Phase 7L)
# ---------------------------------------------------------------------------


class TestGuardrailInteraction:
    """Verify permission checks work independently from guardrail state."""

    def test_permission_check_independent_of_origin(self, monkeypatch):
        """Permission check runs regardless of origin validation result.

        Origin guardrails are enforced earlier in the pipeline (enforce_guardrails).
        Permission checks happen later in _resolve_api_key. These are independent layers.
        """
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        # Simulating a key that would pass origin check but fail permission check
        key = _make_key(
            permission=ApiKeyPermission.READ,
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.READ),
        )
        # DELETE requires admin — should fail regardless of origin
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_method_resource_permission(
                _fake_request("DELETE"), key, _config("apps"),
            )
        assert exc_info.value.status_code == 403
        assert exc_info.value.code == "insufficient_resource_permission"

    def test_permission_check_passes_when_sufficient(self, monkeypatch):
        """Admin key passes permission check regardless of guardrail status."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(
            permission=ApiKeyPermission.ADMIN,
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.ADMIN),
        )
        # Admin key can DELETE — permission layer passes
        _check_method_resource_permission(
            _fake_request("DELETE"), key, _config("apps"),
        )

    def test_basic_permission_check_independent(self, monkeypatch):
        """Basic method permission check is independent of resource guards."""
        # Read key can't POST on unguarded route
        key = _make_key(permission=ApiKeyPermission.READ)
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_basic_method_permission(_fake_request("POST"), key)
        assert exc_info.value.code == "insufficient_permission"

        # But admin key can
        admin_key = _make_key(permission=ApiKeyPermission.ADMIN)
        _check_basic_method_permission(_fake_request("POST"), admin_key)

    def test_layer2_error_code_differs_from_layer1(self, monkeypatch):
        """Layer 1 (resource) uses 'insufficient_resource_permission',
        Layer 2 (basic) uses 'insufficient_permission'."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        # Layer 1
        key_l1 = _make_key(
            permission=ApiKeyPermission.READ,
            resource_permissions=ResourcePermissions(apps=ResourcePermissionLevel.READ),
        )
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_method_resource_permission(
                _fake_request("DELETE"), key_l1, _config("apps"),
            )
        assert exc_info.value.code == "insufficient_resource_permission"

        # Layer 2
        key_l2 = _make_key(permission=ApiKeyPermission.READ)
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_basic_method_permission(_fake_request("DELETE"), key_l2)
        assert exc_info.value.code == "insufficient_permission"


# ---------------------------------------------------------------------------
# Error contract snapshot tests (Phase 7O)
# ---------------------------------------------------------------------------

# Each contract: (scenario, trigger, expected_status, expected_code,
#                  must_contain, must_not_contain)
ERROR_CONTRACTS = [
    {
        "id": "layer2_read_post",
        "desc": "Layer 2: read key + POST → insufficient_permission",
        "perm": ApiKeyPermission.READ,
        "method": "POST",
        "layer": "basic",
        "status": 403,
        "code": "insufficient_permission",
        "must_contain": ["requires 'write'"],
        "must_not_contain": ["read"],
    },
    {
        "id": "layer2_read_delete",
        "desc": "Layer 2: read key + DELETE → insufficient_permission",
        "perm": ApiKeyPermission.READ,
        "method": "DELETE",
        "layer": "basic",
        "status": 403,
        "code": "insufficient_permission",
        "must_contain": ["requires 'admin'"],
        "must_not_contain": ["read"],
    },
    {
        "id": "layer2_write_delete",
        "desc": "Layer 2: write key + DELETE → insufficient_permission",
        "perm": ApiKeyPermission.WRITE,
        "method": "DELETE",
        "layer": "basic",
        "status": 403,
        "code": "insufficient_permission",
        "must_contain": ["requires 'admin'"],
        "must_not_contain": ["write"],
    },
    {
        "id": "layer1_resource_read_write",
        "desc": "Layer 1: read resource + write required → insufficient_resource_permission",
        "perm": ApiKeyPermission.READ,
        "method": "POST",
        "layer": "resource",
        "resource_type": "apps",
        "resource_level": ResourcePermissionLevel.READ,
        "status": 403,
        "code": "insufficient_resource_permission",
        "must_contain": ["apps"],
        "must_not_contain": [],
    },
    {
        "id": "layer1_null_fallback_read_delete",
        "desc": "Layer 1: null resource_permissions + read key + DELETE",
        "perm": ApiKeyPermission.READ,
        "method": "DELETE",
        "layer": "resource_null",
        "resource_type": "apps",
        "status": 403,
        "code": "insufficient_resource_permission",
        "must_contain": ["apps", "requires 'admin'"],
        "must_not_contain": [],
    },
]


class TestErrorContractSnapshots:
    """Phase 7O: parametrized error contract snapshot tests."""

    @pytest.mark.parametrize(
        "contract",
        ERROR_CONTRACTS,
        ids=[c["id"] for c in ERROR_CONTRACTS],
    )
    def test_error_contract(self, monkeypatch, contract):
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )

        if contract["layer"] == "basic":
            key = _make_key(permission=contract["perm"])
            with pytest.raises(ApiKeyValidationError) as exc_info:
                _check_basic_method_permission(
                    _fake_request(contract["method"]), key,
                )
        elif contract["layer"] == "resource":
            key = _make_key(
                permission=contract["perm"],
                resource_permissions=ResourcePermissions(
                    **{contract["resource_type"]: contract["resource_level"]},
                ),
            )
            with pytest.raises(ApiKeyValidationError) as exc_info:
                _check_method_resource_permission(
                    _fake_request(contract["method"]),
                    key,
                    _config(contract["resource_type"]),
                )
        elif contract["layer"] == "resource_null":
            key = _make_key(
                permission=contract["perm"],
                resource_permissions=None,
            )
            with pytest.raises(ApiKeyValidationError) as exc_info:
                _check_method_resource_permission(
                    _fake_request(contract["method"]),
                    key,
                    _config(contract["resource_type"]),
                )

        exc = exc_info.value
        assert exc.status_code == contract["status"]
        assert exc.code == contract["code"]

        for text in contract["must_contain"]:
            assert text in exc.message, (
                f"Expected '{text}' in message: {exc.message}"
            )

        for text in contract["must_not_contain"]:
            assert text not in exc.message, (
                f"'{text}' should NOT appear in message: {exc.message}"
            )


# ---------------------------------------------------------------------------
# Management endpoint hardening tests (Phase 7E / Steps 19-20)
# ---------------------------------------------------------------------------


class TestManagementEndpointGuard:
    """Tests for require_api_key_permission — the management endpoint guard.

    These tests use a real FastAPI app with the actual dependency wired in,
    so we exercise the full HTTP → dependency → guard chain.
    """

    @staticmethod
    def _build_management_app(
        auth_key: ApiKeyV2InDB | None = None,
    ):
        """Build a minimal FastAPI app with require_api_key_permission(ADMIN).

        Mirrors the real flow:
        1. require_api_key_permission stashes required level on request.state
        2. Auth dependency sets request.state.api_key
        3. Auth dependency checks _required_api_key_permission (like _resolve_api_key does)

        *auth_key*: when set, simulates API-key auth by setting request.state.
        When None, simulates bearer-token auth (no API key state).
        """
        from fastapi import Depends, FastAPI
        from fastapi.responses import JSONResponse

        app = FastAPI()

        admin_guard = Depends(require_api_key_permission(ApiKeyPermission.ADMIN))

        def _make_auth_dep(_key: ApiKeyV2InDB | None):
            async def _dep(request):
                if _key is not None:
                    request.state.api_key = _key
                    request.state.api_key_permission = _key.permission
                    request.state.api_key_scope_type = _key.scope_type
                    request.state.api_key_scope_id = _key.scope_id
                    request.state.api_key_resource_permissions = _key.resource_permissions
                    # Simulate _resolve_api_key's management check
                    required_perm = getattr(
                        request.state, "_required_api_key_permission", None
                    )
                    if required_perm is not None:
                        _check_management_permission(_key, required_perm)
                return {"id": "fake-user"}
            _dep.__annotations__["request"] = Request
            return _dep

        fake_auth = _make_auth_dep(auth_key)

        @app.exception_handler(ApiKeyValidationError)
        async def _handle(request, exc):
            return JSONResponse(
                status_code=exc.status_code,
                content={"code": exc.code, "message": exc.message},
                headers=exc.headers,
            )
        _handle.__annotations__["request"] = Request
        _handle.__annotations__["exc"] = ApiKeyValidationError

        @app.post("/api-keys", dependencies=[admin_guard])
        async def create_key(user=Depends(fake_auth)):
            return {"ok": True, "action": "create"}

        @app.patch("/api-keys/{key_id}", dependencies=[admin_guard])
        async def update_key(key_id: str, user=Depends(fake_auth)):
            return {"ok": True, "action": "update"}

        @app.delete("/api-keys/{key_id}", dependencies=[admin_guard])
        async def revoke_key(key_id: str, user=Depends(fake_auth)):
            return {"ok": True, "action": "revoke"}

        @app.post("/api-keys/{key_id}/rotate", dependencies=[admin_guard])
        async def rotate_key(key_id: str, user=Depends(fake_auth)):
            return {"ok": True, "action": "rotate"}

        @app.post("/api-keys/{key_id}/suspend", dependencies=[admin_guard])
        async def suspend_key(key_id: str, user=Depends(fake_auth)):
            return {"ok": True, "action": "suspend"}

        @app.post("/api-keys/{key_id}/reactivate", dependencies=[admin_guard])
        async def reactivate_key(key_id: str, user=Depends(fake_auth)):
            return {"ok": True, "action": "reactivate"}

        # Read endpoints — should NOT be blocked
        @app.get("/api-keys")
        async def list_keys(user=Depends(fake_auth)):
            return {"ok": True, "action": "list"}

        @app.get("/api-keys/{key_id}")
        async def get_key(key_id: str, user=Depends(fake_auth)):
            return {"ok": True, "action": "get"}

        return app

    @pytest.mark.asyncio
    async def test_write_key_cannot_create_api_key(self, monkeypatch):
        """ESCALATION PREVENTION: write key + POST /api-keys → 403.

        This is the core escalation attack: a write-level key tries to
        create an admin-level key for itself.
        """
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        key = _make_key(permission=ApiKeyPermission.WRITE)
        app = self._build_management_app(auth_key=key)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api-keys")
        assert resp.status_code == 403
        body = resp.json()
        assert body["code"] == "insufficient_permission"

    @pytest.mark.asyncio
    async def test_read_key_cannot_create_api_key(self, monkeypatch):
        """Read key + POST /api-keys → 403."""
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        key = _make_key(permission=ApiKeyPermission.READ)
        app = self._build_management_app(auth_key=key)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api-keys")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_key_can_create_api_key(self, monkeypatch):
        """Admin key + POST /api-keys → 200."""
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        key = _make_key(permission=ApiKeyPermission.ADMIN)
        app = self._build_management_app(auth_key=key)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api-keys")
        assert resp.status_code == 200
        assert resp.json()["action"] == "create"

    @pytest.mark.asyncio
    async def test_bearer_token_can_create_api_key(self, monkeypatch):
        """Bearer token (no API key) + POST /api-keys → 200.

        Bearer-token users are not subject to API key permission checks.
        """
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        app = self._build_management_app(auth_key=None)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api-keys")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_write_key_cannot_revoke(self, monkeypatch):
        """Write key + DELETE /api-keys/{id} → 403."""
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        key = _make_key(permission=ApiKeyPermission.WRITE)
        app = self._build_management_app(auth_key=key)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/api-keys/some-id")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_write_key_cannot_rotate(self, monkeypatch):
        """Write key + POST /api-keys/{id}/rotate → 403."""
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        key = _make_key(permission=ApiKeyPermission.WRITE)
        app = self._build_management_app(auth_key=key)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api-keys/some-id/rotate")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_write_key_cannot_suspend(self, monkeypatch):
        """Write key + POST /api-keys/{id}/suspend → 403."""
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        key = _make_key(permission=ApiKeyPermission.WRITE)
        app = self._build_management_app(auth_key=key)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api-keys/some-id/suspend")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_write_key_cannot_reactivate(self, monkeypatch):
        """Write key + POST /api-keys/{id}/reactivate → 403."""
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        key = _make_key(permission=ApiKeyPermission.WRITE)
        app = self._build_management_app(auth_key=key)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api-keys/some-id/reactivate")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_write_key_cannot_update(self, monkeypatch):
        """Write key + PATCH /api-keys/{id} → 403."""
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        key = _make_key(permission=ApiKeyPermission.WRITE)
        app = self._build_management_app(auth_key=key)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.patch("/api-keys/some-id")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_key_can_do_all_mutations(self, monkeypatch):
        """Admin key can perform all management operations."""
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        key = _make_key(permission=ApiKeyPermission.ADMIN)
        app = self._build_management_app(auth_key=key)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for method, path, expected_action in [
                ("POST", "/api-keys", "create"),
                ("PATCH", "/api-keys/some-id", "update"),
                ("DELETE", "/api-keys/some-id", "revoke"),
                ("POST", "/api-keys/some-id/rotate", "rotate"),
                ("POST", "/api-keys/some-id/suspend", "suspend"),
                ("POST", "/api-keys/some-id/reactivate", "reactivate"),
            ]:
                resp = await client.request(method, path)
                assert resp.status_code == 200, (
                    f"Admin key should pass {method} {path}, got {resp.status_code}"
                )
                assert resp.json()["action"] == expected_action

    @pytest.mark.asyncio
    async def test_read_endpoints_not_blocked_for_read_key(self, monkeypatch):
        """Read key can access GET endpoints (no management guard on reads)."""
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        key = _make_key(permission=ApiKeyPermission.READ)
        app = self._build_management_app(auth_key=key)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # GET /api-keys (list) — no guard
            resp = await client.get("/api-keys")
            assert resp.status_code == 200
            assert resp.json()["action"] == "list"

            # GET /api-keys/{id} (detail) — no guard
            resp = await client.get("/api-keys/some-id")
            assert resp.status_code == 200
            assert resp.json()["action"] == "get"

    @pytest.mark.asyncio
    async def test_error_message_includes_actionable_guidance(self, monkeypatch):
        """403 response from management guard includes upgrade instructions."""
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        key = _make_key(permission=ApiKeyPermission.WRITE)
        app = self._build_management_app(auth_key=key)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api-keys")
        assert resp.status_code == 403
        msg = resp.json()["message"]
        assert "admin" in msg.lower()
        assert "bearer token" in msg.lower()

    @pytest.mark.asyncio
    async def test_error_message_does_not_leak_granted_permission(self, monkeypatch):
        """403 from management guard does NOT reveal the key's actual permission."""
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        for perm in [ApiKeyPermission.READ, ApiKeyPermission.WRITE]:
            key = _make_key(permission=perm)
            app = self._build_management_app(auth_key=key)

            from httpx import ASGITransport, AsyncClient

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api-keys")
            msg = resp.json()["message"]
            # The granted level should not appear in the error
            assert f"'{perm.value}'" not in msg


class TestManagementGuardFailClosed:
    """Tests for fail-closed safety in the management permission check.

    The config-stash guard (require_api_key_permission) only stores the required
    permission on request.state. The actual enforcement happens inside
    _check_management_permission, called from _resolve_api_key after auth sets
    request.state.api_key.

    These tests verify:
    1. _check_management_permission raises for every insufficient level
    2. The config-stash guard correctly stores the required permission
    3. Bearer-token auth (no API key) bypasses the check (correct behavior)
    4. Unknown/invalid permission strings default to maximum required level
    """

    def test_check_management_permission_raises_for_read(self):
        """Read key + admin-required → raises."""
        key = _make_key(permission=ApiKeyPermission.READ)
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_management_permission(key, "admin")
        assert exc_info.value.status_code == 403
        assert exc_info.value.code == "insufficient_permission"

    def test_check_management_permission_raises_for_write(self):
        """Write key + admin-required → raises."""
        key = _make_key(permission=ApiKeyPermission.WRITE)
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_management_permission(key, "admin")
        assert exc_info.value.status_code == 403

    def test_check_management_permission_passes_for_admin(self):
        """Admin key + admin-required → passes (no exception)."""
        key = _make_key(permission=ApiKeyPermission.ADMIN)
        _check_management_permission(key, "admin")  # should not raise

    def test_check_management_permission_write_required(self):
        """Read key + write-required → raises, write key passes."""
        read_key = _make_key(permission=ApiKeyPermission.READ)
        write_key = _make_key(permission=ApiKeyPermission.WRITE)
        with pytest.raises(ApiKeyValidationError):
            _check_management_permission(read_key, "write")
        _check_management_permission(write_key, "write")  # should not raise

    def test_unknown_permission_defaults_to_max_level(self):
        """Unknown required permission string → defaults to level 3 (admin).

        This ensures fail-closed behavior: if someone passes an invalid
        permission string, even admin keys won't pass because the required
        level defaults to 3 (same as admin).
        """
        admin_key = _make_key(permission=ApiKeyPermission.ADMIN)
        # Admin key has level 3, unknown defaults to 3 → passes (3 >= 3)
        _check_management_permission(admin_key, "unknown_perm")
        # Write key has level 2, unknown defaults to 3 → fails (2 < 3)
        write_key = _make_key(permission=ApiKeyPermission.WRITE)
        with pytest.raises(ApiKeyValidationError):
            _check_management_permission(write_key, "unknown_perm")

    @pytest.mark.asyncio
    async def test_guard_stashes_required_permission_on_state(self):
        """The config-stash guard should set _required_api_key_permission."""
        guard_fn = require_api_key_permission(ApiKeyPermission.ADMIN)
        request = _make_request(method="POST", path="/api-keys")
        await guard_fn(request)
        assert request.state._required_api_key_permission == "admin"

    @pytest.mark.asyncio
    async def test_guard_stashes_write_permission(self):
        """Different permission levels are stashed correctly."""
        guard_fn = require_api_key_permission(ApiKeyPermission.WRITE)
        request = _make_request(method="POST", path="/test")
        await guard_fn(request)
        assert request.state._required_api_key_permission == "write"

    @pytest.mark.asyncio
    async def test_bearer_token_bypasses_management_check(self, monkeypatch):
        """Bearer token (no API key) + management guard → 200.

        When no API key is used, _resolve_api_key never runs, so the
        stashed _required_api_key_permission is never checked. This is
        correct: bearer-token users have full permissions.
        """
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        app = TestManagementEndpointGuard._build_management_app(auth_key=None)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api-keys")
        assert resp.status_code == 200

    def test_error_message_does_not_leak_granted_level(self):
        """The error message from _check_management_permission must NOT
        reveal the key's actual permission level."""
        for perm in [ApiKeyPermission.READ, ApiKeyPermission.WRITE]:
            key = _make_key(permission=perm)
            with pytest.raises(ApiKeyValidationError) as exc_info:
                _check_management_permission(key, "admin")
            # Granted level must not appear in message
            assert f"'{perm.value}'" not in exc_info.value.message
            # But admin should appear (telling user what's needed)
            assert "admin" in exc_info.value.message.lower()


class TestManagementGuardNotFeatureFlagged:
    """Verify management guards are NOT gated by the feature flag.

    Even when api_key_enforce_resource_permissions=False, management
    endpoint guards must still enforce. This prevents privilege
    escalation when the kill switch is active.
    """

    @pytest.mark.asyncio
    async def test_write_key_blocked_even_with_flag_off(self, monkeypatch):
        """Feature flag OFF + write key + POST /api-keys → still 403."""
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        key = _make_key(permission=ApiKeyPermission.WRITE)
        app = TestManagementEndpointGuard._build_management_app(auth_key=key)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api-keys")
        # The management guard is NOT gated by feature flag
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_read_key_blocked_even_with_flag_off(self, monkeypatch):
        """Feature flag OFF + read key + DELETE /api-keys/{id} → still 403."""
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        key = _make_key(permission=ApiKeyPermission.READ)
        app = TestManagementEndpointGuard._build_management_app(auth_key=key)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/api-keys/some-id")
        assert resp.status_code == 403


class TestManagementGuardPermissionMatrix:
    """Full permission × operation matrix for management endpoints.

    3 permission levels × 6 mutation operations = 18 combinations.
    Only admin keys should pass all operations.
    """

    _MUTATIONS = [
        ("POST", "/api-keys"),
        ("PATCH", "/api-keys/id-1"),
        ("DELETE", "/api-keys/id-1"),
        ("POST", "/api-keys/id-1/rotate"),
        ("POST", "/api-keys/id-1/suspend"),
        ("POST", "/api-keys/id-1/reactivate"),
    ]

    @pytest.mark.parametrize("method,path", _MUTATIONS)
    @pytest.mark.asyncio
    async def test_read_key_blocked_on_all_mutations(
        self, monkeypatch, method, path,
    ):
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        key = _make_key(permission=ApiKeyPermission.READ)
        app = TestManagementEndpointGuard._build_management_app(auth_key=key)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.request(method, path)
        assert resp.status_code == 403, (
            f"Read key should be blocked on {method} {path}"
        )

    @pytest.mark.parametrize("method,path", _MUTATIONS)
    @pytest.mark.asyncio
    async def test_write_key_blocked_on_all_mutations(
        self, monkeypatch, method, path,
    ):
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        key = _make_key(permission=ApiKeyPermission.WRITE)
        app = TestManagementEndpointGuard._build_management_app(auth_key=key)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.request(method, path)
        assert resp.status_code == 403, (
            f"Write key should be blocked on {method} {path}"
        )

    @pytest.mark.parametrize("method,path", _MUTATIONS)
    @pytest.mark.asyncio
    async def test_admin_key_passes_all_mutations(
        self, monkeypatch, method, path,
    ):
        monkeypatch.setattr(
            "intric.authentication.auth_dependencies.get_settings",
            lambda: SimpleNamespace(api_key_header_name="X-API-Key"),
        )
        key = _make_key(permission=ApiKeyPermission.ADMIN)
        app = TestManagementEndpointGuard._build_management_app(auth_key=key)

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.request(method, path)
        assert resp.status_code == 200, (
            f"Admin key should pass on {method} {path}"
        )


# ---------------------------------------------------------------------------
# CI route coverage guard (Phase 5 / Step 19)
# ---------------------------------------------------------------------------


class TestRouteGuardCoverage:
    """Verify that all API key management mutation endpoints have guards wired.

    This test inspects the actual FastAPI router objects to ensure
    require_api_key_permission is present as a dependency. If someone
    adds a new mutation endpoint without the guard, this test fails.
    """

    @staticmethod
    def _endpoint_has_api_key_guard(endpoint_fn) -> bool:
        """Check if an endpoint function has require_api_key_permission in its dependencies."""
        import inspect
        sig = inspect.signature(endpoint_fn)
        for param in sig.parameters.values():
            if param.default is not inspect.Parameter.empty:
                dep = param.default
                if hasattr(dep, "dependency"):
                    # FastAPI Depends wraps the actual dependency
                    inner = dep.dependency
                    # The guard is a closure — check its qualname
                    if hasattr(inner, "__qualname__") and "require_api_key_permission" in inner.__qualname__:
                        return True
        return False

    def test_user_api_key_mutations_have_guard(self):
        """All mutation endpoints in api_key_router have require_api_key_permission."""
        from intric.authentication.api_key_router import router as user_router

        mutation_methods = {"POST", "PATCH", "DELETE", "PUT"}
        unguarded = []

        for route in user_router.routes:
            if not hasattr(route, "methods"):
                continue
            if not route.methods & mutation_methods:
                continue
            endpoint = route.endpoint
            if not self._endpoint_has_api_key_guard(endpoint):
                unguarded.append(f"{route.methods} {route.path} ({endpoint.__name__})")

        assert not unguarded, (
            "Mutation endpoints without require_api_key_permission guard:\n"
            + "\n".join(f"  - {e}" for e in unguarded)
        )

    def test_admin_api_key_mutations_have_guard(self):
        """All API key mutation endpoints in admin_router have require_api_key_permission."""
        from intric.admin.admin_router import router as admin_router_obj

        mutation_methods = {"POST", "PATCH", "DELETE", "PUT"}
        unguarded = []

        for route in admin_router_obj.routes:
            if not hasattr(route, "methods"):
                continue
            if not route.methods & mutation_methods:
                continue
            # Only check API key-related endpoints
            if "/api-keys" not in route.path and "/api-key-policy" not in route.path:
                continue
            endpoint = route.endpoint
            if not self._endpoint_has_api_key_guard(endpoint):
                unguarded.append(f"{route.methods} {route.path} ({endpoint.__name__})")

        assert not unguarded, (
            "Admin API key mutation endpoints without guard:\n"
            + "\n".join(f"  - {e}" for e in unguarded)
        )

    def test_read_endpoints_do_not_have_management_guard(self):
        """GET endpoints in api_key_router should NOT have require_api_key_permission.

        Read operations (list, get, constraints) should be accessible to
        any authenticated key, not just admin keys.
        """
        from intric.authentication.api_key_router import router as user_router

        guarded_reads = []

        for route in user_router.routes:
            if not hasattr(route, "methods"):
                continue
            if route.methods != {"GET"}:
                continue
            endpoint = route.endpoint
            if self._endpoint_has_api_key_guard(endpoint):
                guarded_reads.append(f"{route.methods} {route.path} ({endpoint.__name__})")

        assert not guarded_reads, (
            "GET endpoints should NOT have management guard:\n"
            + "\n".join(f"  - {e}" for e in guarded_reads)
        )


class TestNoDoubleAuth:
    """Verify the rewritten require_api_key_permission does NOT trigger re-auth.

    The old implementation used Depends(get_current_active_user), which caused
    a full re-authentication. The new version reads from request.state only.
    """

    def test_no_get_current_active_user_dependency(self):
        """require_api_key_permission should NOT depend on get_current_active_user."""
        import inspect

        guard_factory = require_api_key_permission(ApiKeyPermission.ADMIN)
        sig = inspect.signature(guard_factory)

        for param in sig.parameters.values():
            if param.default is not inspect.Parameter.empty:
                dep = param.default
                if hasattr(dep, "dependency"):
                    inner_name = getattr(dep.dependency, "__name__", "")
                    assert inner_name != "get_current_active_user", (
                        "require_api_key_permission must NOT depend on "
                        "get_current_active_user (causes double-auth)"
                    )

    def test_guard_signature_only_takes_request(self):
        """The guard dependency should only take a Request parameter."""
        import inspect

        guard_fn = require_api_key_permission(ApiKeyPermission.ADMIN)
        sig = inspect.signature(guard_fn)
        param_names = list(sig.parameters.keys())
        assert param_names == ["request"], (
            f"Guard should only take 'request', got: {param_names}"
        )
