from types import SimpleNamespace

import pytest

from intric.main.exceptions import BadRequestException
from intric.settings.setting_service import SettingService
from intric.settings.settings import (
    AIBuilderBudgetSettingsUpdate,
    FlowInputLimitsUpdate,
    SettingsInDB,
    SettingsPublic,
    SettingsUpsert,
)
from tests.fixtures import TEST_USER, TEST_UUID

TEST_SETTINGS = SettingsPublic()
TEST_SETTINGS_EXPECTED = SettingsInDB(
    user_id=TEST_USER.id,
    id=TEST_UUID,
)


class MockRepo:
    def __init__(self):
        self.settings = {}

    async def get(self, user_id):
        return self.settings.get(user_id)

    async def add(self, settings: SettingsUpsert):
        settings_in_db = SettingsInDB(**settings.model_dump(), id=TEST_UUID)
        self.settings[settings.user_id] = settings_in_db
        return settings_in_db

    async def update(self, settings: SettingsUpsert):
        curr_settings = self.settings[settings.user_id]
        settings_in_db = SettingsInDB(**settings.model_dump(), id=curr_settings.id)
        self.settings[settings.user_id] = settings_in_db
        return settings_in_db


class MockFeatureFlagService:
    """Mock feature flag service for testing."""
    async def check_is_feature_enabled(self, feature_name: str, tenant_id=None):
        # Return False for using_templates by default (feature disabled)
        return False

    async def check_is_feature_enabled_fail_closed(
        self, feature_name: str, tenant_id=None
    ):
        # Scope enforcement is fail-closed by default when no explicit flag exists.
        if feature_name == "api_key_scope_enforcement":
            return True
        return False


class MockTenantRepo:
    """Mock tenant repo for testing."""

    def __init__(self):
        self.tenant = None

    async def get(self, tenant_id):
        # Return a mock tenant with provisioning=False
        from intric.tenants.tenant import TenantInDB, TenantState

        if self.tenant is None:
            self.tenant = TenantInDB(
                id=tenant_id,
                name="Test Tenant",
                quota_limit=1024**3,
                modules=[],
                api_credentials={},
                federation_config={},
                state=TenantState.ACTIVE,
                provisioning=False,
                flow_settings={},
            )

        return self.tenant

    async def set_flow_settings(self, tenant_id, flow_settings):
        tenant = await self.get(tenant_id)
        self.tenant = tenant.model_copy(update={"flow_settings": flow_settings})
        return self.tenant


class MockAuditService:
    """Mock audit service for testing."""
    async def log_async(self, *args, **kwargs):
        pass


async def test_get_settings_if_settings():
    repo = MockRepo()

    repo.settings[TEST_USER.id] = TEST_SETTINGS_EXPECTED

    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=MockTenantRepo(),
        audit_service=MockAuditService(),
    )

    settings = await service.get_settings()

    assert settings.chatbot_widget == TEST_SETTINGS_EXPECTED.chatbot_widget
    assert settings.using_templates == False  # Feature flag disabled in mock


async def test_update_settings():
    repo = MockRepo()
    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=MockTenantRepo(),
        audit_service=MockAuditService(),
    )

    repo.settings[TEST_USER.id] = TEST_SETTINGS_EXPECTED
    new_settings = SettingsPublic(chatbot_widget={"colour": "blue"})
    settings_expected = SettingsInDB(
        **new_settings.model_dump(), id=TEST_UUID, user_id=TEST_USER.id
    )

    settings = await service.update_settings(new_settings)

    assert settings == settings_expected
    assert repo.settings[TEST_USER.id] == settings_expected


async def test_get_flow_input_limits_reads_tenant_override(monkeypatch):
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    tenant_repo.tenant = tenant.model_copy(
        update={
            "flow_settings": {
                "input_limits": {
                    "file_max_size_bytes": 12_000_000,
                    "audio_max_size_bytes": 28_000_000,
                }
            }
        }
    )

    monkeypatch.setattr(
        "intric.flows.flow_input_limits.get_settings",
        lambda: SimpleNamespace(
            upload_max_file_size=10_000_000,
            transcription_max_file_size=25_000_000,
        ),
    )

    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=MockAuditService(),
    )

    limits = await service.get_flow_input_limits()

    assert limits.file_max_size_bytes == 12_000_000
    assert limits.audio_max_size_bytes == 28_000_000


