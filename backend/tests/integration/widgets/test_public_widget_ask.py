"""Integration tests for the visitor ask/session/feedback surface, usage and retention."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import altcha
import pytest
import sqlalchemy as sa

from eneo.ai_models.completion_models.completion_model import Completion, ResponseType
from eneo.assistants.api.assistant_models import AssistantResponse
from eneo.assistants.assistant_service import AssistantService
from eneo.database.database import sessionmanager
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.tenant_table import Tenants
from eneo.main.exceptions import BadRequestException
from eneo.questions.question import UseTools
from eneo.widgets.application.widget_retention import purge_expired_widget_sessions


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _mint(client, public_id: str) -> str:
    resp = await client.get(f"/api/v1/widgets/{public_id}/challenge/")
    challenge = altcha.Challenge.from_dict(resp.json())
    solution = altcha.solve_challenge(challenge)
    assert solution is not None
    payload = altcha.Payload(challenge=challenge, solution=solution).to_base64()
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/visitor-sessions/", json={"altcha": payload}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


# Stored like a turn with tool rounds: the cumulative columns add up every
# provider request, the context columns hold the final request only.
PROMPT_TOKENS, ANSWER_TOKENS = 4_800, 300
FINAL_PROMPT_TOKENS, FINAL_ANSWER_TOKENS = 1_800, 120


@pytest.fixture
def fake_assistant_ask(monkeypatch):
    """Replace the model call with a canned two-chunk stream.

    Everything before it (visitor container, space actor, session ownership)
    and after it (settlement, usage, retention) still runs for real.
    """
    calls: list[dict] = []

    async def fake_ask(self, *, question, assistant_id, session_id=None, **kwargs):
        calls.append({"question": question, "session_id": session_id, **kwargs})
        if session_id is None:
            session = await self.session_service.create_session(
                name=question, assistant_id=assistant_id
            )
        else:
            session = await self.session_service.get_session_by_uuid(
                id=session_id, assistant_id=assistant_id
            )

        question_id = await self.session_service.question_repo.session.scalar(
            sa.insert(Questions)
            .values(
                session_id=session.id,
                tenant_id=self.user.tenant_id,
                assistant_id=assistant_id,
                question=question,
                answer="Hej där!",
                num_tokens_question=PROMPT_TOKENS,
                num_tokens_answer=ANSWER_TOKENS,
                context_prompt_tokens=FINAL_PROMPT_TOKENS,
                context_completion_tokens=FINAL_ANSWER_TOKENS,
            )
            .returning(Questions.id)
        )

        async def answer():
            for text in ("Hej", " där!"):
                yield Completion(text=text, response_type=ResponseType.TEXT)

        return AssistantResponse.model_construct(
            session=session,
            question=question,
            question_id=question_id,
            files=[],
            answer=answer(),
            info_blobs=[],
            completion_model=None,
            tools=UseTools(assistants=[]),
        )

    monkeypatch.setattr(AssistantService, "ask", fake_ask)
    return calls


def _sse_events(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event = "message"
    for line in text.splitlines():
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            events.append((event, json.loads(line[len("data:") :].strip())))
            event = "message"
    return events


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ask_requires_visitor_token_and_validates_input(client, active_widget):
    public_id = active_widget["public_id"]

    resp = await client.post(
        f"/api/v1/widgets/{public_id}/ask/", json={"question": "Hej"}
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"]["code"] == "visitor_token_invalid"

    token = await _mint(client, public_id)
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/ask/",
        json={"question": "x" * 2001},
        headers=_auth(token),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "question_too_long"

    resp = await client.post(
        f"/api/v1/widgets/{public_id}/ask/",
        json={"question": "Hej", "session_id": str(uuid4())},
        headers=_auth(token),
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["code"] == "session_not_owned"

    resp = await client.get(
        f"/api/v1/widgets/{public_id}/sessions/{uuid4()}/", headers=_auth(token)
    )
    assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_visitor_ask_streams_and_owns_its_session(
    client, admin_token, active_widget, fake_assistant_ask
):
    public_id = active_widget["public_id"]
    token = await _mint(client, public_id)

    resp = await client.post(
        f"/api/v1/widgets/{public_id}/ask/",
        json={"question": "Vad har biblioteket för öppettider?"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(resp.text)
    assert events[0][0] == "first_chunk"
    assert "".join(d["answer"] for e, d in events if e == "text") == "Hej där!"
    session_id = events[0][1]["session_id"]
    # The assistant as configured: nothing narrows its MCP servers or
    # capabilities and no approval is requested (tools-off was dropped).
    assert set(fake_assistant_ask[-1]) == {
        "question",
        "session_id",
        "stream",
        "version",
        "num_chunks_override",
        "prompt_addendum",
    }
    assert fake_assistant_ask[-1]["stream"] is True

    # The visitor can restore and continue its own session.
    resp = await client.get(
        f"/api/v1/widgets/{public_id}/sessions/{session_id}/", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == session_id
    assert "visitor_id" not in resp.json()

    resp = await client.post(
        f"/api/v1/widgets/{public_id}/ask/",
        json={"question": "Och på helger?", "session_id": session_id},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert fake_assistant_ask[-1]["session_id"] == UUID(session_id)

    resp = await client.post(
        f"/api/v1/widgets/{public_id}/sessions/{session_id}/feedback/",
        json={"value": 1, "text": "Tack!"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["feedback"]["value"] == 1
    assert resp.json()["feedback"]["text"] is None  # not stored by default

    # Changing the vote moves it between the day's counters instead of adding.
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/sessions/{session_id}/feedback/",
        json={"value": -1},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text

    # Another visitor of the same widget sees nothing.
    other = await _mint(client, public_id)
    resp = await client.get(
        f"/api/v1/widgets/{public_id}/sessions/{session_id}/", headers=_auth(other)
    )
    assert resp.status_code == 404
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/ask/",
        json={"question": "Hej", "session_id": session_id},
        headers=_auth(other),
    )
    assert resp.status_code == 404

    # The session is persisted as a widget session, never as a user's.
    async with sessionmanager.session() as db, db.begin():
        row = (
            await db.execute(
                sa.select(
                    Sessions.user_id,
                    Sessions.api_key_id,
                    Sessions.widget_id,
                    Sessions.visitor_id,
                ).where(Sessions.id == UUID(session_id))
            )
        ).one()
    assert row.user_id is None and row.api_key_id is None
    assert str(row.widget_id) == active_widget["id"]
    assert row.visitor_id is not None

    # Usage was settled after the streams finished, on what every provider
    # round of the two answers cost, not on their final requests.
    resp = await client.get(
        f"/api/v1/widgets/{active_widget['id']}/usage/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text
    usage = resp.json()
    assert usage["daily_token_budget"] == 500_000
    day = usage["days"][0]
    assert day["questions"] == 2
    assert (day["helpful"], day["unhelpful"]) == (0, 1)
    assert (day["input_tokens"], day["output_tokens"]) == (
        2 * PROMPT_TOKENS,
        2 * ANSWER_TOKENS,
    )
    assert usage["budget_used_today"] == 2 * (PROMPT_TOKENS + ANSWER_TOKENS)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_budget_exhaustion_blocks_and_is_counted(
    client, admin_token, active_widget, fake_assistant_ask
):
    public_id = active_widget["public_id"]
    resp = await client.patch(
        f"/api/v1/widgets/{active_widget['id']}/",
        json={
            "revision": (
                await client.get(
                    f"/api/v1/widgets/{active_widget['id']}/",
                    headers=_auth(admin_token),
                )
            ).json()["revision"],
            "limits": {"daily_token_budget": 1_000},
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    token = await _mint(client, public_id)

    resp = await client.post(
        f"/api/v1/widgets/{public_id}/ask/",
        json={"question": "Hej"},
        headers=_auth(token),
    )
    assert resp.status_code == 429, resp.text
    assert resp.json()["detail"]["code"] == "budget_exhausted"
    assert "retry-after" in resp.headers
    assert fake_assistant_ask == []

    resp = await client.get(
        f"/api/v1/widgets/{active_widget['id']}/usage/", headers=_auth(admin_token)
    )
    assert resp.json()["days"][0]["blocked_budget"] == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retention_purge_deletes_old_widget_sessions(
    client, active_widget, fake_assistant_ask
):
    public_id = active_widget["public_id"]
    token = await _mint(client, public_id)
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/ask/",
        json={"question": "Hej"},
        headers=_auth(token),
    )
    session_id = UUID(_sse_events(resp.text)[0][1]["session_id"])

    # Age the session past the 30-day default retention.
    async with sessionmanager.session() as db, db.begin():
        await db.execute(
            sa.update(Sessions)
            .where(Sessions.id == session_id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(days=31))
        )

    summary = await purge_expired_widget_sessions()
    assert summary["errors"] == 0
    assert summary["sessions_deleted"] >= 1

    resp = await client.get(
        f"/api/v1/widgets/{public_id}/sessions/{session_id}/", headers=_auth(token)
    )
    assert resp.status_code == 404


async def _patch_widget(client, admin_token: str, widget_id: str, **fields) -> dict:
    current = await client.get(
        f"/api/v1/widgets/{widget_id}/", headers=_auth(admin_token)
    )
    resp = await client.patch(
        f"/api/v1/widgets/{widget_id}/",
        json={"revision": current.json()["revision"], **fields},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _stored_conversations(widget_id: str) -> tuple[int, int]:
    """(sessions, questions) committed for the widget, seen from a new session."""
    async with sessionmanager.session() as db, db.begin():
        sessions = await db.scalar(
            sa.select(sa.func.count())
            .select_from(Sessions)
            .where(Sessions.widget_id == UUID(widget_id))
        )
        questions = await db.scalar(
            sa.select(sa.func.count())
            .select_from(Questions)
            .join(Sessions, Questions.session_id == Sessions.id)
            .where(Sessions.widget_id == UUID(widget_id))
        )
    return int(sessions or 0), int(questions or 0)


async def _set_tenant_state(tenant_id: UUID, state: str) -> None:
    async with sessionmanager.session() as db, db.begin():
        await db.execute(
            sa.update(Tenants).where(Tenants.id == tenant_id).values(state=state)
        )


@pytest.fixture
def failing_assistant_ask(monkeypatch):
    """The real placeholder write, then a failed model preparation."""

    async def fake_ask(self, *, question, assistant_id, session_id=None, **kwargs):
        await self.session_service.create_session_with_question_placeholder(
            name=question,
            question=question,
            session_assistant_id=assistant_id,
            question_assistant_id=assistant_id,
        )
        raise BadRequestException("Model preparation failed")

    monkeypatch.setattr(AssistantService, "ask", fake_ask)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_suspended_tenant_revokes_visitor_access(
    client, admin_token, active_widget, fake_assistant_ask, db_container
):
    public_id = active_widget["public_id"]
    token = await _mint(client, public_id)
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/ask/",
        json={"question": "Hej"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    session_id = _sse_events(resp.text)[0][1]["session_id"]
    async with db_container() as container:
        user = await container.user_repo().get_user_by_email("test@example.com")
        tenant_id = user.tenant_id

    await _set_tenant_state(tenant_id, "suspended")
    try:
        # The embed page shows its paused notice before anyone solves a
        # challenge or gets a token.
        for method, path, body in [
            ("GET", "config/", None),
            ("GET", "challenge/", None),
            ("POST", "visitor-sessions/", {"previous_token": token}),
        ]:
            resp = await client.request(
                method, f"/api/v1/widgets/{public_id}/{path}", json=body
            )
            assert resp.status_code == 404, (path, resp.text)
            assert resp.json()["detail"]["code"] == "widget_not_active"
        resp = await client.get(
            f"/api/v1/widgets/{public_id}/sessions/{session_id}/",
            headers=_auth(token),
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"]["code"] == "widget_not_active"
        resp = await client.post(
            f"/api/v1/widgets/{public_id}/ask/",
            json={"question": "Och?", "session_id": session_id},
            headers=_auth(token),
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"]["code"] == "widget_not_active"
        resp = await client.post(
            f"/api/v1/widgets/{public_id}/sessions/{session_id}/feedback/",
            json={"value": 1},
            headers=_auth(token),
        )
        assert resp.status_code == 404, resp.text
    finally:
        await _set_tenant_state(tenant_id, "active")

    # Reactivation restores the visitor's access without a new token.
    resp = await client.get(
        f"/api/v1/widgets/{public_id}/sessions/{session_id}/", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/ask/",
        json={"question": "Och?", "session_id": session_id},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_overlapping_identical_votes_count_once(
    client, admin_token, active_widget, fake_assistant_ask
):
    public_id = active_widget["public_id"]
    token = await _mint(client, public_id)
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/ask/",
        json={"question": "Hej"},
        headers=_auth(token),
    )
    session_id = _sse_events(resp.text)[0][1]["session_id"]
    feedback_url = f"/api/v1/widgets/{public_id}/sessions/{session_id}/feedback/"

    # A double click before the first response arrives.
    first, second = await asyncio.gather(
        client.post(feedback_url, json={"value": 1}, headers=_auth(token)),
        client.post(feedback_url, json={"value": 1}, headers=_auth(token)),
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    async def counters() -> tuple[int, int]:
        resp = await client.get(
            f"/api/v1/widgets/{active_widget['id']}/usage/",
            headers=_auth(admin_token),
        )
        day = resp.json()["days"][0]
        return day["helpful"], day["unhelpful"]

    assert await counters() == (1, 0)

    resp = await client.post(feedback_url, json={"value": -1}, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["feedback"]["value"] == -1
    assert await counters() == (0, 1)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_zero_retention_commits_nothing_when_model_preparation_fails(
    client, admin_token, active_widget, failing_assistant_ask
):
    widget_id = active_widget["id"]
    public_id = active_widget["public_id"]
    await _patch_widget(
        client,
        admin_token,
        widget_id,
        privacy={"retention_days": 0, "store_feedback_text": False},
    )
    token = await _mint(client, public_id)

    resp = await client.post(
        f"/api/v1/widgets/{public_id}/ask/",
        json={"question": "Mitt personnummer är 19XX..."},
        headers=_auth(token),
    )
    assert resp.status_code == 400, resp.text
    assert await _stored_conversations(widget_id) == (0, 0)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retained_widget_keeps_the_question_when_model_preparation_fails(
    client, active_widget, failing_assistant_ask
):
    """Ordinary retention keeps the durable placeholder, like every other chat."""
    public_id = active_widget["public_id"]
    token = await _mint(client, public_id)

    resp = await client.post(
        f"/api/v1/widgets/{public_id}/ask/",
        json={"question": "Hej"},
        headers=_auth(token),
    )
    assert resp.status_code == 400, resp.text
    assert await _stored_conversations(active_widget["id"]) == (1, 1)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_zero_retention_answer_leaves_no_session_behind(
    client, admin_token, active_widget, fake_assistant_ask
):
    widget_id = active_widget["id"]
    public_id = active_widget["public_id"]
    await _patch_widget(
        client,
        admin_token,
        widget_id,
        privacy={"retention_days": 0, "store_feedback_text": False},
    )
    resp = await client.get(f"/api/v1/widgets/{public_id}/config/")
    assert resp.json()["single_turn"] is True
    token = await _mint(client, public_id)

    resp = await client.post(
        f"/api/v1/widgets/{public_id}/ask/",
        json={"question": "Vad har biblioteket för öppettider?"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    events = _sse_events(resp.text)
    assert "".join(d["answer"] for e, d in events if e == "text") == "Hej där!"
    session_id = events[0][1]["session_id"]
    assert await _stored_conversations(widget_id) == (0, 0)

    # Nothing to continue, restore or rate afterwards.
    for method, url, body in (
        (
            "post",
            f"/api/v1/widgets/{public_id}/ask/",
            {"question": "Och?", "session_id": session_id},
        ),
        ("get", f"/api/v1/widgets/{public_id}/sessions/{session_id}/", None),
        (
            "post",
            f"/api/v1/widgets/{public_id}/sessions/{session_id}/feedback/",
            {"value": 1},
        ),
    ):
        if method == "get":
            resp = await client.get(url, headers=_auth(token))
        else:
            resp = await client.post(url, json=body, headers=_auth(token))
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"]["code"] == "session_not_owned"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_changing_the_vote_keeps_the_visitors_comment(
    client, admin_token, active_widget, fake_assistant_ask
):
    await _patch_widget(
        client,
        admin_token,
        active_widget["id"],
        privacy={"retention_days": 30, "store_feedback_text": True},
    )
    public_id = active_widget["public_id"]
    token = await _mint(client, public_id)
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/ask/",
        json={"question": "Hej"},
        headers=_auth(token),
    )
    session_id = _sse_events(resp.text)[0][1]["session_id"]
    feedback_url = f"/api/v1/widgets/{public_id}/sessions/{session_id}/feedback/"

    async def stored() -> tuple[int | None, str | None]:
        async with sessionmanager.session() as db, db.begin():
            row = (
                await db.execute(
                    sa.select(Sessions.feedback_value, Sessions.feedback_text).where(
                        Sessions.id == UUID(session_id)
                    )
                )
            ).one()
        return row.feedback_value, row.feedback_text

    resp = await client.post(
        feedback_url,
        json={"value": -1, "text": "Fel öppettider för biblioteket"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert await stored() == (-1, "Fel öppettider för biblioteket")

    # The embed page sends a changed vote without the comment.
    for body in ({"value": 1}, {"value": -1, "text": "  "}):
        resp = await client.post(feedback_url, json=body, headers=_auth(token))
        assert resp.status_code == 200, resp.text
        assert resp.json()["feedback"]["text"] == "Fel öppettider för biblioteket"
    assert await stored() == (-1, "Fel öppettider för biblioteket")

    # A new comment replaces the stored one.
    resp = await client.post(
        feedback_url, json={"value": 1, "text": "Nu stämmer det"}, headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert await stored() == (1, "Nu stämmer det")
