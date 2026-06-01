from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from intric.authentication.auth_models import (
    ApiKeyHashVersion,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
)


def make_api_key(
    *,
    default_permission: ApiKeyPermission = ApiKeyPermission.READ,
    created_at: datetime | None = None,
    **overrides: Any,
) -> ApiKeyV2InDB:
    base: dict[str, Any] = {
        "id": uuid4(),
        "key_prefix": ApiKeyType.SK.value,
        "key_suffix": "abcd1234",
        "name": "Test Key",
        "description": None,
        "key_type": ApiKeyType.SK,
        "permission": default_permission,
        "scope_type": ApiKeyScopeType.TENANT,
        "scope_id": None,
        "allowed_origins": None,
        "allowed_ips": None,
        "state": ApiKeyState.ACTIVE,
        "expires_at": None,
        "last_used_at": None,
        "revoked_at": None,
        "revoked_reason_code": None,
        "revoked_reason_text": None,
        "suspended_at": None,
        "suspended_reason_code": None,
        "suspended_reason_text": None,
        "rotation_grace_until": None,
        "rate_limit": None,
        "created_at": created_at,
        "updated_at": None,
        "rotated_from_key_id": None,
        "tenant_id": uuid4(),
        "owner_user_id": uuid4(),
        "created_by_user_id": None,
        "created_by_key_id": None,
        "delegation_depth": 0,
        "key_hash": "hash",
        "hash_version": ApiKeyHashVersion.HMAC_SHA256.value,
        "resource_permissions": None,
    }
    if created_at is None:
        base["created_at"] = None
    else:
        base["created_at"] = created_at

    base.update(overrides)
    return ApiKeyV2InDB(**base)


def make_api_key_with_timestamp(**overrides: Any) -> ApiKeyV2InDB:
    return make_api_key(created_at=datetime.now(timezone.utc), **overrides)


# ---------------------------------------------------------------------------
# Router walker — used by structural tests that enforce per-route invariants
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourcePermConfig:
    resource_type: str
    read_override_endpoints: frozenset[str] | None


@dataclass(frozen=True)
class ScopeCheckConfig:
    resource_type: str
    path_param: str | None
    self_filtering: bool


@dataclass(frozen=True)
class RouteInfo:
    path: str
    method: str
    endpoint_name: str
    has_resource_perm_dep: bool
    has_scope_check_dep: bool
    has_api_key_permission_dep: bool
    has_file_delete_scope_guard_dep: bool
    resource_perm_config: ResourcePermConfig | None
    scope_check_config: ScopeCheckConfig | None


def _extract_closure_vars(dep_fn: Any) -> dict[str, Any]:
    if not hasattr(dep_fn, "__closure__") or dep_fn.__closure__ is None:
        return {}
    code = getattr(dep_fn, "__code__", None)
    if code is None:
        return {}
    result: dict[str, Any] = {}
    for name, cell in zip(code.co_freevars, dep_fn.__closure__):
        try:
            result[name] = cell.cell_contents
        except ValueError:
            pass
    return result


def _collect_dep_names(dependant: Any) -> list[Any]:
    """Walk a FastAPI Dependant tree and yield every sub-dependant call callable."""
    if dependant is None:
        return []
    callables: list[Any] = []
    if getattr(dependant, "call", None) is not None:
        callables.append(dependant.call)
    for sub in getattr(dependant, "dependencies", []) or []:
        callables.extend(_collect_dep_names(sub))
    return callables


def walk_routes() -> list[RouteInfo]:
    """Enumerate every (path, method) in the live FastAPI router.

    One RouteInfo per (path, method) pair. Inspects both router-level
    ``dependencies=[...]`` and endpoint-level ``Depends(...)`` in the handler
    signature, so structural tests can assert on resource_type / path_param /
    read_override_endpoints / api_key_permission placement without running
    requests.
    """
    from fastapi.routing import APIRoute

    from intric.server.routers import router

    infos: list[RouteInfo] = []

    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        if not path or path == "/":
            continue

        methods = route.methods or set()
        endpoint_name = getattr(route.endpoint, "__name__", "<unknown>")

        resource_perm_config: ResourcePermConfig | None = None
        scope_check_config: ScopeCheckConfig | None = None
        has_resource_perm_dep = False
        has_scope_check_dep = False
        has_api_key_permission_dep = False
        has_file_delete_scope_guard_dep = False

        # Router-level dependencies (passed to include_router(dependencies=[...]))
        router_dep_fns: list[Any] = [
            getattr(dep, "dependency", None) for dep in route.dependencies
        ]
        # Endpoint-level dependencies (Depends(...) in function signature).
        # Walk the Dependant tree to cover sub-deps like factory-produced closures.
        endpoint_dep_fns: list[Any] = _collect_dep_names(route.dependant)

        for fn in router_dep_fns + endpoint_dep_fns:
            if fn is None:
                continue
            dep_name = getattr(fn, "__name__", "")
            closure = _extract_closure_vars(fn)

            if dep_name == "_resource_permission_dep":
                has_resource_perm_dep = True
                if resource_perm_config is None:
                    resource_perm_config = ResourcePermConfig(
                        resource_type=str(closure.get("resource_type", "")),
                        read_override_endpoints=closure.get("read_override_endpoints"),
                    )
            elif dep_name == "_scope_check_dep":
                has_scope_check_dep = True
                if scope_check_config is None:
                    scope_check_config = ScopeCheckConfig(
                        resource_type=str(closure.get("resource_type", "")),
                        path_param=closure.get("path_param"),
                        self_filtering=bool(closure.get("self_filtering", False)),
                    )
            elif dep_name == "_api_key_permission_dep":
                has_api_key_permission_dep = True
            elif dep_name == "_stash":
                has_file_delete_scope_guard_dep = True

        for method in sorted(methods):
            infos.append(
                RouteInfo(
                    path=path,
                    method=method,
                    endpoint_name=endpoint_name,
                    has_resource_perm_dep=has_resource_perm_dep,
                    has_scope_check_dep=has_scope_check_dep,
                    has_api_key_permission_dep=has_api_key_permission_dep,
                    has_file_delete_scope_guard_dep=has_file_delete_scope_guard_dep,
                    resource_perm_config=resource_perm_config,
                    scope_check_config=scope_check_config,
                )
            )

    return infos