async def test_update_flow_input_limits_persists_and_audits(monkeypatch):
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    audit_service = MockAuditService()

    calls = []

    async def _capture(*args, **kwargs):
        calls.append(kwargs)

    audit_service.log_async = _capture

    monkeypatch.setattr(
        "intric.flows.flow_input_limits.get_settings",
        lambda: SimpleNamespace(
            upload_max_file_size=10_000_000,
            transcription_max_file_size=25_000_000,
        ),
    )

    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=audit_service,
    )

    updated = await service.update_flow_input_limits(
        FlowInputLimitsUpdate(audio_max_size_bytes=35_000_000)
    )

    assert updated.audio_max_size_bytes == 35_000_000
    assert updated.file_max_size_bytes == 10_000_000

    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    assert tenant.flow_settings["input_limits"]["audio_max_size_bytes"] == 35_000_000
    assert len(calls) == 1
    assert calls[0]["metadata"]["setting"] == "flow_input_limits"


async def test_update_flow_input_limits_rejects_empty_patch():
    repo = MockRepo()
    tenant_repo = MockTenantRepo()

    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=MockAuditService(),
    )

    with pytest.raises(BadRequestException, match="At least one flow input limit field"):
        await service.update_flow_input_limits(FlowInputLimitsUpdate())


async def test_get_ai_builder_budget_settings_reads_tenant_override(monkeypatch):
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    tenant_repo.tenant = tenant.model_copy(
        update={
            "flow_settings": {
                "ai_builder": {
                    "conversation_safety_buffer_tokens": 1234,
                    "minimum_conversation_budget_tokens": 5678,
                }
            }
        }
    )

    monkeypatch.setattr(
        "intric.flows.ai_builder.ai_builder_settings.get_settings",
        lambda: SimpleNamespace(
            ai_builder_conversation_safety_buffer_tokens=2000,
            ai_builder_minimum_conversation_budget_tokens=4000,
            ai_builder_unknown_model_context_window_tokens=None,
        ),
    )

    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=MockAuditService(),
    )

    settings = await service.get_ai_builder_budget_settings()

    assert settings.conversation_safety_buffer_tokens == 1234
    assert settings.minimum_conversation_budget_tokens == 5678
    assert settings.unknown_model_context_window_tokens is None


async def test_update_ai_builder_budget_settings_persists_and_audits(monkeypatch):
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    audit_service = MockAuditService()
    calls = []

    async def _capture(*args, **kwargs):
        calls.append(kwargs)

    audit_service.log_async = _capture

    monkeypatch.setattr(
        "intric.flows.ai_builder.ai_builder_settings.get_settings",
        lambda: SimpleNamespace(
            ai_builder_conversation_safety_buffer_tokens=2000,
            ai_builder_minimum_conversation_budget_tokens=4000,
            ai_builder_unknown_model_context_window_tokens=128000,
        ),
    )

    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=audit_service,
    )

    updated = await service.update_ai_builder_budget_settings(
        AIBuilderBudgetSettingsUpdate(
            conversation_safety_buffer_tokens=1500,
            unknown_model_context_window_tokens=None,
        )
    )

    assert updated.conversation_safety_buffer_tokens == 1500
    assert updated.minimum_conversation_budget_tokens == 4000
    assert updated.unknown_model_context_window_tokens == 128000

    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    assert tenant.flow_settings["ai_builder"]["conversation_safety_buffer_tokens"] == 1500
    assert "unknown_model_context_window_tokens" not in tenant.flow_settings["ai_builder"]
    assert len(calls) == 1
    assert calls[0]["metadata"]["setting"] == "ai_builder_budget_settings"


async def test_update_ai_builder_budget_settings_rejects_empty_patch():
    repo = MockRepo()
    tenant_repo = MockTenantRepo()

    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=MockAuditService(),
    )

    with pytest.raises(BadRequestException, match="At least one AI Builder budget field"):
        await service.update_ai_builder_budget_settings(AIBuilderBudgetSettingsUpdate())
