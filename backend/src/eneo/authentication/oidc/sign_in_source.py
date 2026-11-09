"""The provider config sign-in uses, chosen in one place.

FEDERATION_ENABLED selects the source: the tenant's stored config, or in env
mode the OIDC_* settings. Initiate and callback resolve it once per request
and read the config and its redirect URIs from that one resolution.
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

from eneo.authentication.oidc.profile import DEFAULT_SCOPES
from eneo.main.config import (
    Settings,
    has_env_oidc_client,
    validate_redirect_path,
    validate_redirect_uri,
)
from eneo.main.logging import get_logger
from eneo.tenants.tenant import TenantInDB

if TYPE_CHECKING:
    from eneo.settings.encryption_service import EncryptionService

logger = get_logger(__name__)

DEFAULT_REDIRECT_PATH = "/login/callback"


def selected_config(settings: Settings, tenant: TenantInDB) -> Mapping[str, object]:
    """What FEDERATION_ENABLED selects, with the secret as stored."""
    if not settings.federation_enabled:
        return {
            "provider": "default",
            "discovery_endpoint": settings.oidc_discovery_endpoint,
            "client_id": settings.oidc_client_id,
            "client_secret": settings.oidc_client_secret,
            "tenant_id": settings.oidc_tenant_id,
            "allowed_domains": settings.oidc_allowed_domains,
            "scopes": list(DEFAULT_SCOPES),
        }
    return tenant.federation_config or {}


def sign_in_available(settings: Settings, tenant: TenantInDB) -> bool:
    """Whether the selected config names a discovery URL, a client ID and a
    secret: what the status, the tenant list and sign-in all require."""
    if not settings.federation_enabled:
        return has_env_oidc_client(settings)
    config = selected_config(settings, tenant)
    return all(
        isinstance(value := config.get(key), str) and value
        for key in ("discovery_endpoint", "client_id", "client_secret")
    )


def sign_in_config(
    settings: Settings, tenant: TenantInDB, encryption: "EncryptionService"
) -> dict[str, object]:
    """The selected config, with its secret decrypted.

    Raises ValueError when the selected source names no provider, or when
    the stored secret is not encrypted or cannot be decrypted.
    """
    config = dict(selected_config(settings, tenant))
    if not settings.federation_enabled:
        if not sign_in_available(settings, tenant):
            raise ValueError(
                "No identity provider configured. "
                "federation_enabled is false, so only global OIDC_* environment variables are used. "
                "Please set OIDC_DISCOVERY_ENDPOINT, OIDC_CLIENT_ID, and OIDC_CLIENT_SECRET in your .env file."
            )
        logger.info(
            "Federation config resolved from global OIDC environment variables (single-tenant mode)",
            extra={
                "credential_source": "global",
                "mode": "single-tenant",
                "federation_enabled": False,
                "metric_name": "federation.global.resolved",
                "metric_value": 1,
            },
        )
        return config

    if not sign_in_available(settings, tenant):
        raise ValueError(
            f"No identity provider configured for tenant '{tenant.name}'. "
            f"federation_enabled is true - each tenant must configure their own IdP in the database. "
            f"Please configure federation via:\n"
            f"PUT /api/v1/sysadmin/tenants/{tenant.id}/federation"
        )
    log_context = {
        "tenant_id": str(tenant.id),
        "tenant_name": tenant.name,
        "provider": config.get("provider"),
    }
    secret = cast(str, config["client_secret"])
    if encryption.is_active():
        if not encryption.is_encrypted(secret):
            logger.error(
                "Federation client_secret missing encryption envelope",
                extra=log_context,
            )
            raise ValueError(
                f"Federation client_secret for tenant '{tenant.name}' is not encrypted. "
                "Delete the credential and upload a new value after confirming ENCRYPTION_KEY is configured."
            )
        try:
            config["client_secret"] = encryption.decrypt(secret)
        except ValueError as exc:
            logger.error(
                "Failed to decrypt federation client_secret",
                extra={**log_context, "error": str(exc)},
            )
            raise ValueError(
                "Failed to decrypt federation config. Encryption key may be incorrect or data corrupted. "
                "Rotate the tenant credential by removing and re-adding it with the active encryption key."
            ) from exc
    logger.info(
        f"Federation config resolved for tenant {tenant.name} (provider: {config.get('provider')})",
        extra={
            **log_context,
            "credential_source": "tenant",
            "federation_enabled": True,
            "metric_name": "federation.tenant.resolved",
            "metric_value": 1,
        },
    )
    return config


def redirect_uris(
    config: Mapping[str, object], settings: Settings
) -> tuple[str, tuple[str, ...]]:
    """The canonical redirect URI, and every URI a sign-in may use with it
    first, from this config alone.

    The origin is the config's canonical_public_origin, else PUBLIC_ORIGIN.
    Raises ValueError when neither is set or the URI is not valid.
    """
    origin = config.get("canonical_public_origin")
    if not isinstance(origin, str) or not origin.strip():
        origin = settings.public_origin or ""
    origin = origin.strip()
    if not origin:
        raise ValueError(
            "No public origin configured: set canonical_public_origin or PUBLIC_ORIGIN"
        )
    path = config.get("redirect_path")
    redirect_path = validate_redirect_path(
        path if isinstance(path, str) else DEFAULT_REDIRECT_PATH
    )
    if redirect_path is None:
        raise ValueError("redirect_path must be configured for OIDC redirects")
    canonical = validate_redirect_uri(f"{origin.rstrip('/')}{redirect_path}")
    if canonical is None:
        raise ValueError("redirect_uri validation returned no value")

    accepted = [canonical]
    extra = config.get("additional_redirect_uris")
    for uri in cast(list[object], extra) if isinstance(extra, list) else []:
        if isinstance(uri, str) and uri not in accepted:
            accepted.append(uri)
    return canonical, tuple(accepted)
