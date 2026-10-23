"""Where outbound headers may be sent (S8a / S8b / S8·0a)."""

import pytest

from eneo.model_providers.domain.outbound_header_destinations import (
    InvalidDestination,
    destination_problem,
    parse_allow_list,
    parse_destination,
    without_credentials,
)


def _problem(endpoint: str | None, *allowed: str) -> str | None:
    return destination_problem(endpoint, parse_allow_list(allowed))


class TestWithoutAllowList:
    @pytest.mark.parametrize("endpoint", [None, "", "   "])
    def test_an_explicit_endpoint_is_required(self, endpoint: str | None):
        assert _problem(endpoint) == "no_endpoint"

    @pytest.mark.parametrize(
        "endpoint",
        [
            "https://gateway.internal/v1",
            "http://vllm.internal:8000/v1",
            "http://127.0.0.1:4010",
        ],
    )
    def test_any_explicit_http_endpoint_is_allowed(self, endpoint: str):
        assert _problem(endpoint) is None

    def test_credentials_in_the_url_are_refused(self):
        assert _problem("https://user:pass@gateway.internal/v1") == "credentials_in_url"

    @pytest.mark.parametrize(
        "endpoint", ["gateway.internal/v1", "ftp://gateway.internal", "https://"]
    )
    def test_non_http_urls_are_invalid(self, endpoint: str):
        assert _problem(endpoint) == "invalid_endpoint"


class TestAllowList:
    def test_exact_match(self):
        assert (
            _problem("https://gateway.internal/v1", "https://gateway.internal/v1")
            is None
        )

    def test_no_suffix_matching(self):
        assert (
            _problem("https://evil-gateway.internal/v1", "https://gateway.internal")
            == "not_allowed"
        )
        assert (
            _problem(
                "https://gateway.internal.evil.example", "https://gateway.internal"
            )
            == "not_allowed"
        )

    def test_host_is_case_insensitive(self):
        assert (
            _problem("https://GATEWAY.internal/v1", "https://gateway.internal") is None
        )

    def test_idna_normalisation(self):
        assert (
            _problem("https://bücher.example/v1", "https://xn--bcher-kva.example")
            is None
        )

    def test_scheme_default_port_is_filled_in(self):
        assert (
            _problem("https://gateway.internal:443/v1", "https://gateway.internal")
            is None
        )
        assert (
            _problem("https://gateway.internal/v1", "https://gateway.internal:443")
            is None
        )

    def test_port_must_match(self):
        assert _problem(
            "https://gateway.internal:8443/v1", "https://gateway.internal"
        ) == ("not_allowed")

    def test_scheme_must_match(self):
        assert _problem("http://gateway.internal/v1", "https://gateway.internal") == (
            "not_allowed"
        )

    @pytest.mark.parametrize(
        ("endpoint", "allowed"),
        [
            ("https://gateway.internal/v1", True),
            ("https://gateway.internal/v1/", True),
            ("https://gateway.internal/v1/chat", True),
            ("https://gateway.internal/v1beta", False),
            ("https://gateway.internal/", False),
        ],
    )
    def test_path_matches_on_slash_boundaries(self, endpoint: str, allowed: bool):
        problem = _problem(endpoint, "https://gateway.internal/v1")
        assert (problem is None) is allowed

    def test_any_entry_may_admit(self):
        assert (
            _problem(
                "https://b.internal/v1", "https://a.internal", "https://b.internal"
            )
            is None
        )


class TestParseDestination:
    def test_errors_never_echo_the_url(self):
        with pytest.raises(InvalidDestination) as exc_info:
            parse_destination("https://user:hunter2@gateway.internal")
        assert "hunter2" not in str(exc_info.value)


class TestWithoutCredentials:
    """Audit records of an endpoint change never keep ``user:pass@``."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://user:pass@gateway.internal/v1", "https://gateway.internal/v1"),
            ("http://token@[::1]:8000/v1?x=@y", "http://[::1]:8000/v1?x=@y"),
            ("https://a@b@gateway.internal", "https://gateway.internal"),
            ("https://gateway.internal/v1/@me", "https://gateway.internal/v1/@me"),
            ("https://gateway.internal/v1", "https://gateway.internal/v1"),
            ("http://[bad", "http://[bad"),
            ("not a url", "not a url"),
            (None, None),
            ("", ""),
        ],
    )
    def test_strips_only_the_authority_userinfo(
        self, url: str | None, expected: str | None
    ):
        assert without_credentials(url) == expected
