from datetime import datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.authentication.auth_dependencies import (
    require_platform_admin,
    require_session_auth,
    require_user_identity,
)
from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.object_content.content import (
    ContentMoveFailureCode,
    ContentMoveState,
    ContentState,
    ObjectContentUnavailableError,
    StorageKind,
)
from eneo.object_content.deployment_policy import (
    DeploymentPolicy,
    DeploymentPolicyPauseUpdate,
    DeploymentPolicyRepository,
    DeploymentPolicyUpdate,
    ObjectStoreTargetNotSelectable,
    PolicyActor,
    UploadLimitProjection,
    project_upload_limits,
)
from eneo.object_content.move_repository import ObjectContentMoveRepository
from eneo.object_content.reconciliation_repository import (
    ObjectContentReconciliationRepository,
)
from eneo.object_content.runtime import (
    ObjectContentReadinessCode,
    object_content_runtime,
)
from eneo.roles.permissions import Permission, validate_permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()
logger = get_logger(__name__)

_policy_admin_container_dependency = get_container(
    with_user=True,
    with_transaction=False,
)
_PolicyAdminContainer = Annotated[
    Container,
    Depends(_policy_admin_container_dependency),
]


async def _require_policy_session_auth(
    request: Request,
    container: _PolicyAdminContainer,
) -> None:
    await require_session_auth(container.user(), request)


async def _require_policy_user_identity(
    container: _PolicyAdminContainer,
) -> None:
    await require_user_identity(container.user())


async def _require_policy_platform_admin(
    container: _PolicyAdminContainer,
) -> None:
    await require_platform_admin(container.user())


class CapabilityPublic(BaseModel):
    target: StorageKind
    configured: bool
    selectable: bool
    readiness_code: ObjectContentReadinessCode


class InventoryPublic(BaseModel):
    target: StorageKind
    state: ContentState
    count: int
    bytes: int
    oldest_created_at: datetime | None


class DeploymentPolicyPublicValues(BaseModel):
    revision: int
    new_write_storage_target: StorageKind
    session_file_limit_bytes: int
    session_image_limit_bytes: int
    knowledge_file_limit_bytes: int
    transcription_audio_limit_bytes: int
    moves_paused: bool
    updated_by_actor: PolicyActor
    created_at: datetime
    updated_at: datetime


class DeploymentPolicyPublic(BaseModel):
    policy: DeploymentPolicyPublicValues
    limits: tuple[UploadLimitProjection, ...]
    capabilities: tuple[CapabilityPublic, ...]


class ObjectContentInventoryPublic(BaseModel):
    inventory: tuple[InventoryPublic, ...]


class MoveStatePublic(BaseModel):
    target: StorageKind
    state: ContentMoveState
    failure_code: ContentMoveFailureCode | None
    count: int
    bytes: int
    oldest_updated_at: datetime | None


class ObjectContentMovesPublic(BaseModel):
    policy_revision: int
    paused: bool
    moves: tuple[MoveStatePublic, ...]


class MoveQueueRequest(BaseModel):
    target: StorageKind
    limit: int = Field(ge=1, le=100)


class MoveQueuePublic(BaseModel):
    queued_count: int
    target_too_large_count: int


class MovePausePublic(BaseModel):
    policy_revision: int
    paused: bool


async def _read_projection(
    session: AsyncSession,
) -> DeploymentPolicyPublic:
    if session.in_transaction():
        raise RuntimeError("Policy projection requires a non-transactional session")

    async with session.begin():
        policy = await DeploymentPolicyRepository(session).get()

    capabilities = tuple(
        CapabilityPublic(
            target=fact.target,
            configured=fact.configured,
            selectable=fact.selectable,
            readiness_code=fact.readiness_code,
        )
        for fact in await object_content_runtime.storage_capabilities()
    )
    return DeploymentPolicyPublic(
        policy=DeploymentPolicyPublicValues(
            revision=policy.revision,
            new_write_storage_target=policy.new_write_storage_target,
            session_file_limit_bytes=policy.session_file_limit_bytes,
            session_image_limit_bytes=policy.session_image_limit_bytes,
            knowledge_file_limit_bytes=policy.knowledge_file_limit_bytes,
            transcription_audio_limit_bytes=policy.transcription_audio_limit_bytes,
            moves_paused=policy.moves_paused,
            updated_by_actor=policy.updated_by_actor,
            created_at=policy.created_at,
            updated_at=policy.updated_at,
        ),
        limits=project_upload_limits(
            policy,
            inline_maximum_bytes=object_content_runtime.inline_maximum_bytes,
            object_store_maximum_bytes=(
                object_content_runtime.object_store_maximum_bytes
            ),
        ),
        capabilities=capabilities,
    )


