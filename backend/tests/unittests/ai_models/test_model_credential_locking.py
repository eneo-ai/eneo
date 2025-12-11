"""
Tests for AIModel credential status tracking when TENANT_CREDENTIALS_ENABLED=true.

This test suite validates that the lock_reason property correctly reports missing
credentials for UI display purposes. Note that missing credentials no longer block
model access (is_locked=False), but the UI can show warnings based on lock_reason.
Runtime credential validation still occurs when models are actually used.
"""

from datetime import datetime
from uuid import uuid4


from intric.completion_models.domain.completion_model import CompletionModel
from intric.ai_models.model_enums import (
    ModelFamily,
    ModelHostingLocation,
    ModelOrg,
    ModelStability,
)


class MockSettings:
    """Mock Settings object for testing."""

    def __init__(self, tenant_credentials_enabled: bool = False):
        self.tenant_credentials_enabled = tenant_credentials_enabled


class MockTenant:
    """Mock TenantInDB object for testing."""

    def __init__(self, api_credentials: dict | None = None):
        self.id = uuid4()
        self.name = "Test Tenant"
        self.api_credentials = api_credentials or {}


class MockUser:
    """Mock UserInDB object for testing."""

    def __init__(self, tenant: MockTenant | None = None, modules: list = None):
        self.id = uuid4()
        self.tenant = tenant
        self.tenant_id = tenant.id if tenant else None
        self.modules = modules or []


