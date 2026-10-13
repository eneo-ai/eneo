"""Contract fixtures for the version=3 AI SDK UI Message Stream.

Each fixture under tests/fixtures/ui_message_stream/ holds the exact event
sequence the encoder emits for one representative conversation turn. The
scenarios below script the internal Completion stream for each fixture and
assert the encoder reproduces the fixture byte for byte; the web-next test
suite (frontend/apps/web-next/src/lib/chat/contract.test.ts) feeds the same
fixtures through the pinned `ai` package. The contract both sides follow is
frontend/apps/web-next/src/lib/chat/CONTRACT.md.

Regenerate a fixture's `events` only when the contract changes
(UPDATE_STREAM_FIXTURES=1 rewrites them in place, keeping the cut point of a
truncated fixture), and keep the `ui` section (the client projection) in step
by running the web-next suite.
"""

import json
import os
from pathlib import Path
from typing import Callable
from uuid import UUID

import pytest

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelPublic,
    McpToolReference,
    ResponseType,
    TokenUsage,
    ToolCallMetadata,
)
from eneo.assistants.api.assistant_models import AssistantResponse
from eneo.conversations import ui_message_stream
from eneo.conversations.ui_message_stream import _ui_message_chunks
from eneo.files.file_models import File, FileType
from eneo.info_blobs.info_blob import InfoBlobInDBWithScore
from eneo.questions.question import UseTools
from eneo.sessions.session import SessionInDB

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "ui_message_stream"

SESSION_ID = UUID("11111111-1111-1111-1111-111111111111")
QUESTION_ID = UUID("22222222-2222-2222-2222-222222222222")
BLOB_A_ID = UUID("33333333-3333-3333-3333-333333333333")
BLOB_B_ID = UUID("33333333-3333-3333-3333-333333333334")
REFERENCE_ID = UUID("44444444-4444-4444-4444-444444444444")
FILE_ID = UUID("55555555-5555-5555-5555-555555555555")
USER_ID = UUID("66666666-6666-6666-6666-666666666666")
TENANT_ID = UUID("77777777-7777-7777-7777-777777777777")
EMBEDDING_MODEL_ID = UUID("88888888-8888-8888-8888-888888888888")
SOURCE_ID = UUID("99999999-9999-9999-9999-999999999999")
MODEL_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
BASE_URL = "http://backend:8123/"


def _completion_model() -> CompletionModelPublic:
    return CompletionModelPublic(
        id=MODEL_ID,
        name="mock-model",
        nickname="Mock",
        max_input_tokens=10_000,
        max_output_tokens=4_000,
        is_deprecated=False,
        vision=False,
        reasoning=False,
    )


def _blob(blob_id: UUID, title: str) -> InfoBlobInDBWithScore:
    return InfoBlobInDBWithScore(
        id=blob_id,
        title=title,
        url="https://example.test/handbook",
        text="reference text",
        embedding_model_id=EMBEDDING_MODEL_ID,
        source_id=SOURCE_ID,
        version_state="active",
        original_available=True,
        user_id=USER_ID,
        tenant_id=TENANT_ID,
        size=42,
        score=0.87,
    )


def _generated_file() -> File:
    return File(
        id=FILE_ID,
        name="generated.png",
        checksum="abc",
        size=10,
        mimetype="image/png",
        file_type=FileType.IMAGE,
        blob=b"\x89PNG",
        user_id=USER_ID,
        tenant_id=TENANT_ID,
    )


def _tool(
    status: str | None, approved: bool | None = None, tool_call_id: str = "call-1"
) -> ToolCallMetadata:
    return ToolCallMetadata(
        server_name="files",
        tool_name="read_file",
        title="Read a file",
        arguments={"path": "a.txt"},
        tool_call_id=tool_call_id,
        approved=approved,
        result_status=status,
        # The loopback files server: Eneo's own, by routing (not by its name).
        is_internal=True,
    )


def _mcp_reference() -> McpToolReference:
    return McpToolReference(
        id=REFERENCE_ID,
        tool_call_id="call-1",
        mcp_tool_name="files__read_file",
        uri="mcp://files/a.txt",
        mime_type="text/markdown",
        content="resource content",
        meta={"title": "a.txt", "section": "Intro"},
        order=0,
    )


def _usage() -> Completion:
    return Completion(
        response_type=ResponseType.TOKEN_USAGE,
        usage=TokenUsage(prompt_tokens=12, completion_tokens=3),
    )


def _text(text: str, **kwargs: object) -> Completion:
    return Completion(response_type=ResponseType.TEXT, text=text, **kwargs)  # pyright: ignore[reportArgumentType]


def _tool_call(*tools: ToolCallMetadata, **kwargs: object) -> Completion:
    return Completion(
        response_type=ResponseType.TOOL_CALL,
        tool_calls_metadata=list(tools),
        **kwargs,  # pyright: ignore[reportArgumentType]
    )


def _approval_required(approval_id: str, *tools: ToolCallMetadata) -> Completion:
    return Completion(
        response_type=ResponseType.TOOL_APPROVAL_REQUIRED,
        approval_id=approval_id,
        tool_calls_metadata=list(tools),
    )


