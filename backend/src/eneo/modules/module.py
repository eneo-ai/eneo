import re
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, computed_field, field_validator

from eneo.main.config import validate_redirect_uri
from eneo.main.models import InDB

# The stable key travels as a URL path segment (the auth-broker session and
# refresh routes), a module-side environment variable and a JWT-audience
# suffix, so new keys are restricted to an ASCII slug. A '/' in particular can
# never be routed: it is decoded before path matching, so such a module could
# exchange its first token but never validate or renew the session.
MODULE_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_MODULE_KEY_PATTERN = re.compile(MODULE_KEY_PATTERN)


def _normalize_redirect_uris(value: list[str]) -> list[str]:
    normalized: list[str] = []
    for uri in value:
        redirect_uri = validate_redirect_uri(uri)
        if redirect_uri is None:
            raise ValueError(f"Invalid redirect URI: {uri}")
        if redirect_uri not in normalized:
            normalized.append(redirect_uri)
    return normalized


def is_url_safe_module_key(value: str) -> bool:
    """True when the key can travel as a single URL path segment.

    Rows that predate the registration restriction may fail this; they stay
    readable but cannot be enabled for login handoff.
    """
    return _MODULE_KEY_PATTERN.fullmatch(value) is not None


class ModuleBase(BaseModel):
    """A module's globally unique machine identity.

    ``name`` predates the auth broker, but is its stable public module key. It
    is case-sensitive and has no rename API; registration restricts new keys
    to a URL-safe slug. Read models stay permissive so rows that predate the
    restriction (e.g. ``SWE Models``) keep loading. A separate display name
    can be introduced if one is needed.
    """

    name: str


class ModuleCreate(ModuleBase):
    """Registration contract for a new stable module key."""

    name: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def validate_stable_key(cls, value: str) -> str:
        if not _MODULE_KEY_PATTERN.fullmatch(value):
            raise ValueError(
                "Module key must be a URL-safe slug: letters and digits plus "
                "'.', '_' or '-', starting with a letter or digit."
            )
        return value


class ModuleClientConfig(BaseModel):
    """Auth-broker client config for a module: which callback URLs are allowed
    and which sk_ key alone may exchange the module's login tickets."""

    redirect_uris: Optional[list[str]] = None
    service_key_id: Optional[UUID] = None

    @field_validator("redirect_uris")
    @classmethod
    def normalize_redirect_uris(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        return _normalize_redirect_uris(value)

    def update_values(self) -> dict[str, object]:
        """Return only fields explicitly supplied by the PATCH caller.

        An explicit ``null`` remains an update while an omitted field is left
        untouched. Keeping this distinction on the request model prevents
        persistence adapters from accidentally turning PATCH into PUT.
        """
        values: dict[str, object] = {}
        if "redirect_uris" in self.model_fields_set:
            values["redirect_uris"] = self.redirect_uris
        if "service_key_id" in self.model_fields_set:
            values["service_key_id"] = self.service_key_id
        return values


class ModuleTenantClientConfig(ModuleClientConfig):
    tenant_id: UUID
    module_id: UUID


class ModuleTenantAssignment(BaseModel):
    """Narrow result for enabling or disabling one tenant module."""

    tenant_id: UUID
    module_id: UUID
    module_key: str
    enabled: bool
    changed: bool


class ModuleInstallationConfig(BaseModel):
    """Complete, tenant-implicit configuration accepted by the admin UI."""

    redirect_uris: list[str] = Field(min_length=1)
    service_key_id: UUID

    @field_validator("redirect_uris")
    @classmethod
    def normalize_redirect_uris(cls, value: list[str]) -> list[str]:
        return _normalize_redirect_uris(value)


class ModuleInstallation(BaseModel):
    """One module installed for the authenticated user's organization.

    The tenant id is intentionally absent. It is derived from the session and
    remains an internal data-partition key rather than an admin-UI concept.
    Older assignments may be incomplete, so reads retain nullable config while
    the new installation command only accepts a complete configuration.
    """

    module_id: UUID
    module_key: str
    redirect_uris: list[str] = Field(default_factory=list)
    service_key_id: Optional[UUID] = None

    @computed_field
    @property
    def configured(self) -> bool:
        return bool(self.redirect_uris) and self.service_key_id is not None


class ModuleInstallationChange(BaseModel):
    """Tenant-free result for an idempotent installation state change."""

    module_id: UUID
    module_key: str
    enabled: bool
    changed: bool


class ModuleInDB(InDB, ModuleBase):
    pass
