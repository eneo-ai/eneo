"""Integration tests for the visitor ask/session/feedback surface, usage and retention."""

from __future__ import annotations

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
                num_tokens_question=0,
                num_tokens_answer=0,
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
    assert fake_assistant_ask[-1]["allow_tools"] is False
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

    # Usage was settled after the streams finished.
    resp = await client.get(
        f"/api/v1/widgets/{active_widget['id']}/usage/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text
    usage = resp.json()
    assert usage["daily_token_budget"] == 500_000
    assert usage["days"] and usage["days"][0]["questions"] == 2
    assert (
        usage["budget_used_today"] == 0
    )  # reservations settled to the real (zero) usage


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
