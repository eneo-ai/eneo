"""Shared fixture data for the insights integration tests.

One tenant (the seeded admin), its org space with a tool-capable completion
model, an insight-enabled assistant with a handful of conversations at fixed
UTC times, a second assistant without insights, a group chat, and two hidden
sessions (a helper run and an insight conversation) on the insight-enabled
assistant.

Question times, all UTC:
  * s1: "Hur ansöker jag om bygglov?" 2026-09-07 10:00, follow-up
        "Vad kostar det?" 10:05
  * s2: "hur ansöker jag om bygglov" 2026-09-07 22:30
        (already 2026-09-08 00:30 in Europe/Stockholm)
  * s3: "Öppettider?" 2026-09-06 08:00
  * s4: "Kan ni hjälpa mig med deklarationen?" 2026-09-07 15:00, answered
        with an admission of not knowing
  * s5: three near-identical "Var parkerar jag?" questions 2026-09-07 16:00
        (a rephrasing conversation)
  * helper-run session (hidden): 2026-09-07 11:00
  * insight-conversation session (hidden): 2026-09-07 12:00
  * other assistant: 2026-09-07 13:00
  * group chat: 2026-09-07 14:00
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.analysis.insight_conversation_repo import InsightConversationRepository
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.group_chats_table import GroupChatsTable
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import SpacesCompletionModels
from eneo.help_assistants.domain.helper_kind import HelperKind


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


async def _insert_assistant(
    session, *, owner_user_id: UUID, space_id: UUID, name: str, **values
) -> UUID:
    assistant_id = uuid4()
    await session.execute(
        sa.insert(Assistants).values(
            id=assistant_id,
            name=name,
            user_id=owner_user_id,
            space_id=space_id,
            logging_enabled=False,
            is_default=False,
            published=False,
            **values,
        )
    )
    return assistant_id


async def _insert_group_chat(session, *, owner_user_id: UUID, space_id: UUID) -> UUID:
    group_chat_id = uuid4()
    await session.execute(
        sa.insert(GroupChatsTable).values(
            id=group_chat_id,
            name="gc-insights",
            user_id=owner_user_id,
            space_id=space_id,
            allow_mentions=False,
            show_response_label=False,
            published=False,
            insight_enabled=True,
            type="group-chat",
        )
    )
    return group_chat_id


async def _insert_session(
    session,
    *,
    name: str,
    user_id: UUID,
    assistant_id: UUID | None = None,
    group_chat_id: UUID | None = None,
) -> UUID:
    session_id = uuid4()
    await session.execute(
        sa.insert(Sessions).values(
            id=session_id,
            name=name,
            user_id=user_id,
            assistant_id=assistant_id,
            group_chat_id=group_chat_id,
        )
    )
    return session_id


async def _insert_question(
    session,
    *,
    tenant_id: UUID,
    session_id: UUID,
    assistant_id: UUID | None,
    text: str,
    at: datetime,
) -> UUID:
    question_id = uuid4()
    await session.execute(
        sa.insert(Questions).values(
            id=question_id,
            tenant_id=tenant_id,
            session_id=session_id,
            assistant_id=assistant_id,
            question=text,
            answer=f"answer to {text}",
            num_tokens_question=1,
            num_tokens_answer=1,
            created_at=at,
            updated_at=at,
        )
    )
    return question_id


async def _seed_insights(container, admin_user) -> dict[str, UUID]:
    """Build the fixture described in the module docstring."""
    session = container.session()
    tenant_id = admin_user.tenant_id

    # Materialise the org space with the admin as member, as the product does
    # lazily on first admin visit; the insights actor checks need membership.
    space = await container.space_service().get_or_create_tenant_space()
    space_id = space.id

    model_id = await session.scalar(
        sa.select(CompletionModels.id).where(
            CompletionModels.tenant_id == tenant_id,
            CompletionModels.is_enabled.is_(True),
        )
    )
    assert model_id is not None, "seed_default_models should have run"
    await session.execute(
        sa.update(CompletionModels)
        .where(CompletionModels.id == model_id)
        .values(supports_tool_calling=True)
    )
    await session.execute(
        sa.insert(SpacesCompletionModels).values(
            space_id=space_id, completion_model_id=model_id
        )
    )

    bygg = await _insert_assistant(
        session,
        owner_user_id=admin_user.id,
        space_id=space_id,
        name="bygg",
        completion_model_id=model_id,
        insight_enabled=True,
    )
    other = await _insert_assistant(
        session,
        owner_user_id=admin_user.id,
        space_id=space_id,
        name="other",
        completion_model_id=model_id,
        insight_enabled=False,
    )
    group_chat = await _insert_group_chat(
        session, owner_user_id=admin_user.id, space_id=space_id
    )

    s1 = await _insert_session(
        session, name="s1", user_id=admin_user.id, assistant_id=bygg
    )
    s2 = await _insert_session(
        session, name="s2", user_id=admin_user.id, assistant_id=bygg
    )
    s3 = await _insert_session(
        session, name="s3", user_id=admin_user.id, assistant_id=bygg
    )
    s4 = await _insert_session(
        session, name="s4", user_id=admin_user.id, assistant_id=bygg
    )
    s5 = await _insert_session(
        session, name="s5", user_id=admin_user.id, assistant_id=bygg
    )
    helper_session = await _insert_session(
        session, name="helper", user_id=admin_user.id, assistant_id=bygg
    )
    insight_session = await _insert_session(
        session, name="insight", user_id=admin_user.id, assistant_id=bygg
    )
    other_session = await _insert_session(
        session, name="other", user_id=admin_user.id, assistant_id=other
    )
    gc_session = await _insert_session(
        session, name="gc", user_id=admin_user.id, group_chat_id=group_chat
    )

    q = dict(tenant_id=tenant_id, assistant_id=bygg)
    s1_q1 = await _insert_question(
        session,
        session_id=s1,
        text="Hur ansöker jag om bygglov?",
        at=utc(2026, 9, 7, 10, 0),
        **q,
    )
    s1_q2 = await _insert_question(
        session, session_id=s1, text="Vad kostar det?", at=utc(2026, 9, 7, 10, 5), **q
    )
    s2_q1 = await _insert_question(
        session,
        session_id=s2,
        text="hur ansöker jag om bygglov",
        at=utc(2026, 9, 7, 22, 30),
        **q,
    )
    s3_q1 = await _insert_question(
        session, session_id=s3, text="Öppettider?", at=utc(2026, 9, 6, 8, 0), **q
    )
    s4_q1 = uuid4()
    await session.execute(
        sa.insert(Questions).values(
            id=s4_q1,
            tenant_id=tenant_id,
            session_id=s4,
            assistant_id=bygg,
            question="Kan ni hjälpa mig med deklarationen?",
            answer="Jag kan tyvärr inte hjälpa till med deklarationen.",
            num_tokens_question=1,
            num_tokens_answer=1,
            created_at=utc(2026, 9, 7, 15, 0),
            updated_at=utc(2026, 9, 7, 15, 0),
        )
    )
    for minute, text in (
        (0, "Var parkerar jag?"),
        (2, "Var parkerar jag i centrum?"),
        (4, "var parkerar jag??"),
    ):
        await _insert_question(
            session, session_id=s5, text=text, at=utc(2026, 9, 7, 16, minute), **q
        )
    await _insert_question(
        session,
        session_id=helper_session,
        text="helper question",
        at=utc(2026, 9, 7, 11, 0),
        **q,
    )
    await _insert_question(
        session,
        session_id=insight_session,
        text="insight question",
        at=utc(2026, 9, 7, 12, 0),
        **q,
    )
    await _insert_question(
        session,
        tenant_id=tenant_id,
        assistant_id=other,
        session_id=other_session,
        text="other question",
        at=utc(2026, 9, 7, 13, 0),
    )
    await _insert_question(
        session,
        tenant_id=tenant_id,
        assistant_id=None,
        session_id=gc_session,
        text="gc question",
        at=utc(2026, 9, 7, 14, 0),
    )

    factory = container.helper_assistants_factory()
    await container.helper_run_repo().add(
        factory.create_helper_run(
            tenant_id=tenant_id,
            org_space_id=space_id,
            kind=HelperKind.PROMPT_GUIDE,
            assistant_id=other,
            target_type="assistant",
            target_id=bygg,
            session_id=helper_session,
            actor_user_id=admin_user.id,
        )
    )
    await InsightConversationRepository(session).add(
        tenant_id=tenant_id,
        session_id=insight_session,
        actor_user_id=admin_user.id,
        timezone="Europe/Stockholm",
        assistant_id=bygg,
        completion_model_id=model_id,
    )
    await session.flush()

    return {
        "tenant_id": tenant_id,
        "space_id": space_id,
        "model_id": model_id,
        "bygg": bygg,
        "other": other,
        "group_chat": group_chat,
        "s1": s1,
        "s2": s2,
        "s3": s3,
        "s1_q1": s1_q1,
        "s1_q2": s1_q2,
        "s2_q1": s2_q1,
        "s3_q1": s3_q1,
        "s4": s4,
        "s4_q1": s4_q1,
        "s5": s5,
        "helper_session": helper_session,
        "insight_session": insight_session,
        "other_session": other_session,
        "gc_session": gc_session,
    }


@pytest.fixture
def seed_insights():
    """``await seed_insights(container, admin_user)`` inside a db_container."""
    return _seed_insights
