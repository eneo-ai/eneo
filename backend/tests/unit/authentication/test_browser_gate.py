"""The browser gate decides from Sec-Fetch-Site alone whether a request may use
the session cookie. A missing header passes only a GET or HEAD without Origin:
supported browsers always send it, so such a request is a same-origin read or a
non-browser client, never a cross-origin page."""

import pytest
from starlette.datastructures import Headers

from eneo.authentication.browser_session import browser_request_allowed

ALL_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")


@pytest.mark.parametrize(
    ("method", "headers", "expected"),
    [
        *[(m, {"Sec-Fetch-Site": "same-origin"}, True) for m in ALL_METHODS],
        ("GET", {"Sec-Fetch-Site": "none"}, True),
        ("HEAD", {"Sec-Fetch-Site": "none"}, True),
        ("POST", {"Sec-Fetch-Site": "none"}, False),
        ("DELETE", {"Sec-Fetch-Site": "none"}, False),
        # A sibling or another tenant's host is same-site, not same-origin.
        *[(m, {"Sec-Fetch-Site": "same-site"}, False) for m in ALL_METHODS],
        *[(m, {"Sec-Fetch-Site": "cross-site"}, False) for m in ALL_METHODS],
        ("GET", {}, True),
        ("HEAD", {}, True),
        ("POST", {}, False),
        ("DELETE", {}, False),
        ("GET", {"Origin": "https://sibling.example.se"}, False),
        ("HEAD", {"Origin": "https://eneo.example.se"}, False),
        ("POST", {"Sec-Fetch-Site": "Same-Origin"}, True),
        ("get", {"Sec-Fetch-Site": "none"}, True),
        ("GET", {"Sec-Fetch-Site": ""}, False),
    ],
)
def test_browser_gate_matrix(method, headers, expected):
    assert browser_request_allowed(method, Headers(headers)) is expected
