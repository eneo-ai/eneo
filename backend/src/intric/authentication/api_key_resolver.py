from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from intric.authentication.api_key_repo import ApiKeysRepository
from intric.authentication.api_key_v2_repo import ApiKeysV2Repository
from intric.authentication.auth_models import (
    ApiKeyInDB,
    ApiKeyHashVersion,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
    PERMISSION_LEVEL_ORDER,
    ResourcePermissions,
)
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.users_table import Users
from intric.main.config import get_settings

if TYPE_CHECKING:
    from intric.audit.application.audit_service import AuditService


class ResourceDenialContext(TypedDict):
    resource_type: str
    required_level: str
    granted_level: str


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


def check_resource_permission(
    key: ApiKeyV2InDB,
    resource_type: str,
    required: str,
) -> None:
    """Centralized fine-grained resource permission check.

    Fail-closed: missing/unrecognized resource keys are treated as "none" (deny).
    If resource_permissions is None, falls back to the key's basic permission
    level as a ceiling (e.g. a read key cannot perform write operations).
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
            granted_value.value if hasattr(granted_value, "value") else str(granted_value),
            0,
        )

    required_level = PERMISSION_LEVEL_ORDER.get(required, 0)
    if granted_level < required_level:
        granted_str = (
            granted_value.value if hasattr(granted_value, "value") else str(granted_value)
        ) if granted_value is not None else "none"
        raise ApiKeyValidationError(
            status_code=403,
            code="insufficient_resource_permission",
            message=f"API key does not have '{resource_type}' {required} permission.",
            context=ResourceDenialContext(
                resource_type=resource_type,
                required_level=required,
                granted_level=granted_str,
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
        legacy_repo: ApiKeysRepository,
        audit_service: "AuditService | None",
    ):
        self.api_key_repo = api_key_repo
        self.legacy_repo = legacy_repo
        self.audit_service = audit_service
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

        resolved = await self._resolve_from_legacy(
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

        return ResolvedApiKey(key=record, plain_key=plain_key, prefix=prefix)

    async def _resolve_from_legacy(
        self,
        plain_key: str,
        prefix: str,
        expected_tenant_id: UUID | None = None,
    ) -> ResolvedApiKey | None:
        sha_hash = self._hash_sha256(plain_key)
        legacy_record = await self.legacy_repo.get(sha_hash)
        if legacy_record is None:
            return None

        if expected_tenant_id is not None:
            if legacy_record.user_id is not None:
                tenant_id, _ = await self._get_user_tenant(legacy_record.user_id)
            elif legacy_record.assistant_id is not None:
                tenant_id, _ = await self._get_assistant_context(
                    legacy_record.assistant_id
                )
            else:
                return None
            if tenant_id != expected_tenant_id:
                return None

        migrated = await self._migrate_legacy_key(plain_key, legacy_record, prefix)
        return ResolvedApiKey(key=migrated, plain_key=plain_key, prefix=prefix)

    async def _migrate_legacy_key(
        self, plain_key: str, legacy_record: ApiKeyInDB, prefix: str
    ) -> ApiKeyV2InDB:
        if legacy_record.user_id is not None:
            tenant_id, owner_user_id = await self._get_user_tenant(
                legacy_record.user_id
            )
            try:
                migrated = await self.api_key_repo.create(
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    created_by_user_id=owner_user_id,
                    scope_type=ApiKeyScopeType.TENANT.value,
                    scope_id=None,
                    permission=ApiKeyPermission.ADMIN.value,
                    key_type=ApiKeyType.SK.value,
                    key_hash=self._hash_sha256(plain_key),
                    hash_version=ApiKeyHashVersion.SHA256.value,
                    key_prefix=prefix,
                    key_suffix=plain_key[-4:],
                    name="Legacy API key",
                    description=None,
                    state=ApiKeyState.ACTIVE.value,
                )
            except IntegrityError:
                migrated = await self._fetch_concurrent_migration(plain_key, prefix, tenant_id)
            await self._log_legacy_migration(
                migrated=migrated,
                legacy_record=legacy_record,
                prefix=prefix,
            )
            return migrated

        if legacy_record.assistant_id is not None:
            tenant_id, owner_user_id = await self._get_assistant_context(
                legacy_record.assistant_id
            )
            try:
                migrated = await self.api_key_repo.create(
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    created_by_user_id=owner_user_id,
                    scope_type=ApiKeyScopeType.ASSISTANT.value,
                    scope_id=legacy_record.assistant_id,
                    permission=ApiKeyPermission.READ.value,
                    key_type=ApiKeyType.SK.value,
                    key_hash=self._hash_sha256(plain_key),
                    hash_version=ApiKeyHashVersion.SHA256.value,
                    key_prefix=prefix,
                    key_suffix=plain_key[-4:],
                    name="Legacy Assistant API key",
                    description=None,
                    state=ApiKeyState.ACTIVE.value,
                )
            except IntegrityError:
                migrated = await self._fetch_concurrent_migration(plain_key, prefix, tenant_id)
            await self._log_legacy_migration(
                migrated=migrated,
                legacy_record=legacy_record,
                prefix=prefix,
            )
            return migrated

        raise ApiKeyValidationError(
            status_code=401,
            code="invalid_api_key",
            message="Legacy API key is invalid.",
        )

    async def _fetch_concurrent_migration(
        self, plain_key: str, prefix: str, tenant_id: UUID
    ) -> ApiKeyV2InDB:
        """Re-fetch a v2 record created by a concurrent migration."""
        migrated = await self.api_key_repo.get_by_hash(
            key_hash=self._hash_sha256(plain_key),
            hash_version=ApiKeyHashVersion.SHA256.value,
            key_prefix=prefix,
            tenant_id=tenant_id,
        )
        if migrated is None:
            # Auto-upgrade may have already converted to HMAC
            migrated = await self.api_key_repo.get_by_hash(
                key_hash=self._hash_hmac(plain_key),
                hash_version=ApiKeyHashVersion.HMAC_SHA256.value,
                key_prefix=prefix,
                tenant_id=tenant_id,
            )
        if migrated is None:
            raise ApiKeyValidationError(
                status_code=500,
                code="migration_error",
                message="Legacy key migration failed.",
            )
        return migrated

    async def _get_user_tenant(self, user_id: UUID) -> tuple[UUID, UUID]:
        stmt = sa.select(Users.tenant_id, Users.id).where(Users.id == user_id).limit(1)
        record = await self.legacy_repo.session.execute(stmt)
        row = record.first()
        if row is None:
            raise ApiKeyValidationError(
                status_code=401,
                code="invalid_api_key",
                message="Legacy API key owner not found.",
            )
        return row.tenant_id, row.id

    async def _get_assistant_context(self, assistant_id: UUID) -> tuple[UUID, UUID]:
        stmt = (
            sa.select(Assistants.user_id, Assistants.space_id, Users.tenant_id)
            .join(Users, Users.id == Assistants.user_id)
            .where(Assistants.id == assistant_id)
            .limit(1)
        )
        record = await self.legacy_repo.session.execute(stmt)
        row = record.first()
        if row is None:
            raise ApiKeyValidationError(
                status_code=401,
                code="invalid_api_key",
                message="Legacy assistant API key owner not found.",
            )
        return row.tenant_id, row.user_id

    def _extract_prefix(self, plain_key: str) -> str | None:
        settings = get_settings()
        if (settings.dev or settings.testing) and plain_key.startswith("test"):
            if "_" in plain_key:
                return f"{plain_key.split('_', 1)[0]}_"
        if plain_key.startswith(ApiKeyType.PK.value):
            return ApiKeyType.PK.value
        if plain_key.startswith(ApiKeyType.SK.value):
            return ApiKeyType.SK.value
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

    async def _log_legacy_migration(
        self,
        *,
        migrated: ApiKeyV2InDB,
        legacy_record: ApiKeyInDB,
        prefix: str,
    ) -> None:
        if self.audit_service is None:
            return

        await self.audit_service.log_async(
            tenant_id=migrated.tenant_id,
            actor_id=None,
            actor_type=ActorType.SYSTEM,
            action=ActionType.API_KEY_CREATED,
            entity_type=EntityType.API_KEY,
            entity_id=migrated.id,
            description="Migrated legacy API key to v2",
            metadata=AuditMetadata.system_action(
                description="Legacy API key migrated",
                target=migrated,
                extra={
                    "legacy_user_id": str(legacy_record.user_id)
                    if legacy_record.user_id
                    else None,
                    "legacy_assistant_id": str(legacy_record.assistant_id)
                    if legacy_record.assistant_id
                    else None,
                    "legacy_prefix": prefix,
                    "hash_version": migrated.hash_version,
                },
            ),
        )
