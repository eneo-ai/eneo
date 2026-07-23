"""Tests for structured audit logging in SettingService toggle methods.

Verifies that all 4 toggle methods produce audit log entries with:
- ActionType.TENANT_SETTINGS_UPDATED
- EntityType.TENANT_SETTINGS
- Correct setting name, old/new values, and actor/tenant context
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.main.exceptions import UnauthorizedException
from eneo.settings.setting_service import SettingService
from eneo.skills.domain.skill import SkillExecutionBlock, SkillExecutionBlockChange

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


def _make_service(
    user: SimpleNamespace | None = None,
) -> tuple[SettingService, AsyncMock]:
    """Build a SettingService with mocked dependencies. Returns (service, audit_mock)."""
    if user is None:
        user = _make_user()

    repo = AsyncMock()
    repo.get = AsyncMock(return_value=SimpleNamespace(chatbot_widget={}))

    ai_models_service = MagicMock()

    feature_flag_service = AsyncMock()
    feature_flag_service.feature_flag_repo = AsyncMock()
    feature_flag_service.check_is_feature_enabled = AsyncMock(return_value=False)
    feature_flag_service.check_is_feature_enabled_fail_closed = AsyncMock(
        return_value=False
    )

    tenant_repo = AsyncMock()
    tenant_repo.get = AsyncMock(
        return_value=SimpleNamespace(id=user.tenant_id, provisioning=False)
    )

    audit_service = AsyncMock()
    audit_service.log_async = AsyncMock(return_value=uuid4())
    skill_repo = AsyncMock()

    service = SettingService(
        repo=repo,
        user=user,
        ai_models_service=ai_models_service,
        feature_flag_service=feature_flag_service,
        tenant_repo=tenant_repo,
        audit_service=audit_service,
        skill_repo=skill_repo,
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


class TestSkillExecutionBlockAudit:
    @staticmethod
    def _block(service: SettingService) -> SkillExecutionBlock:
        now = datetime.now(timezone.utc)
        return SkillExecutionBlock(
            id=uuid4(),
            tenant_id=service.user.tenant_id,
            skill_space_id=uuid4(),
            skill_id=uuid4(),
            blocked_by_user_id=service.user.id,
            reason="Confirmed unsafe instructions",
            blocked_at=now,
        )

    @pytest.mark.asyncio
    async def test_block_records_typed_old_and_new_setting_values(self):
        service, audit_mock = _make_service()
        block = self._block(service)
        service.skill_repo.get_organization_for_tenant.return_value = SimpleNamespace(
            first_published_at=datetime.now(timezone.utc)
        )
        service.skill_repo.block_organization_skill.return_value = (
            SkillExecutionBlockChange(block=block, changed=True)
        )

        state = await service.block_skill_execution(
            skill_id=block.skill_id,
            reason="  Confirmed unsafe instructions  ",
        )

        assert state.block is not None
        assert state.block.id == block.id
        service.skill_repo.block_organization_skill.assert_awaited_once_with(
            tenant_id=service.user.tenant_id,
            skill_id=block.skill_id,
            blocked_by_user_id=service.user.id,
            reason="Confirmed unsafe instructions",
        )
        call_kwargs = audit_mock.log_async.call_args.kwargs
        assert call_kwargs["action"] == ActionType.TENANT_SETTINGS_UPDATED
        assert call_kwargs["entity_type"] == EntityType.TENANT_SETTINGS
        assert call_kwargs["metadata"]["setting"] == "skill_execution_block"
        change = call_kwargs["metadata"]["changes"]["skill_execution_block"]
        assert change["old"] is None
        assert change["new"]["id"] == str(block.id)
        assert change["new"]["reason"] == block.reason

    @pytest.mark.asyncio
    async def test_execution_block_state_requires_tenant_admin(self):
        service, _ = _make_service(user=_make_user(permissions=[]))

        with pytest.raises(UnauthorizedException, match="Need permission admin"):
            await service.get_skill_execution_block(skill_id=uuid4())

        service.skill_repo.get_organization_for_tenant.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unblock_records_recovery_reason_and_closed_time(self):
        service, audit_mock = _make_service()
        active = self._block(service)
        released = replace(
            active,
            unblocked_by_user_id=service.user.id,
            unblock_reason="Removed the harmful revision",
            unblocked_at=datetime.now(timezone.utc),
        )
        service.skill_repo.get_organization_for_tenant.return_value = SimpleNamespace(
            first_published_at=datetime.now(timezone.utc)
        )
        service.skill_repo.unblock_organization_skill.return_value = (
            SkillExecutionBlockChange(block=released, changed=True)
        )

        state = await service.unblock_skill_execution(
            skill_id=active.skill_id,
            expected_block_id=active.id,
            reason=" Removed the harmful revision ",
        )

        assert state.block is None
        call_kwargs = audit_mock.log_async.call_args.kwargs
        change = call_kwargs["metadata"]["changes"]["skill_execution_block"]
        assert change["old"]["id"] == str(active.id)
        assert change["new"] is None
        assert call_kwargs["metadata"]["reason"] == released.unblock_reason
        assert call_kwargs["metadata"]["changed_at"] == (
            released.unblocked_at.isoformat()
        )


class TestSettingToggleAuditLoggingAdditional:
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
        assert (
            call_kwargs["metadata"]["changes"]["audit_logging_enabled"]["new"] is False
        )
        # old value comes from check_is_feature_enabled mock (returns False)
        assert (
            call_kwargs["metadata"]["changes"]["audit_logging_enabled"]["old"] is False
        )

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
    async def test_audit_log_includes_actor(self):
        """Audit entry must include who made the change."""
        user = _make_user()
        service, audit_mock = _make_service(user=user)
        service.feature_flag_service.feature_flag_repo.one_or_none = AsyncMock(
            return_value=_make_feature_flag("using_templates")
        )

        await service.update_template_setting(enabled=True)

        call_kwargs = audit_mock.log_async.call_args[1]
        assert call_kwargs["user"] is user
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
        service.feature_flag_service.check_is_feature_enabled = AsyncMock(
            return_value=True
        )
        service.feature_flag_service.feature_flag_repo.one_or_none = AsyncMock(
            return_value=_make_feature_flag("using_templates")
        )

        # Toggle to True when already True → idempotent
        await service.update_template_setting(enabled=True)

        call_kwargs = audit_mock.log_async.call_args[1]
        assert call_kwargs["metadata"]["changes"]["using_templates"]["old"] is True
        assert call_kwargs["metadata"]["changes"]["using_templates"]["new"] is True
