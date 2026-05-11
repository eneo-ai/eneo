"""Service for determining which websites need crawling based on their update intervals.

Why: Centralizes scheduling logic for better maintainability and testing.
Engine-agnostic design allows future crawler engines without changes.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.websites.domain.website import WebsiteSparse
    from intric.websites.domain.website_sparse_repo import WebsiteSparseRepository

logger = get_logger(__name__)


class CrawlSchedulerService:
    """Service for scheduling website crawls based on update intervals.

    Why: Separates scheduling concerns from crawling logic.
    Enables easy testing and future scheduling enhancements.
    """

    def __init__(self, website_sparse_repo: "WebsiteSparseRepository"):
        super().__init__()
        self.website_sparse_repo = website_sparse_repo

    async def get_websites_due_for_crawl(self) -> list["WebsiteSparse"]:
        """Get all websites that are due at this scheduler tick.

        Why: Delegates to repository for database-side filtering performance.
        Scales efficiently with 1000+ websites by leveraging database indexes.

        Returns:
            List of websites that should be crawled now
        """
        logger.info("Determining websites due for crawling")

        as_of = datetime.now(timezone.utc)  # Use UTC to match DB and cron
        due_websites = await self.website_sparse_repo.get_due_websites(as_of)

        logger.info(f"Found {len(due_websites)} websites due for crawling")

        # Log individual websites for observability
        for website in due_websites:
            logger.info(
                f"Website scheduled for crawl: {website.url} (interval: {website.update_interval})"
            )

        return due_websites
