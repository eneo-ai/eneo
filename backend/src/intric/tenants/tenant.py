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
        valid_providers = {"openai", "azure", "anthropic", "berget", "mistral", "ovhcloud", "vllm"}

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


class TenantWithMaskedCredentials(TenantInDB):
    """TenantInDB with masked API credentials for safe API responses.

    This model is used when returning tenant data through API endpoints
    to prevent exposing full API keys. The api_credentials field is
    automatically masked to show only the last 4 characters of each key.

    Example:
        Full credential: {"openai": {"api_key": "sk-proj-abc123xyz"}}
        Masked: {"openai": "...xyz"}
    """

    # Override the parent's field validator to skip validation for masked credentials
    @field_validator("api_credentials", mode="before")
    @classmethod
    def skip_validation_for_masked(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Skip validation for masked credentials.

        Masked credentials are already validated in from_tenant() and don't
        have the same structure as full credentials (they're strings, not dicts).
        This validator runs in "before" mode to prevent the parent validator
        from running on masked data.
        """
        return v

    @classmethod
    def from_tenant(cls, tenant: TenantInDB) -> "TenantWithMaskedCredentials":
        """Convert TenantInDB to version with masked credentials.

        Args:
            tenant: The TenantInDB instance with full credentials

        Returns:
            TenantWithMaskedCredentials with api_credentials masked
        """
        # Extract all tenant data
        data = tenant.model_dump()

        # Mask the api_credentials
        if tenant.api_credentials:
            masked = {}
            for provider, cred in tenant.api_credentials.items():
                # Extract api_key from credential dict
                if isinstance(cred, dict):
                    api_key = cred.get("api_key", "")
                else:
                    api_key = str(cred)

                # Mask the key - show last 4 chars
                if len(api_key) > 4:
                    masked[provider] = f"...{api_key[-4:]}"
                else:
                    masked[provider] = "***"

            data["api_credentials"] = masked
        else:
            data["api_credentials"] = {}

        return cls.model_construct(**data)
