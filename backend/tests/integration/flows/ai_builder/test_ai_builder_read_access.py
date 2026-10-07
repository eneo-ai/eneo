"""A Builder grant sees a revocation that happened earlier in the same operation.

The operation keeps one database session, and a review reads under a
REPEATABLE READ snapshot that cannot show a later downgrade or removal. Every
grant therefore reads its own fresh access snapshot.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from eneo.authentication.auth_dependencies import ScopeFilter
from eneo.authentication.auth_models import (
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
)
from eneo.database import database as database_module
from eneo.database.database import sessionmanager
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.spaces_table import SpacesUserGroups
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import usergroups_users_table
from eneo.flows import FlowRepository
from eneo.flows.ai_builder.ai_builder_api_models import SendMessageRequest
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderSession,
    SessionStatus,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_flow_review import AIBuilderReviewContext
from eneo.flows.ai_builder.ai_builder_read_access import (
    BuilderReadAccess,
    scope_for_session,
)
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionTurnPreflight,
    SessionTurnPreparationBaseline,
)
from eneo.flows.api.flow_ai_builder_router import (
    audited_evidence_snapshot,
    send_message,
)
from eneo.flows.domain.flow import Flow
from eneo.flows.flow_access_policy import FlowApiAction
from eneo.flows.infrastructure import flow_repo as flow_repo_module
from eneo.main.container.container import Container
from eneo.main.exceptions import NotFoundException, UnauthorizedException
from eneo.users.user import UserGroupInDBRead


async def _seed(
    db_container, space_factory, admin_user, *, editor_group_id: UUID | None = None
) -> tuple[UUID, UUID]:
    """A space the caller edits through a direct role, or through the group
    when one is given, and a flow in it."""
    async with db_container() as container:
        session = container.session()
        space = await space_factory(session, f"Builder grant {uuid4()}")
        if editor_group_id is None:
            await session.execute(
                sa.text(
                    "INSERT INTO spaces_users (space_id, user_id, role) "
                    "VALUES (:space_id, :user_id, 'editor')"
                ),
                {"space_id": str(space.id), "user_id": str(admin_user.id)},
            )
        else:
            session.add(
                SpacesUserGroups(
                    space_id=space.id, user_group_id=editor_group_id, role="editor"
                )
            )
            await session.flush()
        flow = await FlowRepository(session=session).create(
            flow=Flow(
                id=None,
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                name=f"Grant flow {uuid4()}",
                description=None,
                created_by_user_id=admin_user.id,
                owner_user_id=admin_user.id,
                published_version=None,
                metadata_json={},
                data_retention_days=None,
                created_at=None,
                updated_at=None,
                steps=[],
            ),
            tenant_id=admin_user.tenant_id,
        )
        return space.id, flow.id


async def _committed(statement: str, **params: object) -> None:
    """Another actor's change, committed outside the operation."""
    async with sessionmanager.session() as session, session.begin():
        await session.execute(sa.text(statement), params)


def _scope(admin_user, space_id: UUID, flow_id: UUID | None):
    session = BuilderSession(
        id=uuid4(),
        tenant_id=admin_user.tenant_id,
        space_id=space_id,
        flow_id=flow_id,
        target_kind=TargetKind.EDIT,
        status=SessionStatus.CHATTING,
        actor_user_id=admin_user.id,
    )
    return session, scope_for_session(session, ScopeFilter())


def _access(container: Container) -> BuilderReadAccess:
    return BuilderReadAccess(
        user=container.user(),
        space_service=container.space_service,
        actor_manager=container.actor_manager(),
    )


