"""Integration tests for SessionRepository tenant filtering.

Service-key sessions persist with user_id=NULL — the principal is carried on
api_key_id instead. The repo's tenant-scoping path therefore cannot rely on
an INNER JOIN against Users; it LEFT JOINs both principal tables and matches
against whichever tenant_id is present.

These tests pin that contract: tenant-scoped queries must return sessions for
both user principals and service-key principals in the queried tenant, and
must exclude principals from any other tenant.
"""

from __future__ import annotations

import secrets
from uuid import UUID, uuid4

import psycopg2
import pytest
import sqlalchemy as sa

from init_db import add_tenant_user
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.sessions_table import Sessions


@pytest.fixture
async def second_tenant_user(db_container, test_settings):
    """Spin up a second tenant + user pair via the same psycopg2 path other
    integration tests use, then resolve the user through the test container.
    """
    suffix = uuid4().hex[:8]
    email = f"sessions_filter_user_{suffix}@example.com"
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    add_tenant_user(
        conn,
        tenant_name=f"sessions_filter_tenant_{suffix}",
        quota_limit=1_000_000,
        user_name=f"sessions_filter_user_{suffix}",
        user_email=email,
        user_password="test_password",
    )
    conn.close()

    async with db_container() as container:
        user_repo = container.user_repo()
        return await user_repo.get_user_by_email(email)


async def _insert_service_key(
    session: sa.ext.asyncio.AsyncSession,
    *,
    tenant_id: UUID,
    creator_user_id: UUID,
) -> UUID:
    key_id = uuid4()
    suffix = secrets.token_hex(4)
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
        )
    )
    return key_id


async def _insert_session(
    session: sa.ext.asyncio.AsyncSession,
    *,
    name: str,
    user_id: UUID | None = None,
    api_key_id: UUID | None = None,
    assistant_id: UUID | None = None,
) -> UUID:
    session_id = uuid4()
    await session.execute(
        sa.insert(Sessions).values(
            id=session_id,
            name=name,
            user_id=user_id,
            api_key_id=api_key_id,
            assistant_id=assistant_id,
        )
    )
    return session_id


async def _insert_assistant(
    session: sa.ext.asyncio.AsyncSession, *, owner_user_id: UUID
) -> UUID:
    assistant_id = uuid4()
    suffix = uuid4().hex[:8]
    await session.execute(
        sa.insert(Assistants).values(
            id=assistant_id,
            name=f"assistant-{suffix}",
            logging_enabled=False,
            is_default=False,
            published=False,
            user_id=owner_user_id,
        )
    )
    return assistant_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_by_tenant_includes_service_key_sessions(
    db_container, admin_user, second_tenant_user
):
    """get_by_tenant must include sessions where user_id IS NULL.

    Regression for the INNER JOIN bug: an inner join on Users excluded every
    service-key session from tenant-scoped reporting. The LEFT-JOIN fix
    matches on api_keys_v2.tenant_id when sessions.user_id is NULL.
    """
    tenant_a = admin_user.tenant_id
    tenant_b = second_tenant_user.tenant_id

    async with db_container() as container:
        db = container.session()
        repo = container.session_repo()

        key_a = await _insert_service_key(
            db, tenant_id=tenant_a, creator_user_id=admin_user.id
        )
        key_b = await _insert_service_key(
            db, tenant_id=tenant_b, creator_user_id=second_tenant_user.id
        )

        s_user_a = await _insert_session(
            db, name="user-a-session", user_id=admin_user.id
        )
        s_svc_a = await _insert_session(db, name="svc-a-session", api_key_id=key_a)
        s_user_b = await _insert_session(
            db, name="user-b-session", user_id=second_tenant_user.id
        )
        s_svc_b = await _insert_session(db, name="svc-b-session", api_key_id=key_b)
        await db.flush()

        result = await repo.get_by_tenant(tenant_id=tenant_a)
        ids = {s.id for s in result}

        assert s_user_a in ids, "user session in queried tenant must be returned"
        assert s_svc_a in ids, (
            "service-key session in queried tenant must be returned "
            "(this is the bug the fix targets)"
        )
        assert s_user_b not in ids, "user session in another tenant must be excluded"
        assert s_svc_b not in ids, (
            "service-key session in another tenant must be excluded"
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_metadata_by_assistant_includes_service_key_sessions(
    db_container, admin_user
):
    """The insight admin view (assistant scope) must surface service-key sessions.

    analysis_service.get_assistant_insight_sessions passes tenant_id into
    get_metadata_by_assistant, and tenant admins use the result to audit
    activity. Dropping service-key sessions hid API-integration usage from
    that audit.
    """
    async with db_container() as container:
        db = container.session()
        repo = container.session_repo()

        key_a = await _insert_service_key(
            db, tenant_id=admin_user.tenant_id, creator_user_id=admin_user.id
        )
        assistant_id = await _insert_assistant(db, owner_user_id=admin_user.id)

        s_user = await _insert_session(
            db, name="user-session", user_id=admin_user.id, assistant_id=assistant_id
        )
        s_svc = await _insert_session(
            db, name="svc-session", api_key_id=key_a, assistant_id=assistant_id
        )
        await db.flush()

        rows, total = await repo.get_metadata_by_assistant(
            assistant_id=assistant_id,
            tenant_id=admin_user.tenant_id,
        )
        ids = {row.id for row in rows}

        assert s_user in ids
        assert s_svc in ids
        assert total == 2
