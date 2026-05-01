from typing import TYPE_CHECKING, Optional

from typing_extensions import override

from intric.ai_models.ai_model import AIModel
from intric.completion_models.domain.model_kwargs_capabilities import (
    SupportedModelKwargs,
    coerce_model_kwargs_capabilities,
    resolve_supported_model_kwargs,
)
from intric.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal
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
        max_input_tokens: int,
        max_output_tokens: int,
        vision: bool,
        family: Optional[str],
        hosting: Optional[str],
        org: Optional[str],
        stability: Optional[str],
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
        model_kwargs_capabilities: SupportedModelKwargs
        | dict[str, object]
        | None = None,
        input_cost_per_token: Optional["Decimal"] = None,
        output_cost_per_token: Optional["Decimal"] = None,
        security_classification: Optional[SecurityClassification] = None,
        tenant_id: Optional["UUID"] = None,
        provider_id: Optional["UUID"] = None,
        provider_name: Optional[str] = None,
        provider_type: Optional[str] = None,
        migrated_to_model_id: Optional["UUID"] = None,
        deleted_at: Optional["datetime"] = None,
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
        self.model_kwargs_capabilities = coerce_model_kwargs_capabilities(
            model_kwargs_capabilities,
            completion_model_id=id,
            tenant_id=tenant_id,
        )
        self.is_org_default = is_org_default
        self.reasoning = reasoning
        self.vision = vision
        self.supports_tool_calling = supports_tool_calling
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.deployment_name = deployment_name
        self.nr_billion_parameters = nr_billion_parameters
        self.input_cost_per_token = input_cost_per_token
        self.output_cost_per_token = output_cost_per_token
        self.tenant_id = tenant_id
        self.provider_id = provider_id
        self.provider_name = provider_name
        self.provider_type = provider_type
        self.migrated_to_model_id = migrated_to_model_id
        self.deleted_at = deleted_at

    @property
    def can_access(self):
        return (
            super().can_access
            and self.migrated_to_model_id is None
            and self.deleted_at is None
        )

    @property
    def token_limit(self) -> int:
        """Backward-compat alias: returns max_input_tokens."""
        return self.max_input_tokens

    def get_supported_model_kwargs(self) -> SupportedModelKwargs:
        return resolve_supported_model_kwargs(
            model_kwargs_capabilities=self.model_kwargs_capabilities,
            reasoning=self.reasoning,
            provider_type=self.provider_type,
            litellm_model_name=self.litellm_model_name,
            completion_model_id=self.id,
            tenant_id=self.tenant_id,
        )

    @override
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
    ) -> "CompletionModel":
        # Settings are now directly on the model table
        return cls(
            user=user,
            id=completion_model_db.id,
            created_at=completion_model_db.created_at,
            updated_at=completion_model_db.updated_at,
            nickname=completion_model_db.nickname,
            name=completion_model_db.name,
            max_input_tokens=completion_model_db.max_input_tokens,
            max_output_tokens=completion_model_db.max_output_tokens,
            vision=completion_model_db.vision,
            family=completion_model_db.family,
            hosting=completion_model_db.hosting,
            org=completion_model_db.org,
            stability=completion_model_db.stability,
            open_source=bool(completion_model_db.open_source),
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
            model_kwargs_capabilities=completion_model_db.model_kwargs_capabilities,
            input_cost_per_token=completion_model_db.input_cost_per_token,
            output_cost_per_token=completion_model_db.output_cost_per_token,
            security_classification=SecurityClassification.to_domain(
                db_security_classification=completion_model_db.security_classification
            ),
            tenant_id=completion_model_db.tenant_id,
            provider_id=completion_model_db.provider_id,
            provider_name=provider_name,
            provider_type=provider_type,
            migrated_to_model_id=completion_model_db.migrated_to_model_id,
            deleted_at=completion_model_db.deleted_at,
        )
