"""One unattended tool call against a real local MCP endpoint."""

from __future__ import annotations

import asyncio
import gc
import gzip
import json
import time
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import JSONResponse, Response, StreamingResponse

from eneo.main.exceptions import (
    EncryptionNotConfiguredException,
    MCPClientError,
    MCPToolAnswerTooLarge,
    MCPToolCallTimedOut,
)
from eneo.mcp_servers.application.unattended_tool_call import (
    EXCHANGE_STOP_GRACE_SECONDS,
    EXCHANGE_TASK_NAME,
    UnattendedToolCaller,
)
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
from eneo.mcp_servers.infrastructure.client import mcp_client
from eneo.mcp_servers.infrastructure.client.mcp_client import (
    MCPClient,
    MCPHttpClientFactory,
    MCPToolAnswer,
    SdkHttpClientFactory,
)
from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_factory import (
    MCPProxySessionFactory,
)
from eneo.settings.encryption_service import EncryptionService
from tests.unit.mcp_test_server import (
    one_tool_app,
    serve_test_app,
    sse_message,
    sse_stream,
    tool_result,
    tool_result_message,
    unanswered,
)

pytestmark = pytest.mark.asyncio

DAYS = {"days": ["2026-01-03", "2026-01-09"], "count": 2}
LONG_TEXT = "x" * 60_000
CEILING = 64 * 1024
# The latest a call with a one-second budget may end, with room for the host.
ONE_SECOND_BUDGET_ENDS_BY = 1 + EXCHANGE_STOP_GRACE_SECONDS + 1
# An answer that is stopped fails its call at once, long before the budget of
# five seconds that those calls have.
AT_ONCE = 3


def _server(url: str) -> MCPServer:
    return MCPServer(tenant_id=uuid4(), name="one-tool", http_url=url)


async def _call(
    url: str,
    *,
    max_answer_bytes: int = 1024 * 1024,
    timeout: int = 5,
    http_client_factory: MCPHttpClientFactory | None = None,
):
    return await UnattendedToolCaller(MCPProxySessionFactory()).call(
        _server(url),
        "lookup",
        {"from": "2026-01-01"},
        max_answer_bytes=max_answer_bytes,
        timeout_seconds=timeout,
        http_client_factory=http_client_factory or SdkHttpClientFactory(),
    )


def _text(text: str) -> dict[str, object]:
    return {"content": [{"type": "text", "text": text}]}


def _oversized(request_id: object) -> dict[str, object]:
    return tool_result_message(request_id, _text("x" * (2 * CEILING)))


def _exchanges_still_running() -> int:
    return sum(
        task.get_name() == EXCHANGE_TASK_NAME and not task.done()
        for task in asyncio.all_tasks()
    )


def _connections_still_open() -> int:
    return sum(not task.done() for task in mcp_client._connection_hosts)


async def _stopped_as_too_large(url: str) -> float:
    """Seconds until a call with a five-second budget fails as too large."""
    started = time.monotonic()
    with pytest.raises(MCPToolAnswerTooLarge, match=f"more than {CEILING} bytes"):
        await _call(url, max_answer_bytes=CEILING)
    return time.monotonic() - started


async def test_the_answer_arrives_as_sent_with_every_block_accounted_for() -> None:
    # Kills the mutants that leave the structured content unread, that join
    # the text blocks into one text (two JSON documents are then none), that
    # drop the
    # blocks that are not text without saying that there were any, and that
    # read the result with the SDK's model (one block of a kind it does not
    # know, the last one here, fails the whole call).
    app = one_tool_app(
        lambda request_id: tool_result(
            request_id,
            {
                "content": [
                    {"type": "text", "text": LONG_TEXT},
                    {"type": "image", "data": "aGk=", "mimeType": "image/png"},
                    {
                        "type": "resource",
                        "resource": {"uri": "file:///case.txt", "text": "inside"},
                    },
                    {"type": "text", "text": "second block"},
                    {"type": "chart", "series": [1, 2]},
                ],
                "structuredContent": DAYS,
            },
        )
    )
    async with serve_test_app(app) as url:
        answer = await _call(url)

    assert answer == MCPToolAnswer(
        text_blocks=(LONG_TEXT, "second block"),
        other_blocks=3,
        structured=DAYS,
        is_error=False,
    )


