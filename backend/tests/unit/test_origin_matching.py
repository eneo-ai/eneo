from intric.allowed_origins.origin_matching import origin_matches_pattern


def test_origin_matches_exact_scheme_host_and_port():
    assert origin_matches_pattern("https://app.example.com", "https://app.example.com")
    assert origin_matches_pattern("https://app.example.com:443", "https://app.example.com")


def test_origin_does_not_match_on_scheme_or_port_mismatch():
    assert not origin_matches_pattern("http://app.example.com", "https://app.example.com")
    assert not origin_matches_pattern("https://app.example.com:8443", "https://app.example.com")


def test_origin_matches_wildcard_single_subdomain_level_only():
    assert origin_matches_pattern("https://app.example.com", "https://*.example.com")
    assert not origin_matches_pattern("https://deep.app.example.com", "https://*.example.com")


def test_origin_matches_host_only_pattern_and_wildcard():
    assert origin_matches_pattern("https://example.com", "example.com")
    assert origin_matches_pattern("https://app.example.com", "*.example.com")


def test_invalid_origin_or_pattern_returns_false():
    assert not origin_matches_pattern("not-a-url", "https://example.com")
    assert not origin_matches_pattern("https://example.com", "not-a-url")
