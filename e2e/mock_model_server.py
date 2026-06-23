#!/usr/bin/env python3
"""Deterministic OpenAI-compatible mock model server for E2E tests.

The seeded test completion model points its provider `endpoint` here, so the
backend's litellm calls land on this server instead of a real provider. Every
chat completion returns the same fixed text — fast, free, and fully
deterministic. Streaming and non-streaming are both supported.

Stdlib only (no deps) so it runs on the bare image. Listens on :8200.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPLY = os.environ.get("MOCK_REPLY", "E2E mock completion: pong")
PORT = int(os.environ.get("MOCK_PORT", "8200"))


def _chunk(delta: dict, finish_reason=None) -> bytes:
    payload = {
        "id": "e2e-mock",
        "object": "chat.completion.chunk",
        "model": "e2e-mock",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output clean
        pass

    def do_GET(self):
        # Health + a stub /models so any litellm preflight is happy.
        self._json(200, {"status": "ok"} if self.path.endswith("/health") else {"data": []})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(body or b"{}")
        except json.JSONDecodeError:
            req = {}

        if not self.path.endswith("/chat/completions"):
            self._json(404, {"error": "not found"})
            return

        if req.get("stream"):
            self._stream()
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
                            "message": {"role": "assistant", "content": REPLY},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(_chunk({"role": "assistant"}))
        self.wfile.write(_chunk({"content": REPLY}))
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
