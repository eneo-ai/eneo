from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from intric.authentication.api_key_policy import ApiKeyPolicyService
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.authentication.api_key_v2_repo import ApiKeysV2Repository
from intric.authentication.auth_models import (
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyUpdateRequest,
    ApiKeyHashVersion,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyStateChangeRequest,
    ApiKeyType,
    ApiKeyV2,
    ApiKeyV2InDB,
    compute_effective_state,
)
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.main.config import get_settings

if TYPE_CHECKING:
    from intric.audit.application.audit_service import AuditService
    from intric.users.user import UserInDB


class ApiKeyLifecycleService:
    def __init__(
        self,
        api_key_repo: ApiKeysV2Repository,
        policy_service: ApiKeyPolicyService,
        audit_service: "AuditService | None",
        user: "UserInDB | None" = None,
    ):
        self.api_key_repo = api_key_repo
        self.policy_service = policy_service
        self.audit_service = audit_service
        self.user = user
        self.settings = get_settings()

    async def create_key(self, request: ApiKeyCreateRequest) -> ApiKeyCreatedResponse:
        user = self._require_user()
        await self.policy_service.validate_create_request(request=request)

        secret = self._generate_secret(request.key_type.value)
        key_hash = self._hash_hmac(secret)

        record = await self.api_key_repo.create(
            tenant_id=user.tenant_id,
            owner_user_id=user.id,
            created_by_user_id=user.id,
            scope_type=request.scope_type.value,
            scope_id=request.scope_id,
            permission=request.permission.value,
            key_type=request.key_type.value,
            key_hash=key_hash,
            hash_version=ApiKeyHashVersion.HMAC_SHA256.value,
            key_prefix=request.key_type.value,
            key_suffix=secret[-8:],
            name=request.name,
            description=request.description,
            allowed_origins=request.allowed_origins,
            allowed_ips=request.allowed_ips,
            expires_at=request.expires_at,
            rate_limit=request.rate_limit,
            state=ApiKeyState.ACTIVE.value,
        )

        if self.audit_service is not None:
            await self.audit_service.log_async(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                action=ActionType.API_KEY_CREATED,
                entity_type=EntityType.API_KEY,
                entity_id=record.id,
                description=f"Created API key '{record.name}'",
                metadata=AuditMetadata.standard(
                    actor=user,
                    target=record,
                    extra={
                        "scope_type": record.scope_type,
                        "scope_id": str(record.scope_id) if record.scope_id else None,
                        "permission": record.permission,
                        "key_type": record.key_type,
                        "expires_at": record.expires_at.isoformat()
                        if record.expires_at
                        else None,
                    },
                ),
            )

        return ApiKeyCreatedResponse(
            api_key=ApiKeyV2.model_validate(record),
            secret=secret,
        )

    async def rotate_key(
        self, *, key_id: UUID, skip_manage_authorization: bool = False
    ) -> ApiKeyCreatedResponse:
        user = self._require_user()
        key = await self._get_key_or_404(key_id=key_id, tenant_id=user.tenant_id)
        if not skip_manage_authorization:
            await self.policy_service.ensure_manage_authorized(key=key)
        await self.policy_service.validate_key_state(key=key)

        secret = self._generate_secret(key.key_prefix)
        key_hash = self._hash_hmac(secret)

        record = await self.api_key_repo.create(
            tenant_id=key.tenant_id,
            owner_user_id=key.owner_user_id,
            created_by_user_id=user.id,
            scope_type=key.scope_type,
            scope_id=key.scope_id,
            permission=key.permission,
            key_type=key.key_type,
            key_hash=key_hash,
            hash_version=ApiKeyHashVersion.HMAC_SHA256.value,
            key_prefix=key.key_prefix,
            key_suffix=secret[-8:],
            name=key.name,
            description=key.description,
            allowed_origins=key.allowed_origins,
            allowed_ips=key.allowed_ips,
            expires_at=key.expires_at,
            rate_limit=key.rate_limit,
            state=ApiKeyState.ACTIVE.value,
            rotated_from_key_id=key.id,
        )

        grace_hours = self.settings.api_key_rotation_grace_hours
        grace_until = datetime.now(timezone.utc) + timedelta(hours=grace_hours)
        await self.api_key_repo.update(
            key_id=key.id,
            tenant_id=key.tenant_id,
            rotation_grace_until=grace_until,
        )

        if self.audit_service is not None:
            await self.audit_service.log_async(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                action=ActionType.API_KEY_ROTATED,
                entity_type=EntityType.API_KEY,
                entity_id=record.id,
                description=f"Rotated API key '{key.name}'",
                metadata=AuditMetadata.standard(
                    actor=user,
                    target=record,
                    extra={
                        "old_key_id": str(key.id),
                        "rotation_grace_until": grace_until.isoformat(),
                    },
                ),
            )

        return ApiKeyCreatedResponse(
            api_key=ApiKeyV2.model_validate(record),
            secret=secret,
        )

    async def update_key(
        self,
        *,
        key_id: UUID,
        request: ApiKeyUpdateRequest,
    ) -> ApiKeyV2:
        user = self._require_user()
        key = await self._get_key_or_404(key_id=key_id, tenant_id=user.tenant_id)
        await self.policy_service.ensure_manage_authorized(key=key)

        updates = request.model_dump(exclude_unset=True)
        if not updates:
            return ApiKeyV2.model_validate(key)

        if "expires_at" in updates and updates.get("expires_at") is not None:
            expires_at = updates.get("expires_at")
            if isinstance(expires_at, datetime) and expires_at < datetime.now(
                timezone.utc
            ):
                raise ApiKeyValidationError(
                    status_code=400,
                    code="invalid_request",
                    message="expires_at must be in the future.",
                )

        await self.policy_service.validate_update_request(key=key, updates=updates)

        updated = await self.api_key_repo.update(
            key_id=key.id,
            tenant_id=key.tenant_id,
            **updates,
        )

        updated_key = updated or key

        if self.audit_service is not None:
            changes: dict[str, dict[str, object]] = {}
            for field in (
                "name",
                "description",
                "allowed_origins",
                "allowed_ips",
                "expires_at",
                "rate_limit",
            ):
                if field in updates:
                    old_value = getattr(key, field)
                    new_value = getattr(updated_key, field)
                    if old_value != new_value:
                        changes[field] = {"old": old_value, "new": new_value}

            await self.audit_service.log_async(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                action=ActionType.API_KEY_UPDATED,
                entity_type=EntityType.API_KEY,
                entity_id=updated_key.id,
                description=f"Updated API key '{updated_key.name}'",
                metadata=AuditMetadata.standard(
                    actor=user,
                    target=updated_key,
                    changes=changes or None,
                ),
            )

        return ApiKeyV2.model_validate(updated_key)

    async def suspend_key(
        self,
        *,
        key_id: UUID,
        request: ApiKeyStateChangeRequest | None = None,
        skip_manage_authorization: bool = False,
    ) -> ApiKeyV2:
        user = self._require_user()
        key = await self._get_key_or_404(key_id=key_id, tenant_id=user.tenant_id)
        if not skip_manage_authorization:
            await self.policy_service.ensure_manage_authorized(key=key)

        effective_state = compute_effective_state(
            revoked_at=key.revoked_at,
            suspended_at=key.suspended_at,
            expires_at=key.expires_at,
        )
        if effective_state == ApiKeyState.REVOKED:
            raise ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="API key is revoked.",
            )
        if effective_state == ApiKeyState.EXPIRED:
            raise ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="API key is expired.",
            )

        now = datetime.now(timezone.utc)
        reason_code = (
            request.reason_code.value if request and request.reason_code else None
        )
        reason_text = request.reason_text if request else None
        updated = await self.api_key_repo.update(
            key_id=key.id,
            tenant_id=key.tenant_id,
            state=ApiKeyState.SUSPENDED.value,
            suspended_at=key.suspended_at or now,
            suspended_reason_code=reason_code,
            suspended_reason_text=reason_text,
        )

        updated_key = updated or key

        if self.audit_service is not None:
            await self.audit_service.log_async(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                action=ActionType.API_KEY_SUSPENDED,
                entity_type=EntityType.API_KEY,
                entity_id=updated_key.id,
                description=f"Suspended API key '{updated_key.name}'",
                metadata=AuditMetadata.standard(
                    actor=user,
                    target=updated_key,
                    changes={
                        "state": {"old": key.state, "new": ApiKeyState.SUSPENDED.value}
                    },
                    extra={
                        "reason_code": reason_code,
                        "reason_text": reason_text,
                    },
                ),
            )

        return ApiKeyV2.model_validate(updated_key)

    async def reactivate_key(
        self, *, key_id: UUID, skip_manage_authorization: bool = False
    ) -> ApiKeyV2:
        user = self._require_user()
        key = await self._get_key_or_404(key_id=key_id, tenant_id=user.tenant_id)
        if not skip_manage_authorization:
            await self.policy_service.ensure_manage_authorized(key=key)

        effective_state = compute_effective_state(
            revoked_at=key.revoked_at,
            suspended_at=key.suspended_at,
            expires_at=key.expires_at,
        )
        if effective_state == ApiKeyState.REVOKED:
            raise ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="API key is revoked.",
            )
        if effective_state == ApiKeyState.EXPIRED:
            raise ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="API key is expired.",
            )
        if key.suspended_at is None:
            return ApiKeyV2.model_validate(key)

        updated = await self.api_key_repo.update(
            key_id=key.id,
            tenant_id=key.tenant_id,
            state=ApiKeyState.ACTIVE.value,
            suspended_at=None,
            suspended_reason_code=None,
            suspended_reason_text=None,
        )

        updated_key = updated or key

        if self.audit_service is not None:
            await self.audit_service.log_async(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                action=ActionType.API_KEY_REACTIVATED,
                entity_type=EntityType.API_KEY,
                entity_id=updated_key.id,
                description=f"Reactivated API key '{updated_key.name}'",
                metadata=AuditMetadata.standard(
                    actor=user,
                    target=updated_key,
                    changes={
                        "state": {"old": key.state, "new": ApiKeyState.ACTIVE.value}
                    },
                    extra={"previous_suspended_at": key.suspended_at.isoformat()},
                ),
            )

        return ApiKeyV2.model_validate(updated_key)

    async def revoke_key(
        self,
        *,
        key_id: UUID,
        request: ApiKeyStateChangeRequest | None = None,
        skip_manage_authorization: bool = False,
    ) -> ApiKeyV2:
        user = self._require_user()
        key = await self._get_key_or_404(key_id=key_id, tenant_id=user.tenant_id)
        if not skip_manage_authorization:
            await self.policy_service.ensure_manage_authorized(key=key)

        effective_state = compute_effective_state(
            revoked_at=key.revoked_at,
            suspended_at=key.suspended_at,
            expires_at=key.expires_at,
        )
        if effective_state == ApiKeyState.REVOKED:
            return ApiKeyV2.model_validate(key)

        now = datetime.now(timezone.utc)
        reason_code = (
            request.reason_code.value if request and request.reason_code else None
        )
        reason_text = request.reason_text if request else None
        updated = await self.api_key_repo.update(
            key_id=key.id,
            tenant_id=key.tenant_id,
            state=ApiKeyState.REVOKED.value,
            revoked_at=now,
            revoked_reason_code=reason_code,
            revoked_reason_text=reason_text,
        )

        updated_key = updated or key

        if self.audit_service is not None:
            await self.audit_service.log_async(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                action=ActionType.API_KEY_REVOKED,
                entity_type=EntityType.API_KEY,
                entity_id=updated_key.id,
                description=f"Revoked API key '{updated_key.name}'",
                metadata=AuditMetadata.standard(
                    actor=user,
                    target=updated_key,
                    changes={
                        "state": {"old": key.state, "new": ApiKeyState.REVOKED.value}
                    },
                    extra={
                        "reason_code": reason_code,
                        "reason_text": reason_text,
                    },
                ),
            )

        return ApiKeyV2.model_validate(updated_key)

    async def expire_key(self, *, key_id: UUID, tenant_id: UUID) -> ApiKeyV2 | None:
        key = await self.api_key_repo.get(key_id=key_id, tenant_id=tenant_id)
        if key is None:
            return None
        if key.revoked_at is not None:
            return ApiKeyV2.model_validate(key)

        now = datetime.now(timezone.utc)
        expires_at = key.expires_at or now
        updated = await self.api_key_repo.update(
            key_id=key.id,
            tenant_id=tenant_id,
            state=ApiKeyState.EXPIRED.value,
            expires_at=expires_at,
        )

        updated_key = updated or key

        if self.audit_service is not None:
            await self.audit_service.log_async(
                tenant_id=tenant_id,
                actor_id=None,
                actor_type=ActorType.SYSTEM,
                action=ActionType.API_KEY_EXPIRED,
                entity_type=EntityType.API_KEY,
                entity_id=updated_key.id,
                description=f"Expired API key '{updated_key.name}'",
                metadata=AuditMetadata.system_action(
                    description="API key expired",
                    target=updated_key,
                    extra={"expires_at": expires_at.isoformat()},
                ),
            )

        return ApiKeyV2.model_validate(updated_key)

    async def _get_key_or_404(self, *, key_id: UUID, tenant_id: UUID) -> ApiKeyV2InDB:
        key = await self.api_key_repo.get(key_id=key_id, tenant_id=tenant_id)
        if key is None:
            raise ApiKeyValidationError(
                status_code=404,
                code="resource_not_found",
                message="API key not found.",
            )
        return key

    async def create_legacy_key(
        self,
        *,
        owner_user_id: UUID,
        tenant_id: UUID,
        scope_type: ApiKeyScopeType,
        scope_id: UUID | None,
        prefix: str,
        permission: ApiKeyPermission,
        name: str,
    ) -> ApiKeyCreatedResponse:
        secret = self._generate_secret(prefix)
        key_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()

        record = await self.api_key_repo.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            created_by_user_id=owner_user_id,
            scope_type=scope_type.value,
            scope_id=scope_id,
            permission=permission.value,
            key_type=ApiKeyType.SK.value,
            key_hash=key_hash,
            hash_version=ApiKeyHashVersion.SHA256.value,
            key_prefix=prefix,
            key_suffix=secret[-4:],
            name=name,
            description=None,
            state=ApiKeyState.ACTIVE.value,
        )

        return ApiKeyCreatedResponse(
            api_key=ApiKeyV2.model_validate(record),
            secret=secret,
        )

    def _generate_secret(self, prefix: str) -> str:
        return f"{prefix}{secrets.token_hex(self.settings.api_key_length)}"

    def _hash_hmac(self, plain_key: str) -> str:
        secret = self.settings.api_key_hash_secret or self.settings.jwt_secret
        return hmac.new(
            secret.encode("utf-8"),
            plain_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _require_user(self) -> "UserInDB":
        if self.user is None:
            raise ApiKeyValidationError(
                status_code=401,
                code="invalid_request",
                message="User context required.",
            )
        return self.user
