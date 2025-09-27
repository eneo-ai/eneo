from uuid import UUID

from dependency_injector import providers

from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.websites.crawl_dependencies.crawl_models import (
    CrawlTask,
)

logger = get_logger(__name__)


async def queue_website_crawls(container: Container, interval: "UpdateInterval" = "weekly"):
    """
    Queue crawl tasks for all websites with the specified update interval.

    This function is called by cron jobs to batch-queue crawl tasks for websites
    that are due for updates based on their configured interval.

    Args:
        container: Dependency injection container with session and repositories
        interval: The update interval to process (daily, every_other_day, weekly)

    Returns:
        bool: True if the queuing process completed (even if some individual
              websites failed to queue)

    Raises:
        Any database or validation errors that prevent the entire process
    """
    from intric.websites.domain.website import UpdateInterval

    # Convert string to enum if needed (for backward compatibility)
    if isinstance(interval, str):
        try:
            interval = UpdateInterval(interval)
        except ValueError:
            logger.error(f"Invalid update interval provided: {interval}")
            return False

    logger.info(f"Starting crawl queue process for interval: {interval}")

    user_repo = container.user_repo()
    website_sparse_repo = container.website_sparse_repo()

    queued_count = 0
    failed_count = 0

    async with container.session().begin():
        try:
            websites = await website_sparse_repo.get_websites_by_interval(interval)
            logger.info(f"Found {len(websites)} websites with interval '{interval}' to process")

            for website in websites:
                try:
                    logger.debug(f"Processing website: {website.url} (ID: {website.id})")

                    # Get user for this website
                    user = await user_repo.get_user_by_id(website.user_id)
                    container.user.override(providers.Object(user))
                    container.tenant.override(providers.Object(user.tenant))

                    crawl_service = container.crawl_service()

                    # Queue the crawl task
                    await crawl_service.crawl(website)
                    queued_count += 1

                    logger.debug(f"Successfully queued crawl for website: {website.url}")

                except Exception as e:
                    # Log the specific error but continue with other websites
                    failed_count += 1
                    logger.error(
                        f"Failed to queue crawl for website {website.url} (ID: {website.id}) "
                        f"with interval {interval}: {str(e)}",
                        exc_info=True  # Include stack trace for debugging
                    )

        except Exception as e:
            logger.error(f"Database error while fetching websites for interval {interval}: {str(e)}", exc_info=True)
            return False

    logger.info(
        f"Crawl queue process completed for interval '{interval}': "
        f"{queued_count} queued successfully, {failed_count} failed"
    )
    return True


