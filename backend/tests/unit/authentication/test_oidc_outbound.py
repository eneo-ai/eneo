"""Every request Eneo sends to an OpenID provider goes through one owner.

The rules are checked against real aiohttp servers on 127.0.0.1 through the
real shared session, so the redirect, size and resolver checks run in aiohttp
as they do in production.
"""

import inspect
import json
import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from typing import Any

import aiohttp
import pytest
from aiohttp import web

from eneo.authentication.oidc import outbound
from eneo.authentication.oidc.outbound import OidcFetchError
from eneo.crawler import destination_policy
from eneo.main.aiohttp_client import aiohttp_client
from eneo.main.config import get_settings, set_settings

REFUSED = "the provider's address is not allowed"


@pytest.fixture
def in_environment() -> Iterator[Callable[[str], None]]:
    """Run in one ENVIRONMENT; only development lets a provider be on this
    machine."""
    original = get_settings()

    def use(environment: str) -> None:
        set_settings(original.model_copy(update={"environment": environment}))

    yield use
    set_settings(original)


@pytest.fixture
async def session(monkeypatch, in_environment) -> AsyncIterator[Callable[[str], None]]:
    """Start the real shared session in one ENVIRONMENT."""
    monkeypatch.setattr(aiohttp_client, "session", None)

    def start(environment: str) -> None:
        in_environment(environment)
        aiohttp_client.start()

    try:
        yield start
    finally:
        await aiohttp_client.stop()


