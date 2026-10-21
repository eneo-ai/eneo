"""The shared document runtime for tests: a real tool-runtime process.

Tests that render, fill or inspect Word and PDF documents run against the
engine production uses, served by tool-runtime/tests/support. Request
``shared_document_runtime`` to point the runtime client at it.
"""

from __future__ import annotations

import os
import secrets
import select
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from eneo.document_templates import runtime_client

_TOOL_RUNTIME = Path(__file__).resolve().parents[2] / "tool-runtime"
_START_SECONDS = 20


@pytest.fixture(scope="session")
def document_runtime_server() -> Iterator[tuple[str, str]]:
    """Start the runtime's document endpoints once per test process."""

    bun = shutil.which("bun") or str(Path.home() / ".bun" / "bin" / "bun")
    token = secrets.token_urlsafe(40)
    process = subprocess.Popen(
        [bun, "tests/support/document-control-server.ts"],
        cwd=_TOOL_RUNTIME,
        env={**os.environ, "TEST_DOCUMENT_TOKEN": token},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None and process.stderr is not None
    try:
        ready, _, _ = select.select([process.stdout], [], [], _START_SECONDS)
        if not ready:
            raise RuntimeError("The tool runtime did not start for document tests")
        port = int(process.stdout.readline().strip())
        yield f"http://127.0.0.1:{port}", token
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        process.stdout.close()
        process.stderr.close()


@pytest.fixture
def shared_document_runtime(
    document_runtime_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str]:
    """Point the runtime client at the test process's runtime."""

    monkeypatch.setattr(runtime_client, "_runtime", lambda: document_runtime_server)
    return document_runtime_server
