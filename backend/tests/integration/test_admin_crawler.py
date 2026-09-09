from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.database.tables.job_table import Jobs
from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.database.tables.users_table import Users
from eneo.database.tables.websites_table import CrawlRunFailures, CrawlRuns, Websites

pytest_plugins = [
    "tests.integration.test_website_latest_crawl",
    "tests.integration.test_api_key_tenant_isolation",
]

pytestmark = pytest.mark.integration


async def test_admin_details_separate_source_storage_and_selected_run_results(
    client, db_container, admin_user, website_id, headers, monkeypatch
):
    from eneo.spaces.space_repo import SpaceRepository

    async def forbid_space_hydration(*args, **kwargs):
        pytest.fail("Admin details must not load private space content")

    monkeypatch.setattr(SpaceRepository, "_get_from_query", forbid_space_hydration)
    run_id = uuid4()
    indexed_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    async with db_container(user=admin_user) as container:
        session = container.session()
        website = await session.get(Websites, website_id)
        await session.execute(
            sa.delete(SpacesUsers).where(SpacesUsers.space_id == website.space_id)
        )
        website.name = None
        website.size = 200
        website.last_indexed_at = indexed_at
        website.update_interval = "daily"
        session.add(
            CrawlRuns(
                id=run_id,
                website_id=website_id,
                tenant_id=admin_user.tenant_id,
                phase="terminal",
                outcome="failed",
                origin="legacy",
                failure_code="processing_failed",
                finished_at=datetime.now(timezone.utc),
                pages_crawled=0,
                files_downloaded=0,
            )
        )
        for state, size in [("active", 80), ("active", 120), ("superseded", 999)]:
            session.add(
                InfoBlobs(
                    text="Private indexed content",
                    url=f"https://example.test/{uuid4()}",
                    size=size,
                    source_id=uuid4(),
                    version_state=state,
                    user_id=admin_user.id,
                    tenant_id=admin_user.tenant_id,
                    website_id=website_id,
                    embedding_model_id=website.embedding_model_id,
                )
            )

    response = await client.get(
        f"/api/v1/admin/crawler/runs/{run_id}/", headers=headers
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["website_id"] == str(website_id)
    assert data["website_name"] is None
    assert data["space_id"] is not None
    assert data["owner"]["id"] == str(admin_user.id)
    assert data["initiated_by"] is None
    assert data["indexed_size"] == 200
    assert data["stored_resources"] == 2
    assert data["update_interval"] == "daily"
    assert data["last_indexed_at"].startswith("2026-09-01T00:00:00")
    assert data["run"]["pages_crawled"] == 0
    assert data["active_run"] is None
    assert data["latest_run"]["id"] == str(run_id)
    assert "Private indexed content" not in response.text


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
        f"/api/v1/admin/crawler/runs/{run_id}/",
        f"/api/v1/admin/crawler/websites/{website_id}/runs/",
        f"/api/v1/admin/crawler/websites/{website_id}/matches/",
    ]
    for url in endpoints:
        response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403, response.text
    foreign = {"Authorization": f"Bearer {second_tenant_token}"}
    response = await client.get("/api/v1/admin/crawler/?view=recent", headers=foreign)
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    assert response.json()["summary"] == {"ongoing": 0, "queued": 0, "issues": 0}
    for url in endpoints[1:]:
        response = await client.get(url, headers=foreign)
        assert response.status_code == 404, response.text
    response = await client.get(
        f"/api/v1/admin/crawler/?view=recent&cursor={run_id}", headers=foreign
    )
    assert response.status_code == 400, response.text
    for url in [
        f"/api/v1/admin/crawler/websites/{website_id}/run/",
        f"/api/v1/admin/crawler/runs/{run_id}/cancel/",
    ]:
        assert (
            await client.post(url, headers={"Authorization": f"Bearer {token}"})
        ).status_code == 403
        assert (await client.post(url, headers=foreign)).status_code == 404


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

    history_url = f"/api/v1/admin/crawler/websites/{website_id}/runs/"
    history = await client.get(history_url, headers=headers, params={"limit": 2})
    assert history.status_code == 200, history.text
    assert history.json()["total_count"] == 6
    older = await client.get(
        history_url,
        headers=headers,
        params={"cursor": history.json()["next_cursor"], "limit": 100},
    )
    assert len(older.json()["items"]) == 4
    assert {item["id"] for item in history.json()["items"] + older.json()["items"]} == {
        str(id) for id in run_ids
    }
    assert older.json()["next_cursor"] is None


