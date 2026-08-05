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
from eneo.object_content.content import MAXIMUM_UPLOAD_POLICY_BYTES, StorageKind


class PolicyActor(StrEnum):
    MIGRATION = "migration"
    PLATFORM_ADMIN = "platform_admin"


class DeploymentPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    new_write_storage_target: StorageKind
    session_file_limit_bytes: int = Field(ge=1, le=MAXIMUM_UPLOAD_POLICY_BYTES)
    session_image_limit_bytes: int = Field(ge=1, le=MAXIMUM_UPLOAD_POLICY_BYTES)
    knowledge_file_limit_bytes: int = Field(ge=1, le=MAXIMUM_UPLOAD_POLICY_BYTES)
    transcription_audio_limit_bytes: int = Field(
        ge=1,
        le=MAXIMUM_UPLOAD_POLICY_BYTES,
    )


class DeploymentPolicyPauseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    moves_paused: bool


@dataclass(frozen=True, slots=True)
class DeploymentPolicy:
    revision: int
    new_write_storage_target: StorageKind
    session_file_limit_bytes: int
    session_image_limit_bytes: int
    knowledge_file_limit_bytes: int
    transcription_audio_limit_bytes: int
    moves_paused: bool
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
    storage_target: StorageKind
    operator_ceiling_bytes: int | None
    constraining_source: ConstrainingSource


@dataclass(frozen=True, slots=True)
class UploadAdmissionSnapshot:
    policy_revision: int
    new_write_storage_target: StorageKind
    session_file_maximum_bytes: int
    session_image_maximum_bytes: int
    session_audio_maximum_bytes: int
    knowledge_file_maximum_bytes: int
    knowledge_audio_maximum_bytes: int


def project_upload_limits(
    policy: DeploymentPolicy,
    *,
    inline_maximum_bytes: int,
    object_store_maximum_bytes: int | None,
) -> tuple[UploadLimitProjection, ...]:
    operator_ceiling = {
        StorageKind.POSTGRES_INLINE: inline_maximum_bytes,
        StorageKind.OBJECT_STORE: object_store_maximum_bytes,
    }[policy.new_write_storage_target]

    def project_limit(
        use_case: UploadLimitUseCase, configured_bytes: int
    ) -> UploadLimitProjection:
        effective_bytes = (
            min(configured_bytes, operator_ceiling)
            if operator_ceiling is not None
            else configured_bytes
        )
        return UploadLimitProjection(
            use_case=use_case,
            configured_bytes=configured_bytes,
            effective_bytes=effective_bytes,
            storage_target=policy.new_write_storage_target,
            operator_ceiling_bytes=operator_ceiling,
            constraining_source=(
                ConstrainingSource.OPERATOR_CEILING
                if effective_bytes < configured_bytes
                else ConstrainingSource.ADMIN_POLICY
            ),
        )

    return (
        project_limit(
            UploadLimitUseCase.SESSION_FILE,
            policy.session_file_limit_bytes,
        ),
        project_limit(
            UploadLimitUseCase.SESSION_IMAGE,
            policy.session_image_limit_bytes,
        ),
        project_limit(
            UploadLimitUseCase.SESSION_AUDIO,
            policy.transcription_audio_limit_bytes,
        ),
        project_limit(
            UploadLimitUseCase.KNOWLEDGE_FILE,
            policy.knowledge_file_limit_bytes,
        ),
        project_limit(
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
        moves_paused=row.moves_paused,
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

    async def set_moves_paused(
        self,
        replacement: DeploymentPolicyPauseUpdate,
        *,
        actor_user_id: UUID,
    ) -> DeploymentPolicy:
        row = await self._session.scalar(
            update(ObjectContentDeploymentPolicy)
            .where(
                ObjectContentDeploymentPolicy.id == 1,
                ObjectContentDeploymentPolicy.revision == replacement.expected_revision,
            )
            .values(
                moves_paused=replacement.moves_paused,
                revision=ObjectContentDeploymentPolicy.revision + 1,
                updated_by_actor=PolicyActor.PLATFORM_ADMIN.value,
                updated_by_user_id=actor_user_id,
            )
            .returning(ObjectContentDeploymentPolicy)
        )
        if row is None:
            raise DeploymentPolicyConflict("Deployment policy revision is stale")
        return _policy(row)


async def load_upload_admission_snapshot(
    session: AsyncSession,
    *,
    inline_maximum_bytes: int,
    object_store_maximum_bytes: int | None,
) -> UploadAdmissionSnapshot:
    policy = await DeploymentPolicyRepository(session).get()
    projections = {
        projection.use_case: projection
        for projection in project_upload_limits(
            policy,
            inline_maximum_bytes=inline_maximum_bytes,
            object_store_maximum_bytes=object_store_maximum_bytes,
        )
    }
    return UploadAdmissionSnapshot(
        policy_revision=policy.revision,
        new_write_storage_target=policy.new_write_storage_target,
        session_file_maximum_bytes=projections[
            UploadLimitUseCase.SESSION_FILE
        ].effective_bytes,
        session_image_maximum_bytes=projections[
            UploadLimitUseCase.SESSION_IMAGE
        ].effective_bytes,
        session_audio_maximum_bytes=projections[
            UploadLimitUseCase.SESSION_AUDIO
        ].effective_bytes,
        knowledge_file_maximum_bytes=projections[
            UploadLimitUseCase.KNOWLEDGE_FILE
        ].effective_bytes,
        knowledge_audio_maximum_bytes=projections[
            UploadLimitUseCase.KNOWLEDGE_AUDIO
        ].effective_bytes,
    )
