from contextlib import asynccontextmanager

from fastapi import FastAPI

from eneo.database.database import sessionmanager
from eneo.jobs.job_manager import job_manager
from eneo.main.aiohttp_client import aiohttp_client
from eneo.main.config import get_settings
from eneo.object_content.content import (
    ObjectContentConfigurationError,
    ObjectContentUnavailableError,
)
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

    # Remote configuration is optional; the inline-capable core always starts.
    # Any partial configuration fails construction. Startup then verifies the
    # durable PostgreSQL/object-store pairing before producers or workers run.
    object_content_runtime.start(
        required_inline_bytes=max(
            settings.upload_file_to_session_max_size,
            settings.upload_image_to_session_max_size,
            settings.transcription_max_file_size,
        )
    )
    aiohttp_client.start()
    sessionmanager.init(settings.database_url)
    try:
        await object_content_runtime.validate_configuration()
    except ObjectContentConfigurationError:
        await object_content_runtime.stop()
        await sessionmanager.close()
        await aiohttp_client.stop()
        raise
    except ObjectContentUnavailableError:
        # A transient database/store outage is a readiness failure. The process
        # remains live and retries the binding check on readiness and every
        # reconciliation attempt.
        pass
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
