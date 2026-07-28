"""Integration tests for ``AssistantRepository.get_personal_defaults_page``.

Personal-chat governance validation used to load every personal default
assistant for a tenant in one unbounded query, with five eager-loaded
relationship collections per row. At fleet size that materialises the whole
tenant in memory on an already-shipped save path. These tests pin the paged
replacement: keyset pagination on ``(created_at, id)``, exhaustive and
duplicate-free across pages, tenant-isolated, and deterministically ordered
even when rows share a ``created_at``.

Mirrors the integration patterns of ``test_assistant_repo_helper_filter.py``:
real Postgres via testcontainers, raw inserts, ``user_factory`` for extra
users.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.spaces_table import Spaces


async def _insert_personal_space(
    session,
    *,
    tenant_id: UUID,
    user_id: UUID,
) -> UUID:
    space_id = uuid4()
    await session.execute(
        sa.insert(Spaces).values(
            id=space_id,
            name=f"personal-{space_id.hex[:8]}",
            tenant_id=tenant_id,
            user_id=user_id,
        )
    )
    return space_id


async def _insert_assistant(
    session,
    *,
    owner_user_id: UUID,
    space_id: UUID,
    is_default: bool = True,
    created_at: datetime | None = None,
) -> UUID:
    assistant_id = uuid4()
    values: dict = {
        "id": assistant_id,
        "name": f"assistant-{assistant_id.hex[:8]}",
        "user_id": owner_user_id,
        "space_id": space_id,
        "completion_model_id": None,
        "logging_enabled": False,
        "is_default": is_default,
        "published": False,
    }
    if created_at is not None:
        values["created_at"] = created_at
    await session.execute(sa.insert(Assistants).values(**values))
    return assistant_id


async def _seed_personal_default(
    user_factory, session, *, tenant_id: UUID, created_at: datetime | None = None
) -> UUID:
    user = await user_factory(session, tenant_id=tenant_id)
    space_id = await _insert_personal_space(
        session, tenant_id=tenant_id, user_id=user.id
    )
    return await _insert_assistant(
        session, owner_user_id=user.id, space_id=space_id, created_at=created_at
    )


async def _get_org_space(session, *, tenant_id: UUID) -> UUID:
    row = await session.scalar(
        sa.select(Spaces.id).where(
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )
    assert row is not None
    return row


def _walk_pages_ids(pages) -> list[UUID]:
    ids: list[UUID] = []
    for page in pages:
        ids.extend(item.assistant.id for item in page.items)
    return ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pages_partition_the_tenants_personal_defaults(
    db_container, admin_user, user_factory, tenant_factory
):
    async with db_container() as container:
        session = container.session()

        expected = [
            await _seed_personal_default(
                user_factory, session, tenant_id=admin_user.tenant_id
            )
            for _ in range(5)
        ]

        # Excluded rows: a non-default assistant in a personal space, a default
        # assistant in the org space, and another tenant's personal default.
        bystander = await user_factory(session, tenant_id=admin_user.tenant_id)
        bystander_space = await _insert_personal_space(
            session, tenant_id=admin_user.tenant_id, user_id=bystander.id
        )
        await _insert_assistant(
            session,
            owner_user_id=bystander.id,
            space_id=bystander_space,
            is_default=False,
        )
        org_space = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=org_space, is_default=True
        )
        other_tenant = await tenant_factory(session)
        await _seed_personal_default(user_factory, session, tenant_id=other_tenant.id)
        await session.flush()

        repo = container.assistant_repo()
        pages = []
        after = None
        for _ in range(10):  # hard stop against a cursor that never terminates
            page = await repo.get_personal_defaults_page(
                tenant_id=admin_user.tenant_id, limit=2, after=after
            )
            pages.append(page)
            if page.next_after is None:
                break
            after = page.next_after
        else:
            pytest.fail("pagination did not terminate")

        assert [len(page.items) for page in pages] == [2, 2, 1]
        collected = _walk_pages_ids(pages)
        assert len(collected) == len(set(collected)), "a page repeated a row"
        assert set(collected) == set(expected)
        # Every item is hydrated for validation, not just an id.
        first = pages[0].items[0]
        assert first.assistant.attachments == []
        assert first.has_knowledge is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_identical_created_at_rows_page_deterministically(
    db_container, admin_user, user_factory
):
    async with db_container() as container:
        session = container.session()

        shared_moment = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
        seeded = [
            await _seed_personal_default(
                user_factory,
                session,
                tenant_id=admin_user.tenant_id,
                created_at=shared_moment,
            )
            for _ in range(3)
        ]
        await session.flush()

        repo = container.assistant_repo()
        collected: list[UUID] = []
        after = None
        for _ in range(6):
            page = await repo.get_personal_defaults_page(
                tenant_id=admin_user.tenant_id, limit=1, after=after
            )
            collected.extend(item.assistant.id for item in page.items)
            if page.next_after is None:
                break
            after = page.next_after
        else:
            pytest.fail("pagination did not terminate")

        # created_at ties break on id, so single-row pages must walk the ids
        # in ascending order — never skipping or repeating a row.
        assert collected == sorted(seeded)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_page_ordering_is_served_by_the_partial_index(db_container, admin_user):
    """The cursor order must come from ``ix_assistants_default_created_at_id``.

    Without it, every page re-sorts the tenant's remaining rows, and the walk
    does superlinear work exactly on the fleet-sized tenants it exists for.
    Planner toggles make the assertion independent of table size: with
    sequential scans and sorts penalised, the plan can only be cheap if the
    partial index provides the (created_at, id) order itself.
    """
    from sqlalchemy.dialects import postgresql

    from eneo.assistants.assistant_repo import personal_defaults_page_query

    async with db_container() as container:
        session = container.session()
        seeded = datetime(2026, 7, 2, 8, 0, 0, tzinfo=timezone.utc)
        query = personal_defaults_page_query(
            tenant_id=admin_user.tenant_id, limit=100, after=(seeded, uuid4())
        )
        compiled = query.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )

        await session.execute(sa.text("SET LOCAL enable_seqscan = off"))
        await session.execute(sa.text("SET LOCAL enable_sort = off"))
        plan_rows = await session.execute(sa.text(f"EXPLAIN {compiled}"))
        plan = "\n".join(row[0] for row in plan_rows)

        assert "ix_assistants_default_created_at_id" in plan, plan
        assert "Sort" not in plan, plan
