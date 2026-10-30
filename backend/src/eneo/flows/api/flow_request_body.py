from __future__ import annotations

from collections.abc import Callable, Coroutine, MutableMapping
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import FileTooLargeException


def body_too_large(max_bytes: int, message: str | None = None) -> FileTooLargeException:
    return FileTooLargeException(
        message
        or f"The request is larger than the {max_bytes} bytes this route accepts.",
        code=FlowApiErrorCode.REQUEST_BODY_TOO_LARGE.value,
        context={"max_bytes": max_bytes},
        max_size=max_bytes,
    )


async def read_body_within(
    request: Request, max_bytes: int, *, message: str | None = None
) -> bytes:
    """The request body, refused as soon as it is known to exceed ``max_bytes``.

    Nothing is parsed here: a declared length over the cap is refused before a
    byte is read, and a streamed body is refused at the chunk that crosses it.
    """
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > max_bytes:
        raise body_too_large(max_bytes, message)
    size = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise body_too_large(max_bytes, message)
        chunks.append(chunk)
    return b"".join(chunks)


def replay_body(request: Request, body: bytes) -> Request:
    """A request that delivers ``body`` once, then whatever the client sends next.

    Later calls go to the original receive, so a client that disconnects after
    the body was read is still seen as disconnected.
    """
    delivered = False

    # An ASGI message (starlette.types.Message is this alias). The flow egress
    # boundary test keeps third-party imports of flow code to its allowlist, so
    # the alias is spelled out instead of importing starlette for one annotation.
    async def receive() -> MutableMapping[str, Any]:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await request.receive()

    return Request(request.scope, receive)


def capped_body_route_class(
    max_bytes: int, *, message: str | None = None
) -> type[APIRoute]:
    """A route class that reads the body under ``max_bytes`` before FastAPI parses it."""

    class CappedBodyRoute(APIRoute):
        def get_route_handler(
            self,
        ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            original_route_handler = super().get_route_handler()

            async def capped_body_route_handler(request: Request) -> Response:
                body = await read_body_within(request, max_bytes, message=message)
                return await original_route_handler(replay_body(request, body))

            return capped_body_route_handler

    return CappedBodyRoute
