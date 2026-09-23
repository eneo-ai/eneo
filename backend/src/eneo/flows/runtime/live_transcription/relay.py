"""One live session: browser PCM in, committed transcript text out.

The preview never becomes the run's transcript; the recording is uploaded and
transcribed by the normal batch path. So the relay keeps no audio and no text,
only the running sample count that enforces the session's duration ceiling.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Final, cast

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

# Wire and health bounds; the session's own limits (duration, idle, final text)
# are deployment settings and arrive as arguments.
MAX_FRAME_BYTES: Final = 64 * 1024
MAX_CONTROL_BYTES: Final = 1024
UPSTREAM_OPEN_TIMEOUT_SECONDS: Final = 10
# A model server that stops reading must not hold the session past its deadlines;
# a slow one still reads, since it buffers audio it has not decoded yet.
UPSTREAM_SEND_TIMEOUT_SECONDS: Final = 10
UPSTREAM_CLOSE_TIMEOUT_SECONDS: Final = 2
# transcription.done repeats the whole session's text; five hours of speech is
# about 0.5 MB.
UPSTREAM_MAX_MESSAGE_BYTES: Final = 8 * 2**20
# Transient refusals: the server is full, behind, or still loading its model.
_RETRYABLE_UPSTREAM_CODES: Final = frozenset(
    {"capacity_exceeded", "falling_behind", "model_loading"}
)


class LiveSessionEnded(Exception):
    """Ends the session with a typed error the client can act on."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def event(self) -> dict[str, object]:
        return {
            "type": "error",
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


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
    idle_timeout_seconds: float,
    final_text_timeout_seconds: float,
    stats: LiveSessionStats,
) -> str:
    """Run the session to its end and return the outcome for the log line."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        upstream = await connect(
            upstream_url,
            additional_headers=headers,
            open_timeout=UPSTREAM_OPEN_TIMEOUT_SECONDS,
            close_timeout=UPSTREAM_CLOSE_TIMEOUT_SECONDS,
            max_size=UPSTREAM_MAX_MESSAGE_BYTES,
        )
    except (OSError, TimeoutError, InvalidHandshake):
        await send_error(
            client,
            LiveSessionEnded(
                "upstream_unavailable",
                "The transcription server could not be reached.",
                retryable=True,
            ),
        )
        return "upstream_unavailable"

    try:
        try:
            await _send_upstream(upstream, session_update(model_name))
            await _send_upstream(upstream, commit(final=False))
            await _send_client(
                client,
                {
                    "type": "ready",
                    "sample_rate": SAMPLE_RATE,
                    "max_seconds": max_seconds,
                },
            )
            return await _run(
                client,
                upstream,
                max_samples=max_seconds * SAMPLE_RATE,
                idle_timeout_seconds=idle_timeout_seconds,
                final_text_timeout_seconds=final_text_timeout_seconds,
                stats=stats,
            )
        except _ClientGone:
            return "client_closed"
        except LiveSessionEnded as ended:
            await send_error(client, ended)
            return ended.code
    finally:
        await _close_upstream(upstream)


async def _close_upstream(upstream: ClientConnection) -> None:
    # close() first flushes its close frame, which a server that stopped reading
    # never takes, and only then applies its own close timeout.
    try:
        await asyncio.wait_for(upstream.close(), UPSTREAM_CLOSE_TIMEOUT_SECONDS)
    except TimeoutError:
        upstream.transport.abort()


async def send_error(client: WebSocket, ended: LiveSessionEnded) -> None:
    """Tell the client why the session ends; it may already be gone."""
    try:
        await client.send_json(ended.event())
    except (WebSocketDisconnect, RuntimeError):
        pass


async def _run(
    client: WebSocket,
    upstream: ClientConnection,
    *,
    max_samples: int,
    idle_timeout_seconds: float,
    final_text_timeout_seconds: float,
    stats: LiveSessionStats,
) -> str:
    to_upstream = asyncio.create_task(
        _pump_client(
            client,
            upstream,
            max_samples=max_samples,
            idle_timeout_seconds=idle_timeout_seconds,
            stats=stats,
        )
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
            return await asyncio.wait_for(to_client, final_text_timeout_seconds)
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
    idle_timeout_seconds: float,
    stats: LiveSessionStats,
) -> None:
    while True:
        try:
            message = await asyncio.wait_for(client.receive(), idle_timeout_seconds)
        except TimeoutError as exc:
            raise LiveSessionEnded("idle_timeout", "No audio arrived in time.") from exc
        if message["type"] == "websocket.disconnect":
            raise _ClientGone
        frame = message.get("bytes")
        if frame is not None:
            if not frame or len(frame) > MAX_FRAME_BYTES or len(frame) % 2:
                raise LiveSessionEnded(
                    "invalid_audio_frame",
                    "Audio frames must be 16-bit PCM of 2 bytes to 64 KiB.",
                )
            stats.received_samples += len(frame) // 2
            if stats.received_samples > max_samples:
                raise LiveSessionEnded(
                    "duration_exceeded",
                    "The recording is longer than live transcription allows.",
                )
            await _send_upstream(upstream, append(frame))
            continue
        # Anything but audio and the stop message ends the session, so only audio
        # keeps a session, and its slot on the model server, open.
        if not _is_stop(message.get("text")):
            raise LiveSessionEnded(
                "invalid_message",
                'Send audio as binary frames and end with {"type": "stop"}.',
            )
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
    if text is None or len(text) > MAX_CONTROL_BYTES:
        return False
    try:
        event = json.loads(text)
    except ValueError:
        return False
    if not isinstance(event, dict):
        return False
    return cast(dict[str, object], event).get("type") == "stop"


async def _send_upstream(upstream: ClientConnection, message: str) -> None:
    try:
        await asyncio.wait_for(upstream.send(message), UPSTREAM_SEND_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise LiveSessionEnded(
            "upstream_timeout",
            "The transcription server stopped reading the audio.",
            retryable=True,
        ) from exc
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
