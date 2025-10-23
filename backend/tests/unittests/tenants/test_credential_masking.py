"""Unit tests for API key masking utility functions.

Tests the masking logic for displaying API credentials safely in the UI:
- Long keys (>4 chars) show masked suffix with "..." prefix
- Short keys (≤4 chars) show "***" for complete masking
- Empty credentials dict returns empty dict
- Multiple providers all masked independently

This module tests the masking behavior by exercising the shared masking utility
used by the tenant repository and API responses.
"""

import pytest

from intric.tenants.masking import mask_api_key


def mask_credentials(credentials: dict) -> dict[str, str]:
    """Mask all credentials in a dictionary.

    Args:
        credentials: Dict of provider -> credential dict (with api_key field)

    Returns:
        Dict of provider -> masked api_key string
    """
    if not credentials:
        return {}

    masked = {}
    for provider, cred in credentials.items():
        # Handle both dict format and legacy string format
        if isinstance(cred, dict):
            api_key = cred.get("api_key", "")
        else:
            api_key = str(cred)

        masked[provider] = mask_api_key(api_key)

    return masked


def test_mask_long_api_key():
    """Keys >4 chars show last 4 with '...' prefix.

    Standard API keys are long (20+ characters). Should show only
    the last 4 characters for identification while maintaining security.
    """
    # Test various long keys
    assert mask_api_key("sk-test-key-123456789") == "sk-...6789"
    assert mask_api_key("sk-anthropic-key-abcdef") == "sk-...cdef"
    assert mask_api_key("azure-key-1234567890") == "...7890"
    assert mask_api_key("12345") == "...2345"  # Exactly 5 chars (boundary)


def test_mask_short_api_key():
    """Keys ≤4 chars show '***'.

    Very short keys should be completely masked to avoid revealing
    the entire key.
    """
    # Test short keys
    assert mask_api_key("abc") == "***"  # 3 chars
    assert mask_api_key("xy") == "***"  # 2 chars
    assert mask_api_key("z") == "***"  # 1 char
    assert mask_api_key("test") == "***"  # Exactly 4 chars (boundary)


def test_mask_empty_key():
    """Empty string returns '***'."""
    assert mask_api_key("") == "***"


def test_mask_empty_credentials():
    """Empty dict returns empty dict.

    When no credentials are provided, should return an empty dictionary
    rather than None or raising an error.
    """
    assert mask_credentials({}) == {}


def test_mask_single_credential():
    """Single credential is masked correctly."""
    credentials = {"openai": {"api_key": "sk-test-key-123456"}}

    masked = mask_credentials(credentials)

    assert masked == {"openai": "sk-...3456"}


def test_mask_multiple_providers():
    """Multiple providers all masked correctly.

    Each provider's credential should be independently masked according
    to its key length.
    """
    credentials = {
        "openai": {"api_key": "sk-openai-key-123456"},  # Long
        "anthropic": {"api_key": "sk-anthropic-key-abcdef"},  # Long
        "azure": {"api_key": "abc"},  # Short
        "berget": {"api_key": "test"},  # Short (4 chars)
        "mistral": {"api_key": "mistral-key-7890"},  # Long
    }

    masked = mask_credentials(credentials)

    assert masked == {
        "openai": "sk-...3456",
        "anthropic": "sk-...cdef",
        "azure": "***",
        "berget": "***",
        "mistral": "...7890",
    }


def test_mask_credentials_with_extra_fields():
    """Masking ignores extra fields (e.g., Azure endpoint, api_version).

    Some providers (like Azure) store additional configuration fields
    alongside the api_key. Masking should only extract and mask the api_key.
    """
    credentials = {
        "azure": {
            "api_key": "azure-key-1234567890",
            "endpoint": "https://example.openai.azure.com",
            "api_version": "2024-02-15-preview",
            "deployment_name": "gpt-4",
        }
    }

    masked = mask_credentials(credentials)

    # Should only return the masked api_key, not other fields
    assert masked == {"azure": "...7890"}
    assert "endpoint" not in masked
    assert "api_version" not in masked


def test_mask_credentials_legacy_string_format():
    """Support legacy string format for credentials.

    Some old tenants might have credentials stored as plain strings
    instead of {"api_key": "value"} format.
    """
    credentials = {
        "openai": "sk-legacy-string-key-123456",  # String instead of dict
        "anthropic": {"api_key": "sk-modern-dict-key-abcdef"},  # Modern dict
    }

    masked = mask_credentials(credentials)

    assert masked == {
        "openai": "sk-...3456",  # String format handled
        "anthropic": "sk-...cdef",  # Dict format handled
    }


