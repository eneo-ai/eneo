from datetime import datetime, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.database.tables.users_table import Users
from eneo.database.tables.websites_table import CrawlRunFailures, CrawlRuns, Websites

pytest_plugins = [
    "tests.integration.test_website_latest_crawl",
    "tests.integration.test_api_key_tenant_isolation",
]

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("personal", [False, True])
async def test_admin_reads_operational_details_without_space_membership(
    client, db_container, admin_user, website_id, headers, personal
):
    run_id = uuid4()
    async with db_container(user=admin_user) as container:
        session = container.session()
        space_id = await session.scalar(
            sa.select(Websites.space_id).where(Websites.id == website_id)
        )
        await session.execute(
            sa.delete(SpacesUsers).where(SpacesUsers.space_id == space_id)
        )
        if personal:
            owner = Users(
                username=f"private-crawl-{uuid4()}",
                email=f"private-crawl-{uuid4()}@example.com",
                state="active",
                used_tokens=0,
                tenant_id=admin_user.tenant_id,
            )
            session.add(owner)
            await session.flush()
            personal_space = Spaces(
                name="Personal space", tenant_id=admin_user.tenant_id, user_id=owner.id
            )
            session.add(personal_space)
            await session.flush()
            await session.execute(
                sa.update(Websites)
                .where(Websites.id == website_id)
                .values(space_id=personal_space.id)
            )
        session.add(
            CrawlRuns(
                id=run_id,
                website_id=website_id,
                tenant_id=admin_user.tenant_id,
                phase="terminal",
                outcome="partial",
                origin="scheduled",
                failure_code="processing_failed",
                finished_at=datetime.now(timezone.utc),
                failure_details_available=True,
                pages_crawled=3,
                pages_failed=1,
            )
        )
        await session.flush()
        session.add(
            CrawlRunFailures(
                crawl_run_id=run_id,
                kind="page",
                url="https://example.test/error",
                reason="http_503",
            )
        )

    response = await client.get("/api/v1/admin/crawler/?view=recent", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["summary"] == {"ongoing": 0, "queued": 0, "issues": 1}
    assert data["items"][0]["website_name"] == "Municipal website"
    assert data["items"][0]["run"]["id"] == str(run_id)
    assert data["items"][0]["run"]["pages_crawled"] == 3
    details = await client.get(
        f"/api/v1/admin/crawler/runs/{run_id}/failures/", headers=headers
    )
    assert details.status_code == 200, details.text
    assert details.json()["items"][0]["reason"] == "http_503"
    ordinary = await client.get(f"/api/v1/websites/{website_id}/runs/", headers=headers)
    assert ordinary.status_code == 403


async def test_non_admin_and_other_tenant_cannot_read_crawls(
    client,
    db_container,
    admin_user,
    website_id,
    headers,
    patch_auth_service_jwt,
    second_tenant_token,
):
    from eneo.users.user import UserAdd, UserState

    run_id = uuid4()
    async with db_container(user=admin_user) as container:
        container.session().add(
            CrawlRuns(
                id=run_id,
                website_id=website_id,
                tenant_id=admin_user.tenant_id,
                phase="terminal",
                outcome="succeeded",
                origin="manual",
                finished_at=datetime.now(timezone.utc),
            )
        )
        regular = await container.user_repo().add(
            UserAdd(
                email=f"crawler-reader-{uuid4()}@example.com",
                username=f"reader-{uuid4()}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
            )
        )
        token = container.auth_service().create_access_token_for_user(regular)
    endpoints = [
        "/api/v1/admin/crawler/",
        f"/api/v1/admin/crawler/runs/{run_id}/failures/",
    ]
    for url in endpoints:
        response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403, response.text
    foreign = {"Authorization": f"Bearer {second_tenant_token}"}
    response = await client.get("/api/v1/admin/crawler/?view=recent", headers=foreign)
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    assert response.json()["summary"] == {"ongoing": 0, "queued": 0, "issues": 0}
    response = await client.get(endpoints[1], headers=foreign)
    assert response.status_code == 404, response.text
    response = await client.get(
        f"/api/v1/admin/crawler/?view=recent&cursor={run_id}", headers=foreign
    )
    assert response.status_code == 400, response.text


async def test_recent_runs_are_bounded_and_summary_ignores_filters(
    client,
    db_container,
    admin_user,
    website_id,
    headers,
):
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    run_ids = sorted(uuid4() for _ in range(6))
    outcomes = ["succeeded", "partial", "failed", "interrupted", "cancelled", "failed"]
    async with db_container(user=admin_user) as container:
        for index, (id, outcome) in enumerate(zip(run_ids, outcomes, strict=True)):
            container.session().add(
                CrawlRuns(
                    id=id,
                    website_id=website_id,
                    tenant_id=admin_user.tenant_id,
                    phase="terminal",
                    outcome=outcome,
                    origin="scheduled",
                    failure_code=None
                    if outcome == "succeeded"
                    else "processing_failed",
                    finished_at=now - timedelta(hours=25 if index == 5 else 1),
                )
            )
    base = "/api/v1/admin/crawler/?view=recent&limit=2"
    first = await client.get(base, headers=headers)
    assert first.status_code == 200, first.text
    first_data = first.json()
    assert first_data["summary"]["issues"] == 3
    assert [item["run"]["id"] for item in first_data["items"]] == [
        str(i) for i in reversed(run_ids[3:5])
    ]
    second = await client.get(
        f"{base}&cursor={first_data['next_cursor']}", headers=headers
    )
    assert [item["run"]["id"] for item in second.json()["items"]] == [
        str(i) for i in reversed(run_ids[1:3])
    ]
    third = await client.get(
        f"{base}&cursor={second.json()['next_cursor']}", headers=headers
    )
    assert [item["run"]["id"] for item in third.json()["items"]] == [str(run_ids[0])]
    assert third.json()["next_cursor"] is None
    empty = await client.get(f"{base}&search=absent", headers=headers)
    assert empty.json()["items"] == []
    assert empty.json()["summary"]["issues"] == 3
    issues = await client.get(f"{base}&status=issues&limit=100", headers=headers)
    assert {item["run"]["outcome"] for item in issues.json()["items"]} == {
        "partial",
        "failed",
        "interrupted",
    }
    for suffix in ("limit=101", "limit=0", "status=bogus", "cursor=bogus"):
        assert (
            await client.get(f"/api/v1/admin/crawler/?{suffix}", headers=headers)
        ).status_code == 422


async def test_active_overview_tracks_attempt_start_and_completion(
    client,
    db_session,
    admin_user,
    headers,
):
    from datetime import timedelta

    from eneo.database.tables.websites_table import CrawlAttempts
    from eneo.websites.domain.crawl_run import CrawlOutcome
    from eneo.websites.domain.crawl_run_repo import CrawlRunRepository
    from tests.integration.test_crawl_admission_and_dispatch import (
        _admit,
        _persist_website,
    )

    run_ids = []
    attempts = []
    async with db_session() as session:
        repo = CrawlRunRepository(session)
        for index in range(5):
            website = await _persist_website(
                session,
                tenant_id=admin_user.tenant_id,
                user_id=admin_user.id,
                label=f"Overview {index}",
            )
            run = await _admit(session, website=website, user=admin_user)
            await session.execute(
                sa.update(CrawlRuns)
                .where(CrawlRuns.id == run.id)
                .values(
                    created_at=datetime.now(timezone.utc)
                    - timedelta(minutes=10 - index)
                )
            )
            run_ids.append(str(run.id))
            attempt = await session.scalar(
                sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
            )
            assert attempt is not None
            attempts.append(attempt.id)
            if index == 1:
                assert await repo.mark_dispatched(attempt.id)
            elif index >= 2:
                assert await repo.claim_attempt(
                    attempt.id,
                    dispatch_id=attempt.dispatch_id,
                    lease_owner="test",
                    lease_duration=timedelta(minutes=5),
                )
                if index == 3:
                    assert await repo.mark_finalizing(attempt.id, lease_owner="test")
                elif index == 4:
                    await repo.request_cancel(run.id)
    response = await client.get("/api/v1/admin/crawler/", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["summary"] == {"ongoing": 3, "queued": 2, "issues": 0}
    assert [item["run"]["id"] for item in data["items"]] == run_ids
    assert [item["run"]["phase"] for item in data["items"]] == [
        "pending_dispatch",
        "queued",
        "running",
        "finalizing",
        "stopping",
    ]
    assert all(item["started_at"] is None for item in data["items"][:2])
    assert all(item["started_at"] is not None for item in data["items"][2:])
    queued = await client.get("/api/v1/admin/crawler/?status=queued", headers=headers)
    assert len(queued.json()["items"]) == 2
    assert queued.json()["summary"]["ongoing"] == 3
    async with db_session() as session:
        assert await CrawlRunRepository(session).finish_attempt(
            attempts[2],
            lease_owner="test",
            outcome=CrawlOutcome.SUCCEEDED,
            pages_crawled=7,
        )
    refreshed = await client.get("/api/v1/admin/crawler/", headers=headers)
    assert refreshed.json()["summary"]["ongoing"] == 2
    recent = await client.get("/api/v1/admin/crawler/?view=recent", headers=headers)
    assert recent.json()["items"][0]["run"]["pages_crawled"] == 7


@pytest.mark.parametrize(
    ("scope", "permission", "allowed"),
    [("tenant", "admin", True), ("tenant", "read", False), ("space", "admin", False)],
)
async def test_admin_crawler_requires_tenant_admin_api_key_scope(
    client,
    db_container,
    admin_user,
    website_id,
    headers,
    scope,
    permission,
    allowed,
):
    from tests.integration.test_api_key_governance_isolation import _create_api_key

    async with db_container(user=admin_user) as container:
        space_id = await container.session().scalar(
            sa.select(Websites.space_id).where(Websites.id == website_id)
        )
        await container.session().execute(
            sa.update(SpacesUsers)
            .where(
                SpacesUsers.space_id == space_id, SpacesUsers.user_id == admin_user.id
            )
            .values(role="admin")
        )
    secret = await _create_api_key(
        client,
        bearer_token=headers["Authorization"].removeprefix("Bearer "),
        scope_type=scope,
        scope_id=str(space_id) if scope == "space" else None,
        permission=permission,
    )
    response = await client.get("/api/v1/admin/crawler/", headers={"X-API-Key": secret})
    assert response.status_code == (200 if allowed else 403), response.text
    details = await client.get(
        f"/api/v1/admin/crawler/runs/{uuid4()}/failures/", headers={"X-API-Key": secret}
    )
    assert details.status_code == (404 if allowed else 403), details.text
