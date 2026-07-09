from contextlib import asynccontextmanager

from fastapi import FastAPI

from eneo.database.database import sessionmanager
from eneo.internal_mcp import internal_mcp_lifespan
from eneo.jobs.job_manager import job_manager
from eneo.main.aiohttp_client import aiohttp_client
from eneo.main.config import get_settings
from eneo.server.dependencies.modules import init_modules
from eneo.server.dependencies.predefined_roles import init_predefined_roles
from eneo.server.websockets.websocket_manager import websocket_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup()
    # The loopback internal-MCP servers are mounted sub-apps; Starlette does
    # not run a mounted app's lifespan, so the parent must drive their session
    # managers. Skip in OpenAPI-only mode (no startup deps, no requests served).
    if get_settings().openapi_only_mode:
        yield
    else:
        async with internal_mcp_lifespan():
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


async def shutdown():
    settings = get_settings()
    # Skip all shutdown dependencies when in OpenAPI-only mode
    if settings.openapi_only_mode:
        return

    await sessionmanager.close()
    await aiohttp_client.stop()
    await job_manager.close()
    await websocket_manager.shutdown()
