"""
Critical security tests for CredentialResolver strict mode enforcement.

This test suite validates the fix for the multi-tenant isolation bug where
tenants could silently use shared global credentials even in strict mode.

Root Cause (CRITICAL SECURITY BUG):
------------------------------------
The strict mode check was positioned AFTER the global credential fallback,
allowing tenants to bypass tenant-specific credential enforcement.

Fix:
----
Moved strict mode enforcement to BEFORE global fallback in credential_resolver.py
(lines 111-125), ensuring tenants in multi-tenant mode MUST configure their own
credentials and cannot fall back to shared global keys.

Security Impact:
----------------
Without this fix, in a multi-tenant SaaS environment:
- Tenants think they're using their own API keys
- System silently uses shared global credentials
- Causes billing confusion, rate limit sharing, and potential data leakage

These tests are CRITICAL regression guards for this security boundary.
"""

from typing import Any

import pytest

from intric.settings.credential_resolver import CredentialResolver
from intric.settings.encryption_service import EncryptionService


class MockSettings:
    """Mock Settings object for testing CredentialResolver."""

    def __init__(
        self,
        tenant_credentials_enabled: bool = True,
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
        azure_api_key: str | None = None,
        berget_api_key: str | None = None,
        mistral_api_key: str | None = None,
        ovhcloud_api_key: str | None = None,
        vllm_api_key: str | None = None,
    ):
        self.tenant_credentials_enabled = tenant_credentials_enabled
        self.openai_api_key = openai_api_key
        self.anthropic_api_key = anthropic_api_key
        self.azure_api_key = azure_api_key
        self.berget_api_key = berget_api_key
        self.mistral_api_key = mistral_api_key
        self.ovhcloud_api_key = ovhcloud_api_key
        self.vllm_api_key = vllm_api_key


class MockTenant:
    """Mock TenantInDB object for testing."""

    def __init__(
        self,
        tenant_id: str = "test-tenant-123",
        name: str = "Test Tenant",
        api_credentials: dict[str, Any] | None = None,
    ):
        self.id = tenant_id
        self.name = name
        self.api_credentials = api_credentials or {}


