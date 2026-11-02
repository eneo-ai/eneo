"""The one owner of a tenant's OIDC federation settings.

Two doors use it. The operator's super-key routes (tenant_federation_router)
register, replace, patch, test and delete a tenant's identity provider. An org
admin in an interactive session (tenant_self_federation_router) edits the label,
client ID, secret and allowed domains of their own tenant's IdP; the
authorization server and everything derived from it, the redirect topology and
the claim mapping stay with the operator.

Every write reads the stored config with the tenant row locked, is audited as
FEDERATION_UPDATED in the same transaction (always, whatever the tenant's audit
settings) and commits with it. The secret is write-only: it is encrypted before
storage and never appears in a response, a log line or an audit value.
"""

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Annotated, Any, Literal, Optional, Self, cast

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.main.config import (
    Settings,
    get_settings,
    validate_public_origin,
    validate_redirect_path,
    validate_redirect_uri,
)
from eneo.main.logging import get_logger
from eneo.settings.credential_resolver import CredentialResolver
from eneo.settings.encryption_service import EncryptionService
from eneo.tenants.masking import looks_masked
from eneo.tenants.tenant import TenantInDB
from eneo.tenants.tenant_repo import TenantRepository

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService
    from eneo.users.user import UserInDB

logger = get_logger(__name__)


DEFAULT_FEDERATION_SCOPES = ["openid", "email", "profile"]
DEFAULT_CLAIMS_MAPPING = {
    "email": "email",
    "username": "sub",
    "name": "name",
}
# The fields an operator's registration stores; a config holding only redirect
# fields is not a registered IdP.
_REGISTRATION_FIELDS = ("provider", "client_id", "client_secret", "discovery_endpoint")
_DOMAIN_PATTERN = re.compile(r"^[a-z0-9]+([\-\.]{1}[a-z0-9]+)*\.[a-z]{2,}$")
_OPERATOR_ACTOR = {"type": "sysadmin", "via": "eneo_super_api_key"}


def _validate_domains(domains: list[str] | None) -> list[str] | None:
    """Lower-case email domains in the one format both doors accept."""
    if domains is None:
        return None
    for domain in domains:
        if not _DOMAIN_PATTERN.match(domain.lower()):
            raise ValueError(f"Invalid domain format: {domain}")
    return [d.lower() for d in domains]


class FederationRequestBase(BaseModel):
    """Shared fields and validation for federation write operations."""

    provider: str | None = Field(
        None,
        description="Identity provider label (e.g., 'mobilityguard', 'entra_id', 'okta', 'auth0')",
    )
    discovery_endpoint: str | None = Field(
        None,
        description="OIDC discovery endpoint URL",
        examples=[
            "https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration"
        ],
    )
    client_id: str | None = Field(None, description="OAuth client ID")
    client_secret: str | None = Field(
        None, min_length=8, description="OAuth client secret"
    )
    allowed_domains: list[str] | None = Field(
        None,
        description="Email domains allowed for this tenant (e.g., ['stockholm.se'])",
        examples=[["stockholm.se", "stockholm.gov.se"]],
    )
    canonical_public_origin: str | None = Field(
        None,
        description=(
            "Canonical public origin for this tenant (e.g., https://tenant.eneo.se). "
            "Required when federation is enabled to construct redirect_uri"
        ),
        examples=["https://stockholm.eneo.se"],
    )
    redirect_path: str | None = Field(
        None,
        description="Optional custom redirect path starting with /",
        examples=["/auth/callback"],
    )
    additional_redirect_uris: list[str] | None = Field(
        None,
        description=(
            "Additional fully-qualified redirect URIs for OIDC flows. "
            "Use when the tenant is accessed through multiple origins. "
            "Each URI must also be registered in the upstream Identity Provider."
        ),
        examples=[["https://qwerty.sundsvall.se/api/eneo/login/callback"]],
    )

    @field_validator("client_secret")
    @classmethod
    def validate_client_secret(cls, v: str | None) -> str | None:
        """Trim whitespace from client secret."""
        if v is None:
            return None
        return v.strip()

    @field_validator("allowed_domains")
    @classmethod
    def validate_allowed_domains(cls, v: list[str] | None) -> list[str] | None:
        """Validate domain format."""
        return _validate_domains(v)

    @field_validator("canonical_public_origin")
    @classmethod
    def validate_canonical_public_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_public_origin(value)

    @field_validator("redirect_path")
    @classmethod
    def validate_redirect_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_redirect_path(value)

    @field_validator("additional_redirect_uris")
    @classmethod
    def validate_additional_redirect_uris(
        cls, value: list[str] | None
    ) -> list[str] | None:
        if value is None:
            return None
        validated = [validate_redirect_uri(uri) for uri in value]
        return [uri for uri in validated if uri is not None]


