"""HTTP contract of the insights chat: access, stream format and persistence.

The completion call is stubbed; everything around it (access checks, model
resolution, the attached insights server, the link row, tool-call
persistence, the audit row and the hidden-session rule) runs for real.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelResponse,
    ResponseType,
    ToolCallMetadata,
)
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.insight_conversations_table import InsightConversations
from eneo.database.tables.questions_table import Questions

PATH = "/api/v1/analysis/conversation-insights/chat/"
AUDIT_ENQUEUE = "eneo.audit.application.audit_service.job_manager.enqueue"

# The test JWT secret is short; the warning is about the env, not the code.
pytestmark = pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")


def _tool_call(**overrides: Any) -> ToolCallMetadata:
    fields: dict[str, Any] = dict(
        server_name="insights",
        tool_name="top_questions",
        title="Top questions",
        tool_call_id="call-1",
        arguments={"start": "2026-09-07T00:00:00+02:00", "n": 5},
        result="Top 1 exact-text question groups ...",
        result_status="succeeded",
        mcp_tool_name="insights__top_questions",
        is_internal=True,
        is_bundled=False,
    )
    fields.update(overrides)
    return ToolCallMetadata(**fields)


async def _chunks():
    yield Completion(
        response_type=ResponseType.TOOL_CALL,
        tool_calls_metadata=[_tool_call(result=None, result_status="pending")],
    )
    yield Completion(
        response_type=ResponseType.TOOL_CALL, tool_calls_metadata=[_tool_call()]
    )
    yield Completion(response_type=ResponseType.TEXT, text="Vanligaste frågan ")
    yield Completion(response_type=ResponseType.TEXT, text="gäller bygglov.")


@pytest.fixture
def stub_completion(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the model call; record its kwargs for the assertions."""
    captured: dict[str, Any] = {}

    async def fake_get_response(self: CompletionService, **kwargs: Any):
        captured.update(kwargs)
        return CompletionModelResponse(
            completion=_chunks(),
            model=kwargs["model"],
            extended_logging=None,
            total_token_count=42,
            usage=None,
        )

    monkeypatch.setattr(CompletionService, "get_response", fake_get_response)
    return captured


def _events(text: str) -> list[dict[str, Any]]:
    """The stream's parts, in order; the last frame is ``[DONE]``."""
    payloads = [
        line.removeprefix("data: ")
        for line in text.splitlines()
        if line.startswith("data: ")
    ]
    assert payloads[-1] == "[DONE]"
    return [json.loads(payload) for payload in payloads[:-1]]


def _session_id(events: list[dict[str, Any]]) -> str:
    return next(e for e in events if e["type"] == "data-session")["data"]["session_id"]


async def _seed_and_token(db_container, admin_user, seed_insights):
    async with db_container() as container:
        seed = await seed_insights(container, admin_user)
        token = container.auth_service().create_access_token_for_user(admin_user)
    return seed, {"Authorization": f"Bearer {token}"}


