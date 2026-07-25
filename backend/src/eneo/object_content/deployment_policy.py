from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.object_content_policy_table import (
    ObjectContentDeploymentPolicy,
)
from eneo.object_content.content import StorageKind


class PolicyActor(StrEnum):
    MIGRATION = "migration"
    PLATFORM_ADMIN = "platform_admin"


class DeploymentPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    new_write_storage_target: StorageKind
    session_file_limit_bytes: int = Field(ge=1)
    session_image_limit_bytes: int = Field(ge=1)
    knowledge_file_limit_bytes: int = Field(ge=1)
    transcription_audio_limit_bytes: int = Field(ge=1)


@dataclass(frozen=True, slots=True)
class DeploymentPolicy:
    revision: int
    new_write_storage_target: StorageKind
    session_file_limit_bytes: int
    session_image_limit_bytes: int
    knowledge_file_limit_bytes: int
    transcription_audio_limit_bytes: int
    updated_by_actor: PolicyActor
    updated_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime


class DeploymentPolicyConflict(Exception):
    code = "deployment_policy_revision_conflict"


class ObjectStoreTargetNotSelectable(Exception):
    code = "object_store_target_not_selectable"


class UploadLimitUseCase(StrEnum):
    SESSION_FILE = "session_file"
    SESSION_IMAGE = "session_image"
    SESSION_AUDIO = "session_audio"
    KNOWLEDGE_FILE = "knowledge_file"
    KNOWLEDGE_AUDIO = "knowledge_audio"


class ConstrainingSource(StrEnum):
    ADMIN_POLICY = "admin_policy"
    OPERATOR_CEILING = "operator_ceiling"


@dataclass(frozen=True, slots=True)
class UploadLimitProjection:
    use_case: UploadLimitUseCase
    configured_bytes: int
    effective_bytes: int
    storage_target: StorageKind | None
    operator_ceiling_bytes: int | None
    constraining_source: ConstrainingSource


def project_upload_limits(
    policy: DeploymentPolicy, *, inline_maximum_bytes: int
) -> tuple[UploadLimitProjection, ...]:
    session_ceiling = (
        inline_maximum_bytes
        if policy.new_write_storage_target is StorageKind.POSTGRES_INLINE
        else None
    )

    def session_limit(
        use_case: UploadLimitUseCase, configured_bytes: int
    ) -> UploadLimitProjection:
        effective_bytes = (
            min(configured_bytes, session_ceiling)
            if session_ceiling is not None
            else configured_bytes
        )
        return UploadLimitProjection(
            use_case=use_case,
            configured_bytes=configured_bytes,
            effective_bytes=effective_bytes,
            storage_target=policy.new_write_storage_target,
            operator_ceiling_bytes=session_ceiling,
            constraining_source=(
                ConstrainingSource.OPERATOR_CEILING
                if effective_bytes < configured_bytes
                else ConstrainingSource.ADMIN_POLICY
            ),
        )

    def knowledge_limit(
        use_case: UploadLimitUseCase, configured_bytes: int
    ) -> UploadLimitProjection:
        return UploadLimitProjection(
            use_case=use_case,
            configured_bytes=configured_bytes,
            effective_bytes=configured_bytes,
            storage_target=None,
            operator_ceiling_bytes=None,
            constraining_source=ConstrainingSource.ADMIN_POLICY,
        )

    return (
        session_limit(
            UploadLimitUseCase.SESSION_FILE,
            policy.session_file_limit_bytes,
        ),
        session_limit(
            UploadLimitUseCase.SESSION_IMAGE,
            policy.session_image_limit_bytes,
        ),
        session_limit(
            UploadLimitUseCase.SESSION_AUDIO,
            policy.transcription_audio_limit_bytes,
        ),
        knowledge_limit(
            UploadLimitUseCase.KNOWLEDGE_FILE,
            policy.knowledge_file_limit_bytes,
        ),
        knowledge_limit(
            UploadLimitUseCase.KNOWLEDGE_AUDIO,
            policy.transcription_audio_limit_bytes,
        ),
    )


def _policy(row: ObjectContentDeploymentPolicy) -> DeploymentPolicy:
    return DeploymentPolicy(
        revision=row.revision,
        new_write_storage_target=StorageKind(row.new_write_storage_target),
        session_file_limit_bytes=row.session_file_limit_bytes,
        session_image_limit_bytes=row.session_image_limit_bytes,
        knowledge_file_limit_bytes=row.knowledge_file_limit_bytes,
        transcription_audio_limit_bytes=row.transcription_audio_limit_bytes,
        updated_by_actor=PolicyActor(row.updated_by_actor),
        updated_by_user_id=row.updated_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class DeploymentPolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self) -> DeploymentPolicy:
        row = await self._session.scalar(
            select(ObjectContentDeploymentPolicy).where(
                ObjectContentDeploymentPolicy.id == 1
            )
        )
        if row is None:
            raise RuntimeError("Object-content deployment policy is missing")
        return _policy(row)

    async def replace(
        self, replacement: DeploymentPolicyUpdate, *, actor_user_id: UUID
    ) -> DeploymentPolicy:
        values = replacement.model_dump(exclude={"expected_revision"})
        values.update(
            revision=ObjectContentDeploymentPolicy.revision + 1,
            updated_by_actor=PolicyActor.PLATFORM_ADMIN.value,
            updated_by_user_id=actor_user_id,
        )
        row = await self._session.scalar(
            update(ObjectContentDeploymentPolicy)
            .where(
                ObjectContentDeploymentPolicy.id == 1,
                ObjectContentDeploymentPolicy.revision == replacement.expected_revision,
            )
            .values(**values)
            .returning(ObjectContentDeploymentPolicy)
        )
        if row is None:
            raise DeploymentPolicyConflict("Deployment policy revision is stale")
        return _policy(row)
