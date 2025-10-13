import asyncio
import time
from datetime import datetime
from uuid import UUID

from dependency_injector import providers
import sqlalchemy as sa

from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.main.config import SETTINGS
from intric.websites.crawl_dependencies.crawl_models import (
    CrawlTask,
)

logger = get_logger(__name__)


async def process_page_with_retry(
    page,
    uploader,
    session,
    params,
    website,
    max_retries: int | None = None,
    retry_delay: float | None = None
) -> tuple[bool, str | None]:
    """Process a single page with retry logic.

    Args:
        page: CrawledPage object
        uploader: Text processor
        session: Database session
        params: CrawlTask parameters
        website: Website entity
        max_retries: Maximum retry attempts (defaults to SETTINGS.crawl_page_max_retries)
        retry_delay: Initial delay between retries in seconds (defaults to SETTINGS.crawl_page_retry_delay)

    Returns:
        Tuple of (success: bool, error_message: str | None)
    """
    if max_retries is None:
        max_retries = SETTINGS.crawl_page_max_retries
    if retry_delay is None:
        retry_delay = SETTINGS.crawl_page_retry_delay

    for attempt in range(max_retries):
        try:
            # Create explicit savepoint for proper transaction handling
            savepoint = await session.begin_nested()
            try:
                await uploader.process_text(
                    text=page.content,
                    title=page.url,
                    website_id=params.website_id,
                    url=page.url,
                    embedding_model=website.embedding_model,
                )
                await savepoint.commit()
                return True, None  # Success
            except Exception:
                await savepoint.rollback()
                raise  # Re-raise to trigger retry logic

        except Exception as e:
            if attempt < max_retries - 1:
                # Calculate exponential backoff: 1s, 2s, 4s
                delay = retry_delay * (2 ** attempt)
                logger.warning(
                    f"Failed to process page {page.url} (attempt {attempt + 1}/{max_retries}): {str(e)}. "
                    f"Retrying in {delay}s...",
                    extra={
                        "website_id": str(params.website_id),
                        "tenant_id": str(website.tenant_id),
                        "page_url": page.url,
                        "attempt": attempt + 1,
                        "max_retries": max_retries,
                    }
                )
                await asyncio.sleep(delay)
            else:
                # Final attempt failed
                error_msg = f"Failed after {max_retries} attempts: {str(e)}"
                logger.error(
                    f"Permanently failed to process page {page.url}: {error_msg}",
                    extra={
                        "website_id": str(params.website_id),
                        "tenant_id": str(website.tenant_id),
                        "page_url": page.url,
                        "attempts": max_retries,
                    }
                )
                return False, error_msg

    return False, "Unknown error"


async def queue_website_crawls(container: Container):
    """Queue websites for crawling based on their update intervals.

    Why: Uses centralized scheduler service for maintainable interval logic.
    Properly handles DAILY, EVERY_OTHER_DAY, and WEEKLY intervals.
    """
    user_repo = container.user_repo()
    crawl_scheduler_service = container.crawl_scheduler_service()

    async with container.session().begin():
        # Why: Use scheduler service instead of direct repo call for better abstraction
        websites = await crawl_scheduler_service.get_websites_due_for_crawl()

        logger.info(f"Processing {len(websites)} websites due for crawling")

        successful_crawls = 0
        failed_crawls = 0

        for website in websites:
            try:
                # Get user for this website
                user = await user_repo.get_user_by_id(website.user_id)
                container.user.override(providers.Object(user))
                container.tenant.override(providers.Object(user.tenant))

                crawl_service = container.crawl_service()
                await crawl_service.crawl(website)
                successful_crawls += 1

                logger.debug(f"Successfully queued crawl for {website.url}")

            except Exception as e:
                # Why: Individual website failures shouldn't stop the entire batch
                failed_crawls += 1
                logger.error(
                    f"Failed to queue crawl for {website.url}: {str(e)}",
                    extra={
                        "website_id": str(website.id),
                        "tenant_id": str(website.tenant_id),
                        "space_id": str(website.space_id),
                        "user_id": str(website.user_id),
                    }
                )
                continue

        logger.info(f"Crawl queueing completed: {successful_crawls} successful, {failed_crawls} failed")

    return True


