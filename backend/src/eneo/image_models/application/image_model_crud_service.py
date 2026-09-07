from typing import TYPE_CHECKING, Optional, Union

from eneo.main.exceptions import UnauthorizedException
from eneo.main.models import NOT_PROVIDED, ModelId, NotProvided, is_provided
from eneo.roles.permissions import Permission, validate_permissions

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.image_models.domain.image_model import ImageModel
    from eneo.image_models.domain.image_model_repo import ImageModelRepository
    from eneo.security_classifications.domain.repositories.security_classification_repo_impl import (  # noqa: E501
        SecurityClassificationRepoImpl,
    )
    from eneo.users.user import UserInDB


class ImageModelCRUDService:
    def __init__(
        self,
        user: "UserInDB",
        image_model_repo: "ImageModelRepository",
        security_classification_repo: Optional["SecurityClassificationRepoImpl"] = None,
    ) -> None:
        super().__init__()
        self.image_model_repo = image_model_repo
        self.user = user
        self.security_classification_repo = security_classification_repo

    async def get_image_models(self) -> list["ImageModel"]:
        return await self.image_model_repo.all()

    async def get_image_model(self, model_id: "UUID") -> "ImageModel":
        image_model = await self.image_model_repo.one(model_id=model_id)
        if not image_model.can_access:
            raise UnauthorizedException()
        return image_model

    async def get_available_image_models(self) -> list["ImageModel"]:
        image_models = await self.image_model_repo.all()
        return [model for model in image_models if model.can_access]

    @validate_permissions(Permission.ADMIN)
    async def update_image_model(
        self,
        model_id: "UUID",
        is_org_enabled: Optional[bool],
        is_org_default: Optional[bool],
        security_classification: Union[ModelId, None, NotProvided] = NOT_PROVIDED,
    ) -> "ImageModel":
        image_model = await self.image_model_repo.one(model_id=model_id)

        if is_org_enabled is not None:
            image_model.is_org_enabled = is_org_enabled

        if is_org_default is not None:
            image_model.is_org_default = is_org_default

        if is_provided(security_classification):
            if security_classification is None:
                classification = None
            else:
                assert self.security_classification_repo is not None
                classification = await self.security_classification_repo.one(
                    id=security_classification.id
                )
            image_model.security_classification = classification

        await self.image_model_repo.update(image_model)
        return image_model
