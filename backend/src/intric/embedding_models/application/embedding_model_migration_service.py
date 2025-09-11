from typing import TYPE_CHECKING

from intric.jobs.job_models import Task
from intric.jobs.task_models import EmbeddingModelMigrationTask
from intric.main.exceptions import BadRequestException
from intric.roles.permissions import Permission, validate_permissions

if TYPE_CHECKING:
    from uuid import UUID

    from intric.embedding_models.domain.embedding_model_repo import (
        EmbeddingModelRepository,
    )
    from intric.jobs.job_service import JobService
    from intric.users.user import UserInDB


class EmbeddingModelMigrationService:
    def __init__(
        self,
        user: "UserInDB",
        embedding_model_repo: "EmbeddingModelRepository",
        job_service: "JobService",
    ):
        self.user = user
        self.embedding_model_repo = embedding_model_repo
        self.job_service = job_service

    @validate_permissions(Permission.ADMIN)
    async def start_migration(
        self,
        old_embedding_model_id: "UUID",
        new_embedding_model_id: "UUID",
        group_limit: int | None = None,
    ):
        # Validate both embedding models exist
        old_model = await self.embedding_model_repo.one(model_id=old_embedding_model_id)
        new_model = await self.embedding_model_repo.one(model_id=new_embedding_model_id)
        
        # Validate new model is org-enabled
        if not new_model.is_org_enabled:
            raise BadRequestException("Target embedding model must be org-enabled before migration")

        # Create migration task parameters
        migration_params = EmbeddingModelMigrationTask(
            user_id=self.user.id,
            old_embedding_model_id=old_embedding_model_id,
            new_embedding_model_id=new_embedding_model_id,
            group_limit=group_limit,
        )

        # Queue the migration job
        job = await self.job_service.queue_job(
            task=Task.MIGRATE_EMBEDDING_MODEL,
            name=f"Migrate from {old_model.name} to {new_model.name}",
            task_params=migration_params,
        )

        return job