"""Deleting an organisation removes what belongs to it and nothing else."""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg2
import pytest
import sqlalchemy as sa

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.service_table import Services
from eneo.database.tables.spaces_table import Spaces
from init_db import add_tenant_user


@pytest.fixture
async def doomed_tenant_user(db_container, test_settings):
    """A tenant of its own, so deleting it leaves the shared one alone."""
    suffix = uuid4().hex[:8]
    email = f"tenant_delete_user_{suffix}@example.com"
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    add_tenant_user(
        conn,
        tenant_name=f"tenant_delete_{suffix}",
        quota_limit=1_000_000,
        user_name=f"tenant_delete_user_{suffix}",
        user_email=email,
        user_password="RepositoryTestPass123!",
    )
    conn.close()

    async with db_container() as container:
        return await container.user_repo().get_user_by_email(email)


async def _assistant(session, *, user_id: UUID | None, space_id: UUID | None) -> UUID:
    assistant_id = uuid4()
    await session.execute(
        sa.insert(Assistants).values(
            id=assistant_id,
            name=f"assistant-{uuid4().hex[:8]}",
            logging_enabled=False,
            is_default=False,
            published=False,
            user_id=user_id,
            space_id=space_id,
        )
    )
    return assistant_id


async def _service(session, *, user_id: UUID | None, space_id: UUID | None) -> UUID:
    service_id = uuid4()
    await session.execute(
        sa.insert(Services).values(
            id=service_id,
            name=f"service-{uuid4().hex[:8]}",
            prompt="",
            user_id=user_id,
            space_id=space_id,
        )
    )
    return service_id


async def _space(session, *, tenant_id: UUID) -> UUID:
    """A shared space. Each organisation has one organisation space, which the
    shared ones point at; a new organisation gets it here."""
    organisation_space = await session.scalar(
        sa.select(Spaces.id).where(
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )
    if organisation_space is None:
        organisation_space = uuid4()
        await session.execute(
            sa.insert(Spaces).values(
                id=organisation_space, name="Organization space", tenant_id=tenant_id
            )
        )
    space_id = uuid4()
    await session.execute(
        sa.insert(Spaces).values(
            id=space_id,
            name=f"space-{uuid4().hex[:8]}",
            tenant_id=tenant_id,
            tenant_space_id=organisation_space,
        )
    )
    return space_id


async def _existing(session, table, ids: list[UUID]) -> set[UUID]:
    rows = await session.scalars(sa.select(table.id).where(table.id.in_(ids)))
    return set(rows)


async def test_deleting_an_organisation_removes_its_assistants_and_services(
    db_container, admin_user, doomed_tenant_user
):
    doomed = doomed_tenant_user
    async with db_container() as container:
        session = container.session()
        doomed_space = await _space(session, tenant_id=doomed.tenant_id)
        kept_space = await _space(session, tenant_id=admin_user.tenant_id)

        in_a_space = await _assistant(session, user_id=doomed.id, space_id=doomed_space)
        made_by_a_service = await _assistant(
            session, user_id=None, space_id=doomed_space
        )
        outside_a_space = await _assistant(session, user_id=doomed.id, space_id=None)
        service_outside_a_space = await _service(
            session, user_id=doomed.id, space_id=None
        )
        other_tenants = await _assistant(
            session, user_id=admin_user.id, space_id=kept_space
        )
        other_tenants_outside_a_space = await _assistant(
            session, user_id=admin_user.id, space_id=None
        )
        other_tenants_service = await _service(
            session, user_id=admin_user.id, space_id=None
        )
        await session.flush()

        await container.tenant_repo().delete_tenant_by_id(doomed.tenant_id)

        assert (
            await _existing(
                session,
                Assistants,
                [in_a_space, made_by_a_service, outside_a_space],
            )
            == set()
        )
        assert await _existing(session, Services, [service_outside_a_space]) == set()
        assert await _existing(
            session, Assistants, [other_tenants, other_tenants_outside_a_space]
        ) == {other_tenants, other_tenants_outside_a_space}
        assert await _existing(session, Services, [other_tenants_service]) == {
            other_tenants_service
        }
