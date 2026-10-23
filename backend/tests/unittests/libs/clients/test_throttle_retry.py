from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from eneo.libs.clients.http_client import WrappedAiohttpClient
from eneo.libs.clients.throttle_retry import (
    THROTTLE_AND_OVERLOAD_STATUS_CODES,
    TRANSIENT_STATUS_CODES,
    parse_retry_after,
    retry_on_throttle,
)
from eneo.main.exceptions import InternalHTTPException


def _response_error(status: int, headers: dict[str, str] | None = None):
    return aiohttp.ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=status,
        message="boom",
        headers=headers or {},
    )


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds_honoring_retry_after():
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _response_error(429, {"Retry-After": "2"})
        return "ok"

    with patch("asyncio.sleep", new=AsyncMock()) as sleep:
        result = await retry_on_throttle(fn)

    assert result == "ok"
    assert calls["n"] == 3
    # Slept exactly the Retry-After value before each retry.
    assert sleep.await_count == 2
    assert all(call.args[0] == 2.0 for call in sleep.await_args_list)


@pytest.mark.asyncio
async def test_retries_on_429_without_retry_after_uses_backoff():
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _response_error(429, {})
        return "ok"

    with patch("asyncio.sleep", new=AsyncMock()) as sleep:
        result = await retry_on_throttle(fn)

    assert result == "ok"
    assert calls["n"] == 2
    # Fell back to a positive backoff wait rather than Retry-After.
    assert sleep.await_count == 1
    assert sleep.await_args_list[0].args[0] > 0


@pytest.mark.asyncio
async def test_retries_on_503():
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _response_error(503, {"Retry-After": "1"})
        return "ok"

    with patch("asyncio.sleep", new=AsyncMock()):
        result = await retry_on_throttle(
            fn,
            retryable_status_codes=THROTTLE_AND_OVERLOAD_STATUS_CODES,
        )

    assert result == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_default_policy_does_not_retry_503():
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        raise _response_error(503, {"Retry-After": "1"})

    with patch("asyncio.sleep", new=AsyncMock()) as sleep:
        with pytest.raises(aiohttp.ClientResponseError) as excinfo:
            await retry_on_throttle(fn)

    assert excinfo.value.status == 503
    assert calls["n"] == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_reraises_after_max_attempts_exhausted():
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        raise _response_error(429, {"Retry-After": "0"})

    with patch("asyncio.sleep", new=AsyncMock()):
        with pytest.raises(aiohttp.ClientResponseError) as excinfo:
            await retry_on_throttle(fn, max_attempts=3)

    assert excinfo.value.status == 429
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_does_not_retry_non_throttle_error():
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        raise _response_error(401, {})

    with patch("asyncio.sleep", new=AsyncMock()) as sleep:
        with pytest.raises(aiohttp.ClientResponseError) as excinfo:
            await retry_on_throttle(fn)

    assert excinfo.value.status == 401
    assert calls["n"] == 1
    sleep.assert_not_awaited()


def _wrapped(error: BaseException) -> InternalHTTPException:
    try:
        raise InternalHTTPException from error
    except InternalHTTPException as wrapped:
        return wrapped


