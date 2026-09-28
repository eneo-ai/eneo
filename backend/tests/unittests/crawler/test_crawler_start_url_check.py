"""A start URL that can never be an allowed destination fails immediately
with a clear reason instead of going through the crawler's retries."""

from types import SimpleNamespace
from unittest.mock import patch

import crochet
import pytest

# Setup crochet BEFORE importing crawler (module-level @crochet.run_in_reactor).
crochet.setup()

from intric.crawler.crawler import _check_start_url  # noqa: E402
from intric.main.exceptions import CrawlerException  # noqa: E402


@pytest.fixture(autouse=True)
def default_policy():
    with patch("intric.crawler.crawler.get_settings") as get_settings:
        get_settings.return_value = SimpleNamespace(
            crawler_block_private_networks=False
        )
        yield


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8123/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/",
    ],
)
async def test_refused_literal_fails_with_reason(url: str):
    with pytest.raises(CrawlerException, match="not an allowed destination"):
        await _check_start_url(url)


async def test_refused_name_reports_resolved_address():
    with patch("intric.crawler.crawler.socket.getaddrinfo") as getaddrinfo:
        getaddrinfo.return_value = [(None, None, None, None, ("127.0.0.1", 0))]
        with pytest.raises(CrawlerException, match="localhost resolves to 127.0.0.1"):
            await _check_start_url("http://localhost:8123/")


async def test_allowed_literal_passes():
    await _check_start_url("http://8.8.8.8/")
    await _check_start_url("http://10.20.0.5/")  # private allowed by default


async def test_private_literal_refused_when_blocked():
    with patch("intric.crawler.crawler.get_settings") as get_settings:
        get_settings.return_value = SimpleNamespace(crawler_block_private_networks=True)
        with pytest.raises(CrawlerException):
            await _check_start_url("http://10.20.0.5/")


async def test_unresolvable_host_is_left_to_the_crawler():
    import socket

    with patch("intric.crawler.crawler.socket.getaddrinfo") as getaddrinfo:
        getaddrinfo.side_effect = socket.gaierror("nx")
        await _check_start_url("http://nx.invalid/")


@pytest.mark.parametrize("url", ["file:///etc/hostname", "ftp://x/", "https://"])
async def test_non_http_or_missing_host_is_refused(url: str):
    with pytest.raises(CrawlerException, match="only http\\(s\\) URLs"):
        await _check_start_url(url)
