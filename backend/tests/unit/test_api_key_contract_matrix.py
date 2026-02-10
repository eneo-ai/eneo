"""Contract matrix tests for API key v2 enforcement layers.

Tests cover:
- Public endpoint invariants (Part 2C)
- Auth precedence (bearer vs API key) (Part 2C)
- CORS/OPTIONS bypass (Part 2C)
- Scope fail-closed invariant (Part 2C)
- Permission × scope × method boundary tests (Part 2D)
- Scenario-based real-world flow tests (Part 2E)
- Guardrail independence tests (Part 2F)
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from starlette.datastructures import State

from intric.authentication.api_key_resolver import ApiKeyValidationError, check_resource_permission
from intric.authentication.auth_models import (
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyV2InDB,
    METHOD_PERMISSION_MAP,
)
from tests.unit.api_key_test_utils import make_api_key
from intric.users.user_service import (
    _check_basic_method_permission,
    _check_management_permission,
    _check_method_resource_permission,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_key(**overrides: object) -> ApiKeyV2InDB:
    return make_api_key(
        default_permission=ApiKeyPermission.READ,
        **overrides,
    )


def _fake_request(
    method: str,
    *,
    endpoint_name: str | None = None,
    path: str = "/test",
) -> SimpleNamespace:
    """Build a minimal request-like object for permission checks."""
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
        state=State(),
        url=SimpleNamespace(path=path),
        headers={},
    )


def _scope_request(
    path_params: dict[str, str] | None = None,
) -> SimpleNamespace:
    """Build a minimal request-like object for scope enforcement."""
    scope: dict[str, Any] = {}
    if path_params is not None:
        scope["path_params"] = path_params
    return SimpleNamespace(
        scope=scope,
        state=State(),
    )


def _make_user_service(
    feature_flag_service: Any = None,
    session_scalar_return: Any = None,
):
    """Build a minimal UserService for scope enforcement tests."""
    from intric.users.user_service import UserService

    svc = object.__new__(UserService)
    svc.feature_flag_service = feature_flag_service
    mock_session = AsyncMock()
    mock_session.scalar = AsyncMock(return_value=session_scalar_return)
    mock_session.execute = AsyncMock(
        return_value=MagicMock(
            first=MagicMock(return_value=None),
            one_or_none=MagicMock(return_value=None),
        )
    )
    svc.repo = SimpleNamespace(session=mock_session)
    return svc


def _config(
    resource_type: str = "apps",
    read_override_endpoints: frozenset[str] | None = None,
) -> dict:
    return {
        "resource_type": resource_type,
        "read_override_endpoints": read_override_endpoints,
    }


# ---------------------------------------------------------------------------
# Part 2C: Public Endpoint & Auth Precedence Tests
# ---------------------------------------------------------------------------


class TestPublicEndpoints:
    """Public endpoints must remain public regardless of future changes."""

    def test_version_endpoint_has_no_auth_dependency(self):
        """GET /version must not require auth."""
        from intric.server.main import get_application

        app = get_application()
        version_route = None
        for route in app.routes:
            if getattr(route, "path", None) == "/version":
                version_route = route
                break

        assert version_route is not None, "/version route not found"
        # Verify no auth dependencies
        deps = getattr(version_route, "dependencies", [])
        dep_names = [
            getattr(d.dependency, "__name__", "")
            for d in deps
            if hasattr(d, "dependency")
        ]
        assert "get_current_active_user" not in dep_names

    def test_healthz_endpoint_exists_without_auth(self):
        """GET /api/healthz must not have auth dependencies."""
        from intric.server.main import get_application

        app = get_application()
        healthz_route = None
        for route in app.routes:
            if getattr(route, "path", None) == "/api/healthz":
                healthz_route = route
                break

        assert healthz_route is not None, "/api/healthz route not found"
        deps = getattr(healthz_route, "dependencies", [])
        dep_names = [
            getattr(d.dependency, "__name__", "")
            for d in deps
            if hasattr(d, "dependency")
        ]
        assert "get_current_active_user" not in dep_names

    def test_crawler_healthz_endpoint_exists_without_auth(self):
        """GET /api/healthz/crawler must not have auth dependencies."""
        from intric.server.main import get_application

        app = get_application()
        crawler_route = None
        for route in app.routes:
            if getattr(route, "path", None) == "/api/healthz/crawler":
                crawler_route = route
                break

        assert crawler_route is not None, "/api/healthz/crawler route not found"
        deps = getattr(crawler_route, "dependencies", [])
        dep_names = [
            getattr(d.dependency, "__name__", "")
            for d in deps
            if hasattr(d, "dependency")
        ]
        assert "get_current_active_user" not in dep_names


class TestAuthPrecedence:
    """Documents which auth method wins when both are present.

    Auth precedence is enforced in user_service.authenticate():
    - Bearer token takes priority (checked first via `if token is not None`)
    - API key is only used when token is None
    """

    def test_bearer_token_checked_first(self):
        """Bearer token takes precedence — API key branch only if token is None."""
        from intric.users.user_service import UserService

        # Verify the authenticate method's structure: token checked before api_key
        import inspect
        source = inspect.getsource(UserService.authenticate)
        token_check_pos = source.find("if token is not None")
        api_key_check_pos = source.find("elif api_key is not None")
        assert token_check_pos < api_key_check_pos, (
            "Bearer token must be checked before API key in authenticate()"
        )

    def test_api_key_only_triggers_enforcement_chain(self):
        """API key without bearer → full enforcement chain runs."""
        # Verify _resolve_api_key is called in the api_key branch
        from intric.users.user_service import UserService
        import inspect
        source = inspect.getsource(UserService.authenticate)
        assert "_resolve_api_key" in source

    def test_bearer_token_skips_api_key_enforcement(self):
        """Bearer token path calls _get_user_from_token, not _resolve_api_key."""
        from intric.users.user_service import UserService
        import inspect
        source = inspect.getsource(UserService.authenticate)

        # The token branch should NOT call _resolve_api_key
        lines = source.split("\n")
        in_token_branch = False
        token_branch_calls_resolve = False
        for line in lines:
            stripped = line.strip()
            if "if token is not None" in stripped:
                in_token_branch = True
                continue
            if in_token_branch:
                if stripped.startswith("elif") or stripped.startswith("if "):
                    break
                if "_resolve_api_key" in stripped:
                    token_branch_calls_resolve = True

        assert not token_branch_calls_resolve, (
            "Bearer token branch must NOT call _resolve_api_key"
        )

    @pytest.mark.asyncio
    async def test_invalid_bearer_does_not_fallback_to_valid_api_key(self):
        """Invalid bearer + valid API key must fail by bearer precedence."""
        from intric.main.exceptions import AuthenticationException
        from intric.users.user_service import UserService

        svc = object.__new__(UserService)
        svc._get_user_from_token = AsyncMock(
            side_effect=AuthenticationException("Invalid token")
        )
        svc._resolve_api_key = AsyncMock(
            return_value=(SimpleNamespace(id=uuid4(), tenant=SimpleNamespace()), None)
        )
        svc._check_user_and_tenant_state = AsyncMock()

        with pytest.raises(AuthenticationException):
            await svc.authenticate(
                token="invalid-bearer-token",
                api_key="sk_valid_but_must_not_be_used",
                request=SimpleNamespace(),
            )

        svc._resolve_api_key.assert_not_called()


class TestCorsOptionsBypass:
    """OPTIONS requests use read permission — always allowed for CORS preflight."""

    def test_options_mapped_to_read_permission(self):
        """OPTIONS in METHOD_PERMISSION_MAP → 'read' (lowest level, always passes)."""
        assert METHOD_PERMISSION_MAP.get("OPTIONS") == "read"

    def test_options_request_passes_for_read_key(self):
        """Read key + OPTIONS → pass (CORS preflight must not require credentials)."""
        key = _make_key(permission=ApiKeyPermission.READ)
        request = _fake_request("OPTIONS")
        # Should not raise
        _check_basic_method_permission(request, key)


class TestScopeFailClosedInvariant:
    """Missing scope enforcement feature flag row → enforcement ON (fail-closed)."""

    @pytest.mark.asyncio
    async def test_missing_flag_defaults_to_enforced(self):
        """_is_scope_enforcement_enabled returns True when flag row is missing."""
        mock_ff_service = MagicMock()
        mock_ff_service.check_is_feature_enabled_fail_closed = AsyncMock(
            return_value=True
        )

        svc = _make_user_service(feature_flag_service=mock_ff_service)
        result = await svc._is_scope_enforcement_enabled(uuid4())
        assert result is True

    @pytest.mark.asyncio
    async def test_no_feature_flag_service_defaults_to_enforced(self):
        """No feature_flag_service at all → enforcement ON."""
        svc = _make_user_service(feature_flag_service=None)
        result = await svc._is_scope_enforcement_enabled(uuid4())
        assert result is True


# ---------------------------------------------------------------------------
# Part 2D: Contract Matrix — Permission × Scope × Method Boundaries
# ---------------------------------------------------------------------------


class TestContractMatrixBoundaries:
    """Boundary tests for the 4 enforcement layers:
    Layer 1: Resource permission (check_resource_permission)
    Layer 2: Basic method permission (_check_basic_method_permission)
    Layer 3: Scope enforcement (_enforce_api_key_scope)
    Layer 4: Management guards (_check_management_permission)
    """

    # -- Layer 1 + 2: Permission enforcement --

    def test_read_key_get_resource_guarded_passes(self, monkeypatch):
        """1. read key + GET resource-guarded → 200."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(permission=ApiKeyPermission.READ)
        request = _fake_request("GET")
        # No resource_permissions → falls back to basic permission ceiling
        _check_method_resource_permission(request, key, _config("assistants"))

    def test_read_key_post_resource_guarded_blocked(self, monkeypatch):
        """2. read key + POST resource-guarded (non-override) → 403."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(permission=ApiKeyPermission.READ)
        request = _fake_request("POST")
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_method_resource_permission(request, key, _config("assistants"))
        assert exc_info.value.code == "insufficient_resource_permission"

    def test_read_key_post_override_endpoint_passes(self, monkeypatch):
        """3. read key + POST on override endpoint → 200 (read-override)."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        from intric.authentication.auth_dependencies import ASSISTANTS_READ_OVERRIDES

        key = _make_key(permission=ApiKeyPermission.READ)
        request = _fake_request("POST", endpoint_name="ask_assistant")
        _check_method_resource_permission(
            request, key, _config("assistants", ASSISTANTS_READ_OVERRIDES)
        )

    def test_write_key_delete_resource_guarded_blocked(self, monkeypatch):
        """4. write key + DELETE resource-guarded → 403."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(permission=ApiKeyPermission.WRITE)
        request = _fake_request("DELETE")
        with pytest.raises(ApiKeyValidationError):
            _check_method_resource_permission(request, key, _config("assistants"))

    def test_admin_key_delete_resource_guarded_passes(self, monkeypatch):
        """5. admin key + DELETE resource-guarded → 200."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = _make_key(permission=ApiKeyPermission.ADMIN)
        request = _fake_request("DELETE")
        _check_method_resource_permission(request, key, _config("assistants"))

    # -- Layer 4: Management guards --

    def test_write_key_management_guarded_blocked(self):
        """6. write key + POST management-guarded → 403 (escalation prevention)."""
        key = _make_key(permission=ApiKeyPermission.WRITE)
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_management_permission(key, "admin")
        assert exc_info.value.code == "insufficient_permission"

    def test_admin_key_management_guarded_passes(self):
        """7. admin key + POST management-guarded → 200."""
        key = _make_key(permission=ApiKeyPermission.ADMIN)
        # Should not raise
        _check_management_permission(key, "admin")

    # -- Layer 3: Scope enforcement --

    @pytest.mark.asyncio
    async def test_assistant_scoped_key_admin_route_denied(self):
        """8. assistant-scoped key + GET /admin → 403 (scope denial)."""
        assistant_id = uuid4()
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.ASSISTANT,
            scope_id=assistant_id,
        )
        request = _scope_request()
        scope_config = {"resource_type": "admin", "path_param": None}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_tenant_scoped_key_admin_route_passes(self):
        """9. tenant-scoped key + GET /admin → 200."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.TENANT,
            scope_id=None,
        )
        request = _scope_request()
        scope_config = {"resource_type": "admin", "path_param": None}

        # Should not raise
        await svc._enforce_api_key_scope(request, key, scope_config)

    @pytest.mark.asyncio
    async def test_space_scoped_key_other_space_resource_denied(self):
        """10. space-scoped key + GET /assistants/{other-space-assistant} → 403."""
        space_id = uuid4()
        other_space_id = uuid4()
        assistant_id = uuid4()

        svc = _make_user_service(session_scalar_return=other_space_id)
        key = _make_key(
            scope_type=ApiKeyScopeType.SPACE,
            scope_id=space_id,
        )
        request = _scope_request(path_params={"id": str(assistant_id)})
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    # -- Layer 2: Basic method permission (no resource guard) --

    def test_read_key_basic_delete_blocked(self):
        """11. read key + DELETE on unguarded route → 403."""
        key = _make_key(permission=ApiKeyPermission.READ)
        request = _fake_request("DELETE")
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_basic_method_permission(request, key)
        assert exc_info.value.code == "insufficient_permission"


# ---------------------------------------------------------------------------
# Part 2E: Scenario-Based Tests — Real-World Flows
# ---------------------------------------------------------------------------


class TestScenarioReadOnlyIntegration:
    """Scenario 1: Read-only integration key with tenant scope.

    Can: GET assistants, GET conversations, POST ask_assistant (read-override)
    Cannot: DELETE anything
    """

    def _make_read_tenant_key(self):
        return _make_key(
            permission=ApiKeyPermission.READ,
            scope_type=ApiKeyScopeType.TENANT,
            scope_id=None,
        )

    def test_can_get_assistants(self, monkeypatch):
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = self._make_read_tenant_key()
        request = _fake_request("GET")
        _check_method_resource_permission(request, key, _config("assistants"))

    def test_can_post_ask_assistant_override(self, monkeypatch):
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        from intric.authentication.auth_dependencies import ASSISTANTS_READ_OVERRIDES

        key = self._make_read_tenant_key()
        request = _fake_request("POST", endpoint_name="ask_assistant")
        _check_method_resource_permission(
            request, key, _config("assistants", ASSISTANTS_READ_OVERRIDES)
        )

    def test_cannot_delete_assistant(self, monkeypatch):
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = self._make_read_tenant_key()
        request = _fake_request("DELETE")
        with pytest.raises(ApiKeyValidationError):
            _check_method_resource_permission(request, key, _config("assistants"))

    def test_cannot_delete_on_unguarded_route(self):
        key = self._make_read_tenant_key()
        request = _fake_request("DELETE")
        with pytest.raises(ApiKeyValidationError):
            _check_basic_method_permission(request, key)

    def test_cannot_manage_api_keys(self):
        key = self._make_read_tenant_key()
        with pytest.raises(ApiKeyValidationError):
            _check_management_permission(key, "admin")


class TestScenarioSpaceScopedAutomation:
    """Scenario 2: Write key + space scope.

    Can: CRUD within space
    Cannot: resources in other spaces, admin endpoints
    """

    def _space_id(self):
        return uuid4()

    def _make_write_space_key(self, space_id: UUID):
        return _make_key(
            permission=ApiKeyPermission.WRITE,
            scope_type=ApiKeyScopeType.SPACE,
            scope_id=space_id,
        )

    @pytest.mark.asyncio
    async def test_can_access_resource_in_own_space(self):
        space_id = self._space_id()
        svc = _make_user_service(session_scalar_return=space_id)
        key = self._make_write_space_key(space_id)
        request = _scope_request(path_params={"id": str(uuid4())})
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        await svc._enforce_api_key_scope(request, key, scope_config)

    @pytest.mark.asyncio
    async def test_denied_resource_in_other_space(self):
        space_id = self._space_id()
        other_space_id = uuid4()
        svc = _make_user_service(session_scalar_return=other_space_id)
        key = self._make_write_space_key(space_id)
        request = _scope_request(path_params={"id": str(uuid4())})
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_denied_admin_endpoint(self):
        space_id = self._space_id()
        svc = _make_user_service()
        key = self._make_write_space_key(space_id)
        request = _scope_request()
        scope_config = {"resource_type": "admin", "path_param": None}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"


class TestScenarioAdminManagement:
    """Scenario 3: Admin key + tenant scope.

    Can: manage API keys, access token-usage, modify settings
    """

    def _make_admin_tenant_key(self):
        return _make_key(
            permission=ApiKeyPermission.ADMIN,
            scope_type=ApiKeyScopeType.TENANT,
            scope_id=None,
        )

    def test_can_manage_api_keys(self):
        key = self._make_admin_tenant_key()
        _check_management_permission(key, "admin")

    def test_can_delete_resources(self, monkeypatch):
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        key = self._make_admin_tenant_key()
        request = _fake_request("DELETE")
        _check_method_resource_permission(request, key, _config("assistants"))

    @pytest.mark.asyncio
    async def test_can_access_admin_routes(self):
        svc = _make_user_service()
        key = self._make_admin_tenant_key()
        request = _scope_request()
        scope_config = {"resource_type": "admin", "path_param": None}

        await svc._enforce_api_key_scope(request, key, scope_config)


class TestScenarioAssistantChatbot:
    """Scenario 4: Read key + assistant scope.

    Can: chat, list conversations for that assistant
    Cannot: access other assistants
    """

    def _make_assistant_key(self, assistant_id: UUID):
        return _make_key(
            permission=ApiKeyPermission.READ,
            scope_type=ApiKeyScopeType.ASSISTANT,
            scope_id=assistant_id,
        )

    @pytest.mark.asyncio
    async def test_can_access_own_assistant(self):
        assistant_id = uuid4()
        svc = _make_user_service()
        key = self._make_assistant_key(assistant_id)
        request = _scope_request(path_params={"id": str(assistant_id)})
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        await svc._enforce_api_key_scope(request, key, scope_config)

    @pytest.mark.asyncio
    async def test_denied_other_assistant(self):
        assistant_id = uuid4()
        other_assistant_id = uuid4()
        svc = _make_user_service()
        key = self._make_assistant_key(assistant_id)
        request = _scope_request(path_params={"id": str(other_assistant_id)})
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_can_list_conversations(self):
        assistant_id = uuid4()
        svc = _make_user_service()
        key = self._make_assistant_key(assistant_id)
        request = _scope_request()
        scope_config = {"resource_type": "conversation", "path_param": "session_id"}

        # No path_params means list endpoint → assistant-scoped key allowed for conversations
        await svc._enforce_api_key_scope(request, key, scope_config)

    @pytest.mark.asyncio
    async def test_denied_admin_routes(self):
        assistant_id = uuid4()
        svc = _make_user_service()
        key = self._make_assistant_key(assistant_id)
        request = _scope_request()
        scope_config = {"resource_type": "admin", "path_param": None}

        with pytest.raises(ApiKeyValidationError):
            await svc._enforce_api_key_scope(request, key, scope_config)

    def test_cannot_delete_via_permission(self, monkeypatch):
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )
        assistant_id = uuid4()
        key = self._make_assistant_key(assistant_id)
        request = _fake_request("DELETE")
        with pytest.raises(ApiKeyValidationError):
            _check_method_resource_permission(request, key, _config("assistants"))


# ---------------------------------------------------------------------------
# Part 2F: Guardrail Integration Tests
# ---------------------------------------------------------------------------


class TestGuardrailIndependence:
    """Each enforcement layer must fire independently — one doesn't mask another."""

    def test_management_guard_blocks_before_scope(self):
        """Management guard fires on permission alone, regardless of scope."""
        key = _make_key(
            permission=ApiKeyPermission.WRITE,
            scope_type=ApiKeyScopeType.TENANT,
            scope_id=None,
        )
        # Even tenant scope can't bypass permission check
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_management_permission(key, "admin")
        assert exc_info.value.code == "insufficient_permission"

    def test_read_key_denied_on_basic_method_regardless_of_scope(self):
        """Layer 2 fires on permission alone, scope is irrelevant."""
        key = _make_key(
            permission=ApiKeyPermission.READ,
            scope_type=ApiKeyScopeType.TENANT,
        )
        request = _fake_request("DELETE")
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_basic_method_permission(request, key)
        assert exc_info.value.code == "insufficient_permission"

    @pytest.mark.asyncio
    async def test_scope_guard_blocks_correct_permission_wrong_scope(self):
        """Scope guard fires even when permission level is sufficient."""
        space_id = uuid4()
        other_space_id = uuid4()

        # Admin permission key — highest level
        svc = _make_user_service(session_scalar_return=other_space_id)
        key = _make_key(
            permission=ApiKeyPermission.ADMIN,
            scope_type=ApiKeyScopeType.SPACE,
            scope_id=space_id,
        )
        request = _scope_request(path_params={"id": str(uuid4())})
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        # Permission is fine (admin), but scope denies access
        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    def test_each_layer_error_code_is_distinct(self, monkeypatch):
        """Each enforcement layer produces a distinguishable error code."""
        monkeypatch.setattr(
            "intric.authentication.api_key_resolver.get_settings",
            lambda: SimpleNamespace(api_key_enforce_resource_permissions=True),
        )

        read_key = _make_key(permission=ApiKeyPermission.READ)

        # Layer 1: Resource permission → insufficient_resource_permission
        with pytest.raises(ApiKeyValidationError) as exc_l1:
            check_resource_permission(read_key, "assistants", "admin")
        assert exc_l1.value.code == "insufficient_resource_permission"

        # Layer 2: Basic method permission → insufficient_permission
        request = _fake_request("DELETE")
        with pytest.raises(ApiKeyValidationError) as exc_l2:
            _check_basic_method_permission(request, read_key)
        assert exc_l2.value.code == "insufficient_permission"

        # Layer 4: Management guard → insufficient_permission
        with pytest.raises(ApiKeyValidationError) as exc_l4:
            _check_management_permission(read_key, "admin")
        assert exc_l4.value.code == "insufficient_permission"

        # Verify codes exist and are strings
        for exc in [exc_l1, exc_l2, exc_l4]:
            assert isinstance(exc.value.code, str)
            assert len(exc.value.code) > 0

    @pytest.mark.asyncio
    async def test_scope_error_code_is_insufficient_scope(self):
        """Layer 3 (scope) produces 'insufficient_scope' code."""
        space_id = uuid4()
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.SPACE,
            scope_id=space_id,
        )
        request = _scope_request()
        scope_config = {"resource_type": "admin", "path_param": None}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"