async def test_same_address_sources_are_exact_tenant_scoped_and_paginated(
    client, db_container, admin_user, website_id, headers, second_tenant_user
):
    match_ids = sorted(uuid4() for _ in range(12))
    async with db_container(user=admin_user) as container:
        session = container.session()
        source = await session.get(Websites, website_id)
        for index, id in enumerate(match_ids + [uuid4(), uuid4()]):
            foreign = index == 13
            session.add(
                Websites(
                    id=id,
                    name=None,
                    url=source.url if index != 12 else f"{source.url}/different",
                    size=100,
                    download_files=False,
                    crawl_type=source.crawl_type,
                    update_interval="never",
                    tenant_id=second_tenant_user.tenant_id
                    if foreign
                    else admin_user.tenant_id,
                    user_id=second_tenant_user.id if foreign else admin_user.id,
                    space_id=None if foreign else source.space_id,
                    embedding_model_id=source.embedding_model_id,
                )
            )
        await session.flush()
        run = CrawlRuns(
            website_id=match_ids[0],
            tenant_id=admin_user.tenant_id,
            phase="terminal",
            outcome="succeeded",
            finished_at=datetime.now(timezone.utc),
            origin="manual",
        )
        session.add(run)
        await session.flush()
        run_id = run.id

    url = f"/api/v1/admin/crawler/websites/{website_id}/matches/"
    first = await client.get(url, headers=headers, params={"limit": 10})
    assert first.status_code == 200, first.text
    assert [item["website_id"] for item in first.json()["items"]] == [
        str(id) for id in match_ids[:10]
    ]
    assert first.json()["items"][0]["latest_run_id"] == str(run_id)
    assert first.json()["items"][1]["latest_run_id"] is None
    second = await client.get(
        url,
        headers=headers,
        params={"cursor": first.json()["next_cursor"], "limit": 10},
    )
    assert [item["website_id"] for item in second.json()["items"]] == [
        str(id) for id in match_ids[10:]
    ]
    assert second.json()["next_cursor"] is None
    for params in ({"limit": 101}, {"limit": 0}):
        assert (
            await client.get(url, headers=headers, params=params)
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
    website_urls = []
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
            website_urls.append(website.url)
            if index == 2:
                await session.execute(
                    sa.update(Websites)
                    .where(Websites.id == website.id)
                    .values(name=None)
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
    assert data["items"][0]["website_name"] == "Overview 0"
    assert data["items"][2]["website_name"] is None
    assert data["items"][2]["website_url"] == website_urls[2]
    assert [item["run"]["phase"] for item in data["items"]] == [
        "pending_dispatch",
        "queued",
        "running",
        "finalizing",
        "stopping",
    ]
    assert all(item["started_at"] is None for item in data["items"][:2])
    assert all(item["started_at"] is not None for item in data["items"][2:])
    by_url = await client.get(
        "/api/v1/admin/crawler/", params={"search": website_urls[2]}, headers=headers
    )
    assert by_url.status_code == 200, by_url.text
    assert [item["run"]["id"] for item in by_url.json()["items"]] == [run_ids[2]]
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
    assert recent.status_code == 200, recent.text
    assert recent.json()["items"][0]["website_name"] is None
    assert recent.json()["items"][0]["website_url"] == website_urls[2]
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


async def test_admin_can_manage_private_source_crawls_with_durable_attribution(
    client, db_container, admin_user, website_id, headers, monkeypatch
):
    from eneo.websites.domain import crawl_service

    monkeypatch.setattr(crawl_service, "reconcile_crawl_work", AsyncMock())
    async with db_container(user=admin_user) as container:
        session = container.session()
        website = await session.get(Websites, website_id)
        owner = Users(
            username="Source owner",
            email=f"source-owner-{uuid4()}@example.com",
            state="active",
            used_tokens=0,
            tenant_id=admin_user.tenant_id,
        )
        session.add(owner)
        await session.flush()
        private_space = Spaces(
            name="Private source space",
            tenant_id=admin_user.tenant_id,
            user_id=owner.id,
        )
        session.add(private_space)
        await session.flush()
        website.space_id = private_space.id
        website.user_id = owner.id
        website.name = None
        owner_id = owner.id

    start_url = f"/api/v1/admin/crawler/websites/{website_id}/run/"
    first = await client.post(start_url, headers=headers)
    assert first.status_code == 200, first.text
    first_run = first.json()
    assert first_run["phase"] == "pending_dispatch"
    repeated = await client.post(start_url, headers=headers)
    assert repeated.json()["id"] == first_run["id"]

    details_url = f"/api/v1/admin/crawler/runs/{first_run['id']}/"
    details = await client.get(details_url, headers=headers)
    assert details.json()["owner"]["id"] == str(owner_id)
    assert details.json()["initiated_by"]["id"] == str(admin_user.id)
    assert details.json()["space_name"] == "Private source space"

    cancel_url = f"/api/v1/admin/crawler/runs/{first_run['id']}/cancel/"
    stopped = await client.post(cancel_url, headers=headers)
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["outcome"] == "cancelled"
    async with db_container(user=admin_user) as container:
        await container.session().execute(
            sa.delete(Jobs).where(Jobs.name == "https://example.test")
        )
    retained = await client.get(details_url, headers=headers)
    assert retained.json()["initiated_by"]["id"] == str(admin_user.id)

    rerun = await client.post(start_url, headers=headers)
    assert rerun.status_code == 200, rerun.text
    assert rerun.json()["id"] != first_run["id"]
    stale_cancel = await client.post(cancel_url, headers=headers)
    assert stale_cancel.json()["id"] == first_run["id"]
    assert stale_cancel.json()["outcome"] == "cancelled"
    current = await client.get(details_url, headers=headers)
    assert current.json()["active_run"]["id"] == rerun.json()["id"]

    for method, options in [
        ("get", {}),
        ("post", {"json": {"name": "Not permitted"}}),
        ("delete", {}),
    ]:
        response = await client.request(
            method, f"/api/v1/websites/{website_id}/", headers=headers, **options
        )
        assert response.status_code == 403, response.text
    async with db_container(user=admin_user) as container:
        session = container.session()
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(CrawlRuns)
                .where(CrawlRuns.website_id == website_id)
            )
            == 2
        )
        audit = (
            await session.scalars(
                sa.select(AuditLog).where(AuditLog.entity_id == website_id)
            )
        ).all()
        assert {entry.action for entry in audit} == {
            "website_crawl_requested",
            "website_crawl_stop_requested",
        }
        assert all(entry.actor_id == admin_user.id for entry in audit)


