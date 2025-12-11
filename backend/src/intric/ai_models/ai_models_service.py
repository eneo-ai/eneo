from uuid import UUID

from intric.ai_models.completion_models.completion_model import (
    CompletionModel,
    CompletionModelFamily,
    CompletionModelPublic,
)
from intric.ai_models.completion_models.completion_models_repo import (
    CompletionModelsRepository,
)
from intric.ai_models.embedding_models.embedding_model import (
    EmbeddingModelLegacy,
    EmbeddingModelPublicLegacy,
    EmbeddingModelUpdateFlags,
)
from intric.ai_models.embedding_models.embedding_models_repo import (
    AdminEmbeddingModelsService,
)
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.roles.permissions import Permission, validate_permissions
from intric.tenants.tenant_repo import TenantRepository
from intric.users.user import UserInDB


class AIModelsService:
    def __init__(
        self,
        user: UserInDB,
        embedding_model_repo: AdminEmbeddingModelsService,
        completion_model_repo: CompletionModelsRepository,
        tenant_repo: TenantRepository,
    ):
        self.user = user
        self.embedding_model_repo = embedding_model_repo
        self.completion_model_repo = completion_model_repo
        self.tenant_repo = tenant_repo

    def _is_locked(
        self,
        model: CompletionModel | EmbeddingModelLegacy,
    ):
        return False

    def _can_access(
        self,
        model: CompletionModel | EmbeddingModelLegacy,
    ):
        if not self._is_locked(model) and not model.is_deprecated and model.is_org_enabled:
            return True

        return False

    def _get_latest_available_model(
        self, models: list[CompletionModelPublic | EmbeddingModelPublicLegacy]
    ) -> CompletionModelPublic | EmbeddingModelPublicLegacy:
        sorted_models = sorted(models, key=lambda model: model.created_at, reverse=True)

        for model in sorted_models:
            if model.can_access:
                return model

    async def get_embedding_models(
        self, id_list: list[UUID] = None
    ) -> list[EmbeddingModelPublicLegacy]:
        embedding_models = await self.embedding_model_repo.get_models(
            tenant_id=self.user.tenant_id, with_deprecated=False, id_list=id_list
        )

        models = []
        for model in embedding_models:
            models.append(
                EmbeddingModelPublicLegacy(
                    **model.model_dump(),
                    is_locked=self._is_locked(model),
                    can_access=self._can_access(model),
                )
            )

        return models

    async def get_embedding_model(self, id: UUID):
        model = await self.embedding_model_repo.get_model(id, tenant_id=self.user.tenant_id)

        if model.is_deprecated:
            raise BadRequestException(f"EmbeddingModel {model.name} not supported anymore.")

        can_access = self._can_access(model)
        if not can_access:
            raise UnauthorizedException("Unauthorized. User has no permissions to access.")

        return EmbeddingModelPublicLegacy(
            **model.model_dump(),
            is_locked=self._is_locked(model),
            can_access=can_access,
        )

    async def get_latest_available_embedding_model(self):
        models = await self.get_embedding_models()

        return self._get_latest_available_model(models)

    async def get_completion_models(
        self, id_list: list[UUID] = None
    ) -> list[CompletionModelPublic]:
        completion_models = await self.completion_model_repo.get_models(
            tenant_id=self.user.tenant_id,
            is_deprecated=False,
            id_list=id_list,
        )

        models = []
        for model in completion_models:
            if (
                model.family == CompletionModelFamily.AZURE
                and not get_settings().using_azure_models
            ):
                continue

            models.append(
                CompletionModelPublic(
                    **model.model_dump(),
                    is_locked=self._is_locked(model),
                    can_access=self._can_access(model),
                )
            )

        return models

    @validate_permissions(Permission.ADMIN)
    async def enable_embedding_model(
        self, embedding_model_id: UUID, data: EmbeddingModelUpdateFlags
    ):
        await self.embedding_model_repo.enable_embedding_model(
            is_org_enabled=data.is_org_enabled,
            embedding_model_id=embedding_model_id,
            tenant_id=self.user.tenant_id,
        )

        model = await self.embedding_model_repo.get_model(
            embedding_model_id, tenant_id=self.user.tenant_id
        )
        return EmbeddingModelPublicLegacy(
            **model.model_dump(),
            is_locked=self._is_locked(model),
            can_access=self._can_access(model),
        )
