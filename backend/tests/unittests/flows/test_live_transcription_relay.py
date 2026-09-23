"""The live preview relay against a local server speaking vLLM's realtime schema."""

from __future__ import annotations

import asyncio
import base64
import json
import socket
from typing import cast

import pytest
from fastapi import WebSocket

from eneo.flows.runtime.live_transcription import relay
from eneo.flows.runtime.live_transcription.relay import (
    LiveSessionStats,
    relay_live_session,
)
from eneo.flows.runtime.live_transcription.upstream import realtime_websocket_url
from tests.unittests.flows.live_transcription_test_support import (
    FakeRealtimeServer,
    fake_realtime_server,
)

MODEL = "realtime-asr"
TENTH_OF_A_SECOND = b"\x01\x00" * 1600


class FakeBrowser:
    """The browser end of the relay: queued messages in, JSON events out."""

    def __init__(self, *messages: dict[str, object]) -> None:
        self._inbox: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        for message in messages:
            self._inbox.put_nowait(message)
        self.events: list[dict[str, object]] = []

    async def receive(self) -> dict[str, object]:
        return await self._inbox.get()

    async def send_json(self, data: dict[str, object]) -> None:
        self.events.append(data)


def audio(frame: bytes) -> dict[str, object]:
    return {"type": "websocket.receive", "bytes": frame}


def stop() -> dict[str, object]:
    return {"type": "websocket.receive", "text": json.dumps({"type": "stop"})}


def leave() -> dict[str, object]:
    return {"type": "websocket.disconnect", "code": 1001}


async def run_relay(
    browser: FakeBrowser, upstream_url: str, *, max_seconds: int = 60
) -> tuple[str, LiveSessionStats]:
    stats = LiveSessionStats()
    outcome = await relay_live_session(
        cast(WebSocket, browser),
        upstream_url=upstream_url,
        api_key="live-secret",
        model_name=MODEL,
        max_seconds=max_seconds,
        stats=stats,
    )
    return outcome, stats


def appended(server: FakeRealtimeServer) -> list[str]:
    return [
        str(message["audio"])
        for message in server.received
        if message["type"] == "input_audio_buffer.append"
    ]


def b64(frame: bytes) -> str:
    return base64.b64encode(frame).decode("ascii")


async def test_the_preview_streams_committed_text_and_ends_with_the_full_transcript():
    second = b"\x02\x00" * 1600
    browser = FakeBrowser(audio(TENTH_OF_A_SECOND), audio(second), stop())

    async with fake_realtime_server() as server:
        outcome, stats = await run_relay(browser, server.url, max_seconds=60)
        await server.wait_closed()

    assert outcome == "completed"
    assert browser.events == [
        {"type": "ready", "sample_rate": 16000, "max_seconds": 60},
        {"type": "transcript.delta", "text": "Hej"},
        {"type": "transcript.delta", "text": " världen"},
        {"type": "transcript.done", "text": "Hej världen"},
    ]
    assert server.authorization == "Bearer live-secret"
    assert server.received == [
        {"type": "session.update", "model": MODEL},
        {"type": "input_audio_buffer.commit", "final": False},
        {"type": "input_audio_buffer.append", "audio": b64(TENTH_OF_A_SECOND)},
        {"type": "input_audio_buffer.append", "audio": b64(second)},
        {"type": "input_audio_buffer.commit", "final": True},
    ]
    assert stats.audio_seconds == pytest.approx(0.2)


@pytest.mark.parametrize(
    ("code", "retryable"), [("capacity_exceeded", True), ("model_error", False)]
)
async def test_a_model_server_error_reaches_the_browser_with_its_retry_hint(
    code: str, retryable: bool
):
    browser = FakeBrowser(audio(TENTH_OF_A_SECOND))

    async with fake_realtime_server(fail_with=code) as server:
        outcome, _ = await run_relay(browser, server.url)

    assert outcome == code
    assert browser.events[-1] == {
        "type": "error",
        "code": code,
        "message": "Server is busy.",
        "retryable": retryable,
    }


async def test_an_unreachable_model_server_is_reported_as_retryable():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    browser = FakeBrowser()

    outcome, _ = await run_relay(browser, f"ws://127.0.0.1:{port}/v1/realtime")

    assert outcome == "upstream_unavailable"
    assert browser.events == [
        {
            "type": "error",
            "code": "upstream_unavailable",
            "message": "The transcription server could not be reached.",
            "retryable": True,
        }
    ]


async def test_a_model_server_that_hangs_up_mid_session_is_retryable():
    browser = FakeBrowser(audio(TENTH_OF_A_SECOND))

    async with fake_realtime_server(hang_up=True) as server:
        outcome, _ = await run_relay(browser, server.url)

    assert outcome == "upstream_closed"
    assert browser.events[-1]["code"] == "upstream_closed"
    assert browser.events[-1]["retryable"] is True


async def test_audio_past_the_duration_limit_is_not_forwarded():
    one_second = b"\x01\x00" * 16000
    browser = FakeBrowser(audio(one_second), audio(b"\x01\x00"))

    async with fake_realtime_server() as server:
        outcome, _ = await run_relay(browser, server.url, max_seconds=1)
        await server.wait_closed()

    assert outcome == "duration_exceeded"
    assert appended(server) == [b64(one_second)]
    assert browser.events[-1]["code"] == "duration_exceeded"
    assert browser.events[-1]["retryable"] is False


@pytest.mark.parametrize(
    "frame",
    [b"\x01\x00\x01", b"\x00" * (relay.MAX_FRAME_BYTES + 2)],
    ids=["odd_length", "oversized"],
)
async def test_a_malformed_audio_frame_ends_the_session_unforwarded(frame: bytes):
    browser = FakeBrowser(audio(frame))

    async with fake_realtime_server() as server:
        outcome, _ = await run_relay(browser, server.url)
        await server.wait_closed()

    assert outcome == "invalid_audio_frame"
    assert appended(server) == []
    assert browser.events[-1]["code"] == "invalid_audio_frame"


async def test_a_browser_that_leaves_closes_the_model_session():
    browser = FakeBrowser(audio(TENTH_OF_A_SECOND), leave())

    async with fake_realtime_server() as server:
        outcome, _ = await run_relay(browser, server.url)
        await server.wait_closed()

    assert outcome == "client_closed"
    assert not [event for event in browser.events if event["type"] == "error"]


async def test_a_silent_browser_times_out(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(relay, "IDLE_TIMEOUT_SECONDS", 0.05)
    browser = FakeBrowser()

    async with fake_realtime_server() as server:
        outcome, _ = await run_relay(browser, server.url)

    assert outcome == "idle_timeout"
    assert browser.events[-1]["code"] == "idle_timeout"
    assert browser.events[-1]["retryable"] is False


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("http://vadsa:8000", "ws://vadsa:8000/v1/realtime"),
        ("https://asr.example.se/v1/", "wss://asr.example.se/v1/realtime"),
    ],
)
def test_the_realtime_url_follows_the_provider_endpoint(endpoint: str, expected: str):
    assert realtime_websocket_url(endpoint) == expected


def test_a_provider_endpoint_that_is_not_http_is_refused():
    with pytest.raises(ValueError):
        realtime_websocket_url("ftp://asr.example.se")