def test_mask_credentials_mixed_lengths():
    """Mix of long and short keys all masked appropriately."""
    credentials = {
        "provider1": {"api_key": "a"},  # 1 char
        "provider2": {"api_key": "ab"},  # 2 chars
        "provider3": {"api_key": "abc"},  # 3 chars
        "provider4": {"api_key": "abcd"},  # 4 chars (boundary)
        "provider5": {"api_key": "abcde"},  # 5 chars (boundary)
        "provider6": {"api_key": "abcdef"},  # 6 chars
        "provider7": {"api_key": "sk-very-long-key-123456789"},  # Very long
    }

    masked = mask_credentials(credentials)

    assert masked == {
        "provider1": "***",
        "provider2": "***",
        "provider3": "***",
        "provider4": "***",  # 4 chars = short
        "provider5": "...bcde",  # 5 chars = long
        "provider6": "...cdef",
        "provider7": "sk-...6789",
    }


def test_mask_credentials_preserves_provider_names():
    """Provider names are preserved exactly as provided.

    The masking operation should not modify provider names (case, etc.).
    """
    credentials = {
        "OpenAI": {"api_key": "sk-test-123456"},
        "ANTHROPIC": {"api_key": "sk-test-abcdef"},
        "MixedCase": {"api_key": "sk-test-xyz789"},
    }

    masked = mask_credentials(credentials)

    # Provider names should be unchanged
    assert "OpenAI" in masked
    assert "ANTHROPIC" in masked
    assert "MixedCase" in masked
    assert masked["OpenAI"] == "sk-...3456"
    assert masked["ANTHROPIC"] == "sk-...cdef"
    assert masked["MixedCase"] == "sk-...z789"


def test_mask_credentials_handles_none_api_key():
    """Handles missing or None api_key gracefully.

    If a credential dict doesn't have an api_key field, should handle
    gracefully (empty string behavior).
    """
    credentials = {
        "invalid1": {},  # No api_key field
        "invalid2": {"other_field": "value"},  # Has fields but no api_key
    }

    masked = mask_credentials(credentials)

    # Should mask empty string (returns "***")
    assert masked["invalid1"] == "***"
    assert masked["invalid2"] == "***"


@pytest.mark.parametrize(
    "api_key,expected",
    [
        ("sk-proj-1234567890abcdef", "...cdef"),  # OpenAI project key
        ("sk-ant-1234567890abcdef", "sk-...cdef"),  # Anthropic key
        ("azure_key_1234567890", "...7890"),  # Azure key format
        ("berget_key_xyz", "...xyz"),  # Berget key
        ("mistral_key_abc", "...abc"),  # Mistral key
        ("ovh_key_12345", "...2345"),  # OVHcloud key
        ("a", "***"),  # Single char
        ("abcd", "***"),  # Exactly 4
        ("abcde", "...bcde"),  # Exactly 5
    ],
)
def test_mask_api_key_parametrized(api_key, expected):
    """Parametrized test for various API key formats.

    Tests real-world API key formats from different providers.
    """
    assert mask_api_key(api_key) == expected


def test_mask_credentials_real_world_example():
    """Real-world example with multiple providers and mixed formats.

    This test demonstrates the expected behavior with realistic tenant data.
    """
    credentials = {
        "openai": {"api_key": "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk"},
        "anthropic": {"api_key": "sk-ant-api03-1234567890abcdef"},
        "azure": {
            "api_key": "0123456789abcdef0123456789abcdef",
            "endpoint": "https://my-resource.openai.azure.com",
            "api_version": "2024-02-15-preview",
            "deployment_name": "gpt-4-turbo",
        },
        "berget": {"api_key": "berget_secret_key_xyz123"},
        "mistral": {"api_key": "mst_key_abc456def789"},
    }

    masked = mask_credentials(credentials)

    # Verify all providers masked with last 4 chars
    assert masked["openai"] == "...hijk"
    assert masked["anthropic"] == "sk-...cdef"
    assert masked["azure"] == "...cdef"
    assert masked["berget"] == "...z123"
    assert masked["mistral"] == "...f789"

    # Verify other Azure fields not included
    assert "endpoint" not in masked
    assert len(masked) == 5  # Only 5 providers, not Azure fields
