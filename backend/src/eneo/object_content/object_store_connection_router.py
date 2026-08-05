from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from eneo.authentication.auth_dependencies import (
    require_platform_admin,
    require_session_auth,
    require_user_identity,
)
from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.object_content.object_store_connection import (
    ObjectStoreConnectionInput,
    ObjectStoreConnectionSource,
    ObjectStoreCredentialRotation,
    StoredObjectStoreConnection,
)
from eneo.object_content.runtime import object_content_runtime
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()
logger = get_logger(__name__)

_connection_admin_container_dependency = get_container(
    with_user=True,
    with_transaction=False,
)
_ConnectionAdminContainer = Annotated[
    Container,
    Depends(_connection_admin_container_dependency),
]


async def _require_connection_session_auth(
    request: Request,
    container: _ConnectionAdminContainer,
) -> None:
    await require_session_auth(container.user(), request)


async def _require_connection_user_identity(
    container: _ConnectionAdminContainer,
) -> None:
    await require_user_identity(container.user())


async def _require_connection_platform_admin(
    container: _ConnectionAdminContainer,
) -> None:
    await require_platform_admin(container.user())


_PLATFORM_ADMIN_DEPENDENCIES = [
    Depends(_require_connection_session_auth),
    Depends(_require_connection_user_identity),
    Depends(_require_connection_platform_admin),
]


class ObjectStoreConnectionPublic(BaseModel):
    source: ObjectStoreConnectionSource
    configured: bool
    credentials_can_be_managed: bool
    revision: int | None = None
    endpoint_url: str | None = None
    region: str | None = None
    bucket: str | None = None
    addressing_style: Literal["path", "virtual"] | None = None
    updated_at: datetime | None = None


def _public_connection() -> ObjectStoreConnectionPublic:
    source = object_content_runtime.object_store_connection_source
    stored = object_content_runtime.stored_object_store_connection
    legacy = object_content_runtime.legacy_object_store_settings
    if stored is not None:
        return _public_stored_connection(stored)
    if legacy is not None:
        return ObjectStoreConnectionPublic(
            source=source,
            configured=True,
            credentials_can_be_managed=False,
            revision=0,
            endpoint_url=legacy.endpoint_url,
            region=legacy.region,
            bucket=legacy.bucket,
            addressing_style=legacy.addressing_style,
        )
    return ObjectStoreConnectionPublic(
        source=ObjectStoreConnectionSource.UNCONFIGURED,
        configured=False,
        credentials_can_be_managed=(
            object_content_runtime.object_store_credentials_can_be_managed
        ),
    )


def _public_stored_connection(
    stored: StoredObjectStoreConnection,
) -> ObjectStoreConnectionPublic:
    return ObjectStoreConnectionPublic(
        source=ObjectStoreConnectionSource.ADMIN,
        configured=True,
        credentials_can_be_managed=(
            object_content_runtime.object_store_credentials_can_be_managed
        ),
        revision=stored.revision,
        endpoint_url=stored.endpoint_url,
        region=stored.region,
        bucket=stored.bucket,
        addressing_style=stored.addressing_style,
        updated_at=stored.updated_at,
    )


@router.get(
    "/object-store-connection",
    response_model=ObjectStoreConnectionPublic,
    description=(
        "Get the deployment-wide S3-compatible destination without returning "
        "credentials or internal object identifiers. Platform administrators only."
    ),
    dependencies=_PLATFORM_ADMIN_DEPENDENCIES,
    responses=responses.get_responses([403, 503]),
)
async def get_object_store_connection() -> ObjectStoreConnectionPublic:
    await object_content_runtime.refresh_object_store_configuration()
    return _public_connection()


@router.post(
    "/object-store-connection",
    response_model=ObjectStoreConnectionPublic,
    description=(
        "Test and save the first deployment-wide S3-compatible destination. "
        "This does not select it for new writes or move existing content."
    ),
    dependencies=_PLATFORM_ADMIN_DEPENDENCIES,
    responses=responses.get_responses([400, 403, 409, 503]),
)
async def create_object_store_connection(
    candidate: ObjectStoreConnectionInput,
    container: _ConnectionAdminContainer,
) -> ObjectStoreConnectionPublic:
    user = container.user()
    stored = await object_content_runtime.create_object_store_connection(
        candidate,
        actor_user_id=user.id,
    )
    logger.info(
        "object_store.connection_created",
        extra={
            "actor_user_id": str(user.id),
            "actor": {"type": "platform_admin", "via": "session"},
            "revision": stored.revision,
        },
    )
    return _public_stored_connection(stored)


@router.put(
    "/object-store-connection/credentials",
    response_model=ObjectStoreConnectionPublic,
    description=(
        "Test and replace credentials for the configured destination without "
        "changing its endpoint, bucket, signing region, or addressing style."
    ),
    dependencies=_PLATFORM_ADMIN_DEPENDENCIES,
    responses=responses.get_responses([400, 403, 409, 503]),
)
async def rotate_object_store_credentials(
    replacement: ObjectStoreCredentialRotation,
    container: _ConnectionAdminContainer,
) -> ObjectStoreConnectionPublic:
    user = container.user()
    stored = await object_content_runtime.rotate_object_store_credentials(
        replacement,
        actor_user_id=user.id,
    )
    logger.info(
        "object_store.credentials_rotated",
        extra={
            "actor_user_id": str(user.id),
            "actor": {"type": "platform_admin", "via": "session"},
            "revision": stored.revision,
        },
    )
    return _public_stored_connection(stored)
