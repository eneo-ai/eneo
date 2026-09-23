"""A local stand-in for a vLLM realtime transcription endpoint.

It speaks the schema vLLM publishes in
vllm/entrypoints/speech_to_text/realtime/protocol.py: ``session.created`` on
connect, one ``transcription.delta`` per appended chunk, ``transcription.done``
after the final commit, and ``error {error, code}`` when told to fail.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from websockets.asyncio.server import ServerConnection, serve


@dataclass
class FakeRealtimeServer:
    url: str = ""
    received: list[dict[str, object]] = field(default_factory=list)
    authorization: str | None = None
    closed: asyncio.Event = field(default_factory=asyncio.Event)

    async def wait_closed(self) -> None:
        await asyncio.wait_for(self.closed.wait(), timeout=5)


@asynccontextmanager
async def fake_realtime_server(
    *,
    deltas: Sequence[str] = ("Hej", " världen"),
    fail_with: str | None = None,
    hang_up: bool = False,
) -> AsyncIterator[FakeRealtimeServer]:
    state = FakeRealtimeServer()

    async def handler(connection: ServerConnection) -> None:
        state.authorization = connection.request.headers.get("Authorization")
        pending = list(deltas)
        sent: list[str] = []
        try:
            await connection.send(
                json.dumps({"type": "session.created", "id": "sess-test", "created": 0})
            )
            async for raw in connection:
                message = json.loads(raw)
                state.received.append(message)
                if message["type"] == "input_audio_buffer.append":
                    if hang_up:
                        return
                    if fail_with is not None:
                        await connection.send(
                            json.dumps(
                                {
                                    "type": "error",
                                    "error": "Server is busy.",
                                    "code": fail_with,
                                }
                            )
                        )
                    elif pending:
                        sent.append(pending.pop(0))
                        await connection.send(
                            json.dumps(
                                {"type": "transcription.delta", "delta": sent[-1]}
                            )
                        )
                elif (
                    message["type"] == "input_audio_buffer.commit" and message["final"]
                ):
                    await connection.send(
                        json.dumps(
                            {
                                "type": "transcription.done",
                                "text": "".join(sent),
                                "usage": None,
                            }
                        )
                    )
        finally:
            state.closed.set()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        state.url = f"ws://127.0.0.1:{port}/v1/realtime"
        yield state
