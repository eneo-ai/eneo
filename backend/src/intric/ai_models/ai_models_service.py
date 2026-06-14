from collections.abc import Sequence
from uuid import UUID

from intric.ai_models.completion_models.completion_model import (
    CompletionModel,
    CompletionModelPublic,
)
from intric.ai_models.completion_models.completion_models_repo import (
    CompletionModelsRepository,
)
from intric.ai_models.deprecation_lookup import is_model_effectively_deprecated
from intric.ai_models.embedding_models.embedding_model import (
    EmbeddingModelLegacy,
    EmbeddingModelPublicLegacy,
    EmbeddingModelUpdateFlags,
)
from intric.ai_models.embedding_models.embedding_models_repo import (
    AdminEmbeddingModelsService,
)
from intric.main.config import get_settings
from intric.main.datetime_utils import datetime_or_utc_min
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
    ) -> None:
        super().__init__()
        self.user = user
        self.embedding_model_repo = embedding_model_repo
        self.completion_model_repo = completion_model_repo
        self.tenant_repo = tenant_repo

    def _is_locked(
        self,
        model: CompletionModel | EmbeddingModelLegacy,
    ):
        return False

    @staticmethod
    def _is_effectively_deprecated(
        model: CompletionModel | EmbeddingModelLegacy,
    ) -> bool:
        return is_model_effectively_deprecated(
            model.name,
            getattr(model, "provider_type", None),
            manually_deprecated=model.is_deprecated,
        )

    def _can_access(
        self,
        model: CompletionModel | EmbeddingModelLegacy,
    ):
        if (
            not self._is_locked(model)
            and not self._is_effectively_deprecated(model)
            and model.is_org_enabled
        ):
            # Migrated completion models should not be accessible
            if getattr(model, "migrated_to_model_id", None) is not None:
                return False
            return True

        return False

    def _get_latest_available_model(
        self, models: Sequence[CompletionModelPublic | EmbeddingModelPublicLegacy]
    ) -> CompletionModelPublic | EmbeddingModelPublicLegacy | None:
        sorted_models: list[CompletionModelPublic | EmbeddingModelPublicLegacy] = (
            sorted(
                models,
                key=lambda model: datetime_or_utc_min(model.created_at),
                reverse=True,
            )
        )

        for model in sorted_models:
            if model.can_access:
                return model

    async def get_embedding_models(
        self, id_list: list[UUID] | None = None
    ) -> list[EmbeddingModelPublicLegacy]:
        embedding_models = await self.embedding_model_repo.get_models(
            tenant_id=self.user.tenant_id, with_deprecated=False, id_list=id_list
        )

        models: list[EmbeddingModelPublicLegacy] = []
        for model in embedding_models:
            models.append(
                EmbeddingModelPublicLegacy(
                    **model.model_dump(exclude={"is_deprecated"}),
                    is_deprecated=self._is_effectively_deprecated(model),
                    is_locked=self._is_locked(model),
                    can_access=self._can_access(model),
                )
            )

        return models

    async def get_embedding_model(self, id: UUID):
        model = await self.embedding_model_repo.get_model(
            id, tenant_id=self.user.tenant_id
        )

        if self._is_effectively_deprecated(model):
            raise BadRequestException(
                f"EmbeddingModel {model.name} not supported anymore."
            )

        can_access = self._can_access(model)
        if not can_access:
            raise UnauthorizedException(
                "Unauthorized. User has no permissions to access."
            )

        return EmbeddingModelPublicLegacy(
            **model.model_dump(exclude={"is_deprecated"}),
            is_deprecated=self._is_effectively_deprecated(model),
            is_locked=self._is_locked(model),
            can_access=can_access,
        )

    async def get_latest_available_embedding_model(self):
        models = await self.get_embedding_models()

        return self._get_latest_available_model(models)

    async def get_completion_models(
        self, id_list: list[UUID] | None = None
    ) -> list[CompletionModelPublic]:
        completion_models = await self.completion_model_repo.get_models(
            tenant_id=self.user.tenant_id,
            is_deprecated=False,
            id_list=id_list,
        )

        models: list[CompletionModelPublic] = []
        for model in completion_models:
            # See completion_model_crud_service: only the predefined global
            # Azure models (tenant_id is None) are gated by this flag. Tenant-
            # configured Azure models are explicit config and always shown.
            if (
                model.family == "azure"
                and model.tenant_id is None
                and not get_settings().using_azure_models
            ):
                continue

            models.append(
                CompletionModelPublic(
                    **model.model_dump(exclude={"is_deprecated"}),
                    is_deprecated=self._is_effectively_deprecated(model),
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
            is_org_enabled=data.is_org_enabled or False,
            embedding_model_id=embedding_model_id,
            tenant_id=self.user.tenant_id,
        )

        model = await self.embedding_model_repo.get_model(
            embedding_model_id, tenant_id=self.user.tenant_id
        )
        return EmbeddingModelPublicLegacy(
            **model.model_dump(exclude={"is_deprecated"}),
            is_deprecated=self._is_effectively_deprecated(model),
            is_locked=self._is_locked(model),
            can_access=self._can_access(model),
        )
