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

    from intric.database.tables.ai_models_table import (
        CompletionModels,
        CompletionModelSettings,
    )
    from intric.users.user import UserInDB


class CompletionModel(AIModel):
    def supports_temperature(self) -> bool:
        """Most models support temperature control"""
        return True
    
    def supports_top_p(self) -> bool:
        """Most models support top_p control"""  
        return True
    
    def supports_reasoning_effort(self) -> bool:
        """Only reasoning models (o1, o3, Claude thinking modes) support reasoning effort"""
        return self.reasoning
    
    def supports_verbosity(self) -> bool:
        """Only GPT-5 supports verbosity control"""
        return "gpt-5" in self.name.lower()
    
    def supports_max_completion_tokens(self) -> bool:
        """All models support max completion tokens"""
        return True
    
    # Convenience properties for accessing default settings
    @property
    def default_temperature(self) -> Optional[float]:
        return self.default_settings.get('temperature')
    
    @property 
    def default_top_p(self) -> Optional[float]:
        return self.default_settings.get('top_p')
        
    @property
    def default_reasoning_effort(self) -> Optional[str]:
        return self.default_settings.get('reasoning_effort')
        
    @property
    def default_verbosity(self) -> Optional[str]:
        return self.default_settings.get('verbosity')
        
    @property
    def default_max_completion_tokens(self) -> Optional[int]:
        return self.default_settings.get('max_completion_tokens')
    
    @property
    def default_max_reasoning_tokens(self) -> Optional[int]:
        return self.default_settings.get('max_reasoning_tokens')
        
    @property
    def default_max_thinking_tokens(self) -> Optional[int]:
        return self.default_settings.get('max_thinking_tokens')
    
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
        base_url: Optional[str] = None,
        litellm_model_name: Optional[str] = None,
        security_classification: Optional[SecurityClassification] = None,
        # Default model parameters (stored as JSONB for flexibility)
        default_settings: Optional[dict] = None,
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
        self.token_limit = token_limit
        self.deployment_name = deployment_name
        self.nr_billion_parameters = nr_billion_parameters
        
        # Default model parameters (stored as JSONB for flexibility)
        self.default_settings = default_settings or {}

    @classmethod
    def create_from_db(
        cls,
        completion_model_db: "CompletionModels",
        completion_model_settings: Optional["CompletionModelSettings"],
        user: "UserInDB",
    ):
        if completion_model_settings is None:
            is_org_enabled = False
            is_org_default = False
            updated_at = completion_model_db.updated_at
            security_classification = None
        else:
            is_org_enabled = completion_model_settings.is_org_enabled
            is_org_default = completion_model_settings.is_org_default
            updated_at = completion_model_settings.updated_at
            security_classification = completion_model_settings.security_classification

        org = (
            None
            if completion_model_db.org is None
            else ModelOrg(completion_model_db.org)
        )

        return cls(
            user=user,
            id=completion_model_db.id,
            created_at=completion_model_db.created_at,
            updated_at=updated_at,
            nickname=completion_model_db.nickname,
            name=completion_model_db.name,
            token_limit=completion_model_db.token_limit,
            vision=completion_model_db.vision,
            family=ModelFamily(completion_model_db.family),
            hosting=ModelHostingLocation(completion_model_db.hosting),
            org=org,
            stability=ModelStability(completion_model_db.stability),
            open_source=completion_model_db.open_source,
            description=completion_model_db.description,
            nr_billion_parameters=completion_model_db.nr_billion_parameters,
            hf_link=completion_model_db.hf_link,
            is_deprecated=completion_model_db.is_deprecated,
            deployment_name=completion_model_db.deployment_name,
            is_org_enabled=is_org_enabled,
            is_org_default=is_org_default,
            reasoning=completion_model_db.reasoning,
            base_url=completion_model_db.base_url,
            litellm_model_name=completion_model_db.litellm_model_name,
            security_classification=SecurityClassification.to_domain(
                db_security_classification=security_classification
            ),
            # Default model parameters (stored as JSONB for flexibility)
            default_settings=completion_model_db.default_settings,
        )
