from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from eneo.authentication.auth_models import (
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


@dataclass(frozen=True)
class RouteContractView:
    """A flattened view of a route plus dependencies inherited from includes."""

    route: Any
    path: str
    dependencies: list[Any]
    tags: list[str]

    def __getattr__(self, name: str) -> Any:
        return getattr(self.route, name)

    @property
    def endpoint(self) -> Any:
        return getattr(self.route, "endpoint", None)

    @property
    def methods(self) -> set[str] | None:
        return getattr(self.route, "methods", None)

    @property
    def dependant(self) -> Any:
        return getattr(self.route, "dependant", None)


def _join_path(prefix: str, path: str) -> str:
    if not prefix:
        return path
    if not path:
        return prefix
    return f"{prefix.rstrip('/')}/{path.lstrip('/')}"


def flatten_routes(
    routes: list[Any],
    *,
    prefix: str = "",
    dependencies: list[Any] | None = None,
    tags: list[str] | None = None,
) -> list[RouteContractView]:
    """Flatten FastAPI/Starlette routes across lazy include and mount nodes."""
    flattened: list[RouteContractView] = []
    inherited_dependencies = list(dependencies or [])
    inherited_tags = list(tags or [])

    for route in routes:
        include_context = getattr(route, "include_context", None)
        original_router = getattr(route, "original_router", None)
        if include_context is not None and original_router is not None:
            flattened.extend(
                flatten_routes(
                    list(getattr(original_router, "routes", []) or []),
                    prefix=_join_path(prefix, getattr(include_context, "prefix", "")),
                    dependencies=[
                        *inherited_dependencies,
                        *list(getattr(include_context, "dependencies", []) or []),
                    ],
                    tags=[
                        *inherited_tags,
                        *list(getattr(include_context, "tags", []) or []),
                    ],
                )
            )
            continue

        mounted_routes = getattr(getattr(route, "app", None), "routes", None)
        if mounted_routes is not None and getattr(route, "path", None):
            flattened.extend(
                flatten_routes(
                    list(mounted_routes),
                    prefix=_join_path(prefix, getattr(route, "path", "")),
                    dependencies=inherited_dependencies,
                    tags=inherited_tags,
                )
            )
            continue

        path = getattr(route, "path", "")
        if not path:
            # Every recognized node kind (lazy include, mount, plain route) has
            # a path. A pathless entry means FastAPI changed the private lazy
            # include attributes this walker duck-types on — fail loudly so
            # the route-contract suites can't silently lose coverage.
            raise AssertionError(
                "flatten_routes: unrecognized pathless route entry "
                f"{type(route).__module__}.{type(route).__qualname__}; "
                "update the include_context/original_router detection above"
            )
        flattened.append(
            RouteContractView(
                route=route,
                path=_join_path(prefix, path),
                dependencies=[
                    *inherited_dependencies,
                    *list(getattr(route, "dependencies", []) or []),
                ],
                tags=[*inherited_tags, *list(getattr(route, "tags", []) or [])],
            )
        )

    return flattened


def runtime_router_routes() -> list[RouteContractView]:
    from eneo.server.routers import router

    return flatten_routes(list(router.routes))


def runtime_app_routes() -> list[RouteContractView]:
    from eneo.server.main import app

    return flatten_routes(list(app.routes))


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


def route_dependency_callables(route: Any) -> list[Any]:
    """Return every dependency callable FastAPI registered for a route.

    FastAPI exposes router-level and endpoint-level dependencies through
    different attributes, and that surface has shifted across releases. Keep
    structural route-contract tests on this single introspection path.
    """
    router_dep_fns: list[Any] = [
        getattr(dep, "dependency", None)
        for dep in getattr(route, "dependencies", []) or []
    ]
    endpoint_dep_fns: list[Any] = _collect_dep_names(getattr(route, "dependant", None))
    return [fn for fn in router_dep_fns + endpoint_dep_fns if fn is not None]


def route_has_dependency_named(route: Any, dep_name: str) -> bool:
    return any(
        getattr(fn, "__name__", "") == dep_name
        for fn in route_dependency_callables(route)
    )


def route_dependency_closures(route: Any, dep_name: str) -> list[dict[str, Any]]:
    return [
        _extract_closure_vars(fn)
        for fn in route_dependency_callables(route)
        if getattr(fn, "__name__", "") == dep_name
    ]


def walk_routes() -> list[RouteInfo]:
    """Enumerate every (path, method) in the live FastAPI router.

    One RouteInfo per (path, method) pair. Inspects both router-level
    ``dependencies=[...]`` and endpoint-level ``Depends(...)`` in the handler
    signature, so structural tests can assert on resource_type / path_param /
    read_override_endpoints / api_key_permission placement without running
    requests.
    """
    from fastapi.routing import APIRoute

    infos: list[RouteInfo] = []

    for route in runtime_router_routes():
        if not isinstance(route.route, APIRoute):
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

        for fn in route_dependency_callables(route):
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
