"""Members see an oversight visit for 90 days after it ends; then the daily
purge deletes it. Open visits stay, and the audit log keeps the join and the
leave under its own retention."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

import pytest

from eneo.spaces.oversight.visit_retention import purge_ended_oversight_visits
from tests.integration.space_oversight.support import (
    REASON,
    admin_row,
    audit_rows,
    create_space,
    days_ago,
    execute,
    fetch,
    insert_space,
    insert_tenant,
    insert_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _visit(
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    *,
    joined_at: datetime,
    left_at: Optional[datetime],
) -> UUID:
    (row,) = await fetch(
        "INSERT INTO space_oversight_visits (tenant_id, space_id, user_id, role,"
        " reason, joined_at, left_at) VALUES (:t, :s, :u, 'viewer', :reason, :j, :l)"
        " RETURNING id",
        t=tenant_id,
        s=space_id,
        u=user_id,
        reason=REASON,
        j=joined_at,
        l=left_at,
    )
    return row[0]


async def _visit_ids() -> set[UUID]:
    return {row[0] for row in await fetch("SELECT id FROM space_oversight_visits")}


async def test_visits_that_ended_more_than_ninety_days_ago_are_deleted_in_every_tenant():
    _, seeded_tenant = await admin_row()
    kept: set[UUID] = set()
    for tenant_id in (seeded_tenant, await insert_tenant()):
        space_id = await insert_space(tenant_id)
        overseer = await insert_user(tenant_id, label="overseer")
        await _visit(
            tenant_id,
            space_id,
            overseer,
            joined_at=days_ago(130),
            left_at=days_ago(91),
        )
        kept.add(
            await _visit(
                tenant_id,
                space_id,
                overseer,
                joined_at=days_ago(90),
                left_at=days_ago(89),
            )
        )
        # Still a member: however old, the visit is not over.
        kept.add(
            await _visit(
                tenant_id,
                space_id,
                await insert_user(tenant_id, label="member"),
                joined_at=days_ago(400),
                left_at=None,
            )
        )

    assert await purge_ended_oversight_visits() == {"visits_deleted": 2}
    assert await _visit_ids() == kept


async def test_the_audit_log_keeps_the_join_and_leave_of_a_purged_visit(
    client, admin, overseer
):
    space_id = await create_space(client, admin.token)
    resp = await client.post(
        f"/api/v1/admin/spaces/{space_id}/join/",
        json={"role": "viewer", "reason": REASON},
        headers=overseer.headers,
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/admin/spaces/{space_id}/leave/", headers=overseer.headers
    )
    assert resp.status_code == 200, resp.text
    await execute(
        "UPDATE space_oversight_visits SET joined_at = :j, left_at = :l"
        " WHERE space_id = :s",
        j=days_ago(92),
        l=days_ago(91),
        s=space_id,
    )

    assert await purge_ended_oversight_visits() == {"visits_deleted": 1}
    assert await _visit_ids() == set()
    joined, left = await audit_rows(entity_id=space_id)
    assert (joined["action"], joined["metadata"]["extra"]["reason"]) == (
        "space_oversight_joined",
        REASON,
    )
    assert left["action"] == "space_oversight_left"
    assert left["metadata"]["extra"]["was_oversight_join"] is True