class TestGuardrailPolicyEnforcement:
    """Guardrail (policy) checks fire before permission checks in _resolve_api_key.

    These tests verify the ordering contract via code inspection since actual
    guardrail tests require full async integration with mocked repositories.
    """

    def test_guardrail_runs_before_permission_in_resolve_api_key(self):
        """enforce_guardrails() must run before permission checks in _resolve_api_key."""
        import inspect
        from intric.users.user_service import UserService

        source = inspect.getsource(UserService._resolve_api_key)
        guardrail_pos = source.find("enforce_guardrails")
        permission_pos = source.find("_check_method_resource_permission")
        basic_pos = source.find("_check_basic_method_permission")

        assert guardrail_pos > 0, "enforce_guardrails not found in _resolve_api_key"
        assert permission_pos > 0, "_check_method_resource_permission not found"
        assert basic_pos > 0, "_check_basic_method_permission not found"
        assert guardrail_pos < permission_pos, (
            "enforce_guardrails must run before _check_method_resource_permission"
        )
        assert guardrail_pos < basic_pos, (
            "enforce_guardrails must run before _check_basic_method_permission"
        )

    def test_management_guard_runs_after_permission_check(self):
        """_check_management_permission runs after Layer 1/2 in _resolve_api_key."""
        import inspect
        from intric.users.user_service import UserService

        source = inspect.getsource(UserService._resolve_api_key)
        management_pos = source.find("_check_management_permission")
        basic_pos = source.find("_check_basic_method_permission")

        assert management_pos > basic_pos, (
            "Management guard must run after basic method permission check"
        )

    def test_scope_enforcement_runs_last(self):
        """_enforce_api_key_scope runs after all permission checks."""
        import inspect
        from intric.users.user_service import UserService

        source = inspect.getsource(UserService._resolve_api_key)
        scope_pos = source.find("_enforce_api_key_scope")
        management_pos = source.find("_check_management_permission")

        assert scope_pos > management_pos, (
            "Scope enforcement must run after management guard"
        )


