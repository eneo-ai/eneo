from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from uuid import UUID

from typing_extensions import TypedDict

from eneo.authentication.api_key_v2_repo import ApiKeysV2Repository
from eneo.authentication.auth_models import (
    PERMISSION_LEVEL_ORDER,
    ApiKeyHashVersion,
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyType,
    ApiKeyV2InDB,
    ResourcePermissionLevel,
    ResourcePermissions,
    ServicePrincipalState,
)
from eneo.main.config import get_settings


class ResourceDenialContext(TypedDict, total=False):
    resource_type: str
    required_level: str
    granted_level: str
    scope_type: str
    action: str
    auth_layer: str
    required_capability: str
    ownership: str


class ApiKeyValidationError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
        context: ResourceDenialContext | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers
        self.context = context


def resolve_effective_resource_permission(
    key: ApiKeyV2InDB,
    resource_type: str,
) -> ApiKeyPermission:
    if not get_settings().api_key_enforce_resource_permissions:
        return ApiKeyPermission(key.permission)

    if key.resource_permissions is None:
        return ApiKeyPermission(key.permission)

    try:
        resource_permissions = ResourcePermissions.model_validate(
            key.resource_permissions
        )
    except Exception:
        raise ApiKeyValidationError(
            status_code=403,
            code="insufficient_resource_permission",
            message="API key has malformed resource permissions.",
        )

    granted_value = getattr(resource_permissions, resource_type, None)
    if granted_value in (None, ResourcePermissionLevel.NONE):
        raise ApiKeyValidationError(
            status_code=403,
            code="insufficient_resource_permission",
            message=f"API key does not have '{resource_type}' permission.",
            context=ResourceDenialContext(
                resource_type=resource_type,
                required_level=ApiKeyPermission.READ.value,
                granted_level=(
                    granted_value.value
                    if isinstance(granted_value, ResourcePermissionLevel)
                    else "none"
                ),
                auth_layer="api_key_resource",
                action="resource_permission_check",
            ),
        )

    return ApiKeyPermission(granted_value.value)


def check_resource_permission(
    key: ApiKeyV2InDB,
    resource_type: str,
    required: str,
) -> None:
    """Centralized fine-grained resource permission check.

    Fail-closed: missing/unrecognized resource keys are treated as "none" (deny).
    If resource_permissions is None, falls back to the key's basic permission
    level as a ceiling (e.g. a read key cannot perform write operations).
    If resource_permissions is set, absent or "none" resource fields fail closed.
    """
    if not get_settings().api_key_enforce_resource_permissions:
        return

    if key.resource_permissions is None:
        # No fine-grained permissions (simple mode) — use basic permission as ceiling
        key_level = PERMISSION_LEVEL_ORDER.get(key.permission, 0)
        required_level = PERMISSION_LEVEL_ORDER.get(required, 0)
        if key_level < required_level:
            raise ApiKeyValidationError(
                status_code=403,
                code="insufficient_resource_permission",
                message=(
                    f"API key does not have sufficient permission for "
                    f"'{resource_type}' (requires '{required}')."
                ),
                context=ResourceDenialContext(
                    resource_type=resource_type,
                    required_level=required,
                    granted_level=key.permission,
                    auth_layer="api_key_resource",
                    action="resource_permission_check",
                ),
            )
        return

    try:
        rp = ResourcePermissions.model_validate(key.resource_permissions)
    except Exception:
        # Malformed data — fail closed
        raise ApiKeyValidationError(
            status_code=403,
            code="insufficient_resource_permission",
            message="API key has malformed resource permissions.",
        )

    granted_value = getattr(rp, resource_type, None)
    if granted_value is None:
        # Unknown resource type — fail closed
        granted_level = 0
    else:
        granted_level = PERMISSION_LEVEL_ORDER.get(
            granted_value.value
            if hasattr(granted_value, "value")
            else str(granted_value),
            0,
        )

    required_level = PERMISSION_LEVEL_ORDER.get(required, 0)
    if granted_level < required_level:
        granted_str = (
            (
                granted_value.value
                if hasattr(granted_value, "value")
                else str(granted_value)
            )
            if granted_value is not None
            else "none"
        )
        raise ApiKeyValidationError(
            status_code=403,
            code="insufficient_resource_permission",
            message=f"API key does not have '{resource_type}' {required} permission.",
            context=ResourceDenialContext(
                resource_type=resource_type,
                required_level=required,
                granted_level=granted_str,
                auth_layer="api_key_resource",
                action="resource_permission_check",
            ),
        )


@dataclass(frozen=True)
class ResolvedApiKey:
    key: ApiKeyV2InDB
    plain_key: str
    prefix: str