# Scenario name (= fixture file stem) -> scripted Completion stream and the
# pre-retrieved references that precede it.
SCENARIOS: dict[
    str, Callable[[], tuple[list[Completion], list[InfoBlobInDBWithScore]]]
] = {
    "plain-text": lambda: ([_text("Hello"), _text(", world"), _usage()], []),
    "reasoning-and-text": lambda: (
        [
            Completion(
                response_type=ResponseType.REASONING, reasoning_content="Let me "
            ),
            Completion(
                response_type=ResponseType.REASONING, reasoning_content="think."
            ),
            _text("The answer is 42."),
            _usage(),
        ],
        [],
    ),
    "tool-call-with-output": lambda: (
        [
            _tool_call(_tool(status=None)),
            _tool_call(
                _tool(status="succeeded"), mcp_tool_references=[_mcp_reference()]
            ),
            _text("a.txt says hello."),
            _usage(),
        ],
        [],
    ),
    "tool-failure": lambda: (
        [
            _tool_call(_tool(status=None)),
            _tool_call(_tool(status="failed")),
            _text("I could not read the file."),
            _usage(),
        ],
        [],
    ),
    "tool-approval-approved": lambda: (
        [
            _approval_required("approval-1", _tool(status=None)),
            # The user approved: the adapter answers with the decided snapshot,
            # then runs the call.
            _tool_call(_tool(status="approved", approved=True)),
            _tool_call(_tool(status="succeeded", approved=True)),
            _text("a.txt says hello."),
            _usage(),
        ],
        [],
    ),
    "tool-approval-denied": lambda: (
        [
            _approval_required("approval-1", _tool(status=None)),
            _tool_call(_tool(status="denied", approved=False)),
            _text("Understood, I did not read the file."),
            _usage(),
        ],
        [],
    ),
    "tool-approval-timeout": lambda: (
        [
            _approval_required("approval-1", _tool(status=None)),
            Completion(
                response_type=ResponseType.TOOL_APPROVAL_TIMEOUT,
                approval_id="approval-1",
                tool_calls_metadata=[_tool(status="timeout_denied", approved=False)],
            ),
            _tool_call(_tool(status="timeout_denied", approved=False)),
            _text("The approval timed out, so I did not read the file."),
            _usage(),
        ],
        [],
    ),
    "file-part": lambda: (
        [
            _text("Here is your image."),
            Completion(
                response_type=ResponseType.FILES, generated_file=_generated_file()
            ),
            _usage(),
        ],
        [],
    ),
    "sources": lambda: (
        [
            _text("According to", reference_chunks=[_blob(BLOB_A_ID, "Handbook")]),
            _text(" the handbook", reference_chunks=[_blob(BLOB_B_ID, "Policy")]),
            _text(", yes."),
            _usage(),
        ],
        [_blob(BLOB_A_ID, "Handbook")],
    ),
    # The client cancelled while "Hello" was streaming: the fixture is the
    # prefix the client saw (no finish, no [DONE]).
    "cancelled-mid-stream": lambda: ([_text("Hello"), _text(", world"), _usage()], []),
    "backend-error": lambda: (
        [
            _text("Partial"),
            Completion(
                response_type=ResponseType.ERROR,
                error="The model is unavailable",
                error_code=503,
                stop=True,
            ),
        ],
        [],
    ),
}


def _response(
    completions: list[Completion], info_blobs: list[InfoBlobInDBWithScore]
) -> AssistantResponse:
    async def stream():
        for completion in completions:
            yield completion

    return AssistantResponse(
        session=SessionInDB(id=SESSION_ID, name="Test session", user_id=USER_ID),
        question="What is in a.txt?",
        question_id=QUESTION_ID,
        files=[],
        answer=stream(),
        info_blobs=info_blobs,
        completion_model=_completion_model(),
        tools=UseTools(assistants=[]),
    )


async def encode(name: str) -> list[dict]:
    completions, info_blobs = SCENARIOS[name]()
    return [
        chunk
        async for chunk in _ui_message_chunks(
            _response(completions, info_blobs), base_url=BASE_URL
        )
    ]


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text())


@pytest.fixture(autouse=True)
def _stable_download_token(monkeypatch: pytest.MonkeyPatch) -> None:
    # Generated-file URLs carry a signed, expiring token; pin it for the fixtures.
    monkeypatch.setattr(
        ui_message_stream, "generate_signed_token", lambda **_: "fixture-token"
    )


def test_every_fixture_has_a_scenario_and_vice_versa():
    fixture_names = {path.stem for path in FIXTURE_DIR.glob("*.json")}
    assert fixture_names == set(SCENARIOS)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(SCENARIOS))
async def test_encoder_reproduces_fixture(name: str):
    fixture = load_fixture(name)
    events = await encode(name)

    if os.environ.get("UPDATE_STREAM_FIXTURES"):
        cut = len(fixture["events"]) if fixture["terminal"] == "truncated" else None
        fixture["events"] = events[:cut]
        (FIXTURE_DIR / f"{name}.json").write_text(json.dumps(fixture, indent=2) + "\n")

    if fixture["terminal"] == "truncated":
        # A cancelled stream is a strict prefix of the full one: the client
        # never sees finish or [DONE].
        assert events[: len(fixture["events"])] == fixture["events"]
        assert len(fixture["events"]) < len(events)
        assert all(event["type"] != "finish" for event in fixture["events"])
        return

    assert events == fixture["events"]
    assert events[0]["type"] == "start"
    assert events[1]["type"] == "data-session"
    assert events[-1]["type"] == "finish"
    if fixture["terminal"] == "error":
        assert any(event["type"] == "error" for event in events)
    else:
        assert all(event["type"] != "error" for event in events)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_fixture_declares_its_client_projection(name: str):
    fixture = load_fixture(name)
    assert fixture["name"] == name
    assert fixture["terminal"] in {"finish", "error", "truncated"}
    ui = fixture["ui"]
    assert ui["status"] == ("ready" if fixture["terminal"] == "finish" else "error")
    assert ui["message"]["id"] == str(QUESTION_ID)
    assert ui["message"]["role"] == "assistant"