class TestModelCredentialLocking:
    """Test suite for model credential status tracking via lock_reason."""

    def test_openai_model_shows_credential_warning_when_no_credentials(self, monkeypatch):
        """
        OpenAI model should report missing credentials via lock_reason for UI display,
        but should not be locked (is_locked=False) to allow space initialization.
        """
        # Arrange
        settings = MockSettings(tenant_credentials_enabled=True)
        tenant = MockTenant(api_credentials={})  # No credentials
        user = MockUser(tenant=tenant)

        monkeypatch.setattr("intric.ai_models.ai_model.get_settings", lambda: settings)

        model = CompletionModel(
            user=user,
            id=uuid4(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            nickname="GPT-4",
            name="gpt-4",
            token_limit=8000,
            vision=False,
            family=ModelFamily.OPEN_AI,
            hosting=ModelHostingLocation.USA,
            org=ModelOrg.OPENAI,
            stability=ModelStability.STABLE,
            open_source=False,
            description="OpenAI GPT-4",
            nr_billion_parameters=None,
            hf_link=None,
            is_deprecated=False,
            deployment_name=None,
            is_org_enabled=False,
            is_org_default=False,
            reasoning=False,
        )

        # Assert
        assert model.is_locked is False  # Not locked - allows space initialization
        assert model.lock_reason == "credentials"  # UI can show warning
        assert model.can_access is False  # Can't access because not org_enabled

    def test_openai_model_no_warning_when_credentials_exist(
        self, monkeypatch
    ):
        """
        OpenAI model should have no lock_reason when tenant has OpenAI credentials.
        """
        # Arrange
        settings = MockSettings(tenant_credentials_enabled=True)
        tenant = MockTenant(
            api_credentials={"openai": {"api_key": "sk-test-key"}}
        )
        user = MockUser(tenant=tenant)

        monkeypatch.setattr("intric.ai_models.ai_model.get_settings", lambda: settings)

        model = CompletionModel(
            user=user,
            id=uuid4(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            nickname="GPT-4",
            name="gpt-4",
            token_limit=8000,
            vision=False,
            family=ModelFamily.OPEN_AI,
            hosting=ModelHostingLocation.USA,
            org=ModelOrg.OPENAI,
            stability=ModelStability.STABLE,
            open_source=False,
            description="OpenAI GPT-4",
            nr_billion_parameters=None,
            hf_link=None,
            is_deprecated=False,
            deployment_name=None,
            is_org_enabled=False,
            is_org_default=False,
            reasoning=False,
        )

        # Assert
        assert model.is_locked is False
        assert model.lock_reason is None

    def test_claude_model_uses_anthropic_provider_name(self, monkeypatch):
        """
        Claude models (ModelFamily.CLAUDE) should check for 'anthropic' credentials
        when reporting lock_reason for UI display.
        """
        # Arrange
        settings = MockSettings(tenant_credentials_enabled=True)
        tenant = MockTenant(api_credentials={})  # No credentials
        user = MockUser(tenant=tenant)

        monkeypatch.setattr("intric.ai_models.ai_model.get_settings", lambda: settings)

        model = CompletionModel(
            user=user,
            id=uuid4(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            nickname="Claude",
            name="claude-3-opus",
            token_limit=200000,
            vision=False,
            family=ModelFamily.CLAUDE,
            hosting=ModelHostingLocation.USA,
            org=ModelOrg.ANTHROPIC,
            stability=ModelStability.STABLE,
            open_source=False,
            description="Anthropic Claude 3 Opus",
            nr_billion_parameters=None,
            hf_link=None,
            is_deprecated=False,
            deployment_name=None,
            is_org_enabled=False,
            is_org_default=False,
            reasoning=False,
        )

        # Assert - not locked, but shows credential warning for UI
        assert model.is_locked is False
        assert model.lock_reason == "credentials"

        # Now add anthropic credentials
        tenant.api_credentials["anthropic"] = {"api_key": "sk-ant-test"}

        # Should have no warning
        assert model.is_locked is False
        assert model.lock_reason is None

    def test_model_not_locked_when_strict_mode_disabled(self, monkeypatch):
        """
        Models should not be locked based on credentials when strict mode is off.
        """
        # Arrange
        settings = MockSettings(tenant_credentials_enabled=False)
        tenant = MockTenant(api_credentials={})  # No credentials
        user = MockUser(tenant=tenant)

        monkeypatch.setattr("intric.ai_models.ai_model.get_settings", lambda: settings)

        model = CompletionModel(
            user=user,
            id=uuid4(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            nickname="GPT-4",
            name="gpt-4",
            token_limit=8000,
            vision=False,
            family=ModelFamily.OPEN_AI,
            hosting=ModelHostingLocation.USA,
            org=ModelOrg.OPENAI,
            stability=ModelStability.STABLE,
            open_source=False,
            description="OpenAI GPT-4",
            nr_billion_parameters=None,
            hf_link=None,
            is_deprecated=False,
            deployment_name=None,
            is_org_enabled=False,
            is_org_default=False,
            reasoning=False,
        )

        # Assert - not locked because strict mode is off
        assert model.is_locked is False
        assert model.lock_reason is None

    def test_azure_model_shows_warning_without_azure_credentials(self, monkeypatch):
        """
        Azure models should check for 'azure' credentials and report via lock_reason.
        """
        # Arrange
        settings = MockSettings(tenant_credentials_enabled=True)
        tenant = MockTenant(
            api_credentials={"openai": {"api_key": "sk-test"}}  # Has OpenAI, not Azure
        )
        user = MockUser(tenant=tenant)

        monkeypatch.setattr("intric.ai_models.ai_model.get_settings", lambda: settings)

        model = CompletionModel(
            user=user,
            id=uuid4(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            nickname="Azure GPT-4",
            name="gpt-4",
            token_limit=8000,
            vision=False,
            family=ModelFamily.AZURE,
            hosting=ModelHostingLocation.USA,
            org=ModelOrg.MICROSOFT,
            stability=ModelStability.STABLE,
            open_source=False,
            description="Azure OpenAI GPT-4",
            nr_billion_parameters=None,
            hf_link=None,
            is_deprecated=False,
            deployment_name="gpt-4-deployment",
            is_org_enabled=False,
            is_org_default=False,
            reasoning=False,
        )

        # Assert - not locked, but shows credential warning for UI
        assert model.is_locked is False
        assert model.lock_reason == "credentials"

        # Add azure credentials
        tenant.api_credentials["azure"] = {
            "api_key": "azure-key",
            "endpoint": "https://test.openai.azure.com",
            "api_version": "2024-02-01",
            "deployment_name": "gpt-4",
        }

        # Should have no warning
        assert model.is_locked is False
        assert model.lock_reason is None

    def test_all_provider_families_credential_mapping(self, monkeypatch):
        """
        Test that all provider families map to correct credential keys for lock_reason.
        """
        settings = MockSettings(tenant_credentials_enabled=True)

        # Test mapping: ModelFamily -> expected credential provider key
        test_cases = [
            (ModelFamily.OPEN_AI, "openai"),
            (ModelFamily.CLAUDE, "anthropic"),
            (ModelFamily.AZURE, "azure"),
            (ModelFamily.MISTRAL, "mistral"),
            (ModelFamily.VLLM, "vllm"),
            (ModelFamily.OVHCLOUD, "ovhcloud"),
        ]

        monkeypatch.setattr("intric.ai_models.ai_model.get_settings", lambda: settings)

        for family, expected_provider in test_cases:
            # Model without credentials - should show credential warning
            tenant_no_creds = MockTenant(api_credentials={})
            user_no_creds = MockUser(tenant=tenant_no_creds)

            model_no_creds = CompletionModel(
                user=user_no_creds,
                id=uuid4(),
                created_at=datetime.now(),
                updated_at=datetime.now(),
                nickname=f"Test {family.value}",
                name=f"test-{family.value}",
                token_limit=8000,
                vision=False,
                family=family,
                hosting=ModelHostingLocation.USA,
                org=None,
                stability=ModelStability.STABLE,
                open_source=False,
                description=f"Test {family.value}",
                nr_billion_parameters=None,
                hf_link=None,
                is_deprecated=False,
                deployment_name=None,
                is_org_enabled=False,
                is_org_default=False,
                reasoning=False,
            )

            assert model_no_creds.is_locked is False, f"{family.value} should not be locked (missing credentials only)"
            assert model_no_creds.lock_reason == "credentials", f"{family.value} lock_reason should be credentials"

            # Model with credentials - should have no warning
            tenant_with_creds = MockTenant(
                api_credentials={expected_provider: {"api_key": "test-key"}}
            )
            user_with_creds = MockUser(tenant=tenant_with_creds)

            model_with_creds = CompletionModel(
                user=user_with_creds,
                id=uuid4(),
                created_at=datetime.now(),
                updated_at=datetime.now(),
                nickname=f"Test {family.value}",
                name=f"test-{family.value}",
                token_limit=8000,
                vision=False,
                family=family,
                hosting=ModelHostingLocation.USA,
                org=None,
                stability=ModelStability.STABLE,
                open_source=False,
                description=f"Test {family.value}",
                nr_billion_parameters=None,
                hf_link=None,
                is_deprecated=False,
                deployment_name=None,
                is_org_enabled=False,
                is_org_default=False,
                reasoning=False,
            )

            assert model_with_creds.is_locked is False, f"{family.value} should not be locked with credentials"
            assert model_with_creds.lock_reason is None, f"{family.value} should have no lock_reason"
