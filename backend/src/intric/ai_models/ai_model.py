from typing import TYPE_CHECKING, Optional, Union

from intric.ai_models.model_enums import (
    ModelFamily,
    ModelHostingLocation,
    ModelOrg,
    ModelStability,
)
from intric.base.base_entity import Entity
from intric.main.config import get_settings
from intric.modules.module import Modules

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from intric.security_classifications.domain.entities.security_classification import (
        SecurityClassification,
    )
    from intric.users.user import UserInDB


class AIModel(Entity):
    def __init__(
        self,
        *,
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
        id: Optional["UUID"] = None,
        created_at: Optional["datetime"] = None,
        updated_at: Optional["datetime"] = None,
        security_classification: Optional["SecurityClassification"] = None,
    ):
        super().__init__(id, created_at, updated_at)
        self.user = user
        self.nickname = nickname
        self.name = name
        # Allow both enum and string values for tenant model flexibility
        self.family = self._to_enum_or_str(family, ModelFamily)
        self.hosting = self._to_enum_or_str(hosting, ModelHostingLocation)
        self.org = self._to_enum_or_str(org, ModelOrg) if org else None
        self.stability = self._to_enum_or_str(stability, ModelStability)
        self.open_source = open_source
        self.description = description
        self.hf_link = hf_link
        self.is_deprecated = is_deprecated
        self.is_org_enabled = is_org_enabled
        self.security_classification = security_classification

    @staticmethod
    def _to_enum_or_str(value, enum_class):
        """Convert to enum if valid, otherwise keep as string for tenant models."""
        if value is None:
            return None
        if isinstance(value, enum_class):
            return value
        try:
            return enum_class(value)
        except (ValueError, KeyError):
            # For tenant models with dynamic values, keep as string
            return value

    def get_credential_provider_name(self) -> str:
        """
        Get the credential provider name for this model.
        Base implementation uses family value with special handling for Claude.
        Subclasses can override to check litellm_model_name prefix.
        """
        # Claude models use 'anthropic' credentials
        if self.family == ModelFamily.CLAUDE or self.family == "claude":
            return "anthropic"
        # Handle both enum and string values
        return self.family.value if isinstance(self.family, ModelFamily) else self.family

    @property
    def is_locked(self):
        # Handle both enum and string values
        if self.hosting in (ModelHostingLocation.EU, "eu"):
            if Modules.EU_HOSTING not in self.user.modules:
                return True

        if self.hosting in (ModelHostingLocation.SWE, "swe"):
            if Modules.SWE_HOSTING not in self.user.modules:
                return True

        return False

    @property
    def lock_reason(self) -> Optional[str]:
        # Handle both enum and string values
        if self.hosting in (ModelHostingLocation.EU, "eu"):
            if Modules.EU_HOSTING not in self.user.modules:
                return "module"

        if self.hosting in (ModelHostingLocation.SWE, "swe"):
            if Modules.SWE_HOSTING not in self.user.modules:
                return "module"

        # Check if tenant credentials are missing
        if get_settings().tenant_credentials_enabled:
            provider = self.get_credential_provider_name()
            if not self.user.tenant or not self.user.tenant.api_credentials:
                return "credentials"
            if provider not in self.user.tenant.api_credentials:
                return "credentials"

        return None

    @property
    def can_access(self):
        return not self.is_locked and not self.is_deprecated and self.is_org_enabled

    def meets_security_classification(
        self, security_classification: Optional["SecurityClassification"] = None
    ):
        if security_classification is None:
            return True
        else:
            if self.security_classification is None:
                return False

            return (
                self.security_classification.security_level
                >= security_classification.security_level
            )
