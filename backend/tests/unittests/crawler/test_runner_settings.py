"""create_runner() hardening: only http(s) handlers, no ambient proxy, and the
destination guard installed on the reactor with the operator's allowlist."""

from unittest.mock import patch

import crochet
import pytest

# Setup crochet BEFORE importing crawler (module-level @crochet.run_in_reactor).
crochet.setup()

from twisted.internet import reactor  # noqa: E402

from intric.crawler.crawler import create_runner  # noqa: E402
from intric.crawler.destination_policy import GuardedNameResolver  # noqa: E402


@pytest.fixture
def runner(tmp_path):
    return create_runner(filepath=tmp_path / "out.jsonl")


def test_non_http_download_handlers_are_disabled(runner):
    # Scrapy enables these by default; the runner must explicitly switch them
    # off (a missing key would leave the default handler active).
    from scrapy.settings.default_settings import DOWNLOAD_HANDLERS_BASE

    effective = runner.settings.getwithbase("DOWNLOAD_HANDLERS")
    for scheme in ("file", "data", "ftp", "s3"):
        assert DOWNLOAD_HANDLERS_BASE[scheme]
        assert scheme in effective
        assert effective[scheme] is None


def test_http_handlers_remain(runner):
    effective = runner.settings.getwithbase("DOWNLOAD_HANDLERS")
    assert effective["http"] and effective["https"]


def test_ambient_proxy_is_not_used(runner):
    assert runner.settings.getbool("HTTPPROXY_ENABLED") is False


def test_destination_guard_is_installed_from_settings(tmp_path):
    import ipaddress

    with patch("intric.crawler.crawler.get_settings") as get_settings:
        get_settings.return_value.crawler_block_private_networks = False
        create_runner(filepath=tmp_path / "out.jsonl")

    guard = reactor.nameResolver
    assert isinstance(guard, GuardedNameResolver)
    assert guard.policy.allows(ipaddress.ip_address("10.20.1.1")) is True
    assert guard.policy.allows(ipaddress.ip_address("127.0.0.1")) is False

    # A later runner with CRAWLER_BLOCK_PRIVATE_NETWORKS=true swaps the policy
    # in place; the guard itself is installed once.
    with patch("intric.crawler.crawler.get_settings") as get_settings:
        get_settings.return_value.crawler_block_private_networks = True
        create_runner(filepath=tmp_path / "out2.jsonl")
    assert reactor.nameResolver is guard
    assert guard.policy.allows(ipaddress.ip_address("10.20.1.1")) is False
    assert guard.policy.allows(ipaddress.ip_address("8.8.8.8")) is True