async def crawl_task(*, job_id: UUID, params: CrawlTask, container: Container):
    task_manager = container.task_manager(job_id=job_id)
    async with task_manager.set_status_on_exception():
        # Initialize timing tracking for performance analysis
        timings = {
            'fetch_existing_titles': 0.0,
            'crawl_and_parse': 0.0,
            'process_pages': 0.0,
            'process_files': 0.0,
            'cleanup_deleted': 0.0,
            'update_size': 0.0,
        }

        # Get resources
        crawler = container.crawler()
        uploader = container.text_processor()
        crawl_run_repo = container.crawl_run_repo()

        info_blob_repo = container.info_blob_repo()
        update_website_size_service = container.update_website_size_service()
        website_service = container.website_crud_service()
        website = await website_service.get_website(params.website_id)

        # CRITICAL: Verify tenant isolation
        current_tenant = container.tenant()
        if website.tenant_id != current_tenant.id:
            logger.error(
                "Tenant isolation violation detected",
                extra={
                    "website_id": str(params.website_id),
                    "website_tenant_id": str(website.tenant_id),
                    "container_tenant_id": str(current_tenant.id),
                }
            )
            raise Exception(
                f"Tenant isolation violation: website {params.website_id} "
                f"belongs to tenant {website.tenant_id}, not {current_tenant.id}"
            )

        # Do task
        logger.info(f"Running crawl with params: {params}")

        # Extract HTTP auth credentials if present
        http_user = None
        http_pass = None
        if website.http_auth:
            http_user = website.http_auth.username
            http_pass = website.http_auth.password
            logger.info(
                "HTTP auth configured for website",
                extra={
                    "website_id": str(params.website_id),
                    "tenant_id": str(website.tenant_id),
                }
            )

        num_pages = 0
        num_files = 0
        num_failed_pages = 0
        num_failed_files = 0
        num_deleted_blobs = 0

        # Unfortunately, in this type of background task we still need to care about the session atm
        session = container.session()

        # Check if auth was configured but decryption failed
        # Why: Fail-fast with clear error message instead of confusing 401 errors during crawl
        # If database has auth fields but domain object doesn't, decryption failed
        from intric.database.tables.websites_table import Websites as WebsitesTable
        website_db_check = await session.execute(
            sa.select(WebsitesTable.http_auth_username).where(WebsitesTable.id == params.website_id)
        )
        has_auth_in_db = website_db_check.scalar() is not None

        if has_auth_in_db and website.http_auth is None:
            logger.error(
                "Cannot crawl website: HTTP auth decryption failed. "
                "Check WEBSITE_AUTH_ENCRYPTION_KEY is correct.",
                extra={
                    "website_id": str(params.website_id),
                    "tenant_id": str(website.tenant_id),
                }
            )
            raise Exception(
                f"HTTP auth decryption failed for website {params.website_id}. "
                "Check WEBSITE_AUTH_ENCRYPTION_KEY configuration."
            )

        # Measure time to fetch existing titles
        start = time.time()
        existing_titles = await info_blob_repo.get_titles_of_website(params.website_id)
        timings['fetch_existing_titles'] = time.time() - start

        # ✅ PERFORMANCE FIX: Use set instead of list for O(1) membership tests
        # This changes O(n²) to O(n) when checking "if title not in crawled_titles"
        crawled_titles = set()

        # Use Scrapy crawler to process website content
        # Measure crawl and parse phase
        start = time.time()
        async with crawler.crawl(
            url=params.url,
            download_files=params.download_files,
            crawl_type=params.crawl_type,
            http_user=http_user,  # Pass auth credentials as strings
            http_pass=http_pass,
        ) as crawl:
            timings['crawl_and_parse'] = time.time() - start

            # Measure page processing time
            process_start = time.time()
            # Process pages with retry logic
            for page in crawl.pages:
                num_pages += 1

                # Use retry logic for each page
                success, error_message = await process_page_with_retry(
                    page=page,
                    uploader=uploader,
                    session=session,
                    params=params,
                    website=website,
                )

                if success:
                    # ✅ PERFORMANCE FIX: Use set.add() instead of list.append()
                    crawled_titles.add(page.url)
                else:
                    num_failed_pages += 1
                    logger.error(
                        f"Failed page: {page.url} - {error_message}",
                        extra={
                            "website_id": str(params.website_id),
                            "tenant_id": str(website.tenant_id),
                            "page_url": page.url,
                        }
                    )
            timings['process_pages'] = time.time() - process_start

            # Measure file processing time
            file_start = time.time()
            # Process downloaded files
            for file in crawl.files:
                num_files += 1
                try:
                    filename = file.stem
                    # Create explicit savepoint for proper transaction handling
                    savepoint = await session.begin_nested()
                    try:
                        await uploader.process_file(
                            filepath=file,
                            filename=filename,
                            website_id=params.website_id,
                            embedding_model=website.embedding_model,
                        )
                        await savepoint.commit()
                        # ✅ PERFORMANCE FIX: Use set.add() instead of list.append()
                        crawled_titles.add(filename)
                    except Exception:
                        await savepoint.rollback()
                        raise
                except Exception:
                    logger.exception(
                        "Exception while uploading file",
                        extra={
                            "website_id": str(params.website_id),
                            "tenant_id": str(website.tenant_id),
                            "filename": filename,
                        }
                    )
                    num_failed_files += 1
            timings['process_files'] = time.time() - file_start

        # Measure cleanup phase (delete stale blobs)
        cleanup_start = time.time()
        # ✅ PERFORMANCE FIX: Batch delete instead of N individual queries
        # Collect stale titles (set difference is O(n))
        stale_titles = [title for title in existing_titles if title not in crawled_titles]

        # Batch delete in ONE query instead of N individual queries
        if stale_titles:
            num_deleted_blobs = await info_blob_repo.batch_delete_by_titles_and_website(
                titles=stale_titles, website_id=params.website_id
            )
            if num_deleted_blobs > 0:
                logger.info(
                    f"Batch deleted {num_deleted_blobs} stale blobs",
                    extra={
                        "website_id": str(params.website_id),
                        "num_stale": len(stale_titles),
                        "num_deleted": num_deleted_blobs,
                    }
                )
        else:
            num_deleted_blobs = 0
        timings['cleanup_deleted'] = time.time() - cleanup_start

        # Measure website size update
        update_start = time.time()
        await update_website_size_service.update_website_size(website_id=website.id)
        timings['update_size'] = time.time() - update_start

        # Update last_crawled_at timestamp
        # Why: Track crawl completion time independently from record updates
        from intric.database.tables.websites_table import Websites as WebsitesTable
        stmt = (
            sa.update(WebsitesTable)
            .where(WebsitesTable.id == params.website_id)
            .where(WebsitesTable.tenant_id == website.tenant_id)  # Tenant isolation
            .values(last_crawled_at=datetime.now())
        )
        await session.execute(stmt)

        logger.info(
            f"Crawler finished. {num_pages} pages, {num_failed_pages} failed. "
            f"{num_files} files, {num_failed_files} failed. "
            f"{num_deleted_blobs} blobs deleted."
        )

        # Performance breakdown log for analysis
        total_time = sum(timings.values())
        logger.info(
            f"Performance breakdown: "
            f"fetch_existing={timings['fetch_existing_titles']:.2f}s, "
            f"crawl_parse={timings['crawl_and_parse']:.2f}s, "
            f"process_pages={timings['process_pages']:.2f}s, "
            f"process_files={timings['process_files']:.2f}s, "
            f"cleanup={timings['cleanup_deleted']:.2f}s, "
            f"update_size={timings['update_size']:.2f}s, "
            f"total_measured={total_time:.2f}s",
            extra={
                "timings": timings,
                "pages_crawled": num_pages,
                "pages_failed": num_failed_pages,
                "files_crawled": num_files,
                "files_failed": num_failed_files,
                "blobs_deleted": num_deleted_blobs,
            }
        )

        crawl_run = await crawl_run_repo.one(params.run_id)
        crawl_run.update(
            pages_crawled=num_pages,
            files_downloaded=num_files,
            pages_failed=num_failed_pages,
            files_failed=num_failed_files,
        )
        await crawl_run_repo.update(crawl_run)

        task_manager.result_location = f"/api/v1/websites/{params.website_id}/info-blobs/"

    return task_manager.successful()
