"""Calls to the OpenID provider end at a deadline, never follow a redirect,
and a refused token request is logged by its status and protocol code only.

The provider here is a real local HTTP server and the session is the real
shared one, so what is tested is the session's own deadline, not a fake's.
"""

import asyncio
import json
import logging
import socket
import time
from collections.abc import AsyncIterator, Iterator
from uuid import uuid4

import pytest
from aiohttp import web

from eneo.authentication.oidc import verification
from eneo.authentication.oidc.errors import OidcResponseNotVerifiedError
from eneo.authentication.oidc.profile import OidcProfile
from eneo.authentication.oidc.transaction import OidcTransaction
from eneo.main import aiohttp_client as aiohttp_client_module
from eneo.main.aiohttp_client import aiohttp_client
from eneo.main.config import get_settings, set_settings
from eneo.main.logging import OTELJSONFormatter

ISSUER = "https://idp.example"
ADDRESS = "person@example.com"
NAME = "Person Example"


@pytest.fixture
async def provider() -> AsyncIterator[str]:
    """A provider whose token endpoints hang, refuse, or answer in prose."""
    release = asyncio.Event()

    async def hangs(request: web.Request) -> web.Response:  # noqa: ARG001
        await release.wait()
        return web.json_response({})

    async def refuses(request: web.Request) -> web.Response:
        errors = {"code": "invalid_grant", "prose": f"no account for {ADDRESS}"}
        return web.json_response(
            {
                "error": errors[request.match_info["error"]],
                "error_description": f"The user account {ADDRESS} ({NAME}) does not exist",
                "error_uri": f"https://idp.example/help?user={ADDRESS}",
            },
            status=400,
        )

    async def prose(request: web.Request) -> web.Response:  # noqa: ARG001
        return web.Response(status=502, text=f"Upstream refused {ADDRESS} ({NAME})")

    async def redirects(request: web.Request) -> web.Response:
        raise web.HTTPTemporaryRedirect(location=request.query["to"])

    app = web.Application()
    app.router.add_post("/redirects", redirects)
    app.router.add_post("/hangs", hangs)
    app.router.add_post("/refuses/{error}", refuses)
    app.router.add_post("/prose", prose)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        release.set()
        await runner.cleanup()


@pytest.fixture
async def sink() -> AsyncIterator[tuple[str, list[str]]]:
    """A second server, recording every request that reaches it."""
    seen: list[str] = []

    async def record(request: web.Request) -> web.Response:
        seen.append(f"{request.method} {request.path}")
        return web.json_response({"access_token": "a", "id_token": "i"})

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", record)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][:2]
    try:
        yield f"http://{host}:{port}", seen
    finally:
        await runner.cleanup()


@pytest.fixture
async def shared_session(monkeypatch) -> AsyncIterator[None]:
    """The real shared session, started with a short deadline, in development,
    where a provider may run on this machine."""
    monkeypatch.setattr(
        aiohttp_client_module, "REQUEST_TIMEOUT_SECONDS", 0.5, raising=False
    )
    monkeypatch.setattr(aiohttp_client, "session", None)
    original = get_settings()
    set_settings(original.model_copy(update={"environment": "development"}))
    aiohttp_client.start()
    try:
        yield
    finally:
        await aiohttp_client.stop()
        set_settings(original)


@pytest.fixture
def logged() -> Iterator[list[str]]:
    """What the verification module logs, formatted as it is shipped."""
    lines: list[str] = []
    formatter = OTELJSONFormatter()

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(formatter.format(record))

    handler = Capture()
    verification.logger.addHandler(handler)
    try:
        yield lines
    finally:
        verification.logger.removeHandler(handler)


def _profile(token_endpoint: str) -> OidcProfile:
    return OidcProfile(
        issuer=ISSUER,
        client_id="client",
        client_secret="secret",
        authorization_endpoint=f"{ISSUER}/authorize",
        token_endpoint=token_endpoint,
        token_endpoint_auth_method="client_secret_post",
        jwks_uri=f"{ISSUER}/jwks",
        signing_algorithms=("RS256",),
        scopes=("openid", "email"),
        email_claim="email",
        subject_claim="sub",
        email_verified_claims=("email_verified",),
        iss_parameter_supported=False,
    )


def _transaction() -> OidcTransaction:
    return OidcTransaction(
        id="transaction",
        purpose="login",
        nonce="nonce",
        code_verifier="verifier",
        redirect_uri="https://eneo.example/login/callback",
        tenant_id=str(uuid4()),
        tenant_slug="tenant",
        config_version=None,
        issued_at=int(time.time()),
        issuer=ISSUER,
        iss_parameter_supported=False,
        channel="api",
        binding_challenge=None,
    )


async def test_a_token_endpoint_that_never_answers_ends_the_exchange_within_the_bound(
    provider, shared_session
):
    started = time.monotonic()
    async with asyncio.timeout(10):
        with pytest.raises(OidcResponseNotVerifiedError):
            await verification._exchange_code(
                _profile(f"{provider}/hangs"), _transaction(), "code", "correlation"
            )

    assert time.monotonic() - started < 3


async def test_a_token_endpoint_that_refuses_the_connection_is_the_fixed_refusal(
    shared_session,
):
    """Not a 500: the sign-in ends with the same 401 as any failed exchange."""
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        port = unused.getsockname()[1]

    with pytest.raises(OidcResponseNotVerifiedError):
        await verification._exchange_code(
            _profile(f"http://127.0.0.1:{port}/token"),
            _transaction(),
            "code",
            "correlation",
        )


@pytest.mark.parametrize(
    ("path", "oauth_error"),
    [
        ("/refuses/code", "invalid_grant"),
        ("/refuses/prose", None),
        ("/prose", None),
    ],
    ids=["protocol-code", "prose-in-error", "not-json"],
)
async def test_a_token_endpoint_error_logs_only_its_status_and_protocol_code(
    provider, shared_session, logged, path, oauth_error
):
    with pytest.raises(OidcResponseNotVerifiedError):
        await verification._exchange_code(
            _profile(f"{provider}{path}"), _transaction(), "code", "correlation"
        )

    [failure] = [line for line in logged if "Token exchange failed" in line]
    assert ADDRESS not in failure
    assert NAME not in failure
    attributes = json.loads(failure)["attributes"]
    assert attributes["correlation_id"] == "correlation"
    assert attributes["http_status"] in {400, 502}
    assert attributes.get("oauth_error") == oauth_error


async def test_a_token_endpoint_that_redirects_is_refused_and_not_followed(
    provider, sink, shared_session
):
    """A 307 keeps the method and body: following it would hand the code and
    the client secret to whatever the provider names."""
    elsewhere, seen = sink
    with pytest.raises(OidcResponseNotVerifiedError):
        await verification._exchange_code(
            _profile(f"{provider}/redirects?to={elsewhere}/token"),
            _transaction(),
            "code",
            "correlation",
        )

    assert seen == []
