from typing import TYPE_CHECKING, Optional, Union

from intric.ai_models.ai_model import AIModel
from intric.ai_models.model_enums import (
    ModelFamily,
    ModelHostingLocation,
    ModelOrg,
    ModelStability,
)
from intric.main.models import NOT_PROVIDED
from intric.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from intric.database.tables.ai_models_table import (
        EmbeddingModels as EmbeddingModelDB,
    )
    from intric.main.models import NotProvided
    from intric.users.user import UserInDB


class EmbeddingModel(AIModel):
    def __init__(
        self,
        id: Optional["UUID"],
        created_at: Optional["datetime"],
        updated_at: Optional["datetime"],
        user: "UserInDB",
        nickname: Optional[str],
        name: str,
        family: Union[ModelFamily, str],
        hosting: Union[ModelHostingLocation, str],
        org: Optional[Union[ModelOrg, str]],
        stability: Union[ModelStability, str],
        open_source: bool,
        description: Optional[str],
        hf_link: Optional[str],
        is_deprecated: bool,
        is_org_enabled: bool,
        max_input: int,
        dimensions: Optional[int],
        security_classification: Optional[SecurityClassification],
        max_batch_size: Optional[int] = None,
        litellm_model_name: Optional[str] = None,
        tenant_id: Optional["UUID"] = None,
        provider_id: Optional["UUID"] = None,
        provider_name: Optional[str] = None,
        provider_type: Optional[str] = None,
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

        self.max_input = max_input
        self.dimensions = dimensions
        self.max_batch_size = max_batch_size
        self.litellm_model_name = litellm_model_name
        self.tenant_id = tenant_id
        self.provider_id = provider_id
        self.provider_name = provider_name
        self.provider_type = provider_type

    def get_credential_provider_name(self) -> str:
        """Get the credential provider name for this model."""
        # If litellm_model_name is set, extract provider from prefix (e.g. "azure/gpt-4" → "azure")
        if self.litellm_model_name and "/" in self.litellm_model_name:
            return self.litellm_model_name.split("/")[0].lower()

        # Fall back to base implementation (checks family)
        return super().get_credential_provider_name()

    @classmethod
    def to_domain(
        cls,
        db_model: "EmbeddingModelDB",
        user: "UserInDB",
        provider_name: Optional[str] = None,
        provider_type: Optional[str] = None,
    ):
        # Settings are now directly on the model table
        return cls(
            id=db_model.id,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at,
            user=user,
            name=db_model.name,
            nickname=None,
            family=db_model.family,
            hosting=db_model.hosting,
            org=db_model.org,
            stability=db_model.stability,
            open_source=db_model.open_source,
            description=db_model.description,
            hf_link=db_model.hf_link,
            is_deprecated=db_model.is_deprecated,
            is_org_enabled=db_model.is_enabled,
            max_input=db_model.max_input,
            dimensions=db_model.dimensions,
            max_batch_size=getattr(db_model, "max_batch_size", None),
            security_classification=SecurityClassification.to_domain(
                db_security_classification=db_model.security_classification
            ),
            litellm_model_name=db_model.litellm_model_name,
            tenant_id=db_model.tenant_id,
            provider_id=db_model.provider_id,
            provider_name=provider_name,
            provider_type=provider_type,
        )

    def update(self, is_org_enabled: Union[bool, "NotProvided"]):
        if is_org_enabled is not NOT_PROVIDED:
            self.is_org_enabled = is_org_enabled
