from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, cast
from urllib.parse import urlparse
from uuid import UUID

from intric.allowed_origins.allowed_origin_repo import AllowedOriginRepository
from intric.authentication.api_key_request_context import resolve_client_ip
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.authentication.auth_models import (
    ApiKeyPermission,
    ApiKeyCreateRequest,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
    compute_effective_state,
)
from intric.main.config import get_settings
from intric.main.exceptions import NotFoundException, UnauthorizedException
from intric.roles.permissions import Permission

if TYPE_CHECKING:
    from starlette.requests import Request
    from intric.spaces.space import Space
    from intric.spaces.space_service import SpaceService
    from intric.users.user import UserInDB


@dataclass(slots=True)
class _TenantOriginCacheEntry:
    patterns: list[str]
    expires_at: datetime


class ApiKeyPolicyService:
    def __init__(
        self,
        allowed_origin_repo: AllowedOriginRepository,
        space_service: "SpaceService | None" = None,
        user: "UserInDB | None" = None,
    ):
        self.allowed_origin_repo = allowed_origin_repo
        self.space_service = space_service
        self.user = user
        self.settings = get_settings()
        self._tenant_origin_cache: dict[UUID, _TenantOriginCacheEntry] = {}
        self._tenant_origin_cache_ttl_seconds = max(
            int(self.settings.api_key_origin_cache_ttl_seconds), 0
        )

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

        if request.key_type == ApiKeyType.PK:
            if request.permission == ApiKeyPermission.ADMIN:
                raise ApiKeyValidationError(
                    status_code=400,
                    code="invalid_request",
                    message="pk_ keys cannot have admin permission.",
                )
            if request.allowed_origins is None:
                raise ApiKeyValidationError(
                    status_code=400,
                    code="invalid_request",
                    message="pk_ keys require allowed_origins.",
                )
            if request.allowed_ips is not None:
                raise ApiKeyValidationError(
                    status_code=400,
                    code="invalid_request",
                    message="pk_ keys do not allow IP restrictions.",
                )
            if request.allowed_origins:
                for origin in request.allowed_origins:
                    if not self._origin_has_scheme(
                        origin
                    ) and not self._is_localhost_origin(origin):
                        raise ApiKeyValidationError(
                            status_code=400,
                            code="invalid_request",
                            message="Origin entries must include scheme (https://...).",
                        )
                await self.validate_allowed_origins_subset(
                    allowed_origins=request.allowed_origins,
                    tenant_id=self._require_user().tenant_id,
                )

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
        if "allowed_origins" in updates:
            allowed_origins = cast(list[str] | None, updates.get("allowed_origins"))
            if key_type != ApiKeyType.PK and allowed_origins is not None:
                raise ApiKeyValidationError(
                    status_code=400,
                    code="invalid_request",
                    message="allowed_origins is only supported for pk_ keys.",
                )
            if key_type == ApiKeyType.PK and allowed_origins is not None:
                if allowed_origins:
                    for origin in allowed_origins:
                        if not self._origin_has_scheme(
                            origin
                        ) and not self._is_localhost_origin(origin):
                            raise ApiKeyValidationError(
                                status_code=400,
                                code="invalid_request",
                                message="Origin entries must include scheme (https://...).",
                            )
                await self.validate_allowed_origins_subset(
                    allowed_origins=allowed_origins,
                    tenant_id=key.tenant_id,
                )

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

    async def ensure_manage_authorized(self, *, key: ApiKeyV2InDB):
        return await self.ensure_creator_authorized(
            scope_type=ApiKeyScopeType(key.scope_type),
            scope_id=key.scope_id,
        )

    async def validate_key_state(self, *, key: ApiKeyV2InDB):
        effective_state = compute_effective_state(
            revoked_at=key.revoked_at,
            suspended_at=key.suspended_at,
            expires_at=key.expires_at,
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

    async def validate_allowed_origins_subset(
        self, *, allowed_origins: list[str] | None, tenant_id: UUID
    ):
        if allowed_origins is None:
            return

        tenant_patterns = await self._get_tenant_origin_patterns(tenant_id)

        if not tenant_patterns:
            for origin in allowed_origins:
                if not self._is_localhost_origin(origin):
                    raise ApiKeyValidationError(
                        status_code=400,
                        code="invalid_request",
                        message="Origin not allowed by tenant policy.",
                    )
            return

        for origin in allowed_origins:
            if self._is_localhost_origin(origin):
                continue
            if "*" in origin:
                if origin in tenant_patterns:
                    continue
                if "://" in origin:
                    host_only = origin.split("://", 1)[1]
                    if host_only in tenant_patterns:
                        continue
                if origin not in tenant_patterns:
                    raise ApiKeyValidationError(
                        status_code=400,
                        code="invalid_request",
                        message=f"Origin '{origin}' is not allowed by tenant policy.",
                    )
                continue
            if not any(
                self._origin_matches(origin, pattern) for pattern in tenant_patterns
            ):
                raise ApiKeyValidationError(
                    status_code=400,
                    code="invalid_request",
                    message=f"Origin '{origin}' is not allowed by tenant policy.",
                )

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
        if rate_limit == -1 and Permission.ADMIN not in user.permissions:
            raise ApiKeyValidationError(
                status_code=403,
                code="insufficient_permission",
                message="Unlimited rate limit requires admin permission.",
            )
        if rate_limit < -1:
            raise ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="rate_limit must be null, -1, or a positive integer.",
            )

        policy = user.tenant.api_key_policy or {}
        max_override = policy.get("max_rate_limit_override")
        if max_override is None:
            return
        if rate_limit > int(max_override):
            raise ApiKeyValidationError(
                status_code=400,
                code="invalid_request",
                message="rate_limit exceeds tenant maximum.",
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

        if self._is_localhost_origin(origin):
            return

        tenant_patterns = await self._get_tenant_origin_patterns(key.tenant_id)

        if not tenant_patterns:
            raise ApiKeyValidationError(
                status_code=403,
                code="origin_not_allowed",
                message="Origin not allowed by tenant policy.",
            )

        key_patterns = key.allowed_origins
        if key_patterns is None:
            key_patterns = tenant_patterns
        elif len(key_patterns) == 0:
            raise ApiKeyValidationError(
                status_code=403,
                code="origin_not_allowed",
                message="Origin not allowed by API key policy.",
            )

        matches_tenant = any(
            self._origin_matches(origin, pattern) for pattern in tenant_patterns
        )
        matches_key = any(
            self._origin_matches(origin, pattern) for pattern in key_patterns
        )

        if not matches_tenant or not matches_key:
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

    def _origin_has_scheme(self, origin: str) -> bool:
        parsed = urlparse(origin)
        return bool(parsed.scheme and parsed.hostname)

    def _is_localhost_origin(self, origin: str) -> bool:
        parsed = urlparse(origin)
        if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
            return True
        return False

    def _origin_matches(self, origin: str, pattern: str) -> bool:
        origin_parsed = urlparse(origin)
        if not origin_parsed.scheme or not origin_parsed.hostname:
            return False

        origin_scheme = origin_parsed.scheme.lower()
        origin_host = origin_parsed.hostname.lower()
        origin_port = origin_parsed.port or (443 if origin_scheme == "https" else 80)

        if "://" not in pattern:
            pattern_host = pattern.lower()
            if pattern_host.startswith("*."):
                base = pattern_host[2:]
                if not origin_host.endswith(f".{base}"):
                    return False
                origin_labels = origin_host.split(".")
                base_labels = base.split(".")
                return len(origin_labels) == len(base_labels) + 1
            return origin_host == pattern_host

        pattern_parsed = urlparse(pattern)
        if not pattern_parsed.scheme or not pattern_parsed.hostname:
            return False

        pattern_scheme = pattern_parsed.scheme.lower()
        pattern_host = pattern_parsed.hostname.lower()
        pattern_port = pattern_parsed.port or (443 if pattern_scheme == "https" else 80)

        if pattern_scheme != origin_scheme or pattern_port != origin_port:
            return False

        if pattern_host.startswith("*."):
            base = pattern_host[2:]
            if not origin_host.endswith(f".{base}"):
                return False
            origin_labels = origin_host.split(".")
            base_labels = base.split(".")
            return len(origin_labels) == len(base_labels) + 1

        return origin_host == pattern_host

    def _require_user(self) -> "UserInDB":
        if self.user is None:
            raise ApiKeyValidationError(
                status_code=401,
                code="invalid_request",
                message="User context required.",
            )
        return self.user

    async def _get_tenant_origin_patterns(self, tenant_id: UUID) -> list[str]:
        now = datetime.now(timezone.utc)
        if self._tenant_origin_cache_ttl_seconds > 0:
            cached = self._tenant_origin_cache.get(tenant_id)
            if cached is not None and cached.expires_at > now:
                return cached.patterns

        tenant_origins = await self.allowed_origin_repo.get_by_tenant(tenant_id)
        patterns = [origin.url for origin in tenant_origins]
        if self._tenant_origin_cache_ttl_seconds > 0:
            self._tenant_origin_cache[tenant_id] = _TenantOriginCacheEntry(
                patterns=patterns,
                expires_at=now
                + timedelta(seconds=self._tenant_origin_cache_ttl_seconds),
            )
        return patterns

    def invalidate_tenant_origin_cache(self, tenant_id: UUID | None = None) -> None:
        if tenant_id is None:
            self._tenant_origin_cache.clear()
            return
        self._tenant_origin_cache.pop(tenant_id, None)
