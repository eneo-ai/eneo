from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

from eneo.data_retention.infrastructure.data_retention_service import (
    FlowRetentionControlPlaneState,
    FlowRetentionOrganizationChangeDecision,
    FlowRetentionOrganizationProposal,
)
from eneo.flows.flow_evidence_policy import (
    FLOW_EVIDENCE_POLICY_STORAGE_VERSION,
    FLOW_EVIDENCE_POLICY_STORAGE_VERSION_KEY,
)
from eneo.flows.flow_retention_policy import (
    FLOW_RETENTION_POLICY_STORAGE_VERSION,
    FLOW_RETENTION_POLICY_STORAGE_VERSION_KEY,
)
from eneo.main.exceptions import BadRequestException
from eneo.settings.setting_service import SettingService
from eneo.settings.settings import (
    AIBuilderBudgetSettingsUpdate,
    FlowClassificationRetentionPolicyUpdate,
    FlowDocumentRenderLimitsUpdate,
    FlowEvidencePolicyUpdate,
    FlowInputLimitsUpdate,
    FlowRetentionPolicyUpdate,
    FlowRuntimePolicyUpdate,
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
        return False


class MockTenantRepo:
    """Mock tenant repo for testing."""

    def __init__(self):
        self.tenant = None

    async def get(self, tenant_id):
        # Return a mock tenant with provisioning=False
        from eneo.tenants.tenant import TenantInDB, TenantState

        if self.tenant is not None:
            return self.tenant
        self.tenant = TenantInDB(
            id=tenant_id,
            name="Test Tenant",
            quota_limit=1024**3,
            modules=[],
            api_credentials={},
            federation_config={},
            state=TenantState.ACTIVE,
            provisioning=False,
        )
        return self.tenant

    async def update_tenant(self, update):
        tenant = await self.get(update.id)
        self.tenant = tenant.model_copy(
            update=update.model_dump(exclude_unset=True, exclude={"id"})
        )
        return self.tenant


class MockAuditService:
    """Mock audit service for testing."""

    async def log_async(self, *args, **kwargs):
        pass

    async def log(self, *args, **kwargs):
        pass


class MockDataRetentionService:
    async def get_flow_retention_control_plane_state(self, *, tenant_id, lock=False):
        return FlowRetentionControlPlaneState(
            organization_run_history_days=None,
            runtime_upload_abandonment_days=None,
            classification_policies=(),
            latent_space_retention_days=(),
            latent_flow_retention_days=(),
        )

    async def prepare_flow_retention_organization_change(
        self,
        *,
        tenant_id,
        run_history_patch,
        upload_abandonment_patch,
        confirmation,
    ):
        old_policy = FlowRetentionOrganizationProposal(
            flow_run_history_retention_days=None,
            flow_runtime_upload_abandonment_days=None,
        )
        new_policy = FlowRetentionOrganizationProposal(
            flow_run_history_retention_days=(
                run_history_patch.value if run_history_patch.is_set else None
            ),
            flow_runtime_upload_abandonment_days=(
                upload_abandonment_patch.value
                if upload_abandonment_patch.is_set
                else None
            ),
        )
        return FlowRetentionOrganizationChangeDecision(
            old_policy=old_policy,
            new_policy=new_policy,
            destructive_change=False,
            preview=None,
        )


def _assert_extra_forbidden(model: type[BaseModel], payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as exc_info:
        model.model_validate({**payload, "unexpected": True})

    assert any(
        error.get("type") == "extra_forbidden" for error in exc_info.value.errors()
    )


def test_flow_settings_update_models_reject_unknown_fields() -> None:
    cases: tuple[tuple[type[BaseModel], dict[str, object]], ...] = (
        (FlowInputLimitsUpdate, {"file_max_size_bytes": 10_000_000}),
        (FlowDocumentRenderLimitsUpdate, {"max_source_chars": 500_000}),
        (FlowRuntimePolicyUpdate, {"default_step_timeout_seconds": 900}),
        (FlowEvidencePolicyUpdate, {"allow_sensitive_flow_exports": True}),
        (FlowClassificationRetentionPolicyUpdate, {"data_retention_days": 7}),
        (FlowRetentionPolicyUpdate, {"run_debug_evidence_days": 14}),
    )

    for model, payload in cases:
        _assert_extra_forbidden(model, payload)


@pytest.mark.parametrize(
    "field_name",
    (
        "flow_run_history_retention_days",
        "flow_runtime_upload_abandonment_days",
    ),
)
@pytest.mark.parametrize("value", [0, 2556, True, 7.5, "7"])
def test_flow_retention_policy_update_rejects_invalid_tenant_days(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        FlowRetentionPolicyUpdate.model_validate({field_name: value})


def test_flow_retention_policy_update_accepts_nullable_range_boundaries() -> None:
    for value in (None, 1, 2555):
        update = FlowRetentionPolicyUpdate(
            flow_run_history_retention_days=value,
            flow_runtime_upload_abandonment_days=value,
        )
        assert update.flow_run_history_retention_days == value
        assert update.flow_runtime_upload_abandonment_days == value


@pytest.mark.parametrize(
    "field_name",
    (
        "allow_sensitive_flow_exports",
        "allow_space_admin_raw_export_class3",
        "allow_run_owner_raw_export_class3",
        "allow_service_key_raw_export_class3",
    ),
)
def test_flow_evidence_policy_update_rejects_null_flags(field_name: str) -> None:
    with pytest.raises(ValidationError):
        FlowEvidencePolicyUpdate.model_validate({field_name: None})


def test_flow_settings_update_models_keep_intentional_null_clear_contracts() -> None:
    cases: tuple[tuple[type[BaseModel], dict[str, object | None]], ...] = (
        (FlowInputLimitsUpdate, {"max_files_per_run": None}),
        (FlowDocumentRenderLimitsUpdate, {"max_source_chars": None}),
        (FlowRuntimePolicyUpdate, {"default_step_timeout_seconds": None}),
        (FlowRetentionPolicyUpdate, {"run_debug_evidence_days": None}),
    )

    for model, payload in cases:
        assert model.model_validate(payload).model_dump(exclude_unset=True) == payload


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
        data_retention_service=MockDataRetentionService(),
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
        data_retention_service=MockDataRetentionService(),
    )

    repo.settings[TEST_USER.id] = TEST_SETTINGS_EXPECTED
    new_settings = SettingsPublic(chatbot_widget={"colour": "blue"})
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
        data_retention_service=MockDataRetentionService(),
    )

    new_settings = SettingsPublic(chatbot_widget={"preferred_text_format": "richtext"})

    settings = await service.update_settings(new_settings)

    assert settings.chatbot_widget == {"preferred_text_format": "richtext"}
    assert repo.settings[TEST_USER.id].chatbot_widget == {
        "preferred_text_format": "richtext"
    }


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
        "eneo.flows.flow_input_limits.get_settings",
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
        data_retention_service=MockDataRetentionService(),
    )

    limits = await service.get_flow_input_limits()

    assert limits.file_max_size_bytes == 12_000_000
    assert limits.audio_max_size_bytes == 28_000_000