@contextmanager
def _statements() -> Iterator[list[str]]:
    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(Engine, "before_cursor_execute", record)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "revocation",
    [
        "UPDATE spaces_users SET role = 'viewer' "
        "WHERE space_id = :space_id AND user_id = :user_id",
        "DELETE FROM spaces_users WHERE space_id = :space_id AND user_id = :user_id",
    ],
    ids=["downgrade", "removal"],
)
async def test_a_revocation_between_two_grants_of_one_operation_refuses_the_second(
    db_container, space_factory, admin_user, revocation
):
    space_id, flow_id = await _seed(db_container, space_factory, admin_user)
    session, scope = _scope(admin_user, space_id, flow_id)

    async with db_container(user=admin_user) as container:
        access = _access(container)
        first = await access.authorize(
            ScopeFilter(),
            action=FlowApiAction.BUILDER_MESSAGE_SEND,
            space_id=space_id,
            session=session,
            require_creator=True,
        )
        assert first.space is not None
        await access.open_grant(scope, FlowApiAction.BUILDER_MESSAGE_SEND)

        await _committed(revocation, space_id=space_id, user_id=admin_user.id)

        with pytest.raises(UnauthorizedException) as refused:
            await access.open_grant(scope, FlowApiAction.BUILDER_MESSAGE_SEND)
        assert getattr(refused.value, "code", None) == "insufficient_space_permission"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_group_membership_removed_between_two_grants_refuses_the_second(
    db_container, space_factory, admin_user
):
    """The caller's group list was loaded with the principal; the grant reads
    the membership edge itself, so a removal in between refuses the next one."""
    async with db_container() as container:
        session = container.session()
        group = UserGroups(
            name=f"grant-editors-{uuid4().hex}", tenant_id=admin_user.tenant_id
        )
        session.add(group)
        await session.flush()
        await session.execute(
            sa.insert(usergroups_users_table).values(
                user_id=admin_user.id, user_group_id=group.id
            )
        )
        group_id, group_name = group.id, group.name
    space_id, flow_id = await _seed(
        db_container, space_factory, admin_user, editor_group_id=group_id
    )
    member = admin_user.model_copy(
        update={
            "user_groups": [
                *admin_user.user_groups,
                UserGroupInDBRead(id=group_id, name=group_name),
            ]
        }
    )
    _, scope = _scope(member, space_id, flow_id)

    async with db_container(user=member) as container:
        access = _access(container)
        await access.open_grant(scope, FlowApiAction.BUILDER_MESSAGE_SEND)

        await _committed(
            "DELETE FROM usergroups_users "
            "WHERE user_id = :user_id AND user_group_id = :group_id",
            user_id=member.id,
            group_id=group_id,
        )
        assert group_id in member.user_groups_ids

        with pytest.raises(UnauthorizedException) as refused:
            await access.open_grant(scope, FlowApiAction.BUILDER_MESSAGE_SEND)
        assert getattr(refused.value, "code", None) == "insufficient_space_permission"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("key_scope", "expected_statements"),
    [
        # The space row, this caller's member rows, group rows, the flow's
        # ownership row.
        (None, 4),
        # ... and the scoped key's resource row in the space.
        (ApiKeyScopeType.ASSISTANT, 5),
        (ApiKeyScopeType.APP, 5),
    ],
    ids=["keyless", "assistant_key", "app_key"],
)
async def test_one_grant_reads_a_bounded_snapshot_without_flow_content(
    db_container, space_factory, admin_user, key_scope, expected_statements
):
    space_id, flow_id = await _seed(db_container, space_factory, admin_user)
    _, scope = _scope(admin_user, space_id, flow_id)
    caller = (
        admin_user
        if key_scope is None
        else _scoped_key(admin_user, scope_type=key_scope, scope_id=uuid4())
    )

    async with db_container(user=caller) as container:
        with _statements() as statements:
            # A key for no resource of this space is refused, after the same
            # reads an accepted key makes.
            with suppress(UnauthorizedException):
                await _access(container).open_grant(
                    scope, FlowApiAction.BUILDER_MESSAGE_SEND
                )

    assert len(statements) == expected_statements, statements
    assert not any("flow_steps" in statement for statement in statements)
    assert not any("metadata_json" in statement for statement in statements)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_refused_grant_parses_no_flow_metadata(
    db_container, space_factory, admin_user, monkeypatch
):
    space_id, flow_id = await _seed(db_container, space_factory, admin_user)
    _, scope = _scope(admin_user, space_id, flow_id)
    parsed: list[object] = []
    monkeypatch.setattr(
        flow_repo_module,
        "flow_metadata_marks_sensitive_or_unreadable",
        lambda metadata: parsed.append(metadata) or False,
    )
    await _committed(
        "UPDATE spaces_users SET role = 'viewer' "
        "WHERE space_id = :space_id AND user_id = :user_id",
        space_id=space_id,
        user_id=admin_user.id,
    )

    async with db_container(user=admin_user) as container:
        with pytest.raises(UnauthorizedException):
            await _access(container).open_grant(
                scope, FlowApiAction.BUILDER_MESSAGE_SEND
            )

    assert parsed == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_grant_inside_an_evidence_snapshot_sees_a_later_revocation(
    db_container, space_factory, admin_user
):
    space_id, flow_id = await _seed(db_container, space_factory, admin_user)
    _, scope = _scope(admin_user, space_id, flow_id)
    async with db_container() as container:
        tenant = container.tenant()

    async with sessionmanager.session() as operation_session:
        container = Container(
            session=providers.Object(operation_session),
            user=providers.Object(admin_user),
            tenant=providers.Object(tenant),
        )
        access = _access(container)

        async def audit_ids() -> set[UUID]:
            async with sessionmanager.session() as reader, reader.begin():
                return set(
                    (
                        await reader.scalars(
                            sa.select(AuditLogTable.id).where(
                                AuditLogTable.tenant_id == admin_user.tenant_id
                            )
                        )
                    ).all()
                )

        before = await audit_ids()
        with pytest.raises(UnauthorizedException) as refused:
            async with audited_evidence_snapshot(
                container, admin_user, evidence_detail="read_access_test"
            ):
                # Pin the snapshot as the evidence reads would.
                pinned_role = await operation_session.scalar(
                    sa.text(
                        "SELECT role FROM spaces_users "
                        "WHERE space_id = :space_id AND user_id = :user_id"
                    ),
                    {"space_id": str(space_id), "user_id": str(admin_user.id)},
                )
                assert pinned_role == "editor"
                await _committed(
                    "DELETE FROM spaces_users "
                    "WHERE space_id = :space_id AND user_id = :user_id",
                    space_id=space_id,
                    user_id=admin_user.id,
                )
                # The snapshot cannot see the removal ...
                assert (
                    await operation_session.scalar(
                        sa.text(
                            "SELECT role FROM spaces_users "
                            "WHERE space_id = :space_id AND user_id = :user_id"
                        ),
                        {"space_id": str(space_id), "user_id": str(admin_user.id)},
                    )
                    == "editor"
                )
                # ... the grant can.
                await access.open_grant(scope, FlowApiAction.BUILDER_REVIEW)
        assert getattr(refused.value, "code", None) == "insufficient_space_permission"
        assert await audit_ids() == before


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_flow_deleted_or_moved_between_grants_is_refused(
    db_container, space_factory, admin_user
):
    space_id, flow_id = await _seed(db_container, space_factory, admin_user)
    other_space_id, _ = await _seed(db_container, space_factory, admin_user)
    _, scope = _scope(admin_user, space_id, flow_id)

    async with db_container(user=admin_user) as container:
        access = _access(container)
        await access.open_grant(scope, FlowApiAction.BUILDER_MESSAGE_SEND)

        await _committed(
            "UPDATE flows SET space_id = :other WHERE id = :flow_id",
            other=other_space_id,
            flow_id=flow_id,
        )
        with pytest.raises(Exception) as moved:
            await access.open_grant(scope, FlowApiAction.BUILDER_MESSAGE_SEND)
        assert getattr(moved.value, "code", None) == "flow_space_mismatch"

        await _committed(
            "UPDATE flows SET deleted_at = now() WHERE id = :flow_id", flow_id=flow_id
        )
        with pytest.raises(NotFoundException):
            await access.open_grant(scope, FlowApiAction.BUILDER_MESSAGE_SEND)


