# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import TYPE_CHECKING, Optional, Union

from intric.main.exceptions import UnauthorizedException
from intric.main.models import NOT_PROVIDED, ModelId, NotProvided
from intric.roles.permissions import Permission, validate_permissions

if TYPE_CHECKING:
    from uuid import UUID

    from intric.image_models.domain.image_model import ImageModel
    from intric.image_models.domain.image_model_repo import ImageModelRepository
    from intric.security_classifications.domain.repositories.security_classification_repo_impl import (
        SecurityClassificationRepoImpl,
    )
    from intric.users.user import UserInDB


class ImageModelCRUDService:
    """Service for managing image generation models."""

    def __init__(
        self,
        user: "UserInDB",
        image_model_repo: "ImageModelRepository",
        security_classification_repo: Optional["SecurityClassificationRepoImpl"] = None,
    ):
        self.image_model_repo = image_model_repo
        self.user = user
        self.security_classification_repo = security_classification_repo

    async def get_image_models(self) -> list["ImageModel"]:
        """Get all image models with tenant-specific settings."""
        return await self.image_model_repo.all()

    async def get_image_model(self, model_id: "UUID") -> "ImageModel":
        """Get a specific image model by ID."""
        image_model = await self.image_model_repo.one(model_id=model_id)

        if not image_model.can_access:
            raise UnauthorizedException("You do not have access to this image model")

        return image_model

    async def get_available_image_models(self) -> list["ImageModel"]:
        """Get all image models that the user can access."""
        image_models = await self.image_model_repo.all()
        return [model for model in image_models if model.can_access]

    async def get_default_image_model(self) -> Optional["ImageModel"]:
        """Get the default image model for the tenant."""
        image_models = await self.get_available_image_models()

        # First try to get the org default model
        for model in image_models:
            if model.is_org_default:
                return model

        # Otherwise get the first available model
        if image_models:
            return image_models[0]

        return None

    @validate_permissions(Permission.ADMIN)
    async def update_image_model(
        self,
        model_id: "UUID",
        is_org_enabled: Optional[bool] = None,
        is_org_default: Optional[bool] = None,
        security_classification: Union[ModelId, None, NotProvided] = NOT_PROVIDED,
    ) -> "ImageModel":
        """Update tenant-specific settings for an image model (admin only)."""
        image_model = await self.image_model_repo.one(model_id=model_id)

        if is_org_enabled is not None:
            image_model.is_org_enabled = is_org_enabled

        if is_org_default is not None:
            image_model.is_org_default = is_org_default

        if security_classification is not NOT_PROVIDED:
            if security_classification is None:
                im_security_classification = None
            else:
                im_security_classification = await self.security_classification_repo.one(
                    id=security_classification.id
                )
            image_model.security_classification = im_security_classification

        await self.image_model_repo.update(image_model)

        return image_model