async def test_get_flow_input_limits_resolved_returns_domain_limits(monkeypatch):
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    tenant_repo.tenant = tenant.model_copy(
        update={
            "flow_settings": {
                "input_limits": {
                    "file_max_size_bytes": 13_000_000,
                    "audio_max_size_bytes": 29_000_000,
                    "max_files_per_run": 7,
                    "audio_max_files_per_run": 3,
                }
            }
        }
    )

    monkeypatch.setattr(
        "eneo.flows.flow_input_limits.get_settings",
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
        data_retention_service=MockDataRetentionService(),
    )

    limits = await service.get_flow_input_limits_resolved()

    assert limits.file_max_size_bytes == 13_000_000
    assert limits.audio_max_size_bytes == 29_000_000
    assert limits.max_files_per_run == 7
    assert limits.audio_max_files_per_run == 3


async def test_update_flow_input_limits_persists_and_audits(monkeypatch):
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    audit_service = MockAuditService()

    calls = []

    async def _capture(*args, **kwargs):
        calls.append(kwargs)

    audit_service.log_async = _capture

    monkeypatch.setattr(
        "eneo.flows.flow_input_limits.get_settings",
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
        data_retention_service=MockDataRetentionService(),
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
    assert calls[0]["metadata"]["changes"] == {
        "audio_max_size_bytes": {"old": 25_000_000, "new": 35_000_000}
    }


async def test_update_flow_input_limits_scrubs_unknown_top_level_flow_settings(
    monkeypatch,
):
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    tenant_repo.tenant = tenant.model_copy(
        update={
            "flow_settings": {
                "evidence_polici": {"allow_sensitive_flow_exports": True},
                "input_limits": {"max_files_per_run": 25},
            }
        }
    )

    monkeypatch.setattr(
        "eneo.flows.flow_input_limits.get_settings",
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
        data_retention_service=MockDataRetentionService(),
    )

    await service.update_flow_input_limits(FlowInputLimitsUpdate(max_files_per_run=30))

    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    assert "evidence_polici" not in tenant.flow_settings
    assert tenant.flow_settings["input_limits"]["max_files_per_run"] == 30


async def test_update_flow_input_limits_null_clears_nullable_overrides(monkeypatch):
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    tenant_repo.tenant = tenant.model_copy(
        update={
            "flow_settings": {
                "input_limits": {
                    "max_files_per_run": 25,
                    "audio_max_files_per_run": 8,
                }
            }
        }
    )

    monkeypatch.setattr(
        "eneo.flows.flow_input_limits.get_settings",
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
        data_retention_service=MockDataRetentionService(),
    )

    updated = await service.update_flow_input_limits(
        FlowInputLimitsUpdate(max_files_per_run=None, audio_max_files_per_run=None)
    )

    assert updated.max_files_per_run is None
    assert updated.audio_max_files_per_run == 10
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    assert "max_files_per_run" not in tenant.flow_settings["input_limits"]
    assert "audio_max_files_per_run" not in tenant.flow_settings["input_limits"]


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
        data_retention_service=MockDataRetentionService(),
    )

    with pytest.raises(
        BadRequestException, match="At least one flow input limit field"
    ):
        await service.update_flow_input_limits(FlowInputLimitsUpdate())


