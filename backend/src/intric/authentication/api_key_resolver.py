from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa

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


class ApiKeyValidationError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


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
            migrated = await self.api_key_repo.create(
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                created_by_user_id=owner_user_id,
                scope_type=ApiKeyScopeType.TENANT.value,
                scope_id=None,
                permission=ApiKeyPermission.WRITE.value,
                key_type=ApiKeyType.SK.value,
                key_hash=self._hash_sha256(plain_key),
                hash_version=ApiKeyHashVersion.SHA256.value,
                key_prefix=prefix,
                key_suffix=plain_key[-4:],
                name="Legacy API key",
                description=None,
                state=ApiKeyState.ACTIVE.value,
            )
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
            migrated = await self.api_key_repo.create(
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                created_by_user_id=owner_user_id,
                scope_type=ApiKeyScopeType.ASSISTANT.value,
                scope_id=legacy_record.assistant_id,
                permission=ApiKeyPermission.WRITE.value,
                key_type=ApiKeyType.SK.value,
                key_hash=self._hash_sha256(plain_key),
                hash_version=ApiKeyHashVersion.SHA256.value,
                key_prefix=prefix,
                key_suffix=plain_key[-4:],
                name="Legacy Assistant API key",
                description=None,
                state=ApiKeyState.ACTIVE.value,
            )
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
