# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import TYPE_CHECKING, Optional

from intric.ai_models.ai_model import AIModel
from intric.ai_models.litellm_providers.provider_registry import LiteLLMProviderRegistry
from intric.ai_models.model_enums import (
    ModelFamily,
    ModelHostingLocation,
    ModelOrg,
    ModelStability,
)
from intric.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from intric.database.tables.image_models_table import (
        ImageModels as ImageModelsDB,
    )
    from intric.database.tables.image_models_table import (
        ImageModelSettings,
    )
    from intric.users.user import UserInDB


class ImageModel(AIModel):
    """Domain entity for image generation models."""

    def __init__(
        self,
        user: "UserInDB",
        id: "UUID",
        created_at: "datetime",
        updated_at: "datetime",
        nickname: str,
        name: str,
        family: ModelFamily,
        hosting: ModelHostingLocation,
        org: Optional[ModelOrg],
        stability: ModelStability,
        open_source: bool,
        description: Optional[str],
        hf_link: Optional[str],
        is_deprecated: bool,
        is_org_enabled: bool,
        is_org_default: bool,
        max_resolution: Optional[str] = None,
        supported_sizes: Optional[list[str]] = None,
        supported_qualities: Optional[list[str]] = None,
        max_images_per_request: int = 4,
        litellm_model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        security_classification: Optional["SecurityClassification"] = None,
    ):
        super().__init__(
            user=user,
            id=id,
            created_at=created_at,
            updated_at=updated_at,
            nickname=nickname,
            name=name,
            family=family,
            hosting=hosting,
            org=org,
            stability=stability,
            open_source=open_source,
            description=description,
            hf_link=hf_link,
            is_deprecated=is_deprecated,
            is_org_enabled=is_org_enabled,
            security_classification=security_classification,
        )

        self.is_org_default = is_org_default
        self.max_resolution = max_resolution
        self.supported_sizes = supported_sizes or ["1024x1024"]
        self.supported_qualities = supported_qualities or ["standard"]
        self.max_images_per_request = max_images_per_request
        self.litellm_model_name = litellm_model_name
        self.base_url = base_url

    def get_credential_provider_name(self) -> str:
        """
        Get the credential provider name for this model.
        Checks litellm_model_name prefix first, then falls back to family.
        """
        if self.litellm_model_name:
            return LiteLLMProviderRegistry.detect_provider_from_model_name(
                self.litellm_model_name
            )
        return super().get_credential_provider_name()

    @classmethod
    def create_from_db(
        cls,
        image_model_db: "ImageModelsDB",
        image_model_settings: Optional["ImageModelSettings"],
        user: "UserInDB",
    ) -> "ImageModel":
        """Create an ImageModel domain entity from database models."""
        if image_model_settings is None:
            is_org_enabled = False
            is_org_default = False
            updated_at = image_model_db.updated_at
            security_classification = None
        else:
            is_org_enabled = image_model_settings.is_org_enabled
            is_org_default = image_model_settings.is_org_default
            updated_at = image_model_settings.updated_at
            security_classification = image_model_settings.security_classification

        org = (
            None
            if image_model_db.org is None
            else ModelOrg(image_model_db.org)
        )

        return cls(
            user=user,
            id=image_model_db.id,
            created_at=image_model_db.created_at,
            updated_at=updated_at,
            nickname=image_model_db.nickname,
            name=image_model_db.name,
            family=ModelFamily(image_model_db.family),
            hosting=ModelHostingLocation(image_model_db.hosting),
            org=org,
            stability=ModelStability(image_model_db.stability),
            open_source=image_model_db.open_source or False,
            description=image_model_db.description,
            hf_link=image_model_db.hf_link,
            is_deprecated=image_model_db.is_deprecated,
            is_org_enabled=is_org_enabled,
            is_org_default=is_org_default,
            max_resolution=image_model_db.max_resolution,
            supported_sizes=image_model_db.supported_sizes,
            supported_qualities=image_model_db.supported_qualities,
            max_images_per_request=image_model_db.max_images_per_request,
            litellm_model_name=image_model_db.litellm_model_name,
            base_url=image_model_db.base_url,
            security_classification=SecurityClassification.to_domain(
                db_security_classification=security_classification
            ),
        )
