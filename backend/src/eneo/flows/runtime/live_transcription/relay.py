"""One live session: browser PCM in, committed transcript text out.

Clean sessions may store their text for later binding to a recording. Audio is
never retained by the relay; sample counts reconcile the client's capture.
"""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass, field
from typing import Final, cast

from fastapi import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as websocket_connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake
from websockets.uri import parse_uri

from eneo.flows.runtime.egress.policy import (
    Deadline,
    DestinationRefused,
    DestinationUnresolvable,
    FlowDestinationPolicy,
    FlowOutboundTraffic,
    connect_to_first_answering,
    vet_destination,
)
from eneo.flows.runtime.egress.resolver import flow_name_resolver
from eneo.flows.runtime.live_transcription.repository import persist_live_transcript
from eneo.flows.runtime.live_transcription.segments import TimedPieces
from eneo.flows.runtime.live_transcription.tickets import LiveTranscriptionGrant
from eneo.flows.runtime.live_transcription.upstream import (
    SAMPLE_RATE,
    append,
    commit,
    parse_event,
    session_update,
)
from eneo.main.logging import get_logger

# Wire and health bounds; the session's own limits (duration, idle, final text)
# are deployment settings and arrive as arguments.
MAX_FRAME_BYTES: Final = 64 * 1024
MAX_CONTROL_BYTES: Final = 1024
UPSTREAM_OPEN_TIMEOUT_SECONDS: Final = 10
# A model server that stops reading must not hold the session past its deadlines;
# a slow one still reads, since it buffers audio it has not decoded yet.
UPSTREAM_SEND_TIMEOUT_SECONDS: Final = 10
UPSTREAM_CLOSE_TIMEOUT_SECONDS: Final = 2
LIVE_TRANSCRIPT_WRITE_TIMEOUT_SECONDS: Final = 5
# transcription.done repeats the whole session's text; five hours of speech is
# about 0.5 MB.
UPSTREAM_MAX_MESSAGE_BYTES: Final = 8 * 2**20
# Transient refusals: the server is full, behind, still loading its model, or
# too slow to send the final text in its grace.
_RETRYABLE_UPSTREAM_CODES: Final = frozenset(
    {"capacity_exceeded", "falling_behind", "finalize_timeout", "model_loading"}
)
# The model server is a tenant administrator's provider endpoint, often a speech
# service on the organisation's own network: private addresses are allowed, but
# never loopback, link-local or cloud metadata (decided 2026-10-12).
UPSTREAM_DESTINATION_POLICY = FlowDestinationPolicy(
    allow_private_networks=True, traffic=FlowOutboundTraffic.LIVE_TRANSCRIPTION
)
logger = get_logger(__name__)


class UpstreamConnect(websocket_connect):
    """Opens the model server's session without following a redirect, as the
    flow egress never does: a redirect would leave the vetted address. The
    redirect answer then fails the handshake like any other non-101 answer."""

    def process_redirect(self, exc: Exception) -> Exception | str:
        return exc


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


@dataclass
class _Capture:
    produced_samples: int | None = None
    final_commit_sent: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass(frozen=True)
