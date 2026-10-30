#!/usr/bin/env python3
"""Deterministic OpenAI-compatible mock model server for E2E tests.

The seeded test models point their provider `endpoint` here, so the backend's
litellm calls land on this server instead of a real provider. Every chat
completion returns the same fixed text, and every embedding is a fixed-size
vector derived from its input text alone — fast, free, and fully
deterministic. Streaming and non-streaming chat are both supported.

Stdlib only (no deps) so it runs on the bare image. Listens on :8200.
"""

import hashlib
import json
import os
import random
import threading
import time
from collections import Counter
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

from workflow_model import response as workflow_response

REPLY = os.environ.get("MOCK_REPLY", "E2E mock completion: pong")
ERROR_MARKER = os.environ.get("MOCK_ERROR_MARKER", "E2E_FORCE_MODEL_ERROR")
PORT = int(os.environ.get("MOCK_PORT", "8200"))
# Vector size for a request without `dimensions`; the seeded embedding model
# sends none (e2e/seed.py).
EMBEDDING_DIMENSIONS = int(os.environ.get("MOCK_EMBEDDING_DIMENSIONS", "32"))
# Scale-test knobs (e2e/scale); the defaults keep the E2E behaviour.
LATENCY_MS = int(os.environ.get("MOCK_LATENCY_MS", "0"))
LATENCY_JITTER_MS = int(os.environ.get("MOCK_LATENCY_JITTER_MS", "0"))
TRANSCRIPTION_LATENCY_MS = int(os.environ.get("MOCK_TRANSCRIPTION_LATENCY_MS", "0"))
TRANSCRIPT_WORDS = int(os.environ.get("MOCK_TRANSCRIPT_WORDS", "200"))
STATS: Counter = Counter()
STATS_LOCK = threading.Lock()
TIMING_JOBS: dict[str, dict] = {}
TIMING_JOBS_LOCK = threading.Lock()


def _timed_transcript(content_type: str, body: bytes) -> dict:
    """Echo the model's words with deterministic timings for the native service API."""
    form = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\n\r\n".encode() + body
    )
    fields = {
        part.get_param("name", header="content-disposition"): part.get_payload(
            decode=True
        ).decode()
        for part in form.iter_parts()
        if not part.get_filename()
    }
    if fields["task"] != "timestamp":
        raise ValueError("The E2E timing service supports timestamp jobs only")
    segments = json.loads(fields["segments"])
    for segment in segments:
        words = segment["text"].split()
        interval = (segment["end"] - segment["start"]) / len(words)
        segment["words"] = [
            {
                "word": word,
                "start": segment["start"] + index * interval,
                "end": segment["start"] + (index + 1) * interval,
            }
            for index, word in enumerate(words)
        ]
        segment["speaker"] = None
    return {
        "text": "\n".join(segment["text"] for segment in segments),
        "segments": segments,
        "model": fields["model"],
        "language": fields["language"],
        "duration_seconds": segments[-1]["end"],
        "alignment": "forced",
    }


def _count(path: str) -> None:
    with STATS_LOCK:
        STATS[path.split("?", 1)[0]] += 1


def _delay() -> None:
    # Runs in the handler's own thread, so other requests are not held up.
    if LATENCY_MS or LATENCY_JITTER_MS:
        time.sleep((LATENCY_MS + random.uniform(0, LATENCY_JITTER_MS)) / 1000)


