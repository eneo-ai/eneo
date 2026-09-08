from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from eneo.ai_models.ai_model import AIModel
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from eneo.database.tables.ai_models_table import ImageModels as ImageModelsDB
    from eneo.tenants.tenant import TenantInDB


# Request vocabulary of the OpenAI Images API contract, which every provider
# LiteLLM routes image generation through speaks or is adapted to. "auto"
# sends no value so the model decides.
AUTO_IMAGE_OPTION = "auto"
IMAGE_SIZES: tuple[str, ...] = (
    AUTO_IMAGE_OPTION,
    "1024x1024",
    "1536x1024",
    "1024x1536",
)
IMAGE_QUALITIES: tuple[str, ...] = (AUTO_IMAGE_OPTION, "low", "medium", "high")


@dataclass(frozen=True)
class ImageModelUsage:
    """A capability provider (``mcp_servers`` row) that runs on the model.

    While any such provider exists the model cannot be deleted.
    """

    id: "UUID"
    name: str
    purpose: str


class ImageModel(AIModel):
    def __init__(
        self,
        *,
        tenant: "TenantInDB",
        id: "UUID",
        created_at: "datetime",
        updated_at: "datetime",
        nickname: str,
        name: str,
        family: Optional[str],
        hosting: Optional[str],
        org: Optional[str],
        stability: Optional[str],
        open_source: bool,
        description: Optional[str],
        hf_link: Optional[str],
        is_deprecated: bool,
        is_org_enabled: bool,
        is_org_default: bool,
        default_size: str = AUTO_IMAGE_OPTION,
        default_quality: str = AUTO_IMAGE_OPTION,
        cost_per_image: Optional[Decimal] = None,
        security_classification: Optional["SecurityClassification"] = None,
        tenant_id: Optional["UUID"] = None,
        provider_id: Optional["UUID"] = None,
        provider_name: Optional[str] = None,
        provider_type: Optional[str] = None,
        used_by_mcp_servers: Optional[list[ImageModelUsage]] = None,
    ):
        super().__init__(
            tenant=tenant,
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
        )

        self.is_org_default = is_org_default
        self.default_size = default_size
        self.default_quality = default_quality
        self.cost_per_image = cost_per_image
        self.security_classification = security_classification
        self.tenant_id = tenant_id
        self.used_by_mcp_servers: list[ImageModelUsage] = list(
            used_by_mcp_servers or []
        )
        self.provider_id = provider_id
        self.provider_name = provider_name
        self.provider_type = provider_type

    @classmethod
    def create_from_db(
        cls,
        image_model_db: "ImageModelsDB",
        tenant: "TenantInDB",
        provider_name: Optional[str] = None,
        provider_type: Optional[str] = None,
    ) -> "ImageModel":
        return cls(
            tenant=tenant,
            id=image_model_db.id,
            created_at=image_model_db.created_at,
            updated_at=image_model_db.updated_at,
            nickname=image_model_db.nickname,
            name=image_model_db.name,
            family=image_model_db.family,
            hosting=image_model_db.hosting,
            org=image_model_db.org,
            stability=image_model_db.stability,
            open_source=image_model_db.open_source or False,
            description=image_model_db.description,
            hf_link=image_model_db.hf_link,
            is_deprecated=image_model_db.is_deprecated,
            is_org_enabled=image_model_db.is_enabled,
            is_org_default=image_model_db.is_default,
            default_size=image_model_db.default_size,
            default_quality=image_model_db.default_quality,
            cost_per_image=image_model_db.cost_per_image,
            security_classification=SecurityClassification.to_domain(
                db_security_classification=image_model_db.security_classification
            ),
            tenant_id=image_model_db.tenant_id,
            provider_id=image_model_db.provider_id,
            provider_name=provider_name,
            provider_type=provider_type,
        )