async def test_a_tool_that_says_it_failed_is_an_answer_not_a_failed_call() -> None:
    # Kills the mutant that reads the tool's own error flag as "no call was
    # made": the caller has to see the tool's message and decide.
    app = one_tool_app(
        lambda request_id: tool_result(
            request_id, {**_text("no such case"), "isError": True}
        )
    )
    async with serve_test_app(app) as url:
        answer = await _call(url)

    assert answer == MCPToolAnswer(("no such case",), 0, None, True)


async def test_every_request_carries_the_credential_stored_for_the_server() -> None:
    # Kills the mutants that connect without the server's credential and that
    # send it as it is stored, encrypted.
    encryption = EncryptionService(Fernet.generate_key().decode())
    sent: set[str | None] = set()

    async def note_the_credential(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        sent.add(request.headers.get("authorization"))
        return await call_next(request)

    app = one_tool_app(lambda request_id: tool_result(request_id, _text("ok")))
    app.middleware("http")(note_the_credential)
    async with serve_test_app(app) as url:
        server = MCPServer(
            tenant_id=uuid4(),
            name="one-tool",
            http_url=url,
            http_auth_type="bearer",
            http_auth_config_schema={"token": encryption.encrypt("stored-token")},
        )
        await UnattendedToolCaller(MCPProxySessionFactory(encryption)).call(
            server,
            "lookup",
            {},
            max_answer_bytes=CEILING,
            timeout_seconds=5,
            http_client_factory=SdkHttpClientFactory(),
        )

    assert sent == {"Bearer stored-token"}


@pytest.mark.parametrize(
    ("reads_with", "cause"),
    [
        pytest.param("another-key", ValueError, id="another-key"),
        pytest.param(None, EncryptionNotConfiguredException, id="no-key"),
    ],
)
async def test_a_stored_credential_that_cannot_be_read_is_a_failed_call(
    reads_with: str | None, cause: type[Exception]
) -> None:
    # Kills the mutants that let what decrypting raises out of the caller as
    # it is (the flow step maps the MCP failures only) and that put its text,
    # which can quote the stored value, into the message. Nothing is sent.
    stored = EncryptionService(Fernet.generate_key().decode()).encrypt("stored-token")
    reading = EncryptionService(Fernet.generate_key().decode() if reads_with else None)
    app = one_tool_app(lambda request_id: tool_result(request_id, _text("ok")))
    async with serve_test_app(app) as url:
        server = MCPServer(
            tenant_id=uuid4(),
            name="one-tool",
            http_url=url,
            http_auth_type="bearer",
            http_auth_config_schema={"token": stored},
        )
        with pytest.raises(MCPClientError) as failure:
            await UnattendedToolCaller(MCPProxySessionFactory(reading)).call(
                server,
                "lookup",
                {},
                max_answer_bytes=CEILING,
                timeout_seconds=5,
                http_client_factory=SdkHttpClientFactory(),
            )

    assert type(failure.value) is MCPClientError
    assert type(failure.value.__cause__) is cause
    assert str(failure.value) == (
        "Tool call failed: the server's stored credential could not be read"
    )
    assert app.state.requests == []


async def test_only_the_call_is_sent_and_the_tools_output_schema_is_not_applied() -> (
    None
):
    # Kills the mutant that calls through the SDK's call_tool: it asks for the
    # tool list after the call and fails the call when the tool declares an
    # output schema and sent no structured content. The caller checks the
    # answer against its own contract.
    app = one_tool_app(
        lambda request_id: tool_result(request_id, _text("plain")),
        output_schema={"type": "object", "required": ["days"]},
    )
    async with serve_test_app(app) as url:
        answer = await _call(url)

    assert answer == MCPToolAnswer(("plain",), 0, None, False)
    assert app.state.requests == [
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]


async def test_an_answer_over_the_ceiling_is_stopped_while_it_arrives() -> None:
    # Kills the mutant without a ceiling for tools/call (the whole answer is
    # received and decoded) and the one that reports the stop as any failure.
    chunks_sent = 0
    total_chunks = 512
    stream_closed = asyncio.Event()

    def oversized(request_id: object) -> Response:
        prefix = (
            b'{"jsonrpc":"2.0","id":'
            + json.dumps(request_id).encode()
            + b',"result":{"content":[{"type":"text","text":"'
        )

        async def body() -> AsyncIterator[bytes]:
            nonlocal chunks_sent
            try:
                yield prefix
                for _ in range(total_chunks):
                    chunks_sent += 1
                    yield b"x" * 4096
                    await asyncio.sleep(0.001)
                yield b'"}]}}'
            finally:
                stream_closed.set()

        return StreamingResponse(body(), media_type="application/json")

    async with serve_test_app(one_tool_app(oversized)) as url:
        await _stopped_as_too_large(url)

    await asyncio.wait_for(stream_closed.wait(), timeout=1)
    assert chunks_sent < total_chunks


async def test_an_answer_sent_as_an_event_stream_counts_against_the_ceiling() -> None:
    # Kills the mutant that counts only a JSON body: a server chooses how it
    # answers, and an event of any size would be decoded.
    app = one_tool_app(
        lambda request_id: sse_stream([sse_message(_oversized(request_id))])
    )
    async with serve_test_app(app) as url:
        assert await _stopped_as_too_large(url) < AT_ONCE


async def test_an_answer_declared_larger_than_the_ceiling_is_refused_unread() -> None:
    # Kills the mutant that only counts what arrives: this server declares the
    # size and sends nothing, so the call would wait out its time.
    async def nothing() -> AsyncIterator[bytes]:
        await app.state.shutting_down.wait()
        yield b""

    app = one_tool_app(
        lambda _: StreamingResponse(
            nothing(),
            media_type="application/json",
            headers={"content-length": str(CEILING + 1)},
        )
    )
    async with serve_test_app(app) as url:
        assert await _stopped_as_too_large(url) < AT_ONCE


async def test_an_answer_on_the_listening_stream_counts_against_the_ceiling() -> None:
    # Kills the mutant that bounds only the response to tools/call (this
    # server answers 202 and sends the answer on the stream the client
    # listens on, where an answer of any size was decoded) and the one that
    # learns which call waits only when its request is answered (the answer is
    # stopped, and the call then waits out its time).
    answers: asyncio.Queue[bytes] = asyncio.Queue()
    stream_closed = asyncio.Event()

    def listening(_: Request) -> Response:
        async def events() -> AsyncIterator[bytes]:
            try:
                while True:
                    yield await answers.get()
            finally:
                stream_closed.set()

        return sse_stream(events())

    async def accepted(request_id: object) -> Response:
        answers.put_nowait(sse_message(_oversized(request_id)))
        # The request itself is answered after the client met the answer.
        await asyncio.wait_for(stream_closed.wait(), timeout=AT_ONCE)
        return Response(status_code=202)

    app = one_tool_app(accepted, session_id="session-1", get_response=listening)
    async with serve_test_app(app) as url:
        assert await _stopped_as_too_large(url) < AT_ONCE


async def test_an_answer_on_a_reopened_stream_counts_against_the_ceiling() -> None:
    # Kills the mutant that bounds only the response to tools/call: this
    # server opens the answer as an event stream, names an event and closes;
    # the SDK asks again from that event and gets the answer there.
    waiting: list[object] = []
    reopened_from: list[str | None] = []

    def opened_and_closed(request_id: object) -> Response:
        waiting.append(request_id)
        return sse_stream([b"id: event-1\nretry: 10\n\n"])

    def reopened(request: Request) -> Response:
        reopened_from.append(request.headers.get("last-event-id"))
        return sse_stream([sse_message(_oversized(waiting[0]))])

    app = one_tool_app(opened_and_closed, get_response=reopened)
    async with serve_test_app(app) as url:
        assert await _stopped_as_too_large(url) < AT_ONCE

    assert reopened_from == ["event-1"]


async def test_a_compressed_answer_is_refused_as_compressed_not_as_too_large() -> None:
    # Kills the mutant that reports every refused answer as too large: a
    # small answer that is compressed is a server that ignores what was asked
    # for, and raising the limit would not help its author.
    def compressed(request_id: object) -> Response:
        return Response(
            gzip.compress(json.dumps(tool_result_message(request_id, {})).encode()),
            media_type="application/json",
            headers={"content-encoding": "gzip"},
        )

    async with serve_test_app(one_tool_app(compressed)) as url:
        with pytest.raises(MCPClientError, match="is compressed") as failure:
            await _call(url, max_answer_bytes=CEILING)

    assert type(failure.value) is MCPClientError


async def test_a_server_error_is_not_reported_as_an_answer_that_was_too_large() -> None:
    # Kills the mutant that reads the ceiling from the error the SDK raises:
    # a server can send the same JSON-RPC error itself.
    def refused(request_id: object) -> Response:
        return Response(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "MCP tools/call wire response exceeds the "
                        "configured maximum of 65536 bytes",
                    },
                }
            ),
            media_type="application/json",
        )

    async with serve_test_app(one_tool_app(refused)) as url:
        with pytest.raises(MCPClientError) as failure:
            await _call(url, max_answer_bytes=CEILING)

    assert type(failure.value) is MCPClientError