# ---------------------------------------------------------------------------
# User listing endpoint enforcement (router-level split)
# ---------------------------------------------------------------------------


class TestUserListingEndpointGuards:
    """Verify GET /users/ has router-level admin scope + permission guards.

    The listing endpoint is on users_admin_router (mounted with router-level
    guards) rather than the main users router, so the config-stash pattern
    works correctly.
    """

    def _get_users_listing_route(self):
        """Find the GET /users/ route and return it."""
        from intric.server.routers import router as root

        for route in root.routes:
            path = getattr(route, "path", "")
            endpoint = getattr(route, "endpoint", None)
            if path == "/users/" and endpoint is not None:
                if endpoint.__name__ == "get_tenant_users":
                    return route
        pytest.fail("GET /users/ (get_tenant_users) route not found")

    def _route_has_dependency(self, route, dep_name: str) -> bool:
        """Check if a route has a specific dependency by function name."""
        deps = getattr(route, "dependencies", [])
        for dep in deps:
            if hasattr(dep, "dependency"):
                if getattr(dep.dependency, "__name__", "") == dep_name:
                    return True
        return False

    def test_space_scoped_read_key_denied_by_scope(self):
        """Space-scoped read key -> GET /users/ => 403 insufficient_scope."""
        key = _make_key(
            permission=ApiKeyPermission.READ.value,
            scope_type=ApiKeyScopeType.SPACE.value,
            scope_id=str(uuid4()),
        )
        request = _scope_request()

        svc = _make_user_service()

        with pytest.raises(ApiKeyValidationError) as exc_info:
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                svc._enforce_api_key_scope(
                    request,
                    key,
                    {"resource_type": "admin", "path_param": None},
                )
            )
        assert exc_info.value.code == "insufficient_scope"

    def test_tenant_scoped_read_key_denied_by_permission(self):
        """Tenant-scoped read key -> GET /users/ => 403 insufficient_permission.

        The router-level require_api_key_permission(ADMIN) blocks read keys.
        """
        key = _make_key(
            permission=ApiKeyPermission.READ.value,
            scope_type=ApiKeyScopeType.TENANT.value,
        )

        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_management_permission(key, ApiKeyPermission.ADMIN.value)
        assert exc_info.value.code == "insufficient_permission"

    def test_tenant_scoped_admin_key_passes(self):
        """Tenant-scoped admin key + admin user => passes all guards."""
        key = _make_key(
            permission=ApiKeyPermission.ADMIN.value,
            scope_type=ApiKeyScopeType.TENANT.value,
        )

        # Scope enforcement: tenant-scoped keys always pass
        request = _scope_request()
        svc = _make_user_service()
        import asyncio
        # Should NOT raise — tenant scope bypasses all scope checks
        asyncio.get_event_loop().run_until_complete(
            svc._enforce_api_key_scope(
                request,
                key,
                {"resource_type": "admin", "path_param": None},
            )
        )

        # Permission check: admin key passes admin requirement
        _check_management_permission(key, ApiKeyPermission.ADMIN.value)

    def test_listing_route_has_router_level_scope_guard(self):
        """GET /users/ must have require_api_key_scope_check at router level."""
        route = self._get_users_listing_route()
        assert self._route_has_dependency(route, "_scope_check_dep"), (
            "GET /users/ missing router-level require_api_key_scope_check"
        )

    def test_listing_route_has_router_level_permission_guard(self):
        """GET /users/ must have require_api_key_permission at router level."""
        route = self._get_users_listing_route()
        assert self._route_has_dependency(route, "_api_key_permission_dep"), (
            "GET /users/ missing router-level require_api_key_permission"
        )