def _scoped_key(admin_user, *, scope_type: ApiKeyScopeType, scope_id: UUID | None):
    return admin_user.model_copy(
        update={
            "active_api_key": ApiKeyV2InDB(
                id=uuid4(),
                ownership=ApiKeyOwnership.USER,
                owner_user_id=admin_user.id,
                key_prefix="sk_",
                key_suffix="abcd",
                name="scoped",
                key_type=ApiKeyType.SK,
                permission=ApiKeyPermission.WRITE,
                scope_type=scope_type,
                scope_id=scope_id,
                state=ApiKeyState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                key_hash="hash",
                hash_version="1",
            )
        }
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_authorize_and_grant_decide_a_hidden_assistant_key_the_same_way(
    db_container,
    space_factory,
    completion_model_factory,
    assistant_factory,
    admin_user,
):
    """A key scoped to a flow-managed (hidden) assistant is no key of the
    space's assistants: ``Space.assistants`` leaves it out, so ``authorize``
    refuses it, and the grant's own facts must refuse it for the same reason."""
    async with db_container() as container:
        session = container.session()
        space = await space_factory(session, f"Hidden key {uuid4()}")
        model = await completion_model_factory(session, f"cm-{uuid4()}")
        visible = await assistant_factory(session, "visible", model.id)
        hidden = await assistant_factory(session, "hidden", model.id, hidden=True)
        for assistant in (visible, hidden):
            await session.execute(
                sa.text("UPDATE assistants SET space_id = :space WHERE id = :id"),
                {"space": space.id, "id": assistant.id},
            )
        await session.execute(
            sa.text(
                "INSERT INTO spaces_users (space_id, user_id, role) "
                "VALUES (:space_id, :user_id, 'editor')"
            ),
            {"space_id": str(space.id), "user_id": str(admin_user.id)},
        )
        space_id, visible_id, hidden_id = space.id, visible.id, hidden.id
    _, scope = _scope(admin_user, space_id, None)
    action = FlowApiAction.BUILDER_MESSAGE_SEND

    async def outcome(user, decide) -> str:
        async with db_container(user=user) as container:
            try:
                await decide(_access(container), container)
            except UnauthorizedException as refused:
                return str(getattr(refused, "code", "refused"))
            except Exception as refused:  # noqa: BLE001 - the outcome is the datum
                return type(refused).__name__
            return "allowed"

    async def authorize(access, _):
        await access.authorize(
            ScopeFilter(), action=action, space_id=space_id, session=None
        )

    async def grant(access, _):
        await access.open_grant(scope, action)

    outcomes = {}
    for label, assistant_id in (("visible", visible_id), ("hidden", hidden_id)):
        keyed = _scoped_key(
            admin_user, scope_type=ApiKeyScopeType.ASSISTANT, scope_id=assistant_id
        )
        outcomes[label] = (await outcome(keyed, authorize), await outcome(keyed, grant))

    assert outcomes["visible"] == ("allowed", "allowed")
    # Both refuse: the layer that names the refusal differs, the decision not.
    assert "allowed" not in outcomes["hidden"]


def _review_service(
    session: BuilderSession, barrier: asyncio.Barrier, reached: list[str]
) -> AsyncMock:
    service = AsyncMock()
    service.get_session.return_value = session

    async def preflight(**_: object) -> SessionTurnPreflight:
        return SessionTurnPreflight(
            session=session,
            baseline=SessionTurnPreparationBaseline(
                session_status=session.status,
                latest_plan_id=None,
                planning_state_version=session.planning_state_version,
                latest_turn_id=None,
                latest_turn_state=None,
                attachment_file_ids=(),
            ),
        )

    async def prepare(**_: object) -> MagicMock:
        # Both turns are inside their evidence snapshot before either goes on.
        # A turn that failed earlier never arrives: the bound keeps the other
        # from waiting for it.
        await asyncio.wait_for(barrier.wait(), timeout=10)
        reached.append("prepared")
        prepared = MagicMock()
        prepared.session_attachment_file_ids = ()
        return prepared

    async def no_events(**_: object):
        return
        yield

    service.preflight_message_turn.side_effect = preflight
    service.prepare_message_context.side_effect = prepare
    service.send_message.side_effect = no_events
    return service


@asynccontextmanager
async def _pool_of(size: int) -> AsyncIterator[None]:
    engine = create_async_engine(
        sessionmanager._engine.url.render_as_string(hide_password=False),
        pool_size=size,
        max_overflow=0,
        pool_timeout=3,
    )
    original = sessionmanager._engine, sessionmanager._sessionmaker
    sessionmanager._engine = engine
    sessionmanager._sessionmaker = async_sessionmaker(
        autocommit=False,
        bind=engine,
        autobegin=False,
        class_=database_module.SafeAsyncSession,
    )
    try:
        yield
    finally:
        await engine.dispose()
        sessionmanager._engine, sessionmanager._sessionmaker = original


@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_review_turns_complete_on_a_pool_of_two(
    db_container, space_factory, admin_user
):
    """A review turn holds one connection for its evidence snapshot. The grant
    must not ask for a second one from inside it: with every connection held
    by a turn that waits for another, no turn could ever go on."""
    space_id, flow_id = await _seed(db_container, space_factory, admin_user)
    async with db_container() as container:
        tenant = container.tenant()
    session = BuilderSession(
        id=uuid4(),
        tenant_id=admin_user.tenant_id,
        space_id=space_id,
        flow_id=flow_id,
        target_kind=TargetKind.EDIT,
        status=SessionStatus.CHATTING,
        actor_user_id=admin_user.id,
    )
    barrier = asyncio.Barrier(2)
    reached: list[str] = []

    async def review_turn() -> list[str]:
        async with sessionmanager.session() as operation_session:
            container = Container(
                session=providers.Object(operation_session),
                user=providers.Object(admin_user),
                tenant=providers.Object(tenant),
            )
            container.ai_builder_service.override(
                providers.Object(_review_service(session, barrier, reached))
            )
            response = await send_message(
                request=MagicMock(),
                session_id=session.id,
                body=SendMessageRequest(
                    client_turn_id=uuid4(),
                    message="Undersök",
                    review_context=AIBuilderReviewContext(
                        flow_version=1,
                        definition_checksum="sum",
                        finding_ids=["f1f1f1f1f1f1f1f1"],
                    ),
                ),
                container=container,
            )
            return [chunk async for chunk in response.body_iterator]

    started = time.monotonic()
    # The container context keeps the object-content runtime the real space
    # service needs started; it takes its own connection before the pool is
    # narrowed, and the turns then share two.
    async with db_container(), _pool_of(2):
        await asyncio.gather(review_turn(), review_turn())
    assert reached == ["prepared", "prepared"]
    assert time.monotonic() - started < 3
