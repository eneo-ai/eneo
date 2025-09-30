"""Service for determining which websites need crawling based on their update intervals.

Why: Centralizes scheduling logic for better maintainability and testing.
Engine-agnostic design allows future crawler engines without changes.
"""

from datetime import datetime
from typing import List, TYPE_CHECKING
import logging

from intric.websites.domain.website import UpdateInterval

if TYPE_CHECKING:
    from intric.websites.domain.website import WebsiteSparse
    from intric.websites.infrastructure.website_sparse_repo import WebsiteSparseRepository

logger = logging.getLogger(__name__)


class CrawlSchedulerService:
    """Service for scheduling website crawls based on update intervals.

    Why: Separates scheduling concerns from crawling logic.
    Enables easy testing and future scheduling enhancements.
    """

    def __init__(self, website_sparse_repo: "WebsiteSparseRepository"):
        self.website_sparse_repo = website_sparse_repo

    async def get_websites_due_for_crawl(self) -> List["WebsiteSparse"]:
        """Get all websites that are due for crawling today.

        Why: Single method that handles all interval types consistently.
        Uses reliable date comparison instead of day-of-year arithmetic.

        Returns:
            List of websites that should be crawled today
        """
        logger.info("Determining websites due for crawling")

        # Get all websites with active update intervals
        all_websites = await self.website_sparse_repo.get_websites_with_intervals()

        logger.info(f"Found {len(all_websites)} websites with active intervals")

        due_websites = []
        today = datetime.now().date()

        for website in all_websites:
            try:
                is_due = self._is_website_due_for_crawl(website, today)
                if is_due:
                    due_websites.append(website)
                    logger.info(f"Website scheduled for crawl: {website.url} (interval: {website.update_interval})")
                else:
                    logger.info(
                        f"Website not due: {website.url} (interval: {website.update_interval}, "
                        f"last_crawled_at: {website.last_crawled_at})"
                    )

            except Exception as e:
                # Why: Individual website errors shouldn't stop the entire crawl batch
                logger.warning(f"Error checking crawl schedule for {website.url}: {str(e)}")
                continue

        logger.info(f"Found {len(due_websites)} websites due for crawling")
        return due_websites

    def _is_website_due_for_crawl(self, website: "WebsiteSparse", today: datetime.date) -> bool:
        """Determine if a website is due for crawling based on its interval and last crawl time.

        Why: Uses last_crawled_at instead of updated_at to prevent settings changes
        from resetting the crawl schedule. More accurate crawl interval tracking.

        Args:
            website: Website to check
            today: Current date

        Returns:
            True if website should be crawled today
        """
        if website.update_interval == UpdateInterval.NEVER:
            return False

        # Get last crawl date - when was this website last crawled?
        last_crawl_date = website.last_crawled_at.date() if website.last_crawled_at else None

        if last_crawl_date is None:
            # Why: New websites (never crawled) should be crawled immediately
            logger.info(f"Website {website.url} has never been crawled - scheduling for initial crawl")
            return True

        days_since_crawl = (today - last_crawl_date).days
        logger.debug(
            f"Checking {website.url}: last_crawled={last_crawl_date}, "
            f"today={today}, days_since={days_since_crawl}, interval={website.update_interval}"
        )

        if website.update_interval == UpdateInterval.DAILY:
            # Why: Daily crawls should happen every day (minimum 1 day gap)
            return days_since_crawl >= 1

        elif website.update_interval == UpdateInterval.EVERY_OTHER_DAY:
            # Why: Every other day means minimum 2 day gap between crawls
            return days_since_crawl >= 2

        elif website.update_interval == UpdateInterval.WEEKLY:
            # Why: Weekly crawls should maintain existing behavior (7 day minimum gap)
            # Also check if today is Friday to preserve existing scheduling pattern
            is_friday = today.weekday() == 4
            is_week_old = days_since_crawl >= 7

            # Why: Either it's the weekly schedule day (Friday) OR it's overdue
            return is_friday and is_week_old

        else:
            # Why: Unknown interval types should not be crawled (fail safe)
            logger.warning(f"Unknown update interval: {website.update_interval}")
            return False