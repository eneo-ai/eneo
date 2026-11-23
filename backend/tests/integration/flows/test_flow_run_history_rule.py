"""Flow run history follows one rule: the space's time caps every flow in it,
a flow may choose a shorter time, and a run is due at its deadline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from eneo.database.tables.flow_tables import (
    FlowRetentionHolds,
    FlowRuns,
    Flows,
    FlowVersions,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_retention_repo import FlowRetentionRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

POLICY = "/api/v1/settings/flow-run-retention-policy"


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


async def _space_and_flow(
    db_container, admin_user, *, space_days: int | None
) -> tuple[UUID, UUID]:
    async with db_container() as container:
        session = container.session()
        organization_space_id = await session.scalar(
            sa.select(Spaces.id).where(
                Spaces.tenant_id == admin_user.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        space = Spaces(
            name=f"Rule Space {uuid4()}",
            tenant_id=admin_user.tenant_id,
            user_id=None,
            tenant_space_id=organization_space_id,
            data_retention_days=space_days,
        )
        session.add(space)
        await session.flush()
        flow = Flows(
            name=f"Rule Flow {uuid4()}",
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            created_by_user_id=admin_user.id,
            owner_user_id=admin_user.id,
            published_version=None,
            metadata_json=None,
        )
        session.add(flow)
        await session.flush()
        session.add(
            FlowVersions(
                flow_id=flow.id,
                version=1,
                tenant_id=admin_user.tenant_id,
                definition_checksum=f"rule-{uuid4()}",
                definition_json={"schema_version": 1, "steps": []},
            )
        )
        await session.flush()
        flow.published_version = 1
        await session.flush()
        return space.id, flow.id


async def _run(db_container, admin_user, flow_id: UUID, anchor: datetime) -> UUID:
    async with db_container() as container:
        run = FlowRuns(
            flow_id=flow_id,
            flow_version=1,
            principal_type="user",
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            trace_id=uuid4(),
            status="completed",
            started_at=anchor,
            finished_at=anchor,
            created_at=anchor,
            updated_at=anchor,
        )
        container.session().add(run)
        await container.session().flush()
        return run.id


async def test_a_run_past_the_space_time_is_previewed_then_purged(
    client, admin_token, admin_user, db_container
) -> None:
    """A run that an earlier version kept for review, with the space's time and
    no time on the flow. Mutants: Flows read a Flow-only space value; a mode
    keeps the run; the preview removes it; a held run is selected."""
    _, flow_id = await _space_and_flow(db_container, admin_user, space_days=7)
    now = datetime.now(timezone.utc)
    due = await _run(db_container, admin_user, flow_id, now - timedelta(days=10))
    recent = await _run(db_container, admin_user, flow_id, now - timedelta(days=2))
    held = await _run(db_container, admin_user, flow_id, now - timedelta(days=10))
    async with db_container() as container:
        container.session().add(
            FlowRetentionHolds(
                tenant_id=admin_user.tenant_id,
                flow_id=flow_id,
                flow_run_id=held,
                reason="Recorded request",
                created_at=now - timedelta(days=1),
                review_by=now + timedelta(days=30),
                created_by_actor={"type": "user", "id": str(admin_user.id)},
            )
        )

    headers = {"Authorization": f"Bearer {admin_token}"}
    path = f"{POLICY}/flows/{flow_id}/purge"
    preview = await client.post(path, json={}, headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["candidate_count"] == 1
    assert preview.json()["purged_run_ids"] == []
    assert preview.json()["blocked"]["legal_hold"] == 1
    async with db_container() as container:
        for run_id in (due, recent, held):
            assert await container.session().get(FlowRuns, run_id) is not None

    purge = await client.post(path, json={"dry_run": False}, headers=headers)
    assert purge.status_code == 200, purge.text
    assert purge.json()["purged_run_ids"] == [str(due)]
    async with db_container() as container:
        assert await container.session().get(FlowRuns, due) is None
        assert await container.session().get(FlowRuns, recent) is not None
        assert await container.session().get(FlowRuns, held) is not None


async def test_an_organisation_conversation_time_gives_flows_no_time(
    client, admin_token, admin_user, db_container
) -> None:
    """Mutant: an empty space lets its flows inherit the organisation's
    conversation time, so a conversation setting makes runs purgeable."""
    _, flow_id = await _space_and_flow(db_container, admin_user, space_days=None)
    await _run(
        db_container, admin_user, flow_id, datetime.now(timezone.utc) - timedelta(30)
    )
    async with db_container() as container:
        session = container.session()
        policy = await session.get(AuditRetentionPolicy, admin_user.tenant_id)
        if policy is None:
            session.add(
                AuditRetentionPolicy(
                    tenant_id=admin_user.tenant_id,
                    conversation_retention_enabled=True,
                    conversation_retention_days=1,
                )
            )
        else:
            policy.conversation_retention_enabled = True
            policy.conversation_retention_days = 1
        await session.flush()

    headers = {"Authorization": f"Bearer {admin_token}"}
    preview = await client.post(
        f"{POLICY}/flows/{flow_id}/purge", json={}, headers=headers
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["candidate_count"] == 0
    async with db_container() as container:
        flow = await FlowRepository(container.session()).get(
            flow_id, admin_user.tenant_id
        )
    assert flow.run_history_retention is not None
    assert flow.run_history_retention.state == "off"


# (now, the anchor that is not due yet, a control anchor that is due), all a
# one-day time read in Stockholm time.
DST_CASES = [
    pytest.param(
        "2026-03-29T03:00+02:00",
        "2026-03-28T02:30+01:00",
        "2026-03-28T01:00+01:00",
        id="spring: the anchor's clock time does not exist on the deadline day",
    ),
    pytest.param(
        "2026-10-25T02:00+02:00",
        "2026-10-24T02:00+02:00",
        "2026-10-24T01:00+02:00",
        id="autumn: the anchor's clock time comes twice on the deadline day",
    ),
]


@pytest.mark.parametrize("now,not_yet,control", DST_CASES)
async def test_preview_and_purge_agree_on_the_deadline_across_dst(
    admin_user, db_container, now: str, not_yet: str, control: str
) -> None:
    """Mutant: "due" is `anchor <= now - days`, which says due up to an hour
    before the deadline `anchor + days` around a clock change."""
    _, flow_id = await _space_and_flow(db_container, admin_user, space_days=1)
    at = {value: datetime.fromisoformat(value) for value in (now, not_yet, control)}
    await _run(db_container, admin_user, flow_id, at[not_yet])
    due = await _run(db_container, admin_user, flow_id, at[control])

    for dry_run in (True, False):
        async with db_container() as container:
            session = container.session()
            await session.execute(sa.text("SET LOCAL TIME ZONE 'Europe/Stockholm'"))
            result = await FlowRetentionRepository(
                session
            ).purge_due_flow_run_history_for_tenant(
                tenant_id=admin_user.tenant_id,
                now=at[now],
                limit=10,
                dry_run=dry_run,
                flow_id=flow_id,
            )
        assert result.candidate_count == 1
        assert result.purged_run_ids == (() if dry_run else (due,))


async def test_a_policy_that_names_a_mode_is_refused(
    client, admin_token, admin_user, db_container
) -> None:
    """Mutant: an old client's mode is accepted, so it believes a run waits for
    review that an explicit purge removes."""
    _, flow_id = await _space_and_flow(db_container, admin_user, space_days=7)
    response = await client.put(
        f"{POLICY}/flows/{flow_id}",
        json={"policy": {"mode": "review_required", "days": 3}},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 422, response.text


async def test_the_flow_shows_the_space_time_as_its_cap(
    client, admin_token, admin_user, db_container
) -> None:
    """Mutants: the flow reads a Flow-only space value; the projection keeps a
    mode or an organisation contributor; a longer flow time loosens the cap."""
    _, flow_id = await _space_and_flow(db_container, admin_user, space_days=7)
    headers = {"Authorization": f"Bearer {admin_token}"}

    settings = await client.get(f"{POLICY}/flows/{flow_id}", headers=headers)
    assert settings.status_code == 200, settings.text
    assert settings.json() == {
        "scope": "flow",
        "scope_id": str(flow_id),
        "local_policy": None,
        "inherited_policy": {"days": 7},
        "effective": {
            "state": "configured",
            "effective_days": 7,
            "source": "space",
            "contributors": {"space": {"days": 7}, "flow": None},
        },
    }

    async with db_container() as container:
        # Stored before the space's cap was lowered: the cap still wins.
        await container.session().execute(
            sa.update(Flows)
            .where(Flows.id == flow_id)
            .values(flow_run_history_retention_days=10)
        )
    async with db_container() as container:
        flow = await FlowRepository(container.session()).get(
            flow_id, admin_user.tenant_id
        )
    assert flow.run_history_retention is not None
    assert flow.run_history_retention.model_dump() == {
        "state": "configured",
        "effective_days": 7,
        "source": "space",
        "contributors": {"space": {"days": 7}, "flow": {"days": 10}},
    }
