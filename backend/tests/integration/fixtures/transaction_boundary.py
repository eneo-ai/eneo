import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import Message, Receive, Scope, Send

from eneo.database.database import get_session_with_transaction


async def request_at_transaction_boundary(
    app: FastAPI,
    *,
    method: str,
    path: str,
    payload: dict[str, object],
    headers: dict[str, str],
) -> Response:
    """Run a real route while holding transaction teardown at the ASGI edge."""
    response_started = asyncio.Event()
    teardown_started = asyncio.Event()
    release_teardown = asyncio.Event()

    async def blocked_transaction_teardown() -> AsyncIterator[AsyncSession]:
        async for session in get_session_with_transaction():
            try:
                yield session
            finally:
                teardown_started.set()
                await release_teardown.wait()

    async def record_response_start(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        async def recording_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_started.set()
            await send(message)

        await app(scope, receive, recording_send)

    assert get_session_with_transaction not in app.dependency_overrides
    app.dependency_overrides[get_session_with_transaction] = (
        blocked_transaction_teardown
    )
    request_task: asyncio.Task[Response] | None = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=record_response_start),
            base_url="http://test.local",
        ) as boundary_client:
            request_task = asyncio.create_task(
                boundary_client.request(
                    method,
                    path,
                    json=payload,
                    headers=headers,
                )
            )
            try:
                await asyncio.wait_for(teardown_started.wait(), timeout=10)
                assert not response_started.is_set()
            finally:
                release_teardown.set()

            return await asyncio.wait_for(request_task, timeout=10)
    finally:
        release_teardown.set()
        if request_task is not None and not request_task.done():
            with contextlib.suppress(Exception):
                await request_task
        app.dependency_overrides.pop(get_session_with_transaction, None)
