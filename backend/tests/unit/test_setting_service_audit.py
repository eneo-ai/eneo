"""Tests for structured audit logging in SettingService toggle methods.

Verifies that all 4 toggle methods produce audit log entries with:
- ActionType.TENANT_SETTINGS_UPDATED
- EntityType.TENANT_SETTINGS
- Correct setting name, old/new values, and actor/tenant context
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.settings.setting_service import SettingService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_user(**overrides: Any) -> SimpleNamespace:
    base = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "username": "admin-user",
        "email": "admin@example.com",
        "permissions": ["admin"],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_feature_flag(name: str = "test_flag") -> SimpleNamespace:
    return SimpleNamespace(feature_id=uuid4(), name=name)


def _make_service(user: SimpleNamespace | None = None) -> tuple[SettingService, AsyncMock]:
    """Build a SettingService with mocked dependencies. Returns (service, audit_mock)."""
    if user is None:
        user = _make_user()

    repo = AsyncMock()
    repo.get = AsyncMock(return_value=SimpleNamespace(chatbot_widget={}))

    ai_models_service = MagicMock()

    feature_flag_service = AsyncMock()
    feature_flag_service.feature_flag_repo = AsyncMock()
    feature_flag_service.check_is_feature_enabled = AsyncMock(return_value=False)

    tenant_repo = AsyncMock()
    tenant_repo.get = AsyncMock(return_value=SimpleNamespace(
        id=user.tenant_id, provisioning=False
    ))

    audit_service = AsyncMock()
    audit_service.log_async = AsyncMock(return_value=uuid4())

    service = SettingService(
        repo=repo,
        user=user,
        ai_models_service=ai_models_service,
        feature_flag_service=feature_flag_service,
        tenant_repo=tenant_repo,
        audit_service=audit_service,
    )

    return service, audit_service


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSettingToggleAuditLogging:
    """Each toggle method must produce a structured audit log entry."""

    @pytest.mark.asyncio
    async def test_update_template_setting_logs_audit(self):
        service, audit_mock = _make_service()
        service.feature_flag_service.feature_flag_repo.one_or_none = AsyncMock(
            return_value=_make_feature_flag("using_templates")
        )

        await service.update_template_setting(enabled=True)

        audit_mock.log_async.assert_called_once()
        call_kwargs = audit_mock.log_async.call_args[1]
        assert call_kwargs["action"] == ActionType.TENANT_SETTINGS_UPDATED
        assert call_kwargs["entity_type"] == EntityType.TENANT_SETTINGS
        assert call_kwargs["entity_id"] == service.user.tenant_id
        assert call_kwargs["metadata"]["setting"] == "using_templates"
        assert call_kwargs["metadata"]["changes"]["using_templates"]["new"] is True
        # old value comes from check_is_feature_enabled mock (returns False)
        assert call_kwargs["metadata"]["changes"]["using_templates"]["old"] is False

    @pytest.mark.asyncio
    async def test_update_audit_logging_setting_logs_audit(self):
        service, audit_mock = _make_service()
        service.feature_flag_service.feature_flag_repo.one_or_none = AsyncMock(
            return_value=_make_feature_flag("audit_logging_enabled")
        )

        await service.update_audit_logging_setting(enabled=False)

        audit_mock.log_async.assert_called_once()
        call_kwargs = audit_mock.log_async.call_args[1]
        assert call_kwargs["action"] == ActionType.TENANT_SETTINGS_UPDATED
        assert call_kwargs["metadata"]["setting"] == "audit_logging_enabled"
        assert call_kwargs["metadata"]["changes"]["audit_logging_enabled"]["new"] is False
        # old value comes from check_is_feature_enabled mock (returns False)
        assert call_kwargs["metadata"]["changes"]["audit_logging_enabled"]["old"] is False

    @pytest.mark.asyncio
    async def test_update_provisioning_setting_logs_audit(self):
        service, audit_mock = _make_service()

        await service.update_provisioning_setting(enabled=True)

        audit_mock.log_async.assert_called_once()
        call_kwargs = audit_mock.log_async.call_args[1]
        assert call_kwargs["action"] == ActionType.TENANT_SETTINGS_UPDATED
        assert call_kwargs["metadata"]["setting"] == "provisioning"
        assert call_kwargs["metadata"]["changes"]["provisioning"]["new"] is True
        # old value comes from tenant_repo.get mock (provisioning=False)
        assert call_kwargs["metadata"]["changes"]["provisioning"]["old"] is False

    @pytest.mark.asyncio
    async def test_update_scope_enforcement_setting_logs_audit(self):
        service, audit_mock = _make_service()
        service.feature_flag_service.feature_flag_repo.one_or_none = AsyncMock(
            return_value=_make_feature_flag("api_key_scope_enforcement")
        )

        await service.update_scope_enforcement_setting(enabled=True)

        audit_mock.log_async.assert_called_once()
        call_kwargs = audit_mock.log_async.call_args[1]
        assert call_kwargs["action"] == ActionType.TENANT_SETTINGS_UPDATED
        assert call_kwargs["metadata"]["setting"] == "api_key_scope_enforcement"
        assert call_kwargs["metadata"]["changes"]["api_key_scope_enforcement"]["new"] is True
        # old value comes from check_is_feature_enabled mock (returns False)
        assert call_kwargs["metadata"]["changes"]["api_key_scope_enforcement"]["old"] is False

    @pytest.mark.asyncio
    async def test_audit_log_includes_actor_id(self):
        """Audit entry must include who made the change."""
        user = _make_user()
        service, audit_mock = _make_service(user=user)
        service.feature_flag_service.feature_flag_repo.one_or_none = AsyncMock(
            return_value=_make_feature_flag("using_templates")
        )

        await service.update_template_setting(enabled=True)

        call_kwargs = audit_mock.log_async.call_args[1]
        assert call_kwargs["actor_id"] == user.id
        assert call_kwargs["tenant_id"] == user.tenant_id

    @pytest.mark.asyncio
    async def test_audit_log_description_contains_setting_name(self):
        """Description should be human-readable with setting name and value."""
        service, audit_mock = _make_service()

        await service.update_provisioning_setting(enabled=False)

        call_kwargs = audit_mock.log_async.call_args[1]
        assert "provisioning" in call_kwargs["description"]
        assert "False" in call_kwargs["description"]

    @pytest.mark.asyncio
    async def test_idempotent_toggle_logs_same_old_and_new(self):
        """When toggling to the same value, audit logs old==new (real query, no synthetic)."""
        service, audit_mock = _make_service()
        # Mock check_is_feature_enabled returns True (already enabled)
        service.feature_flag_service.check_is_feature_enabled = AsyncMock(return_value=True)
        service.feature_flag_service.feature_flag_repo.one_or_none = AsyncMock(
            return_value=_make_feature_flag("using_templates")
        )

        # Toggle to True when already True → idempotent
        await service.update_template_setting(enabled=True)

        call_kwargs = audit_mock.log_async.call_args[1]
        assert call_kwargs["metadata"]["changes"]["using_templates"]["old"] is True
        assert call_kwargs["metadata"]["changes"]["using_templates"]["new"] is True