async def test_scheduled_crawl_does_not_attribute_a_manual_request_to_its_execution_user(
    client, db_container, admin_user, website_id, headers
):
    from eneo.websites.domain.crawl_run import CrawlOrigin

    async with db_container(user=admin_user) as container:
        website = await container.website_sparse_repo().one_for_tenant(
            website_id, admin_user.tenant_id
        )
        run = await container.crawl_service().crawl(
            website, CrawlOrigin.SCHEDULED, reconcile_after_commit=False
        )
        run_id = run.id
    response = await client.get(
        f"/api/v1/admin/crawler/runs/{run_id}/", headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["run"]["origin"] == "scheduled"
    assert response.json()["initiated_by"] is None


async def test_admin_crawl_and_audit_commit_together(
    client, db_container, admin_user, website_id, headers, monkeypatch
):
    from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
    from eneo.websites.domain import crawl_service

    dispatch = AsyncMock()
    monkeypatch.setattr(crawl_service, "reconcile_crawl_work", dispatch)
    monkeypatch.setattr(
        AuditLogRepositoryImpl,
        "create",
        AsyncMock(side_effect=RuntimeError("Audit write failed")),
    )
    with pytest.raises(RuntimeError, match="Audit write failed"):
        await client.post(
            f"/api/v1/admin/crawler/websites/{website_id}/run/", headers=headers
        )
    async with db_container(user=admin_user) as container:
        assert (
            await container.session().scalar(
                sa.select(sa.func.count())
                .select_from(CrawlRuns)
                .where(CrawlRuns.website_id == website_id)
            )
            == 0
        )
        assert (
            await container.session().scalar(
                sa.select(sa.func.count()).select_from(Jobs).where(Jobs.task == "crawl")
            )
            == 0
        )
    dispatch.assert_not_awaited()


async def test_service_admin_key_can_read_and_cancel_but_cannot_create_crawl_jobs(
    client, db_container, admin_user, website_id, headers, monkeypatch
):
    from datetime import timedelta

    from eneo.websites.domain import crawl_service
    from tests.integration.test_service_key_endpoint_gates import _create_service_key

    key = await _create_service_key(
        client,
        token=headers["Authorization"].removeprefix("Bearer "),
        scope_type="tenant",
        permission="admin",
        expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    )
    monkeypatch.setattr(crawl_service, "reconcile_crawl_work", AsyncMock())
    key_headers = {"X-API-Key": key["secret"]}
    assert (
        await client.get("/api/v1/admin/crawler/", headers=key_headers)
    ).status_code == 200
    response = await client.post(
        f"/api/v1/admin/crawler/websites/{website_id}/run/", headers=key_headers
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "service_key_cannot_create_resources"

    started = await client.post(
        f"/api/v1/admin/crawler/websites/{website_id}/run/", headers=headers
    )
    assert started.status_code == 200, started.text
    cancelled = await client.post(
        f"/api/v1/admin/crawler/runs/{started.json()['id']}/cancel/",
        headers=key_headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["outcome"] == "cancelled"
    async with db_container(user=admin_user) as container:
        audit = await container.session().scalar(
            sa.select(AuditLog).where(
                AuditLog.entity_id == website_id,
                AuditLog.action == "website_crawl_stop_requested",
            )
        )
        assert audit is not None
        assert audit.actor_id is None
        assert audit.log_metadata["actor"]["type"] == "service_key"