async def test_get_flow_document_render_limits_reads_tenant_override():
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    tenant_repo.tenant = tenant.model_copy(
        update={
            "flow_settings": {
                "document_render_limits": {
                    "max_source_chars": 750_000,
                    "max_table_cells": 75_000,
                }
            }
        }
    )

    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=MockAuditService(),
        data_retention_service=MockDataRetentionService(),
    )

    limits = await service.get_flow_document_render_limits()

    assert limits.max_source_chars == 750_000
    assert limits.max_table_cells == 75_000


async def test_update_flow_document_render_limits_persists_and_audits():
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    audit_service = MockAuditService()
    calls = []

    async def _capture(*args, **kwargs):
        calls.append(kwargs)

    audit_service.log_async = _capture

    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=audit_service,
        data_retention_service=MockDataRetentionService(),
    )

    updated = await service.update_flow_document_render_limits(
        FlowDocumentRenderLimitsUpdate(max_source_chars=800_000)
    )

    assert updated.max_source_chars == 800_000
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    assert tenant.flow_settings["document_render_limits"]["max_source_chars"] == 800_000
    assert calls[0]["metadata"]["setting"] == "flow_document_render_limits"
    assert calls[0]["metadata"]["changes"] == {
        "max_source_chars": {"old": 500_000, "new": 800_000}
    }


async def test_update_flow_document_render_limits_null_clears_override():
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    tenant_repo.tenant = tenant.model_copy(
        update={
            "flow_settings": {
                "document_render_limits": {
                    "max_source_chars": 800_000,
                }
            }
        }
    )

    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=MockAuditService(),
        data_retention_service=MockDataRetentionService(),
    )

    updated = await service.update_flow_document_render_limits(
        FlowDocumentRenderLimitsUpdate(max_source_chars=None)
    )

    assert updated.max_source_chars == 500_000
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    assert "document_render_limits" not in tenant.flow_settings


async def test_update_flow_document_render_limits_rejects_empty_patch():
    service = SettingService(
        repo=MockRepo(),
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=MockTenantRepo(),
        audit_service=MockAuditService(),
        data_retention_service=MockDataRetentionService(),
    )

    with pytest.raises(
        BadRequestException, match="At least one flow document render limit"
    ):
        await service.update_flow_document_render_limits(
            FlowDocumentRenderLimitsUpdate()
        )


async def test_get_flow_evidence_policy_reads_tenant_override():
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    tenant_repo.tenant = tenant.model_copy(
        update={
            "flow_settings": {
                "evidence_policy": {
                    "classification_3": {
                        "allow_space_admin_raw_export": True,
                        "allow_run_owner_raw_export": False,
                        "allow_service_key_raw_export": True,
                    }
                }
            }
        }
    )

    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=MockAuditService(),
        data_retention_service=MockDataRetentionService(),
    )

    policy = await service.get_flow_evidence_policy()

    assert policy.allow_sensitive_flow_exports is False
    assert policy.allow_space_admin_raw_export_class3 is True
    assert policy.allow_run_owner_raw_export_class3 is False
    assert policy.allow_service_key_raw_export_class3 is True


