from contextlib import asynccontextmanager

import sqlalchemy as sa
from dependency_injector import providers
from fastapi import FastAPI
from sqlalchemy.exc import ProgrammingError

from intric.database.database import sessionmanager
from intric.database.tables.website_integration_table import WebsiteIntegrationConfig
from intric.jobs.job_manager import job_manager
from intric.main.aiohttp_client import aiohttp_client
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.server.dependencies.modules import init_modules
from intric.server.dependencies.predefined_roles import init_predefined_roles
from intric.server.websockets.websocket_manager import websocket_manager

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup()
    yield
    await shutdown()


async def startup():
    settings = get_settings()
    # Skip all startup dependencies when in OpenAPI-only mode
    if settings.openapi_only_mode:
        return

    aiohttp_client.start()
    sessionmanager.init(settings.database_url)
    await job_manager.init()

    # init predefined roles
    await init_predefined_roles()

    # init modules
    await init_modules()
    await _queue_website_integration_startup_syncs()


async def _queue_website_integration_startup_syncs() -> None:
    try:
        async with sessionmanager.session() as session, session.begin():
            stmt = sa.select(WebsiteIntegrationConfig).where(
                WebsiteIntegrationConfig.sync_status.not_in(["queued", "in_progress"])
            )
            configs = list((await session.execute(stmt)).scalars().all())

            for config in configs:
                container = Container(session=providers.Object(session))
                user = await container.user_repo().get_user_by_id(
                    config.created_by_user_id
                )
                if user is None:
                    continue

                container = Container(
                    session=providers.Object(session),
                    user=providers.Object(user),
                )
                await container.website_integration_service().queue_sync(
                    config_id=config.id
                )
    except ProgrammingError as exc:
        if "website_integration_configs" not in str(exc):
            raise
        logger.warning(
            "Skipping website integration startup sync because migrations are not applied yet"
        )


async def shutdown():
    settings = get_settings()
    # Skip all shutdown dependencies when in OpenAPI-only mode
    if settings.openapi_only_mode:
        return

    await sessionmanager.close()
    await aiohttp_client.stop()
    await job_manager.close()
    await websocket_manager.shutdown()
