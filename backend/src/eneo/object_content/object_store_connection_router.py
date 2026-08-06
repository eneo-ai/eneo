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


class PreviousObjectStoreDestination(BaseModel):
    endpoint_url: str
    region: str
    bucket: str
    addressing_style: Literal["path", "virtual"]
    updated_at: datetime


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
    previous_destination: PreviousObjectStoreDestination | None = None


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


def _public_previous(
    previous: StoredObjectStoreConnection | None,
) -> PreviousObjectStoreDestination | None:
    if previous is None:
        return None
    return PreviousObjectStoreDestination(
        endpoint_url=previous.endpoint_url,
        region=previous.region,
        bucket=previous.bucket,
        addressing_style=previous.addressing_style,
        updated_at=previous.updated_at,
    )


def _public_stored_connection(
    stored: StoredObjectStoreConnection,
    previous: StoredObjectStoreConnection | None = None,
) -> ObjectStoreConnectionPublic:
    return ObjectStoreConnectionPublic(
        previous_destination=_public_previous(previous),
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
    connection = _public_connection()
    if connection.source is ObjectStoreConnectionSource.ADMIN:
        connection.previous_destination = _public_previous(
            await object_content_runtime.previous_object_store_destination()
        )
    return connection


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


@router.post(
    "/object-store-connection/destination",
    response_model=ObjectStoreConnectionPublic,
    description=(
        "Switch the deployment to an S3-compatible destination the operator "
        "has already filled with a byte-for-byte copy of the content "
        "namespace. Refused while any write could still reach a destination. "
        "The previous destination is archived for switch-back; no bucket is "
        "ever deleted."
    ),
    dependencies=_PLATFORM_ADMIN_DEPENDENCIES,
    responses=responses.get_responses([400, 403, 409, 503]),
)
async def replace_object_store_destination(
    candidate: ObjectStoreConnectionInput,
    container: _ConnectionAdminContainer,
) -> ObjectStoreConnectionPublic:
    user = container.user()
    stored = await object_content_runtime.replace_object_store_destination(
        candidate,
        actor_user_id=user.id,
    )
    logger.info(
        "object_store.destination_switched",
        extra={
            "actor_user_id": str(user.id),
            "actor": {"type": "platform_admin", "via": "session"},
            "revision": stored.revision,
        },
    )
    return _public_stored_connection(
        stored,
        await object_content_runtime.previous_object_store_destination(),
    )


@router.post(
    "/object-store-connection/destination/switch-back",
    response_model=ObjectStoreConnectionPublic,
    description=(
        "Return to the archived previous destination using its stored "
        "credentials. Subject to the same write-quiescence preconditions as "
        "a forward switch."
    ),
    dependencies=_PLATFORM_ADMIN_DEPENDENCIES,
    responses=responses.get_responses([400, 403, 404, 409, 503]),
)
async def switch_back_object_store_destination(
    container: _ConnectionAdminContainer,
) -> ObjectStoreConnectionPublic:
    user = container.user()
    stored = await object_content_runtime.switch_back_object_store_destination(
        actor_user_id=user.id,
    )
    logger.info(
        "object_store.destination_switched_back",
        extra={
            "actor_user_id": str(user.id),
            "actor": {"type": "platform_admin", "via": "session"},
            "revision": stored.revision,
        },
    )
    return _public_stored_connection(
        stored,
        await object_content_runtime.previous_object_store_destination(),
    )


@router.delete(
    "/object-store-connection/previous",
    status_code=204,
    description=(
        "Forget the archived previous destination. The bucket itself is "
        "operator-owned and is never touched; decommission it at the "
        "provider when it is no longer needed."
    ),
    dependencies=_PLATFORM_ADMIN_DEPENDENCIES,
    responses=responses.get_responses([403, 404, 503]),
)
async def forget_previous_object_store_destination(
    container: _ConnectionAdminContainer,
) -> None:
    user = container.user()
    await object_content_runtime.forget_previous_object_store_destination(
        actor_user_id=user.id,
    )
    logger.info(
        "object_store.previous_destination_forgotten",
        extra={
            "actor_user_id": str(user.id),
            "actor": {"type": "platform_admin", "via": "session"},
        },
    )