async def test_update_flow_evidence_policy_persists_and_audits():
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    audit_service = MockAuditService()
    calls = []

    async def _capture(*args, **kwargs):
        calls.append(kwargs)

    audit_service.log_async = _capture

    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=audit_service,
        data_retention_service=MockDataRetentionService(),
    )

    updated = await service.update_flow_evidence_policy(
        FlowEvidencePolicyUpdate(
            allow_sensitive_flow_exports=True,
            allow_service_key_raw_export_class3=True,
        )
    )

    assert updated.allow_sensitive_flow_exports is True
    assert updated.allow_service_key_raw_export_class3 is True
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    assert (
        tenant.flow_settings["evidence_policy"][
            FLOW_EVIDENCE_POLICY_STORAGE_VERSION_KEY
        ]
        == FLOW_EVIDENCE_POLICY_STORAGE_VERSION
    )
    assert (
        tenant.flow_settings["evidence_policy"]["allow_sensitive_flow_exports"] is True
    )
    assert (
        tenant.flow_settings["evidence_policy"]["classification_3"][
            "allow_service_key_raw_export"
        ]
        is True
    )
    assert calls[0]["metadata"]["setting"] == "flow_evidence_policy"


async def test_update_flow_evidence_policy_rejects_empty_patch():
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=MockAuditService(),
        data_retention_service=MockDataRetentionService(),
    )

    with pytest.raises(
        BadRequestException, match="At least one flow evidence policy field"
    ):
        await service.update_flow_evidence_policy(FlowEvidencePolicyUpdate())


async def test_get_flow_evidence_policy_requires_admin_permission():
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    tenant_repo.tenant = tenant.model_copy(
        update={
            "flow_settings": {
                "evidence_policy": {
                    "classification_3": {
                        "allow_service_key_raw_export": True,
                    }
                }
            }
        }
    )

    service = SettingService(
        repo=repo,
        user=TEST_USER.model_copy(update={"roles": []}),
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=MockAuditService(),
        data_retention_service=MockDataRetentionService(),
    )

    with pytest.raises(Exception, match="Need permission admin"):
        await service.get_flow_evidence_policy()


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
        "eneo.flows.ai_builder.ai_builder_settings.get_settings",
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
        data_retention_service=MockDataRetentionService(),
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
        "eneo.flows.ai_builder.ai_builder_settings.get_settings",
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
        data_retention_service=MockDataRetentionService(),
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
    assert (
        tenant.flow_settings["ai_builder"]["conversation_safety_buffer_tokens"] == 1500
    )
    assert (
        "unknown_model_context_window_tokens" not in tenant.flow_settings["ai_builder"]
    )
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
        data_retention_service=MockDataRetentionService(),
    )

    with pytest.raises(
        BadRequestException, match="At least one AI Builder budget field"
    ):
        await service.update_ai_builder_budget_settings(AIBuilderBudgetSettingsUpdate())


async def test_get_flow_runtime_policy_reads_tenant_override(monkeypatch):
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    tenant_repo.tenant = tenant.model_copy(
        update={
            "flow_settings": {
                "runtime_policy": {
                    "default_step_timeout_seconds": 1200,
                    "max_step_timeout_seconds": 2400,
                }
            }
        }
    )

    monkeypatch.setattr(
        "eneo.flows.flow_runtime_policy.get_settings",
        lambda: SimpleNamespace(
            flow_llm_request_timeout_seconds=600,
            flow_task_timeout_seconds=3600,
            flow_runtime_step_timeout_hard_ceiling_seconds=3600,
        ),
    )

    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=MockAuditService(),
        data_retention_service=MockDataRetentionService(),
    )

    policy = await service.get_flow_runtime_policy()

    assert policy.default_step_timeout_seconds == 1200
    assert policy.max_step_timeout_seconds == 2400
    assert policy.hard_ceiling_seconds == 3540


async def test_update_flow_runtime_policy_persists_and_audits(monkeypatch):
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    audit_service = MockAuditService()
    calls = []

    async def _capture(*args, **kwargs):
        calls.append(kwargs)

    audit_service.log_async = _capture
    monkeypatch.setattr(
        "eneo.flows.flow_runtime_policy.get_settings",
        lambda: SimpleNamespace(
            flow_llm_request_timeout_seconds=600,
            flow_task_timeout_seconds=3600,
            flow_runtime_step_timeout_hard_ceiling_seconds=3600,
        ),
    )

    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=audit_service,
        data_retention_service=MockDataRetentionService(),
    )

    updated = await service.update_flow_runtime_policy(
        FlowRuntimePolicyUpdate(
            default_step_timeout_seconds=1200,
            max_step_timeout_seconds=2400,
        )
    )

    assert updated.default_step_timeout_seconds == 1200
    assert updated.max_step_timeout_seconds == 2400
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    assert tenant.flow_settings["runtime_policy"] == {
        "version": 1,
        "default_step_timeout_seconds": 1200,
        "max_step_timeout_seconds": 2400,
    }
    assert calls[0]["metadata"]["setting"] == "flow_runtime_policy"