async def test_a_stopped_answer_is_not_remembered_for_the_next_call() -> None:
    # Kills the mutant that keeps "too large" after the call it was for: the
    # next failed call on the same client would be reported as too large.
    calls = 0

    def first_too_large_then_refused(request_id: object) -> Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return tool_result(request_id, _text(LONG_TEXT))
        return Response(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32000, "message": "not today"},
                }
            ),
            media_type="application/json",
        )

    async with serve_test_app(one_tool_app(first_too_large_then_refused)) as url:
        async with MCPClient(_server(url), tool_call_max_bytes=1024) as client:
            with pytest.raises(MCPToolAnswerTooLarge):
                await client.call_tool_as_sent("lookup", {})
            with pytest.raises(MCPClientError, match="not today") as second:
                await client.call_tool_as_sent("lookup", {})

    assert type(second.value) is MCPClientError


async def test_a_stream_stopped_while_no_call_waits_fails_no_call() -> None:
    # Kills the mutants that tie a stopped stream to a call that does not
    # wait: to the call before (its request still noted after it ended) or to
    # the call after (which inherits "too large"). Either way the server's own
    # refusal of the next call would be reported as an answer over the ceiling.
    flood = asyncio.Event()
    stream_closed = asyncio.Event()
    calls = 0

    def listening(_: Request) -> Response:
        async def events() -> AsyncIterator[bytes]:
            try:
                await flood.wait()
                yield b": " + b"x" * 4096 + b"\n\n"
                await app.state.shutting_down.wait()
            finally:
                stream_closed.set()

        return sse_stream(events())

    def answered_then_refused(request_id: object) -> Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return tool_result(request_id, _text("ok"))
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32000, "message": "not today"},
            }
        )

    app = one_tool_app(
        answered_then_refused, session_id="session-1", get_response=listening
    )
    async with serve_test_app(app) as url:
        async with MCPClient(_server(url), tool_call_max_bytes=1024) as client:
            await client.call_tool_as_sent("lookup", {})
            flood.set()
            await asyncio.wait_for(stream_closed.wait(), timeout=AT_ONCE)
            with pytest.raises(MCPClientError, match="not today") as refused:
                await client.call_tool_as_sent("lookup", {})

    assert type(refused.value) is MCPClientError


