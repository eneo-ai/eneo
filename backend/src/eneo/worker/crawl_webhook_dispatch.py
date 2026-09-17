"""Admit durable webhook requests into the crawler's attempt dispatcher."""

import asyncio
from uuid import UUID

import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.websites_table import Websites
from eneo.main.logging import get_logger
from eneo.websites.application.crawl_dispatch import reconcile_crawl_work
from eneo.websites.application.crawl_webhook import lock_website, prepare_run

logger = get_logger(__name__)


async def dispatch_website(website_id: UUID) -> None:
    # Admission is serialized in PostgreSQL. Dispatch uses the target crawler's
    # durable attempts, concurrency limits and crash recovery.
    async with sessionmanager.session() as session, session.begin():
        website = await lock_website(session, website_id)
        if website is None:
            return
        if await prepare_run(session, website) is None:
            return
    # Python crawler accounts for capacity in durable attempts, so cancelled
    # webhook runs must not separately decrement a Redis reservation.
    await reconcile_crawl_work()


async def dispatch_after_commit(website_id: UUID) -> None:
    try:
        await dispatch_website(website_id)
    except Exception:
        logger.exception(
            "Webhook dispatch failed", extra={"website_id": str(website_id)}
        )


async def reconcile() -> None:
    async with sessionmanager.session() as session, session.begin():
        ids = list(
            (
                await session.scalars(
                    sa.select(Websites.id).where(
                        Websites.webhook_pending.is_(True),
                        Websites.webhook_token_hash.is_not(None),
                        sa.or_(
                            Websites.next_retry_at.is_(None),
                            Websites.next_retry_at <= sa.func.now(),
                        ),
                    )
                )
            ).all()
        )
    for website_id in ids:
        await dispatch_after_commit(website_id)


async def run_forever() -> None:
    while True:
        try:
            await reconcile()
        except Exception:
            logger.exception("Webhook reconciliation failed")
        await asyncio.sleep(10)