class _Recorder:
    """A session that records each request instead of sending it."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def get(self, url: str, **kwargs: Any) -> None:
        self.sent.append(url)

    post = get


@asynccontextmanager
async def _serve(app: web.Application) -> AsyncIterator[int]:
    runner = web.AppRunner(app)
    await runner.setup()
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(("127.0.0.1", 0))
    server_socket.listen(16)
    port = server_socket.getsockname()[1]
    await web.SockSite(runner, server_socket).start()
    try:
        yield port
    finally:
        await runner.cleanup()


def _app(routes: dict[str, Any]) -> tuple[web.Application, list[str]]:
    seen: list[str] = []

    async def handle(request: web.Request) -> web.StreamResponse:
        seen.append(f"{request.method} {request.path}")
        answer = routes[request.path]
        if not callable(answer):
            return answer
        response = answer(request)
        return await response if inspect.isawaitable(response) else response

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handle)
    return app, seen


async def test_a_provider_on_this_machine_is_served_over_http_in_development(
    session,
):
    session("development")
    app, seen = _app(
        {
            "/discovery": web.json_response({"issuer": "http://127.0.0.1"}),
            "/token": lambda request: web.json_response({"access_token": "a"}),
        }
    )
    async with _serve(app) as port:
        assert await outbound.get_json(f"http://127.0.0.1:{port}/discovery") == {
            "issuer": "http://127.0.0.1"
        }
        assert await outbound.post_form(
            f"http://localhost:{port}/token", {"code": "c"}
        ) == (200, {"access_token": "a"})
    assert seen == ["GET /discovery", "POST /token"]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:{port}/discovery",
        "http://localhost:{port}/discovery",
        "https://localhost:{port}/discovery",
    ],
)
async def test_this_machine_is_refused_outside_development(session, url):
    """An administrator could otherwise point the backend at its own
    loopback services."""
    session("production")
    app, seen = _app({"/discovery": web.json_response({})})
    async with _serve(app) as port:
        with pytest.raises(OidcFetchError) as refused:
            await outbound.get_json(url.format(port=port))
    assert refused.value.reason == REFUSED
    assert seen == []


@pytest.mark.parametrize(
    "url",
    [
        "http://[::1]:9134/discovery",
        # Full-width digits and dots: aiohttp connects to 127.0.0.1.
        "https://127\u30020\u30020\u30021/discovery",
        "https://\uff11\uff12\uff17.0.0.1/discovery",
    ],
)
async def test_other_spellings_of_loopback_are_refused_outside_development(
    in_environment, monkeypatch, url
):
    in_environment("production")
    recorder = _Recorder()
    monkeypatch.setattr(aiohttp_client, "session", recorder)
    with pytest.raises(OidcFetchError) as refused:
        await outbound.get_json(url)
    assert refused.value.reason == REFUSED
    assert recorder.sent == []


@pytest.mark.parametrize("environment", ["production", "development"])
async def test_another_name_for_this_machine_is_refused(
    session, monkeypatch, environment
):
    """Only the loopback names themselves are this machine; a public name
    that resolves (or rebinds) to loopback is refused in either mode."""

    class _ToLoopback:
        async def resolve(self, host: str, port: int = 0, family: int = 0) -> list:
            return [
                {
                    "hostname": host,
                    "host": "127.0.0.1",
                    "port": port,
                    "family": socket.AF_INET,
                    "proto": 0,
                    "flags": socket.AI_NUMERICHOST,
                }
            ]

        async def close(self) -> None:
            return None

    monkeypatch.setattr(destination_policy, "DefaultResolver", _ToLoopback)
    session(environment)
    with pytest.raises(OidcFetchError) as refused:
        await outbound.get_json("https://idp.example.org/discovery")
    assert refused.value.reason == REFUSED


@pytest.mark.parametrize(
    "url",
    [
        "http://idp.example.org/.well-known/openid-configuration",
        "http://10.0.0.5/token",
        "ftp://idp.example.org/x",
        "https://user:secret@idp.example.org/token",
        "https:///no-host",
        # Link-local and cloud metadata addresses, and IPv4 inside IPv6.
        "https://169.254.169.254/latest/meta-data",
        "https://[fd00:ec2::254]/latest/meta-data",
        "https://100.100.100.200/latest/meta-data",
        "https://[::ffff:127.0.0.1]/token",
        "http://[::ffff:127.0.0.1]/token",
        "https://0.0.0.0/token",
        # Full-width dots: aiohttp reads these as 169.254.169.254 and connects
        # without resolving, so the resolver never sees them.
        "https://169\u3002254\u3002169\u3002254/latest/meta-data",
        "https://169\uff0e254\uff0e169\uff0e254/latest/meta-data",
        # A URL aiohttp cannot read.
        "https://idp.example.org:bad/token",
        "https://idp.example.org:99999/token",
        "https://[invalid/token",
    ],
)
@pytest.mark.parametrize("environment", ["production", "development"])
async def test_refused_destinations_are_never_requested(
    in_environment, monkeypatch, url, environment
):
    in_environment(environment)
    recorder = _Recorder()
    monkeypatch.setattr(aiohttp_client, "session", recorder)
    with pytest.raises(OidcFetchError):
        await outbound.get_json(url)
    assert recorder.sent == []


@pytest.mark.parametrize(
    "url",
    [
        "https://idp.example.org/.well-known/openid-configuration",
        # Private addresses: the operator chooses the provider.
        "https://10.0.0.5/token",
        "https://[fd12:3456::1]/token",
    ],
)
def test_allowed_destinations_pass_the_url_check(url):
    outbound.check_url(url)


@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_a_redirect_is_refused_and_not_followed(session, method):
    session("development")
    app, seen = _app(
        {
            "/token": web.Response(status=307, headers={"Location": "/elsewhere"}),
            "/elsewhere": web.json_response({"access_token": "a"}),
        }
    )
    async with _serve(app) as port:
        url = f"http://127.0.0.1:{port}/token"
        with pytest.raises(OidcFetchError) as refused:
            if method == "GET":
                await outbound.get_json(url)
            else:
                await outbound.post_form(url, {"client_secret": "s"})
    assert "redirect" in refused.value.reason
    assert seen == [f"{method} /token"]


@pytest.mark.parametrize("declared", [True, False])
async def test_an_answer_above_the_limit_is_refused(session, declared):
    session("development")
    body = json.dumps({"keys": ["k" * outbound.MAX_RESPONSE_BYTES]}).encode()

    async def large(request: web.Request) -> web.StreamResponse:
        if declared:
            return web.Response(body=body, content_type="application/json")
        response = web.StreamResponse()  # chunked: no Content-Length
        await response.prepare(request)
        for start in range(0, len(body), 8192):
            await response.write(body[start : start + 8192])
        return response

    app, _ = _app({"/jwks": large})
    async with _serve(app) as port:
        with pytest.raises(OidcFetchError) as refused:
            await outbound.get_json(f"http://127.0.0.1:{port}/jwks")
    assert "256 KiB" in refused.value.reason


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]", b'"text"'])
async def test_an_answer_that_is_not_a_json_object_is_refused(session, body):
    session("development")
    app, _ = _app({"/discovery": web.Response(body=body)})
    async with _serve(app) as port:
        with pytest.raises(OidcFetchError) as refused:
            await outbound.get_json(f"http://127.0.0.1:{port}/discovery")
    assert refused.value.reason == "the answer is not a JSON object"


async def test_an_error_answer_is_handed_back_with_its_status(session):
    """The token exchange reads the protocol code from it; nothing here
    interprets what the provider wrote."""
    session("development")
    answer = {"error": "invalid_grant", "error_description": "code abc123 expired"}
    app, _ = _app({"/token": web.json_response(answer, status=400)})
    async with _serve(app) as port:
        assert await outbound.post_form(
            f"http://127.0.0.1:{port}/token", {"code": "c"}
        ) == (400, answer)


async def test_an_unreachable_provider_raises_as_aiohttp_does(session):
    session("development")
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        port = unused.getsockname()[1]
    request: Awaitable[object] = outbound.get_json(f"http://127.0.0.1:{port}/x")
    with pytest.raises(aiohttp.ClientConnectionError):
        await request