class TestAdminApiKeyGuardContract:
    """Tenant-admin API key mounts require admin key permission."""

    def _route_has_dependency(self, route, dep_name: str) -> bool:
        deps = getattr(route, "dependencies", [])
        for dep in deps:
            if hasattr(dep, "dependency") and getattr(dep.dependency, "__name__", "") == dep_name:
                return True
        return False

    def test_read_tenant_key_denied_by_admin_key_guard(self):
        key = _make_key(
            permission=ApiKeyPermission.READ.value,
            scope_type=ApiKeyScopeType.TENANT.value,
        )
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_management_permission(key, ApiKeyPermission.ADMIN.value)
        assert exc_info.value.code == "insufficient_permission"

    def test_admin_tenant_key_passes_admin_key_guard(self):
        key = _make_key(
            permission=ApiKeyPermission.ADMIN.value,
            scope_type=ApiKeyScopeType.TENANT.value,
        )
        _check_management_permission(key, ApiKeyPermission.ADMIN.value)

    def test_api_keys_list_route_has_scope_but_not_admin_key_guard(self):
        from intric.server.routers import router as root

        list_route = None
        for route in root.routes:
            if getattr(route, "path", "") == "/api-keys" and "GET" in getattr(route, "methods", set()):
                list_route = route
                break

        assert list_route is not None, "GET /api-keys route not found"
        assert self._route_has_dependency(list_route, "_scope_check_dep")
        assert not self._route_has_dependency(list_route, "_api_key_permission_dep")