class SetFederationRequest(FederationRequestBase):
    """Request model for providing a full tenant federation config."""

    # Pydantic field narrowing: required fields in subclass override optional fields in base.
    # pyright: ignore[reportIncompatibleVariableOverride] applies per-field below.
    provider: str = Field(  # pyright: ignore[reportIncompatibleVariableOverride]
        ...,
        description="Identity provider label (e.g., 'mobilityguard', 'entra_id', 'okta', 'auth0')",
    )
    discovery_endpoint: str = Field(  # pyright: ignore[reportIncompatibleVariableOverride]
        ...,
        description="OIDC discovery endpoint URL",
        examples=[
            "https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration"
        ],
    )
    client_id: str = Field(..., description="OAuth client ID")  # pyright: ignore[reportIncompatibleVariableOverride]
    client_secret: str = Field(..., min_length=8, description="OAuth client secret")  # pyright: ignore[reportIncompatibleVariableOverride]
    allowed_domains: list[str] = Field(  # pyright: ignore[reportIncompatibleVariableOverride]
        default_factory=list,
        description="Email domains allowed for this tenant (e.g., ['stockholm.se'])",
        examples=[["stockholm.se", "stockholm.gov.se"]],
    )


class PatchFederationRequest(FederationRequestBase):
    """Request model for partially updating the current tenant federation config."""

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> Self:
        invalid_null_fields = [
            field
            for field in (
                "provider",
                "discovery_endpoint",
                "client_id",
                "client_secret",
            )
            if field in self.model_fields_set and getattr(self, field) is None
        ]
        if invalid_null_fields:
            raise ValueError(
                f"PATCH does not allow null for: {', '.join(invalid_null_fields)}"
            )
        return self


class TenantAdminFederationPatch(BaseModel):
    """What an org admin may change in their tenant's registered IdP.

    Every other field (the authorization server and its endpoints, redirect
    topology, scopes, claim mapping, token auth method) is operator-owned and
    refused as an unknown field.
    """

    model_config = ConfigDict(extra="forbid")

    revision: str = Field(
        ...,
        min_length=1,
        description=(
            "The revision from GET that this change was made against. A save "
            "against an older revision is refused with 409."
        ),
    )
    # Omitted means unchanged; null is refused (reject_null), so the schema
    # does not offer it.
    provider: (
        Annotated[str, Field(min_length=1, max_length=100)] | SkipJsonSchema[None]
    ) = Field(default=None, description="Identity provider label")
    client_id: (
        Annotated[str, Field(min_length=1, max_length=512)] | SkipJsonSchema[None]
    ) = Field(default=None, description="OAuth client ID")
    # No min_length here: a masked display value ("...cret") is refused as
    # such (400 federation_secret_looks_masked) before the length rule.
    client_secret: (
        Annotated[str, Field(max_length=EncryptionService.MAX_CREDENTIAL_LENGTH)]
        | SkipJsonSchema[None]
    ) = Field(
        default=None,
        description=(
            "Replacement OAuth client secret, at least 8 characters. Write-only: "
            "never returned."
        ),
    )
    allowed_domains: list[str] | SkipJsonSchema[None] = Field(
        default=None,
        description="Email domains allowed to sign in (e.g., ['stockholm.se'])",
        examples=[["stockholm.se", "stockholm.gov.se"]],
    )

    @field_validator("provider", "client_id", "client_secret", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("client_secret")
    @classmethod
    def validate_secret_length(cls, value: str | None) -> str | None:
        if value is None or (value and looks_masked(value)):
            return value
        if len(value) < 8:
            raise ValueError("The client secret must be at least 8 characters")
        return value

    @field_validator("allowed_domains")
    @classmethod
    def validate_allowed_domains(cls, v: list[str] | None) -> list[str] | None:
        return _validate_domains(v)

    @model_validator(mode="after")
    def reject_null(self) -> Self:
        nulls = sorted(
            field
            for field in self.model_fields_set
            if field != "revision" and getattr(self, field) is None
        )
        if nulls:
            raise ValueError(f"PATCH does not allow null for: {', '.join(nulls)}")
        return self


class TenantFederationAdminView(BaseModel):
    """A tenant's federation settings as its admin sees them. Never the secret
    or any part of it."""

    configured: bool = Field(
        ..., description="Whether the operator has registered an identity provider"
    )
    provider: Optional[str] = None
    discovery_endpoint: Optional[str] = Field(
        default=None, description="Operator-owned. Shown as text, never as a link."
    )
    issuer: Optional[str] = Field(
        default=None, description="Operator-owned, from discovery"
    )
    client_id: Optional[str] = None
    client_secret_set: bool = False
    client_secret_updated_at: Optional[datetime] = None
    encryption_status: Optional[Literal["encrypted", "plaintext"]] = None
    allowed_domains: list[str] = Field(default_factory=list)
    redirect_uris: list[str] = Field(
        default_factory=list,
        description="Operator-owned callback URIs to register at the IdP",
    )
    redirect_uris_problem: Optional[Literal["unresolvable"]] = Field(
        default=None, description="Set when the redirect URIs cannot be computed"
    )
    scopes: list[str] = Field(default_factory=list)
    token_endpoint_auth_method: Optional[str] = None
    revision: Optional[str] = Field(
        default=None,
        description="Send back with PATCH; changes whenever the settings do",
    )
    configured_at: Optional[datetime] = None


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message}
    )


