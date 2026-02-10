from typing import TYPE_CHECKING, Optional

from intric.ai_models.ai_model import AIModel
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

    from intric.database.tables.ai_models_table import CompletionModels
    from intric.users.user import UserInDB


class CompletionModel(AIModel):
    def __init__(
        self,
        user: "UserInDB",
        id: "UUID",
        created_at: "datetime",
        updated_at: "datetime",
        nickname: str,
        name: str,
        token_limit: int,
        vision: bool,
        family: ModelFamily,
        hosting: ModelHostingLocation,
        org: Optional[ModelOrg],
        stability: ModelStability,
        open_source: bool,
        description: Optional[str],
        nr_billion_parameters: Optional[int],
        hf_link: Optional[str],
        is_deprecated: bool,
        deployment_name: Optional[str],
        is_org_enabled: bool,
        is_org_default: bool,
        reasoning: bool,
        supports_tool_calling: bool = False,
        base_url: Optional[str] = None,
        litellm_model_name: Optional[str] = None,
        security_classification: Optional[SecurityClassification] = None,
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

        self.base_url = base_url
        self.litellm_model_name = litellm_model_name
        self.is_org_default = is_org_default
        self.reasoning = reasoning
        self.vision = vision
        self.supports_tool_calling = supports_tool_calling
        self.token_limit = token_limit
        self.deployment_name = deployment_name
        self.nr_billion_parameters = nr_billion_parameters
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
    def create_from_db(
        cls,
        completion_model_db: "CompletionModels",
        user: "UserInDB",
        provider_name: Optional[str] = None,
        provider_type: Optional[str] = None,
    ):
        # Settings are now directly on the model table
        return cls(
            user=user,
            id=completion_model_db.id,
            created_at=completion_model_db.created_at,
            updated_at=completion_model_db.updated_at,
            nickname=completion_model_db.nickname,
            name=completion_model_db.name,
            token_limit=completion_model_db.token_limit,
            vision=completion_model_db.vision,
            family=completion_model_db.family,
            hosting=completion_model_db.hosting,
            org=completion_model_db.org,
            stability=completion_model_db.stability,
            open_source=completion_model_db.open_source,
            description=completion_model_db.description,
            nr_billion_parameters=completion_model_db.nr_billion_parameters,
            hf_link=completion_model_db.hf_link,
            is_deprecated=completion_model_db.is_deprecated,
            deployment_name=completion_model_db.deployment_name,
            is_org_enabled=completion_model_db.is_enabled,
            is_org_default=completion_model_db.is_default,
            reasoning=completion_model_db.reasoning,
            supports_tool_calling=completion_model_db.supports_tool_calling,
            base_url=completion_model_db.base_url,
            litellm_model_name=completion_model_db.litellm_model_name,
            security_classification=SecurityClassification.to_domain(
                db_security_classification=completion_model_db.security_classification
            ),
            tenant_id=completion_model_db.tenant_id,
            provider_id=completion_model_db.provider_id,
            provider_name=provider_name,
            provider_type=provider_type,
        )
