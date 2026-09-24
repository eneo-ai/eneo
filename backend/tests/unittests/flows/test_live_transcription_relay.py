"""The live preview relay against a local server speaking vLLM's realtime schema."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
from typing import cast
from uuid import uuid4

import pytest
from fastapi import WebSocket, WebSocketDisconnect

from eneo.flows.runtime.live_transcription import relay
from eneo.flows.runtime.live_transcription.relay import (
    LiveSessionStats,
    relay_live_session,
)
from eneo.flows.runtime.live_transcription.tickets import LiveTranscriptionGrant
from eneo.flows.runtime.live_transcription.upstream import realtime_websocket_url
from tests.unittests.flows.live_transcription_test_support import (
    FakeRealtimeServer,
    fake_realtime_server,
)

MODEL = "realtime-asr"
TENTH_OF_A_SECOND = b"\x01\x00" * 1600


class FakeBrowser:
    """The browser end of the relay: queued messages in, JSON events out."""

    def __init__(self, *messages: dict[str, object], gone: bool = False) -> None:
        self._inbox: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        for message in messages:
            self._inbox.put_nowait(message)
        self.events: list[dict[str, object]] = []
        self._gone = gone

    async def receive(self) -> dict[str, object]:
        return await self._inbox.get()

    async def send_json(self, data: dict[str, object]) -> None:
        if self._gone:
            raise WebSocketDisconnect(1001)
        self.events.append(data)


def audio(frame: bytes) -> dict[str, object]:
    return {"type": "websocket.receive", "bytes": frame}


def stop() -> dict[str, object]:
    return {"type": "websocket.receive", "text": json.dumps({"type": "stop"})}


def leave() -> dict[str, object]:
    return {"type": "websocket.disconnect", "code": 1001}


async def run_relay(
    browser: FakeBrowser,
    upstream_url: str,
    *,
    max_seconds: int = 60,
    idle_timeout_seconds: float = 300,
    final_text_timeout_seconds: float = 30,
    grant: LiveTranscriptionGrant | None = None,
) -> tuple[str, LiveSessionStats]:
    stats = LiveSessionStats()
    outcome = await relay_live_session(
        cast(WebSocket, browser),
        upstream_url=upstream_url,
        api_key="live-secret",
        model_name=MODEL,
        max_seconds=max_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
        final_text_timeout_seconds=final_text_timeout_seconds,
        stats=stats,
        grant=grant,
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
    ("code", "retryable"),
    [
        ("capacity_exceeded", True),
        ("finalize_timeout", True),
        ("model_error", False),
    ],
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
    [b"", b"\x01\x00\x01", b"\x00" * (relay.MAX_FRAME_BYTES + 2)],
    ids=["empty", "odd_length", "oversized"],
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


async def test_a_silent_browser_times_out():
    browser = FakeBrowser()

    async with fake_realtime_server() as server:
        outcome, _ = await run_relay(browser, server.url, idle_timeout_seconds=0.05)

    assert outcome == "idle_timeout"
    assert browser.events[-1]["code"] == "idle_timeout"
    assert browser.events[-1]["retryable"] is False


async def test_a_text_message_other_than_stop_ends_the_session():
    browser = FakeBrowser(
        audio(TENTH_OF_A_SECOND), {"type": "websocket.receive", "text": "{}"}
    )

    async with fake_realtime_server() as server:
        outcome, _ = await run_relay(browser, server.url)
        await server.wait_closed()

    assert outcome == "invalid_message"
    assert browser.events[-1]["code"] == "invalid_message"
    assert appended(server) == [b64(TENTH_OF_A_SECOND)]


async def test_a_model_server_that_stops_reading_ends_the_session_in_bounded_time(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(relay, "UPSTREAM_SEND_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(relay, "UPSTREAM_CLOSE_TIMEOUT_SECONDS", 0.2)
    # random, so the connection's compression cannot shrink it below the buffers
    largest = os.urandom(relay.MAX_FRAME_BYTES)
    browser = FakeBrowser(*(audio(largest) for _ in range(400)))

    async with fake_realtime_server(stop_reading=True) as server:
        outcome, _ = await asyncio.wait_for(
            run_relay(browser, server.url, max_seconds=100_000), timeout=5
        )

    assert outcome == "upstream_timeout"
    assert browser.events[-1]["code"] == "upstream_timeout"
    assert browser.events[-1]["retryable"] is True


async def test_a_model_server_that_closes_at_once_is_reported_as_retryable():
    browser = FakeBrowser()

    async with fake_realtime_server(close_at_once=True) as server:
        outcome, _ = await run_relay(browser, server.url)

    assert outcome == "upstream_closed"
    assert browser.events[-1]["code"] == "upstream_closed"
    assert browser.events[-1]["retryable"] is True


async def test_a_browser_gone_before_ready_ends_the_session_quietly():
    browser = FakeBrowser(gone=True)

    async with fake_realtime_server() as server:
        outcome, _ = await run_relay(browser, server.url)
        await server.wait_closed()

    assert outcome == "client_closed"


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


@pytest.mark.parametrize(
    ("evidence", "recording_id", "stored"),
    [
        ({"produced_samples": 1600}, "recording_123", True),
        ({"produced_samples": 0}, "recording_123", True),
        ({"produced_samples": 1599}, "recording_123", False),
        ({}, "recording_123", False),
        ({"produced_samples": True}, "recording_123", False),
        ({"produced_samples": -1}, "recording_123", False),
        ({"produced_samples": 1600.0}, "recording_123", False),
        ({"produced_samples": "1600"}, "recording_123", False),
        ({"produced_samples": None}, "recording_123", False),
        ({"produced_samples": 1600}, None, False),
        ({"produced_samples": False}, "recording_123", False),
    ],
)
async def test_only_reconciled_sessions_are_stored(
    monkeypatch, evidence, recording_id, stored
):
    grant = LiveTranscriptionGrant(
        tenant_id=uuid4(),
        user_id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        step_id=uuid4(),
        model_id=uuid4(),
        max_seconds=60,
        recording_id=recording_id,
    )
    writes = []
    transcript_id = uuid4()

    async def persist(grant, *, text, segments, received_audio_seconds):
        writes.append((grant, text, segments, received_audio_seconds))
        return transcript_id

    monkeypatch.setattr(relay, "persist_live_transcript", persist)
    sample_count = (
        1
        if evidence.get("produced_samples") is True
        else 0
        if evidence.get("produced_samples") == 0
        else 1600
    )
    frames = [audio(b"\x01\x00" * sample_count)] if sample_count else []
    browser = FakeBrowser(
        *frames,
        {
            "type": "websocket.receive",
            "text": json.dumps({"type": "stop", "ignored": 42, **evidence}),
        },
    )
    async with fake_realtime_server(deltas=["Hej"]) as server:
        outcome = await relay_live_session(
            cast(WebSocket, browser),
            upstream_url=server.url,
            api_key=None,
            model_name=MODEL,
            max_seconds=60,
            idle_timeout_seconds=1,
            final_text_timeout_seconds=1,
            stats=LiveSessionStats(),
            grant=grant,
        )
    assert outcome == "completed"
    assert writes == (
        [(grant, "Hej" if sample_count else "", None, sample_count / 16000)]
        if stored
        else []
    )
    assert browser.events[-1] == {
        "type": "transcript.done",
        "text": "Hej" if sample_count else "",
        **({"transcript_id": str(transcript_id)} if stored else {}),
    }


def recording_grant() -> LiveTranscriptionGrant:
    return LiveTranscriptionGrant(
        tenant_id=uuid4(),
        user_id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        step_id=uuid4(),
        model_id=uuid4(),
        max_seconds=60,
        recording_id="recording_123",
    )


def counted_stop(samples: int) -> dict[str, object]:
    return {
        "type": "websocket.receive",
        "text": json.dumps({"type": "stop", "produced_samples": samples}),
    }


@pytest.mark.parametrize(
    "missing_span,mismatch", [(False, False), (True, False), (False, True)]
)
async def test_stored_passages_require_complete_matching_timed_deltas(
    monkeypatch, missing_span, mismatch
):
    writes = []

    async def persist(grant, **values):
        writes.append(values)
        return uuid4()

    monkeypatch.setattr(relay, "persist_live_transcript", persist)
    spans = [(0.0, 12.0), (12.0, 20.0), (20.0, 35.0), (35.0, 45.0)]
    if missing_span:
        spans[1] = None
    browser = FakeBrowser(
        *(audio(TENTH_OF_A_SECOND) for _ in spans), counted_stop(6400)
    )
    async with fake_realtime_server(
        deltas=["Hej", " världen.", " Nästa", " mening"],
        spans=spans,
        done_text="Authoritative" if mismatch else None,
    ) as server:
        outcome, _ = await run_relay(browser, server.url, grant=recording_grant())
    assert outcome == "completed"
    [stored] = writes
    assert stored["text"] == (
        "Authoritative" if mismatch else "Hej världen. Nästa mening"
    )
    assert stored["segments"] == (
        None
        if missing_span or mismatch
        else [
            {"start": 0.0, "end": 20.0, "text": "Hej världen."},
            {"start": 20.0, "end": 45.0, "text": " Nästa mening"},
        ]
    )


async def test_a_failed_write_preserves_preview_without_logging_text(
    monkeypatch, caplog
):
    async def persist(grant, **values):
        raise RuntimeError(values["text"])

    monkeypatch.setattr(relay, "persist_live_transcript", persist)
    browser = FakeBrowser(audio(TENTH_OF_A_SECOND), counted_stop(1600))
    async with fake_realtime_server(deltas=["Private words"]) as server:
        outcome, _ = await run_relay(browser, server.url, grant=recording_grant())
    assert outcome == "completed"
    assert browser.events[-1] == {"type": "transcript.done", "text": "Private words"}
    assert "Private words" not in caplog.text


@pytest.mark.parametrize(
    "ending",
    ["capacity_exceeded", "unexpected_error", "disconnect", "timeout", "early_done"],
)
async def test_unclean_sessions_never_write(monkeypatch, ending):
    writes = []

    async def persist(grant, **values):
        writes.append(values)
        return uuid4()

    monkeypatch.setattr(relay, "persist_live_transcript", persist)
    messages = [audio(TENTH_OF_A_SECOND), counted_stop(1600)]
    if ending == "disconnect":
        messages[-1] = leave()
    elif ending == "early_done":
        messages = []
    browser = FakeBrowser(*messages)
    async with fake_realtime_server(
        fail_with=ending
        if ending in {"capacity_exceeded", "unexpected_error"}
        else None,
        early_done=ending == "early_done",
        finish=ending != "timeout",
    ) as server:
        outcome, _ = await run_relay(
            browser,
            server.url,
            grant=recording_grant(),
            final_text_timeout_seconds=0.05,
        )
    assert outcome == {
        "disconnect": "client_closed",
        "timeout": "upstream_timeout",
        "early_done": "completed",
    }.get(ending, ending)
    assert writes == []
    assert all("transcript_id" not in event for event in browser.events)


@pytest.mark.parametrize("bounded", [False, True])
async def test_passages_split_at_thirty_seconds_and_drop_on_buffer_limit(
    monkeypatch, bounded
):
    writes = []

    async def persist(grant, **values):
        writes.append(values)
        return uuid4()

    monkeypatch.setattr(relay, "persist_live_transcript", persist)
    if bounded:
        monkeypatch.setattr(relay, "UPSTREAM_MAX_MESSAGE_BYTES", 256)
    browser = FakeBrowser(
        *(audio(TENTH_OF_A_SECOND) for _ in range(4)), counted_stop(6400)
    )
    async with fake_realtime_server(
        deltas=["x" * 30] * 4, spans=[(0, 10), (10, 20), (20, 30), (30, 40)]
    ) as server:
        outcome, _ = await run_relay(browser, server.url, grant=recording_grant())
    assert outcome == "completed"
    [stored] = writes
    assert stored["segments"] == (
        None
        if bounded
        else [
            {"start": 0.0, "end": 30.0, "text": "x" * 90},
            {"start": 30.0, "end": 40.0, "text": "x" * 30},
        ]
    )


async def test_early_done_queued_behind_slow_browser_never_stores_partial_audio(
    monkeypatch,
):
    forwarding = asyncio.Event()
    release_browser = asyncio.Event()
    final_written = asyncio.Event()
    writes = []
    original_send = relay._send_upstream

    async def send(upstream, message, **kwargs):
        await original_send(upstream, message, **kwargs)
        if json.loads(message).get("final"):
            final_written.set()

    class SlowBrowser(FakeBrowser):
        async def send_json(self, data):
            if data["type"] == "transcript.delta":
                forwarding.set()
                await release_browser.wait()
            await super().send_json(data)

    async def persist(grant, **values):
        writes.append(values)
        return uuid4()

    monkeypatch.setattr(relay, "_send_upstream", send)
    monkeypatch.setattr(relay, "persist_live_transcript", persist)
    browser = SlowBrowser(audio(TENTH_OF_A_SECOND))
    async with fake_realtime_server(
        early_done_after_audio=True, finish=False
    ) as server:
        task = asyncio.create_task(
            run_relay(browser, server.url, grant=recording_grant())
        )
        try:
            await asyncio.wait_for(forwarding.wait(), 1)
            await asyncio.wait_for(server.done_sent.wait(), 1)
            browser._inbox.put_nowait(audio(TENTH_OF_A_SECOND))
            browser._inbox.put_nowait(counted_stop(3200))
            await asyncio.wait_for(final_written.wait(), 1)
            release_browser.set()
            outcome, stats = await asyncio.wait_for(task, 1)
        finally:
            release_browser.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert outcome == "completed"
    assert stats.received_samples == 3200
    assert writes == []
    assert "transcript_id" not in browser.events[-1]


async def test_fast_done_does_not_wait_for_the_final_send_callers_resumption(
    monkeypatch,
):
    original_send = relay._send_upstream
    caller_resumes = asyncio.Event()
    writes = []

    async def send(upstream, message, **kwargs):
        await original_send(upstream, message, **kwargs)
        if json.loads(message).get("final"):
            await caller_resumes.wait()

    async def persist(grant, **values):
        writes.append(values)
        return uuid4()

    monkeypatch.setattr(relay, "_send_upstream", send)
    monkeypatch.setattr(relay, "persist_live_transcript", persist)
    browser = FakeBrowser(audio(TENTH_OF_A_SECOND), counted_stop(1600))
    async with fake_realtime_server() as server:
        outcome, _ = await asyncio.wait_for(
            run_relay(browser, server.url, grant=recording_grant()), 1
        )
    assert outcome == "completed"
    assert len(writes) == 1
    assert "transcript_id" in browser.events[-1]


@pytest.mark.parametrize("reported,seconds", [(False, None), (True, 1599 / 16000)])
async def test_missing_or_mismatched_upstream_sample_evidence_does_not_store(
    monkeypatch, reported, seconds
):
    writes = []

    async def persist(grant, **values):
        writes.append(values)
        return uuid4()

    monkeypatch.setattr(relay, "persist_live_transcript", persist)
    browser = FakeBrowser(audio(TENTH_OF_A_SECOND), counted_stop(1600))
    async with fake_realtime_server(
        report_audio_seconds=reported, done_audio_seconds=seconds
    ) as server:
        outcome, _ = await run_relay(browser, server.url, grant=recording_grant())
    assert outcome == "completed"
    assert writes == []
    assert "transcript_id" not in browser.events[-1]


async def test_disconnect_after_stop_before_done_never_stores(monkeypatch):
    writes = []
    release = asyncio.Event()

    async def persist(grant, **values):
        writes.append(values)
        return uuid4()

    monkeypatch.setattr(relay, "persist_live_transcript", persist)
    browser = FakeBrowser(audio(TENTH_OF_A_SECOND), counted_stop(1600), leave())
    async with fake_realtime_server(final_release=release) as server:
        task = asyncio.create_task(
            run_relay(
                browser,
                server.url,
                grant=recording_grant(),
                final_text_timeout_seconds=0.05,
            )
        )
        try:
            await asyncio.wait_for(server.final_received.wait(), 1)
            outcome, _ = await asyncio.wait_for(task, 1)
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert outcome == "client_closed"
    assert writes == []


async def test_suspended_write_times_out_without_breaking_preview(monkeypatch):
    cancelled = asyncio.Event()

    async def persist(grant, **values):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(relay, "persist_live_transcript", persist)
    monkeypatch.setattr(
        relay, "LIVE_TRANSCRIPT_WRITE_TIMEOUT_SECONDS", 0.02, raising=False
    )
    browser = FakeBrowser(audio(TENTH_OF_A_SECOND), counted_stop(1600))
    async with fake_realtime_server(deltas=["Hej"]) as server:
        outcome, _ = await asyncio.wait_for(
            run_relay(browser, server.url, grant=recording_grant()), 0.5
        )
    assert outcome == "completed"
    assert cancelled.is_set()
    assert browser.events[-1] == {"type": "transcript.done", "text": "Hej"}
