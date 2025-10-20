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
        self.website_sparse_repo = website_sparse_repo

    async def get_websites_due_for_crawl(self) -> list["WebsiteSparse"]:
        """Get all websites that are due for crawling today.

        Why: Delegates to repository for database-side filtering performance.
        Scales efficiently with 1000+ websites by leveraging database indexes.

        Returns:
            List of websites that should be crawled today
        """
        logger.info("Determining websites due for crawling")

        today = datetime.now(timezone.utc).date()  # Use UTC to match DB and cron
        due_websites = await self.website_sparse_repo.get_due_websites(today)

        logger.info(f"Found {len(due_websites)} websites due for crawling")

        # Log individual websites for observability
        for website in due_websites:
            logger.info(
                f"Website scheduled for crawl: {website.url} (interval: {website.update_interval})"
            )

        return due_websites

    def _is_website_due_for_crawl(
        self, website: "WebsiteSparse", today: datetime.date
    ) -> bool:
        """DEPRECATED: Logic moved to WebsiteSparseRepository.get_due_websites() for performance.

        Why: Database-side filtering is much faster with 1000+ websites.
        This method is kept for backwards compatibility but should not be used.

        Use get_websites_due_for_crawl() instead, which delegates to the repository.
        """
        # This method is no longer used by the service but kept for reference
        # All scheduling logic is now in WebsiteSparseRepository.get_due_websites()
        raise NotImplementedError(
            "This method is deprecated. Use get_websites_due_for_crawl() instead."
        )
