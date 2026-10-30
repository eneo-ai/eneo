"""One reading of a flow HTTP URL, used at authoring and at runtime."""

from __future__ import annotations

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from eneo.flows.http_transport.effective_url import (
    HTTP_URL_SCHEMES,
    InvalidHttpUrl,
    parse_effective_http_url,
)
from eneo.flows.http_transport.errors import HttpTransportError
from eneo.flows.http_transport.validator import validate_http_url
from tests.unittests.flows.egress.egress_test_support import INVALID_URLS

VALID = [
    ("http://example.com", "http", "example.com", 80),
    ("https://Example.COM:8443/p?q=1#f", "https", "example.com", 8443),
    ("  http://example.com/x  ", "http", "example.com", 80),
    ("http://example.com:80/", "http", "example.com", 80),
    ("https://example.com:443/", "https", "example.com", 443),
    ("http://[2606:4700::1]:8080/x", "http", "2606:4700::1", 8080),
    ("http://[2606:4700::1]/", "http", "2606:4700::1", 80),
    ("http://93.184.216.34/", "http", "93.184.216.34", 80),
    ("http://xn--nicode-2ya.example/", "http", "xn--nicode-2ya.example", 80),
    ("http://ünicode.example/", "http", "xn--nicode-2ya.example", 80),
    ("http://svc_name.internal/", "http", "svc_name.internal", 80),
    ("http://example.com./", "http", "example.com.", 80),
    # Address spellings the policy judges by what they resolve to.
    ("http://127.1/", "http", "127.1", 80),
    ("http://2130706433/", "http", "2130706433", 80),
    ("http://0x7f000001/", "http", "0x7f000001", 80),
    ("http://127.0.0.1/", "http", "127.0.0.1", 80),
]


def test_the_only_schemes_are_http_and_https():
    assert HTTP_URL_SCHEMES == {"http", "https"}


@pytest.mark.parametrize(("text", "scheme", "host", "port"), VALID)
def test_a_valid_url_reads_as_what_httpx_will_connect_to(text, scheme, host, port):
    parsed = parse_effective_http_url(text)
    assert (parsed.scheme, parsed.host, parsed.port) == (scheme, host, port)
    assert isinstance(parsed.url, httpx.URL)
    assert parsed.url.raw_host.decode("ascii").lower() == host
    assert validate_http_url(text) is None


@pytest.mark.parametrize("text", INVALID_URLS, ids=repr)
def test_an_invalid_url_is_refused_by_the_parser_and_by_authoring(text):
    with pytest.raises(InvalidHttpUrl):
        parse_effective_http_url(text)
    assert validate_http_url(text) in {
        HttpTransportError.INVALID_URL,
        HttpTransportError.MISSING_URL,
    }


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_an_empty_url_is_missing_at_authoring(text):
    assert validate_http_url(text) is HttpTransportError.MISSING_URL


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("ftp://example.com/", "Unsupported HTTP URL scheme: 'ftp'."),
        ("http:///path", "HTTP URL must include a hostname."),
        ("http://a.com:abc/", "HTTP URL is not valid."),
        ("http://user@example.com/", "HTTP URL must not contain credentials."),
    ],
)
def test_the_reason_is_the_message_users_see(text, message):
    with pytest.raises(InvalidHttpUrl, match=message.replace(".", r"\.")):
        parse_effective_http_url(text)


_URL_ATOMS = [
    "http://",
    "https://",
    "a",
    "b.c",
    "xn--",
    "xn--a",
    "xn--bcher-kva",
    "127.0.0.1",
    "[::1]",
    ":",
    "80",
    "0",
    "@",
    "/",
    "%",
    "ü",
    "ß",
    "-",
    "_",
    " ",
    ".",
]


@settings(max_examples=3000, deadline=None, derandomize=True)
@given(
    st.lists(st.sampled_from(_URL_ATOMS), min_size=1, max_size=10).map("".join),
    st.sampled_from(["", "http://", "https://"]),
)
def test_a_url_the_parser_accepts_never_breaks_the_request_builder(text, scheme):
    """The parse is where a URL is refused: whatever it accepts, httpx can turn
    into a request. Nothing untyped may surface later, after a client exists."""
    try:
        parsed = parse_effective_http_url(scheme + text)
    except InvalidHttpUrl:
        return
    request = httpx.Request("GET", parsed.url)
    assert request.url.raw_host.decode("ascii").lower() == parsed.host