_TRANSIENT_FAILURES = [
    pytest.param(lambda: _response_error(502), id="502"),
    pytest.param(lambda: _response_error(504), id="504"),
    pytest.param(
        lambda: aiohttp.ClientOSError(104, "Connection reset by peer"),
        id="connection-reset",
    ),
    pytest.param(lambda: aiohttp.ServerDisconnectedError(), id="disconnected"),
    pytest.param(
        lambda: aiohttp.ClientPayloadError("Response payload is not completed"),
        id="payload",
    ),
    pytest.param(lambda: TimeoutError(), id="timeout"),
    pytest.param(
        lambda: _wrapped(aiohttp.ClientPayloadError("cut off")),
        id="wrapped-payload",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", _TRANSIENT_FAILURES)
async def test_transient_failures_are_retried_when_the_request_is_repeatable(failure):
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise failure()
        return "ok"

    with patch("asyncio.sleep", new=AsyncMock()):
        result = await retry_on_throttle(
            fn,
            retryable_status_codes=TRANSIENT_STATUS_CODES,
            retry_transport_errors=True,
        )

    assert result == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", _TRANSIENT_FAILURES)
async def test_transient_failures_are_not_retried_by_default(failure):
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        raise failure()

    with patch("asyncio.sleep", new=AsyncMock()):
        with pytest.raises(Exception):
            await retry_on_throttle(fn)

    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_transient_failures_stop_after_the_attempt_budget():
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        raise aiohttp.ServerDisconnectedError()

    with patch("asyncio.sleep", new=AsyncMock()):
        with pytest.raises(aiohttp.ServerDisconnectedError):
            await retry_on_throttle(fn, retry_transport_errors=True, max_attempts=4)

    assert calls["n"] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(
            lambda: aiohttp.ClientSSLError(MagicMock(), OSError("bad certificate")),
            id="tls",
        ),
        pytest.param(lambda: _response_error(500), id="500"),
        pytest.param(lambda: _response_error(404), id="404"),
        pytest.param(lambda: ValueError("not a transport error"), id="value"),
    ],
)
async def test_failures_about_the_request_are_never_retried(failure):
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        raise failure()

    with patch("asyncio.sleep", new=AsyncMock()):
        with pytest.raises(Exception):
            await retry_on_throttle(
                fn,
                retryable_status_codes=TRANSIENT_STATUS_CODES,
                retry_transport_errors=True,
            )

    assert calls["n"] == 1


class _Response:
    def __init__(self, error: BaseException | None = None) -> None:
        self._error = error

    async def __aenter__(self):
        if self._error:
            raise self._error
        return self

    async def __aexit__(self, *_exc):
        return False

    def raise_for_status(self) -> None:
        pass

    async def json(self):
        return {"value": ["ok"]}


@pytest.mark.asyncio
async def test_a_get_survives_a_gateway_error_and_a_reset_connection():
    client = WrappedAiohttpClient("https://graph.microsoft.com")
    await client.close()
    client.client = MagicMock()
    client.client.get = MagicMock(
        side_effect=[
            _Response(_response_error(502)),
            _Response(aiohttp.ClientOSError(104, "Connection reset by peer")),
            _Response(),
        ]
    )

    with patch("asyncio.sleep", new=AsyncMock()):
        result = await client.get("v1.0/drives/d/root/children")

    assert result == {"value": ["ok"]}
    assert client.client.get.call_count == 3


def test_parse_retry_after_integer_seconds():
    assert parse_retry_after("5") == 5.0


@pytest.mark.asyncio
async def test_retry_after_uses_separate_server_cap():
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _response_error(429, {"Retry-After": "120"})
        return "ok"

    with patch("asyncio.sleep", new=AsyncMock()) as sleep:
        result = await retry_on_throttle(
            fn,
            max_backoff=1,
            max_retry_after=300,
        )

    assert result == "ok"
    assert sleep.await_args_list[0].args[0] == 120.0


@pytest.mark.asyncio
async def test_retry_after_is_capped_by_retry_after_cap():
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _response_error(429, {"Retry-After": "400"})
        return "ok"

    with patch("asyncio.sleep", new=AsyncMock()) as sleep:
        result = await retry_on_throttle(fn, max_retry_after=300)

    assert result == "ok"
    assert sleep.await_args_list[0].args[0] == 300.0


def test_parse_retry_after_absent():
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None


def test_parse_retry_after_http_date():
    future = datetime.now(timezone.utc) + timedelta(seconds=30)
    parsed = parse_retry_after(format_datetime(future))
    assert parsed is not None
    assert 25 <= parsed <= 31


def test_parse_retry_after_invalid_returns_none():
    assert parse_retry_after("not-a-date") is None
