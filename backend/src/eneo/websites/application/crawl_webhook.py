"""Durable, coalescing crawl requests. All transitions lock the website first.

The pending bit is consumed at actual worker start, not at enqueue time. The
outbox lives on CrawlRuns and is committed with its Job, before touching Redis.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.job_table import Jobs
from eneo.database.tables.websites_table import CrawlRuns, Websites
from eneo.main.models import Status
from eneo.websites.domain.crawl_run import CrawlType, CrawlPhase, CrawlOrigin
from eneo.websites.domain.crawl_run_repo import CrawlRunRepository
from eneo.websites.domain.website import UpdateInterval

WEBHOOK_CANCELLED = "Webhook disabled before crawl start"

ACTIVE = (Status.QUEUED.value, Status.IN_PROGRESS.value)


def issue_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).hexdigest()


def verify_token(token: str, stored_hash: str | None) -> bool:
    digest = hashlib.sha256(token.encode()).hexdigest()
    return (
        hmac.compare_digest(digest, stored_hash or "0" * 64) and stored_hash is not None
    )


async def lock_website(session: AsyncSession, website_id: UUID) -> Websites | None:
    return await session.scalar(
        sa.select(Websites)
        .where(Websites.id == website_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def active_job(session: AsyncSession, website_id: UUID) -> Jobs | None:
    return await session.scalar(
        sa.select(Jobs)
        .join(CrawlRuns, CrawlRuns.job_id == Jobs.id)
        .where(CrawlRuns.website_id == website_id, CrawlRuns.phase != CrawlPhase.TERMINAL.value)
        .order_by(Jobs.created_at, Jobs.id)
        .limit(1)
    )


def revoke(website: Websites) -> None:
    website.webhook_token_hash = None
    website.webhook_pending = False


async def cancel_unstarted_webhook_runs(
    session: AsyncSession, website_id: UUID
) -> None:
    """Invalidate durable runs as well as any copies already in ARQ."""
    runs = list(
        (
            await session.scalars(
                sa.select(CrawlRuns).where(
                    CrawlRuns.website_id == website_id,
                    CrawlRuns.webhook_dispatch.is_not(None),
                    CrawlRuns.phase.in_([CrawlPhase.PENDING_DISPATCH.value, CrawlPhase.QUEUED.value]),
                )
            )
        ).all()
    )
    for run in runs:
        await CrawlRunRepository(session).request_cancel(run.id)
        run.webhook_dispatch = None


async def prepare_run(session: AsyncSession, website: Websites) -> Jobs | None:
    """Caller holds website lock. Persist a run only when eligible and idle."""
    if (
        not website.webhook_pending
        or not website.webhook_token_hash
        or website.update_interval != UpdateInterval.WEBHOOK
        or website.crawl_type != CrawlType.SITEMAP
    ):
        return None
    if website.next_retry_at and website.next_retry_at > datetime.now(timezone.utc):
        return None
    current = await active_job(session, website.id)
    if current:
        return current
    from dependency_injector import providers

    from eneo.main.container.container import Container
    from eneo.websites.domain.website import WebsiteSparse

    container = Container(session=providers.Object(session))
    user = await container.user_repo().get_user_by_id(website.user_id)
    if user is None:
        return None
    container.user.override(providers.Object(user))
    container.tenant.override(providers.Object(user.tenant))
    run = await container.crawl_service().crawl(
        WebsiteSparse.to_domain(website),
        origin=CrawlOrigin.SCHEDULED,
        reconcile_after_commit=False,
    )
    # Attempts already provide a transactional outbox on this crawler. This
    # marker records provenance until the first successful worker claim only.
    await session.execute(
        sa.update(CrawlRuns).where(CrawlRuns.id == run.id).values(webhook_dispatch={})
    )
    return await session.get(Jobs, run.job_id)


async def request_crawl(session: AsyncSession, website: Websites) -> str:
    """Caller authenticated and locked website. Persist before acknowledging."""
    current = await active_job(session, website.id)
    already_pending = website.webhook_pending
    website.webhook_pending = True
    if current:
        if current.status == Status.QUEUED.value:
            return "coalesced"
        return "coalesced" if already_pending else "pending"
    await prepare_run(session, website)
    if already_pending:
        return "coalesced"
    return (
        "pending"
        if website.next_retry_at and website.next_retry_at > datetime.now(timezone.utc)
        else "queued"
    )


async def consume_on_start(
    session: AsyncSession, website: Websites, job_id: UUID
) -> None:
    # Only a run admitted by the webhook dispatcher can consume its request.
    # Initial/manual crawls have no outbox; retries already cleared theirs.
    run_id = await session.scalar(
        sa.update(CrawlRuns)
        .where(
            CrawlRuns.website_id == website.id,
            CrawlRuns.job_id == job_id,
            CrawlRuns.webhook_dispatch.is_not(None),
        )
        .values(webhook_dispatch=None)
        .returning(CrawlRuns.id)
    )
    if run_id is not None and website.webhook_started_job_id != job_id:
        website.webhook_pending = False
        website.webhook_started_job_id = job_id
