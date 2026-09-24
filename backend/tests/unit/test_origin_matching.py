import pytest

from eneo.allowed_origins.origin_matching import (
    normalize_origin_pattern,
    origin_matches_pattern,
)


def test_origin_matches_exact_scheme_host_and_port():
    assert origin_matches_pattern("https://app.example.com", "https://app.example.com")
    assert origin_matches_pattern(
        "https://app.example.com:443", "https://app.example.com"
    )


def test_origin_does_not_match_on_scheme_or_port_mismatch():
    assert not origin_matches_pattern(
        "http://app.example.com", "https://app.example.com"
    )
    assert not origin_matches_pattern(
        "https://app.example.com:8443", "https://app.example.com"
    )


def test_origin_matches_wildcard_single_subdomain_level_only():
    assert origin_matches_pattern("https://app.example.com", "https://*.example.com")
    assert not origin_matches_pattern(
        "https://deep.app.example.com", "https://*.example.com"
    )


def test_origin_matches_host_only_pattern_and_wildcard():
    assert origin_matches_pattern("https://example.com", "example.com")
    assert origin_matches_pattern("https://app.example.com", "*.example.com")


def test_invalid_origin_or_pattern_returns_false():
    assert not origin_matches_pattern("not-a-url", "https://example.com")
    assert not origin_matches_pattern("https://example.com", "not-a-url")


def test_port_wildcard_matches_any_port_on_same_scheme_host():
    """``http://localhost:*`` matches the host on any port — useful for dev."""
    assert origin_matches_pattern("http://localhost:5173", "http://localhost:*")
    assert origin_matches_pattern("http://localhost:6006", "http://localhost:*")
    assert origin_matches_pattern("http://localhost:80", "http://localhost:*")
    assert origin_matches_pattern("http://localhost", "http://localhost:*")


def test_port_wildcard_still_pins_scheme_and_host():
    """Port wildcard does not relax scheme or host."""
    # Different scheme → no match even though port wildcard would match.
    assert not origin_matches_pattern("https://localhost:5173", "http://localhost:*")
    # Different host → no match.
    assert not origin_matches_pattern("http://other.local:5173", "http://localhost:*")


def test_port_wildcard_combines_with_subdomain_wildcard():
    """``https://*.example.com:*`` matches any subdomain on any port."""
    assert origin_matches_pattern(
        "https://app.example.com:8443", "https://*.example.com:*"
    )
    assert origin_matches_pattern(
        "https://admin.example.com", "https://*.example.com:*"
    )
    # But still only one subdomain level.
    assert not origin_matches_pattern(
        "https://a.b.example.com:8443", "https://*.example.com:*"
    )


def test_malformed_port_in_origin_fails_closed():
    """If the inbound Origin somehow has a malformed port, deny rather than 500."""
    assert not origin_matches_pattern("http://localhost:abc", "http://localhost:*")


# The widget editor mirrors this rule (frontend/apps/web/src/lib/features/
# widget/admin/origins.test.ts holds the same table), so a value the field
# accepts is never refused by the save and the other way round.
_PARITY = [
    ("https://www.kommun.se", "https://www.kommun.se"),
    ("https://www.kommun.se/", "https://www.kommun.se"),
    ("https://www.kommun.se/kontakt", None),
    ("HTTPS://WWW.Kommun.SE//", "https://www.kommun.se"),
    ("https://*.kommun.se", "https://*.kommun.se"),
    ("http://localhost:*", "http://localhost:*"),
    ("http://localhost:3000", "http://localhost:3000"),
    ("http://localhost:", None),
    ("http://localhost:99999", None),
    ("http://localhost:65535", "http://localhost:65535"),
    ("https://user@kommun.se", None),
    ("https://kommun.se?x=1", None),
    ("https://kommun.se#frag", None),
    ("ftp://kommun.se", None),
    ("kommun.se", None),
    ("https://", None),
    ("https://[::1]", None),
    ("https://[::1]:8080", "https://[::1]:8080"),
    ("https://[::1]:*", "https://[::1]:*"),
    ("https://kom mun.se", None),
    ("https://kommun.se;script", None),
    ("https://-bad.se", None),
    ("https://bad-.se", None),
    ("https://a..se", None),
    ("https://*.*.se", None),
    ("https://xn--bcher-kva.example", "https://xn--bcher-kva.example"),
    ("https://1.2.3.4:443", "https://1.2.3.4:443"),
    ("http://localhost:08", "http://localhost:08"),
    ("https://kommun.se:abc", None),
    ("https://[zz]", None),
    ("https://example.com?", None),
    ("https://example.com#", None),
    ("https://@example.com", None),
    ("https://example.com:000080", "https://example.com:000080"),
    ("https://[abc.def]:80", None),
    ("https://[1.2.3.4]:80", None),
    ("https://[:::]:80", None),
    ("https://[::ffff:1.2.3.4]:80", "https://[::ffff:1.2.3.4]:80"),
]


@pytest.mark.parametrize(("pattern", "expected"), _PARITY)
def test_normalize_origin_pattern_matches_the_editor(pattern, expected):
    if expected is None:
        with pytest.raises(ValueError):
            normalize_origin_pattern(pattern)
    else:
        assert normalize_origin_pattern(pattern) == expected
