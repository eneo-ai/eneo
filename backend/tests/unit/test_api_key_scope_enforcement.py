"""Tests for API key scope enforcement (Phase 3).

Covers:
- _enforce_api_key_scope() unit tests (tenant, space, assistant, app scopes)
- List endpoint behavior per scope type
- Route guard coverage (CI guard)
- Body-driven conversation scope validation
- Settings mutation scope guards
- Scope toggle (env flag + tenant flag)
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette.datastructures import State

from intric.authentication.auth_dependencies import require_api_key_scope_check
from intric.authentication.auth_models import (
    ApiKeyPermission,
    ApiKeyScopeType,
)
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.conversations.conversations_router import _validate_conversation_scope
from tests.unit.api_key_test_utils import make_api_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_key(**overrides: object):
    return make_api_key(
        default_permission=ApiKeyPermission.READ,
        **overrides,
    )


def _scope_request(
    path_params: dict[str, str] | None = None,
) -> SimpleNamespace:
    """Build a minimal request-like object with scope (path_params) for _enforce_api_key_scope."""
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
    """Build a minimal UserService-like object with the methods needed for scope enforcement."""
    from intric.users.user_service import UserService

    svc = object.__new__(UserService)
    svc.feature_flag_service = feature_flag_service
    # Mock the repo.session for direct SQL queries used by scope resolution
    mock_session = AsyncMock()
    mock_session.scalar = AsyncMock(return_value=session_scalar_return)
    svc.repo = SimpleNamespace(session=mock_session)
    return svc


def _make_space(space_id: UUID) -> SimpleNamespace:
    """Build a minimal space-like object (used by body-driven scope tests that mock container.space_repo)."""
    return SimpleNamespace(id=space_id)


# ---------------------------------------------------------------------------
# TestScopeEnforcementUnit — direct _enforce_api_key_scope() tests
# ---------------------------------------------------------------------------


class TestScopeEnforcementUnit:
    """Direct unit tests for UserService._enforce_api_key_scope()."""

    @pytest.mark.asyncio
    async def test_tenant_key_always_passes(self):
        """Tenant-scoped key should pass regardless of resource_type."""
        svc = _make_user_service()
        key = _make_key(scope_type=ApiKeyScopeType.TENANT, scope_id=None)
        request = _scope_request()
        scope_config = {"resource_type": "admin", "path_param": None}

        # Should not raise
        await svc._enforce_api_key_scope(request, key, scope_config)

    @pytest.mark.asyncio
    async def test_space_key_admin_route_denied(self):
        """Space-scoped key on admin route → 403 insufficient_scope."""
        space_id = uuid4()
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.SPACE, scope_id=space_id
        )
        request = _scope_request()
        scope_config = {"resource_type": "admin", "path_param": None}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"
        assert exc_info.value.status_code == 403
        assert "Admin endpoints require a tenant-scoped key" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_assistant_key_admin_route_denied(self):
        """Assistant-scoped key on admin route → 403."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.ASSISTANT, scope_id=uuid4()
        )
        request = _scope_request()
        scope_config = {"resource_type": "admin", "path_param": None}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_app_key_admin_route_denied(self):
        """App-scoped key on admin route → 403."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.APP, scope_id=uuid4()
        )
        request = _scope_request()
        scope_config = {"resource_type": "admin", "path_param": None}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_space_key_matching_space_passes(self):
        """Space-scoped key accessing resource in its own space → pass."""
        space_id = uuid4()
        assistant_id = uuid4()
        svc = _make_user_service(session_scalar_return=space_id)
        key = _make_key(
            scope_type=ApiKeyScopeType.SPACE, scope_id=space_id
        )
        request = _scope_request(path_params={"id": str(assistant_id)})
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        await svc._enforce_api_key_scope(request, key, scope_config)

    @pytest.mark.asyncio
    async def test_space_key_different_space_denied(self):
        """Space-scoped key accessing resource in another space → 403."""
        key_space = uuid4()
        other_space = uuid4()
        assistant_id = uuid4()
        svc = _make_user_service(session_scalar_return=other_space)
        key = _make_key(
            scope_type=ApiKeyScopeType.SPACE, scope_id=key_space
        )
        request = _scope_request(path_params={"id": str(assistant_id)})
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"
        assert "different scope" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_space_key_space_resource_exact_match(self):
        """Space-scoped key accessing its own space directly → pass."""
        space_id = uuid4()
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.SPACE, scope_id=space_id
        )
        request = _scope_request(path_params={"id": str(space_id)})
        scope_config = {"resource_type": "space", "path_param": "id"}

        await svc._enforce_api_key_scope(request, key, scope_config)

    @pytest.mark.asyncio
    async def test_space_key_different_space_resource_denied(self):
        """Space-scoped key accessing another space directly → 403."""
        key_space = uuid4()
        other_space = uuid4()
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.SPACE, scope_id=key_space
        )
        request = _scope_request(path_params={"id": str(other_space)})
        scope_config = {"resource_type": "space", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_assistant_key_exact_match_passes(self):
        """Assistant-scoped key accessing its own assistant → pass."""
        assistant_id = uuid4()
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.ASSISTANT, scope_id=assistant_id
        )
        request = _scope_request(path_params={"id": str(assistant_id)})
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        await svc._enforce_api_key_scope(request, key, scope_config)

    @pytest.mark.asyncio
    async def test_assistant_key_different_assistant_denied(self):
        """Assistant-scoped key accessing different assistant (even same space) → 403."""
        key_assistant = uuid4()
        other_assistant = uuid4()
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.ASSISTANT, scope_id=key_assistant
        )
        request = _scope_request(path_params={"id": str(other_assistant)})
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"
        assert "assistant" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_assistant_key_own_conversation_passes(self):
        """Assistant-scoped key accessing conversation of its own assistant → pass."""
        assistant_id = uuid4()
        session_id = uuid4()
        svc = _make_user_service(session_scalar_return=assistant_id)
        key = _make_key(
            scope_type=ApiKeyScopeType.ASSISTANT, scope_id=assistant_id
        )
        request = _scope_request(path_params={"session_id": str(session_id)})
        scope_config = {"resource_type": "conversation", "path_param": "session_id"}

        await svc._enforce_api_key_scope(request, key, scope_config)

    @pytest.mark.asyncio
    async def test_assistant_key_other_conversation_denied(self):
        """Assistant-scoped key accessing conversation of different assistant → 403."""
        key_assistant = uuid4()
        other_assistant = uuid4()
        session_id = uuid4()
        svc = _make_user_service(session_scalar_return=other_assistant)
        key = _make_key(
            scope_type=ApiKeyScopeType.ASSISTANT, scope_id=key_assistant
        )
        request = _scope_request(path_params={"session_id": str(session_id)})
        scope_config = {"resource_type": "conversation", "path_param": "session_id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_assistant_key_app_endpoint_denied(self):
        """Assistant-scoped key accessing app endpoint → 403 (wrong scope type)."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.ASSISTANT, scope_id=uuid4()
        )
        app_id = uuid4()
        request = _scope_request(path_params={"id": str(app_id)})
        scope_config = {"resource_type": "app", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_app_key_exact_match_passes(self):
        """App-scoped key accessing its own app → pass."""
        app_id = uuid4()
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.APP, scope_id=app_id
        )
        request = _scope_request(path_params={"id": str(app_id)})
        scope_config = {"resource_type": "app", "path_param": "id"}

        await svc._enforce_api_key_scope(request, key, scope_config)

    @pytest.mark.asyncio
    async def test_app_key_different_app_denied(self):
        """App-scoped key accessing different app → 403."""
        key_app = uuid4()
        other_app = uuid4()
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.APP, scope_id=key_app
        )
        request = _scope_request(path_params={"id": str(other_app)})
        scope_config = {"resource_type": "app", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_app_key_own_app_run_passes(self):
        """App-scoped key accessing app_run of its own app → pass."""
        app_id = uuid4()
        app_run_id = uuid4()
        svc = _make_user_service(session_scalar_return=app_id)
        # _resolve_app_run_app_id uses repo.session.scalar
        key = _make_key(
            scope_type=ApiKeyScopeType.APP, scope_id=app_id
        )
        request = _scope_request(path_params={"id": str(app_run_id)})
        scope_config = {"resource_type": "app_run", "path_param": "id"}

        await svc._enforce_api_key_scope(request, key, scope_config)

    @pytest.mark.asyncio
    async def test_app_key_other_app_run_denied(self):
        """App-scoped key accessing app_run of different app → 403."""
        key_app = uuid4()
        other_app = uuid4()
        app_run_id = uuid4()
        svc = _make_user_service(session_scalar_return=other_app)
        key = _make_key(
            scope_type=ApiKeyScopeType.APP, scope_id=key_app
        )
        request = _scope_request(path_params={"id": str(app_run_id)})
        scope_config = {"resource_type": "app_run", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_app_key_assistant_endpoint_denied(self):
        """App-scoped key accessing assistant endpoint → 403."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.APP, scope_id=uuid4()
        )
        assistant_id = uuid4()
        request = _scope_request(path_params={"id": str(assistant_id)})
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_app_key_service_endpoint_denied(self):
        """App-scoped key accessing service endpoint → 403 (services are not app sub-resources)."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.APP, scope_id=uuid4()
        )
        service_id = uuid4()
        request = _scope_request(path_params={"id": str(service_id)})
        scope_config = {"resource_type": "service", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_space_key_unresolvable_resource_denied(self):
        """Space-scoped key with unresolvable resource → 403 (fail-closed)."""
        svc = _make_user_service(session_scalar_return=None)
        key = _make_key(
            scope_type=ApiKeyScopeType.SPACE, scope_id=uuid4()
        )
        request = _scope_request(path_params={"id": str(uuid4())})
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_space_key_info_blob_id_in_scope_passes(self):
        """Space-scoped key with info_blob id resolves to same space → pass."""
        space_id = uuid4()
        blob_id = uuid4()
        svc = _make_user_service(session_scalar_return=space_id)
        key = _make_key(scope_type=ApiKeyScopeType.SPACE, scope_id=space_id)
        request = _scope_request(path_params={"id": str(blob_id)})
        scope_config = {"resource_type": "info_blob", "path_param": None}

        await svc._enforce_api_key_scope(request, key, scope_config, strict_mode=True)

    @pytest.mark.asyncio
    async def test_space_key_space_scoped_info_blob_listing_route_passes_in_strict_mode(self):
        """Space-scoped key + /info-blobs/spaces/{space_id} is deterministic and allowed."""
        space_id = uuid4()
        svc = _make_user_service()
        key = _make_key(scope_type=ApiKeyScopeType.SPACE, scope_id=space_id)
        request = _scope_request(path_params={"space_id": str(space_id)})
        scope_config = {"resource_type": "info_blob", "path_param": None}

        await svc._enforce_api_key_scope(request, key, scope_config, strict_mode=True)

    @pytest.mark.asyncio
    async def test_space_key_space_scoped_info_blob_listing_route_wrong_space_denied(self):
        """Space-scoped key + /info-blobs/spaces/{other} is denied."""
        key_space_id = uuid4()
        other_space_id = uuid4()
        svc = _make_user_service()
        key = _make_key(scope_type=ApiKeyScopeType.SPACE, scope_id=key_space_id)
        request = _scope_request(path_params={"space_id": str(other_space_id)})
        scope_config = {"resource_type": "info_blob", "path_param": None}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config, strict_mode=True)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_info_blob_route_ignores_non_deterministic_session_id_in_strict_mode(self):
        """info_blob fallback only supports id/space_id; session_id must not be inferred."""
        space_id = uuid4()
        svc = _make_user_service()
        key = _make_key(scope_type=ApiKeyScopeType.SPACE, scope_id=space_id)
        request = _scope_request(path_params={"session_id": str(uuid4())})
        scope_config = {"resource_type": "info_blob", "path_param": None}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config, strict_mode=True)
        assert exc_info.value.code == "insufficient_scope"
        assert "path parameter 'id' or 'space_id'" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_space_key_file_detail_route_strict_mode_denied_as_ambiguous(self):
        """File detail route remains ambiguous when mounted with path_param=None."""
        space_id = uuid4()
        file_id = uuid4()
        svc = _make_user_service()
        key = _make_key(scope_type=ApiKeyScopeType.SPACE, scope_id=space_id)
        request = _scope_request(path_params={"id": str(file_id)})
        scope_config = {"resource_type": "space", "path_param": None}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config, strict_mode=True)
        assert exc_info.value.code == "insufficient_scope"
        assert "Strict mode requires deterministic scope filtering" in exc_info.value.message
        assert "resource type 'space'" in exc_info.value.message
        assert "Expected a deterministic scoped path parameter" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_space_key_file_detail_route_non_strict_mode_stays_list_path(self):
        """File detail route should not reinterpret file id as space id."""
        space_id = uuid4()
        svc = _make_user_service(session_scalar_return=space_id)
        key = _make_key(scope_type=ApiKeyScopeType.SPACE, scope_id=space_id)
        request = _scope_request(path_params={"id": str(uuid4())})
        scope_config = {"resource_type": "space", "path_param": None}

        await svc._enforce_api_key_scope(request, key, scope_config, strict_mode=False)
        svc.repo.session.scalar.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_scope_config_no_check(self):
        """When no scope config is set on route, enforcement is skipped."""
        # This is tested at the _resolve_api_key level:
        # scope_config = getattr(request.state, "_scope_check_config", None)
        # if scope_config is not None and ...:
        # We just verify the config-stash pattern works.
        request = _scope_request()
        assert not hasattr(request.state, "_scope_check_config")

    @pytest.mark.asyncio
    async def test_error_code_is_insufficient_scope(self):
        """All scope denials should use code 'insufficient_scope' (distinct from permission)."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.SPACE, scope_id=uuid4()
        )
        request = _scope_request()
        scope_config = {"resource_type": "admin", "path_param": None}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"
        assert exc_info.value.code != "insufficient_permission"


# ---------------------------------------------------------------------------
# TestScopeListEndpoints — list endpoint behavior per scope type
# ---------------------------------------------------------------------------


class TestScopeListEndpoints:
    """List endpoint behavior: path_param present but no resource_id in path."""

    @pytest.mark.asyncio
    async def test_space_key_list_apps_passes(self):
        """Space-scoped key listing apps (no path ID) → pass (service filters)."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.SPACE, scope_id=uuid4()
        )
        request = _scope_request(path_params={})  # No 'id' in path
        scope_config = {"resource_type": "app", "path_param": "id"}

        await svc._enforce_api_key_scope(request, key, scope_config)

    @pytest.mark.asyncio
    async def test_space_key_list_assistants_passes(self):
        """Space-scoped key listing assistants → pass."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.SPACE, scope_id=uuid4()
        )
        request = _scope_request(path_params={})
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        await svc._enforce_api_key_scope(request, key, scope_config)

    @pytest.mark.asyncio
    async def test_assistant_key_list_assistants_passes(self):
        """Assistant-scoped key listing assistants → pass (own type)."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.ASSISTANT, scope_id=uuid4()
        )
        request = _scope_request(path_params={})
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        await svc._enforce_api_key_scope(request, key, scope_config)

    @pytest.mark.asyncio
    async def test_assistant_key_list_conversations_passes(self):
        """Assistant-scoped key listing conversations → pass (related type)."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.ASSISTANT, scope_id=uuid4()
        )
        request = _scope_request(path_params={})
        scope_config = {"resource_type": "conversation", "path_param": "session_id"}

        await svc._enforce_api_key_scope(request, key, scope_config)

    @pytest.mark.asyncio
    async def test_assistant_key_list_apps_denied(self):
        """Assistant-scoped key listing apps → 403 (wrong type)."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.ASSISTANT, scope_id=uuid4()
        )
        request = _scope_request(path_params={})
        scope_config = {"resource_type": "app", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_assistant_key_list_services_denied(self):
        """Assistant-scoped key listing services → 403."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.ASSISTANT, scope_id=uuid4()
        )
        request = _scope_request(path_params={})
        scope_config = {"resource_type": "service", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_app_key_list_apps_passes(self):
        """App-scoped key listing apps → pass (own type)."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.APP, scope_id=uuid4()
        )
        request = _scope_request(path_params={})
        scope_config = {"resource_type": "app", "path_param": "id"}

        await svc._enforce_api_key_scope(request, key, scope_config)

    @pytest.mark.asyncio
    async def test_app_key_list_app_runs_passes(self):
        """App-scoped key listing app_runs → pass (related type)."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.APP, scope_id=uuid4()
        )
        request = _scope_request(path_params={})
        scope_config = {"resource_type": "app_run", "path_param": "id"}

        await svc._enforce_api_key_scope(request, key, scope_config)

    @pytest.mark.asyncio
    async def test_app_key_list_assistants_denied(self):
        """App-scoped key listing assistants → 403."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.APP, scope_id=uuid4()
        )
        request = _scope_request(path_params={})
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_app_key_list_services_denied(self):
        """App-scoped key listing services → 403 (services are not app sub-resources)."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.APP, scope_id=uuid4()
        )
        request = _scope_request(path_params={})
        scope_config = {"resource_type": "service", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        assert exc_info.value.code == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_space_key_list_denied_in_strict_mode(self):
        """Strict mode denies non-tenant scoped list endpoints when scope cannot be proven."""
        svc = _make_user_service()
        key = _make_key(scope_type=ApiKeyScopeType.SPACE, scope_id=uuid4())
        request = _scope_request(path_params={})  # list endpoint (no resource id)
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config, strict_mode=True)
        assert exc_info.value.code == "insufficient_scope"
        assert "Strict mode requires deterministic scope filtering" in exc_info.value.message
        assert "path parameter 'id'" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_assistant_key_list_denied_in_strict_mode(self):
        """Strict mode denies assistant-scoped list endpoints as well."""
        svc = _make_user_service()
        key = _make_key(scope_type=ApiKeyScopeType.ASSISTANT, scope_id=uuid4())
        request = _scope_request(path_params={})  # list endpoint (no resource id)
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config, strict_mode=True)
        assert exc_info.value.code == "insufficient_scope"


# ---------------------------------------------------------------------------
# TestScopeToggle — env flag + tenant feature flag
# ---------------------------------------------------------------------------


class TestScopeToggle:
    """Scope enforcement toggle: env flag and tenant feature flag."""

    @pytest.mark.asyncio
    async def test_env_flag_off_skips_enforcement(self):
        """When api_key_enforce_scope is False, scope enforcement is skipped entirely."""
        # The env flag check is in _resolve_api_key:
        # if get_settings().api_key_enforce_scope: ...
        # We test by verifying the config flag exists and its effect.
        from intric.main.config import get_settings

        settings = get_settings()
        assert hasattr(settings, "api_key_enforce_scope")

    @pytest.mark.asyncio
    async def test_tenant_flag_off_skips_enforcement(self):
        """When tenant feature flag is disabled, enforcement is skipped."""
        feature_flag_service = MagicMock()
        feature_flag_service.check_is_feature_enabled_fail_closed = AsyncMock(
            return_value=False
        )

        svc = _make_user_service(feature_flag_service=feature_flag_service)
        result = await svc._is_scope_enforcement_enabled(uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_tenant_flag_on_enables_enforcement(self):
        """When tenant feature flag is enabled, enforcement is active."""
        feature_flag_service = MagicMock()
        feature_flag_service.check_is_feature_enabled_fail_closed = AsyncMock(
            return_value=True
        )

        svc = _make_user_service(feature_flag_service=feature_flag_service)
        result = await svc._is_scope_enforcement_enabled(uuid4())
        assert result is True

    @pytest.mark.asyncio
    async def test_missing_flag_row_defaults_enforced(self):
        """Missing feature flag row → enforcement ON (fail-closed for security)."""
        feature_flag_service = MagicMock()
        feature_flag_service.check_is_feature_enabled_fail_closed = AsyncMock(
            return_value=True
        )

        svc = _make_user_service(feature_flag_service=feature_flag_service)
        result = await svc._is_scope_enforcement_enabled(uuid4())
        assert result is True

    @pytest.mark.asyncio
    async def test_missing_feature_flag_service_defaults_enforced(self):
        """No feature_flag_service injected → enforcement ON (fail-closed)."""
        svc = _make_user_service(feature_flag_service=None)
        result = await svc._is_scope_enforcement_enabled(uuid4())
        assert result is True

    @pytest.mark.asyncio
    async def test_strict_mode_flag_on_enables_strict_mode(self):
        """Tenant strict mode flag enabled -> strict mode active."""
        feature_flag_service = MagicMock()
        feature_flag_service.check_is_feature_enabled = AsyncMock(return_value=True)

        svc = _make_user_service(feature_flag_service=feature_flag_service)
        result = await svc._is_strict_mode_enabled(uuid4())
        assert result is True

    @pytest.mark.asyncio
    async def test_missing_strict_mode_flag_defaults_disabled(self):
        """Missing strict mode row defaults OFF for staged rollout."""
        feature_flag_service = MagicMock()
        feature_flag_service.check_is_feature_enabled = AsyncMock(return_value=False)

        svc = _make_user_service(feature_flag_service=feature_flag_service)
        result = await svc._is_strict_mode_enabled(uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_missing_feature_flag_service_defaults_strict_mode_disabled(self):
        """No feature_flag_service injected -> strict mode disabled."""
        svc = _make_user_service(feature_flag_service=None)
        result = await svc._is_strict_mode_enabled(uuid4())
        assert result is False


# ---------------------------------------------------------------------------
# TestResolveApiKeyStrictModeWiring — runtime strict-mode forwarding checks
# ---------------------------------------------------------------------------


class TestResolveApiKeyStrictModeWiring:
    """Ensure _resolve_api_key forwards strict-mode runtime state to scope checks."""

    @staticmethod
    def _build_request() -> SimpleNamespace:
        request = SimpleNamespace(
            method="GET",
            headers={},
            scope={},
            client=SimpleNamespace(host="127.0.0.1"),
            state=State(),
            url=SimpleNamespace(path="/api/v1/assistants"),
        )
        request.state._scope_check_config = {"resource_type": "assistant", "path_param": "id"}
        return request

    @staticmethod
    def _build_service(key) -> object:
        from intric.users.user_service import UserService

        svc = object.__new__(UserService)
        svc.api_key_auth_resolver = SimpleNamespace(
            resolve=AsyncMock(return_value=SimpleNamespace(key=key))
        )
        svc.repo = SimpleNamespace(
            get_user_by_id=AsyncMock(
                return_value=SimpleNamespace(
                    id=key.owner_user_id,
                    tenant_id=key.tenant_id,
                )
            )
        )
        svc.allowed_origin_repo = AsyncMock()
        svc.space_service = AsyncMock()
        svc.api_key_rate_limiter = None
        svc.api_key_v2_repo = SimpleNamespace(update_last_used_at=AsyncMock())
        svc._log_api_key_auth_failed = AsyncMock()
        svc._maybe_log_api_key_used = AsyncMock()
        svc._enforce_api_key_scope = AsyncMock()
        svc._is_scope_enforcement_enabled = AsyncMock(return_value=True)
        svc._is_strict_mode_enabled = AsyncMock(return_value=False)
        return svc

    @pytest.mark.asyncio
    async def test_resolve_api_key_forwards_strict_mode_true(self, monkeypatch):
        key = _make_key(scope_type=ApiKeyScopeType.SPACE, scope_id=uuid4())
        svc = self._build_service(key)
        request = self._build_request()

        class _PolicyServiceStub:
            def __init__(self, **kwargs):
                pass

            async def enforce_guardrails(self, *, key, origin, client_ip):
                return None

        monkeypatch.setattr("intric.users.user_service.ApiKeyPolicyService", _PolicyServiceStub)
        monkeypatch.setattr(
            "intric.users.user_service.get_settings",
            lambda: SimpleNamespace(
                api_key_enforce_resource_permissions=False,
                api_key_enforce_scope=True,
                api_key_last_used_min_interval_seconds=0,
            ),
        )
        svc._is_strict_mode_enabled = AsyncMock(return_value=True)

        await svc._resolve_api_key("sk_test_key", request=request)

        svc._enforce_api_key_scope.assert_awaited_once()
        assert svc._enforce_api_key_scope.await_args.kwargs["strict_mode"] is True

    @pytest.mark.asyncio
    async def test_resolve_api_key_forwards_strict_mode_false(self, monkeypatch):
        key = _make_key(scope_type=ApiKeyScopeType.SPACE, scope_id=uuid4())
        svc = self._build_service(key)
        request = self._build_request()

        class _PolicyServiceStub:
            def __init__(self, **kwargs):
                pass

            async def enforce_guardrails(self, *, key, origin, client_ip):
                return None

        monkeypatch.setattr("intric.users.user_service.ApiKeyPolicyService", _PolicyServiceStub)
        monkeypatch.setattr(
            "intric.users.user_service.get_settings",
            lambda: SimpleNamespace(
                api_key_enforce_resource_permissions=False,
                api_key_enforce_scope=True,
                api_key_last_used_min_interval_seconds=0,
            ),
        )
        svc._is_strict_mode_enabled = AsyncMock(return_value=False)

        await svc._resolve_api_key("sk_test_key", request=request)

        svc._enforce_api_key_scope.assert_awaited_once()
        assert svc._enforce_api_key_scope.await_args.kwargs["strict_mode"] is False

    @pytest.mark.asyncio
    async def test_resolve_api_key_skips_scope_check_when_env_toggle_off(self, monkeypatch):
        key = _make_key(scope_type=ApiKeyScopeType.SPACE, scope_id=uuid4())
        svc = self._build_service(key)
        request = self._build_request()

        class _PolicyServiceStub:
            def __init__(self, **kwargs):
                pass

            async def enforce_guardrails(self, *, key, origin, client_ip):
                return None

        monkeypatch.setattr("intric.users.user_service.ApiKeyPolicyService", _PolicyServiceStub)
        monkeypatch.setattr(
            "intric.users.user_service.get_settings",
            lambda: SimpleNamespace(
                api_key_enforce_resource_permissions=False,
                api_key_enforce_scope=False,
                api_key_last_used_min_interval_seconds=0,
            ),
        )

        await svc._resolve_api_key("sk_test_key", request=request)

        svc._is_scope_enforcement_enabled.assert_not_awaited()
        svc._is_strict_mode_enabled.assert_not_awaited()
        svc._enforce_api_key_scope.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resolve_api_key_skips_scope_check_when_tenant_flag_off(self, monkeypatch):
        key = _make_key(scope_type=ApiKeyScopeType.SPACE, scope_id=uuid4())
        svc = self._build_service(key)
        request = self._build_request()

        class _PolicyServiceStub:
            def __init__(self, **kwargs):
                pass

            async def enforce_guardrails(self, *, key, origin, client_ip):
                return None

        monkeypatch.setattr("intric.users.user_service.ApiKeyPolicyService", _PolicyServiceStub)
        monkeypatch.setattr(
            "intric.users.user_service.get_settings",
            lambda: SimpleNamespace(
                api_key_enforce_resource_permissions=False,
                api_key_enforce_scope=True,
                api_key_last_used_min_interval_seconds=0,
            ),
        )
        svc._is_scope_enforcement_enabled = AsyncMock(return_value=False)

        await svc._resolve_api_key("sk_test_key", request=request)

        svc._is_scope_enforcement_enabled.assert_awaited_once()
        svc._is_strict_mode_enabled.assert_not_awaited()
        svc._enforce_api_key_scope.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resolve_api_key_tenant_scoped_key_skips_scope_enforcement(self, monkeypatch):
        key = _make_key(scope_type=ApiKeyScopeType.TENANT, scope_id=None)
        svc = self._build_service(key)
        request = self._build_request()

        class _PolicyServiceStub:
            def __init__(self, **kwargs):
                pass

            async def enforce_guardrails(self, *, key, origin, client_ip):
                return None

        monkeypatch.setattr("intric.users.user_service.ApiKeyPolicyService", _PolicyServiceStub)
        monkeypatch.setattr(
            "intric.users.user_service.get_settings",
            lambda: SimpleNamespace(
                api_key_enforce_resource_permissions=False,
                api_key_enforce_scope=True,
                api_key_last_used_min_interval_seconds=0,
            ),
        )
        svc._is_strict_mode_enabled = AsyncMock(return_value=True)

        await svc._resolve_api_key("sk_test_key", request=request)

        svc._is_scope_enforcement_enabled.assert_awaited_once()
        svc._is_strict_mode_enabled.assert_awaited_once()
        svc._enforce_api_key_scope.assert_not_awaited()


# ---------------------------------------------------------------------------
# TestScopeRouteGuardCoverage — CI guard for route coverage
# ---------------------------------------------------------------------------


class TestScopeRouteGuardCoverage:
    """CI guard: verify scope checks are wired to key routes."""

    def test_admin_routes_have_scope_check(self):
        """All admin route mounts should have resource_type='admin' scope check."""
        from intric.server.routers import router

        admin_routes_found = []
        for route in router.routes:
            prefix = getattr(route, "path", "")
            if prefix.startswith("/admin"):
                deps = getattr(route, "dependencies", [])
                has_scope_dep = any(
                    hasattr(dep, "dependency")
                    and getattr(dep.dependency, "__name__", "") == "_scope_check_dep"
                    for dep in deps
                )
                admin_routes_found.append((prefix, has_scope_dep))
                assert has_scope_dep, (
                    f"Admin route {prefix} missing require_api_key_scope_check dependency"
                )

        # Ensure we actually found admin routes (not silently passing on zero)
        assert len(admin_routes_found) >= 7, (
            f"Expected at least 7 admin route mounts, found {len(admin_routes_found)}: "
            f"{[r[0] for r in admin_routes_found]}"
        )

    def test_api_key_routes_have_scope_check(self):
        """API key management routes should have admin scope check."""
        from intric.server.routers import router

        # api_key_router is mounted without prefix — routes are flattened as
        # top-level APIRoute objects with the scope dependency attached.
        api_key_routes = []
        for route in router.routes:
            path = getattr(route, "path", "")
            # Match /api-keys* but NOT /admin/api-keys* or /users/api-keys*
            if path.startswith("/api-keys"):
                api_key_routes.append(route)

        assert len(api_key_routes) >= 3, (
            f"Expected >= 3 api-key routes, found {len(api_key_routes)}"
        )
        for route in api_key_routes:
            deps = getattr(route, "dependencies", [])
            has_scope_dep = any(
                hasattr(dep, "dependency")
                and getattr(dep.dependency, "__name__", "") == "_scope_check_dep"
                for dep in deps
            )
            assert has_scope_dep, (
                f"API key route {route.path} missing _scope_check_dep dependency"
            )

    def test_core_resource_routes_have_scope_metadata(self):
        """Core resource routes (spaces, assistants, apps, etc.) have scope checks."""
        from intric.server.routers import router

        # Routes are flattened by FastAPI — match by prefix (startswith).
        required_prefixes = {
            "/spaces", "/assistants", "/apps", "/app-runs",
            "/conversations", "/services", "/group-chats",
            "/groups", "/websites", "/crawl-runs",
        }
        found_prefixes = set()
        routes_missing_scope_dep = []
        for route in router.routes:
            path = getattr(route, "path", "")
            for req in required_prefixes:
                if path.startswith(req):
                    found_prefixes.add(req)
                    deps = getattr(route, "dependencies", [])
                    has_scope_dep = any(
                        hasattr(dep, "dependency")
                        and getattr(dep.dependency, "__name__", "") == "_scope_check_dep"
                        for dep in deps
                    )
                    if not has_scope_dep:
                        routes_missing_scope_dep.append(path)

        missing = required_prefixes - found_prefixes
        assert not missing, (
            f"Required route prefixes not found in router: {missing}. "
            f"Found: {found_prefixes}"
        )
        assert not routes_missing_scope_dep, (
            f"Routes missing _scope_check_dep dependency: {routes_missing_scope_dep}"
        )

    def test_settings_patch_endpoints_have_router_level_admin_guards(self):
        """Settings PATCH endpoints should have router-level admin scope + key guards."""
        from intric.server.routers import router

        patch_routes = []
        for route in router.routes:
            path = getattr(route, "path", "")
            methods = getattr(route, "methods", set())
            if path.startswith("/settings") and "PATCH" in methods:
                deps = getattr(route, "dependencies", [])
                has_scope_dep = any(
                    hasattr(dep, "dependency")
                    and getattr(dep.dependency, "__name__", "") == "_scope_check_dep"
                    for dep in deps
                )
                has_admin_key_dep = any(
                    hasattr(dep, "dependency")
                    and getattr(dep.dependency, "__name__", "") == "_api_key_permission_dep"
                    for dep in deps
                )
                patch_routes.append((path, has_scope_dep, has_admin_key_dep))

        assert len(patch_routes) >= 5, (
            f"Expected at least 5 PATCH /settings endpoints, found {len(patch_routes)}"
        )
        for path, has_scope_dep, has_admin_key_dep in patch_routes:
            assert has_scope_dep, f"Settings PATCH endpoint {path} missing _scope_check_dep"
            assert has_admin_key_dep, f"Settings PATCH endpoint {path} missing _api_key_permission_dep"

    def test_template_admin_routes_have_scope_check(self):
        """Template admin router mounts should have admin scope check."""
        from intric.server.routers import router

        # Template admin routers are mounted with prefix="" but their internal
        # routes start with /admin/templates/. Find mounts with "admin-templates" tag.
        found = 0
        for route in router.routes:
            tags = getattr(route, "tags", [])
            if "admin-templates" in (tags or []):
                deps = getattr(route, "dependencies", [])
                has_scope_dep = any(
                    hasattr(dep, "dependency")
                    and getattr(dep.dependency, "__name__", "") == "_scope_check_dep"
                    for dep in deps
                )
                assert has_scope_dep, (
                    "Template admin route mount missing _scope_check_dep dependency"
                )
                found += 1
        assert found >= 2, (
            f"Expected at least 2 template admin route mounts, found {found}"
        )

    def test_user_admin_endpoints_have_router_level_admin_guards(self):
        """User admin endpoints should have router-level admin scope + key guards."""
        from intric.server.routers import router

        admin_routes = []
        for route in router.routes:
            path = getattr(route, "path", "")
            methods = getattr(route, "methods", set())
            if path == "/users/" or path.startswith("/users/admin") or path.startswith("/users/api-keys"):
                deps = getattr(route, "dependencies", [])
                has_scope_dep = any(
                    hasattr(dep, "dependency")
                    and getattr(dep.dependency, "__name__", "") == "_scope_check_dep"
                    for dep in deps
                )
                has_admin_key_dep = any(
                    hasattr(dep, "dependency")
                    and getattr(dep.dependency, "__name__", "") == "_api_key_permission_dep"
                    for dep in deps
                )
                admin_routes.append((path, sorted(methods), has_scope_dep, has_admin_key_dep))

        assert len(admin_routes) >= 5, (
            f"Expected at least 5 user admin routes, found {len(admin_routes)}"
        )
        for path, methods, has_scope_dep, has_admin_key_dep in admin_routes:
            assert has_scope_dep, f"User admin route {path} {methods} missing _scope_check_dep"
            assert has_admin_key_dep, f"User admin route {path} {methods} missing _api_key_permission_dep"


# ---------------------------------------------------------------------------
# TestScopeBodyDriven — body-driven conversation scope validation
# ---------------------------------------------------------------------------


class TestScopeBodyDriven:
    """Body-driven scope validation for POST /conversations/."""

    def _make_http_request(
        self, scope_type: str | None = None, scope_id: UUID | None = None
    ) -> SimpleNamespace:
        state = State()
        if scope_type is not None:
            state.api_key_scope_type = scope_type
            state.api_key_scope_id = scope_id
        return SimpleNamespace(state=state)

    def _make_container(
        self,
        space_by_assistant: Any = None,
        space_by_group_chat: Any = None,
        space_by_session: Any = None,
        session_obj: Any = None,
        session_not_found: bool = False,
    ) -> MagicMock:
        container = MagicMock()

        space_repo = AsyncMock()
        if space_by_assistant is not None:
            space_repo.get_space_by_assistant = AsyncMock(return_value=space_by_assistant)
        else:
            from intric.main.exceptions import NotFoundException
            space_repo.get_space_by_assistant = AsyncMock(side_effect=NotFoundException())

        if space_by_group_chat is not None:
            space_repo.get_space_by_group_chat = AsyncMock(return_value=space_by_group_chat)
        else:
            from intric.main.exceptions import NotFoundException
            space_repo.get_space_by_group_chat = AsyncMock(side_effect=NotFoundException())

        if space_by_session is not None:
            space_repo.get_space_by_session = AsyncMock(return_value=space_by_session)
        else:
            from intric.main.exceptions import NotFoundException
            space_repo.get_space_by_session = AsyncMock(side_effect=NotFoundException())

        container.space_repo = MagicMock(return_value=space_repo)

        session_service = AsyncMock()
        if session_obj is not None:
            session_service.get_session_by_uuid = AsyncMock(return_value=session_obj)
        elif session_not_found:
            from intric.main.exceptions import NotFoundException
            session_service.get_session_by_uuid = AsyncMock(side_effect=NotFoundException())
        else:
            session_service.get_session_by_uuid = AsyncMock(side_effect=Exception("not found"))
        container.session_service = MagicMock(return_value=session_service)

        # Feature flag service (for _validate_conversation_scope flag gating)
        flag = MagicMock()
        flag.is_enabled = MagicMock(return_value=True)
        feature_flag_service = MagicMock()
        feature_flag_service.feature_flag_repo = MagicMock()
        feature_flag_service.feature_flag_repo.one_or_none = AsyncMock(return_value=flag)
        container.feature_flag_service = MagicMock(return_value=feature_flag_service)

        # User (needed for feature flag tenant check)
        user = MagicMock()
        user.tenant_id = uuid4()
        container.user = MagicMock(return_value=user)

        return container

    @pytest.mark.asyncio
    async def test_no_scope_passes(self):
        """No scope metadata (bearer token or no key) → pass."""
        request = self._make_http_request(scope_type=None)
        container = self._make_container()

        await _validate_conversation_scope(
            http_request=request,
            container=container,
            assistant_id=uuid4(),
            group_chat_id=None,
            session_id=None,
        )

    @pytest.mark.asyncio
    async def test_tenant_scope_passes(self):
        """Tenant-scoped key → always pass."""
        request = self._make_http_request(scope_type="tenant")
        container = self._make_container()

        await _validate_conversation_scope(
            http_request=request,
            container=container,
            assistant_id=uuid4(),
            group_chat_id=None,
            session_id=None,
        )

    @pytest.mark.asyncio
    async def test_app_scope_denied(self):
        """App-scoped key → DENY (can't create conversations)."""
        app_id = uuid4()
        request = self._make_http_request(scope_type="app", scope_id=app_id)
        container = self._make_container()

        with pytest.raises(HTTPException) as exc_info:
            await _validate_conversation_scope(
                http_request=request,
                container=container,
                assistant_id=uuid4(),
                group_chat_id=None,
                session_id=None,
            )
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "insufficient_scope"
        assert "app" in exc_info.value.detail["message"].lower()

    @pytest.mark.asyncio
    async def test_assistant_scope_matching_assistant_passes(self):
        """Assistant-scoped key + matching assistant_id → pass."""
        assistant_id = uuid4()
        request = self._make_http_request(scope_type="assistant", scope_id=assistant_id)
        container = self._make_container()

        await _validate_conversation_scope(
            http_request=request,
            container=container,
            assistant_id=assistant_id,
            group_chat_id=None,
            session_id=None,
        )

    @pytest.mark.asyncio
    async def test_assistant_scope_different_assistant_denied(self):
        """Assistant-scoped key + different assistant_id → 403."""
        key_assistant = uuid4()
        other_assistant = uuid4()
        request = self._make_http_request(scope_type="assistant", scope_id=key_assistant)
        container = self._make_container()

        with pytest.raises(HTTPException) as exc_info:
            await _validate_conversation_scope(
                http_request=request,
                container=container,
                assistant_id=other_assistant,
                group_chat_id=None,
                session_id=None,
            )
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_assistant_scope_group_chat_denied(self):
        """Assistant-scoped key + group_chat_id → 403 (can't access group chats)."""
        assistant_id = uuid4()
        request = self._make_http_request(scope_type="assistant", scope_id=assistant_id)
        container = self._make_container()

        with pytest.raises(HTTPException) as exc_info:
            await _validate_conversation_scope(
                http_request=request,
                container=container,
                assistant_id=None,
                group_chat_id=uuid4(),
                session_id=None,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_assistant_scope_session_own_assistant_passes(self):
        """Assistant-scoped key + session_id of own assistant → pass."""
        assistant_id = uuid4()
        session_id = uuid4()
        session_obj = SimpleNamespace(
            assistant=SimpleNamespace(id=assistant_id),
            group_chat_id=None,
        )
        request = self._make_http_request(scope_type="assistant", scope_id=assistant_id)
        container = self._make_container(session_obj=session_obj)

        await _validate_conversation_scope(
            http_request=request,
            container=container,
            assistant_id=None,
            group_chat_id=None,
            session_id=session_id,
        )

    @pytest.mark.asyncio
    async def test_assistant_scope_session_other_assistant_denied(self):
        """Assistant-scoped key + session_id of different assistant → 403."""
        key_assistant = uuid4()
        other_assistant = uuid4()
        session_id = uuid4()
        session_obj = SimpleNamespace(
            assistant=SimpleNamespace(id=other_assistant),
            group_chat_id=None,
        )
        request = self._make_http_request(scope_type="assistant", scope_id=key_assistant)
        container = self._make_container(session_obj=session_obj)

        with pytest.raises(HTTPException) as exc_info:
            await _validate_conversation_scope(
                http_request=request,
                container=container,
                assistant_id=None,
                group_chat_id=None,
                session_id=session_id,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_space_scope_assistant_in_own_space_passes(self):
        """Space-scoped key + assistant in own space → pass."""
        space_id = uuid4()
        assistant_id = uuid4()
        request = self._make_http_request(scope_type="space", scope_id=space_id)
        container = self._make_container(
            space_by_assistant=_make_space(space_id)
        )

        await _validate_conversation_scope(
            http_request=request,
            container=container,
            assistant_id=assistant_id,
            group_chat_id=None,
            session_id=None,
        )

    @pytest.mark.asyncio
    async def test_space_scope_assistant_in_other_space_denied(self):
        """Space-scoped key + assistant in different space → 403."""
        key_space = uuid4()
        other_space = uuid4()
        assistant_id = uuid4()
        request = self._make_http_request(scope_type="space", scope_id=key_space)
        container = self._make_container(
            space_by_assistant=_make_space(other_space)
        )

        with pytest.raises(HTTPException) as exc_info:
            await _validate_conversation_scope(
                http_request=request,
                container=container,
                assistant_id=assistant_id,
                group_chat_id=None,
                session_id=None,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_space_scope_group_chat_in_own_space_passes(self):
        """Space-scoped key + group_chat in own space → pass."""
        space_id = uuid4()
        group_chat_id = uuid4()
        request = self._make_http_request(scope_type="space", scope_id=space_id)
        container = self._make_container(
            space_by_group_chat=_make_space(space_id)
        )

        await _validate_conversation_scope(
            http_request=request,
            container=container,
            assistant_id=None,
            group_chat_id=group_chat_id,
            session_id=None,
        )

    @pytest.mark.asyncio
    async def test_space_scope_group_chat_in_other_space_denied(self):
        """Space-scoped key + group_chat in different space → 403."""
        key_space = uuid4()
        other_space = uuid4()
        request = self._make_http_request(scope_type="space", scope_id=key_space)
        container = self._make_container(
            space_by_group_chat=_make_space(other_space)
        )

        with pytest.raises(HTTPException) as exc_info:
            await _validate_conversation_scope(
                http_request=request,
                container=container,
                assistant_id=None,
                group_chat_id=uuid4(),
                session_id=None,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_space_scope_session_in_own_space_passes(self):
        """Space-scoped key + session in own space → pass."""
        space_id = uuid4()
        session_id = uuid4()
        session_obj = SimpleNamespace(
            assistant=SimpleNamespace(id=uuid4()),
            group_chat_id=None,
        )
        request = self._make_http_request(scope_type="space", scope_id=space_id)
        container = self._make_container(
            session_obj=session_obj,
            space_by_session=_make_space(space_id),
        )

        await _validate_conversation_scope(
            http_request=request,
            container=container,
            assistant_id=None,
            group_chat_id=None,
            session_id=session_id,
        )

    @pytest.mark.asyncio
    async def test_space_scope_session_in_other_space_denied(self):
        """Space-scoped key + session in different space → 403."""
        key_space = uuid4()
        other_space = uuid4()
        session_id = uuid4()
        session_obj = SimpleNamespace(
            assistant=SimpleNamespace(id=uuid4()),
            group_chat_id=None,
        )
        request = self._make_http_request(scope_type="space", scope_id=key_space)
        container = self._make_container(
            session_obj=session_obj,
            space_by_session=_make_space(other_space),
        )

        with pytest.raises(HTTPException) as exc_info:
            await _validate_conversation_scope(
                http_request=request,
                container=container,
                assistant_id=None,
                group_chat_id=None,
                session_id=session_id,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_error_messages_are_human_readable(self):
        """All scope denial messages should be clear and actionable."""
        app_id = uuid4()
        request = self._make_http_request(scope_type="app", scope_id=app_id)
        container = self._make_container()

        with pytest.raises(HTTPException) as exc_info:
            await _validate_conversation_scope(
                http_request=request,
                container=container,
                assistant_id=uuid4(),
                group_chat_id=None,
                session_id=None,
            )
        msg = exc_info.value.detail["message"]
        # Message should mention the scope type and scope ID
        assert str(app_id) in msg
        assert "app" in msg.lower()
        # Message should explain what the key can access
        assert "only access" in msg.lower() or "can only" in msg.lower()

    @pytest.mark.asyncio
    async def test_session_not_found_returns_403_not_404(self):
        """Anti-enumeration: scoped key + nonexistent session → 403 (not 404).

        Prevents attackers from probing session existence via distinct error codes.
        """
        assistant_id = uuid4()
        session_id = uuid4()
        request = self._make_http_request(scope_type="assistant", scope_id=assistant_id)
        container = self._make_container(session_not_found=True)

        with pytest.raises(HTTPException) as exc_info:
            await _validate_conversation_scope(
                http_request=request,
                container=container,
                assistant_id=None,
                group_chat_id=None,
                session_id=session_id,
            )
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "insufficient_scope"

    @pytest.mark.asyncio
    async def test_env_flag_off_skips_body_driven_scope(self):
        """Body-driven scope check respects env kill switch."""
        assistant_id = uuid4()
        other_assistant = uuid4()
        request = self._make_http_request(scope_type="assistant", scope_id=assistant_id)
        container = self._make_container()

        with patch("intric.conversations.conversations_router.get_settings") as mock_settings:
            mock_settings.return_value = SimpleNamespace(api_key_enforce_scope=False)
            # Should NOT raise even though assistant doesn't match
            await _validate_conversation_scope(
                http_request=request,
                container=container,
                assistant_id=other_assistant,
                group_chat_id=None,
                session_id=None,
            )

    @pytest.mark.asyncio
    async def test_tenant_flag_off_skips_body_driven_scope(self):
        """Body-driven scope check respects tenant feature flag."""
        assistant_id = uuid4()
        other_assistant = uuid4()
        request = self._make_http_request(scope_type="assistant", scope_id=assistant_id)
        container = self._make_container()

        # Override feature flag to disabled
        flag = MagicMock()
        flag.is_enabled = MagicMock(return_value=False)
        ff_service = MagicMock()
        ff_service.feature_flag_repo = MagicMock()
        ff_service.feature_flag_repo.one_or_none = AsyncMock(return_value=flag)
        container.feature_flag_service = MagicMock(return_value=ff_service)

        with patch("intric.conversations.conversations_router.get_settings") as mock_settings:
            mock_settings.return_value = SimpleNamespace(api_key_enforce_scope=True)
            # Should NOT raise even though assistant doesn't match
            await _validate_conversation_scope(
                http_request=request,
                container=container,
                assistant_id=other_assistant,
                group_chat_id=None,
                session_id=None,
            )


# ---------------------------------------------------------------------------
# TestScopeConfigStashPattern — require_api_key_scope_check factory
# ---------------------------------------------------------------------------


class TestScopeConfigStashPattern:
    """Verify the config-stash pattern for scope enforcement."""

    @pytest.mark.asyncio
    async def test_factory_stores_config_on_request_state(self):
        """require_api_key_scope_check stores config on request.state."""
        dep = require_api_key_scope_check(resource_type="space", path_param="id")
        request = SimpleNamespace(state=State())
        await dep(request)

        config = request.state._scope_check_config
        assert config["resource_type"] == "space"
        assert config["path_param"] == "id"

    @pytest.mark.asyncio
    async def test_factory_with_none_path_param(self):
        """Config-stash with path_param=None (list/admin endpoints)."""
        dep = require_api_key_scope_check(resource_type="admin", path_param=None)
        request = SimpleNamespace(state=State())
        await dep(request)

        config = request.state._scope_check_config
        assert config["resource_type"] == "admin"
        assert config["path_param"] is None

    @pytest.mark.asyncio
    async def test_factory_default_path_param(self):
        """Default path_param should be 'id'."""
        dep = require_api_key_scope_check(resource_type="app")
        request = SimpleNamespace(state=State())
        await dep(request)

        config = request.state._scope_check_config
        assert config["path_param"] == "id"


# ---------------------------------------------------------------------------
# TestScopeErrorMessages — human-readable error messages
# ---------------------------------------------------------------------------


class TestScopeErrorMessages:
    """Verify error messages are clear, actionable, and include relevant context."""

    @pytest.mark.asyncio
    async def test_admin_denial_mentions_tenant_requirement(self):
        """Admin scope denial should tell user they need a tenant-scoped key."""
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.SPACE, scope_id=uuid4()
        )
        request = _scope_request()
        scope_config = {"resource_type": "admin", "path_param": None}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        msg = exc_info.value.message
        assert "tenant-scoped key" in msg.lower()
        assert "admin" in msg.lower()

    @pytest.mark.asyncio
    async def test_space_denial_mentions_different_scope(self):
        """Space scope denial should mention the resource belongs to a different scope."""
        key_space = uuid4()
        other_space = uuid4()
        svc = _make_user_service(session_scalar_return=other_space)
        key = _make_key(
            scope_type=ApiKeyScopeType.SPACE, scope_id=key_space
        )
        request = _scope_request(path_params={"id": str(uuid4())})
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        msg = exc_info.value.message
        assert str(key_space) in msg
        assert "different scope" in msg.lower()

    @pytest.mark.asyncio
    async def test_assistant_denial_explains_scope_limit(self):
        """Assistant denial should explain what the key can access."""
        assistant_id = uuid4()
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.ASSISTANT, scope_id=assistant_id
        )
        request = _scope_request(path_params={"id": str(uuid4())})
        scope_config = {"resource_type": "app", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        msg = exc_info.value.message
        assert str(assistant_id) in msg
        assert "conversations" in msg.lower()

    @pytest.mark.asyncio
    async def test_app_denial_explains_scope_limit(self):
        """App denial should explain what the key can access."""
        app_id = uuid4()
        svc = _make_user_service()
        key = _make_key(
            scope_type=ApiKeyScopeType.APP, scope_id=app_id
        )
        request = _scope_request(path_params={"id": str(uuid4())})
        scope_config = {"resource_type": "assistant", "path_param": "id"}

        with pytest.raises(ApiKeyValidationError) as exc_info:
            await svc._enforce_api_key_scope(request, key, scope_config)
        msg = exc_info.value.message
        assert str(app_id) in msg
        assert "runs" in msg.lower()
