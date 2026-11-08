"""A copy of another conversation's content is unreadable once a source goes.

A copy session registers an edge to each source question. From the moment a
source deletion commits, whichever path removed it, every read that returns
conversation content refuses the copy, with no retention task running. The
typed refusal comes only after the caller proved ownership and current access
to the chat partner; anyone else gets today's refusal.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.util import await_only

from eneo.assistants.assistant_service import AssistantService
from eneo.data_retention.derivations import (
    DerivationRegistrationError,
    DerivedSourceRemovedError,
    register_derivations,
)
from eneo.database.database import sessionmanager
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.retention_tables import ContentDerivations
from eneo.database.tables.sessions_table import Sessions
from eneo.main.exceptions import ErrorCodes, NotFoundException, UnauthorizedException
from eneo.main.models import ModelId
from eneo.users.user import UserAdd, UserInDB, UserState
from tests.integration.data_retention.copy_support import (
    REMOVALS,
    Copy,
    Removal,
    auth,
    make_copy,
    remove_by_user,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def owner_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.fixture
async def other_user_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        other = await container.user_repo().add(
            UserAdd(
                email=f"copy-other-{uuid4().hex[:8]}@example.com",
                username=f"copy_other_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id) for role in admin_user.roles],
            )
        )
        return container.auth_service().create_access_token_for_user(other)


@pytest.fixture
async def copy(client: AsyncClient, db_container, admin_user, owner_token) -> Copy:
    return await make_copy(client, db_container, admin_user, owner_token)


def _assert_removed_source(response) -> None:
    assert response.status_code == 410, response.text
    body = response.json()
    assert body["code"] == "derived_source_removed"
    assert body["eneo_error_code"] == ErrorCodes.DERIVED_SOURCE_REMOVED.value


async def _listed(client: AsyncClient, token: str, copy: Copy) -> tuple[set[str], int]:
    listed = await client.get(
        f"/api/v1/conversations/?assistant_id={copy.copy_assistant}",
        headers=auth(token),
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    return {item["id"] for item in body["items"]}, body["total_count"]


async def _recent(client: AsyncClient, token: str) -> set[str]:
    recent = await client.get("/api/v1/conversations/recent/", headers=auth(token))
    assert recent.status_code == 200, recent.text
    return {item["id"] for item in recent.json()["items"]}


async def test_a_copy_reads_like_any_conversation_while_its_source_exists(
    client: AsyncClient, owner_token: str, copy: Copy
):
    """Mutant: the validity check refuses every copy, not only invalid ones."""
    detail = await client.get(
        f"/api/v1/conversations/{copy.copy_session}/", headers=auth(owner_token)
    )

    assert detail.status_code == 200, detail.text
    assert await _listed(client, owner_token, copy) == ({str(copy.copy_session)}, 1)
    assert str(copy.copy_session) in await _recent(client, owner_token)


@pytest.mark.parametrize("removal", REMOVALS.values(), ids=REMOVALS.keys())
async def test_a_removed_source_makes_the_copy_unreadable_at_once(
    client: AsyncClient,
    owner_token: str,
    copy: Copy,
    retention_session: AsyncSession,
    removal: Removal,
):
    """Mutants: a read path skips the validity check (detail, tool result,
    title, rename, either feedback route, list, its count, recent), the refusal
    is untyped, a refused rename or feedback is stored anyway, or only one
    removal path invalidates the copy. No retention task removes copies here:
    the refusal comes from the read itself."""
    await removal(client, owner_token, copy, retention_session)

    _assert_removed_source(
        await client.get(
            f"/api/v1/conversations/{copy.copy_session}/", headers=auth(owner_token)
        )
    )
    _assert_removed_source(
        await client.get(
            f"/api/v1/conversations/{copy.copy_session}/tool-calls/call-1/result/",
            headers=auth(owner_token),
        )
    )
    _assert_removed_source(
        await client.post(
            f"/api/v1/conversations/{copy.copy_session}/title/",
            headers=auth(owner_token),
        )
    )
    _assert_removed_source(
        await client.patch(
            f"/api/v1/conversations/{copy.copy_session}/name/",
            json={"name": "renamed"},
            headers=auth(owner_token),
        )
    )
    _assert_removed_source(
        await client.post(
            f"/api/v1/conversations/{copy.copy_session}/feedback/",
            json={"value": 1, "text": "kept"},
            headers=auth(owner_token),
        )
    )
    _assert_removed_source(
        await client.post(
            f"/api/v1/assistants/{copy.copy_assistant}/sessions/"
            f"{copy.copy_session}/feedback/",
            json={"value": -1},
            headers=auth(owner_token),
        )
    )
    assert await _listed(client, owner_token, copy) == (set(), 0)
    assert str(copy.copy_session) not in await _recent(client, owner_token)
    # The copy's rows are still there, unchanged: only the read refuses them.
    stored = (
        await retention_session.execute(
            sa.select(Sessions.name, Sessions.feedback_value).where(
                Sessions.id == copy.copy_session
            )
        )
    ).one()
    assert tuple(stored) == ("conversation", None)


async def test_a_source_removed_while_the_turns_load_hides_them(
    db_container, copy: Copy
):
    """Mutant: the statement that loads a conversation's turns skips the copy
    check, so a source removed after the session row was read still shows
    the copy's turns. The removal commits between the two statements."""
    removed: list[str] = []

    async def remove_source() -> None:
        async with sessionmanager.session() as other, other.begin():
            await other.execute(
                sa.delete(Questions).where(Questions.id == copy.source_question)
            )

    def between_statements(_conn, _cursor, statement: str, *_: object) -> None:
        if (
            not removed
            and "FROM questions \nWHERE questions.session_id IN" in statement
        ):
            removed.append(statement)
            await_only(remove_source())

    async with db_container() as container:
        bind = container.session().sync_session.bind
        assert bind is not None
        sa.event.listen(bind.engine, "before_cursor_execute", between_statements)
        try:
            loaded = await container.session_repo().get(copy.copy_session)
        finally:
            sa.event.remove(bind.engine, "before_cursor_execute", between_statements)

    assert removed, "the turns were not loaded in a statement of their own"
    assert loaded is not None
    assert loaded.questions == []


