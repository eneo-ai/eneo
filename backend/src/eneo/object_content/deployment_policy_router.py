from datetime import datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.authentication.auth_dependencies import (
    get_current_active_user,
    require_permission,
    require_platform_admin,
    require_session_auth,
    require_user_identity,
)
from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.object_content.content import ContentState, StorageKind
from eneo.object_content.deployment_policy import (
    DeploymentPolicy,
    DeploymentPolicyRepository,
    DeploymentPolicyUpdate,
    ObjectStoreTargetNotSelectable,
    PolicyActor,
    UploadLimitProjection,
    project_upload_limits,
)
from eneo.object_content.reconciliation_repository import (
    ObjectContentReconciliationRepository,
)
from eneo.object_content.runtime import (
    ObjectContentReadinessCode,
    object_content_runtime,
)
from eneo.roles.permissions import Permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.users.user import UserInDB

router = APIRouter()
logger = get_logger(__name__)


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
    updated_by_actor: PolicyActor
    created_at: datetime
    updated_at: datetime


class DeploymentPolicyPublic(BaseModel):
    policy: DeploymentPolicyPublicValues
    limits: tuple[UploadLimitProjection, ...]
    capabilities: tuple[CapabilityPublic, ...]
    inventory: tuple[InventoryPublic, ...]


async def _read_projection(
    session: AsyncSession,
) -> DeploymentPolicyPublic:
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
    inventory = tuple(
        InventoryPublic(
            target=fact.storage_kind,
            state=fact.state,
            count=fact.count,
            bytes=fact.size_bytes,
            oldest_created_at=fact.oldest_created_at,
        )
        for fact in await ObjectContentReconciliationRepository(
            session
        ).inventory_facts()
    )
    return DeploymentPolicyPublic(
        policy=DeploymentPolicyPublicValues(
            revision=policy.revision,
            new_write_storage_target=policy.new_write_storage_target,
            session_file_limit_bytes=policy.session_file_limit_bytes,
            session_image_limit_bytes=policy.session_image_limit_bytes,
            knowledge_file_limit_bytes=policy.knowledge_file_limit_bytes,
            transcription_audio_limit_bytes=policy.transcription_audio_limit_bytes,
            updated_by_actor=policy.updated_by_actor,
            created_at=policy.created_at,
            updated_at=policy.updated_at,
        ),
        limits=project_upload_limits(
            policy,
            inline_maximum_bytes=object_content_runtime.inline_maximum_bytes,
        ),
        capabilities=capabilities,
        inventory=inventory,
    )


@router.get(
    "/object-content-policy",
    response_model=DeploymentPolicyPublic,
    description=(
        "Get the deployment-wide new-write storage target, upload limits, "
        "and sanitized capability and inventory facts."
    ),
    dependencies=[Depends(require_permission(Permission.ADMIN))],
    responses=responses.get_responses([403]),
)
async def get_deployment_policy(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> DeploymentPolicyPublic:
    return await _read_projection(cast(AsyncSession, container.session()))


@router.put(
    "/object-content-policy",
    response_model=DeploymentPolicyPublic,
    description=(
        "Replace the deployment-wide new-write storage target and upload limits "
        "using the expected revision. The target affects eligible new writes only "
        "and never moves existing content."
    ),
    dependencies=[
        Depends(require_session_auth),
        Depends(require_user_identity),
        Depends(require_platform_admin),
    ],
    responses=responses.get_responses([403, 409]),
)
async def replace_deployment_policy(
    replacement: DeploymentPolicyUpdate,
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    container: Annotated[
        Container,
        Depends(get_container(with_user=True, with_transaction=False)),
    ],
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
    async with session.begin():
        return await _read_projection(session)


def _log_values(policy: DeploymentPolicy) -> dict[str, str | int]:
    return {
        "revision": policy.revision,
        "new_write_storage_target": policy.new_write_storage_target.value,
        "session_file_limit_bytes": policy.session_file_limit_bytes,
        "session_image_limit_bytes": policy.session_image_limit_bytes,
        "knowledge_file_limit_bytes": policy.knowledge_file_limit_bytes,
        "transcription_audio_limit_bytes": policy.transcription_audio_limit_bytes,
    }
