from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, ValidationInfo, field_validator
from pydantic.networks import HttpUrl

from intric.main.models import InDB
from intric.modules.module import ModuleInDB


class TenantState(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class PrivacyPolicyMixin(BaseModel):
    privacy_policy: Optional[HttpUrl] = None


class TenantBase(BaseModel):
    name: str
    display_name: Optional[str] = None
    quota_limit: int = Field(
        default=10 * 1024**3, description="Size in bytes. Default is 10 GB"
    )
    domain: Optional[str] = None
    zitadel_org_id: Optional[str] = None
    provisioning: bool = False
    state: TenantState = TenantState.ACTIVE
    security_enabled: bool = False

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: Optional[str], info: ValidationInfo) -> str:
        if v is not None:
            return v

        return info.data["name"]


class TenantPublic(PrivacyPolicyMixin, TenantBase):
    pass


class TenantInDB(PrivacyPolicyMixin, InDB):
    name: str
    display_name: Optional[str] = None
    quota_limit: int
    domain: Optional[str] = None
    zitadel_org_id: Optional[str] = None
    provisioning: bool = False
    state: TenantState = TenantState.ACTIVE
    security_enabled: bool = False
    modules: list[ModuleInDB] = []
    api_credentials: dict[str, Any] = Field(default_factory=dict)

    @field_validator("api_credentials")
    @classmethod
    def validate_api_credentials(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Validate JSONB structure for API credentials.

        Ensures provider keys are valid and credentials have required fields.
        Azure provider requires additional fields beyond api_key.
        """
        valid_providers = {"openai", "azure", "anthropic", "berget", "mistral", "ovhcloud"}

        for provider, cred in v.items():
            if provider not in valid_providers:
                raise ValueError(f"Invalid provider: {provider}. Must be one of: {valid_providers}")

            if not isinstance(cred, dict):
                raise ValueError(f"Provider {provider} credentials must be a dict")

            if "api_key" not in cred:
                raise ValueError(f"Provider {provider} missing required field: api_key")

            # Azure-specific validation - requires additional configuration fields
            if provider == "azure":
                required = {"api_key", "endpoint", "api_version", "deployment_name"}
                missing = required - set(cred.keys())
                if missing:
                    raise ValueError(f"Azure provider missing required fields: {missing}")

        return v


class TenantUpdatePublic(BaseModel):
    display_name: Optional[str] = None
    quota_limit: Optional[int] = None
    domain: Optional[str] = None
    zitadel_org_id: Optional[str] = None
    provisioning: Optional[bool] = None
    state: Optional[TenantState] = None
    security_enabled: Optional[bool] = None


class TenantUpdate(TenantUpdatePublic):
    id: UUID
