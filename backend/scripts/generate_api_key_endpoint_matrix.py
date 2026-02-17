#!/usr/bin/env python3
"""Generate an API key v2 endpoint access matrix from mounted route guards.

This script statically inspects mounted FastAPI routes and classifies expected
API-key behavior for each key profile:
  - scopes: tenant, space, assistant, app
  - permissions: read, write, admin

It focuses on API-key enforcement layers:
  1) method/resource permission
  2) management permission
  3) scope enforcement

It does not execute service-layer role checks or data-dependent scope lookups.
Those outcomes are marked as CONDITIONAL where runtime data is required.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Keep local copies to avoid importing auth_models at module import time.
# auth_models currently initializes Settings via get_settings().
METHOD_PERMISSION_MAP: dict[str, str] = {
    "GET": "read",
    "HEAD": "read",
    "OPTIONS": "read",
    "POST": "write",
    "PUT": "write",
    "PATCH": "write",
    "DELETE": "admin",
}

PERMISSION_LEVEL_ORDER: dict[str, int] = {
    "none": 0,
    "read": 1,
    "write": 2,
    "admin": 3,
}


def _bootstrap_env() -> None:
    """Load backend/.env into process env if values are not already exported.

    This allows running the script directly with `python3` in devcontainer shells
    where env vars are not exported but .env exists.
    """
    env_file = os.getenv("INTRIC_ENV_FILE")
    if env_file:
        path = Path(env_file)
    else:
        # /backend/scripts/generate_api_key_endpoint_matrix.py -> /backend/.env
        path = Path(__file__).resolve().parents[1] / ".env"

    if not path.exists():
        return

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        # Preserve quoted values as-is (minus surrounding quotes).
        if value and value[0] in {"'", '"'}:
            quote = value[0]
            if value.endswith(quote) and len(value) >= 2:
                value = value[1:-1]
            else:
                value = value.strip('"').strip("'")
        else:
            # Strip inline comments for unquoted values:
            # KEY=123   # comment  -> 123
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        os.environ.setdefault(key, value)


def _bootstrap_pythonpath() -> None:
    """Ensure backend/src is importable when script is run from scripts/."""
    src_path = Path(__file__).resolve().parents[1] / "src"
    if src_path.exists():
        src_str = str(src_path)
        if src_str not in sys.path:
            sys.path.insert(0, src_str)


def _get_root_router():
    # Import after env bootstrap so Settings can initialize.
    from intric.server.routers import router as root_router

    return root_router


@dataclass(frozen=True)
class KeyProfile:
    name: str
    scope: str
    permission: str


PROFILES: tuple[KeyProfile, ...] = (
    KeyProfile("tenant_read", "tenant", "read"),
    KeyProfile("tenant_write", "tenant", "write"),
    KeyProfile("tenant_admin", "tenant", "admin"),
    KeyProfile("space_read", "space", "read"),
    KeyProfile("space_write", "space", "write"),
    KeyProfile("space_admin", "space", "admin"),
    KeyProfile("assistant_read", "assistant", "read"),
    KeyProfile("assistant_write", "assistant", "write"),
    KeyProfile("assistant_admin", "assistant", "admin"),
    KeyProfile("app_read", "app", "read"),
    KeyProfile("app_write", "app", "write"),
    KeyProfile("app_admin", "app", "admin"),
)


def _rank(permission: str) -> int:
    return PERMISSION_LEVEL_ORDER[permission]


def _dep_by_name(route, dep_name: str):
    for dep in getattr(route, "dependencies", []):
        fn = getattr(dep, "dependency", None)
        if fn is not None and getattr(fn, "__name__", "") == dep_name:
            return fn
    return None


def _extract_closure_value(fn, predicate) -> Any:
    closure = getattr(fn, "__closure__", None)
    if not closure:
        return None
    for cell in closure:
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        if predicate(value):
            return value
    return None


def _scope_config(route) -> dict[str, Any] | None:
    fn = _dep_by_name(route, "_scope_check_dep")
    if fn is None:
        return None
    cfg = _extract_closure_value(
        fn,
        lambda value: isinstance(value, dict)
        and "resource_type" in value
        and "path_param" in value,
    )
    if cfg is not None:
        return cfg

    # Current implementation stores free vars directly in closure:
    #   path_param, resource_type
    closure = getattr(fn, "__closure__", None) or ()
    values: list[Any] = []
    for cell in closure:
        try:
            values.append(cell.cell_contents)
        except ValueError:
            continue

    known_resource_types = {
        "admin",
        "space",
        "assistant",
        "app",
        "app_run",
        "conversation",
        "group_chat",
        "service",
        "collection",
        "website",
        "info_blob",
        "crawl_run",
    }
    resource_type = next(
        (v for v in values if isinstance(v, str) and v in known_resource_types),
        None,
    )
    path_param = next(
        (
            v
            for v in values
            if v is None or (isinstance(v, str) and v not in known_resource_types)
        ),
        None,
    )
    if resource_type is None:
        return None

    if resource_type == "info_blob" and path_param is None:
        route_path = getattr(route, "path", "")
        if "{id}" in route_path:
            path_param = "id"
        elif "{space_id}" in route_path:
            path_param = "space_id"

    return {"resource_type": resource_type, "path_param": path_param}


def _resource_perm_config(route) -> dict[str, Any] | None:
    fn = _dep_by_name(route, "_resource_permission_dep")
    if fn is None:
        return None
    cfg = _extract_closure_value(
        fn,
        lambda value: isinstance(value, dict)
        and "resource_type" in value
        and "read_override_endpoints" in value,
    )
    if cfg is not None:
        return cfg

    # Current implementation stores free vars directly in closure:
    #   read_override_endpoints, resource_type
    closure = getattr(fn, "__closure__", None) or ()
    values: list[Any] = []
    for cell in closure:
        try:
            values.append(cell.cell_contents)
        except ValueError:
            continue

    overrides = next(
        (
            v
            for v in values
            if isinstance(v, frozenset) or v is None
        ),
        None,
    )
    resource_type = next((v for v in values if isinstance(v, str)), None)
    if resource_type is None:
        return None
    return {
        "resource_type": resource_type,
        "read_override_endpoints": overrides,
    }


def _required_management_perm(route) -> str | None:
    fn = _dep_by_name(route, "_api_key_permission_dep")
    if fn is None:
        return None
    value = _extract_closure_value(
        fn,
        lambda v: isinstance(v, str) or hasattr(v, "value"),
    )
    if hasattr(value, "value"):
        return value.value
    return value


def _special_auth(route) -> str | None:
    dep_names = {
        getattr(getattr(dep, "dependency", None), "__name__", "")
        for dep in getattr(route, "dependencies", [])
    }
    if "authenticate_super_api_key" in dep_names:
        return "SUPER_API_KEY_ONLY"
    if "authenticate_super_duper_api_key" in dep_names:
        return "SUPER_DUPER_API_KEY_ONLY"
    return None


def _required_method_permission(
    method: str, endpoint_name: str, resource_cfg: dict[str, Any] | None
) -> str:
    required = METHOD_PERMISSION_MAP.get(method, "read")
    if resource_cfg is None:
        return required
    overrides = resource_cfg.get("read_override_endpoints") or frozenset()
    if endpoint_name in overrides:
        return "read"
    return required


def _scope_outcome(
    *,
    profile_scope: str,
    scope_cfg: dict[str, Any] | None,
    strict_mode: bool,
) -> str:
    if scope_cfg is None:
        return "ALLOW"

    resource_type = scope_cfg.get("resource_type")
    path_param = scope_cfg.get("path_param")

    if profile_scope == "tenant":
        return "ALLOW"

    # Non-tenant scopes are always denied on tenant-admin resources.
    if resource_type == "admin":
        return "DENY_SCOPE"

    # List/body-driven routes (no deterministic path resource id at auth layer)
    if path_param is None:
        if strict_mode:
            return "DENY_SCOPE_STRICT_LIST"
        if profile_scope == "space":
            return "CONDITIONAL_SCOPE_SERVICE_FILTER"
        if profile_scope == "assistant":
            if resource_type in {"assistant", "conversation"}:
                return "CONDITIONAL_SCOPE_SERVICE_FILTER"
            return "DENY_SCOPE"
        if profile_scope == "app":
            if resource_type in {"app", "app_run"}:
                return "CONDITIONAL_SCOPE_SERVICE_FILTER"
            return "DENY_SCOPE"
        return "DENY_SCOPE"

    # Path-level routes with resource id:
    if profile_scope == "space":
        return "CONDITIONAL_SCOPE_MATCH"
    if profile_scope == "assistant":
        if resource_type in {"assistant", "conversation"}:
            return "CONDITIONAL_SCOPE_MATCH"
        return "DENY_SCOPE"
    if profile_scope == "app":
        if resource_type in {"app", "app_run"}:
            return "CONDITIONAL_SCOPE_MATCH"
        return "DENY_SCOPE"
    return "DENY_SCOPE"


def _profile_outcome(
    *,
    profile: KeyProfile,
    method_required: str,
    management_required: str | None,
    scope_cfg: dict[str, Any] | None,
    strict_mode: bool,
    permission_enforcement: bool,
    scope_enforcement: bool,
    special_auth: str | None,
) -> str:
    if special_auth is not None:
        return special_auth

    # Layer 1/2: method/resource permission checks
    if permission_enforcement and _rank(profile.permission) < _rank(method_required):
        return "DENY_PERMISSION"

    # Layer 4: management permission (always enforced)
    if management_required is not None and _rank(profile.permission) < _rank(management_required):
        return "DENY_MANAGEMENT"

    # Layer 3: scope enforcement
    if scope_enforcement:
        scope_outcome = _scope_outcome(
            profile_scope=profile.scope,
            scope_cfg=scope_cfg,
            strict_mode=strict_mode,
        )
        if scope_outcome != "ALLOW":
            return scope_outcome

    return "ALLOW"


def _route_rows(
    *,
    strict_mode: bool,
    permission_enforcement: bool,
    scope_enforcement: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    root_router = _get_root_router()
    for route in root_router.routes:
        path = getattr(route, "path", "")
        endpoint = getattr(route, "endpoint", None)
        methods = sorted(m for m in getattr(route, "methods", set()) if m != "HEAD")
        if not path or endpoint is None or not methods:
            continue

        endpoint_name = getattr(endpoint, "__name__", "<unknown>")
        scope_cfg = _scope_config(route)
        resource_cfg = _resource_perm_config(route)
        management_required = _required_management_perm(route)
        special_auth = _special_auth(route)

        for method in methods:
            method_required = _required_method_permission(
                method=method,
                endpoint_name=endpoint_name,
                resource_cfg=resource_cfg,
            )
            row = {
                "method": method,
                "path": path,
                "endpoint": endpoint_name,
                "method_required_permission": method_required,
                "management_required_permission": management_required or "",
                "scope_resource_type": (scope_cfg or {}).get("resource_type", ""),
                "scope_path_param": (scope_cfg or {}).get("path_param", ""),
                "special_auth": special_auth or "",
            }
            for profile in PROFILES:
                row[profile.name] = _profile_outcome(
                    profile=profile,
                    method_required=method_required,
                    management_required=management_required,
                    scope_cfg=scope_cfg,
                    strict_mode=strict_mode,
                    permission_enforcement=permission_enforcement,
                    scope_enforcement=scope_enforcement,
                    special_auth=special_auth,
                )
            rows.append(row)

    rows.sort(key=lambda r: (r["path"], r["method"], r["endpoint"]))
    return rows


def _to_markdown(rows: list[dict[str, Any]]) -> str:
    headers = [
        "method",
        "path",
        "endpoint",
        "method_required_permission",
        "management_required_permission",
        "scope_resource_type",
        "scope_path_param",
    ] + [p.name for p in PROFILES]

    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        values = [str(row.get(h, "")) for h in headers]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _to_csv(rows: list[dict[str, Any]], out_path: Path) -> None:
    headers = list(rows[0].keys()) if rows else []
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    _bootstrap_pythonpath()
    _bootstrap_env()

    parser = argparse.ArgumentParser(
        description="Generate API key endpoint matrix by profile.",
    )
    parser.add_argument(
        "--strict-mode",
        choices=["on", "off"],
        default="off",
        help="Assume strict mode enabled or disabled for list/body-driven scope checks.",
    )
    parser.add_argument(
        "--permission-enforcement",
        choices=["on", "off"],
        default="on",
        help="Assume api_key_enforce_resource_permissions flag state.",
    )
    parser.add_argument(
        "--scope-enforcement",
        choices=["on", "off"],
        default="on",
        help="Assume effective scope enforcement flag state.",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "csv", "json"],
        default="markdown",
        help="Output format.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output file path. If empty, prints to stdout.",
    )
    args = parser.parse_args()

    rows = _route_rows(
        strict_mode=args.strict_mode == "on",
        permission_enforcement=args.permission_enforcement == "on",
        scope_enforcement=args.scope_enforcement == "on",
    )

    if args.format == "json":
        payload = json.dumps(rows, indent=2, default=str)
        if args.output:
            Path(args.output).write_text(payload, encoding="utf-8")
        else:
            print(payload)
        return 0

    if args.format == "csv":
        if args.output:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            _to_csv(rows, out)
        else:
            # Print CSV to stdout
            headers = list(rows[0].keys()) if rows else []
            writer = csv.DictWriter(__import__("sys").stdout, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return 0

    # markdown
    payload = _to_markdown(rows)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
