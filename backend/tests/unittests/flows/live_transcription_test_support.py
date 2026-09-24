"""A local stand-in for a vLLM realtime transcription endpoint.

It speaks the schema vLLM publishes in
vllm/entrypoints/speech_to_text/realtime/protocol.py: ``session.created`` on
connect, one ``transcription.delta`` per appended chunk, ``transcription.done``
after the final commit, and ``error {error, code}`` when told to fail.
"""

from __future__ import annotations

import asyncio
import base64
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
    done_sent: asyncio.Event = field(default_factory=asyncio.Event)
    final_received: asyncio.Event = field(default_factory=asyncio.Event)

    async def wait_closed(self) -> None:
        await asyncio.wait_for(self.closed.wait(), timeout=5)


@asynccontextmanager
async def fake_realtime_server(
    *,
    deltas: Sequence[str] = ("Hej", " världen"),
    fail_with: str | None = None,
    hang_up: bool = False,
    close_at_once: bool = False,
    stop_reading: bool = False,
    spans: Sequence[tuple[float, float] | None] = (),
    done_text: str | None = None,
    early_done: bool = False,
    finish: bool = True,
    report_audio_seconds: bool = True,
    done_audio_seconds: float | None = None,
    early_done_after_audio: bool = False,
    final_release: asyncio.Event | None = None,
) -> AsyncIterator[FakeRealtimeServer]:
    """`close_at_once` closes right after the handshake; `stop_reading` never reads,
    so a client's sends back up once the socket buffers are full."""
    state = FakeRealtimeServer()

    async def handler(connection: ServerConnection) -> None:
        state.authorization = connection.request.headers.get("Authorization")
        pending = list(deltas)
        sent: list[str] = []
        received_samples = 0
        try:
            if close_at_once:
                return
            if stop_reading:
                await connection.wait_closed()
                return
            await connection.send(
                json.dumps({"type": "session.created", "id": "sess-test", "created": 0})
            )
            if early_done:
                await connection.send(
                    json.dumps({"type": "transcription.done", "text": "Early"})
                )
            async for raw in connection:
                message = json.loads(raw)
                state.received.append(message)
                if message["type"] == "input_audio_buffer.append":
                    received_samples += len(base64.b64decode(message["audio"])) // 2
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
                        span = spans[len(sent) - 1] if len(spans) >= len(sent) else None
                        await connection.send(
                            json.dumps(
                                {
                                    "type": "transcription.delta",
                                    "delta": sent[-1],
                                    **(
                                        {"audio_start": span[0], "audio_end": span[1]}
                                        if span
                                        else {}
                                    ),
                                }
                            )
                        )
                    if early_done_after_audio and not state.done_sent.is_set():
                        await connection.send(
                            json.dumps(
                                {
                                    "type": "transcription.done",
                                    "text": "".join(sent),
                                    "audio_seconds": received_samples / 16000,
                                }
                            )
                        )
                        state.done_sent.set()
                elif (
                    message["type"] == "input_audio_buffer.commit" and message["final"]
                ):
                    state.final_received.set()
                    if not finish:
                        continue
                    if final_release is not None:
                        await final_release.wait()
                    await connection.send(
                        json.dumps(
                            {
                                "type": "transcription.done",
                                "text": "".join(sent)
                                if done_text is None
                                else done_text,
                                "usage": None,
                                **(
                                    {
                                        "audio_seconds": received_samples / 16000
                                        if done_audio_seconds is None
                                        else done_audio_seconds
                                    }
                                    if report_audio_seconds
                                    else {}
                                ),
                            }
                        )
                    )
                    state.done_sent.set()
        finally:
            state.closed.set()

    async with serve(handler, "127.0.0.1", 0, close_timeout=0.5) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        state.url = f"ws://127.0.0.1:{port}/v1/realtime"
        yield state
