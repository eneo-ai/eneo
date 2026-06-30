from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.domain.outcome import Outcome
from eneo.authentication.api_key_policy import ApiKeyPolicyService
from eneo.authentication.api_key_resolver import ApiKeyValidationError
from eneo.authentication.api_key_v2_repo import ApiKeysV2Repository
from eneo.authentication.auth_models import (
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyExtendRequest,
    ApiKeyHashVersion,
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyRotateRequest,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyStateChangeRequest,
    ApiKeyType,
    ApiKeyUpdateRequest,
    ApiKeyV2,
    ApiKeyV2InDB,
    ResourcePermissions,
    compute_effective_state,
    derive_permission_from_resource_permissions,
)
from eneo.main.config import get_settings

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService
    from eneo.users.user import UserInDB


def _normalize_future_expiration(value: object) -> datetime | None:
    """Normalize a user-supplied expiration: assume UTC for naive datetimes and
    require it lies in the future. Returns None when value is None."""
    if value is None:
        return None
    if not isinstance(value, datetime):
        return value  # type: ignore[return-value]
    normalized = (
        value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    )
    if normalized < datetime.now(timezone.utc):
        raise ApiKeyValidationError(
            status_code=400,
            code="invalid_request",
            message="expires_at must be in the future.",
        )
    return normalized


def _resource_permissions_to_json(
    resource_permissions: ResourcePermissions | dict[str, str] | None,
) -> dict[str, str] | None:
    if resource_permissions is None:
        return None
    if isinstance(resource_permissions, ResourcePermissions):
        return resource_permissions.model_dump(mode="json", exclude_unset=True)
    return resource_permissions