def _is_registered(config: Mapping[str, Any]) -> bool:
    return all(field in config for field in _REGISTRATION_FIELDS)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _texts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in cast(list[object], value) if isinstance(item, str)]


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def canonical_federation_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """The config as a loaded tenant holds it: TenantInDB's validator normalises
    the redirect path, origin and redirect URIs of rows stored before strict
    validation. A raw row (read under the lock) and a loaded tenant compare
    alike only in this form."""
    return TenantInDB.validate_federation_config(dict(config))


def federation_revision(config: Mapping[str, Any]) -> str | None:
    """sha256 of the canonical stored config; None when there is none.

    Raw rows and loaded tenants hash alike (canonical_federation_config). The
    secret's stored value is left out, so the revision is no guessing oracle
    for a legacy plaintext secret. Replacing the secret stamps
    ``encrypted_at``, which is included, so the revision still moves.
    """
    if not config:
        return None
    canonical = json.dumps(
        {
            key: value
            for key, value in canonical_federation_config(config).items()
            if key != "client_secret"
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def federation_changes(
    old: Mapping[str, Any], new: Mapping[str, Any], *, secret_replaced: bool
) -> dict[str, dict[str, object]]:
    """Each changed setting from what to what; the secret only as replaced."""
    changes: dict[str, dict[str, object]] = {
        key: {"old": old.get(key), "new": new.get(key)}
        for key in sorted((old.keys() | new.keys()) - {"client_secret", "encrypted_at"})
        if old.get(key) != new.get(key)
    }
    if secret_replaced:
        changes["client_secret"] = {"replaced": True}
    return changes


def build_admin_view(
    tenant: TenantInDB, settings: Settings
) -> TenantFederationAdminView:
    config = tenant.federation_config
    if not _is_registered(config):
        return TenantFederationAdminView(configured=False)

    secret = _text(config.get("client_secret")) or ""
    secret_updated_at = _timestamp(config.get("encrypted_at"))
    redirect_problem: Literal["unresolvable"] | None = None
    try:
        # No encryption service: listing the URIs never decrypts the secret.
        redirect_uris = CredentialResolver(
            tenant=tenant, settings=settings
        ).get_valid_redirect_uris()
    except ValueError:
        redirect_uris, redirect_problem = [], "unresolvable"

    return TenantFederationAdminView(
        configured=True,
        provider=_text(config.get("provider")),
        discovery_endpoint=_text(config.get("discovery_endpoint")),
        issuer=_text(config.get("issuer")),
        client_id=_text(config.get("client_id")),
        client_secret_set=bool(secret),
        client_secret_updated_at=secret_updated_at,
        encryption_status=(
            "encrypted" if secret.startswith("enc:fernet:v") else "plaintext"
        ),
        allowed_domains=_texts(config.get("allowed_domains")),
        redirect_uris=redirect_uris,
        redirect_uris_problem=redirect_problem,
        scopes=_texts(config.get("scopes", DEFAULT_FEDERATION_SCOPES)),
        token_endpoint_auth_method=_text(config.get("token_endpoint_auth_method")),
        revision=federation_revision(config),
        configured_at=secret_updated_at or tenant.updated_at,
    )


def _select_token_auth_method(methods: list[str]) -> str:
    normalized = [str(m).lower() for m in methods if m]
    if "client_secret_post" in normalized:
        return "client_secret_post"
    if "client_secret_basic" in normalized:
        return "client_secret_basic"
    return normalized[0] if normalized else "client_secret_post"


async def _fetch_discovery_metadata(
    *,
    tenant: TenantInDB,
    discovery_endpoint: str,
    provider: str,
) -> dict[str, Any]:
    """Fetch and validate discovery metadata for a federation configuration."""
    import aiohttp

    from eneo.main.aiohttp_client import aiohttp_client

    logger.info(
        "Validating OIDC discovery endpoint",
        extra={
            "tenant_id": str(tenant.id),
            "tenant_name": tenant.name,
            "discovery_endpoint": discovery_endpoint,
            "provider": provider,
        },
    )

    try:
        async with aiohttp_client().get(discovery_endpoint) as resp:
            if resp.status != 200:
                try:
                    error_body = await resp.json()
                except Exception:
                    error_body = await resp.text()

                logger.error(
                    f"Discovery endpoint validation failed: HTTP {resp.status}",
                    extra={
                        "tenant_id": str(tenant.id),
                        "tenant_name": tenant.name,
                        "discovery_endpoint": discovery_endpoint,
                        "http_status": resp.status,
                        "error_response": error_body,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to fetch discovery endpoint: HTTP {resp.status}",
                )
            discovery = await resp.json()
    except aiohttp.ClientError as e:
        logger.error(
            "Failed to connect to discovery endpoint",
            extra={
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "discovery_endpoint": discovery_endpoint,
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch discovery endpoint: {str(e)}",
        )

    # resp.json() returns Any; cast to typed dict at the HTTP boundary.
    discovery_doc: dict[str, object] = (
        cast(dict[str, object], discovery) if isinstance(discovery, dict) else {}
    )

    def _str_field(key: str) -> str | None:
        v = discovery_doc.get(key)
        return v if isinstance(v, str) else None

    issuer = _str_field("issuer")
    authorization_endpoint = _str_field("authorization_endpoint")
    token_endpoint = _str_field("token_endpoint")
    userinfo_endpoint = _str_field("userinfo_endpoint")
    jwks_uri = _str_field("jwks_uri")
    methods_raw: object = (
        discovery_doc.get("token_endpoint_auth_methods_supported") or []
    )
    if isinstance(methods_raw, list):
        methods_list: list[object] = cast(list[object], methods_raw)
        token_auth_methods_supported: list[str] = [str(m) for m in methods_list if m]
    elif methods_raw:
        token_auth_methods_supported = [str(methods_raw)]
    else:
        token_auth_methods_supported = []

    if not all([issuer, authorization_endpoint, token_endpoint, jwks_uri]):
        logger.error(
            "Discovery endpoint missing required OIDC fields",
            extra={
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "discovery_endpoint": discovery_endpoint,
                "has_issuer": bool(issuer),
                "has_authorization_endpoint": bool(authorization_endpoint),
                "has_token_endpoint": bool(token_endpoint),
                "has_jwks_uri": bool(jwks_uri),
                "discovery_keys": list(discovery_doc.keys()),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Discovery endpoint missing required fields",
        )

    logger.debug(
        "Discovery endpoint validated successfully",
        extra={
            "tenant_id": str(tenant.id),
            "tenant_name": tenant.name,
            "issuer": issuer,
            "authorization_endpoint": authorization_endpoint,
            "token_endpoint": token_endpoint,
            "jwks_uri": jwks_uri,
            "token_endpoint_auth_methods_supported": token_auth_methods_supported,
        },
    )

    return {
        "issuer": issuer,
        "authorization_endpoint": authorization_endpoint,
        "token_endpoint": token_endpoint,
        "userinfo_endpoint": userinfo_endpoint,
        "jwks_uri": jwks_uri,
        "token_endpoint_auth_method": _select_token_auth_method(
            token_auth_methods_supported
        ),
        "token_endpoint_auth_methods_supported": token_auth_methods_supported,
    }


def _build_full_federation_config(
    request: SetFederationRequest,
    *,
    encrypted_secret: str,
    discovery_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Construct a complete federation config for PUT semantics."""
    federation_config = {
        "provider": request.provider,
        "discovery_endpoint": request.discovery_endpoint,
        "client_id": request.client_id,
        "client_secret": encrypted_secret,
        "scopes": DEFAULT_FEDERATION_SCOPES.copy(),
        "allowed_domains": request.allowed_domains,
        "claims_mapping": DEFAULT_CLAIMS_MAPPING.copy(),
        "encrypted_at": datetime.now(timezone.utc).isoformat(),
    }
    federation_config.update(discovery_metadata)

    if request.canonical_public_origin:
        federation_config["canonical_public_origin"] = request.canonical_public_origin

    if request.redirect_path:
        federation_config["redirect_path"] = request.redirect_path

    if request.additional_redirect_uris is not None:
        federation_config["additional_redirect_uris"] = request.additional_redirect_uris

    return federation_config


def _merge_federation_config(
    existing_config: dict[str, Any],
    updates: dict[str, Any],
    *,
    encrypted_secret: str | None,
    discovery_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge PATCH updates into an existing federation config."""
    merged = existing_config.copy()

    for field in ("provider", "client_id", "discovery_endpoint"):
        if field in updates:
            merged[field] = updates[field]

    if "allowed_domains" in updates:
        merged["allowed_domains"] = updates["allowed_domains"] or []

    for field in (
        "canonical_public_origin",
        "redirect_path",
        "additional_redirect_uris",
    ):
        if field not in updates:
            continue
        value = updates[field]
        if value is None:
            merged.pop(field, None)
        else:
            merged[field] = value

    if encrypted_secret is not None:
        merged["client_secret"] = encrypted_secret
        merged["encrypted_at"] = datetime.now(timezone.utc).isoformat()

    if discovery_metadata is not None:
        merged.update(discovery_metadata)

    merged.setdefault("scopes", DEFAULT_FEDERATION_SCOPES.copy())
    merged.setdefault("claims_mapping", DEFAULT_CLAIMS_MAPPING.copy())
    merged.setdefault("allowed_domains", [])

    return merged


def _no_config() -> HTTPException:
    # A new exception per request: re-raising one instance would keep growing
    # its traceback, holding every earlier request's frames.
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No federation config found for tenant",
    )


def _require_updates(updates: Mapping[str, Any]) -> None:
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field must be provided for patch",
        )


class TenantFederationService:
    def __init__(
        self,
        tenant_repo: TenantRepository,
        encryption_service: EncryptionService,
        audit_service: "AuditService",
    ):
        super().__init__()
        self.tenant_repo = tenant_repo
        self.encryption_service = encryption_service
        self.audit_service = audit_service

    # Tenant admin door

    def admin_view(self, tenant: TenantInDB) -> TenantFederationAdminView:
        return build_admin_view(tenant, get_settings())

    async def edit_as_admin(
        self, user: "UserInDB", patch: TenantAdminFederationPatch
    ) -> TenantFederationAdminView:
        """Apply an org admin's edit to their own tenant's registered IdP.

        Never fetches anything: the admin cannot move the authorization server,
        so no network call happens while the tenant row is locked.
        """
        tenant = user.tenant
        updates = patch.model_dump(exclude_unset=True, exclude={"revision"})
        _require_updates(updates)
        if patch.client_secret is not None and looks_masked(patch.client_secret):
            raise _error(
                status.HTTP_400_BAD_REQUEST,
                "federation_secret_looks_masked",
                "The client secret looks like a masked display value; enter the actual secret.",
            )
        if patch.client_secret is not None and not self.encryption_service.is_active():
            raise _error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "federation_encryption_unavailable",
                "Encryption is not configured, so a client secret cannot be stored.",
            )

        current = await self._lock(tenant)
        if not _is_registered(current):
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "federation_not_configured",
                "No identity provider is registered for this organisation.",
            )
        if patch.revision != federation_revision(current):
            raise _error(
                status.HTTP_409_CONFLICT,
                "federation_config_revision_conflict",
                "The sign-in settings changed after you loaded them. Reload and try again.",
            )

        merged = _merge_federation_config(
            current,
            updates,
            encrypted_secret=self._encrypt(patch.client_secret),
            discovery_metadata=None,
        )
        await self._save(
            tenant,
            current,
            merged,
            user=user,
            secret_replaced=patch.client_secret is not None,
            description=f"{user.username} changed the sign-in settings of {tenant.name}",
        )
        logger.info(
            f"Federation config edited by an admin of tenant {tenant.name}",
            extra={
                "tenant_id": str(tenant.id),
                "user_id": str(user.id),
                "updated_fields": sorted(updates.keys()),
            },
        )
        # The same canonical form a following GET loads, so the views agree.
        return build_admin_view(
            tenant.model_copy(
                update={"federation_config": canonical_federation_config(merged)}
            ),
            get_settings(),
        )

    # Operator door

    async def replace(
        self, tenant: TenantInDB, request: SetFederationRequest
    ) -> dict[str, Any]:
        """Register or replace the tenant's IdP (super API key)."""
        discovery_metadata = await _fetch_discovery_metadata(
            tenant=tenant,
            discovery_endpoint=request.discovery_endpoint,
            provider=request.provider,
        )
        federation_config = _build_full_federation_config(
            request,
            encrypted_secret=self.encryption_service.encrypt(request.client_secret),
            discovery_metadata=discovery_metadata,
        )

        current = await self._lock(tenant)
        await self._save(
            tenant,
            current,
            federation_config,
            user=None,
            secret_replaced=True,
            description=f"Sysadmin replaced federation config for tenant {tenant.name}",
        )
        logger.info(
            f"Federation config set for tenant {tenant.name} (provider: {request.provider})",
            extra={
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "provider": request.provider,
                "issuer": federation_config.get("issuer"),
                "client_id": request.client_id,
                "allowed_domains": request.allowed_domains,
                "endpoints_configured": {
                    "authorization": federation_config.get("authorization_endpoint"),
                    "token": federation_config.get("token_endpoint"),
                    "userinfo": federation_config.get("userinfo_endpoint"),
                    "jwks": federation_config.get("jwks_uri"),
                },
            },
        )
        return federation_config

    async def patch(
        self, tenant: TenantInDB, request: PatchFederationRequest
    ) -> dict[str, Any]:
        """Change some of the tenant's settings (super API key).

        Discovery is fetched before the tenant row is locked.
        """
        if not tenant.federation_config:
            raise _no_config()
        updates = request.model_dump(exclude_unset=True)
        _require_updates(updates)

        discovery_metadata = None
        if "discovery_endpoint" in updates:
            discovery_metadata = await _fetch_discovery_metadata(
                tenant=tenant,
                discovery_endpoint=updates["discovery_endpoint"],
                provider=updates.get("provider")
                or tenant.federation_config.get("provider")
                or "unknown",
            )
        encrypted_secret = (
            self.encryption_service.encrypt(request.client_secret)
            if "client_secret" in updates and request.client_secret is not None
            else None
        )

        current = await self._lock(tenant)
        if not current:
            raise _no_config()
        federation_config = _merge_federation_config(
            current,
            updates,
            encrypted_secret=encrypted_secret,
            discovery_metadata=discovery_metadata,
        )
        await self._save(
            tenant,
            current,
            federation_config,
            user=None,
            secret_replaced=encrypted_secret is not None,
            description=f"Sysadmin patched federation config for tenant {tenant.name}",
        )
        logger.info(
            f"Federation config patched for tenant {tenant.name} (provider: {federation_config.get('provider')})",
            extra={
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "provider": federation_config.get("provider"),
                "issuer": federation_config.get("issuer"),
                "client_id": federation_config.get("client_id"),
                "allowed_domains": federation_config.get("allowed_domains", []),
                "updated_fields": sorted(updates.keys()),
            },
        )
        return federation_config

    async def delete(self, tenant: TenantInDB) -> None:
        """Remove the tenant's IdP (super API key)."""
        current = await self._lock(tenant)
        await self.tenant_repo.delete_federation_config(tenant_id=tenant.id)
        await self._audit(
            tenant,
            current,
            {},
            user=None,
            secret_replaced=False,
            description=f"Sysadmin deleted federation config for tenant {tenant.name}",
        )
        logger.info(f"Federation config deleted for tenant {tenant.name}")

    async def test_connection(self, tenant: TenantInDB) -> dict[str, Any]:
        """Fetch the stored discovery document (super API key)."""
        if not tenant.federation_config:
            raise _no_config()

        discovery_endpoint = tenant.federation_config.get("discovery_endpoint")
        if not discovery_endpoint:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No discovery endpoint in federation config",
            )

        import aiohttp

        from eneo.main.aiohttp_client import aiohttp_client

        logger.info(
            f"Testing federation config for tenant {tenant.name}",
            extra={
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "discovery_endpoint": discovery_endpoint,
            },
        )

        try:
            async with aiohttp_client().get(discovery_endpoint) as resp:
                if resp.status != 200:
                    try:
                        error_body = await resp.json()
                    except Exception:
                        error_body = await resp.text()

                    logger.error(
                        f"Test failed: Discovery endpoint returned HTTP {resp.status}",
                        extra={
                            "tenant_id": str(tenant.id),
                            "tenant_name": tenant.name,
                            "discovery_endpoint": discovery_endpoint,
                            "http_status": resp.status,
                            "error_response": error_body,
                        },
                    )
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Discovery endpoint returned HTTP {resp.status}",
                    )
                discovery = await resp.json()

                required = [
                    "issuer",
                    "authorization_endpoint",
                    "token_endpoint",
                    "jwks_uri",
                ]
                missing = [f for f in required if f not in discovery]
                if missing:
                    logger.error(
                        "Test failed: Discovery endpoint missing required fields",
                        extra={
                            "tenant_id": str(tenant.id),
                            "tenant_name": tenant.name,
                            "discovery_endpoint": discovery_endpoint,
                            "missing_fields": missing,
                            "discovery_keys": list(discovery.keys()),
                        },
                    )
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Discovery endpoint missing required fields: {missing}",
                    )
        except aiohttp.ClientError as e:
            logger.error(
                "Test failed: Could not connect to discovery endpoint",
                extra={
                    "tenant_id": str(tenant.id),
                    "tenant_name": tenant.name,
                    "discovery_endpoint": discovery_endpoint,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to connect to discovery endpoint: {str(e)}",
            )

        logger.info(
            f"Federation test successful for tenant {tenant.name}",
            extra={
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "issuer": discovery["issuer"],
                "endpoints_validated": {
                    "authorization": discovery.get("authorization_endpoint"),
                    "token": discovery.get("token_endpoint"),
                    "jwks": discovery.get("jwks_uri"),
                },
            },
        )

        return {
            "success": True,
            "message": "Federation config is valid and IdP is reachable",
            "issuer": discovery["issuer"],
        }

    # Shared

    def _encrypt(self, secret: str | None) -> str | None:
        return None if secret is None else self.encryption_service.encrypt(secret)

    async def _lock(self, tenant: TenantInDB) -> dict[str, Any]:
        current = await self.tenant_repo.lock_federation_config(tenant.id)
        return current or {}

    async def _save(
        self,
        tenant: TenantInDB,
        old: dict[str, Any],
        new: dict[str, Any],
        *,
        user: Optional["UserInDB"],
        secret_replaced: bool,
        description: str,
    ) -> None:
        await self.tenant_repo.update_federation_config(
            tenant_id=tenant.id, federation_config=new
        )
        await self._audit(
            tenant,
            old,
            new,
            user=user,
            secret_replaced=secret_replaced,
            description=description,
        )

    async def _audit(
        self,
        tenant: TenantInDB,
        old: dict[str, Any],
        new: dict[str, Any],
        *,
        user: Optional["UserInDB"],
        secret_replaced: bool,
        description: str,
    ) -> None:
        """FEDERATION_UPDATED in the caller's transaction: if this write fails,
        the settings change rolls back with it."""
        target: dict[str, Any] = {
            "tenant_id": str(tenant.id),
            "tenant_name": tenant.name,
            "provider": new.get("provider"),
            "issuer": new.get("issuer"),
            "client_id": new.get("client_id"),
            "allowed_domains": new.get("allowed_domains", []),
        }
        if not new:
            target["action"] = "deleted"
        metadata: dict[str, Any] = {
            "actor": _OPERATOR_ACTOR if user is None else AuditMetadata.actor(user),
            "target": target,
            "changes": federation_changes(old, new, secret_replaced=secret_replaced),
            "via": "super_api_key" if user is None else "admin",
        }
        await self.audit_service.log(
            tenant_id=tenant.id,
            user=user,
            actor_type=ActorType.SYSTEM if user is None else ActorType.USER,
            action=ActionType.FEDERATION_UPDATED,
            entity_type=EntityType.FEDERATION_CONFIG,
            entity_id=tenant.id,
            description=description,
            metadata=metadata,
        )