async def _read_inventory(session: AsyncSession) -> ObjectContentInventoryPublic:
    if session.in_transaction():
        raise RuntimeError("Inventory projection requires a non-transactional session")

    async with session.begin():
        inventory_facts = await ObjectContentReconciliationRepository(
            session
        ).inventory_facts()

    return ObjectContentInventoryPublic(
        inventory=tuple(
            InventoryPublic(
                target=fact.storage_kind,
                state=fact.state,
                count=fact.count,
                bytes=fact.size_bytes,
                oldest_created_at=fact.oldest_created_at,
            )
            for fact in inventory_facts
        )
    )


async def _read_moves(session: AsyncSession) -> ObjectContentMovesPublic:
    if session.in_transaction():
        raise RuntimeError("Move projection requires a non-transactional session")

    async with session.begin():
        policy = await DeploymentPolicyRepository(session).get()
        facts = await ObjectContentMoveRepository(session).state_facts()

    return ObjectContentMovesPublic(
        policy_revision=policy.revision,
        paused=policy.moves_paused,
        moves=tuple(
            MoveStatePublic(
                target=fact.target_kind,
                state=fact.state,
                failure_code=fact.failure_code,
                count=fact.count,
                bytes=fact.size_bytes,
                oldest_updated_at=fact.oldest_updated_at,
            )
            for fact in facts
        ),
    )


@router.get(
    "/object-content-policy",
    response_model=DeploymentPolicyPublic,
    description=(
        "Get the deployment-wide new-write storage target, upload limits, "
        "and sanitized capability facts."
    ),
    responses=responses.get_responses([403]),
)
async def get_deployment_policy(
    container: Annotated[
        Container,
        Depends(get_container(with_user=True, with_transaction=False)),
    ],
) -> DeploymentPolicyPublic:
    # Keep this tenant-admin read on its sole authenticated container while it
    # awaits object-store readiness.
    validate_permission(container.user(), Permission.ADMIN)
    return await _read_projection(cast(AsyncSession, container.session()))


@router.get(
    "/object-content-inventory",
    response_model=ObjectContentInventoryPublic,
    description=(
        "Get bounded deployment-wide object-content inventory facts. "
        "Platform administrators only."
    ),
    dependencies=[
        Depends(_require_policy_session_auth),
        Depends(_require_policy_user_identity),
        Depends(_require_policy_platform_admin),
    ],
    responses=responses.get_responses([403]),
)
async def get_object_content_inventory(
    container: _PolicyAdminContainer,
) -> ObjectContentInventoryPublic:
    return await _read_inventory(cast(AsyncSession, container.session()))


@router.get(
    "/object-content-moves",
    response_model=ObjectContentMovesPublic,
    description=(
        "Get bounded aggregate progress and typed failure reasons for explicit "
        "object-content moves. Platform administrators only."
    ),
    dependencies=[
        Depends(_require_policy_session_auth),
        Depends(_require_policy_user_identity),
        Depends(_require_policy_platform_admin),
    ],
    responses=responses.get_responses([403]),
)
async def get_object_content_moves(
    container: _PolicyAdminContainer,
) -> ObjectContentMovesPublic:
    return await _read_moves(cast(AsyncSession, container.session()))


