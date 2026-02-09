"""CI route coverage guard — prevents permission guard drift.

These are STRUCTURAL invariant tests, not feature tests.
They catch mistakes at the code level and prevent regression.

Phase 5 + Phase 8A-D from the implementation plan.
"""

import ast
import importlib
import pathlib

import pytest

from intric.authentication.auth_dependencies import (
    APPS_READ_OVERRIDES,
    ASSISTANTS_READ_OVERRIDES,
    CONVERSATIONS_READ_OVERRIDES,
    FILES_READ_OVERRIDES,
    KNOWLEDGE_READ_OVERRIDES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_router():
    from intric.server.routers import router
    return router


def _route_has_resource_permission_dep(route) -> bool:
    """Check if a route has _resource_permission_dep dependency."""
    deps = getattr(route, "dependencies", [])
    return any(
        hasattr(dep, "dependency")
        and getattr(dep.dependency, "__name__", "") == "_resource_permission_dep"
        for dep in deps
    )


def _get_all_endpoint_names():
    """Collect all registered endpoint function names from the router."""
    router = _get_router()
    names = set()
    for route in router.routes:
        if hasattr(route, "endpoint"):
            names.add(route.endpoint.__name__)
    return names


def _extract_path_prefix(path: str) -> str:
    """Extract the first path segment as prefix (e.g., '/apps/{id}/' → '/apps')."""
    parts = path.strip("/").split("/")
    if parts and parts[0]:
        return "/" + parts[0]
    return path


def _get_intric_src_path() -> pathlib.Path:
    """Resolve the intric source package path dynamically."""
    spec = importlib.util.find_spec("intric")
    if spec and spec.submodule_search_locations:
        return pathlib.Path(spec.submodule_search_locations[0])
    # Fallback
    return pathlib.Path(__file__).parent.parent.parent / "src" / "intric"


# ---------------------------------------------------------------------------
# Phase 5: Route coverage with explicit allowlist
# ---------------------------------------------------------------------------

# Route prefixes that intentionally lack require_resource_permission_for_method()
# Each entry has a rationale — no silent omissions.
INTENTIONALLY_UNGUARDED = {
    "/settings":                "Internal admin_service role check + endpoint-level scope guards",
    "/users":                   "Router-level admin scope + permission guard on listing; endpoint-level scope guards on admin mutations; /me/ and /tenant/ safe for any scoped key",
    "/admin":                   "admin_service.validate_admin_permission() internally",
    "/dashboard":               "Read-only aggregation endpoint",
    "/icons":                   "Public static assets",
    "/limits":                  "Authenticated limit info (with_user=True)",
    "/prompts":                 "Authenticated via get_container(with_user=True)",
    "/integrations":            "Authenticated via get_container(with_user=True)",
    "/jobs":                    "Authenticated via get_container(with_user=True)",
    "/analysis":                "Authenticated via get_container(with_user=True), service-layer role checks",
    "/logging":                 "Router-level Depends(get_current_active_user) auth",
    "/completion-models":       "Model listing with admin scope guard",
    "/embedding-models":        "Model listing with admin scope guard",
    "/transcription-models":    "Model listing with admin scope guard",
    "/ai-models":               "Model listing aggregation",
    "/user-groups":             "Internal admin role checks",
    "/allowed-origins":         "Internal admin role checks",
    "/security-classifications": "Internal admin role checks",
    "/storage":                 "Internal admin role checks",
    "/token-usage":             "Admin scope + admin key permission guards (not resource guard)",
    "/templates":               "Read-only discovery endpoints",
    "/sysadmin":                "Separate intric_super_api_key auth, out of scope",
    "/modules":                 "Separate auth, out of scope",
    "/roles":                   "Internal role-based access management",
    "/api-keys":                "Self-management with ensure_manage_authorized() + scope guard",
    "/ws":                      "WebSocket endpoint — separate auth",
    "/audit":                   "Admin audit endpoints with scope guard",
    "/auth":                    "Public federation/auth endpoints — no user auth required",
    "/api-docs":                "Public API documentation endpoint",
}


class TestRouteCoverage:
    """Every route must have a resource permission guard or be allowlisted."""

    def test_all_routes_have_permission_guard_or_allowlist(self):
        """Fails CI when new routes are added without permission enforcement."""
        router = _get_router()
        unaccounted_prefixes = set()

        for route in router.routes:
            path = getattr(route, "path", "")
            if not path or path == "/":
                continue

            # Check if this specific route has the guard
            if _route_has_resource_permission_dep(route):
                continue

            # Check if allowlisted by prefix
            prefix = _extract_path_prefix(path)
            if prefix in INTENTIONALLY_UNGUARDED:
                continue

            unaccounted_prefixes.add(prefix)

        assert not unaccounted_prefixes, (
            f"Route prefixes without resource permission guard or allowlist: "
            f"{sorted(unaccounted_prefixes)}. "
            f"Either add require_resource_permission_for_method() or add to "
            f"INTENTIONALLY_UNGUARDED with rationale."
        )

    def test_no_pending_classifications(self):
        """All route classifications must be resolved — zero PENDING allowed."""
        pending = [k for k, v in INTENTIONALLY_UNGUARDED.items() if "PENDING" in v]
        assert len(pending) == 0, (
            f"Found {len(pending)} unresolved PENDING classification(s). "
            f"Investigate and classify: {pending}"
        )

    def test_guarded_routes_exist(self):
        """Verify we actually have guarded routes (not silently passing on zero)."""
        router = _get_router()
        guarded = [
            getattr(r, "path", "")
            for r in router.routes
            if _route_has_resource_permission_dep(r)
        ]
        assert len(guarded) >= 20, (
            f"Expected at least 20 guarded routes, found {len(guarded)}"
        )


# ---------------------------------------------------------------------------
# Phase 8A: No duplicate permission maps or ordering dicts
# ---------------------------------------------------------------------------

class TestNoDuplicatePermissionMaps:
    """Ensure METHOD_PERMISSION_MAP and PERMISSION_LEVEL_ORDER are defined once."""

    def test_no_duplicate_method_permission_map(self):
        """METHOD_PERMISSION_MAP must exist in exactly one place (auth_models.py)."""
        intric_src = _get_intric_src_path()
        matches = []
        for py_file in intric_src.rglob("*.py"):
            if "test" in str(py_file):
                continue
            try:
                tree = ast.parse(py_file.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "METHOD_PERMISSION_MAP":
                            rel = py_file.relative_to(intric_src)
                            matches.append(f"{rel}:{node.lineno}")
                elif isinstance(node, ast.AnnAssign):
                    target = node.target
                    if isinstance(target, ast.Name) and target.id == "METHOD_PERMISSION_MAP":
                        rel = py_file.relative_to(intric_src)
                        matches.append(f"{rel}:{node.lineno}")

        assert len(matches) == 1, (
            f"METHOD_PERMISSION_MAP must exist in exactly one place (auth_models.py). "
            f"Found in: {matches}"
        )

    def test_method_permission_map_is_in_auth_models(self):
        """Verify the single definition is in auth_models.py."""
        from intric.authentication.auth_models import METHOD_PERMISSION_MAP

        assert isinstance(METHOD_PERMISSION_MAP, dict)
        assert "GET" in METHOD_PERMISSION_MAP
        assert "DELETE" in METHOD_PERMISSION_MAP

    def test_permission_level_order_is_in_auth_models(self):
        """Verify PERMISSION_LEVEL_ORDER is in auth_models.py."""
        from intric.authentication.auth_models import PERMISSION_LEVEL_ORDER

        assert isinstance(PERMISSION_LEVEL_ORDER, dict)
        assert PERMISSION_LEVEL_ORDER["read"] < PERMISSION_LEVEL_ORDER["admin"]


# ---------------------------------------------------------------------------
# Phase 8B: Read-override names match real endpoint functions
# ---------------------------------------------------------------------------

class TestReadOverrideValidity:
    """Every name in a read-override frozenset must match a registered endpoint."""

    def test_read_override_names_match_registered_routes(self):
        """Catches stale overrides after endpoint renames."""
        all_endpoint_names = _get_all_endpoint_names()

        all_overrides = (
            ASSISTANTS_READ_OVERRIDES
            | CONVERSATIONS_READ_OVERRIDES
            | APPS_READ_OVERRIDES
            | FILES_READ_OVERRIDES
            | KNOWLEDGE_READ_OVERRIDES
        )
        stale = all_overrides - all_endpoint_names
        assert not stale, (
            f"Read-override endpoint names not found in registered routes: {stale}. "
            f"Was an endpoint renamed? Update the override constant."
        )


# ---------------------------------------------------------------------------
# Phase 8C: Guarded routers have correct read-overrides
# ---------------------------------------------------------------------------

class TestReadOverrideWiring:
    """Verify routers with resource guards have the expected read-override constants.

    Routes are flattened as individual APIRoute objects, so we find a representative
    route by prefix and inspect its dependency closure.
    """

    def _find_guarded_route_by_prefix(self, prefix: str):
        """Find a route starting with prefix that has _resource_permission_dep."""
        router = _get_router()
        for route in router.routes:
            path = getattr(route, "path", "")
            if path.startswith(prefix) and _route_has_resource_permission_dep(route):
                return route
        pytest.fail(f"No guarded route found with prefix '{prefix}'")

    def _get_read_overrides_from_route(self, route):
        """Extract the read_override_endpoints set from a route's dependency closure.

        The _resource_permission_dep closure captures two free variables:
        - read_override_endpoints (frozenset or None)
        - resource_type (str)
        We look for the frozenset cell.
        """
        deps = getattr(route, "dependencies", [])
        for dep in deps:
            if not hasattr(dep, "dependency"):
                continue
            fn = dep.dependency
            if getattr(fn, "__name__", "") == "_resource_permission_dep":
                if hasattr(fn, "__closure__") and fn.__closure__:
                    for cell in fn.__closure__:
                        try:
                            val = cell.cell_contents
                        except ValueError:
                            continue
                        if isinstance(val, frozenset):
                            return val
        return None

    def test_assistants_router_has_assistants_read_overrides(self):
        route = self._find_guarded_route_by_prefix("/assistants")
        overrides = self._get_read_overrides_from_route(route)
        assert overrides is not None, "/assistants missing read overrides"
        assert "ask_assistant" in overrides
        assert "ask_followup" in overrides

    def test_conversations_router_has_conversations_read_overrides(self):
        route = self._find_guarded_route_by_prefix("/conversations")
        overrides = self._get_read_overrides_from_route(route)
        assert overrides is not None, "/conversations missing read overrides"
        assert "chat" in overrides
        assert "leave_feedback" in overrides

    def test_apps_router_has_apps_read_overrides(self):
        route = self._find_guarded_route_by_prefix("/apps")
        overrides = self._get_read_overrides_from_route(route)
        assert overrides is not None, "/apps missing read overrides"
        assert "run_app" in overrides

    def test_services_router_has_apps_read_overrides(self):
        route = self._find_guarded_route_by_prefix("/services")
        overrides = self._get_read_overrides_from_route(route)
        assert overrides is not None, "/services missing read overrides"
        assert "run_service" in overrides

    def test_files_router_has_files_read_overrides(self):
        route = self._find_guarded_route_by_prefix("/files")
        overrides = self._get_read_overrides_from_route(route)
        assert overrides is not None, "/files missing read overrides"
        assert "generate_signed_url" in overrides


# ---------------------------------------------------------------------------
# Phase 8D: Feature flag contract
# ---------------------------------------------------------------------------

class TestFeatureFlagContract:
    """The feature flag truth table as executable code.

    flag=True:  Layer 1 enforced, Layer 2 enforced, Phase 4 enforced
    flag=False: Layer 1 skipped, Layer 2 skipped, Phase 4 STILL enforced
    """

    def _make_key(self, permission="read"):
        from unittest.mock import MagicMock
        key = MagicMock()
        key.permission = permission
        key.resource_permissions = None
        key.scope_type = "tenant"
        key.scope_id = None
        key.id = "test-key-id"
        key.key_prefix = "sk_"
        return key

    def _make_request(self, method="DELETE", path="/test"):
        from unittest.mock import MagicMock
        request = MagicMock()
        request.method = method
        request.url.path = path
        request.state._resource_perm_config = None
        request.state._required_api_key_permission = None
        request.headers = {}
        return request

    def test_flag_true_layer2_enforces(self):
        """flag=True: read key + DELETE on unguarded route → 403."""
        from intric.users.user_service import _check_basic_method_permission
        from intric.authentication.api_key_resolver import ApiKeyValidationError

        key = self._make_key("read")
        request = self._make_request("DELETE")

        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_basic_method_permission(request, key)
        assert exc_info.value.code == "insufficient_permission"

    def test_flag_true_layer1_enforces(self):
        """flag=True: read key + DELETE on guarded route → 403 (resource check)."""
        from intric.authentication.api_key_resolver import (
            ApiKeyValidationError,
            check_resource_permission,
        )
        from unittest.mock import patch

        key = self._make_key("read")

        with patch("intric.authentication.api_key_resolver.get_settings") as mock_settings:
            mock_settings.return_value.api_key_enforce_resource_permissions = True
            with pytest.raises(ApiKeyValidationError):
                check_resource_permission(key, "assistants", "admin")

    def test_flag_false_layer1_skips(self):
        """flag=False: Layer 1 skipped (no exception)."""
        from intric.authentication.api_key_resolver import check_resource_permission
        from unittest.mock import patch

        key = self._make_key("read")

        with patch("intric.authentication.api_key_resolver.get_settings") as mock_settings:
            mock_settings.return_value.api_key_enforce_resource_permissions = False
            # Should NOT raise
            check_resource_permission(key, "assistants", "admin")

    def test_phase4_management_guard_always_enforces(self):
        """Phase 4 management guards enforce regardless of feature flag."""
        from intric.users.user_service import _check_management_permission
        from intric.authentication.api_key_resolver import ApiKeyValidationError

        key = self._make_key("write")

        # Management check does NOT consult feature flag
        with pytest.raises(ApiKeyValidationError) as exc_info:
            _check_management_permission(key, "admin")
        assert exc_info.value.code == "insufficient_permission"