class _Completed:
    text: str
    audio_seconds: float | None


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
    grant: LiveTranscriptionGrant | None = None,
) -> str:
    """Run the session to its end and return the outcome for the log line."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        upstream = await _connect_upstream(upstream_url, headers)
    except DestinationRefused:
        await send_error(
            client,
            LiveSessionEnded(
                "model_unavailable",
                "The transcription server's address is not allowed.",
            ),
        )
        return "model_unavailable"
    except (OSError, TimeoutError, InvalidHandshake, DestinationUnresolvable):
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
                grant=grant,
            )
        except _ClientGone:
            return "client_closed"
        except LiveSessionEnded as ended:
            await send_error(client, ended)
            return ended.code
    finally:
        await _close_upstream(upstream)


async def _connect_upstream(
    upstream_url: str, headers: dict[str, str]
) -> ClientConnection:
    """Open the session at an address the policy vetted, as the flow egress does.

    The name is resolved once and only a vetted IP literal is connected to, so a
    DNS answer that changes in between cannot reach a refused address. The URL is
    kept, so the Host header and the TLS name are the server's own. Proxy
    environment variables are ignored: a proxy would connect for us, and only
    the proxy could be vetted.
    """
    uri = parse_uri(upstream_url)
    deadline = Deadline(UPSTREAM_OPEN_TIMEOUT_SECONDS)
    addresses = await vet_destination(
        uri.host,
        uri.port,
        policy=UPSTREAM_DESTINATION_POLICY,
        deadline=deadline,
        resolver=flow_name_resolver(),
    )
    return await connect_to_first_answering(
        addresses,
        deadline=deadline,
        connect=lambda address, budget: UpstreamConnect(
            upstream_url,
            host=str(address),
            port=uri.port,
            proxy=None,
            additional_headers=headers,
            open_timeout=budget,
            close_timeout=UPSTREAM_CLOSE_TIMEOUT_SECONDS,
            max_size=UPSTREAM_MAX_MESSAGE_BYTES,
        ),
        retry_on=(OSError, TimeoutError),
        timed_out=TimeoutError,
    )


async def _close_upstream(upstream: ClientConnection) -> None:
    # close() first flushes its close frame, which a server that stopped reading
    # never takes, and only then applies its own close timeout.
    try:
        async with asyncio.timeout(UPSTREAM_CLOSE_TIMEOUT_SECONDS):
            await upstream.close()
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
    grant: LiveTranscriptionGrant | None,
) -> str:
    capture = _Capture()
    pieces = TimedPieces(UPSTREAM_MAX_MESSAGE_BYTES)
    to_upstream = asyncio.create_task(
        _pump_client(
            client,
            upstream,
            max_samples=max_samples,
            idle_timeout_seconds=idle_timeout_seconds,
            stats=stats,
            capture=capture,
        )
    )
    to_client = asyncio.create_task(_pump_upstream(client, upstream, pieces))
    stopped = asyncio.create_task(capture.final_commit_sent.wait())
    try:
        done, _ = await asyncio.wait(
            {to_upstream, to_client, stopped}, return_when=asyncio.FIRST_COMPLETED
        )
        if to_upstream in done:
            to_upstream.result()
        if to_client not in done:
            done, _ = await asyncio.wait(
                {to_upstream, to_client},
                timeout=final_text_timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if to_upstream in done:
                to_upstream.result()
            if to_client not in done:
                raise LiveSessionEnded(
                    "upstream_timeout",
                    "The transcription server did not finish the session in time.",
                    retryable=True,
                )
        completed = to_client.result()
        event: dict[str, object] = {"type": "transcript.done", "text": completed.text}
        if (
            grant is not None
            and grant.recording_id is not None
            and capture.final_commit_sent.is_set()
            and capture.produced_samples == stats.received_samples
            and completed.audio_seconds is not None
            and math.isfinite(completed.audio_seconds * SAMPLE_RATE)
            and round(completed.audio_seconds * SAMPLE_RATE) == stats.received_samples
        ):
            writing = asyncio.create_task(
                persist_live_transcript(
                    grant,
                    text=completed.text,
                    segments=pieces.passages(completed.text),
                    received_audio_seconds=stats.audio_seconds,
                )
            )
            try:
                async with asyncio.timeout(LIVE_TRANSCRIPT_WRITE_TIMEOUT_SECONDS):
                    await asyncio.wait(
                        {writing, to_upstream}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if to_upstream.done():
                        to_upstream.result()
                    event["transcript_id"] = str(writing.result())
            except _ClientGone:
                raise
            except Exception:
                # Database exceptions can contain bound parameters, including text.
                logger.warning(
                    "Could not store live transcript",
                    extra={"flow_id": str(grant.flow_id)},
                )
            finally:
                writing.cancel()
                await asyncio.gather(writing, return_exceptions=True)
        if to_upstream.done():
            to_upstream.result()
        await _send_client(client, event)
        return "completed"
    finally:
        for task in (to_upstream, to_client, stopped):
            task.cancel()
        await asyncio.gather(to_upstream, to_client, stopped, return_exceptions=True)


async def _pump_client(
    client: WebSocket,
    upstream: ClientConnection,
    *,
    max_samples: int,
    idle_timeout_seconds: float,
    stats: LiveSessionStats,
    capture: _Capture,
) -> None:
    while True:
        try:
            async with asyncio.timeout(idle_timeout_seconds):
                message = await client.receive()
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
        evidence = json.loads(message["text"]).get("produced_samples")
        if type(evidence) is int and evidence >= 0:
            capture.produced_samples = evidence
        await _send_upstream(
            upstream, commit(final=True), final_commit_sent=capture.final_commit_sent
        )
        # Audio after stop is ignored, but disconnects must still cancel storage.
        while True:
            message = await client.receive()
            if message["type"] == "websocket.disconnect":
                raise _ClientGone


async def _pump_upstream(
    client: WebSocket,
    upstream: ClientConnection,
    pieces: TimedPieces,
) -> _Completed:
    try:
        async for raw in upstream:
            event = parse_event(raw)
            if event.kind == "delta":
                pieces.append(event)
                if event.text:
                    await _send_client(
                        client, {"type": "transcript.delta", "text": event.text}
                    )
            elif event.kind == "done":
                return _Completed(event.text, event.audio_seconds)
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


async def _send_upstream(
    upstream: ClientConnection,
    message: str,
    *,
    final_commit_sent: asyncio.Event | None = None,
) -> None:
    try:
        async with asyncio.timeout(UPSTREAM_SEND_TIMEOUT_SECONDS):
            await upstream.send(message)
            if final_commit_sent is not None:
                final_commit_sent.set()
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