@router.post(
    "/object-content-moves",
    response_model=MoveQueuePublic,
    description=(
        "Queue one bounded page of eligible content for an explicit storage move. "
        "This never starts an automatic fleet migration."
    ),
    dependencies=[
        Depends(_require_policy_session_auth),
        Depends(_require_policy_user_identity),
        Depends(_require_policy_platform_admin),
    ],
    responses=responses.get_responses([403, 503]),
)
async def queue_object_content_moves(
    request: MoveQueueRequest,
    container: _PolicyAdminContainer,
) -> MoveQueuePublic:
    object_store_capability = next(
        fact
        for fact in await object_content_runtime.storage_capabilities()
        if fact.target is StorageKind.OBJECT_STORE
    )
    if not object_store_capability.selectable:
        raise ObjectContentUnavailableError(
            "Compatible object storage is not ready for a new move command"
        )
    maximum_bytes = (
        object_content_runtime.inline_maximum_bytes
        if request.target is StorageKind.POSTGRES_INLINE
        else object_content_runtime.object_store_maximum_bytes
    )
    if maximum_bytes is None:
        raise ObjectContentUnavailableError(
            "Compatible object storage is required to move durable content"
        )

    user = container.user()
    session = cast(AsyncSession, container.session())
    async with session.begin():
        result = await ObjectContentMoveRepository(session).queue(
            target_kind=request.target,
            limit=request.limit,
            requested_by_user_id=user.id,
            target_maximum_bytes=maximum_bytes,
        )
    logger.info(
        "object_content.moves_queued",
        extra={
            "actor_user_id": str(user.id),
            "actor": {"type": "platform_admin", "via": "session"},
            "target": request.target.value,
            "requested_limit": request.limit,
            "queued_count": result.queued_count,
            "target_too_large_count": result.target_too_large_count,
        },
    )
    return MoveQueuePublic(
        queued_count=result.queued_count,
        target_too_large_count=result.target_too_large_count,
    )


@router.put(
    "/object-content-moves/pause",
    response_model=MovePausePublic,
    description=(
        "Pause or resume new object-content move claims using the expected "
        "deployment-policy revision."
    ),
    dependencies=[
        Depends(_require_policy_session_auth),
        Depends(_require_policy_user_identity),
        Depends(_require_policy_platform_admin),
    ],
    responses=responses.get_responses([403, 409]),
)
async def set_object_content_moves_paused(
    replacement: DeploymentPolicyPauseUpdate,
    container: _PolicyAdminContainer,
) -> MovePausePublic:
    user = container.user()
    session = cast(AsyncSession, container.session())
    async with session.begin():
        old = await DeploymentPolicyRepository(session).get()
        updated = await DeploymentPolicyRepository(session).set_moves_paused(
            replacement,
            actor_user_id=user.id,
        )
    logger.info(
        "object_content.move_pause_changed",
        extra={
            "actor_user_id": str(user.id),
            "actor": {"type": "platform_admin", "via": "session"},
            "old_paused": old.moves_paused,
            "new_paused": updated.moves_paused,
            "policy_revision": updated.revision,
        },
    )
    return MovePausePublic(
        policy_revision=updated.revision,
        paused=updated.moves_paused,
    )


@router.put(
    "/object-content-policy",
    response_model=DeploymentPolicyPublic,
    description=(
        "Replace the deployment-wide new-write storage target and upload limits "
        "using the expected revision. The target affects eligible new writes only "
        "and never moves existing content."
    ),
    dependencies=[
        Depends(_require_policy_session_auth),
        Depends(_require_policy_user_identity),
        Depends(_require_policy_platform_admin),
    ],
    responses=responses.get_responses([403, 409]),
)
async def replace_deployment_policy(
    replacement: DeploymentPolicyUpdate,
    container: _PolicyAdminContainer,
) -> DeploymentPolicyPublic:
    if replacement.new_write_storage_target is StorageKind.OBJECT_STORE:
        capability = next(
            fact
            for fact in await object_content_runtime.storage_capabilities()
            if fact.target is StorageKind.OBJECT_STORE
        )
        if not capability.selectable:
            raise ObjectStoreTargetNotSelectable(
                "Object-store target is not selectable."
            )

    user = container.user()
    session = cast(AsyncSession, container.session())
    async with session.begin():
        old = await DeploymentPolicyRepository(session).get()
        updated = await DeploymentPolicyRepository(session).replace(
            replacement, actor_user_id=user.id
        )

    logger.info(
        "object_content.deployment_policy_changed",
        extra={
            "actor_user_id": str(user.id),
            "actor": {"type": "platform_admin", "via": "session"},
            "old": _log_values(old),
            "new": _log_values(updated),
        },
    )
    return await _read_projection(session)


def _log_values(policy: DeploymentPolicy) -> dict[str, str | int]:
    return {
        "revision": policy.revision,
        "new_write_storage_target": policy.new_write_storage_target.value,
        "session_file_limit_bytes": policy.session_file_limit_bytes,
        "session_image_limit_bytes": policy.session_image_limit_bytes,
        "knowledge_file_limit_bytes": policy.knowledge_file_limit_bytes,
        "transcription_audio_limit_bytes": policy.transcription_audio_limit_bytes,
        "moves_paused": str(policy.moves_paused).lower(),
    }
