from unittest.mock import MagicMock

from eneo.object_content.runtime import ObjectContentRuntime
from eneo.settings.setting_service import SettingService
from eneo.settings.settings import (
    ChunkingPolicyPublic,
    SettingsBase,
    SettingsInDB,
    SettingsPublic,
    SettingsUpsert,
)
from tests.fixtures import TEST_USER, TEST_UUID

TEST_SETTINGS = SettingsPublic(chunking=ChunkingPolicyPublic.from_platform())
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
        return False


class MockTenantRepo:
    """Mock tenant repo for testing."""

    async def get(self, tenant_id):
        # Return a mock tenant with provisioning=False
        from eneo.tenants.tenant import TenantInDB, TenantState

        return TenantInDB(
            id=tenant_id,
            name="Test Tenant",
            quota_limit=1024**3,
            modules=[],
            api_credentials={},
            federation_config={},
            state=TenantState.ACTIVE,
            provisioning=False,
        )


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
        skill_repo=MagicMock(),
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
        skill_repo=MagicMock(),
    )

    repo.settings[TEST_USER.id] = TEST_SETTINGS_EXPECTED
    new_settings = SettingsBase(chatbot_widget={"colour": "blue"})
    settings_expected = SettingsInDB(
        **new_settings.model_dump(), id=TEST_UUID, user_id=TEST_USER.id
    )

    settings = await service.update_settings(new_settings)

    assert settings.chatbot_widget == settings_expected.chatbot_widget
    assert settings.using_templates == False
    assert repo.settings[TEST_USER.id] == settings_expected


async def test_update_settings_creates_row_when_missing():
    repo = MockRepo()
    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=MockTenantRepo(),
        audit_service=MockAuditService(),
        skill_repo=MagicMock(),
    )

    new_settings = SettingsBase(chatbot_widget={"preferred_text_format": "richtext"})

    settings = await service.update_settings(new_settings)

    assert settings.chatbot_widget == {"preferred_text_format": "richtext"}
    assert repo.settings[TEST_USER.id].chatbot_widget == {
        "preferred_text_format": "richtext"
    }


async def test_settings_project_object_content_as_a_read_only_capability():
    repo = MockRepo()
    runtime = MagicMock(spec=ObjectContentRuntime)
    runtime.enabled = True
    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=MockTenantRepo(),
        audit_service=MockAuditService(),
        skill_repo=MagicMock(),
        object_content=runtime,
    )

    settings = await service.get_settings()

    assert settings.object_content_enabled is True


def test_settings_write_model_accepts_an_echoed_public_response() -> None:
    echoed_response = SettingsPublic(
        chatbot_widget={"colour": "blue"},
        object_content_enabled=True,
        chunking=ChunkingPolicyPublic.from_platform(),
    )

    writable = SettingsBase.model_validate(echoed_response.model_dump())

    assert writable == SettingsBase(chatbot_widget={"colour": "blue"})
    assert "object_content_enabled" not in writable.model_dump()
