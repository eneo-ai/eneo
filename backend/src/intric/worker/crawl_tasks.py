from uuid import UUID

from dependency_injector import providers

from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.websites.crawl_dependencies.crawl_models import (
    CrawlTask,
)
from intric.crawler.engines import get_engine
from intric.websites.domain.crawler_engine import CrawlerEngine

logger = get_logger(__name__)


async def queue_website_crawls(container: Container):
    user_repo = container.user_repo()
    website_sparse_repo = container.website_sparse_repo()

    async with container.session().begin():
        websites = await website_sparse_repo.get_weekly_websites()

        for website in websites:
            try:
                # Get user
                user = await user_repo.get_user_by_id(website.user_id)
                container.user.override(providers.Object(user))
                container.tenant.override(providers.Object(user.tenant))

                crawl_service = container.crawl_service()

                await crawl_service.crawl(website)
            except Exception as e:
                # If a website fails to queue, try the next one
                logger.error(f"Error when queueing up website {website.url}: {e}")

    return True


async def crawl_task(*, job_id: UUID, params: CrawlTask, container: Container):
    task_manager = container.task_manager(job_id=job_id)
    async with task_manager.set_status_on_exception():
        # Get resources
        crawler = container.crawler()
        uploader = container.text_processor()
        crawl_run_repo = container.crawl_run_repo()

        info_blob_repo = container.info_blob_repo()
        update_website_size_service = container.update_website_size_service()
        website_service = container.website_crud_service()
        website = await website_service.get_website(params.website_id)

        # Do task
        logger.info(f"Running crawl with params: {params}")
        num_pages = 0
        num_files = 0
        num_failed_pages = 0
        num_failed_files = 0
        num_deleted_blobs = 0

        # Unfortunately, in this type of background task we still need to care about the session atm
        session = container.session()

        existing_titles = await info_blob_repo.get_titles_of_website(params.website_id)

        crawled_titles = []

        # Select appropriate engine based on website configuration
        if website.crawler_engine == CrawlerEngine.SCRAPY:
            # Use legacy Scrapy crawler for backwards compatibility
            async with crawler.crawl(
                url=params.url,
                download_files=params.download_files,
                crawl_type=params.crawl_type,
            ) as crawl:
                # Process Scrapy results (original logic)
                for page in crawl.pages:
                    num_pages += 1
                    try:
                        title = page.url
                        async with session.begin_nested():
                            await uploader.process_text(
                                text=page.content,
                                title=title,
                                website_id=params.website_id,
                                url=page.url,
                                embedding_model=website.embedding_model,
                            )
                        crawled_titles.append(title)

                    except Exception:
                        logger.exception("Exception while uploading page")
                        num_failed_pages += 1

                for file in crawl.files:
                    num_files += 1
                    try:
                        filename = file.stem
                        async with session.begin_nested():
                            await uploader.process_file(
                                filepath=file,
                                filename=filename,
                                website_id=params.website_id,
                                embedding_model=website.embedding_model,
                            )

                        crawled_titles.append(filename)
                    except Exception:
                        logger.exception("Exception while uploading file")
                        num_failed_files += 1
        else:
            # Use new engine abstraction for crawl4ai and future engines
            engine = get_engine(website.crawler_engine)

            # Process pages from engine
            async for page in engine.crawl(
                url=params.url,
                download_files=params.download_files,
                crawl_type=params.crawl_type,
            ):
                num_pages += 1
                try:
                    title = page.url
                    async with session.begin_nested():
                        await uploader.process_text(
                            text=page.content,
                            title=title,
                            website_id=params.website_id,
                            url=page.url,
                            embedding_model=website.embedding_model,
                        )
                    crawled_titles.append(title)

                except Exception:
                    logger.exception("Exception while uploading page")
                    num_failed_pages += 1

            # Process files from engine if downloading files
            if params.download_files:
                logger.info(f"Starting file download for {website.crawler_engine} engine")
                async for file in engine.crawl_files(url=params.url):
                    num_files += 1
                    try:
                        filename = file.stem
                        logger.info(f"Processing downloaded file: {filename}")
                        async with session.begin_nested():
                            await uploader.process_file(
                                filepath=file,
                                filename=filename,
                                website_id=params.website_id,
                                embedding_model=website.embedding_model,
                            )

                        crawled_titles.append(filename)
                        logger.info(f"Successfully processed file: {filename}")
                    except Exception:
                        logger.exception("Exception while uploading file")
                        num_failed_files += 1

                logger.info(f"File download completed: {num_files} files processed, {num_failed_files} failed")

        # Clean up old content (common for both engines)
        for title in existing_titles:
            if title not in crawled_titles:
                num_deleted_blobs += 1
                await info_blob_repo.delete_by_title_and_website(
                    title=title, website_id=params.website_id
                )

        await update_website_size_service.update_website_size(website_id=website.id)

        logger.info(
            f"Crawler finished. {num_pages} pages, {num_failed_pages} failed. "
            f"{num_files} files, {num_failed_files} failed. "
            f"{num_deleted_blobs} blobs deleted."
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
