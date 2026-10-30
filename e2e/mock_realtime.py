"""Deterministic vLLM realtime peer for browser tests; WebSocket framing is library-owned."""

import asyncio
import base64
import json

from websockets.asyncio.server import ServerConnection, serve

TRANSCRIPT = "E2E live transcription: mikrofonen fungerar."


async def transcribe(connection: ServerConnection) -> None:
    await connection.send(
        json.dumps({"type": "session.created", "id": "e2e-live", "created": 0})
    )
    samples = 0
    sent = False
    async for raw in connection:
        message = json.loads(raw)
        if message["type"] == "input_audio_buffer.append":
            samples += len(base64.b64decode(message["audio"], validate=True)) // 2
            if not sent:
                await connection.send(
                    json.dumps({"type": "transcription.delta", "delta": TRANSCRIPT})
                )
                sent = True
        elif message["type"] == "input_audio_buffer.commit" and message["final"]:
            await connection.send(
                json.dumps(
                    {
                        "type": "transcription.done",
                        "text": TRANSCRIPT if sent else "",
                        "audio_seconds": samples / 16_000,
                    }
                )
            )


async def main() -> None:
    async with serve(transcribe, "0.0.0.0", 8201, max_size=256 * 1024):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
