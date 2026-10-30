"""A local HTTP server for tests that need a real MCP transport."""

import asyncio
import json
import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, Response
from starlette.responses import JSONResponse, StreamingResponse

Answer = Response | Awaitable[Response]


@asynccontextmanager
async def serve_test_app(app: FastAPI) -> AsyncIterator[str]:
    """Run an ASGI app over a real local TCP socket for transport tests."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    sock.setblocking(False)
    host, port = sock.getsockname()
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            log_config=None,
            lifespan="off",
            access_log=False,
            ws="none",
        )
    )
    app.state.shutting_down = asyncio.Event()
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        else:
            raise RuntimeError("test MCP server did not start")
        yield f"http://{host}:{port}/mcp"
    finally:
        # Requests held by ``unanswered`` end here, so a failed test does not
        # leave the server waiting for them.
        app.state.shutting_down.set()
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)


async def unanswered(app: FastAPI) -> Response:
    """Hold a request until the test server shuts down."""
    await app.state.shutting_down.wait()
    return Response(status_code=503)


def one_tool_app(
    call_response: Callable[[object], Answer],
    *,
    output_schema: dict[str, object] | None = None,
    before_initialize: Callable[[], Awaitable[object]] | None = None,
    session_id: str | None = None,
    get_response: Callable[[Request], Answer] | None = None,
    delete_response: Callable[[], Answer] | None = None,
    tool_meta: dict[str, object] | None = None,
    read_response: Callable[[object], Answer] | None = None,
    extra_tools: Iterable[dict[str, object]] = (),
) -> FastAPI:
    """An MCP endpoint with one tool, ``lookup``, answered by ``call_response``.

    ``call_response`` gets the JSON-RPC id of the ``tools/call`` request and
    returns the HTTP response for it. ``tools/list`` is answered too, with
    ``output_schema`` on the tool, for a client that asks for the catalog.
    ``before_initialize`` runs before each ``initialize`` is answered.
    ``tool_meta`` is the tool's ``_meta``; ``read_response`` gets the
    JSON-RPC id of a ``resources/read`` request and answers it.
    ``extra_tools`` are listed after ``lookup``.

    A server that gives ``session_id`` assigns that session: the SDK then
    opens its listening stream (a GET, answered by ``get_response``) and may
    end the session when it closes (a DELETE, answered by
    ``delete_response``). ``get_response`` also answers the GET with which
    the SDK reopens a stream that the server closed. Without a handler either
    request is answered 405.

    ``app.state.requests`` lists what arrived, in order: the JSON-RPC method
    of a POST, ``GET`` or ``DELETE``.
    """
    app = FastAPI()
    requests: list[str] = []
    app.state.requests = requests

    @app.post("/mcp")
    async def post(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
        payload = await request.json()
        method, request_id = payload.get("method"), payload.get("id")
        requests.append(str(method))
        if method == "initialize":
            if before_initialize is not None:
                await before_initialize()
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "one-tool", "version": "1"},
                    },
                },
                headers={"mcp-session-id": session_id} if session_id else None,
            )
        if method == "notifications/initialized":
            return Response(status_code=202)
        if method == "tools/list":
            tool: dict[str, object] = {
                "name": "lookup",
                "inputSchema": {"type": "object"},
            }
            if output_schema is not None:
                tool["outputSchema"] = output_schema
            if tool_meta is not None:
                tool["_meta"] = tool_meta
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"tools": [tool, *extra_tools]},
                }
            )
        if method == "tools/call":
            return await _answered(call_response(request_id))
        if method == "resources/read" and read_response is not None:
            return await _answered(read_response(request_id))
        return Response(status_code=400)

    @app.get("/mcp")
    async def get(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
        requests.append("GET")
        if get_response is None:
            return Response(status_code=405)
        return await _answered(get_response(request))

    @app.delete("/mcp")
    async def delete() -> Response:  # pyright: ignore[reportUnusedFunction]
        requests.append("DELETE")
        if delete_response is None:
            return Response(status_code=405)
        return await _answered(delete_response())

    return app


async def _answered(answer: Answer) -> Response:
    return await answer if isinstance(answer, Awaitable) else answer


def tool_result_message(
    request_id: object, result: dict[str, object]
) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def tool_result(request_id: object, result: dict[str, object]) -> JSONResponse:
    return JSONResponse(tool_result_message(request_id, result))


def sse_message(message: dict[str, object], *, event_id: str | None = None) -> bytes:
    """One server-sent event that carries a JSON-RPC message."""
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}event: message\ndata: {json.dumps(message)}\n\n".encode()


def sse_stream(events: AsyncIterator[bytes] | Iterable[bytes]) -> StreamingResponse:
    return StreamingResponse(events, media_type="text/event-stream")
