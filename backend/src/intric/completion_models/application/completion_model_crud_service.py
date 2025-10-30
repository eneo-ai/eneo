from typing import TYPE_CHECKING, Optional, Union

from intric.completion_models.domain import ModelFamily
from intric.main.config import get_settings
from intric.main.exceptions import UnauthorizedException
from intric.main.models import NOT_PROVIDED, ModelId, NotProvided
from intric.roles.permissions import Permission, validate_permissions

if TYPE_CHECKING:
    from uuid import UUID

    from intric.completion_models.domain import CompletionModel, CompletionModelRepository
    from intric.security_classifications.domain.repositories.security_classification_repo_impl import (  # noqa: E501
        SecurityClassificationRepoImpl,
    )
    from intric.users.user import UserInDB


class CompletionModelCRUDService:
    def __init__(
        self,
        user: "UserInDB",
        completion_model_repo: "CompletionModelRepository",
        security_classification_repo: "SecurityClassificationRepoImpl",
    ):
        self.completion_model_repo = completion_model_repo
        self.user = user
        self.security_classification_repo = security_classification_repo

    async def get_completion_models(self) -> list["CompletionModel"]:
        models = await self.completion_model_repo.all()

        available_models = []
        for model in models:
            if model.family == ModelFamily.AZURE and not get_settings().using_azure_models:
                continue

            available_models.append(model)

        return available_models

    async def get_completion_model(self, model_id: "UUID") -> "CompletionModel":
        completion_model = await self.completion_model_repo.one(model_id=model_id)

        if not completion_model.can_access:
            raise UnauthorizedException()

        return completion_model

    async def get_available_completion_models(self) -> list["CompletionModel"]:
        completion_models = await self.completion_model_repo.all()

        return [model for model in completion_models if model.can_access]

    async def get_default_completion_model(self) -> "CompletionModel":
        completion_models = await self.get_available_completion_models()

        # First try to get the org default model
        for model in completion_models:
            if model.is_org_default:
                return model

        # Otherwise get the latest model
        sorted_models = sorted(completion_models, key=lambda model: model.created_at, reverse=True)

        # If no models are available
        # let each caller handle that
        if not sorted_models:
            return None

        return sorted_models[0]

    @validate_permissions(Permission.ADMIN)
    async def update_completion_model(
        self,
        model_id: "UUID",
        is_org_enabled: Optional[bool],
        is_org_default: Optional[bool],
        security_classification: Union[ModelId, None, NotProvided] = NOT_PROVIDED,
    ) -> "CompletionModel":
        completion_model = await self.completion_model_repo.one(model_id=model_id)

        if is_org_enabled is not None:
            completion_model.is_org_enabled = is_org_enabled

        if is_org_default is not None:
            completion_model.is_org_default = is_org_default

        if security_classification is not NOT_PROVIDED:
            if security_classification is None:
                cm_security_classification = None
            else:
                cm_security_classification = await self.security_classification_repo.one(
                    id=security_classification.id
                )

            completion_model.security_classification = cm_security_classification

        await self.completion_model_repo.update(completion_model)

        return completion_model
