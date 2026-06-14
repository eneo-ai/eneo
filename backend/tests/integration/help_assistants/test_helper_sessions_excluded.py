"""Critical test #1 — helper sessions are excluded from every session /
conversation / insights / analytics path.

Pins PRD §4 ("one rule, one place"): helper conversations live in the
regular ``sessions`` / ``questions`` tables so streaming, RAG, model
selection, and tool calling all work — but they must never appear in normal
session / conversation / insights / export endpoints. The filter is defined
twice (mirrored, intentionally): ``SessionRepository._exclude_helper_run_sessions``
for queries that issue from ``sessions_repo``, and the module-level
``_exclude_helper_run_sessions`` in ``analysis_repo.py`` for queries that
issue from analysis.

The tests are parametrised over the public methods of both repos and over a
small set of HTTP endpoints. If a future engineer adds a list/aggregate
method that touches ``Sessions``/``Questions`` and forgets to apply the
filter, the relevant parametrised case here fails loud.

Fixture layout: a single tenant with
  * a regular assistant, with one regular session (one question), and
  * a helper assistant + role assignment, with one helper-backed session
    (one question) plus a ``help_assistant_runs`` row pointing at that
    session,
  * a group chat with one regular group-chat session and one synthetic
    helper-backed group-chat session (also pinned by a ``help_assistant_runs``
    row) — needed to exercise the group-chat code paths without changing
    the production data model.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.assistant_table import Assistants
from intric.database.tables.group_chats_table import GroupChatsTable
from intric.database.tables.questions_table import Questions
from intric.database.tables.sessions_table import Sessions
from intric.database.tables.spaces_table import Spaces
from intric.help_assistants.domain.helper_kind import HelperKind


async def _get_org_space(
    session: sa.ext.asyncio.AsyncSession, *, tenant_id: UUID
) -> UUID:
    row = await session.scalar(
        sa.select(Spaces.id).where(
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )
    assert row is not None, "Expected an org-space seeded by add_tenant_user"
    return row


async def _insert_assistant(
    session: sa.ext.asyncio.AsyncSession,
    *,
    owner_user_id: UUID,
    space_id: UUID,
    name: str | None = None,
) -> UUID:
    assistant_id = uuid4()
    await session.execute(
        sa.insert(Assistants).values(
            id=assistant_id,
            name=name or f"assistant-{assistant_id.hex[:8]}",
            user_id=owner_user_id,
            space_id=space_id,
            completion_model_id=None,
            logging_enabled=False,
            is_default=False,
            published=False,
        )
    )
    return assistant_id


async def _insert_group_chat(
    session: sa.ext.asyncio.AsyncSession,
    *,
    owner_user_id: UUID,
    space_id: UUID,
) -> UUID:
    group_chat_id = uuid4()
    await session.execute(
        sa.insert(GroupChatsTable).values(
            id=group_chat_id,
            name=f"gc-{group_chat_id.hex[:8]}",
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
    session: sa.ext.asyncio.AsyncSession,
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
    session: sa.ext.asyncio.AsyncSession,
    *,
    tenant_id: UUID,
    session_id: UUID,
    assistant_id: UUID | None,
    text: str,
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
        )
    )
    return question_id


async def _record_helper_run(
    container,
    *,
    tenant_id: UUID,
    org_space_id: UUID,
    helper_assistant_id: UUID,
    target_id: UUID,
    session_id: UUID,
    actor_user_id: UUID,
) -> None:
    repo = container.helper_run_repo()
    factory = container.helper_assistants_factory()
    await repo.add(
        factory.create_helper_run(
            tenant_id=tenant_id,
            org_space_id=org_space_id,
            kind=HelperKind.PROMPT_GUIDE,
            assistant_id=helper_assistant_id,
            target_type="assistant",
            target_id=target_id,
            session_id=session_id,
            actor_user_id=actor_user_id,
        )
    )


async def _assign_helper_role(
    container,
    *,
    org_space_id: UUID,
    assistant_id: UUID,
    actor_user_id: UUID,
) -> None:
    role_repo = container.org_space_assistant_role_repo()
    factory = container.helper_assistants_factory()
    await role_repo.add(
        factory.create_role_assignment(
            org_space_id=org_space_id,
            kind=HelperKind.PROMPT_GUIDE,
            assistant_id=assistant_id,
            created_by_user_id=actor_user_id,
        )
    )


async def _seed(container, admin_user) -> dict[str, UUID]:
    """Build the canonical helper-vs-regular fixture for this test module."""
    session = container.session()
    space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)

    regular_assistant = await _insert_assistant(
        session,
        owner_user_id=admin_user.id,
        space_id=space_id,
        name="regular-assistant",
    )
    helper_assistant = await _insert_assistant(
        session,
        owner_user_id=admin_user.id,
        space_id=space_id,
        name="helper-assistant",
    )
    await _assign_helper_role(
        container,
        org_space_id=space_id,
        assistant_id=helper_assistant,
        actor_user_id=admin_user.id,
    )

    regular_session = await _insert_session(
        session,
        name="regular-session",
        user_id=admin_user.id,
        assistant_id=regular_assistant,
    )
    helper_session = await _insert_session(
        session,
        name="helper-session",
        user_id=admin_user.id,
        assistant_id=helper_assistant,
    )

    regular_question = await _insert_question(
        session,
        tenant_id=admin_user.tenant_id,
        session_id=regular_session,
        assistant_id=regular_assistant,
        text="regular question",
    )
    helper_question = await _insert_question(
        session,
        tenant_id=admin_user.tenant_id,
        session_id=helper_session,
        assistant_id=helper_assistant,
        text="helper question",
    )

    await _record_helper_run(
        container,
        tenant_id=admin_user.tenant_id,
        org_space_id=space_id,
        helper_assistant_id=helper_assistant,
        target_id=regular_assistant,
        session_id=helper_session,
        actor_user_id=admin_user.id,
    )

    # Group-chat parallel: a real group chat with one regular session and one
    # synthetic helper-tagged session. Real helpers don't use group chats, but
    # we still want to prove the filter works on every group-chat code path,
    # so the helper-tagging is constructed explicitly here.
    group_chat = await _insert_group_chat(
        session, owner_user_id=admin_user.id, space_id=space_id
    )
    regular_gc_session = await _insert_session(
        session,
        name="regular-gc-session",
        user_id=admin_user.id,
        group_chat_id=group_chat,
    )
    helper_gc_session = await _insert_session(
        session,
        name="helper-gc-session",
        user_id=admin_user.id,
        group_chat_id=group_chat,
    )
    await _insert_question(
        session,
        tenant_id=admin_user.tenant_id,
        session_id=regular_gc_session,
        assistant_id=None,
        text="regular gc question",
    )
    await _insert_question(
        session,
        tenant_id=admin_user.tenant_id,
        session_id=helper_gc_session,
        assistant_id=None,
        text="helper gc question",
    )
    await _record_helper_run(
        container,
        tenant_id=admin_user.tenant_id,
        org_space_id=space_id,
        helper_assistant_id=helper_assistant,
        target_id=regular_assistant,
        session_id=helper_gc_session,
        actor_user_id=admin_user.id,
    )

    await session.flush()

    return {
        "tenant_id": admin_user.tenant_id,
        "regular_assistant": regular_assistant,
        "helper_assistant": helper_assistant,
        "regular_session": regular_session,
        "helper_session": helper_session,
        "regular_question": regular_question,
        "helper_question": helper_question,
        "group_chat": group_chat,
        "regular_gc_session": regular_gc_session,
        "helper_gc_session": helper_gc_session,
    }


# ---------------------------------------------------------------------------
# sessions_repo coverage
# ---------------------------------------------------------------------------


def _ids(items) -> set[UUID]:
    return {getattr(item, "id", item) for item in items}


SESSIONS_REPO_CASES: list[tuple[str, Callable[..., Awaitable[set[UUID]]], str]] = [
    (
        "get_returns_none_for_helper",
        # Direct lookup of a helper session by UUID must return None.
        lambda repo, s: repo.get(s["helper_session"]),
        "single",
    ),
    (
        "get_by_assistant_helper_returns_empty",
        # Listing by the helper assistant must return no sessions.
        lambda repo, s: repo.get_by_assistant(assistant_id=s["helper_assistant"]),
        "list_then_total",
    ),
    (
        "get_by_assistant_with_tenant_excludes_helper",
        lambda repo, s: repo.get_by_assistant(
            assistant_id=s["helper_assistant"], tenant_id=s["tenant_id"]
        ),
        "list_then_total",
    ),
    (
        "get_metadata_by_assistant_helper_returns_empty",
        lambda repo, s: repo.get_metadata_by_assistant(
            assistant_id=s["helper_assistant"]
        ),
        "list_then_total",
    ),
    (
        "get_metadata_by_assistant_with_tenant_excludes_helper",
        lambda repo, s: repo.get_metadata_by_assistant(
            assistant_id=s["helper_assistant"], tenant_id=s["tenant_id"]
        ),
        "list_then_total",
    ),
    (
        "get_by_group_chat_excludes_helper",
        lambda repo, s: repo.get_by_group_chat(group_chat_id=s["group_chat"]),
        "list_then_total",
    ),
    (
        "get_by_group_chat_with_tenant_excludes_helper",
        lambda repo, s: repo.get_by_group_chat(
            group_chat_id=s["group_chat"], tenant_id=s["tenant_id"]
        ),
        "list_then_total",
    ),
    (
        "get_metadata_by_group_chat_excludes_helper",
        lambda repo, s: repo.get_metadata_by_group_chat(group_chat_id=s["group_chat"]),
        "list_then_total",
    ),
    (
        "get_metadata_by_group_chat_with_tenant_excludes_helper",
        lambda repo, s: repo.get_metadata_by_group_chat(
            group_chat_id=s["group_chat"], tenant_id=s["tenant_id"]
        ),
        "list_then_total",
    ),
    (
        "get_by_tenant_excludes_helper",
        lambda repo, s: repo.get_by_tenant(tenant_id=s["tenant_id"]),
        "list",
    ),
]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "case_id,call,shape",
    SESSIONS_REPO_CASES,
    ids=[case[0] for case in SESSIONS_REPO_CASES],
)
async def test_sessions_repo_excludes_helper(
    db_container, admin_user, case_id, call, shape
):
    async with db_container() as container:
        setup = await _seed(container, admin_user)
        repo = container.session_repo()

        result = await call(repo, setup)

        if shape == "single":
            assert result is None, f"{case_id}: helper session must not be returned"
        elif shape == "list":
            ids = _ids(result)
            assert setup["helper_session"] not in ids, (
                f"{case_id}: helper session leaked"
            )
            assert setup["helper_gc_session"] not in ids, (
                f"{case_id}: helper group-chat session leaked"
            )
        elif shape == "list_then_total":
            items, total = result
            ids = _ids(items)
            assert setup["helper_session"] not in ids, (
                f"{case_id}: helper session leaked"
            )
            assert setup["helper_gc_session"] not in ids, (
                f"{case_id}: helper group-chat session leaked"
            )
            # total_count must agree with the filtered list. If the count
            # query forgets the filter, ``total`` would be larger than ``items``
            # for a small fixture and this assertion would fail.
            assert total == len(items), (
                f"{case_id}: count disagrees with filtered list "
                f"(total={total}, len(items)={len(items)})"
            )
        else:
            raise AssertionError(f"unknown shape {shape}")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sessions_repo_returns_regular_sessions(db_container, admin_user):
    """Baseline: the filter does not over-exclude. Regular sessions still
    surface in every method, so the helper-only exclusion above is a real
    signal, not vacuous truth."""
    async with db_container() as container:
        setup = await _seed(container, admin_user)
        repo = container.session_repo()

        assert (await repo.get(setup["regular_session"])) is not None

        sessions, total = await repo.get_by_assistant(
            assistant_id=setup["regular_assistant"]
        )
        assert setup["regular_session"] in _ids(sessions)
        assert total >= 1

        sessions, total = await repo.get_by_group_chat(
            group_chat_id=setup["group_chat"]
        )
        assert setup["regular_gc_session"] in _ids(sessions)
        assert total >= 1

        all_for_tenant = await repo.get_by_tenant(tenant_id=setup["tenant_id"])
        ids = _ids(all_for_tenant)
        assert setup["regular_session"] in ids
        assert setup["regular_gc_session"] in ids


# ---------------------------------------------------------------------------
# analysis_repo coverage
# ---------------------------------------------------------------------------


ANALYSIS_REPO_CASES: list[
    tuple[
        str,
        Callable[..., Awaitable[object]],
        Callable[[object, dict[str, UUID]], None],
    ]
] = [
    (
        "get_session_count_excludes_helper",
        lambda repo, s: repo.get_session_count(tenant_id=s["tenant_id"]),
        # Two regular sessions (assistant + group-chat) — helpers must be hidden.
        lambda result, s: _assert_eq(result, 2, "get_session_count"),
    ),
    (
        "get_question_count_excludes_helper",
        lambda repo, s: repo.get_question_count(tenant_id=s["tenant_id"]),
        lambda result, s: _assert_eq(result, 2, "get_question_count"),
    ),
    (
        "get_tenant_counts_excludes_helper",
        lambda repo, s: repo.get_tenant_counts(tenant_id=s["tenant_id"]),
        lambda result, s: _assert_tenant_counts(result, s),
    ),
    (
        "get_assistant_sessions_since_helper_returns_empty",
        lambda repo, s: repo.get_assistant_sessions_since(
            assistant_id=s["helper_assistant"], tenant_id=s["tenant_id"]
        ),
        lambda result, s: _assert_empty_sessions(
            result, "get_assistant_sessions_since"
        ),
    ),
    (
        "get_group_chat_sessions_since_excludes_helper",
        lambda repo, s: repo.get_group_chat_sessions_since(
            group_chat_id=s["group_chat"], tenant_id=s["tenant_id"]
        ),
        lambda result, s: _assert_no_helper_gc_session(result, s),
    ),
    (
        "get_assistant_question_texts_since_helper_returns_empty",
        lambda repo, s: repo.get_assistant_question_texts_since(
            assistant_id=s["helper_assistant"],
            from_date=_FROM,
            to_date=_TO,
            include_followups=True,
            tenant_id=s["tenant_id"],
        ),
        lambda result, s: _assert_eq(result, [], "get_assistant_question_texts_since"),
    ),
    (
        "get_group_chat_question_texts_since_excludes_helper",
        lambda repo, s: repo.get_group_chat_question_texts_since(
            group_chat_id=s["group_chat"],
            from_date=_FROM,
            to_date=_TO,
            include_followups=True,
            tenant_id=s["tenant_id"],
        ),
        lambda result, s: _assert_only_regular_gc_question_text(result, s),
    ),
    (
        "get_assistant_question_history_page_helper_returns_empty",
        lambda repo, s: repo.get_assistant_question_history_page(
            assistant_id=s["helper_assistant"],
            from_date=_FROM,
            to_date=_TO,
            include_followups=True,
            tenant_id=s["tenant_id"],
            limit=50,
        ),
        lambda result, s: _assert_empty_history_page(result),
    ),
    (
        "get_assistant_conversation_counts_helper_zero",
        lambda repo, s: repo.get_assistant_conversation_counts(
            assistant_id=s["helper_assistant"], tenant_id=s["tenant_id"]
        ),
        lambda result, s: _assert_eq(
            result, (0, 0), "get_assistant_conversation_counts"
        ),
    ),
    (
        "count_assistant_questions_since_helper_zero",
        lambda repo, s: repo.count_assistant_questions_since(
            assistant_id=s["helper_assistant"],
            from_date=_FROM,
            to_date=_TO,
            tenant_id=s["tenant_id"],
        ),
        lambda result, s: _assert_eq(result, 0, "count_assistant_questions_since"),
    ),
    (
        "get_session_metadata_for_tenant_excludes_helper",
        lambda repo, s: repo.get_session_metadata_for_tenant(tenant_id=s["tenant_id"]),
        lambda result, s: _assert_no_helper_in_session_metadata(result, s),
    ),
    (
        "get_question_metadata_for_tenant_excludes_helper",
        lambda repo, s: repo.get_question_metadata_for_tenant(tenant_id=s["tenant_id"]),
        lambda result, s: _assert_no_helper_in_question_metadata(result, s),
    ),
    (
        "get_session_counts_by_hour_for_tenant_excludes_helper",
        lambda repo, s: repo.get_session_counts_by_hour_for_tenant(
            tenant_id=s["tenant_id"]
        ),
        lambda result, s: _assert_total_buckets(result, 2, "session bucket"),
    ),
    (
        "get_question_counts_by_hour_for_tenant_excludes_helper",
        lambda repo, s: repo.get_question_counts_by_hour_for_tenant(
            tenant_id=s["tenant_id"]
        ),
        lambda result, s: _assert_total_buckets(result, 2, "question bucket"),
    ),
    (
        "get_group_chat_conversation_counts_excludes_helper",
        lambda repo, s: repo.get_group_chat_conversation_counts(
            group_chat_id=s["group_chat"], tenant_id=s["tenant_id"]
        ),
        lambda result, s: _assert_eq(
            result, (1, 1), "get_group_chat_conversation_counts"
        ),
    ),
    (
        "count_group_chat_questions_since_excludes_helper",
        lambda repo, s: repo.count_group_chat_questions_since(
            group_chat_id=s["group_chat"],
            from_date=_FROM,
            to_date=_TO,
            tenant_id=s["tenant_id"],
        ),
        lambda result, s: _assert_eq(result, 1, "count_group_chat_questions_since"),
    ),
    (
        "get_active_user_count_for_tenant_excludes_helper_only_users",
        # admin_user is the only user; they have regular sessions, so still 1.
        # The point is that the count doesn't double-count via the helper row.
        lambda repo, s: repo.get_active_user_count_for_tenant(tenant_id=s["tenant_id"]),
        lambda result, s: _assert_eq(result, 1, "get_active_user_count_for_tenant"),
    ),
]


_FROM = datetime(2000, 1, 1, tzinfo=timezone.utc)
_TO = datetime.now(timezone.utc) + timedelta(days=365)


def _assert_eq(actual, expected, name: str) -> None:
    assert actual == expected, f"{name}: expected {expected!r}, got {actual!r}"


def _assert_tenant_counts(result, s) -> None:
    assistants, sessions, questions = result
    # Two assistants exist; we don't gate assistants in this filter (step 012
    # owns that), but sessions/questions must hide helper-backed rows.
    assert assistants >= 2
    assert sessions == 2, f"get_tenant_counts session_count leaked helper: {sessions}"
    assert questions == 2, (
        f"get_tenant_counts question_count leaked helper: {questions}"
    )


def _assert_empty_sessions(result, name: str) -> None:
    assert result == [], f"{name}: expected empty, got {result!r}"


def _assert_no_helper_gc_session(result, s) -> None:
    ids = {row.id for row in result}
    assert s["helper_gc_session"] not in ids, "group_chat sessions leaked helper"
    assert s["regular_gc_session"] in ids


def _assert_only_regular_gc_question_text(result, s) -> None:
    texts = {row.question for row in result}
    assert "helper gc question" not in texts
    assert "regular gc question" in texts


def _assert_empty_history_page(result) -> None:
    items, total_count, has_more = result
    assert items == []
    assert total_count == 0
    assert has_more is False


def _assert_no_helper_in_session_metadata(result, s) -> None:
    ids = {row.id for row in result}
    assert s["helper_session"] not in ids
    assert s["helper_gc_session"] not in ids
    assert s["regular_session"] in ids
    assert s["regular_gc_session"] in ids


def _assert_no_helper_in_question_metadata(result, s) -> None:
    session_ids = {row.session_id for row in result}
    assert s["helper_session"] not in session_ids
    assert s["helper_gc_session"] not in session_ids
    assert s["regular_session"] in session_ids
    assert s["regular_gc_session"] in session_ids


def _assert_total_buckets(result, expected_total: int, name: str) -> None:
    total = sum(row.total for row in result)
    assert total == expected_total, (
        f"{name}: expected total {expected_total}, got {total}"
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "case_id,call,assertion",
    ANALYSIS_REPO_CASES,
    ids=[case[0] for case in ANALYSIS_REPO_CASES],
)
async def test_analysis_repo_excludes_helper(
    db_container, admin_user, case_id, call, assertion
):
    async with db_container() as container:
        setup = await _seed(container, admin_user)
        repo = container.analysis_repo()

        result = await call(repo, setup)
        assertion(result, setup)


# ---------------------------------------------------------------------------
# HTTP endpoint coverage (sanity check)
# ---------------------------------------------------------------------------

ANALYSIS_HTTP_CASES = [
    ("/api/v1/analysis/counts/", "sessions", 2),
    ("/api/v1/analysis/counts/", "questions", 2),
]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("path,field,expected", ANALYSIS_HTTP_CASES)
async def test_analysis_http_endpoints_exclude_helper(
    db_container,
    admin_user,
    client,
    patch_auth_service_jwt,
    path,
    field,
    expected,
):
    """End-to-end check: a representative analysis endpoint hides helpers.

    The repo-level tests above are the exhaustive coverage; this is the
    integration sanity check that the wiring all the way through the
    container respects the filter.
    """
    async with db_container() as container:
        await _seed(container, admin_user)
        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(admin_user)

    response = await client.get(path, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload[field] == expected, (
        f"{path}: {field}={payload[field]} (expected {expected}; helper leaked)"
    )
