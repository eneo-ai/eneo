"""vLLM's realtime transcription dialect, the one vadsa and vLLM serve.

Pinned to vLLM's published schemas (vllm/entrypoints/speech_to_text/realtime/
protocol.py): the client sends ``session.update {model}``, an initial
``input_audio_buffer.commit``, ``input_audio_buffer.append {audio}`` with
base64 PCM16 at 16 kHz, and a final commit; the server answers
``transcription.delta {delta}``, ``transcription.done {text}`` and
``error {error, code}``.
"""

from __future__ import annotations

import base64
import json
import math
from dataclasses import dataclass
from typing import Final, Literal, cast

from eneo.model_providers.domain.endpoints import normalize_endpoint_base

REALTIME_PATH: Final = "/v1/realtime"
SAMPLE_RATE: Final = 16_000


def realtime_websocket_url(api_base: str) -> str:
    """Turn a provider endpoint (with or without ``/v1``) into its realtime URL."""
    base = normalize_endpoint_base(api_base)
    for http_scheme, ws_scheme in (("https://", "wss://"), ("http://", "ws://")):
        if base.startswith(http_scheme):
            return ws_scheme + base.removeprefix(http_scheme) + REALTIME_PATH
    raise ValueError("The provider endpoint must be an http or https URL.")


def session_update(model: str) -> str:
    return json.dumps({"type": "session.update", "model": model})


def commit(*, final: bool) -> str:
    return json.dumps({"type": "input_audio_buffer.commit", "final": final})


def append(pcm16: bytes) -> str:
    audio = base64.b64encode(pcm16).decode("ascii")
    return json.dumps({"type": "input_audio_buffer.append", "audio": audio})


@dataclass(frozen=True)
class UpstreamEvent:
    kind: Literal["delta", "done", "error", "other"]
    text: str = ""
    code: str | None = None
    audio_start: float | None = None
    audio_end: float | None = None


def parse_event(raw: str | bytes) -> UpstreamEvent:
    try:
        data = json.loads(raw)
    except ValueError:
        return UpstreamEvent("error", text="Unreadable event from the model server.")
    if not isinstance(data, dict):
        return UpstreamEvent("other")
    event = cast(dict[str, object], data)
    match event.get("type"):
        case "transcription.delta":
            return UpstreamEvent(
                "delta",
                text=str(event.get("delta") or ""),
                audio_start=_seconds(event.get("audio_start")),
                audio_end=_seconds(event.get("audio_end")),
            )
        case "transcription.done":
            return UpstreamEvent("done", text=str(event.get("text") or ""))
        case "error":
            code = event.get("code")
            return UpstreamEvent(
                "error",
                text=str(event.get("error") or "The model server reported an error."),
                code=code if isinstance(code, str) else None,
            )
        case _:
            return UpstreamEvent("other")


def _seconds(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        seconds = float(value)
    except (OverflowError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None
