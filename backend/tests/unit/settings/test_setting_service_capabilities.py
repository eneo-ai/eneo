"""Read-only capability flags projected by SettingService._build_settings_public.

These flags are computed from deployment state, never persisted, and exist so
the UI can gate features the deployment cannot deliver.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.settings import setting_service
from eneo.settings.setting_service import SettingService


def _make_service(*, object_store_configured: bool) -> SettingService:
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        username="admin-user",
        email="admin@example.com",
        permissions=["admin"],
    )

    repo = AsyncMock()
    repo.get = AsyncMock(return_value=SimpleNamespace(chatbot_widget={}))

    feature_flag_service = AsyncMock()
    feature_flag_service.check_is_feature_enabled = AsyncMock(return_value=False)

    tenant_repo = AsyncMock()
    tenant_repo.get = AsyncMock(
        return_value=SimpleNamespace(id=user.tenant_id, provisioning=False)
    )

    object_content = SimpleNamespace(
        enabled=True,
        object_store_configured=object_store_configured,
    )

    return SettingService(
        repo=repo,
        user=user,
        ai_models_service=MagicMock(),
        feature_flag_service=feature_flag_service,
        tenant_repo=tenant_repo,
        audit_service=AsyncMock(),
        data_retention_service=AsyncMock(),
        skill_repo=AsyncMock(),
        object_content=object_content,
    )


async def test_object_store_configured_follows_the_runtime_connection():
    service = _make_service(object_store_configured=True)

    settings = await service.get_settings()

    assert settings.object_store_configured is True


async def test_object_store_configured_is_false_without_a_connection():
    service = _make_service(object_store_configured=False)

    settings = await service.get_settings()

    assert settings.object_store_configured is False


async def test_file_references_enabled_is_independent_of_object_storage(monkeypatch):
    """A reference base URL still enables minting; the storage flag is separate."""
    monkeypatch.setattr(
        setting_service,
        "file_reference_base_url",
        lambda _settings: "https://eneo.example.com",
    )

    service = _make_service(object_store_configured=False)
    settings = await service.get_settings()

    assert settings.file_references_enabled is True
    assert settings.object_store_configured is False