async def test_a_turn_streams_the_chat_stream_and_persists_a_hidden_conversation(
    db_container,
    admin_user,
    client,
    patch_auth_service_jwt,
    seed_insights,
    stub_completion,
):
    seed, headers = await _seed_and_token(db_container, admin_user, seed_insights)

    # Audit rows are queued for background processing; assert the enqueue.
    with patch(AUDIT_ENQUEUE, new_callable=AsyncMock) as enqueue_audit:
        response = await client.post(
            PATH,
            json={
                "assistant_id": str(seed["bygg"]),
                "question": "Vilka är de vanligaste frågorna?",
                "timezone": "Europe/Stockholm",
                "stream": True,
                "selected_range": {"start": "2026-09-01", "end": "2026-09-08"},
            },
            headers=headers,
        )
    assert response.status_code == 200, response.text
    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
    events = _events(response.text)
    assert [e["type"] for e in events] == [
        "start",
        "data-session",
        "tool-input-available",
        "tool-output-available",
        "text-start",
        "text-delta",
        "text-delta",
        "data-token-usage",
        "text-end",
        "finish",
    ]
    session_id = _session_id(events)
    question_id = events[0]["messageId"]
    session_data = events[1]["data"]
    assert session_data["completion_model"]["id"] == str(seed["model_id"])
    for part in events[2:4]:
        eneo = part["providerMetadata"]["eneo"]
        assert eneo["server_name"] == "insights"
        assert eneo["is_internal"] is True
    # The call's status is streamed, never its result.
    assert events[3]["output"] == {"status": "succeeded"}
    assert "Top 1 exact-text" not in response.text

    # The completion got the insights server, and nothing else.
    (server,) = stub_completion["mcp_servers"]
    assert server.name == "insights"
    assert {"usage_summary", "list_questions", "top_questions", "find_gaps"} <= {
        t.name for t in server.tools
    }
    assert stub_completion["stream"] is True
    assert stub_completion["extended_logging"] is False
    assert stub_completion["require_tool_approval"] is False
    assert "assistant 'bygg'" in stub_completion["prompt"]
    assert "2026-09-01 to 2026-09-08" in stub_completion["prompt"]

    async with db_container() as container:
        db = container.session()
        link = (
            await db.execute(
                sa.select(InsightConversations).where(
                    InsightConversations.session_id == session_id
                )
            )
        ).scalar_one()
        assert link.assistant_id == seed["bygg"]
        assert link.actor_user_id == admin_user.id
        assert link.timezone == "Europe/Stockholm"
        assert link.completion_model_id == seed["model_id"]

        question = (
            await db.execute(sa.select(Questions).where(Questions.id == question_id))
        ).scalar_one()
        assert question.answer == "Vanligaste frågan gäller bygglov."
        assert question.tool_calls is not None
        (tool_call,) = question.tool_calls
        assert isinstance(tool_call, dict)
        assert tool_call["tool_name"] == "top_questions"
        assert tool_call["result"] == "Top 1 exact-text question groups ..."

        # Hidden from the operator's own history from the first commit.
        assert await container.session_repo().get(session_id) is None

    sidebar = await client.get(
        "/api/v1/conversations/",
        params={"assistant_id": str(seed["bygg"])},
        headers=headers,
    )
    assert sidebar.status_code == 200, sidebar.text
    assert session_id not in {item["id"] for item in sidebar.json()["items"]}

    assert enqueue_audit.await_count == 1
    audit_params = enqueue_audit.await_args.args[2]
    assert audit_params["action"] == "insight_conversation_started"
    assert audit_params["entity_type"] == "assistant"
    assert str(audit_params["entity_id"]) == str(seed["bygg"])
    assert audit_params["metadata"]["target"]["name"] == "bygg"
    assert audit_params["metadata"]["extra"]["session_id"] == session_id


