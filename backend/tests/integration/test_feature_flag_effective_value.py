"""A feature check answers for one tenant from the global flag and that tenant's
own preference, without reading the other tenants' preferences."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.feature_flag_table import GlobalFeatureFlag, TenantFeatureFlag
from eneo.feature_flag.feature_flag_repo import FeatureFlagRepository
from eneo.feature_flag.feature_flag_service import FeatureFlagService

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_FEATURE = "ff_effective_value_probe"

# (global row, tenant preference) -> effective value. None means no row; a
# tenant preference cannot exist without its global row (foreign key).
_EXPECTED: dict[tuple[bool | None, bool | None], bool | None] = {
    (True, True): True,
    (True, False): False,
    (True, None): True,
    (False, True): True,
    (False, False): False,
    (False, None): False,
    (None, None): None,
}


async def _new_tenants(session: AsyncSession, count: int) -> list[UUID]:
    rows = await session.execute(
        sa.text(
            "INSERT INTO tenants (name, quota_limit, state) "
            "SELECT 'ff-' || :run || '-' || g, 0, 'active' "
            "FROM generate_series(1, :count) AS g RETURNING id"
        ),
        {"run": uuid4().hex[:8], "count": count},
    )
    return [row[0] for row in rows]


async def _new_flag(session: AsyncSession, *, enabled: bool) -> UUID:
    return await session.scalar(
        sa.insert(GlobalFeatureFlag)
        .values(name=_FEATURE, enabled=enabled)
        .returning(GlobalFeatureFlag.id)
    )


async def _set_preferences(
    session: AsyncSession, feature_id: UUID, preferences: dict[UUID, bool]
) -> None:
    if preferences:
        await session.execute(
            sa.insert(TenantFeatureFlag),
            [
                {
                    "feature_id": feature_id,
                    "tenant_id": tenant_id,
                    "enabled": enabled,
                    "name": _FEATURE,
                }
                for tenant_id, enabled in preferences.items()
            ],
        )


@contextmanager
def _count_reads(session: AsyncSession) -> Iterator[dict[str, int]]:
    """Statements and rows the session reads inside the block."""
    counts = {"statements": 0, "rows": 0}
    engine = session.bind.sync_engine

    def after(_conn, cursor, statement: str, *_args) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            counts["statements"] += 1
            counts["rows"] += cursor.rowcount

    sa.event.listen(engine, "after_cursor_execute", after)
    try:
        yield counts
    finally:
        sa.event.remove(engine, "after_cursor_execute", after)


@pytest.mark.parametrize(("global_row", "preference"), list(_EXPECTED))
async def test_the_tenant_preference_overrides_the_global_flag(
    async_session: AsyncSession, global_row, preference
):
    tenant, other = await _new_tenants(async_session, 2)
    expected = _EXPECTED[(global_row, preference)]
    if global_row is not None:
        feature_id = await _new_flag(async_session, enabled=global_row)
        # Every row gives the other tenant the opposite of the expected answer,
        # so its preference cannot leak into the checked tenant's answer.
        mine = {} if preference is None else {tenant: preference}
        await _set_preferences(async_session, feature_id, {**mine, other: not expected})
    repo = FeatureFlagRepository(async_session)
    service = FeatureFlagService(repo)

    enabled = await service.check_is_feature_enabled(_FEATURE, tenant_id=tenant)
    fail_closed = await service.check_is_feature_enabled_fail_closed(
        _FEATURE, tenant_id=tenant
    )

    assert enabled is (False if expected is None else expected)
    assert fail_closed is (True if expected is None else expected)
    # The narrow read is the effective value itself, never a partial aggregate.
    assert await repo.is_enabled_for_tenant(_FEATURE, tenant) is expected
    aggregate = await repo.one_or_none(name=_FEATURE)
    if aggregate is None:
        assert expected is None
    else:
        assert aggregate.is_enabled(tenant_id=tenant) is enabled
        assert aggregate.is_enabled(tenant_id=other) is (not expected)


@pytest.mark.parametrize("global_row", [True, False])
async def test_a_check_without_a_tenant_answers_the_global_flag(
    async_session: AsyncSession, global_row
):
    tenants = await _new_tenants(async_session, 2)
    feature_id = await _new_flag(async_session, enabled=global_row)
    await _set_preferences(
        async_session, feature_id, {tenant: not global_row for tenant in tenants}
    )
    service = FeatureFlagService(FeatureFlagRepository(async_session))

    assert await service.check_is_feature_enabled(_FEATURE) is global_row
    assert await service.check_is_feature_enabled_fail_closed(_FEATURE) is global_row


@pytest.mark.parametrize("configured", [1, 500])
async def test_a_check_reads_one_row_however_many_tenants_have_preferences(
    async_session: AsyncSession, configured
):
    tenants = await _new_tenants(async_session, configured)
    feature_id = await _new_flag(async_session, enabled=False)
    await _set_preferences(async_session, feature_id, dict.fromkeys(tenants, True))
    service = FeatureFlagService(FeatureFlagRepository(async_session))

    with _count_reads(async_session) as reads:
        assert await service.check_is_feature_enabled(_FEATURE, tenant_id=tenants[-1])

    assert reads == {"statements": 1, "rows": 1}

    # Negative control: the aggregate read does grow with the tenants, so the
    # counter would have caught a check that still read them all.
    with _count_reads(async_session) as aggregate_reads:
        await service.feature_flag_repo.one(name=_FEATURE)
    assert aggregate_reads == {"statements": 2, "rows": 1 + configured}