class TestCredentialResolverStrictMode:
    """
    Test suite for CredentialResolver strict mode enforcement.

    These tests validate that the security fix preventing credential fallback
    in multi-tenant mode works correctly and cannot regress.
    """

    def test_strict_mode_blocks_global_fallback_even_when_global_exists(
        self, monkeypatch
    ):
        """
        CRITICAL SECURITY TEST #1: Strict mode prevents global credential fallback.

        This test validates the core security fix: when TENANT_CREDENTIALS_ENABLED=true,
        tenants MUST configure their own credentials and CANNOT silently use shared
        global credentials, even if they exist.

        Security Boundary:
        ------------------
        Lines 111-125 in credential_resolver.py:
            if self.settings.tenant_credentials_enabled and self.tenant:
                raise ValueError("No API key configured...")

        Attack Vector Prevented:
        ------------------------
        Without this check, a tenant could:
        1. Not configure any credentials
        2. Silently use the system's shared global API key
        3. Cause billing/usage to be charged to system admin
        4. Share rate limits with all other tenants
        5. Potentially access data from other tenants (depending on provider isolation)

        Regression Risk:
        ----------------
        HIGH - If strict mode check is moved back AFTER global fallback, this exact
        security bug returns. This test will immediately catch that regression.
        """
        # Arrange: Multi-tenant strict mode with global key available
        settings = MockSettings(
            tenant_credentials_enabled=True,  # Strict mode ON
            openai_api_key="global-shared-api-key-should-not-be-used",
        )

        # Also set environment variable to test both fallback paths
        monkeypatch.setenv("OPENAI_API_KEY", "env-global-key-should-not-be-used")

        # Tenant has NO credentials configured
        tenant = MockTenant(
            tenant_id="sundsvall-municipality",
            name="Sundsvall Municipality",
            api_credentials={},  # Empty - no credentials
        )

        resolver = CredentialResolver(
            tenant=tenant,
            settings=settings,
            encryption_service=None,  # Not testing encryption here
        )

        # Act & Assert: Must raise ValueError (no fallback to global)
        with pytest.raises(ValueError) as exc_info:
            resolver.get_api_key("openai")

        # Verify error message is helpful and security-focused
        error_message = str(exc_info.value)
        assert "No API key configured for provider 'openai'" in error_message
        assert "Tenant-specific credentials are enabled" in error_message
        assert "must configure their own credentials" in error_message

        # Verify we did NOT use global credentials
        assert not resolver.uses_global_credentials("openai")

    def test_tenant_credentials_always_preferred_over_global(self, monkeypatch):
        """
        CRITICAL SECURITY TEST #2: Tenant credentials have absolute precedence.

        This test ensures that even if global credentials exist, a tenant's own
        configured credentials are ALWAYS used exclusively. This prevents scenarios
        where a tenant believes they're operating under their own API key and billing
        plan, but the system incorrectly uses the global key.

        Security Boundary:
        ------------------
        Lines 45-85 in credential_resolver.py:
            if self.tenant and self.tenant.api_credentials:
                tenant_cred = self.tenant.api_credentials.get(provider_lower)
                if tenant_cred:
                    # Use tenant's credential exclusively
                    return api_key

        This check MUST be evaluated before global fallback (lines 128+).

        Business Impact:
        ----------------
        Without this precedence:
        - Tenant configures their own API key for cost control
        - System ignores it and uses global key
        - Tenant's usage is billed to system admin
        - Tenant's API limits/quotas are not honored
        - Billing and usage reports are incorrect

        Regression Risk:
        ----------------
        MEDIUM - Less likely than Test #1, but if credential resolution logic is
        refactored, this precedence could be accidentally inverted.
        """
        # Arrange: Both global and tenant credentials exist
        settings = MockSettings(
            tenant_credentials_enabled=True,  # Strict mode ON
            openai_api_key="global-shared-key-must-not-be-used",
        )

        # Environment variable also set (double fallback test)
        monkeypatch.setenv("OPENAI_API_KEY", "env-global-key-must-not-be-used")

        # Tenant HAS their own credential configured
        tenant = MockTenant(
            tenant_id="sundsvall-municipality",
            name="Sundsvall Municipality",
            api_credentials={
                "openai": {
                    "api_key": "tenant-specific-openai-key-sk-proj-xyz123"
                }
            },
        )

        resolver = CredentialResolver(
            tenant=tenant,
            settings=settings,
            encryption_service=None,
        )

        # Act: Get API key
        resolved_key = resolver.get_api_key("openai")

        # Assert: MUST return tenant's key, NOT global key
        assert resolved_key == "tenant-specific-openai-key-sk-proj-xyz123"
        assert resolved_key != "global-shared-key-must-not-be-used"
        assert resolved_key != "env-global-key-must-not-be-used"

        # Verify source tracking shows tenant credential was used
        assert not resolver.uses_global_credentials("openai")

    def test_strict_mode_blocks_partial_field_fallback(self):
        """
        CRITICAL SECURITY TEST #3: Strict mode prevents partial credential fallback.

        This test validates that once a tenant has configured credentials for a provider,
        they cannot "fill in" missing required fields from the global configuration.
        This ensures complete tenant isolation and prevents configuration leakage.

        IMPORTANT: The actual implementation is MORE secure than expected - it raises
        a ValueError when required fields are missing, rather than silently returning None.
        This is fail-fast behavior that prevents incomplete credential configurations
        from being used.

        Security Boundary:
        ------------------
        Lines 246-258 in credential_resolver.py (get_credential_field):
            # Tenant has credential but required field missing → block fallback
            raise ValueError(
                f"Tenant credential for provider '{provider}' is missing required field '{field}'. "
            )

        Attack Vector Prevented:
        ------------------------
        Without this check:
        1. Tenant configures VLLM API key but forgets endpoint
        2. System "helps" by filling in global VLLM endpoint
        3. Tenant's requests go to wrong VLLM instance
        4. Data leakage or billing to wrong account
        5. Security boundary violated

        Business Impact:
        ----------------
        - Prevents mixing of tenant and global configuration
        - Ensures tenant credentials are self-contained
        - Catches incomplete credential configuration explicitly
        - Fail-fast prevents subtle bugs
        """
        # Arrange: Tenant has API key but missing required endpoint field
        settings = MockSettings(
            tenant_credentials_enabled=True,
            vllm_api_key="global-vllm-key",  # Global fallback exists
        )

        tenant = MockTenant(
            tenant_id="sundsvall-municipality",
            name="Sundsvall Municipality",
            api_credentials={
                "vllm": {
                    "api_key": "tenant-vllm-key",
                    # Missing 'endpoint' field intentionally
                }
            },
        )

        resolver = CredentialResolver(
            tenant=tenant,
            settings=settings,
            encryption_service=None,
        )

        # Act & Assert: Missing required field raises ValueError (fail-fast)
        with pytest.raises(ValueError) as exc_info:
            resolver.get_credential_field(
                provider="vllm",
                field="endpoint",
                fallback="http://global-vllm-endpoint:8000",
            )

        # Verify error message is helpful
        error_message = str(exc_info.value)
        assert "missing required field 'endpoint'" in error_message
        assert "vllm" in error_message

        # Also test that API key still resolves correctly
        api_key = resolver.get_api_key("vllm")
        assert api_key == "tenant-vllm-key"
        assert not resolver.uses_global_credentials("vllm")

    def test_non_strict_mode_allows_global_fallback(self, monkeypatch):
        """
        REGRESSION TEST: Single-tenant mode (non-strict) still allows global fallback.

        This test ensures that the security fix for strict mode didn't break the
        legitimate use case of single-tenant deployments where global credentials
        should be used as fallback.

        When TENANT_CREDENTIALS_ENABLED=false (single-tenant mode):
        - Tenant can have their own credentials (used if present)
        - If tenant has no credentials, fall back to global is OK
        - This is the legacy/simple deployment model
        """
        # Arrange: Single-tenant mode (strict mode OFF)
        settings = MockSettings(
            tenant_credentials_enabled=False,  # Single-tenant mode
            openai_api_key="global-openai-key-for-single-tenant",
        )

        # Tenant has NO credentials
        tenant = MockTenant(
            tenant_id="legacy-deployment",
            name="Legacy Single Tenant",
            api_credentials={},
        )

        resolver = CredentialResolver(
            tenant=tenant,
            settings=settings,
            encryption_service=None,
        )

        # Act: Get API key
        resolved_key = resolver.get_api_key("openai")

        # Assert: In non-strict mode, fallback to global is allowed
        assert resolved_key == "global-openai-key-for-single-tenant"

        # Verify source tracking shows global was used
        assert resolver.uses_global_credentials("openai")

    def test_encrypted_tenant_credentials_in_strict_mode(self):
        """
        INTEGRATION TEST: Encrypted credentials work correctly in strict mode.

        This test validates that the security fix works seamlessly with the
        encryption service, ensuring encrypted credentials are properly decrypted
        and used instead of falling back to global.
        """
        # Arrange: Create encryption service with test key
        encryption_service = EncryptionService(
            encryption_key="yPIAaWTENh5knUuz75NYHblR3672X-7lH-W6AD4F1hs="  # Valid Fernet key
        )

        # Encrypt a test API key
        plaintext_key = "sk-tenant-openai-key-encrypted-version"
        encrypted_key = encryption_service.encrypt(plaintext_key)

        # Verify encryption worked
        assert encrypted_key.startswith("enc:fernet:v1:")

        # Set up strict mode with global fallback
        settings = MockSettings(
            tenant_credentials_enabled=True,
            openai_api_key="global-key-should-not-be-used",
        )

        # Tenant has encrypted credential
        tenant = MockTenant(
            tenant_id="secure-municipality",
            name="Secure Municipality",
            api_credentials={"openai": {"api_key": encrypted_key}},
        )

        resolver = CredentialResolver(
            tenant=tenant,
            settings=settings,
            encryption_service=encryption_service,
        )

        # Act: Get API key (should decrypt)
        resolved_key = resolver.get_api_key("openai")

        # Assert: Decrypted tenant key is used, not global
        assert resolved_key == plaintext_key
        assert not resolver.uses_global_credentials("openai")


# Regression test metadata
__test_metadata__ = {
    "feature": "multi-tenant-credential-isolation",
    "security_critical": True,
    "fixed_bug": "strict-mode-bypass-allows-global-fallback",
    "fixed_date": "2025-10-21",
    "regression_risk": "HIGH",
    "related_files": [
        "backend/src/intric/settings/credential_resolver.py",
        "backend/src/intric/settings/encryption_service.py",
        "backend/src/intric/tenants/tenant_repo.py",
    ],
    "security_impact": (
        "Without these tests, a refactoring could re-introduce the critical security "
        "bug where tenants silently use shared global credentials in multi-tenant mode, "
        "violating tenant isolation and causing billing/security issues."
    ),
}
