from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, cast
from urllib.parse import urlparse
from uuid import UUID

from intric.allowed_origins.origin_matching import origin_matches_pattern
from intric.authentication.api_key_request_context import resolve_client_ip
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.authentication.auth_models import (
    ApiKeyCreateRequest,
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
    compute_effective_state,
    derive_permission_from_resource_permissions,
)
from intric.main.config import get_settings
from intric.main.exceptions import NotFoundException, UnauthorizedException
from intric.roles.permissions import Permission

if TYPE_CHECKING:
    from starlette.requests import Request

    from intric.spaces.space import Space
    from intric.spaces.space_service import SpaceService
    from intric.users.user import UserInDB


class ApiKeyPolicyService:
    def __init__(
        self,
        space_service: "SpaceService | None" = None,
        user: "UserInDB | None" = None,
    ):
        super().__init__()
        self.space_service = space_service
        self.user = user
        self.settings = get_settings()

    def _require_space_service(self) -> "SpaceService":
        if self.space_service is None:
            raise RuntimeError(
                "SpaceService is required for creator authorization checks."
            )
        return self.space_service

    async def validate_create_request(
        self,
        *,
        request: ApiKeyCreateRequest,
    ) -> "Space | None":
        if request.scope_type != ApiKeyScopeType.TENANT and request.scope_id is None:
            raise ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="scope_id is required for non-tenant keys.",
            )
        if (
            request.scope_type == ApiKeyScopeType.TENANT
            and request.scope_id is not None
        ):
            raise ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="scope_id must be null for tenant-scoped keys.",
            )

        effective_permission = request.permission
        if (
            request.key_type == ApiKeyType.SK
            and request.resource_permissions is not None
        ):
            effective_permission = derive_permission_from_resource_permissions(
                request.resource_permissions
            )

        # Service key guardrails
        if request.ownership == ApiKeyOwnership.SERVICE:
            user = self._require_user()
            if Permission.ADMIN not in user.permissions:
                raise ApiKeyValidationError(
                    status_code=403,
                    code="insufficient_permission",
                    message="Only tenant admins can create service keys.",
                )
            # Extra guardrail: service write/admin keys need IP allowlist or expiration
            if effective_permission in (ApiKeyPermission.WRITE, ApiKeyPermission.ADMIN):
                has_ip = (
                    request.allowed_ips is not None and len(request.allowed_ips) > 0
                )
                has_expiry = request.expires_at is not None
                if not has_ip and not has_expiry:
                    raise ApiKeyValidationError(
                        status_code=400,
                        code="invalid_request",
                        message="Service keys with write/admin permission require an IP allowlist or expiration.",
                    )

        if request.key_type == ApiKeyType.PK:
            if request.permission != ApiKeyPermission.READ:
                raise ApiKeyValidationError(
                    status_code=400,
                    code="invalid_request",
                    message="pk_ keys can only have read permission.",
                )
            if request.allowed_origins is None:
                raise ApiKeyValidationError(
                    status_code=400,
                    code="invalid_request",
                    message="pk_ keys require allowed_origins.",
                )
            if len(request.allowed_origins) == 0:
                raise ApiKeyValidationError(
                    status_code=400,
                    code="invalid_request",
                    message="pk_ keys require at least one allowed origin.",
                )
            if request.allowed_ips is not None:
                raise ApiKeyValidationError(
                    status_code=400,
                    code="invalid_request",
                    message="pk_ keys do not allow IP restrictions.",
                )
            for origin in request.allowed_origins:
                self._validate_origin_format(origin)

        if request.key_type == ApiKeyType.SK and request.allowed_origins is not None:
            raise ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="sk_ keys do not allow origin restrictions.",
            )

        if request.allowed_ips is not None:
            for entry in request.allowed_ips:
                self._validate_ip_entry(entry)

        await self._validate_expiration(request.expires_at)
        await self._validate_rate_limit(request.rate_limit)

        if request.resource_permissions is not None:
            if request.key_type == ApiKeyType.PK:
                raise ApiKeyValidationError(
                    status_code=400,
                    code="invalid_request",
                    message="Public keys (pk_) do not support fine-grained resource permissions.",
                )
            if request.scope_type in (
                ApiKeyScopeType.ASSISTANT,
                ApiKeyScopeType.APP,
            ):
                raise ApiKeyValidationError(
                    status_code=400,
                    code="invalid_request",
                    message=(
                        "Assistant- and app-scoped keys use a flat permission "
                        "level; resource_permissions is not supported."
                    ),
                )

        return await self.ensure_creator_authorized(
            scope_type=request.scope_type, scope_id=request.scope_id
        )

    async def ensure_creator_authorized(
        self,
        *,
        scope_type: ApiKeyScopeType,
        scope_id: UUID | None,
    ) -> "Space | None":
        space_service = self._require_space_service()
        user = self._require_user()
        if scope_type == ApiKeyScopeType.TENANT:
            if Permission.ADMIN not in user.permissions:
                raise ApiKeyValidationError(
                    status_code=403,
                    code="insufficient_permission",
                    message="Tenant-scoped keys require tenant admin permission.",
                )
            return None

        if scope_id is None:
            raise ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="scope_id is required for non-tenant keys.",
            )

        if scope_type == ApiKeyScopeType.SPACE:
            try:
                space = await space_service.get_space(scope_id)
            except NotFoundException:
                raise ApiKeyValidationError(
                    status_code=404,
                    code="resource_not_found",
                    message="Space not found.",
                )
            except UnauthorizedException:
                raise ApiKeyValidationError(
                    status_code=403,
                    code="insufficient_permission",
                    message="Space-scoped keys require space admin permission.",
                )
            actor = space_service.actor_manager.get_space_actor_from_space(space)
            if not actor.can_edit_space():
                raise ApiKeyValidationError(
                    status_code=403,
                    code="insufficient_permission",
                    message="Space-scoped keys require space admin permission.",
                )
            return space

        if scope_type == ApiKeyScopeType.ASSISTANT:
            try:
                space = await space_service.get_space_by_assistant(scope_id)
            except NotFoundException:
                raise ApiKeyValidationError(
                    status_code=404,
                    code="resource_not_found",
                    message="Assistant not found.",
                )
            except UnauthorizedException:
                raise ApiKeyValidationError(
                    status_code=403,
                    code="insufficient_permission",
                    message="Assistant-scoped keys require space editor or admin permission.",
                )
            actor = space_service.actor_manager.get_space_actor_from_space(space)
            if not actor.can_edit_assistants():
                raise ApiKeyValidationError(
                    status_code=403,
                    code="insufficient_permission",
                    message="Assistant-scoped keys require space editor or admin permission.",
                )
            return space

        if scope_type == ApiKeyScopeType.APP:
            try:
                space = await space_service.get_space_by_app(scope_id)
            except NotFoundException:
                raise ApiKeyValidationError(
                    status_code=404,
                    code="resource_not_found",
                    message="App not found.",
                )
            except UnauthorizedException:
                raise ApiKeyValidationError(
                    status_code=403,
                    code="insufficient_permission",
                    message="App-scoped keys require space editor or admin permission.",
                )
            actor = space_service.actor_manager.get_space_actor_from_space(space)
            if not actor.can_edit_apps():
                raise ApiKeyValidationError(
                    status_code=403,
                    code="insufficient_permission",
                    message="App-scoped keys require space editor or admin permission.",
                )
            return space

        raise ApiKeyValidationError(
            status_code=400,
            code="invalid_request",
            message=f"Unsupported scope_type '{scope_type}'.",
        )

    async def validate_update_request(
        self,
        *,
        key: ApiKeyV2InDB,
        updates: dict[str, object],
    ) -> None:
        if not updates:
            return

        key_type = ApiKeyType(key.key_type)
        new_permission: ApiKeyPermission | None = None
        if "permission" in updates:
            raw_permission = updates.get("permission")
            if raw_permission is not None:
                new_permission = (
                    raw_permission
                    if isinstance(raw_permission, ApiKeyPermission)
                    else ApiKeyPermission(raw_permission)
                )
                if (
                    key_type == ApiKeyType.PK
                    and new_permission != ApiKeyPermission.READ
                ):
                    raise ApiKeyValidationError(
                        status_code=400,
                        code="invalid_request",
                        message="pk_ keys can only have read permission.",
                    )

        if "allowed_origins" in updates:
            allowed_origins = cast(list[str] | None, updates.get("allowed_origins"))
            if key_type != ApiKeyType.PK and allowed_origins is not None:
                raise ApiKeyValidationError(
                    status_code=400,
                    code="invalid_request",
                    message="allowed_origins is only supported for pk_ keys.",
                )
            if key_type == ApiKeyType.PK and allowed_origins is not None:
                if len(allowed_origins) == 0:
                    raise ApiKeyValidationError(
                        status_code=400,
                        code="invalid_request",
                        message="pk_ keys require at least one allowed origin.",
                    )
                for origin in allowed_origins:
                    self._validate_origin_format(origin)

        if "allowed_ips" in updates:
            allowed_ips = cast(list[str] | None, updates.get("allowed_ips"))
            if key_type != ApiKeyType.SK and allowed_ips is not None:
                raise ApiKeyValidationError(
                    status_code=400,
                    code="invalid_request",
                    message="allowed_ips is only supported for sk_ keys.",
                )
            if allowed_ips is not None:
                for entry in allowed_ips:
                    self._validate_ip_entry(entry)

        if "expires_at" in updates:
            expires_at = cast(datetime | None, updates.get("expires_at"))
            await self._validate_expiration(expires_at)
        if "rate_limit" in updates:
            rate_limit = cast(int | None, updates.get("rate_limit"))
            await self._validate_rate_limit(rate_limit)

        if "resource_permissions" in updates:
            raw_rp = updates.get("resource_permissions")
            if raw_rp is not None:
                if ApiKeyType(key.key_type) == ApiKeyType.PK:
                    raise ApiKeyValidationError(
                        status_code=400,
                        code="invalid_request",
                        message="Public keys (pk_) do not support fine-grained resource permissions.",
                    )
                if ApiKeyScopeType(key.scope_type) in (
                    ApiKeyScopeType.ASSISTANT,
                    ApiKeyScopeType.APP,
                ):
                    raise ApiKeyValidationError(
                        status_code=400,
                        code="invalid_request",
                        message=(
                            "Assistant- and app-scoped keys use a flat permission "
                            "level; resource_permissions is not supported."
                        ),
                    )

    async def ensure_ownership_authorized(self, *, key: ApiKeyV2InDB):
        """Service keys: any scope-authorized user can manage.
        User keys: only the owner can manage."""
        if ApiKeyOwnership(key.ownership) == ApiKeyOwnership.SERVICE:
            return
        user = self._require_user()
        if key.owner_user_id == user.id:
            return
        raise ApiKeyValidationError(
            status_code=403,
            code="insufficient_permission",
            message="You do not have permission to manage another user's personal API key.",
        )

    async def ensure_manage_authorized(self, *, key: ApiKeyV2InDB):
        await self.ensure_creator_authorized(
            scope_type=ApiKeyScopeType(key.scope_type),
            scope_id=key.scope_id,
        )

    async def validate_key_state(self, *, key: ApiKeyV2InDB):
        effective_state = compute_effective_state(
            revoked_at=key.revoked_at,
            suspended_at=key.suspended_at,
            expires_at=key.expires_at,
            rotation_grace_until=getattr(key, "rotation_grace_until", None),
        )
        if effective_state != ApiKeyState.ACTIVE:
            raise ApiKeyValidationError(
                status_code=401,
                code="invalid_api_key",
                message=f"API key is {effective_state.value}.",
            )

    async def enforce_guardrails(
        self,
        *,
        key: ApiKeyV2InDB,
        origin: str | None,
        client_ip: str | None,
    ):
        await self.validate_key_state(key=key)
        if ApiKeyType(key.key_type) == ApiKeyType.PK:
            await self._validate_origin(key=key, origin=origin)
        if ApiKeyType(key.key_type) == ApiKeyType.SK:
            self._validate_ip(key=key, client_ip=client_ip)

    async def _validate_expiration(self, expires_at: datetime | None):
        user = self._require_user()
        policy = user.tenant.api_key_policy or {}
        require_expiration = policy.get("require_expiration")
        max_expiration_days = policy.get("max_expiration_days")
        if require_expiration and expires_at is None:
            raise ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="Expiration is required by tenant policy.",
            )
        if expires_at is None or max_expiration_days is None:
            return

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        max_delta = timedelta(days=int(max_expiration_days))
        if expires_at > datetime.now(timezone.utc) + max_delta:
            raise ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="Expiration exceeds tenant maximum.",
            )

    async def _validate_rate_limit(self, rate_limit: int | None):
        user = self._require_user()
        if rate_limit is None:
            return
        if rate_limit == 0:
            raise ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="rate_limit must be null, -1, or a positive integer.",
            )
        if rate_limit < -1:
            raise ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="rate_limit must be null, -1, or a positive integer.",
            )

        policy = user.tenant.api_key_policy or {}
        max_override = policy.get("max_rate_limit_override")

        if max_override is not None:
            # max_rate_limit_override is an absolute ceiling — even admin -1
            # (unlimited) is rejected when a cap is set.
            if rate_limit == -1:
                raise ApiKeyValidationError(
                    status_code=400,
                    code="invalid_request",
                    message="Unlimited rate limit is not allowed when a tenant maximum is set.",
                )
            if rate_limit > int(max_override):
                raise ApiKeyValidationError(
                    status_code=400,
                    code="invalid_request",
                    message="rate_limit exceeds tenant maximum.",
                )
        elif rate_limit == -1 and Permission.ADMIN not in user.permissions:
            raise ApiKeyValidationError(
                status_code=403,
                code="insufficient_permission",
                message="Unlimited rate limit requires admin permission.",
            )

    def _validate_ip_entry(self, entry: str) -> None:
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError as exc:
            raise ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message=f"Invalid IP allowlist entry '{entry}'.",
            ) from exc

    async def _validate_origin(self, *, key: ApiKeyV2InDB, origin: str | None):
        if origin is None:
            raise ApiKeyValidationError(
                status_code=403,
                code="origin_not_allowed",
                message="Origin header required for pk_ keys.",
            )

        # Per-key allowed_origins is the only authority. The central tenant
        # allowlist was dropped: trust the key creator to list exactly the
        # origins their integration needs.
        key_patterns = key.allowed_origins
        if key_patterns is None:
            # Legacy keys minted before allowed_origins became required.
            # New pk_ keys always carry a non-empty list.
            return
        if len(key_patterns) == 0:
            raise ApiKeyValidationError(
                status_code=403,
                code="origin_not_allowed",
                message="Origin not allowed by API key policy.",
            )

        if not any(self._origin_matches(origin, pattern) for pattern in key_patterns):
            raise ApiKeyValidationError(
                status_code=403,
                code="origin_not_allowed",
                message="Origin not allowed.",
            )

    def _validate_ip(self, *, key: ApiKeyV2InDB, client_ip: str | None):
        if key.allowed_ips is None:
            return
        if client_ip is None:
            raise ApiKeyValidationError(
                status_code=403,
                code="ip_not_allowed",
                message="Client IP unavailable.",
            )

        if not self._ip_allowed(client_ip, key.allowed_ips):
            raise ApiKeyValidationError(
                status_code=403,
                code="ip_not_allowed",
                message="Client IP not allowed.",
            )

    def resolve_client_ip(self, request: "Request") -> str | None:
        return resolve_client_ip(
            request,
            trusted_proxy_count=self.settings.trusted_proxy_count,
            trusted_proxy_headers=self.settings.trusted_proxy_headers,
        )

    def _ip_allowed(self, client_ip: str, allowlist: list[str]) -> bool:
        try:
            parsed_client_ip = ipaddress.ip_address(client_ip)
        except ValueError:
            return False

        for entry in allowlist:
            try:
                network = ipaddress.ip_network(entry, strict=False)
            except ValueError:
                continue
            if parsed_client_ip in network:
                return True
        return False

    def _validate_origin_format(self, origin: str) -> None:
        """Sanity-check a per-key origin entry. Trust the key creator on the
        value, but reject typos that would silently break their integration.

        Required shape: ``<scheme>://<host>[:port]`` with scheme http(s) and
        a non-empty host. Wildcards in the host are fine (matching is the
        request-time concern of ``origin_matches_pattern``).
        """
        parsed = urlparse(origin)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message=(
                    f"Invalid origin '{origin}': "
                    "must include scheme (http:// or https://) and host."
                ),
            )

    def _origin_matches(self, origin: str, pattern: str) -> bool:
        return origin_matches_pattern(origin, pattern)

    def _require_user(self) -> "UserInDB":
        if self.user is None:
            raise ApiKeyValidationError(
                status_code=401,
                code="invalid_request",
                message="User context required.",
            )
        return self.user
