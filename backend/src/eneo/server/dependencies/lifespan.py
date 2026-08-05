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
from eneo.object_content.object_store_connection import (
    ObjectStoreConnectionDatabaseUnavailable,
    ObjectStoreConnectionError,
)
from eneo.object_content.runtime import object_content_runtime
from eneo.server.dependencies.modules import init_modules
from eneo.server.dependencies.predefined_roles import init_predefined_roles
from eneo.server.websockets.websocket_manager import websocket_manager
from eneo.settings.encryption_service import EncryptionService


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

    sessionmanager.init(settings.database_url)
    # PostgreSQL owns the optional administrator-managed connection, so it must
    # be available before object-content imports or loads that configuration.
    # The root encryption key remains deployment bootstrap material.
    encryption_key = None if settings.testing else settings.encryption_key
    object_content_runtime.start(
        encryption=EncryptionService(encryption_key),
    )
    aiohttp_client.start()
    try:
        await object_content_runtime.validate_configuration()
    except ObjectStoreConnectionDatabaseUnavailable:
        # Connection metadata lives in PostgreSQL. Treat an outage there like
        # any other transient storage dependency failure and retry through
        # readiness and reconciliation after startup.
        pass
    except (ObjectContentConfigurationError, ObjectStoreConnectionError):
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
