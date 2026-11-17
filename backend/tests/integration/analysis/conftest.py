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

``seed_sources`` adds conversations of the other sources to the same
assistant, plus ratings and a hidden assistant:
  * api (service API key): "Status för ärende 123?" 2026-09-07 09:00,
        follow-up "Och ärende 124?" 09:10
  * widget_1 (website visitor): "När öppnar simhallen?" 2026-09-07 11:30,
        answered with an admission of not knowing; the visitor voted the
        conversation bad with the comment "Fel svar" (2026-09-07 12:00)
  * widget_2: "Var kan jag parkera?" 2026-09-06 12:00, conversation voted
        good without a comment (2026-09-06 13:00)
  * widget_old: "Har ni wifi?" 2026-09-05 08:00 (the period before)
  * answer ratings: s1_q1 good (2026-09-07 10:01), s1_q2 bad with the comment
        "Saknar avgiften" (10:06), api_q1 bad (09:01)
  * s3 conversation voted good (2026-09-06 09:00)
  * a hidden assistant with no conversations

``seed_quality`` adds knowledge and tool calls to ``seed_sources``; the
assistant answers in tool mode:
  * collections "Bygglov" and "Taxor", both attached to the assistant, and the
    group chat gets the assistant as its member
  * Bygglov's one document in two versions: v1 superseded by a refresh, v2
    active
  * s1_q1 cites v1 (injected, score 0.8); s2_q1 searched and cites v2 through
    the knowledge tool (score 0.7); s1_q2's knowledge search found nothing;
    s3_q1 cites a passage of a removed document (score 0.1); Taxor is never
    cited
  * tool calls: s1_q1 a web search; s4_q1 a failed Grounding call; widget_1_q1
    a denied Grounding call; s5's first question a Skill activation
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.analysis.insight_conversation_repo import InsightConversationRepository
from eneo.authentication.api_key_v2_repo import ApiKeysV2Repository
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.assistant_table import Assistants, AssistantsGroups
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.group_chats_table import (
    GroupChatsAssistantsMapping,
    GroupChatsTable,
)
from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.database.tables.mcp_tool_references_table import McpToolReference
from eneo.database.tables.questions_table import (
    InfoBlobReferences,
    QuestionFeedback,
    Questions,
)
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import SpacesCompletionModels
from eneo.database.tables.widgets_table import Widgets
from eneo.help_assistants.domain.helper_kind import HelperKind
from eneo.widgets.domain.widget import generate_public_id


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
    answer: str | None = None,
) -> UUID:
    question_id = uuid4()
    await session.execute(
        sa.insert(Questions).values(
            id=question_id,
            tenant_id=tenant_id,
            session_id=session_id,
            assistant_id=assistant_id,
            question=text,
            answer=answer if answer is not None else f"answer to {text}",
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


async def _insert_service_key(session, *, tenant_id: UUID, creator_user_id: UUID):
    principal = await ApiKeysV2Repository(session).create_service_principal(
        tenant_id=tenant_id,
        display_name="Insights test service",
        description=None,
        scope_type="tenant",
        scope_id=None,
        created_by_user_id=creator_user_id,
    )
    key_id = uuid4()
    suffix = uuid4().hex[:8]
    await session.execute(
        sa.insert(ApiKeysV2).values(
            id=key_id,
            tenant_id=tenant_id,
            ownership="service",
            scope_type="tenant",
            permission="read",
            key_type="sk_",
            key_hash=f"hash-{suffix}-{uuid4().hex}",
            hash_version="argon2id-v1",
            key_prefix=f"sk_{suffix}",
            key_suffix=suffix[-4:],
            name=f"svc-{suffix}",
            state="active",
            created_by_user_id=creator_user_id,
            service_principal_id=principal.id,
        )
    )
    return key_id


async def _seed_sources(container, admin_user) -> dict[str, UUID]:
    """``_seed_insights`` plus the other sources, described in the module
    docstring."""
    seed = await _seed_insights(container, admin_user)
    session = container.session()
    tenant_id, bygg = seed["tenant_id"], seed["bygg"]

    key_id = await _insert_service_key(
        session, tenant_id=tenant_id, creator_user_id=admin_user.id
    )
    widget_id = uuid4()
    await session.execute(
        sa.insert(Widgets).values(
            id=widget_id,
            public_id=generate_public_id(),
            tenant_id=tenant_id,
            space_id=seed["space_id"],
            target_type="assistant",
            target_id=bygg,
            name="Webbchatt",
        )
    )
    hidden = await _insert_assistant(
        session,
        owner_user_id=admin_user.id,
        space_id=seed["space_id"],
        name="hidden-helper",
        hidden=True,
    )

    def widget_session(name: str, **values) -> sa.Insert:
        return sa.insert(Sessions).values(
            name=name,
            widget_id=widget_id,
            visitor_id=uuid4(),
            assistant_id=bygg,
            **values,
        )

    api = uuid4()
    await session.execute(
        sa.insert(Sessions).values(
            id=api, name="api", api_key_id=key_id, assistant_id=bygg
        )
    )
    widget_1, widget_2, widget_old = uuid4(), uuid4(), uuid4()
    await session.execute(
        widget_session(
            "widget-1",
            id=widget_1,
            feedback_value=-1,
            feedback_text="Fel svar",
            feedback_set_at=utc(2026, 9, 7, 12, 0),
        )
    )
    await session.execute(
        widget_session(
            "widget-2",
            id=widget_2,
            feedback_value=1,
            feedback_set_at=utc(2026, 9, 6, 13, 0),
        )
    )
    await session.execute(widget_session("widget-old", id=widget_old))
    await session.execute(
        sa.update(Sessions)
        .where(Sessions.id == seed["s3"])
        .values(feedback_value=1, feedback_set_at=utc(2026, 9, 6, 9, 0))
    )

    q = dict(tenant_id=tenant_id, assistant_id=bygg)
    api_q1 = await _insert_question(
        session,
        session_id=api,
        text="Status för ärende 123?",
        at=utc(2026, 9, 7, 9, 0),
        **q,
    )
    await _insert_question(
        session, session_id=api, text="Och ärende 124?", at=utc(2026, 9, 7, 9, 10), **q
    )
    widget_1_q1 = await _insert_question(
        session,
        session_id=widget_1,
        text="När öppnar simhallen?",
        at=utc(2026, 9, 7, 11, 30),
        answer="Jag hittar tyvärr ingen information om simhallen.",
        **q,
    )
    await _insert_question(
        session,
        session_id=widget_2,
        text="Var kan jag parkera?",
        at=utc(2026, 9, 6, 12, 0),
        **q,
    )
    await _insert_question(
        session,
        session_id=widget_old,
        text="Har ni wifi?",
        at=utc(2026, 9, 5, 8, 0),
        **q,
    )

    for question_id, value, text, at, principal in (
        (seed["s1_q1"], 1, None, utc(2026, 9, 7, 10, 1), {"user_id": admin_user.id}),
        (
            seed["s1_q2"],
            -1,
            "Saknar avgiften",
            utc(2026, 9, 7, 10, 6),
            {"user_id": admin_user.id},
        ),
        (api_q1, -1, None, utc(2026, 9, 7, 9, 1), {"api_key_id": key_id}),
    ):
        await session.execute(
            sa.insert(QuestionFeedback).values(
                question_id=question_id,
                value=value,
                text=text,
                created_at=at,
                updated_at=at,
                **principal,
            )
        )
    await session.flush()

    return {
        **seed,
        "api_key": key_id,
        "widget": widget_id,
        "hidden_assistant": hidden,
        "api": api,
        "api_q1": api_q1,
        "widget_1": widget_1,
        "widget_1_q1": widget_1_q1,
        "widget_2": widget_2,
        "widget_old": widget_old,
    }


def _call(server: str, tool: str, **values) -> dict[str, object]:
    return {
        "server_name": server,
        "tool_name": tool,
        "approved": True,
        "result_status": "succeeded",
        **values,
    }


async def _seed_quality(container, admin_user) -> dict[str, UUID]:
    """``_seed_sources`` plus knowledge and tool calls, described in the
    module docstring."""
    seed = await _seed_sources(container, admin_user)
    session = container.session()
    tenant_id, bygg = seed["tenant_id"], seed["bygg"]
    await session.execute(
        sa.update(Assistants).where(Assistants.id == bygg).values(knowledge_mode="tool")
    )
    await session.execute(
        sa.insert(GroupChatsAssistantsMapping).values(
            group_chat_id=seed["group_chat"], assistant_id=bygg
        )
    )
    collections: dict[str, UUID] = {}
    for name in ("Bygglov", "Taxor"):
        collections[name] = uuid4()
        await session.execute(
            sa.insert(CollectionsTable).values(
                id=collections[name],
                name=name,
                size=0,
                user_id=admin_user.id,
                tenant_id=tenant_id,
            )
        )
        await session.execute(
            sa.insert(AssistantsGroups).values(
                assistant_id=bygg, group_id=collections[name]
            )
        )
    document = uuid4()
    versions = {"v1": uuid4(), "v2": uuid4()}
    for version, state in (("v1", "superseded"), ("v2", "active")):
        await session.execute(
            sa.insert(InfoBlobs).values(
                id=versions[version],
                text=f"Bygglov {version}",
                title="Ansök om bygglov",
                size=1,
                source_id=document,
                version_state=state,
                user_id=admin_user.id,
                tenant_id=tenant_id,
                group_id=collections["Bygglov"],
            )
        )
    await session.execute(
        sa.insert(InfoBlobReferences).values(
            question_id=seed["s1_q1"],
            info_blob_id=versions["v1"],
            similarity_score=0.8,
            order=0,
        )
    )
    await session.execute(
        sa.insert(McpToolReference),
        [
            dict(
                question_id=seed["s2_q1"],
                uri=f"eneo://info-blob/{versions['v2']}#chunk-0",
                meta={"score": 0.7},
                order=0,
            ),
            dict(
                question_id=seed["s3_q1"],
                uri=f"eneo://info-blob/{uuid4()}#chunk-0",
                meta={"score": 0.1},
                order=0,
            ),
        ],
    )
    s5_q1 = await session.scalar(
        sa.select(Questions.id)
        .where(Questions.session_id == seed["s5"])
        .order_by(Questions.created_at)
        .limit(1)
    )
    grounding = _call("Grounding", "get_chat_grounding", title="Grundning")
    for question_id, calls in (
        (
            seed["s1_q1"],
            [_call("Webbsök", "search", purpose="web_search", title="Sök på webben")],
        ),
        (
            seed["s2_q1"],
            [
                _call(
                    "knowledge", "search_knowledge", result="1 result(s) for 'bygglov'"
                )
            ],
        ),
        (
            seed["s1_q2"],
            [
                _call(
                    "knowledge",
                    "search_knowledge",
                    is_internal=True,
                    result="No results for 'avgift'.",
                )
            ],
        ),
        (seed["s4_q1"], [{**grounding, "result_status": "failed"}]),
        (
            seed["widget_1_q1"],
            [{**grounding, "approved": False, "result_status": "denied"}],
        ),
        (
            s5_q1,
            [
                _call(
                    "skills",
                    "faktagranskning",
                    mcp_tool_name="eneo_activate_skill",
                    is_internal=True,
                    result_status="completed",
                )
            ],
        ),
    ):
        await session.execute(
            sa.update(Questions)
            .where(Questions.id == question_id)
            .values(tool_calls=calls)
        )
    await session.flush()
    return {
        **seed,
        "bygglov": collections["Bygglov"],
        "taxor": collections["Taxor"],
        "blob_v1": versions["v1"],
        "blob_v2": versions["v2"],
    }


@pytest.fixture
def seed_insights():
    """``await seed_insights(container, admin_user)`` inside a db_container."""
    return _seed_insights


@pytest.fixture
def seed_quality():
    """``await seed_quality(container, admin_user)`` inside a db_container."""
    return _seed_quality


@pytest.fixture
def seed_sources():
    """``await seed_sources(container, admin_user)`` inside a db_container."""
    return _seed_sources