async def test_a_group_chat_analysis_is_keyed_on_the_group_chat(
    db_container,
    admin_user,
    client,
    patch_auth_service_jwt,
    seed_insights,
    stub_completion,
):
    seed, headers = await _seed_and_token(db_container, admin_user, seed_insights)

    response = await client.post(
        PATH,
        json={
            "group_chat_id": str(seed["group_chat"]),
            "question": "Vad frågade användarna om igår?",
            "timezone": "Europe/Stockholm",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert _events(response.text)[-1]["type"] == "finish"
    assert "group chat 'gc-insights'" in stub_completion["prompt"]

    async with db_container() as container:
        db = container.session()
        link = (
            await db.execute(
                sa.select(InsightConversations).where(
                    InsightConversations.group_chat_id == seed["group_chat"]
                )
            )
        ).scalar_one()
        question = (
            await db.execute(
                sa.select(Questions).where(Questions.session_id == link.session_id)
            )
        ).scalar_one()
        assert question.answer == "Vanligaste frågan gäller bygglov."
        assert question.tool_calls is not None
        assert question.tool_calls[0]["result_status"] == "succeeded"


async def test_insights_disabled_target_is_forbidden(
    db_container,
    admin_user,
    client,
    patch_auth_service_jwt,
    seed_insights,
    stub_completion,
):
    seed, headers = await _seed_and_token(db_container, admin_user, seed_insights)

    response = await client.post(
        PATH,
        json={"assistant_id": str(seed["other"]), "question": "Hur går det?"},
        headers=headers,
    )

    assert response.status_code == 403, response.text
    assert "mcp_servers" not in stub_completion
    async with db_container() as container:
        count = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(InsightConversations)
            .where(InsightConversations.assistant_id == seed["other"])
        )
    assert count == 0


async def test_unknown_timezone_is_a_bad_request_with_a_code(
    db_container,
    admin_user,
    client,
    patch_auth_service_jwt,
    seed_insights,
    stub_completion,
):
    seed, headers = await _seed_and_token(db_container, admin_user, seed_insights)

    response = await client.post(
        PATH,
        json={
            "assistant_id": str(seed["bygg"]),
            "question": "Hur går det?",
            "timezone": "Mars/Olympus",
        },
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "invalid_timezone"


async def test_no_tool_capable_model_is_a_bad_request_with_a_code(
    db_container,
    admin_user,
    client,
    patch_auth_service_jwt,
    seed_insights,
    stub_completion,
):
    seed, headers = await _seed_and_token(db_container, admin_user, seed_insights)
    async with db_container() as container:
        await container.session().execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id == seed["model_id"])
            .values(supports_tool_calling=False)
        )

    response = await client.post(
        PATH,
        json={"assistant_id": str(seed["bygg"]), "question": "Hur går det?"},
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "insights_model_unavailable"


async def test_follow_up_history_tool_result_and_delete_round_trip(
    db_container,
    admin_user,
    client,
    patch_auth_service_jwt,
    seed_insights,
    stub_completion,
):
    seed, headers = await _seed_and_token(db_container, admin_user, seed_insights)
    with patch(AUDIT_ENQUEUE, new_callable=AsyncMock) as enqueue_audit:
        started = await client.post(
            PATH,
            json={"assistant_id": str(seed["bygg"]), "question": "Första frågan"},
            headers=headers,
        )
        assert started.status_code == 200, started.text
        session_id = _session_id(_events(started.text))

        follow_up = await client.post(
            f"{PATH}{session_id}/",
            json={"question": "Och förra veckan?", "stream": True},
            headers=headers,
        )
        assert follow_up.status_code == 200, follow_up.text
        assert _session_id(_events(follow_up.text)) == session_id
        # The prior turn, tool calls included, is in the replayed session.
        history = stub_completion["session"].questions
        assert [q.question for q in history] == ["Första frågan"]
        assert history[0].tool_calls
        assert history[0].tool_calls[0].tool_name == "top_questions"

        listed = await client.get(
            PATH,
            params={"assistant_id": str(seed["bygg"]), "limit": 10},
            headers=headers,
        )
        assert listed.status_code == 200, listed.text
        items = listed.json()["items"]
        # Named by the question each started with, newest first; the seeded
        # conversation belongs to the same operator and target.
        assert [item["name"] for item in items] == ["Första frågan", "insight"]
        assert items[0]["id"] == session_id
        assert listed.json()["total_count"] == 2

        fetched = await client.get(f"{PATH}{session_id}/", headers=headers)
        assert fetched.status_code == 200, fetched.text
        messages = fetched.json()["messages"]
        assert [m["question"] for m in messages] == [
            "Första frågan",
            "Och förra veckan?",
        ]
        # History shows the steps: the saved call, without its result.
        saved_call = messages[0]["tool_calls"][0]
        assert saved_call["tool_name"] == "top_questions"
        assert saved_call["server_name"] == "insights"
        assert saved_call["is_internal"] is True
        assert saved_call["tool_call_id"] == "call-1"
        assert saved_call["arguments"] == {
            "start": "2026-09-07T00:00:00+02:00",
            "n": 5,
        }
        assert saved_call["result_status"] == "succeeded"
        assert saved_call["result"] is None

        result = await client.get(
            f"{PATH}{session_id}/tool-calls/call-1/result/", headers=headers
        )
        assert result.status_code == 200, result.text
        assert result.json()["result"] == "Top 1 exact-text question groups ..."
        assert result.json()["mcp_tool_name"] == "insights__top_questions"
        missing = await client.get(
            f"{PATH}{session_id}/tool-calls/no-such-call/result/", headers=headers
        )
        assert missing.status_code == 404

        deleted = await client.delete(f"{PATH}{session_id}/", headers=headers)
        assert deleted.status_code == 204, deleted.text
        gone = await client.get(f"{PATH}{session_id}/", headers=headers)
        assert gone.status_code == 404

    actions = [call.args[2]["action"] for call in enqueue_audit.await_args_list]
    assert actions == ["insight_conversation_started", "insight_conversation_deleted"]

    async with db_container() as container:
        count = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(InsightConversations)
            .where(InsightConversations.session_id == session_id)
        )
    assert count == 0


async def test_list_pages_with_the_cursor_it_gives(
    db_container,
    admin_user,
    client,
    patch_auth_service_jwt,
    seed_insights,
    stub_completion,
):
    seed, headers = await _seed_and_token(db_container, admin_user, seed_insights)
    for question in ("Ett", "Två"):
        response = await client.post(
            PATH,
            json={"assistant_id": str(seed["bygg"]), "question": question},
            headers=headers,
        )
        assert response.status_code == 200, response.text

    first = await client.get(
        PATH, params={"assistant_id": str(seed["bygg"]), "limit": 2}, headers=headers
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert [item["name"] for item in body["items"]] == ["Två", "Ett"]
    assert body["total_count"] == 3
    assert isinstance(body["next_cursor"], str)

    second = await client.get(
        PATH,
        params={
            "assistant_id": str(seed["bygg"]),
            "limit": 2,
            "cursor": body["next_cursor"],
        },
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert [item["id"] for item in second.json()["items"]] == [
        str(seed["insight_session"])
    ]
    assert second.json()["next_cursor"] is None

    refused = await client.get(
        PATH,
        params={"assistant_id": str(seed["bygg"]), "cursor": "not a cursor"},
        headers=headers,
    )
    assert refused.status_code == 400, refused.text
