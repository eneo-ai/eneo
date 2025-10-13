from contextlib import asynccontextmanager

from fastapi import FastAPI

from intric.database.database import sessionmanager
from intric.jobs.job_manager import job_manager
from intric.main.aiohttp_client import aiohttp_client
from intric.main.config import get_settings
from intric.server.dependencies.ai_models import init_models
from intric.server.dependencies.modules import init_modules
from intric.server.dependencies.predefined_roles import init_predefined_roles
from intric.server.websockets.websocket_manager import websocket_manager


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

    # Check encryption key for HTTP auth
    import os
    from intric.main.logging import get_logger
    logger = get_logger(__name__)

    encryption_key = os.environ.get("WEBSITE_AUTH_ENCRYPTION_KEY")
    if not encryption_key:
        logger.warning(
            "WEBSITE_AUTH_ENCRYPTION_KEY not set. HTTP Basic Auth will not work. "
            "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    elif encryption_key == "LOCAL_DEV_KEY_CHANGE_IN_PRODUCTION_Wz8x9K2mP5nQ7rT4vY6uI3oA1sD0fG=":
        logger.warning("Using default dev encryption key. Generate a new key for production!")

    aiohttp_client.start()
    sessionmanager.init(settings.database_url)
    await job_manager.init()

    # init predefined roles
    await init_predefined_roles()

    # init models
    await init_models()

    # init modules
    await init_modules()


async def shutdown():
    settings = get_settings()
    # Skip all shutdown dependencies when in OpenAPI-only mode
    if settings.openapi_only_mode:
        return

    await sessionmanager.close()
    await aiohttp_client.stop()
    await job_manager.close()
    await websocket_manager.shutdown()
