"""Where an endpoint sends requests, and which key may go there."""

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.model_providers.domain.endpoints import (
    normalize_destination,
    require_key_for_destination,
)


class TestDestinationNormalization:
    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("https://api.example.com", "https://api.example.com/"),
            ("https://api.example.com", "HTTPS://API.Example.com"),
            ("https://api.example.com", "https://api.example.com:443"),
            ("http://vllm:8000", "http://vllm:8000/"),
            ("http://vllm", "http://vllm:80"),
            ("https://api.example.com/v1", "https://api.example.com/v1/"),
        ],
    )
    def test_equivalent_destinations_compare_equal(self, left: str, right: str):
        assert normalize_destination(left) == normalize_destination(right)

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("https://api.example.com", "http://api.example.com"),
            ("https://api.example.com", "https://api.example.org"),
            ("https://api.example.com", "https://api.example.com:8443"),
            ("https://api.example.com", "https://api.example.com/v1"),
            ("https://api.example.com/v1", "https://api.example.com/v2"),
            ("https://api.example.com", "https://api.example.com?region=eu"),
        ],
    )
    def test_different_destinations_compare_unequal(self, left: str, right: str):
        assert normalize_destination(left) != normalize_destination(right)

    def test_blank_and_missing_are_no_destination(self):
        assert normalize_destination(None) is None
        assert normalize_destination("   ") is None


class TestKeyForDestination:
    def test_an_unchanged_destination_keeps_the_stored_key(self):
        require_key_for_destination(
            stored_destination="https://vemsa.example.se",
            proposed_destination="HTTPS://vemsa.example.se:443/",
            key_stored=True,
            replacement_key=None,
        )

    @pytest.mark.parametrize("replacement", [None, "", "   "])
    def test_a_moved_destination_needs_a_typed_key(self, replacement):
        with pytest.raises(BadRequestException, match="new API key"):
            require_key_for_destination(
                stored_destination="https://vemsa.example.se",
                proposed_destination="https://other.example.se",
                key_stored=True,
                replacement_key=replacement,
            )

    def test_a_moved_destination_accepts_a_typed_key(self):
        require_key_for_destination(
            stored_destination="https://vemsa.example.se",
            proposed_destination="https://other.example.se",
            key_stored=True,
            replacement_key="new-secret",
        )

    @pytest.mark.parametrize("masked", ["...abcd", "****", "•••"])
    def test_a_masked_display_value_is_never_a_key(self, masked):
        with pytest.raises(BadRequestException, match="masked display value"):
            require_key_for_destination(
                stored_destination="https://vemsa.example.se",
                proposed_destination="https://vemsa.example.se",
                key_stored=True,
                replacement_key=masked,
            )
