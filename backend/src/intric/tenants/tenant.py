import re
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
        default=10 * 1024**3,
        description="Size in bytes. Default is 10 GB",
        json_schema_extra={"format": "int64"},
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
    slug: Optional[str] = None
    quota_limit: int
    domain: Optional[str] = None
    zitadel_org_id: Optional[str] = None
    provisioning: bool = False
    state: TenantState = TenantState.ACTIVE
    security_enabled: bool = False
    modules: list[ModuleInDB] = []
    api_credentials: dict[str, Any] = Field(default_factory=dict)
    federation_config: dict[str, Any] = Field(default_factory=dict)
    crawler_settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: Optional[str]) -> Optional[str]:
        """Validate slug format (URL-safe, lowercase, alphanumeric + hyphens)."""
        if v is None:
            return v

        # Must be lowercase alphanumeric with hyphens only
        if not re.match(r"^[a-z0-9-]+$", v):
            raise ValueError(
                "Slug must contain only lowercase letters, numbers, and hyphens"
            )

        # Must not start or end with hyphen
        if v.startswith("-") or v.endswith("-"):
            raise ValueError("Slug cannot start or end with a hyphen")

        # Length validation (DNS label limit)
        if len(v) > 63:
            raise ValueError("Slug cannot exceed 63 characters")

        return v

    @field_validator("api_credentials")
    @classmethod
    def validate_api_credentials(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Validate JSONB structure for API credentials.

        Ensures provider keys are valid and credentials have required fields.
        Azure provider requires additional fields beyond api_key.
        """
        valid_providers = {
            "openai",
            "azure",
            "anthropic",
            "berget",
            "gdm",
            "mistral",
            "ovhcloud",
            "gemini",
            "cohere",
        }

        for provider, cred in v.items():
            if provider not in valid_providers:
                raise ValueError(
                    f"Invalid provider: {provider}. Must be one of: {valid_providers}"
                )

            if not isinstance(cred, dict):
                raise ValueError(f"Provider {provider} credentials must be a dict")

            # Basic validation: all providers must have api_key
            # (Provider-specific field validation happens in routers when setting credentials)
            if "api_key" not in cred:
                raise ValueError(f"Provider {provider} missing required field: api_key")

        return v

    @field_validator("federation_config")
    @classmethod
    def validate_federation_config(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Validate JSONB structure for federation config."""
        if not v:
            return {}

        # Required fields for federation
        required = {
            "provider",
            "client_id",
            "client_secret",
            "discovery_endpoint",
        }
        missing = required - set(v.keys())
        if missing:
            raise ValueError(f"Federation config missing required fields: {missing}")

        # Provider is just a label - any string is valid (no validation needed)
        # This allows any OIDC-compliant provider (Entra ID, Auth0, Okta, Keycloak, etc.)

        # Validate canonical_public_origin (optional field)
        if "canonical_public_origin" in v:
            from intric.main.config import validate_public_origin
            try:
                v["canonical_public_origin"] = validate_public_origin(
                    v["canonical_public_origin"]
                )
            except ValueError as e:
                raise ValueError(
                    f"Invalid canonical_public_origin in federation_config: {e}"
                )

        # Validate redirect_path (optional field)
        if "redirect_path" in v:
            redirect_path = v["redirect_path"]
            if not isinstance(redirect_path, str):
                raise ValueError("redirect_path must be a string")
            if not redirect_path.startswith("/"):
                raise ValueError("redirect_path must start with /")

        # Validate allowed_domains (optional but recommended)
        if "allowed_domains" in v:
            if not isinstance(v["allowed_domains"], list):
                raise ValueError("allowed_domains must be a list")
            if not all(isinstance(d, str) for d in v["allowed_domains"]):
                raise ValueError("allowed_domains must contain only strings")

        return v

    @field_validator("crawler_settings")
    @classmethod
    def validate_crawler_settings(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Validate JSONB structure for crawler settings.

        All fields are optional - only validates types and ranges for provided fields.
        Missing fields will fall back to environment variable defaults at runtime.

        Uses CRAWLER_SETTING_SPECS from crawler_settings_helper.py as single source of truth.
        """
        if not v:
            return {}

        # Import here to avoid circular dependency
        from intric.tenants.crawler_settings_helper import validate_crawler_setting

        for key, value in v.items():
            errors = validate_crawler_setting(key, value)
            if errors:
                raise ValueError(errors[0])

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

        Note:
            Preserves credential structure (endpoint, api_version, etc.)
            but masks only the api_key field to prevent exposing encrypted values.
        """
        # Extract all tenant data
        data = tenant.model_dump()

        # Mask the api_credentials - preserve structure but mask api_key field only
        if tenant.api_credentials:
            masked = {}
            for provider, cred in tenant.api_credentials.items():
                if isinstance(cred, dict):
                    # Preserve structure: copy all fields except mask api_key
                    masked_cred = cred.copy()
                    api_key = cred.get("api_key", "")

                    # Mask the api_key field
                    if len(api_key) > 4:
                        masked_cred["api_key"] = f"...{api_key[-4:]}"
                    else:
                        masked_cred["api_key"] = "***"

                    masked[provider] = masked_cred
                else:
                    # Legacy string format (shouldn't happen, but handle gracefully)
                    api_key = str(cred)
                    if len(api_key) > 4:
                        masked[provider] = f"...{api_key[-4:]}"
                    else:
                        masked[provider] = "***"

            data["api_credentials"] = masked
        else:
            data["api_credentials"] = {}

        return cls.model_construct(**data)
