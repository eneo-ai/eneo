"""The widget load script's exit verdict, run against a stub widget server."""

import argparse
from collections.abc import Callable

import altcha
import httpx

from tests.load import widget_load

VISITORS = 3


def _args(*extra: str) -> argparse.Namespace:
    return widget_load.parse_args(
        [
            "--base-url",
            "http://widgets.test",
            "--public-id",
            "wgt_load",
            "--visitors",
            str(VISITORS),
            "--messages",
            "1",
            "--concurrency",
            str(VISITORS),
            *extra,
        ]
    )


def _refusal(status: int, code: str, *, retry_after: bool = True) -> httpx.Response:
    return httpx.Response(
        status,
        json={"detail": {"code": code, "message": "Refused."}},
        headers={"Retry-After": "30"} if retry_after else {},
    )


def _issued_challenge() -> httpx.Response:
    challenge = altcha.create_challenge(
        "SHA-256", 1, key_prefix="0", hmac_secret="load-test"
    )
    return httpx.Response(200, json=challenge.to_dict())


def _widget_server(challenge: Callable[[], httpx.Response]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/ask/") and "authorization" not in request.headers:
            return _refusal(401, "visitor_token_invalid", retry_after=False)
        if path.endswith("/challenge/"):
            return challenge()
        if path.endswith("/visitor-sessions/"):
            return httpx.Response(200, json={"token": "visitor-token"})
        if path.endswith("/ask/"):
            return httpx.Response(
                200,
                text='data: {"session_id": "s1"}\n\n',
                headers={"Content-Type": "text/event-stream"},
            )
        return httpx.Response(404)

    return httpx.MockTransport(handle)


async def test_a_refusal_without_retry_after_fails_the_run():
    args = _args()
    report = await widget_load.run(
        args,
        _widget_server(
            lambda: _refusal(429, "rate_limited_challenge", retry_after=False)
        ),
    )

    assert report.retry_after_missing == VISITORS
    assert widget_load.failures(report, args) == [
        f"{VISITORS} 429/503 responses had no Retry-After"
    ]


async def test_refusals_with_retry_after_pass():
    args = _args()
    report = await widget_load.run(
        args, _widget_server(lambda: _refusal(429, "rate_limited_challenge"))
    )

    assert report.statuses == {"429": VISITORS}
    assert report.unauthenticated_asks_rejected == VISITORS
    assert widget_load.failures(report, args) == []


async def test_redis_down_passes_when_every_visitor_is_refused_with_503():
    args = _args("--expect-redis-down")
    report = await widget_load.run(
        args, _widget_server(lambda: _refusal(503, "rate_limit_unavailable"))
    )

    assert widget_load.failures(report, args) == []


async def test_redis_down_fails_when_the_protection_fails_open():
    args = _args("--expect-redis-down")
    report = await widget_load.run(args, _widget_server(_issued_challenge))

    # Each visitor minted a token and was answered.
    assert report.statuses == {"200": 2 * VISITORS}
    assert widget_load.failures(report, args) == [
        f"with Redis down, {VISITORS} of {VISITORS} visitors were not refused"
        " with 503 rate_limit_unavailable"
    ]
    assert widget_load.failures(report, _args()) == []


async def test_redis_down_fails_when_the_refusal_is_not_the_protection():
    args = _args("--expect-redis-down")
    report = await widget_load.run(
        args, _widget_server(lambda: _refusal(503, "upstream_unavailable"))
    )

    assert widget_load.failures(report, args) == [
        f"with Redis down, {VISITORS} of {VISITORS} visitors were not refused"
        " with 503 rate_limit_unavailable"
    ]
