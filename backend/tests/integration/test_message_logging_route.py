"""Message logging route over stored logging rows.

A question answered while extended logging was off still points at a logging
row: the answer path stores one with empty model kwargs and no request body.
The route reports such a question as not logged, the same answer a question
without any logging row gets.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from eneo.database.database import sessionmanager
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.users_table import Users
from eneo.logging.logging import LoggingDetails
from eneo.logging.logging_repo import LoggingRepository

_EMAIL = "test@example.com"
_PASSWORD = "IntegrationPass123!"


async def _token(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/users/login/token/",
        data={"username": _EMAIL, "password": _PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _insight_assistant(client: AsyncClient, token: str) -> tuple[UUID, UUID]:
    headers = {"Authorization": f"Bearer {token}"}
    space = await client.post(
        "/api/v1/spaces/",
        json={"name": f"logging-{uuid4().hex[:8]}", "description": "Logging"},
        headers=headers,
    )
    assert space.status_code in (200, 201), space.text
    assistant = await client.post(
        "/api/v1/assistants/",
        json={"name": f"logging-{uuid4().hex[:8]}", "space_id": space.json()["id"]},
        headers=headers,
    )
    assert assistant.status_code == 200, assistant.text
    assistant_id = assistant.json()["id"]
    enabled = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"insight_enabled": True},
        headers=headers,
    )
    assert enabled.status_code == 200, enabled.text
    user = await client.get("/api/v1/users/me/", headers=headers)
    assert user.status_code == 200, user.text
    return UUID(assistant_id), UUID(user.json()["id"])


async def _question_with_logging(
    *, assistant_id: UUID, user_id: UUID, details: LoggingDetails
) -> UUID:
    async with sessionmanager.session() as session, session.begin():
        logging_row = await LoggingRepository(session).add(details)
        chat_session = Sessions(
            user_id=user_id, name="Logged session", assistant_id=assistant_id
        )
        session.add(chat_session)
        await session.flush()
        question = Questions(
            question="Which day is it?",
            answer="Monday.",
            num_tokens_question=4,
            num_tokens_answer=2,
            tenant_id=(await session.get(Users, user_id)).tenant_id,
            session_id=chat_session.id,
            assistant_id=assistant_id,
            logging_details_id=logging_row.id,
        )
        session.add(question)
        await session.flush()
        return question.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_question_answered_without_extended_logging_is_not_logged(
    client: AsyncClient,
    patch_auth_service_jwt,
    mock_transcription_models,
):
    token = await _token(client)
    assistant_id, user_id = await _insight_assistant(client, token)
    # The row the answer path stores when the Assistant does not log.
    message_id = await _question_with_logging(
        assistant_id=assistant_id,
        user_id=user_id,
        details=LoggingDetails(model_kwargs={}),
    )

    response = await client.get(
        f"/api/v1/logging/{message_id}/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400, response.text
    assert "Question was not logged" in response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_logged_question_returns_its_parsed_request_body(
    client: AsyncClient,
    patch_auth_service_jwt,
    mock_transcription_models,
):
    token = await _token(client)
    assistant_id, user_id = await _insight_assistant(client, token)
    message_id = await _question_with_logging(
        assistant_id=assistant_id,
        user_id=user_id,
        details=LoggingDetails(
            context="Knowledge about weekdays",
            model_kwargs={"temperature": 0.2},
            json_body='[{"role": "user", "content": "Which day is it?"}]',
        ),
    )

    response = await client.get(
        f"/api/v1/logging/{message_id}/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["logging_details"] == {
        "context": "Knowledge about weekdays",
        "model_kwargs": {"temperature": 0.2},
        "json_body": [{"role": "user", "content": "Which day is it?"}],
    }