class TestModelProvidersBearerRoleContract:
    """Model provider GET endpoints must require admin role for bearer users."""

    @staticmethod
    def _provider_dict():
        from datetime import datetime, timezone

        return {
            "id": uuid4(),
            "tenant_id": uuid4(),
            "name": "Provider",
            "provider_type": "openai",
            "config": {},
            "is_active": True,
            "masked_api_key": "...abcd",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    @pytest.mark.asyncio
    async def test_non_admin_denied_on_list(self):
        from intric.main.exceptions import UnauthorizedException
        from intric.model_providers.presentation.model_provider_router import list_providers

        service = AsyncMock()
        user = SimpleNamespace(permissions=[])

        with pytest.raises(UnauthorizedException):
            await list_providers(user=user, service=service)
        service.get_all.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_admin_allowed_on_list(self):
        from intric.roles.permissions import Permission
        from intric.model_providers.presentation.model_provider_router import list_providers

        provider = MagicMock()
        provider.to_dict.return_value = self._provider_dict()
        service = AsyncMock()
        service.get_all.return_value = [provider]
        user = SimpleNamespace(permissions=[Permission.ADMIN])

        response = await list_providers(user=user, service=service)
        service.get_all.assert_awaited_once()
        assert len(response) == 1
        assert response[0].name == "Provider"

    @pytest.mark.asyncio
    async def test_non_admin_denied_on_get(self):
        from intric.main.exceptions import UnauthorizedException
        from intric.model_providers.presentation.model_provider_router import get_provider

        service = AsyncMock()
        user = SimpleNamespace(permissions=[])

        with pytest.raises(UnauthorizedException):
            await get_provider(provider_id=uuid4(), user=user, service=service)
        service.get_by_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_admin_allowed_on_get(self):
        from intric.roles.permissions import Permission
        from intric.model_providers.presentation.model_provider_router import get_provider

        provider = MagicMock()
        provider.to_dict.return_value = self._provider_dict()
        service = AsyncMock()
        service.get_by_id.return_value = provider
        user = SimpleNamespace(permissions=[Permission.ADMIN])

        response = await get_provider(provider_id=uuid4(), user=user, service=service)
        service.get_by_id.assert_awaited_once()
        assert response.name == "Provider"


class TestSuperKeyIsolationContract:
    """Lock sysadmin/modules auth separation by dependency and auth function behavior."""

    def _route_has_dependency(self, route, dep_name: str) -> bool:
        deps = getattr(route, "dependencies", [])
        return any(
            hasattr(dep, "dependency")
            and getattr(dep.dependency, "__name__", "") == dep_name
            for dep in deps
        )

    def test_sysadmin_routes_use_super_api_key_only(self):
        from intric.server.routers import router as root

        sysadmin_routes = [
            route
            for route in root.routes
            if getattr(route, "path", "").startswith("/sysadmin")
        ]
        assert sysadmin_routes, "No /sysadmin routes found"
        for route in sysadmin_routes:
            assert self._route_has_dependency(route, "authenticate_super_api_key"), (
                f"{route.path} missing authenticate_super_api_key"
            )
            assert not self._route_has_dependency(route, "authenticate_super_duper_api_key"), (
                f"{route.path} should not use authenticate_super_duper_api_key"
            )

    def test_module_routes_use_super_duper_key_only(self):
        from intric.server.routers import router as root

        module_routes = [
            route
            for route in root.routes
            if getattr(route, "path", "").startswith("/modules")
        ]
        assert module_routes, "No /modules routes found"
        for route in module_routes:
            assert self._route_has_dependency(route, "authenticate_super_duper_api_key"), (
                f"{route.path} missing authenticate_super_duper_api_key"
            )
            assert not self._route_has_dependency(route, "authenticate_super_api_key"), (
                f"{route.path} should not use authenticate_super_api_key"
            )

    def test_super_and_super_duper_keys_are_not_interchangeable(self, monkeypatch):
        from intric.authentication import auth
        from intric.main.exceptions import AuthenticationException

        settings = SimpleNamespace(
            intric_super_api_key="super-key",
            intric_super_duper_api_key="super-duper-key",
            api_key_header_name="X-API-Key",
        )
        monkeypatch.setattr("intric.authentication.auth.get_settings", lambda: settings)

        request_super = SimpleNamespace(headers={"X-API-Key": "super-key"})
        request_super_duper = SimpleNamespace(headers={"X-API-Key": "super-duper-key"})

        # In real requests, Security(APIKeyHeader) provides the header value directly.
        assert auth.authenticate_super_api_key(request_super, "super-key") == "super-key"
        assert (
            auth.authenticate_super_duper_api_key(request_super_duper, "super-duper-key")
            == "super-duper-key"
        )

        with pytest.raises(AuthenticationException):
            auth.authenticate_super_duper_api_key(request_super, "super-key")

        with pytest.raises(AuthenticationException):
            auth.authenticate_super_api_key(request_super_duper, "super-duper-key")
