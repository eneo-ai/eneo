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
    ASSISTANTS_READ_OVERRIDES,
    KNOWLEDGE_READ_OVERRIDES,
    _raise_api_key_http_error,
    require_resource_permission_for_method,
)
from intric.authentication.api_key_resolver import (
    ApiKeyValidationError,
    check_resource_permission,
)
from intric.authentication.auth_models import (
    ApiKeyHashVersion,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
    ResourcePermissionLevel,
    ResourcePermissions,
)
from starlette.requests import Request

from intric.users.user_service import UserService, _check_method_resource_permission


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_key(**overrides: object) -> ApiKeyV2InDB:
    base: dict[str, Any] = {
        "id": uuid4(),
        "key_prefix": ApiKeyType.SK.value,
        "key_suffix": "abcd1234",
        "name": "Test Key",
        "description": None,
        "key_type": ApiKeyType.SK,
        "permission": ApiKeyPermission.WRITE,
        "scope_type": ApiKeyScopeType.TENANT,
        "scope_id": None,
        "allowed_origins": None,
        "allowed_ips": None,
        "state": ApiKeyState.ACTIVE,
        "expires_at": None,
        "last_used_at": None,
        "revoked_at": None,
        "revoked_reason_code": None,
        "revoked_reason_text": None,
        "suspended_at": None,
        "suspended_reason_code": None,
        "suspended_reason_text": None,
        "rotation_grace_until": None,
        "rate_limit": None,
        "created_at": None,
        "updated_at": None,
        "rotated_from_key_id": None,
        "tenant_id": uuid4(),
        "owner_user_id": uuid4(),
        "created_by_user_id": None,
        "created_by_key_id": None,
        "delegation_depth": 0,
        "key_hash": "hash",
        "hash_version": ApiKeyHashVersion.HMAC_SHA256.value,
        "resource_permissions": None,
    }
    base.update(overrides)
    return ApiKeyV2InDB(**base)


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

    def test_read_key_denied_on_post_assistants_sessions(self, monkeypatch):
        """10. Read key denied on POST ask_assistant (requires write)."""
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
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_method_resource_permission(
                request, key,
                _config("assistants", read_override_endpoints=ASSISTANTS_READ_OVERRIDES),
            )
        assert exc_info.value.status_code == 403

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

    def test_no_resource_permissions_passes(self, monkeypatch):
        """12. Key with resource_permissions=None passes (backward compat)."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(resource_permissions=None)
        for method in ("GET", "POST", "DELETE"):
            request = _fake_request(method)
            _check_method_resource_permission(request, key, _config("apps"))


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

        assistant_names = self._collect_endpoint_names(assistants_router)
        group_names = self._collect_endpoint_names(groups_router)

        for name in ASSISTANTS_READ_OVERRIDES:
            assert name in assistant_names, (
                f"ASSISTANTS_READ_OVERRIDES contains '{name}' but no route has that endpoint name"
            )

        for name in KNOWLEDGE_READ_OVERRIDES:
            assert name in group_names, (
                f"KNOWLEDGE_READ_OVERRIDES contains '{name}' but no route has that endpoint name"
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