async def test_another_principal_learns_nothing_about_a_removed_source(
    client: AsyncClient,
    owner_token: str,
    other_user_token: str,
    copy: Copy,
    retention_session: AsyncSession,
):
    """Mutant: the removal status is checked before ownership, so another
    principal can tell a copy with a removed source from any other session."""
    before = await client.get(
        f"/api/v1/conversations/{copy.copy_session}/", headers=auth(other_user_token)
    )
    await remove_by_user(client, owner_token, copy, retention_session)
    after = await client.get(
        f"/api/v1/conversations/{copy.copy_session}/", headers=auth(other_user_token)
    )
    unknown = await client.get(
        f"/api/v1/conversations/{uuid4()}/", headers=auth(owner_token)
    )

    assert before.status_code == after.status_code == 403
    assert before.json()["message"] == after.json()["message"]
    assert unknown.status_code == 404


async def test_an_owner_without_partner_access_gets_the_authorization_refusal(
    client: AsyncClient,
    owner_token: str,
    copy: Copy,
    retention_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Mutant: ownership alone reveals the removal status, although the
    owner's access to the chat partner was revoked."""
    await remove_by_user(client, owner_token, copy, retention_session)
    original = AssistantService.get_assistant

    async def revoked(self: AssistantService, id: UUID, *args, **kwargs):
        if id == copy.copy_assistant:
            raise UnauthorizedException("Access to this assistant was revoked")
        return await original(self, id, *args, **kwargs)

    monkeypatch.setattr(AssistantService, "get_assistant", revoked)
    detail = await client.get(
        f"/api/v1/conversations/{copy.copy_session}/", headers=auth(owner_token)
    )

    assert detail.status_code == 403, detail.text
    assert detail.json().get("code") != "derived_source_removed"


async def test_follow_ups_and_other_content_readers_refuse_the_copy(
    client: AsyncClient,
    db_container,
    owner_token: str,
    admin_user: UserInDB,
    copy: Copy,
    retention_session: AsyncSession,
):
    """Mutants: a follow-up rebuilds its history from the copy (the replay
    reads through get_session_by_uuid), or the helper run, export and
    question reads return the copy's turns."""
    await remove_by_user(client, owner_token, copy, retention_session)

    async with db_container() as container:
        with pytest.raises(NotFoundException):
            await container.session_service().get_session_by_uuid(copy.copy_session)
        sessions = container.session_repo()
        assert (
            await sessions.get_for_helper_run(copy.copy_session, admin_user.tenant_id)
            is None
        )
        exported = await sessions.get_by_tenant(admin_user.tenant_id)
        assert copy.copy_session not in {session.id for session in exported}
        questions = container.question_repo()
        for question_id in copy.copy_questions:
            assert (
                await questions.get_for_tenant(
                    id=question_id, tenant_id=admin_user.tenant_id
                )
                is None
            )
            assert (
                await questions.get_with_skill_activation(
                    id=question_id, tenant_id=admin_user.tenant_id
                )
                is None
            )
        window = (
            datetime.now(timezone.utc) - timedelta(days=1),
            datetime.now(timezone.utc) + timedelta(days=1),
        )
        exported_questions = await questions.get_by_tenant(
            tenant_id=admin_user.tenant_id, start_date=window[0], end_date=window[1]
        )
        assert set(copy.copy_questions).isdisjoint(
            question.id for question in exported_questions
        )


async def test_insight_reads_refuse_the_copy_after_their_access_check(
    client: AsyncClient,
    db_container,
    owner_token: str,
    admin_user: UserInDB,
    copy: Copy,
    retention_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Mutants: an insight read returns a copy's turns, fails with an
    assertion instead of a refusal, or tells a caller without insight access
    that a source was removed."""
    from eneo.analysis.analysis_service import AnalysisService

    await remove_by_user(client, owner_token, copy, retention_session)
    allowed: list[bool] = [True]

    async def access(self: AnalysisService, **_: object) -> None:
        if not allowed[0]:
            raise UnauthorizedException("Insights are not enabled for this assistant")

    monkeypatch.setattr(AnalysisService, "_check_insight_access", access)
    async with db_container() as container:
        insights = container.analysis_service()
        with pytest.raises(DerivedSourceRemovedError):
            await insights.get_insight_session(session_id=copy.copy_session)
        with pytest.raises(DerivedSourceRemovedError):
            await insights.get_message_for_insights(message_id=copy.copy_questions[0])
        with pytest.raises(NotFoundException):
            await insights.get_insight_session(session_id=uuid4())
        allowed[0] = False
        with pytest.raises(UnauthorizedException):
            await insights.get_insight_session(session_id=copy.copy_session)
        with pytest.raises(NotFoundException):
            await insights.get_message_for_insights(message_id=copy.copy_questions[0])
        since = datetime.now(timezone.utc) - timedelta(days=1)
        until = datetime.now(timezone.utc) + timedelta(days=1)
        repository = container.analysis_repo()
        sessions = await repository.get_assistant_sessions_since(
            assistant_id=copy.copy_assistant,
            from_date=since,
            to_date=until,
            tenant_id=admin_user.tenant_id,
        )
        assert copy.copy_session not in {session.id for session in sessions}


async def test_registration_needs_a_committed_session(
    db_container, admin_user: UserInDB, copy: Copy
):
    """Mutants: an edge is written against an uncommitted or deleted session,
    so a producer would release content whose provenance is lost; a retry
    duplicates edges; the call returns before the edges are visible."""
    async with sessionmanager.session() as open_transaction, open_transaction.begin():
        uncommitted = Sessions(user_id=admin_user.id, name="not yet committed")
        open_transaction.add(uncommitted)
        await open_transaction.flush()
        with pytest.raises(DerivationRegistrationError):
            await register_derivations(
                copy_session_id=uncommitted.id,
                source_question_ids=[copy.source_question],
            )
        await open_transaction.rollback()
    with pytest.raises(DerivationRegistrationError):
        await register_derivations(
            copy_session_id=uuid4(), source_question_ids=[copy.source_question]
        )

    await register_derivations(
        copy_session_id=copy.copy_session,
        source_question_ids=[copy.source_question, copy.source_question],
    )

    async with sessionmanager.session() as reader, reader.begin():
        edges = (
            await reader.execute(
                sa.select(ContentDerivations.source_question_id).where(
                    ContentDerivations.copy_session_id == copy.copy_session
                )
            )
        ).scalars()
        assert list(edges) == [copy.source_question]