def _chunk(delta: dict, finish_reason=None) -> bytes:
    payload = {
        "id": "e2e-mock",
        "object": "chat.completion.chunk",
        "model": "e2e-mock",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


def _request_text(payload: dict) -> str:
    parts: list[str] = []
    for message in payload.get("messages") or []:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if isinstance(text, str):
                        parts.append(text)
    return "\n".join(parts)


def _embedding(text: str, dimensions: int) -> list[float]:
    """The same text always gets the same vector; no component is ever zero,
    so the cosine distances the backend ranks by are always defined."""
    digest = hashlib.shake_256(text.encode()).digest(dimensions)
    return [(byte - 127.5) / 127.5 for byte in digest]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output clean
        pass

    def do_GET(self):
        if self.path == "/v1/health/ready":
            self._json(
                200, {"queue_accepting_jobs": True, "supported_tasks": ["timestamp"]}
            )
            return
        if self.path.startswith("/v1/jobs/"):
            job_id = self.path.split("/")[3]
            with TIMING_JOBS_LOCK:
                result = (
                    TIMING_JOBS.pop(job_id, None)
                    if self.path.endswith("/result")
                    else TIMING_JOBS.get(job_id)
                )
            if result is None:
                self._json(404, {"detail": "Unknown timing job"})
            elif self.path.endswith("/result"):
                self._json(200, result)
            else:
                self._json(
                    200,
                    {
                        "job_id": job_id,
                        "status": "completed",
                        "stage": "completed",
                        "queue_position": None,
                    },
                )
            return
        if self.path.startswith("/stats"):
            with STATS_LOCK:
                counts = dict(STATS)
                if "reset" in self.path:
                    STATS.clear()
            self._json(200, counts)
            return
        _count(self.path)
        # Health + a stub /models so any litellm preflight is happy.
        self._json(
            200, {"status": "ok"} if self.path.endswith("/health") else {"data": []}
        )

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        _count(self.path)
        _delay()
        if self.path == "/v1/jobs":
            result = _timed_transcript(self.headers["Content-Type"], body)
            job_id = uuid4().hex
            with TIMING_JOBS_LOCK:
                TIMING_JOBS[job_id] = result
            self._json(202, {"job_id": job_id, "status": "queued"})
            return
        if self.path.endswith("/audio/transcriptions"):
            time.sleep(TRANSCRIPTION_LATENCY_MS / 1000)
            words = " ".join(f"word{i}" for i in range(TRANSCRIPT_WORDS))
            self._json(200, {"text": words})
            return
        try:
            req = json.loads(body or b"{}")
        except json.JSONDecodeError:
            req = {}

        if self.path.endswith("/embeddings"):
            self._embeddings(req)
            return

        if not self.path.endswith("/chat/completions"):
            self._json(404, {"error": "not found"})
            return

        if ERROR_MARKER and ERROR_MARKER in _request_text(req):
            self._json(
                500,
                {
                    "error": {
                        "message": "E2E forced model failure",
                        "type": "server_error",
                        "code": "e2e_forced_model_failure",
                    }
                },
            )
            return

        message = workflow_response(req) or {"role": "assistant", "content": REPLY}
        if req.get("stream"):
            self._stream(message)
        else:
            self._json(
                200,
                {
                    "id": "e2e-mock",
                    "object": "chat.completion",
                    "model": req.get("model", "e2e-mock"),
                    "choices": [
                        {
                            "index": 0,
                            "message": message,
                            "finish_reason": "tool_calls"
                            if message.get("tool_calls")
                            else "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                },
            )

    def _embeddings(self, req: dict):
        texts = req.get("input") or []
        if isinstance(texts, str):
            texts = [texts]
        dimensions = req.get("dimensions") or EMBEDDING_DIMENSIONS
        data = [
            {
                "object": "embedding",
                "index": index,
                "embedding": _embedding(str(text), dimensions),
            }
            for index, text in enumerate(texts)
        ]
        self._json(
            200,
            {
                "object": "list",
                "model": req.get("model", "e2e-mock-embedding"),
                "data": data,
                "usage": {"prompt_tokens": len(texts), "total_tokens": len(texts)},
            },
        )

    def _stream(self, message):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(_chunk({"role": "assistant"}))
        if message.get("tool_calls"):
            for index, call in enumerate(message["tool_calls"]):
                self.wfile.write(_chunk({"tool_calls": [{"index": index, **call}]}))
            self.wfile.write(_chunk({}, finish_reason="tool_calls"))
        else:
            self.wfile.write(_chunk({"content": message.get("content") or ""}))
            self.wfile.write(_chunk({}, finish_reason="stop"))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _json(self, status: int, payload: dict):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    print(f"[mock-model] listening on :{PORT}, reply={REPLY!r}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
