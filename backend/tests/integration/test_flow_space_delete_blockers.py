from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.flow_tables import (
    FlowPackageImports,
    FlowRuns,
    Flows,
    FlowSteps,
    FlowVersions,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.users_table import Users
from eneo.spaces.space_flow_delete_blockers import space_has_flow_delete_blockers
from eneo.users.user import UserState
from eneo.users.user_repo import UsersRepository


async def _create_user(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    email: str | None = None,
) -> Users:
    user = Users(
        email=email or f"user-{uuid4()}@example.com",
        username=f"user-{uuid4()}",
        state=UserState.ACTIVE.value,
        tenant_id=tenant_id,
        is_active=True,
        email_verified=True,
        used_tokens=0,
    )
    session.add(user)
    await session.flush()
    return user


async def _create_space(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
) -> Spaces:
    tenant_space_id = None
    if user_id is None:
        tenant_space_id = await session.scalar(
            sa.select(Spaces.id)
            .where(Spaces.tenant_id == tenant_id)
            .where(Spaces.user_id.is_(None))
            .where(Spaces.tenant_space_id.is_(None))
            .limit(1)
        )

    space = Spaces(
        name=f"Flow blocker space {uuid4()}",
        description=None,
        tenant_id=tenant_id,
        user_id=user_id,
        tenant_space_id=tenant_space_id,
        data_retention_days=None,
    )
    session.add(space)
    await session.flush()
    return space


async def _create_flow(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    deleted: bool = False,
) -> Flows:
    flow = Flows(
        name=f"Delete blocker flow {uuid4()}",
        description=None,
        tenant_id=tenant_id,
        space_id=space_id,
        created_by_user_id=user_id,
        owner_user_id=user_id,
        published_version=None,
        metadata_json={},
        data_retention_days=None,
        draft_revision=0,
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )
    session.add(flow)
    await session.flush()
    return flow


async def _create_assistant(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    managing_flow_id: UUID | None = None,
) -> Assistants:
    assistant = Assistants(
        name=f"Flow blocker assistant {uuid4()}",
        user_id=user_id,
        space_id=space_id,
        completion_model_id=None,
        completion_model_kwargs={},
        logging_enabled=False,
        is_default=False,
        published=False,
        description=None,
        insight_enabled=False,
        data_retention_days=None,
        metadata_json={},
        hidden=managing_flow_id is not None,
        origin="flow_managed" if managing_flow_id is not None else "user",
        managing_flow_id=managing_flow_id,
    )
    session.add(assistant)
    await session.flush()
    return assistant


async def _create_flow_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    flow_id: UUID,
) -> None:
    session.add(
        FlowVersions(
            flow_id=flow_id,
            version=1,
            tenant_id=tenant_id,
            definition_checksum="checksum",
            definition_json={"steps": []},
        )
    )
    await session.flush()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_space_flow_delete_blockers_allow_empty_and_bare_flow_spaces(
    db_session,
    admin_user,
):
    async with db_session() as session:
        user = await _create_user(session, tenant_id=admin_user.tenant_id)
        empty_space = await _create_space(
            session, tenant_id=admin_user.tenant_id, user_id=None
        )
        bare_flow_space = await _create_space(
            session, tenant_id=admin_user.tenant_id, user_id=None
        )
        await _create_flow(
            session,
            tenant_id=admin_user.tenant_id,
            space_id=bare_flow_space.id,
            user_id=user.id,
        )

        assert not await space_has_flow_delete_blockers(session, empty_space.id)
        assert not await space_has_flow_delete_blockers(session, bare_flow_space.id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_space_flow_delete_blockers_detect_step_rows(db_session, admin_user):
    async with db_session() as session:
        user = await _create_user(session, tenant_id=admin_user.tenant_id)
        space = await _create_space(
            session, tenant_id=admin_user.tenant_id, user_id=None
        )
        flow = await _create_flow(
            session,
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=user.id,
        )
        assistant = await _create_assistant(
            session,
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=user.id,
        )
        session.add(
            FlowSteps(
                flow_id=flow.id,
                tenant_id=admin_user.tenant_id,
                assistant_id=assistant.id,
                step_order=1,
                user_description="Draft step",
                input_source="flow_input",
                input_type="text",
                output_mode="pass_through",
                output_type="json",
            )
        )
        await session.flush()

        assert await space_has_flow_delete_blockers(session, space.id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_space_flow_delete_blockers_detect_flow_managed_assistants(
    db_session,
    admin_user,
):
    async with db_session() as session:
        user = await _create_user(session, tenant_id=admin_user.tenant_id)
        space = await _create_space(
            session, tenant_id=admin_user.tenant_id, user_id=None
        )
        flow = await _create_flow(
            session,
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=user.id,
        )
        await _create_assistant(
            session,
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=user.id,
            managing_flow_id=flow.id,
        )

        assert await space_has_flow_delete_blockers(session, space.id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_space_flow_delete_blockers_detect_draft_package_imports(
    db_session,
    admin_user,
):
    async with db_session() as session:
        user = await _create_user(session, tenant_id=admin_user.tenant_id)
        space = await _create_space(
            session, tenant_id=admin_user.tenant_id, user_id=None
        )
        flow = await _create_flow(
            session,
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=user.id,
        )
        await session.execute(
            sa.insert(FlowPackageImports).values(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                flow_id=flow.id,
                created_by_user_id=user.id,
                package_id="se.example.delete-blocker",
                package_version="1.0.0",
                content_checksum="a" * 64,
                source="file_upload",
                status="draft_created",
                import_plan_json={},
                selected_mappings_json={},
            )
        )
        await session.flush()

        assert await space_has_flow_delete_blockers(session, space.id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_space_flow_delete_blockers_detect_soft_deleted_flow_with_run_history(
    db_session,
    admin_user,
):
    async with db_session() as session:
        user = await _create_user(session, tenant_id=admin_user.tenant_id)
        space = await _create_space(
            session, tenant_id=admin_user.tenant_id, user_id=None
        )
        flow = await _create_flow(
            session,
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=user.id,
            deleted=True,
        )
        await _create_flow_version(
            session, tenant_id=admin_user.tenant_id, flow_id=flow.id
        )
        session.add(
            FlowRuns(
                flow_id=flow.id,
                flow_version=1,
                principal_type="user",
                principal_user_id=user.id,
                tenant_id=admin_user.tenant_id,
                trace_id=uuid4(),
                status="completed",
            )
        )
        await session.flush()

        assert await space_has_flow_delete_blockers(session, space.id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_user_soft_delete_preserves_personal_space_with_flow_blockers(
    db_session,
    admin_user,
):
    async with db_session() as session:
        user = await _create_user(session, tenant_id=admin_user.tenant_id)
        personal_space = await _create_space(
            session, tenant_id=admin_user.tenant_id, user_id=user.id
        )
        flow = await _create_flow(
            session,
            tenant_id=admin_user.tenant_id,
            space_id=personal_space.id,
            user_id=user.id,
        )
        await _create_assistant(
            session,
            tenant_id=admin_user.tenant_id,
            space_id=personal_space.id,
            user_id=user.id,
            managing_flow_id=flow.id,
        )

        deleted_user = await UsersRepository(session).soft_delete(user.id)

        assert deleted_user.state == UserState.DELETED
        assert await session.get(Spaces, personal_space.id) is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_user_soft_delete_deletes_personal_space_without_flow_blockers(
    db_session,
    admin_user,
):
    async with db_session() as session:
        user = await _create_user(session, tenant_id=admin_user.tenant_id)
        personal_space = await _create_space(
            session, tenant_id=admin_user.tenant_id, user_id=user.id
        )

        deleted_user = await UsersRepository(session).soft_delete(user.id)

        assert deleted_user.state == UserState.DELETED
        assert await session.get(Spaces, personal_space.id) is None
