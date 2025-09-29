from uuid import UUID

from dependency_injector import providers

from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.websites.crawl_dependencies.crawl_models import (
    CrawlTask,
)

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
        logger.info("=== CRAWL TASK DIAGNOSTIC START ===")
        logger.info(f"Job ID: {job_id}")
        logger.info(f"Crawl params: {params}")
        logger.info(f"Website ID: {params.website_id}")
        logger.info(f"User ID: {params.user_id}")
        logger.info(f"Target URL: {params.url}")

        # Capture network environment for database connectivity analysis
        logger.info("Capturing network environment for database diagnostics...")
        import os
        logger.info("Database connection environment:")
        logger.info(f"  - Database host: {os.environ.get('DATABASE_HOST', 'Not set')}")
        logger.info(f"  - Database port: {os.environ.get('DATABASE_PORT', 'Not set')}")
        logger.info(f"  - Database name: {os.environ.get('DATABASE_NAME', 'Not set')}")
        logger.info(f"  - Redis host: {os.environ.get('REDIS_HOST', 'Not set')}")
        logger.info(f"  - Redis port: {os.environ.get('REDIS_PORT', 'Not set')}")

        # Test database connectivity
        logger.info("Testing database connectivity...")
        try:
            # Test basic container access
            logger.info("Getting container resources...")
            crawler = container.crawler()
            uploader = container.text_processor()
            crawl_run_repo = container.crawl_run_repo()
            info_blob_repo = container.info_blob_repo()
            update_website_size_service = container.update_website_size_service()
            website_service = container.website_crud_service()
            logger.info("✅ Container resources obtained successfully")

            # Test database session
            logger.info("Testing database session...")
            session_obj = container.session()
            logger.info(f"Session object type: {type(session_obj)}")
            logger.info(f"Session object: {session_obj}")
            logger.info(f"Session callable: {callable(session_obj)}")

            # Handle both factory and direct session patterns
            if callable(session_obj):
                logger.info("Using session as factory (normal behavior)")
                async with session_obj() as session:
                    from sqlalchemy import text
                    result = await session.execute(text("SELECT 1 as test"))
                    test_value = result.scalar()
                    logger.info(f"✅ Database connectivity test passed: {test_value}")
            else:
                logger.warning("Session object is not callable - using direct session (abnormal behavior)")
                logger.warning("This indicates container dependency injection issue")
                session = session_obj
                from sqlalchemy import text
                result = await session.execute(text("SELECT 1 as test"))
                test_value = result.scalar()
                logger.info(f"✅ Database connectivity test passed with direct session: {test_value}")

            # Investigate why container behavior differs between networks
            logger.info("=== CONTAINER STATE INVESTIGATION ===")

            # Check container attributes
            container_attrs = [attr for attr in dir(container) if not attr.startswith('_')]
            logger.info(f"Container available attributes: {container_attrs}")

            # Check configuration state
            try:
                from intric.main.config import get_settings
                settings = get_settings()
                logger.info(f"Settings loaded: {type(settings)}")
                logger.info(f"Database URL configured: {'database_url' in dir(settings)}")
            except Exception as settings_e:
                logger.error(f"Could not load settings: {settings_e}")

            # Check environment variables that affect container setup
            import os
            critical_env_vars = [
                'DATABASE_URL', 'DATABASE_HOST', 'DATABASE_PORT', 'DATABASE_NAME',
                'DATABASE_USER', 'DATABASE_PASSWORD', 'REDIS_URL', 'REDIS_HOST',
                'REDIS_PORT', 'ENVIRONMENT', 'DEBUG', 'TESTING'
            ]

            logger.info("Critical environment variables:")
            for var in critical_env_vars:
                value = os.environ.get(var, 'Not set')
                # Don't log passwords
                if 'PASSWORD' in var and value != 'Not set':
                    value = '***HIDDEN***'
                logger.info(f"  {var}: {value}")

            # Check if there are any network-dependent config files being loaded
            config_paths = ['/workspace/backend/.env', '/workspace/backend/.env.local', '/.env']
            for path in config_paths:
                if os.path.exists(path):
                    logger.info(f"Config file exists: {path}")
                    try:
                        with open(path, 'r') as f:
                            content = f.read()
                            logger.info(f"Config file size: {len(content)} bytes")
                    except Exception as e:
                        logger.warning(f"Could not read config file {path}: {e}")
                else:
                    logger.info(f"Config file not found: {path}")

            logger.info("=== END CONTAINER INVESTIGATION ===")

            # Test space service before website lookup
            logger.info("Testing space service availability...")
            space_service = container.space_service()
            logger.info(f"Space service: {space_service}")

            # Try to get website with detailed error handling
            logger.info(f"Attempting to get website with ID: {params.website_id}")
            website = await website_service.get_website(params.website_id)
            logger.info(f"✅ Website found: {website.url if website else 'None'}")

        except Exception as e:
            logger.error("❌ EARLY DATABASE/SERVICE ERROR:")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error message: {str(e)}")
            logger.error(f"Error details: {repr(e)}")

            # Try to get more specific information about the failure
            if "NotFoundException" in str(type(e)):
                logger.error("NotFoundException details:")
                logger.error(f"  - Could not find website with ID: {params.website_id}")
                logger.error("  - This could indicate:")
                logger.error("    • Website was deleted from database")
                logger.error("    • Database connectivity issue")
                logger.error("    • Space/website relationship broken")
                logger.error("    • User permissions issue")

                # Try to investigate further
                try:
                    logger.info("Investigating database state...")
                    session_factory = container.session()
                    async with session_factory() as session:
                        # Check if website exists at all
                        from intric.websites.domain.website import Website
                        from sqlalchemy import select

                        website_query = select(Website).where(Website.id == params.website_id)
                        website_result = await session.execute(website_query)
                        website_exists = website_result.scalar_one_or_none()

                        logger.info(f"Website exists in database: {'Yes' if website_exists else 'No'}")
                        if website_exists:
                            logger.info(f"Website details: URL={website_exists.url}, Space ID={website_exists.space_id}")

                            # Check space
                            from intric.spaces.space import Space
                            space_query = select(Space).where(Space.id == website_exists.space_id)
                            space_result = await session.execute(space_query)
                            space_exists = space_result.scalar_one_or_none()

                            logger.info(f"Associated space exists: {'Yes' if space_exists else 'No'}")

                except Exception as investigate_e:
                    logger.error(f"Could not investigate database state: {investigate_e}")

            raise  # Re-raise the original exception

        # Do task
        logger.info(f"Running crawl with params: {params}")
        logger.info(f"Target URL: {params.url}")
        logger.info(f"Download files: {params.download_files}")
        logger.info(f"Crawl type: {params.crawl_type}")

        num_pages = 0
        num_files = 0
        num_failed_pages = 0
        num_failed_files = 0
        num_deleted_blobs = 0

        # Unfortunately, in this type of background task we still need to care about the session atm
        session = container.session()

        logger.info("Getting existing titles from database...")
        existing_titles = await info_blob_repo.get_titles_of_website(params.website_id)
        logger.info(f"Found {len(existing_titles)} existing titles in database")

        crawled_titles = []

        logger.info("Starting crawler context manager...")
        async with crawler.crawl(
            url=params.url,
            download_files=params.download_files,
            crawl_type=params.crawl_type,
        ) as crawl:
            logger.info("Crawler context manager opened successfully - starting to process pages...")

            page_counter = 0
            for page in crawl.pages:
                page_counter += 1
                num_pages += 1
                logger.info(f"Processing page {page_counter}: {page.url}")
                if page_counter == 1:
                    logger.info(f"First page content preview: {page.content[:200]}...")

                if page_counter % 10 == 0:
                    logger.info(f"Processed {page_counter} pages so far...")

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

            logger.info("Finished processing pages. Moving to files...")
            file_counter = 0
            for file in crawl.files:
                file_counter += 1
                num_files += 1
                logger.info(f"Processing file {file_counter}: {file}")
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

            logger.info("Cleaning up old titles...")
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
