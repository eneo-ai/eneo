from __future__ import annotations

from types import MappingProxyType

from intric.flows.http_transport.normalizer import is_authored_config

# --- is_authored_config ---


def test_is_authored_config_true_for_config_with_auth_key() -> None:
    assert (
        is_authored_config({"auth": {"mode": "none"}, "url": "https://example.org"})
        is True
    )


def test_is_authored_config_false_for_config_without_auth_key() -> None:
    assert is_authored_config({"url": "https://example.org", "headers": {}}) is False


def test_is_authored_config_accepts_read_only_mapping() -> None:
    config = MappingProxyType({"auth": {"mode": "none"}, "url": "https://example.org"})

    assert is_authored_config(config) is True


def test_is_authored_config_false_for_none() -> None:
    assert is_authored_config(None) is False


def test_is_authored_config_false_for_empty_dict() -> None:
    assert is_authored_config({}) is False