class ApiKeyLifecycleService:
    def __init__(
        self,
        api_key_repo: ApiKeysV2Repository,
        policy_service: ApiKeyPolicyService,
        audit_service: "AuditService | None",
        user: "UserInDB | None" = None,
    ):
        super().__init__()
        self.api_key_repo = api_key_repo
        self.policy_service = policy_service
        self.audit_service = audit_service
        self.user = user
        self.settings = get_settings()

    async def create_key(
        self,
        request: ApiKeyCreateRequest,
        *,
        ip_address: str | None = None,
        request_id: UUID | None = None,
        user_agent: str | None = None,
    ) -> ApiKeyCreatedResponse:
        user = self._require_user()
        await self.policy_service.validate_create_request(request=request)

        secret = self._generate_secret(request.key_type.value)
        key_hash = self._hash_hmac(secret)

        resource_permissions_value = _resource_permissions_to_json(
            request.resource_permissions
        )

        # For sk_ keys with fine-grained permissions, derive the effective
        # permission ceiling automatically. pk_ keys always use read.
        effective_permission = request.permission
        if (
            request.key_type == ApiKeyType.SK
            and request.resource_permissions is not None
        ):
            effective_permission = derive_permission_from_resource_permissions(
                request.resource_permissions
            )

        owner_user_id = (
            None if request.ownership == ApiKeyOwnership.SERVICE else user.id
        )

        record = await self.api_key_repo.create(
            tenant_id=user.tenant_id,
            ownership=request.ownership.value,
            owner_user_id=owner_user_id,
            created_by_user_id=user.id,
            scope_type=request.scope_type.value,
            scope_id=request.scope_id,
            permission=effective_permission.value,
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
            resource_permissions=resource_permissions_value,
            state=ApiKeyState.ACTIVE.value,
        )

        if self.audit_service is not None:
            await self.audit_service.log_async(
                tenant_id=user.tenant_id,
                user=user,
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
                        "resource_permissions": resource_permissions_value,
                        "allowed_origins": record.allowed_origins,
                        "allowed_ips": record.allowed_ips,
                        "rate_limit": record.rate_limit,
                    },
                ),
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )

        return ApiKeyCreatedResponse(
            api_key=ApiKeyV2.model_validate(record),
            secret=secret,
        )

    async def rotate_key(
        self,
        *,
        key_id: UUID,
        request: ApiKeyRotateRequest | None = None,
        skip_manage_authorization: bool = False,
        ip_address: str | None = None,
        request_id: UUID | None = None,
        user_agent: str | None = None,
    ) -> ApiKeyCreatedResponse:
        user = self._require_user()
        key: ApiKeyV2InDB | None = None
        try:
            key = await self._get_key_or_404(key_id=key_id, tenant_id=user.tenant_id)
            if not skip_manage_authorization:
                await self.policy_service.ensure_manage_authorized(key=key)
                await self.policy_service.ensure_ownership_authorized(key=key)
            await self.policy_service.validate_key_state(key=key)
        except ApiKeyValidationError as exc:
            await self._log_lifecycle_failure(
                action=ActionType.API_KEY_ROTATED,
                user=user,
                key_id=key_id,
                key=key,
                error=exc,
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )
            raise

        assert key is not None

        update_expiration = bool(request and request.update_expiration)
        new_expires_at = key.expires_at
        if update_expiration:
            new_expires_at = await self._validate_expiration_change(
                user=user,
                key=key,
                new_expires_at=request.expires_at if request else None,
                failure_action=ActionType.API_KEY_ROTATED,
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )

        secret = self._generate_secret(key.key_prefix)
        key_hash = self._hash_hmac(secret)

        resource_permissions_value = _resource_permissions_to_json(
            key.resource_permissions
        )

        record = await self.api_key_repo.create(
            tenant_id=key.tenant_id,
            ownership=key.ownership,
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
            expires_at=new_expires_at,
            rate_limit=key.rate_limit,
            resource_permissions=resource_permissions_value,
            state=ApiKeyState.ACTIVE.value,
            rotated_from_key_id=key.id,
        )

        disable_grace = bool(request and request.disable_grace_period)
        if disable_grace:
            grace_until = datetime.now(timezone.utc)
        else:
            tenant = getattr(user, "tenant", None)
            policy = cast(
                dict[str, int | None], getattr(tenant, "api_key_policy", None) or {}
            )
            grace_hours = policy.get("rotation_grace_hours")
            if grace_hours is None:
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
                user=user,
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
                        "grace_period_disabled": disable_grace,
                    },
                ),
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )

            if update_expiration and new_expires_at != key.expires_at:
                await self._log_expiration_extended(
                    user=user,
                    key=record,
                    previous_expires_at=key.expires_at,
                    new_expires_at=new_expires_at,
                    via="rotation",
                    ip_address=ip_address,
                    request_id=request_id,
                    user_agent=user_agent,
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
        skip_manage_authorization: bool = False,
        ip_address: str | None = None,
        request_id: UUID | None = None,
        user_agent: str | None = None,
    ) -> ApiKeyV2:
        user = self._require_user()
        key: ApiKeyV2InDB | None = None
        try:
            key = await self._get_key_or_404(key_id=key_id, tenant_id=user.tenant_id)
            if not skip_manage_authorization:
                await self.policy_service.ensure_manage_authorized(key=key)
                await self.policy_service.ensure_ownership_authorized(key=key)
        except ApiKeyValidationError as exc:
            await self._log_lifecycle_failure(
                action=ActionType.API_KEY_UPDATED,
                user=user,
                key_id=key_id,
                key=key,
                error=exc,
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )
            raise

        assert key is not None
        updates = request.model_dump(exclude_unset=True)
        if not updates:
            return ApiKeyV2.model_validate(key)

        effective_state = compute_effective_state(
            revoked_at=key.revoked_at,
            suspended_at=key.suspended_at,
            expires_at=key.expires_at,
            rotation_grace_until=getattr(key, "rotation_grace_until", None),
        )
        if effective_state in (ApiKeyState.REVOKED, ApiKeyState.EXPIRED):
            metadata_only_fields = {"name", "description"}
            disallowed_fields = sorted(set(updates.keys()) - metadata_only_fields)
            if disallowed_fields:
                exc = ApiKeyValidationError(
                    status_code=400,
                    code="invalid_request",
                    message=(
                        "Only name and description can be updated for revoked or expired "
                        "API keys."
                    ),
                )
                await self._log_lifecycle_failure(
                    action=ActionType.API_KEY_UPDATED,
                    user=user,
                    key_id=key_id,
                    key=key,
                    error=exc,
                    ip_address=ip_address,
                    request_id=request_id,
                    user_agent=user_agent,
                )
                raise exc

        if "expires_at" in updates:
            try:
                updates["expires_at"] = _normalize_future_expiration(
                    updates.get("expires_at")
                )
            except ApiKeyValidationError as exc:
                await self._log_lifecycle_failure(
                    action=ActionType.API_KEY_UPDATED,
                    user=user,
                    key_id=key_id,
                    key=key,
                    error=exc,
                    ip_address=ip_address,
                    request_id=request_id,
                    user_agent=user_agent,
                )
                raise

        try:
            await self.policy_service.validate_update_request(key=key, updates=updates)
        except ApiKeyValidationError as exc:
            await self._log_lifecycle_failure(
                action=ActionType.API_KEY_UPDATED,
                user=user,
                key_id=key_id,
                key=key,
                error=exc,
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )
            raise

        # For sk_ keys: if resource_permissions are being updated, derive
        # the effective permission ceiling automatically.
        if (
            key.key_type == ApiKeyType.SK.value
            and "resource_permissions" in updates
            and updates["resource_permissions"] is not None
        ):
            rp = ResourcePermissions.model_validate(updates["resource_permissions"])
            updates["permission"] = derive_permission_from_resource_permissions(
                rp
            ).value

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
                "permission",
                "allowed_origins",
                "allowed_ips",
                "expires_at",
                "rate_limit",
                "resource_permissions",
            ):
                if field in updates:
                    old_value = getattr(key, field)
                    new_value = getattr(updated_key, field)
                    if old_value != new_value:
                        changes[field] = {"old": old_value, "new": new_value}

            await self.audit_service.log_async(
                tenant_id=user.tenant_id,
                user=user,
                action=ActionType.API_KEY_UPDATED,
                entity_type=EntityType.API_KEY,
                entity_id=updated_key.id,
                description=f"Updated API key '{updated_key.name}'",
                metadata=AuditMetadata.standard(
                    actor=user,
                    target=updated_key,
                    changes=changes or None,
                ),
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )

        return ApiKeyV2.model_validate(updated_key)

    async def extend_expiration(
        self,
        *,
        key_id: UUID,
        request: ApiKeyExtendRequest,
        skip_manage_authorization: bool = False,
        ip_address: str | None = None,
        request_id: UUID | None = None,
        user_agent: str | None = None,
    ) -> ApiKeyV2:
        user = self._require_user()
        key: ApiKeyV2InDB | None = None
        try:
            key = await self._get_key_or_404(key_id=key_id, tenant_id=user.tenant_id)
            if not skip_manage_authorization:
                await self.policy_service.ensure_manage_authorized(key=key)
                await self.policy_service.ensure_ownership_authorized(key=key)
        except ApiKeyValidationError as exc:
            await self._log_lifecycle_failure(
                action=ActionType.API_KEY_EXPIRATION_EXTENDED,
                user=user,
                key_id=key_id,
                key=key,
                error=exc,
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )
            raise

        assert key is not None
        new_expires_at = await self._validate_expiration_change(
            user=user,
            key=key,
            new_expires_at=request.expires_at,
            failure_action=ActionType.API_KEY_EXPIRATION_EXTENDED,
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
        )

        if new_expires_at == key.expires_at:
            return ApiKeyV2.model_validate(key)

        updated = await self.api_key_repo.update(
            key_id=key.id,
            tenant_id=key.tenant_id,
            expires_at=new_expires_at,
        )
        updated_key = updated or key

        await self._log_expiration_extended(
            user=user,
            key=updated_key,
            previous_expires_at=key.expires_at,
            new_expires_at=new_expires_at,
            via="standalone",
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
        )

        return ApiKeyV2.model_validate(updated_key)

    async def suspend_key(
        self,
        *,
        key_id: UUID,
        request: ApiKeyStateChangeRequest | None = None,
        skip_manage_authorization: bool = False,
        ip_address: str | None = None,
        request_id: UUID | None = None,
        user_agent: str | None = None,
    ) -> ApiKeyV2:
        user = self._require_user()
        key: ApiKeyV2InDB | None = None
        try:
            key = await self._get_key_or_404(key_id=key_id, tenant_id=user.tenant_id)
            if not skip_manage_authorization:
                await self.policy_service.ensure_manage_authorized(key=key)
                await self.policy_service.ensure_ownership_authorized(key=key)
        except ApiKeyValidationError as exc:
            await self._log_lifecycle_failure(
                action=ActionType.API_KEY_SUSPENDED,
                user=user,
                key_id=key_id,
                key=key,
                error=exc,
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )
            raise

        assert key is not None
        effective_state = compute_effective_state(
            revoked_at=key.revoked_at,
            suspended_at=key.suspended_at,
            expires_at=key.expires_at,
            rotation_grace_until=getattr(key, "rotation_grace_until", None),
        )
        if effective_state == ApiKeyState.REVOKED:
            exc = ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="API key is revoked.",
            )
            await self._log_lifecycle_failure(
                action=ActionType.API_KEY_SUSPENDED,
                user=user,
                key_id=key_id,
                key=key,
                error=exc,
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )
            raise exc
        if effective_state == ApiKeyState.EXPIRED:
            exc = ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="API key is expired.",
            )
            await self._log_lifecycle_failure(
                action=ActionType.API_KEY_SUSPENDED,
                user=user,
                key_id=key_id,
                key=key,
                error=exc,
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )
            raise exc

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
                user=user,
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
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )

        return ApiKeyV2.model_validate(updated_key)

    async def reactivate_key(
        self,
        *,
        key_id: UUID,
        skip_manage_authorization: bool = False,
        ip_address: str | None = None,
        request_id: UUID | None = None,
        user_agent: str | None = None,
    ) -> ApiKeyV2:
        user = self._require_user()
        key: ApiKeyV2InDB | None = None
        try:
            key = await self._get_key_or_404(key_id=key_id, tenant_id=user.tenant_id)
            if not skip_manage_authorization:
                await self.policy_service.ensure_manage_authorized(key=key)
                await self.policy_service.ensure_ownership_authorized(key=key)
        except ApiKeyValidationError as exc:
            await self._log_lifecycle_failure(
                action=ActionType.API_KEY_REACTIVATED,
                user=user,
                key_id=key_id,
                key=key,
                error=exc,
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )
            raise

        assert key is not None
        effective_state = compute_effective_state(
            revoked_at=key.revoked_at,
            suspended_at=key.suspended_at,
            expires_at=key.expires_at,
            rotation_grace_until=getattr(key, "rotation_grace_until", None),
        )
        if effective_state == ApiKeyState.REVOKED:
            exc = ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="API key is revoked.",
            )
            await self._log_lifecycle_failure(
                action=ActionType.API_KEY_REACTIVATED,
                user=user,
                key_id=key_id,
                key=key,
                error=exc,
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )
            raise exc
        if effective_state == ApiKeyState.EXPIRED:
            exc = ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="API key is expired.",
            )
            await self._log_lifecycle_failure(
                action=ActionType.API_KEY_REACTIVATED,
                user=user,
                key_id=key_id,
                key=key,
                error=exc,
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )
            raise exc
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
                user=user,
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
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )

        return ApiKeyV2.model_validate(updated_key)

    async def revoke_key(
        self,
        *,
        key_id: UUID,
        request: ApiKeyStateChangeRequest | None = None,
        skip_manage_authorization: bool = False,
        ip_address: str | None = None,
        request_id: UUID | None = None,
        user_agent: str | None = None,
    ) -> ApiKeyV2:
        user = self._require_user()
        key: ApiKeyV2InDB | None = None
        try:
            key = await self._get_key_or_404(key_id=key_id, tenant_id=user.tenant_id)
            if not skip_manage_authorization:
                await self.policy_service.ensure_manage_authorized(key=key)
                await self.policy_service.ensure_ownership_authorized(key=key)
        except ApiKeyValidationError as exc:
            await self._log_lifecycle_failure(
                action=ActionType.API_KEY_REVOKED,
                user=user,
                key_id=key_id,
                key=key,
                error=exc,
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )
            raise

        assert key is not None
        effective_state = compute_effective_state(
            revoked_at=key.revoked_at,
            suspended_at=key.suspended_at,
            expires_at=key.expires_at,
            rotation_grace_until=getattr(key, "rotation_grace_until", None),
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
                user=user,
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
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )

        return ApiKeyV2.model_validate(updated_key)

    async def purge_key(
        self,
        *,
        key_id: UUID,
        skip_manage_authorization: bool = False,
        ip_address: str | None = None,
        request_id: UUID | None = None,
        user_agent: str | None = None,
    ) -> None:
        user = self._require_user()
        key: ApiKeyV2InDB | None = None
        try:
            key = await self._get_key_or_404(key_id=key_id, tenant_id=user.tenant_id)
            if not skip_manage_authorization:
                await self.policy_service.ensure_manage_authorized(key=key)
                await self.policy_service.ensure_ownership_authorized(key=key)
        except ApiKeyValidationError as exc:
            await self._log_lifecycle_failure(
                action=ActionType.API_KEY_PURGED,
                user=user,
                key_id=key_id,
                key=key,
                error=exc,
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )
            raise

        assert key is not None
        effective_state = compute_effective_state(
            revoked_at=key.revoked_at,
            suspended_at=key.suspended_at,
            expires_at=key.expires_at,
            rotation_grace_until=getattr(key, "rotation_grace_until", None),
        )
        if effective_state not in (ApiKeyState.REVOKED, ApiKeyState.EXPIRED):
            exc = ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="Only revoked or expired API keys can be deleted.",
            )
            await self._log_lifecycle_failure(
                action=ActionType.API_KEY_PURGED,
                user=user,
                key_id=key_id,
                key=key,
                error=exc,
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )
            raise exc

        # Log before deletion so the audit row references a still-valid key snapshot.
        if self.audit_service is not None:
            await self.audit_service.log_async(
                tenant_id=user.tenant_id,
                user=user,
                action=ActionType.API_KEY_PURGED,
                entity_type=EntityType.API_KEY,
                entity_id=key.id,
                description=f"Permanently deleted API key '{key.name}'",
                metadata=AuditMetadata.standard(
                    actor=user,
                    target=key,
                    extra={
                        "previous_state": effective_state.value,
                        "key_prefix": key.key_prefix,
                        "key_suffix": key.key_suffix,
                    },
                ),
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )

        await self.api_key_repo.delete(key_id=key.id, tenant_id=key.tenant_id)

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
        ip_address: str | None = None,
        request_id: UUID | None = None,
        user_agent: str | None = None,
    ) -> ApiKeyCreatedResponse:
        secret = self._generate_secret(prefix)
        key_hash = self._hash_hmac(secret)

        record = await self.api_key_repo.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            created_by_user_id=owner_user_id,
            scope_type=scope_type.value,
            scope_id=scope_id,
            permission=permission.value,
            key_type=ApiKeyType.SK.value,
            key_hash=key_hash,
            hash_version=ApiKeyHashVersion.HMAC_SHA256.value,
            key_prefix=prefix,
            key_suffix=secret[-4:],
            name=name,
            description=None,
            state=ApiKeyState.ACTIVE.value,
        )

        if self.audit_service is not None:
            actor = self.user
            metadata = (
                AuditMetadata.standard(
                    actor=actor,
                    target=record,
                    extra={
                        "scope_type": record.scope_type,
                        "scope_id": str(record.scope_id) if record.scope_id else None,
                        "permission": record.permission,
                        "legacy_prefix": prefix,
                    },
                )
                if actor is not None
                else AuditMetadata.system_action(
                    description="Created legacy API key",
                    target=record,
                    extra={
                        "scope_type": record.scope_type,
                        "scope_id": str(record.scope_id) if record.scope_id else None,
                        "permission": record.permission,
                        "legacy_prefix": prefix,
                    },
                )
            )
            await self.audit_service.log_async(
                tenant_id=tenant_id,
                actor_id=actor.id if actor is not None else None,
                actor_type=ActorType.USER if actor is not None else ActorType.SYSTEM,
                action=ActionType.API_KEY_GENERATED,
                entity_type=EntityType.API_KEY,
                entity_id=record.id,
                description=f"Created legacy API key '{record.name}'",
                metadata=metadata,
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
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

    async def _validate_expiration_change(
        self,
        *,
        user: "UserInDB",
        key: ApiKeyV2InDB,
        new_expires_at: datetime | None,
        failure_action: ActionType,
        ip_address: str | None,
        request_id: UUID | None,
        user_agent: str | None,
    ) -> datetime | None:
        effective_state = compute_effective_state(
            revoked_at=key.revoked_at,
            suspended_at=key.suspended_at,
            expires_at=key.expires_at,
            rotation_grace_until=getattr(key, "rotation_grace_until", None),
        )
        if effective_state in (ApiKeyState.REVOKED, ApiKeyState.EXPIRED):
            exc = ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="Cannot change expiration on a revoked or expired API key.",
            )
            await self._log_lifecycle_failure(
                action=failure_action,
                user=user,
                key_id=key.id,
                key=key,
                error=exc,
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )
            raise exc

        try:
            normalized = _normalize_future_expiration(new_expires_at)
            await self.policy_service.validate_update_request(
                key=key, updates={"expires_at": normalized}
            )
        except ApiKeyValidationError as exc:
            await self._log_lifecycle_failure(
                action=failure_action,
                user=user,
                key_id=key.id,
                key=key,
                error=exc,
                ip_address=ip_address,
                request_id=request_id,
                user_agent=user_agent,
            )
            raise

        return normalized

    async def _log_expiration_extended(
        self,
        *,
        user: "UserInDB",
        key: ApiKeyV2InDB,
        previous_expires_at: datetime | None,
        new_expires_at: datetime | None,
        via: Literal["standalone", "rotation"],
        ip_address: str | None,
        request_id: UUID | None,
        user_agent: str | None,
    ) -> None:
        if self.audit_service is None:
            return

        await self.audit_service.log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.API_KEY_EXPIRATION_EXTENDED,
            entity_type=EntityType.API_KEY,
            entity_id=key.id,
            description=f"Changed expiration on API key '{key.name}'",
            metadata=AuditMetadata.standard(
                actor=user,
                target=key,
                changes={
                    "expires_at": {
                        "old": previous_expires_at,
                        "new": new_expires_at,
                    }
                },
                extra={"via": via},
            ),
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
        )

    def _require_user(self) -> "UserInDB":
        if self.user is None:
            raise ApiKeyValidationError(
                status_code=401,
                code="invalid_request",
                message="User context required.",
            )
        return self.user

    async def _log_lifecycle_failure(
        self,
        *,
        action: ActionType,
        user: "UserInDB",
        key_id: UUID,
        key: ApiKeyV2InDB | None,
        error: ApiKeyValidationError,
        ip_address: str | None = None,
        request_id: UUID | None = None,
        user_agent: str | None = None,
    ) -> None:
        if self.audit_service is None:
            return

        target_name = key.name if key is not None else None
        actor_name = (
            getattr(user, "username", None)
            or getattr(user, "name", None)
            or (getattr(user, "email", "") or "").split("@")[0]
            or "unknown"
        )
        metadata: dict[str, object] = {
            "actor": {
                "id": str(user.id),
                "name": actor_name,
                "email": user.email,
            },
            "target": {
                "id": str(key.id if key is not None else key_id),
                "name": target_name,
            },
            "extra": {
                "error_code": error.code,
                "status_code": error.status_code,
                "scope_type": key.scope_type if key is not None else None,
                "scope_id": str(key.scope_id)
                if key is not None and key.scope_id
                else None,
            },
        }
        await self.audit_service.log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=action,
            entity_type=EntityType.API_KEY,
            entity_id=key.id if key is not None else key_id,
            description=f"Failed API key lifecycle action '{action.value}'",
            metadata=metadata,
            outcome=Outcome.FAILURE,
            error_message=error.message,
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
        )
