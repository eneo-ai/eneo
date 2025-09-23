from contextlib import asynccontextmanager

from fastapi import FastAPI

from intric.database.database import sessionmanager
from intric.jobs.job_manager import job_manager
from intric.main.aiohttp_client import aiohttp_client
from intric.main.config import SETTINGS
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
    # Skip all startup dependencies when in OpenAPI-only mode
    if SETTINGS.openapi_only_mode:
        return

    aiohttp_client.start()
    sessionmanager.init(SETTINGS.database_url)
    await job_manager.init()

    # init predefined roles
    await init_predefined_roles()

    # init models
    await init_models()

    # init modules
    await init_modules()


async def shutdown():
    # Skip all shutdown dependencies when in OpenAPI-only mode
    if SETTINGS.openapi_only_mode:
        return

    await sessionmanager.close()
    await aiohttp_client.stop()
    await job_manager.close()
    await websocket_manager.shutdown()
