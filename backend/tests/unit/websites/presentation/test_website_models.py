"""Website URLs must be http(s) with a host name. Early feedback at the API;
the crawler's destination policy is the actual protection."""

import pytest
from pydantic import ValidationError

from eneo.main.models import NOT_PROVIDED
from eneo.websites.presentation.website_models import WebsiteCreate, WebsiteUpdate


@pytest.mark.parametrize(
    "url",
    [
        "https://www.sundsvall.se",
        "http://intranet.example/x",
        "HTTPS://Example.com/Path?q=1",
    ],
)
def test_create_accepts_http_urls(url: str):
    assert WebsiteCreate(url=url).url == url


def test_create_trims_surrounding_whitespace():
    assert (
        WebsiteCreate(url="  https://www.sundsvall.se ").url
        == "https://www.sundsvall.se"
    )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/hostname",
        "ftp://example.com/a",
        "data:text/plain,hi",
        "https://",
        "www.sundsvall.se",
        "",
        "https://example.com:abc/",
        "https://example.com:70000/",
    ],
)
def test_create_rejects_non_http_urls(url: str):
    with pytest.raises(ValidationError):
        WebsiteCreate(url=url)


@pytest.mark.parametrize("url", ["file:///etc/hostname", "https://example.com:abc/"])
def test_update_rejects_non_http_url(url: str):
    with pytest.raises(ValidationError):
        WebsiteUpdate(url=url)


def test_update_accepts_http_url_and_omitted_url():
    assert WebsiteUpdate(url="https://example.com").url == "https://example.com"
    assert WebsiteUpdate().url is NOT_PROVIDED
    assert WebsiteUpdate(name="x").url is NOT_PROVIDED
