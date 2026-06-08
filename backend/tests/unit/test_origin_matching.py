from intric.allowed_origins.origin_matching import origin_matches_pattern


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