async def crawl_task(*, job_id: UUID, params: CrawlTask, container: Container):
    """
    Execute a website crawl task in the background.

    This function performs the actual crawling of a website, processes the content,
    and updates the database with the results. It handles both pages and files,
    tracks success/failure metrics, and cleans up outdated content.

    Args:
        job_id: Unique identifier for this crawl job
        params: Crawl parameters including website_id, URL, auth credentials, etc.
        container: Dependency injection container with all required services

    Returns:
        bool: Task manager result indicating success/failure

    Note:
        This function is designed to be fault-tolerant - if individual pages or
        files fail to process, the crawl continues with the remaining content.
    """
    task_manager = container.task_manager(job_id=job_id)
    async with task_manager.set_status_on_exception():
        # Get resources
        crawler = container.crawler()
        uploader = container.text_processor()
        crawl_run_repo = container.crawl_run_repo()

        info_blob_repo = container.info_blob_repo()
        update_website_size_service = container.update_website_size_service()
        website_service = container.website_crud_service()

        # Validate website exists and get its configuration
        try:
            website = await website_service.get_website(params.website_id)
            logger.info(
                f"Starting crawl task for website '{website.name}' ({website.url}) "
                f"- Job ID: {job_id}, Run ID: {params.run_id}"
            )
        except Exception as e:
            logger.error(f"Failed to get website {params.website_id} for crawl job {job_id}: {str(e)}")
            raise

        # Initialize metrics tracking
        num_pages = 0
        num_files = 0
        num_failed_pages = 0
        num_failed_files = 0
        num_deleted_blobs = 0

        # Unfortunately, in this type of background task we still need to care about the session atm
        session = container.session()

        # Get existing content to identify what should be cleaned up after crawl
        try:
            existing_titles = await info_blob_repo.get_titles_of_website(params.website_id)
            logger.debug(f"Found {len(existing_titles)} existing content items for cleanup comparison")
        except Exception as e:
            logger.error(f"Failed to get existing titles for website {params.website_id}: {str(e)}")
            existing_titles = []  # Continue without cleanup if this fails

        crawled_titles = []

        # Execute the actual crawl
        logger.info(f"Starting crawler for URL: {params.url} (type: {params.crawl_type})")
        try:
            async with crawler.crawl(
                url=params.url,
                download_files=params.download_files,
                crawl_type=params.crawl_type,
                http_user=params.http_user,
                http_pass=params.http_pass,
            ) as crawl:
                logger.info(f"Crawler started successfully, processing content...")

                # Process pages
                for page in crawl.pages:
                    num_pages += 1
                    try:
                        title = page.url
                        logger.debug(f"Processing page: {title}")

                        async with session.begin_nested():
                            await uploader.process_text(
                                text=page.content,
                                title=title,
                                website_id=params.website_id,
                                url=page.url,
                                embedding_model=website.embedding_model,
                            )
                        crawled_titles.append(title)

                        # Log progress every 10 pages for long crawls
                        if num_pages % 10 == 0:
                            logger.info(f"Processed {num_pages} pages so far...")

                    except Exception as e:
                        num_failed_pages += 1
                        logger.error(
                            f"Failed to process page {page.url}: {str(e)}",
                            exc_info=True
                        )

                # Process files (if enabled)
                if params.download_files:
                    logger.info("Processing downloaded files...")
                    for file in crawl.files:
                        num_files += 1
                        try:
                            filename = file.stem
                            logger.debug(f"Processing file: {filename}")

                            async with session.begin_nested():
                                await uploader.process_file(
                                    filepath=file,
                                    filename=filename,
                                    website_id=params.website_id,
                                    embedding_model=website.embedding_model,
                                )

                            crawled_titles.append(filename)

                            # Log progress every 5 files
                            if num_files % 5 == 0:
                                logger.info(f"Processed {num_files} files so far...")

                        except Exception as e:
                            num_failed_files += 1
                            logger.error(
                                f"Failed to process file {file}: {str(e)}",
                                exc_info=True
                            )

                # Clean up outdated content (remove items that were not found in this crawl)
                logger.info("Starting content cleanup...")
                for title in existing_titles:
                    if title not in crawled_titles:
                        try:
                            num_deleted_blobs += 1
                            await info_blob_repo.delete_by_title_and_website(
                                title=title, website_id=params.website_id
                            )
                            logger.debug(f"Deleted outdated content: {title}")
                        except Exception as e:
                            logger.error(
                                f"Failed to delete outdated content '{title}': {str(e)}",
                                exc_info=True
                            )
                            # Don't fail the entire crawl if cleanup fails
                            num_deleted_blobs -= 1

                # Update website size metrics
                try:
                    await update_website_size_service.update_website_size(website_id=website.id)
                    logger.debug("Website size metrics updated successfully")
                except Exception as e:
                    logger.error(
                        f"Failed to update website size for {params.website_id}: {str(e)}",
                        exc_info=True
                    )
                    # Continue even if size update fails

                # Log comprehensive crawl results
                success_rate_pages = ((num_pages - num_failed_pages) / num_pages * 100) if num_pages > 0 else 100
                success_rate_files = ((num_files - num_failed_files) / num_files * 100) if num_files > 0 else 100

                logger.info(
                    f"Crawl completed for '{website.name}' ({website.url}):\n"
                    f"  Pages: {num_pages} processed, {num_failed_pages} failed ({success_rate_pages:.1f}% success)\n"
                    f"  Files: {num_files} processed, {num_failed_files} failed ({success_rate_files:.1f}% success)\n"
                    f"  Cleanup: {num_deleted_blobs} outdated items removed\n"
                    f"  Job ID: {job_id}, Run ID: {params.run_id}"
                )

                # Update the crawl run record with final metrics
                try:
                    crawl_run = await crawl_run_repo.one(params.run_id)
                    crawl_run.update(
                        pages_crawled=num_pages,
                        files_downloaded=num_files,
                        pages_failed=num_failed_pages,
                        files_failed=num_failed_files,
                    )
                    await crawl_run_repo.update(crawl_run)
                    logger.debug(f"Crawl run record updated successfully for run {params.run_id}")
                except Exception as e:
                    logger.error(
                        f"Failed to update crawl run record {params.run_id}: {str(e)}",
                        exc_info=True
                    )
                    # This is important but shouldn't fail the entire task

        except Exception as e:
            logger.error(
                f"Crawler failed for website {website.url} (ID: {params.website_id}): {str(e)}",
                exc_info=True
            )
            # Re-raise to let task manager handle the failure
            raise

        task_manager.result_location = f"/api/v1/websites/{params.website_id}/info-blobs/"

    return task_manager.successful()