async def test_a_request_the_server_fails_is_a_failed_call_not_a_cancellation() -> None:
    # Kills the mutant that hands on however the exchange ended: the SDK's
    # transport cancels the task it runs in when a request of its own fails,
    # and a caller that nobody cancelled would be told that it was.
    app = one_tool_app(lambda _: Response(status_code=500))
    async with serve_test_app(app) as url:
        with pytest.raises(MCPClientError) as failure:
            await _call(url)

    assert type(failure.value) is MCPClientError


async def test_connecting_and_calling_share_one_time_budget() -> None:
    # Kills the mutant that gives each part of the exchange its own time:
    # connect and call each stay within the second here, and together pass it.
    async def slow_tool(request_id: object) -> Response:
        await asyncio.sleep(0.7)
        return tool_result(request_id, _text("late"))

    app = one_tool_app(slow_tool, before_initialize=lambda: asyncio.sleep(0.7))
    async with serve_test_app(app) as url:
        started = time.monotonic()
        with pytest.raises(MCPToolCallTimedOut, match="within 1s"):
            await _call(url, timeout=1)
        elapsed = time.monotonic() - started

    assert elapsed < ONE_SECOND_BUDGET_ENDS_BY


async def test_closing_sends_nothing_that_a_server_could_leave_unanswered() -> None:
    # Kills the mutant that ends the server's session on close: this server
    # never answers that request, and the stopped exchange would hang on it
    # for the transport's read timeout instead of ending within the grace.
    app = one_tool_app(
        lambda _: unanswered(app),
        session_id="session-1",
        delete_response=lambda: unanswered(app),
    )
    async with serve_test_app(app) as url:
        started = time.monotonic()
        with pytest.raises(MCPToolCallTimedOut, match="within 1s"):
            await _call(url, timeout=1)
        elapsed = time.monotonic() - started
        still_running = _exchanges_still_running()

    assert elapsed < ONE_SECOND_BUDGET_ENDS_BY
    assert "DELETE" not in app.state.requests
    assert still_running == 0


