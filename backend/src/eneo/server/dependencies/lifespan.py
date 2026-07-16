from contextlib import asynccontextmanager

from fastapi import FastAPI

from eneo.database.database import sessionmanager
from eneo.jobs.job_manager import job_manager
from eneo.main.aiohttp_client import aiohttp_client
from eneo.main.config import get_settings
from eneo.object_content.content import ObjectContentUnavailableError
from eneo.object_content.runtime import object_content_runtime
from eneo.server.dependencies.modules import init_modules
from eneo.server.dependencies.predefined_roles import init_predefined_roles
from eneo.server.websockets.websocket_manager import websocket_manager


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

    # All-absent object-content configuration is a supported disabled state.
    # Any partial configuration fails construction; endpoint availability stays
    # a readiness concern and construction itself performs no network probe.
    object_content_runtime.start()
    aiohttp_client.start()
    sessionmanager.init(settings.database_url)
    try:
        await object_content_runtime.validate_configuration()
    except ObjectContentUnavailableError:
        await object_content_runtime.stop()
        await sessionmanager.close()
        await aiohttp_client.stop()
        raise
    await job_manager.init()

    # init predefined roles
    await init_predefined_roles()

    # init modules
    await init_modules()


async def shutdown():
    settings = get_settings()
    # Skip all shutdown dependencies when in OpenAPI-only mode
    if settings.openapi_only_mode:
        return

    await object_content_runtime.stop()
    await sessionmanager.close()
    await aiohttp_client.stop()
    await job_manager.close()
    await websocket_manager.shutdown()
