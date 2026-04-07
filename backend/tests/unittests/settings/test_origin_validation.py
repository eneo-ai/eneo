"""Tests for validate_public_origin() helper."""

import pytest
from intric.main.config import (
    validate_public_origin,
    validate_redirect_path,
    validate_redirect_uri,
)


def test_validates_https_required():
    """HTTP origins are rejected."""
    with pytest.raises(ValueError, match="must use https://"):
        validate_public_origin("http://insecure.com")


def test_validates_hostname_required():
    """Origins without hostname are rejected."""
    with pytest.raises(ValueError, match="missing hostname"):
        validate_public_origin("https://")


def test_rejects_path():
    """Origins with path are rejected."""
    with pytest.raises(ValueError, match="must not include path"):
        validate_public_origin("https://example.com/path")


def test_rejects_query():
    """Origins with query are rejected."""
    with pytest.raises(ValueError, match="must not include query"):
        validate_public_origin("https://example.com?query=value")


def test_rejects_fragment():
    """Origins with fragment are rejected."""
    with pytest.raises(ValueError, match="must not include query or fragment"):
        validate_public_origin("https://example.com#section")


def test_normalizes_trailing_slash():
    """Trailing slash is stripped."""
    result = validate_public_origin("https://example.com/")
    assert result == "https://example.com"


def test_normalizes_case():
    """Hostname is lowercased."""
    result = validate_public_origin("https://Example.COM")
    assert result == "https://example.com"


def test_preserves_non_default_port():
    """Non-default port is preserved."""
    result = validate_public_origin("https://example.com:8443")
    assert result == "https://example.com:8443"


def test_strips_default_port():
    """Default port 443 is stripped."""
    result = validate_public_origin("https://example.com:443")
    assert result == "https://example.com"


def test_accepts_valid_proxy_url():
    """Accepts proxy URLs like m00-https-*."""
    result = validate_public_origin("https://m00-https-eneo-test.login.sundsvall.se")
    assert result == "https://m00-https-eneo-test.login.sundsvall.se"


def test_returns_none_for_none_input():
    """None input returns None (for optional fields)."""
    result = validate_public_origin(None)
    assert result is None


def test_accepts_subdomain():
    """Accepts subdomains."""
    result = validate_public_origin("https://app.example.com")
    assert result == "https://app.example.com"


def test_accepts_multi_level_subdomain():
    """Accepts multi-level subdomains."""
    result = validate_public_origin("https://api.app.example.com")
    assert result == "https://api.app.example.com"


def test_normalizes_complex_case():
    """Normalizes complex case with trailing slash."""
    result = validate_public_origin("https://Stockholm.Eneo.SE/")
    assert result == "https://stockholm.eneo.se"


def test_handles_localhost():
    """Handles localhost for development."""
    result = validate_public_origin("https://localhost:3000")
    assert result == "https://localhost:3000"


def test_handles_ip_address():
    """Handles IP addresses."""
    result = validate_public_origin("https://192.168.1.1:8443")
    assert result == "https://192.168.1.1:8443"


def test_strips_whitespace():
    """Strips leading/trailing whitespace."""
    result = validate_public_origin("  https://example.com  ")
    assert result == "https://example.com"


def test_rejects_empty_string():
    """Empty string is rejected (not treated as None)."""
    with pytest.raises(ValueError, match="cannot be an empty string"):
        validate_public_origin("")


def test_rejects_whitespace_only():
    """Whitespace-only string is rejected."""
    with pytest.raises(ValueError, match="cannot be an empty string"):
        validate_public_origin("   ")


@pytest.mark.parametrize(
    ("uri", "expected", "error_match"),
    [
        ("https://*.example.com/callback", None, "must not include wildcards"),
        ("http://localhost:3000/callback", "http://localhost:3000/callback", None),
        ("http://example.com/callback", None, "must use https://"),
        ("https://example.com", None, "must include an absolute path"),
        ("https://Example.com/callback/", "https://example.com/callback", None),
    ],
)
def test_validate_redirect_uri_branches(uri, expected, error_match):
    if error_match:
        with pytest.raises(ValueError, match=error_match):
            validate_redirect_uri(uri)
        return

    assert validate_redirect_uri(uri) == expected


@pytest.mark.parametrize(
    "uri", ["https://example.com/callback?x=1", "https://example.com/callback#frag"]
)
def test_redirect_uri_rejects_query_and_fragment(uri):
    with pytest.raises(ValueError, match="must not include query or fragment"):
        validate_redirect_uri(uri)


@pytest.mark.parametrize(
    "path", ["/auth/callback/", "/auth/callback?x=1", "/auth/callback#frag"]
)
def test_redirect_path_rejects_non_canonical_variants(path):
    with pytest.raises(ValueError):
        validate_redirect_path(path)