async def test_get_flow_retention_policy_reads_tenant_override():
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    tenant_repo.tenant = tenant.model_copy(
        update={
            "flow_settings": {
                "retention_policy": {
                    "source_audio_days": 3,
                    "run_debug_evidence_days": 7,
                }
            }
        }
    )

    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=MockAuditService(),
        data_retention_service=MockDataRetentionService(),
    )

    policy = await service.get_flow_retention_policy()

    assert policy.run_debug_evidence_days == 7


async def test_update_flow_retention_policy_persists_and_audits():
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    audit_service = MockAuditService()
    calls = []

    async def _capture(*args, **kwargs):
        calls.append(kwargs)

    audit_service.log = _capture

    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=audit_service,
        data_retention_service=MockDataRetentionService(),
    )

    updated = await service.update_flow_retention_policy(
        FlowRetentionPolicyUpdate(run_debug_evidence_days=14)
    )

    assert updated.run_debug_evidence_days == 14
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    assert tenant.flow_settings["retention_policy"] == {
        "run_debug_evidence_days": 14,
        FLOW_RETENTION_POLICY_STORAGE_VERSION_KEY: FLOW_RETENTION_POLICY_STORAGE_VERSION,
    }
    metadata = calls[0]["metadata"]
    assert set(metadata) == {"old_policy", "new_policy", "preview", "activation"}
    assert metadata["old_policy"]["run_debug_evidence_days"] is None
    assert metadata["new_policy"]["run_debug_evidence_days"] == 14
    assert metadata["preview"] is None


async def test_update_flow_retention_policy_can_clear_override():
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    tenant_repo.tenant = tenant.model_copy(
        update={
            "flow_settings": {
                "retention_policy": {
                    "source_audio_days": 3,
                    "run_debug_evidence_days": 7,
                }
            }
        }
    )

    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=MockAuditService(),
        data_retention_service=MockDataRetentionService(),
    )

    updated = await service.update_flow_retention_policy(
        FlowRetentionPolicyUpdate(run_debug_evidence_days=None)
    )

    assert updated.run_debug_evidence_days is None
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    assert "retention_policy" not in tenant.flow_settings


async def test_update_flow_retention_policy_rejects_deleted_fields():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FlowRetentionPolicyUpdate(source_audio_days=3)


async def test_update_flow_retention_policy_rejects_stored_unknown_keys():
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    tenant_repo.tenant = tenant.model_copy(
        update={"flow_settings": {"retention_policy": {"unexpected_days": 7}}}
    )
    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=MockAuditService(),
        data_retention_service=MockDataRetentionService(),
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.update_flow_retention_policy(
            FlowRetentionPolicyUpdate(run_debug_evidence_days=14)
        )

    assert exc_info.value.code == "flow_settings_invalid_payload"
    assert "unexpected_days" in str(exc_info.value)


async def test_update_flow_runtime_policy_scrubs_stale_retention_policy_keys():
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    tenant_repo.tenant = tenant.model_copy(
        update={
            "flow_settings": {
                "retention_policy": {
                    "source_audio_days": 3,
                    "run_debug_evidence_days": 7,
                }
            }
        }
    )
    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=MockAuditService(),
        data_retention_service=MockDataRetentionService(),
    )

    updated = await service.update_flow_runtime_policy(
        FlowRuntimePolicyUpdate(default_step_timeout_seconds=1200)
    )

    assert updated.default_step_timeout_seconds == 1200
    tenant = await tenant_repo.get(TEST_USER.tenant_id)
    assert tenant.flow_settings["runtime_policy"] == {
        "version": 1,
        "default_step_timeout_seconds": 1200,
    }
    assert tenant.flow_settings["retention_policy"] == {"run_debug_evidence_days": 7}


async def test_update_flow_retention_policy_rejects_empty_patch():
    repo = MockRepo()
    tenant_repo = MockTenantRepo()
    service = SettingService(
        repo=repo,
        user=TEST_USER,
        ai_models_service=MockRepo(),
        feature_flag_service=MockFeatureFlagService(),
        tenant_repo=tenant_repo,
        audit_service=MockAuditService(),
        data_retention_service=MockDataRetentionService(),
    )

    with pytest.raises(
        BadRequestException, match="At least one flow retention policy field"
    ):
        await service.update_flow_retention_policy(FlowRetentionPolicyUpdate())