async def test_an_exchange_stopped_while_it_connects_leaves_no_connection_behind() -> (
    None
):
    # Kills the mutant that lets the connection a stopped exchange was opening
    # finish on its own. This server never answers an initialize: the budget
    # ends during connect, and the exchange ends at once, as the client does
    # not ask a server why a connect it was stopped in failed. Left to itself,
    # the connection would stay on the handshake, with the credential, until
    # the client's own disconnect deadline; it must go with the exchange.
    app = one_tool_app(
        lambda request_id: tool_result(request_id, _text("never asked")),
        before_initialize=lambda: app.state.shutting_down.wait(),
    )

    async with serve_test_app(app) as url:
        started = time.monotonic()
        with pytest.raises(MCPToolCallTimedOut, match="within 1s"):
            await _call(url, timeout=1)
        elapsed = time.monotonic() - started
        still_running = _exchanges_still_running()
        async with asyncio.timeout(EXCHANGE_STOP_GRACE_SECONDS):
            while _connections_still_open():
                await asyncio.sleep(0.01)

    assert elapsed < ONE_SECOND_BUDGET_ENDS_BY
    assert still_running == 0
    assert app.state.requests == ["initialize"]


async def test_an_exchange_that_does_not_stop_when_told_is_let_go_and_ends_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Kills the mutant that waits for a stopped exchange as long as it takes,
    # and the one that lets go without reading how the exchange ended (asyncio
    # then reports an exception that nobody retrieved). A close that goes on
    # through every cancellation stands in for anything in an exchange that
    # does.
    loop = asyncio.get_running_loop()
    goes_on_for = 3 * EXCHANGE_STOP_GRACE_SECONDS
    close = MCPClient.disconnect

    async def close_that_does_not_stop(client: MCPClient) -> None:
        ends = loop.time() + goes_on_for
        while (left := ends - loop.time()) > 0:
            try:
                await asyncio.sleep(left)
            except asyncio.CancelledError:
                continue
        await close(client)

    monkeypatch.setattr(MCPClient, "disconnect", close_that_does_not_stop)
    app = one_tool_app(lambda request_id: tool_result(request_id, _text("ok")))
    unretrieved: list[object] = []
    handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _, context: unretrieved.append(context))
    try:
        async with serve_test_app(app) as url:
            started = time.monotonic()
            with pytest.raises(MCPToolCallTimedOut, match="within 1s"):
                await _call(url, timeout=1)
            elapsed = time.monotonic() - started
            let_go = _exchanges_still_running()
            for _ in range(int(goes_on_for * 100)):
                if not _exchanges_still_running():
                    break
                await asyncio.sleep(0.01)
            ended_alone = not _exchanges_still_running()
        gc.collect()
    finally:
        loop.set_exception_handler(handler)

    assert elapsed < ONE_SECOND_BUDGET_ENDS_BY
    assert (let_go, ended_alone) == (1, True)
    assert unretrieved == []