class ApiKeyAuthResolver:
    def __init__(
        self,
        api_key_repo: ApiKeysV2Repository,
    ):
        super().__init__()
        self.api_key_repo = api_key_repo
        settings = get_settings()
        self.hash_secret = settings.api_key_hash_secret or settings.jwt_secret

    async def resolve(
        self, plain_key: str, expected_tenant_id: UUID | None = None
    ) -> ResolvedApiKey:
        if not plain_key:
            raise ApiKeyValidationError(
                status_code=401,
                code="invalid_api_key",
                message="API key missing.",
            )

        prefix = self._extract_prefix(plain_key)
        if prefix is None:
            raise ApiKeyValidationError(
                status_code=401,
                code="invalid_api_key",
                message="API key format is invalid.",
            )

        resolved = await self._resolve_from_v2(
            plain_key, prefix, expected_tenant_id=expected_tenant_id
        )
        if resolved is not None:
            return resolved

        raise ApiKeyValidationError(
            status_code=401,
            code="invalid_api_key",
            message="API key is invalid.",
        )

    async def _resolve_from_v2(
        self,
        plain_key: str,
        prefix: str,
        expected_tenant_id: UUID | None = None,
    ) -> ResolvedApiKey | None:
        hmac_hash = self._hash_hmac(plain_key)
        record = await self.api_key_repo.get_by_hash(
            key_hash=hmac_hash,
            hash_version=ApiKeyHashVersion.HMAC_SHA256.value,
            key_prefix=prefix,
            tenant_id=expected_tenant_id,
        )
        if record is None:
            sha_hash = self._hash_sha256(plain_key)
            record = await self.api_key_repo.get_by_hash(
                key_hash=sha_hash,
                hash_version=ApiKeyHashVersion.SHA256.value,
                key_prefix=prefix,
                tenant_id=expected_tenant_id,
            )
            if record is None:
                return None

            if record.hash_version == ApiKeyHashVersion.SHA256.value:
                await self.api_key_repo.update(
                    key_id=record.id,
                    tenant_id=record.tenant_id,
                    key_hash=hmac_hash,
                    hash_version=ApiKeyHashVersion.HMAC_SHA256.value,
                )
                record = await self.api_key_repo.get(
                    key_id=record.id, tenant_id=record.tenant_id
                )

        if record is None:
            return None

        if expected_tenant_id is not None and record.tenant_id != expected_tenant_id:
            return None

        if record.key_prefix != prefix:
            return None

        if prefix in (ApiKeyType.PK.value, ApiKeyType.SK.value):
            if (
                ApiKeyType(record.key_type) == ApiKeyType.PK
                and prefix != ApiKeyType.PK.value
            ):
                return None
            if (
                ApiKeyType(record.key_type) == ApiKeyType.SK
                and prefix != ApiKeyType.SK.value
            ):
                return None

        if record.ownership == ApiKeyOwnership.SERVICE:
            if record.service_principal_id is None:
                raise ApiKeyValidationError(
                    status_code=401,
                    code="invalid_api_key",
                    message="API key service principal is invalid.",
                )
            service_principal = await self.api_key_repo.get_service_principal(
                service_principal_id=record.service_principal_id,
                tenant_id=record.tenant_id,
            )
            if service_principal is None:
                raise ApiKeyValidationError(
                    status_code=401,
                    code="invalid_api_key",
                    message="API key service principal is invalid.",
                )
            if service_principal.state != ServicePrincipalState.ACTIVE:
                raise ApiKeyValidationError(
                    status_code=403,
                    code="service_principal_disabled",
                    message="Service principal is disabled.",
                )

        return ResolvedApiKey(key=record, plain_key=plain_key, prefix=prefix)

    def _extract_prefix(self, plain_key: str) -> str | None:
        settings = get_settings()
        if (settings.dev or settings.testing) and plain_key.startswith("test"):
            if "_" in plain_key:
                return f"{plain_key.split('_', 1)[0]}_"
        if plain_key.startswith(ApiKeyType.PK.value):
            return ApiKeyType.PK.value
        if plain_key.startswith(ApiKeyType.SK.value):
            return ApiKeyType.SK.value
        # v1 keys migrated into api_keys_v2 keep their original inp_/ina_
        # prefixes forever; dropping these would break every migrated key.
        if plain_key.startswith("inp_"):
            return "inp_"
        if plain_key.startswith("ina_"):
            return "ina_"
        return None

    def _hash_hmac(self, plain_key: str) -> str:
        return hmac.new(
            self.hash_secret.encode("utf-8"),
            plain_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _hash_sha256(self, plain_key: str) -> str:
        return hashlib.sha256(plain_key.encode("utf-8")).hexdigest()
