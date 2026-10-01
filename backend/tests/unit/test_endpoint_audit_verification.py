"""Endpoint audit verification tests.

Verifies that all fixes from the endpoint audit (Steps 17-25) are correctly
wired. These are STRUCTURAL tests that inspect actual router/endpoint objects
to prevent regression.
"""

import importlib
import inspect
from types import SimpleNamespace

import pytest

from eneo.authentication.auth_dependencies import FILES_READ_OVERRIDES
from eneo.authentication.endpoint_access import access_for
from eneo.roles.permissions import Permission
from tests.unit.api_key_test_utils import (
    route_dependency_closures,
    runtime_app_routes,
    runtime_router_routes,
)
from tests.unit.api_key_test_utils import (
    route_has_dependency_named as _route_has_dependency_named_from_route,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_router():
    return SimpleNamespace(routes=runtime_router_routes())


def _get_app():
    return SimpleNamespace(routes=runtime_app_routes())


def _find_route_by_path_and_method(router, path_prefix: str, method: str = None):
    """Find routes matching a path prefix (and optionally an HTTP method)."""
    matches = []
    for route in router.routes:
        route_path = getattr(route, "path", "")
        if route_path.startswith(path_prefix):
            if method is None:
                matches.append(route)
            else:
                methods = getattr(route, "methods", set())
                if method in methods:
                    matches.append(route)
    return matches


def _route_has_dependency_named(route, dep_name: str) -> bool:
    """Check if a route has a dependency with a specific __name__."""
    return _route_has_dependency_named_from_route(route, dep_name)


def _endpoint_has_dependency_named(endpoint_fn, dep_name: str) -> bool:
    """Check if an endpoint function has a parameter with a dependency matching dep_name."""
    sig = inspect.signature(endpoint_fn)
    for param in sig.parameters.values():
        dep = param.default
        if hasattr(dep, "dependency"):
            if getattr(dep.dependency, "__name__", "") == dep_name:
                return True
    return False


def _get_eneo_src_path():
    spec = importlib.util.find_spec("eneo")
    if spec and spec.submodule_search_locations:
        import pathlib

        return pathlib.Path(spec.submodule_search_locations[0])
    import pathlib

    return pathlib.Path(__file__).parent.parent.parent / "src" / "eneo"


# ---------------------------------------------------------------------------
# Step 17: /users/admin/* Admin-Role Enforcement (P0-1)
# ---------------------------------------------------------------------------


class TestUserAdminEndpointGuards:
    """Every user-administration operation has an explicit ADMIN contract."""

    def test_admin_endpoints_require_admin(self):
        from eneo.users.user_router import delete_user, invite_user, update_user

        for endpoint in (invite_user, update_user, delete_user):
            policy = access_for(endpoint)
            assert policy is not None
            assert policy.authorization is Permission.ADMIN


# ---------------------------------------------------------------------------
# Step 18: Model Provider + Tenant Model Admin Checks (P0-2)
# ---------------------------------------------------------------------------


class TestModelRouterAdminChecks:
    """Check each registered operation, never the number of guards in a file."""

    def test_model_administration_and_probes_require_admin(self):
        checked = set()
        for route in runtime_router_routes():
            if not route.path.startswith(
                ("/admin/model-providers", "/admin/tenant-models")
            ):
                continue
            if not (route.methods or set()) & {
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
            } and not route.path.endswith("/{provider_id}/models/"):
                continue
            policy = access_for(route.endpoint)
            assert policy is not None, route.path
            assert policy.authorization is Permission.ADMIN, route.path
            checked.add(route.path)
        assert {
            "/admin/model-providers/{provider_id}/models/",
            "/admin/model-providers/{provider_id}/test/",
            "/admin/model-providers/{provider_id}/validate-model/",
        } <= checked


# ---------------------------------------------------------------------------
# Step 21: Legacy v1 API key endpoints removed
# ---------------------------------------------------------------------------


class TestLegacyApiKeyEndpointsRemoved:
    """The v1 key endpoints are retired; only /api/v1/api-keys (v2) mints keys."""

    def test_no_legacy_api_key_routes(self):
        router = _get_router()
        for route in router.routes:
            endpoint = getattr(route, "endpoint", None)
            endpoint_name = endpoint.__name__ if endpoint else ""
            if endpoint_name in ("generate_api_key", "revoke_legacy_api_key"):
                path = getattr(route, "path", "")
                pytest.fail(
                    f"{path} still maps to {endpoint_name}. "
                    "Legacy v1 API key endpoints should be removed."
                )


# ---------------------------------------------------------------------------
# Step 22: Signed URL Read Override
# ---------------------------------------------------------------------------


class TestSignedUrlReadOverride:
    """Verify generate_signed_url is in FILES_READ_OVERRIDES and wired to /files."""

    def test_generate_signed_url_in_files_read_overrides(self):
        assert "generate_signed_url" in FILES_READ_OVERRIDES
        assert "generate_original_signed_url" in FILES_READ_OVERRIDES

    def test_files_router_has_read_overrides(self):
        """The /files router mount should have FILES_READ_OVERRIDES wired."""
        router = _get_router()
        for route in router.routes:
            path = getattr(route, "path", "")
            if not path.startswith("/files"):
                continue
            if _route_has_dependency_named(route, "_resource_permission_dep"):
                for closure in route_dependency_closures(
                    route, "_resource_permission_dep"
                ):
                    val = closure.get("read_override_endpoints")
                    if isinstance(val, frozenset) and "generate_signed_url" in val:
                        return  # Found it
                pytest.fail(
                    "/files route has resource guard but no generate_signed_url override"
                )
        pytest.fail("No guarded /files route found")


# ---------------------------------------------------------------------------
# Step 23: /version Unauthenticated
# ---------------------------------------------------------------------------


class TestVersionEndpointPublic:
    """Verify /version is a public endpoint (no auth dependency)."""

    def test_version_has_no_auth_dependency(self):
        """GET /version should not require authentication."""
        app = _get_app()
        for route in app.routes:
            path = getattr(route, "path", "")
            if path == "/version":
                assert not _route_has_dependency_named(
                    route, "get_current_active_user"
                ), "/version should not require auth (get_current_active_user found)"
                return
        pytest.fail("/version endpoint not found in app routes")


# ---------------------------------------------------------------------------
# Step 24: Error Code Consistency
# ---------------------------------------------------------------------------


class TestScopeErrorCodeConsistency:
    """Verify scope violations use 'insufficient_scope' not 'insufficient_permission'."""

    def test_scope_errors_use_correct_code(self):
        """_require_api_key_scope_for_assistant should use 'insufficient_scope'."""
        eneo_src = _get_eneo_src_path()
        user_service_path = eneo_src / "users" / "user_service.py"
        source = user_service_path.read_text()

        # Find _require_api_key_scope_for_assistant function
        in_scope_fn = False
        scope_fn_indent = 0
        wrong_codes = []

        for i, line in enumerate(source.splitlines(), 1):
            stripped = line.lstrip()
            indent = len(line) - len(stripped)

            if "def _require_api_key_scope_for_assistant" in stripped:
                in_scope_fn = True
                scope_fn_indent = indent
                continue

            if in_scope_fn:
                # Function ends when we hit a line at same or lower indent (non-blank)
                if (
                    stripped
                    and not stripped.startswith("#")
                    and indent <= scope_fn_indent
                ):
                    break

                if 'code="insufficient_permission"' in stripped:
                    wrong_codes.append(i)

        assert not wrong_codes, (
            f"_require_api_key_scope_for_assistant uses 'insufficient_permission' "
            f"instead of 'insufficient_scope' at lines: {wrong_codes}"
        )


# ---------------------------------------------------------------------------
# Step 25: Limits Router Authentication
# ---------------------------------------------------------------------------


class TestLimitsRouterAuth:
    """Verify /limits requires authentication."""

    def test_limits_requires_user_context(self):
        """get_limits should use get_container(with_user=True)."""
        from eneo.limits.limit_router import get_limits

        sig = inspect.signature(get_limits)
        container_param = sig.parameters.get("container")
        assert container_param is not None, "get_limits missing container parameter"

        eneo_src = _get_eneo_src_path()
        source = (eneo_src / "limits" / "limit_router.py").read_text()
        assert "with_user=True" in source
        assert "with_upload_admission=True" in source
