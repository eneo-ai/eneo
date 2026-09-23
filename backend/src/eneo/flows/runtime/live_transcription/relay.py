"""One live session: browser PCM in, committed transcript text out.

The preview never becomes the run's transcript; the recording is uploaded and
transcribed by the normal batch path. So the relay keeps no audio and no text,
only the running sample count that enforces the session's duration ceiling.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Final

from fastapi import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

from eneo.flows.runtime.live_transcription.upstream import (
    SAMPLE_RATE,
    append,
    commit,
    parse_event,
    session_update,
)

MAX_FRAME_BYTES: Final = 64 * 1024
IDLE_TIMEOUT_SECONDS: Final = 300
UPSTREAM_OPEN_TIMEOUT_SECONDS: Final = 10
FINAL_TRANSCRIPT_TIMEOUT_SECONDS: Final = 30
_RETRYABLE_UPSTREAM_CODES: Final = frozenset({"capacity_exceeded", "falling_behind"})


class LiveSessionEnded(Exception):
    """Ends the session with a typed error the client can act on."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class _ClientGone(Exception):
    pass


@dataclass
class LiveSessionStats:
    received_samples: int = 0

    @property
    def audio_seconds(self) -> float:
        return self.received_samples / SAMPLE_RATE


async def relay_live_session(
    client: WebSocket,
    *,
    upstream_url: str,
    api_key: str | None,
    model_name: str,
    max_seconds: int,
    stats: LiveSessionStats,
) -> str:
    """Run the session to its end and return the outcome for the log line."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        upstream = await connect(
            upstream_url,
            additional_headers=headers,
            open_timeout=UPSTREAM_OPEN_TIMEOUT_SECONDS,
            max_size=2**20,
        )
    except (OSError, TimeoutError, InvalidHandshake):
        await _send_error(
            client,
            LiveSessionEnded(
                "upstream_unavailable",
                "The transcription server could not be reached.",
                retryable=True,
            ),
        )
        return "upstream_unavailable"

    async with upstream:
        try:
            await upstream.send(session_update(model_name))
            await upstream.send(commit(final=False))
            await client.send_json(
                {
                    "type": "ready",
                    "sample_rate": SAMPLE_RATE,
                    "max_seconds": max_seconds,
                }
            )
            return await _run(
                client, upstream, max_samples=max_seconds * SAMPLE_RATE, stats=stats
            )
        except _ClientGone:
            return "client_closed"
        except LiveSessionEnded as ended:
            await _send_error(client, ended)
            return ended.code


async def _run(
    client: WebSocket,
    upstream: ClientConnection,
    *,
    max_samples: int,
    stats: LiveSessionStats,
) -> str:
    to_upstream = asyncio.create_task(
        _pump_client(client, upstream, max_samples=max_samples, stats=stats)
    )
    to_client = asyncio.create_task(_pump_upstream(client, upstream))
    try:
        done, _ = await asyncio.wait(
            {to_upstream, to_client}, return_when=asyncio.FIRST_COMPLETED
        )
        if to_client in done:
            return to_client.result()
        to_upstream.result()  # the client asked to stop; wait for the final text
        try:
            return await asyncio.wait_for(to_client, FINAL_TRANSCRIPT_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise LiveSessionEnded(
                "upstream_timeout",
                "The transcription server did not finish the session in time.",
                retryable=True,
            ) from exc
    finally:
        for task in (to_upstream, to_client):
            task.cancel()
        await asyncio.gather(to_upstream, to_client, return_exceptions=True)


async def _pump_client(
    client: WebSocket,
    upstream: ClientConnection,
    *,
    max_samples: int,
    stats: LiveSessionStats,
) -> None:
    while True:
        try:
            message = await asyncio.wait_for(client.receive(), IDLE_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise LiveSessionEnded(
                "idle_timeout", "No audio arrived for five minutes."
            ) from exc
        if message["type"] == "websocket.disconnect":
            raise _ClientGone
        frame = message.get("bytes")
        if frame is not None:
            if len(frame) > MAX_FRAME_BYTES or len(frame) % 2:
                raise LiveSessionEnded(
                    "invalid_audio_frame",
                    "Audio frames must be 16-bit PCM of at most 64 KiB.",
                )
            stats.received_samples += len(frame) // 2
            if stats.received_samples > max_samples:
                raise LiveSessionEnded(
                    "duration_exceeded",
                    "The recording is longer than live transcription allows.",
                )
            await _send_upstream(upstream, append(frame))
        elif _is_stop(message.get("text")):
            await _send_upstream(upstream, commit(final=True))
            return


async def _pump_upstream(client: WebSocket, upstream: ClientConnection) -> str:
    try:
        async for raw in upstream:
            event = parse_event(raw)
            if event.kind == "delta" and event.text:
                await _send_client(
                    client, {"type": "transcript.delta", "text": event.text}
                )
            elif event.kind == "done":
                await _send_client(
                    client, {"type": "transcript.done", "text": event.text}
                )
                return "completed"
            elif event.kind == "error":
                raise LiveSessionEnded(
                    event.code or "upstream_error",
                    event.text,
                    retryable=event.code in _RETRYABLE_UPSTREAM_CODES,
                )
    except ConnectionClosed:
        pass
    raise LiveSessionEnded(
        "upstream_closed",
        "The transcription server closed the session.",
        retryable=True,
    )


def _is_stop(text: str | None) -> bool:
    if text is None:
        return False
    try:
        return json.loads(text).get("type") == "stop"
    except (ValueError, AttributeError):
        return False


async def _send_upstream(upstream: ClientConnection, message: str) -> None:
    try:
        await upstream.send(message)
    except ConnectionClosed as exc:
        raise LiveSessionEnded(
            "upstream_closed",
            "The transcription server closed the session.",
            retryable=True,
        ) from exc


async def _send_client(client: WebSocket, payload: dict[str, object]) -> None:
    try:
        await client.send_json(payload)
    except (WebSocketDisconnect, RuntimeError) as exc:
        raise _ClientGone from exc


async def _send_error(client: WebSocket, ended: LiveSessionEnded) -> None:
    try:
        await client.send_json(
            {
                "type": "error",
                "code": ended.code,
                "message": ended.message,
                "retryable": ended.retryable,
            }
        )
    except (WebSocketDisconnect, RuntimeError):
        pass
