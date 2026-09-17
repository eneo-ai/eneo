"""Exercise the request/start/finish boundary with real independent DB sessions."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.spaces_table import SpacesUsers
from eneo.database.tables.websites_table import CrawlAttempts, CrawlRuns, Websites
from eneo.websites.application.crawl_webhook import (
    active_job,
    cancel_unstarted_webhook_runs,
    consume_on_start,
    issue_token,
    lock_website,
    prepare_run,
    request_crawl,
    revoke,
    verify_token,
)
from eneo.websites.domain.crawl_run import CrawlOutcome, CrawlType
from eneo.websites.domain.crawl_run_repo import CrawlRunRepository
from eneo.websites.domain.website import UpdateInterval
from eneo.websites.domain.website_sparse_repo import WebsiteSparseRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def webhook_site(db_session, admin_user, space_factory):
    token, digest = issue_token()
    async with db_session() as session:
        space = await space_factory(session, "Webhook test")
        session.add(SpacesUsers(space_id=space.id, user_id=admin_user.id, role="admin"))
        embedding_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
        site = Websites(
            id=uuid4(),
            name="Webhook",
            url="https://example.com/sitemap.xml",
            space_id=space.id,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_id,
            size=0,
            download_files=False,
            crawl_type=CrawlType.SITEMAP,
            update_interval=UpdateInterval.WEBHOOK,
            webhook_token_hash=digest,
        )
        session.add(site)
        await session.flush()
        site_id = site.id
    return site_id, token


async def post(db_session, site_id):
    async with db_session() as session:
        site = await lock_website(session, site_id)
        return await request_crawl(session, site)


async def start(db_session, site_id):
    async with db_session() as session:
        await lock_website(session, site_id)
        job = await active_job(session, site_id)
        attempt_id = await session.scalar(
            sa.select(CrawlAttempts.id).where(CrawlAttempts.dispatch_id == job.id)
        )
        assert await CrawlRunRepository(session).claim_attempt(
            attempt_id,
            dispatch_id=job.id,
            lease_owner="webhook-test",
            lease_duration=timedelta(minutes=5),
        )
        return job.id


async def finish(db_session, site_id, job_id):
    async with db_session() as session:
        site = await lock_website(session, site_id)
        attempt_id = await session.scalar(
            sa.select(CrawlAttempts.id).where(CrawlAttempts.dispatch_id == job_id)
        )
        assert await CrawlRunRepository(session).finish_attempt(
            attempt_id,
            lease_owner="webhook-test",
            outcome=CrawlOutcome.SUCCEEDED,
        )
        await prepare_run(session, site)


async def run_count(db_session, site_id):
    async with db_session() as session:
        return await session.scalar(
            sa.select(sa.func.count())
            .select_from(CrawlRuns)
            .where(CrawlRuns.website_id == site_id)
        )


async def test_concurrent_posts_coalesce_before_and_during_run(
    db_session, webhook_site
):
    site_id, _ = webhook_site
    results = await asyncio.gather(*(post(db_session, site_id) for _ in range(20)))
    assert results.count("queued") == 1
    assert await run_count(db_session, site_id) == 1
    job_id = await start(db_session, site_id)
    results = await asyncio.gather(*(post(db_session, site_id) for _ in range(20)))
    assert results.count("pending") == 1
    assert await run_count(db_session, site_id) == 1
    await finish(db_session, site_id, job_id)
    assert await run_count(db_session, site_id) == 2
    next_job_id = await start(db_session, site_id)
    await finish(db_session, site_id, next_job_id)
    assert await run_count(db_session, site_id) == 2


async def test_post_racing_finish_never_lost(db_session, webhook_site):
    site_id, _ = webhook_site
    await post(db_session, site_id)
    job_id = await start(db_session, site_id)
    await asyncio.gather(post(db_session, site_id), finish(db_session, site_id, job_id))
    assert await run_count(db_session, site_id) == 2


async def test_retry_does_not_consume_next_request(db_session, webhook_site):
    site_id, _ = webhook_site
    await post(db_session, site_id)
    job_id = await start(db_session, site_id)
    await post(db_session, site_id)
    async with db_session() as session:
        site = await lock_website(session, site_id)
        await consume_on_start(session, site, job_id)
        assert site.webhook_pending
    await finish(db_session, site_id, job_id)
    assert await run_count(db_session, site_id) == 2


async def test_backoff_and_disable(db_session, webhook_site):
    site_id, token = webhook_site
    async with db_session() as session:
        site = await lock_website(session, site_id)
        site.next_retry_at = datetime.now(timezone.utc) + timedelta(hours=1)
    assert await post(db_session, site_id) == "pending"
    assert await run_count(db_session, site_id) == 0
    async with db_session() as session:
        site = await lock_website(session, site_id)
        site.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await prepare_run(session, site)
    assert await run_count(db_session, site_id) == 1
    async with db_session() as session:
        site = await lock_website(session, site_id)
        revoke(site)
        site.update_interval = UpdateInterval.NEVER
        await cancel_unstarted_webhook_runs(session, site_id)
        assert not verify_token(token, site.webhook_token_hash)
        assert not site.webhook_pending
        assert await active_job(session, site_id) is None
        assert await prepare_run(session, site) is None


async def test_rollback_keeps_pending_request(db_session, webhook_site):
    site_id, _ = webhook_site
    with pytest.raises(RuntimeError):
        async with db_session() as session:
            site = await lock_website(session, site_id)
            await request_crawl(session, site)
            raise RuntimeError("transaction failed")
    assert await run_count(db_session, site_id) == 0
    assert await post(db_session, site_id) == "queued"


async def test_interval_scheduler_excludes_webhooks(db_session, webhook_site):
    site_id, _ = webhook_site
    async with db_session() as session:
        repo = WebsiteSparseRepository(session)
        assert site_id not in {x.id for x in await repo.get_websites_with_intervals()}
        assert site_id not in {
            x.id for x in await repo.get_due_websites(datetime.now(timezone.utc).date())
        }


async def test_http_auth_rate_limit_and_committed_acceptance(
    client,
    db_session,
    webhook_site,
    monkeypatch,
    test_settings,
):
    from eneo.worker import crawl_webhook_dispatch

    site_id, token = webhook_site
    monkeypatch.setattr(test_settings, "environment", "test")
    monkeypatch.setattr(test_settings, "crawl_webhook_rate_limit_per_minute", 2)
    dispatch = AsyncMock()
    monkeypatch.setattr(crawl_webhook_dispatch, "dispatch_after_commit", dispatch)
    url = f"/api/v1/webhooks/websites/{site_id}/crawl"
    assert (await client.post(url)).status_code == 401
    assert (
        await client.post(url, headers={"Authorization": "Bearer wrong"})
    ).status_code == 401
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        await client.post(f"/api/v1/webhooks/websites/{uuid4()}/crawl", headers=headers)
    ).status_code == 401
    response = await client.post(
        url, headers=headers, json={"url": "https://untrusted.invalid"}
    )
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"
    assert await run_count(db_session, site_id) == 1
    assert (await client.post(url, headers=headers)).json()["status"] == "coalesced"
    response = await client.post(url, headers=headers)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert await run_count(db_session, site_id) == 1


async def test_rotation_invalidates_previous_token(db_session, webhook_site):
    site_id, old_token = webhook_site
    new_token, digest = issue_token()
    async with db_session() as session:
        site = await lock_website(session, site_id)
        site.webhook_token_hash = digest
    async with db_session() as session:
        site = await lock_website(session, site_id)
        assert not verify_token(old_token, site.webhook_token_hash)
        assert verify_token(new_token, site.webhook_token_hash)
        assert new_token not in site.webhook_token_hash


async def test_dispatch_recovers_after_redis_failure_without_duplicate_job(
    db_session,
    webhook_site,
    redis_client,
    monkeypatch,
):
    from eneo.websites.application import crawl_dispatch
    from eneo.worker import crawl_webhook_dispatch as dispatch

    site_id, _ = webhook_site
    await post(db_session, site_id)
    async with db_session() as session:
        job_id = (await active_job(session, site_id)).id
    enqueue = AsyncMock(side_effect=[ConnectionError("Redis disconnected"), object()])
    discard = AsyncMock()

    async def reconcile():
        return await crawl_dispatch.reconcile_crawl_work(
            enqueue=enqueue, discard=discard
        )

    monkeypatch.setattr(dispatch, "reconcile_crawl_work", reconcile)
    await dispatch.dispatch_website(site_id)
    async with db_session() as session:
        await session.execute(
            sa.update(CrawlAttempts)
            .where(CrawlAttempts.dispatch_id == job_id)
            .values(
                dispatch_attempted_at=datetime.now(timezone.utc) - timedelta(minutes=2)
            )
        )
    await dispatch.dispatch_website(site_id)
    assert enqueue.call_count == 2
    assert {call.args[1] for call in enqueue.call_args_list} == {job_id}
    assert await run_count(db_session, site_id) == 1
    await dispatch.dispatch_website(site_id)
    assert enqueue.call_count == 2


async def test_token_management_and_disable_api(
    client,
    db_session,
    webhook_site,
    admin_user_api_key,
    monkeypatch,
    test_settings,
):
    from eneo.worker import crawl_webhook_dispatch

    monkeypatch.setattr(test_settings, "environment", "test")
    monkeypatch.setattr(crawl_webhook_dispatch, "dispatch_after_commit", AsyncMock())
    site_id, old_token = webhook_site
    headers = {"X-API-Key": admin_user_api_key.key}
    token_path = f"/api/v1/websites/{site_id}/webhook/token/"
    assert (await client.post(token_path)).status_code in (401, 403)
    response = await client.post(token_path, headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    token = response.json()["token"]
    assert len(token) >= 43
    trigger = f"/api/v1/webhooks/websites/{site_id}/crawl"
    assert (
        await client.post(trigger, headers={"Authorization": f"Bearer {old_token}"})
    ).status_code == 401
    assert (
        await client.post(trigger, headers={"Authorization": f"Bearer {token}"})
    ).status_code == 202
    response = await client.get(f"/api/v1/websites/{site_id}/", headers=headers)
    assert response.status_code == 200, response.text
    assert token not in response.text
    assert response.json()["webhook_enabled"]
    response = await client.post(
        f"/api/v1/websites/{site_id}/",
        headers=headers,
        json={"update_interval": "daily"},
    )
    assert response.status_code == 200, response.text
    assert not response.json()["webhook_enabled"]
    assert (
        await client.post(trigger, headers={"Authorization": f"Bearer {token}"})
    ).status_code == 401
    async with db_session() as session:
        assert await active_job(session, site_id) is None


async def test_rate_limit_unavailable_rejects_without_accepting(
    client,
    db_session,
    webhook_site,
    monkeypatch,
    test_settings,
):
    from eneo.audit.infrastructure.rate_limiting import RateLimitServiceUnavailableError
    from eneo.websites.presentation import crawl_webhook_router

    monkeypatch.setattr(test_settings, "environment", "test")
    monkeypatch.setattr(
        crawl_webhook_router,
        "check_rate_limit",
        AsyncMock(side_effect=RateLimitServiceUnavailableError(ConnectionError())),
    )
    site_id, token = webhook_site
    response = await client.post(
        f"/api/v1/webhooks/websites/{site_id}/crawl",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert await run_count(db_session, site_id) == 0


async def test_viewer_cannot_rotate_token(
    client,
    db_session,
    webhook_site,
    admin_user,
    admin_user_api_key,
):
    site_id, token = webhook_site
    async with db_session() as session:
        site = await lock_website(session, site_id)
        await session.execute(
            sa.update(SpacesUsers)
            .where(
                SpacesUsers.space_id == site.space_id,
                SpacesUsers.user_id == admin_user.id,
            )
            .values(role="viewer")
        )
    response = await client.post(
        f"/api/v1/websites/{site_id}/webhook/token/",
        headers={"X-API-Key": admin_user_api_key.key},
    )
    assert response.status_code == 403
    async with db_session() as session:
        site = await lock_website(session, site_id)
        assert verify_token(token, site.webhook_token_hash)


async def test_webhook_rejects_basic_crawl_configuration(
    client,
    webhook_site,
    admin_user_api_key,
):
    site_id, _ = webhook_site
    response = await client.post(
        f"/api/v1/websites/{site_id}/",
        headers={"X-API-Key": admin_user_api_key.key},
        json={"crawl_type": "crawl"},
    )
    assert response.status_code == 400


async def test_webhook_migration_roundtrip(db_session, webhook_site):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/202609161000_crawl_webhook.py"
    )
    spec = importlib.util.spec_from_file_location("webhook_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    site_id, _ = webhook_site

    def roundtrip(connection):
        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()
        assert "webhook_pending" not in {
            c["name"] for c in sa.inspect(connection).get_columns("websites")
        }
        assert (
            connection.execute(
                sa.text("SELECT update_interval FROM websites WHERE id = :id"),
                {"id": site_id},
            ).scalar_one()
            == "never"
        )
        migration.upgrade()
        assert connection.execute(
            sa.text(
                "SELECT webhook_pending, webhook_token_hash FROM websites WHERE id = :id"
            ),
            {"id": site_id},
        ).one() == (False, None)

    async with db_session() as session:
        connection = await session.connection()
        await connection.run_sync(roundtrip)


async def test_concurrent_settings_edits_in_same_space(
    client, db_session, webhook_site, admin_user_api_key, monkeypatch
):
    from eneo.websites.application import crawl_webhook

    site_id, _ = webhook_site
    other_id = uuid4()
    async with db_session() as session:
        site = await session.get(Websites, site_id)
        session.add(
            Websites(
                id=other_id,
                name="Other",
                url="https://example.org/sitemap.xml",
                space_id=site.space_id,
                tenant_id=site.tenant_id,
                user_id=site.user_id,
                embedding_model_id=site.embedding_model_id,
                size=0,
                download_files=False,
                crawl_type=CrawlType.SITEMAP,
                update_interval=UpdateInterval.NEVER,
            )
        )

    original_lock = crawl_webhook.lock_website

    async def slow_lock(session, website_id):
        result = await original_lock(session, website_id)
        # Give the other request time to acquire its website lock if the common
        # space lock was not taken first (the previous implementation deadlocked).
        await asyncio.sleep(0.3)
        return result

    monkeypatch.setattr(crawl_webhook, "lock_website", slow_lock)
    headers = {"X-API-Key": admin_user_api_key.key}
    responses = await asyncio.wait_for(
        asyncio.gather(
            *(
                client.post(
                    f"/api/v1/websites/{id}/", headers=headers, json={"name": name}
                )
                for id, name in [(site_id, "First edited"), (other_id, "Second edited")]
            )
        ),
        timeout=15,
    )
    for response in responses:
        assert response.status_code == 200, response.text
    async with db_session() as session:
        assert (await session.get(Websites, site_id)).name == "First edited"
        assert (await session.get(Websites, other_id)).name == "Second edited"


async def test_cancelled_webhook_releases_only_its_durable_capacity(
    db_session,
    webhook_site,
):
    site_id, _ = webhook_site
    await post(db_session, site_id)
    async with db_session() as session:
        repo = CrawlRunRepository(session)
        claims = await repo.claim_dispatch_candidates(
            concurrency_limit=1,
            retry_after=timedelta(minutes=1),
            redeliver_after=timedelta(minutes=5),
        )
        assert len(claims) == 1
        cancelled_id = claims[0].dispatch_id
        site = await lock_website(session, site_id)
        await cancel_unstarted_webhook_runs(session, site_id)
        await request_crawl(session, site)
    async with db_session() as session:
        repo = CrawlRunRepository(session)
        claims = await repo.claim_dispatch_candidates(
            concurrency_limit=1,
            retry_after=timedelta(minutes=1),
            redeliver_after=timedelta(minutes=5),
        )
        assert len(claims) == 1
        assert claims[0].dispatch_id != cancelled_id
    # Repeated cancellation cleanup must leave the new running attempt alone.
    await start(db_session, site_id)
    async with db_session() as session:
        site = await lock_website(session, site_id)
        await cancel_unstarted_webhook_runs(session, site_id)
        job = await active_job(session, site_id)
        assert job is not None and job.id != cancelled_id
        assert (
            await CrawlRunRepository(session).claim_dispatch_candidates(
                concurrency_limit=1,
                retry_after=timedelta(minutes=1),
                redeliver_after=timedelta(minutes=5),
            )
            == []
        )


@pytest.mark.parametrize("post_before_start", [True, False])
async def test_non_webhook_run_preserves_pending_followup(
    db_session, webhook_site, post_before_start
):
    from dependency_injector import providers

    from eneo.main.container.container import Container
    from eneo.websites.domain.website import WebsiteSparse

    site_id, _ = webhook_site
    async with db_session() as session:
        site = await lock_website(session, site_id)
        container = Container(session=providers.Object(session))
        user = await container.user_repo().get_user_by_id(site.user_id)
        container.user.override(providers.Object(user))
        container.tenant.override(providers.Object(user.tenant))
        run = await container.crawl_service().crawl(
            WebsiteSparse.to_domain(site),
            reconcile_after_commit=False,
        )
        job_id = run.job_id
    if post_before_start:
        await post(db_session, site_id)
    assert await start(db_session, site_id) == job_id
    if not post_before_start:
        await post(db_session, site_id)
        # A retry of an initial/manual crawl must preserve requests too.
        async with db_session() as session:
            site = await lock_website(session, site_id)
            await consume_on_start(session, site, job_id)
    async with db_session() as session:
        site = await lock_website(session, site_id)
        assert site.webhook_pending
        assert site.webhook_started_job_id is None
    await finish(db_session, site_id, job_id)
    assert await run_count(db_session, site_id) == 2
    followup_id = await start(db_session, site_id)
    assert followup_id != job_id
    async with db_session() as session:
        site = await lock_website(session, site_id)
        assert not site.webhook_pending
        assert site.webhook_started_job_id == followup_id
    await finish(db_session, site_id, followup_id)
    assert await run_count(db_session, site_id) == 2