@pytest.mark.parametrize(
    "cancelled", ["after-the-budget", "a-second-time", "twice-in-a-row"]
)
async def test_a_caller_cancelled_while_it_stops_the_exchange_still_stops_it(
    cancelled: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Kills the mutants whose stop ends at a cancellation of the caller, or
    # goes on without waiting its share out. This server never answers the
    # call, and the close that follows the cancelled call is held until it is
    # cancelled in turn: an exchange that was told to stop once would stay in
    # it, with the connection and the credential, as long as the server
    # likes. The caller is cancelled while the exchange is in that close
    # (after its budget ended, or for a second time), or twice in a row, the
    # second time before the exchange has got as far as the close.
    in_the_call = asyncio.Event()
    closing = asyncio.Event()
    close = MCPClient.disconnect

    async def held_call(_: object) -> Response:
        in_the_call.set()
        return await unanswered(app)

    async def close_held_until_cancelled(client: MCPClient) -> None:
        closing.set()
        try:
            await app.state.shutting_down.wait()
        except asyncio.CancelledError:
            await close(client)
            raise

    monkeypatch.setattr(MCPClient, "disconnect", close_held_until_cancelled)
    app = one_tool_app(held_call)

    async with serve_test_app(app) as url:
        caller = asyncio.create_task(
            _call(url, timeout=1 if cancelled == "after-the-budget" else 5)
        )
        if cancelled != "after-the-budget":
            await asyncio.wait_for(in_the_call.wait(), timeout=3)
            caller.cancel()
        if cancelled == "twice-in-a-row":
            await asyncio.sleep(0)
        else:
            await asyncio.wait_for(closing.wait(), timeout=3)
        caller.cancel()
        await asyncio.wait({caller}, timeout=ONE_SECOND_BUDGET_ENDS_BY)
        still_running = _exchanges_still_running()

    assert caller.done() and caller.cancelled()
    assert still_running == 0


@pytest.mark.parametrize("phase", ["connect", "call", "close"])
async def test_a_cancelled_caller_is_cancelled_wherever_the_exchange_is(
    phase: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Kills the mutant that runs the exchange in the caller's own task. The
    # client answers a cancellation during connect with "could not connect"
    # and goes on closing through one during close, so the caller was told
    # that the call failed, or got the answer, and ran on after being
    # cancelled. During the call it kills the one that waits for the answer
    # before it lets the cancellation through.
    reached = asyncio.Event()

    async def held_on_the_first_connect() -> None:
        if not reached.is_set():
            reached.set()
            await app.state.shutting_down.wait()

    async def held_call(_: object) -> Response:
        reached.set()
        return await unanswered(app)

    close = MCPClient.disconnect

    async def close_that_takes_a_moment(client: MCPClient) -> None:
        reached.set()
        try:
            await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            # As the client's close does when a cancellation arrives while it
            # waits for a context to close: it goes on with the next one.
            pass
        await close(client)

    if phase == "connect":
        app = one_tool_app(held_call, before_initialize=held_on_the_first_connect)
    elif phase == "call":
        app = one_tool_app(held_call)
    else:
        app = one_tool_app(lambda request_id: tool_result(request_id, _text("ok")))
        monkeypatch.setattr(MCPClient, "disconnect", close_that_takes_a_moment)

    async with serve_test_app(app) as url:
        caller = asyncio.create_task(_call(url))
        await asyncio.wait_for(reached.wait(), timeout=3)
        caller.cancel()
        await asyncio.wait({caller}, timeout=ONE_SECOND_BUDGET_ENDS_BY)
        still_running = _exchanges_still_running()

    assert caller.done() and caller.cancelled()
    assert still_running == 0


async def test_a_client_without_a_ceiling_takes_an_answer_of_any_size() -> None:
    # Kills the mutant that gives every client the ceiling: chat's proxy
    # passes none, and its tools answer as before.
    app = one_tool_app(lambda request_id: tool_result(request_id, _text(LONG_TEXT)))
    async with serve_test_app(app) as url:
        async with MCPClient(_server(url)) as client:
            result = await client.call_tool("lookup", {})

    assert result["content"][0]["text"] == LONG_TEXT
