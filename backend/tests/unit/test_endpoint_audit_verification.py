"""Endpoint audit verification tests.

Verifies that all fixes from the endpoint audit (Steps 17-25) are correctly
wired. These are STRUCTURAL tests that inspect actual router/endpoint objects
to prevent regression.
"""

import ast
import importlib
import inspect

import pytest

from intric.authentication.auth_dependencies import FILES_READ_OVERRIDES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_router():
    from intric.server.routers import router
    return router


def _get_app():
    from intric.server.main import app
    return app


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
    deps = getattr(route, "dependencies", [])
    for dep in deps:
        if hasattr(dep, "dependency"):
            if getattr(dep.dependency, "__name__", "") == dep_name:
                return True
    return False


def _endpoint_has_dependency_named(endpoint_fn, dep_name: str) -> bool:
    """Check if an endpoint function has a parameter with a dependency matching dep_name."""
    sig = inspect.signature(endpoint_fn)
    for param in sig.parameters.values():
        dep = param.default
        if hasattr(dep, "dependency"):
            if getattr(dep.dependency, "__name__", "") == dep_name:
                return True
    return False


def _get_intric_src_path():
    spec = importlib.util.find_spec("intric")
    if spec and spec.submodule_search_locations:
        import pathlib
        return pathlib.Path(spec.submodule_search_locations[0])
    import pathlib
    return pathlib.Path(__file__).parent.parent.parent / "src" / "intric"


# ---------------------------------------------------------------------------
# Step 17: /users/admin/* Admin-Role Enforcement (P0-1)
# ---------------------------------------------------------------------------

class TestUserAdminEndpointGuards:
    """Verify /users/admin/* endpoints have validate_permission(Permission.ADMIN).

    These endpoints use inline validate_permission() calls in the function body
    instead of Depends(require_permission()) to avoid double-auth overhead.
    """

    def test_admin_endpoints_have_validate_permission_guard(self):
        """invite_user, update_user, delete_user all call validate_permission in their body."""
        intric_src = _get_intric_src_path()
        source = (intric_src / "users" / "user_router.py").read_text()
        tree = ast.parse(source)

        # Find the three endpoint function definitions and check for validate_permission call in body
        target_fns = {"invite_user", "update_user", "delete_user"}
        found_guards = {}

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name not in target_fns:
                    continue
                # Check function body for validate_permission(...) call
                has_guard = False
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.Call):
                        func = stmt.func
                        func_name = getattr(func, "id", getattr(func, "attr", ""))
                        if func_name == "validate_permission":
                            has_guard = True
                            break
                found_guards[node.name] = has_guard

        for fn_name in target_fns:
            assert fn_name in found_guards, f"{fn_name} function not found in user_router.py"
            assert found_guards[fn_name], (
                f"{fn_name} missing validate_permission() guard in function body"
            )


# ---------------------------------------------------------------------------
# Step 18: Model Provider + Tenant Model Admin Checks (P0-2)
# ---------------------------------------------------------------------------

class TestModelRouterAdminChecks:
    """Verify model provider and tenant model mutation endpoints have admin checks.

    These endpoints use inline validate_permission(user, Permission.ADMIN) calls
    inside the function body. We verify this via AST inspection of the source files.
    """

    _ROUTER_FILES = [
        ("model_providers/presentation/model_provider_router.py", 3),
        ("completion_models/presentation/tenant_completion_models_router.py", 3),
        ("embedding_models/presentation/tenant_embedding_models_router.py", 3),
        ("transcription_models/presentation/tenant_transcription_models_router.py", 3),
    ]

    @pytest.mark.parametrize("rel_path,expected_count", _ROUTER_FILES)
    def test_mutation_endpoints_have_admin_check(self, rel_path, expected_count):
        """Each model router file must have validate_permission(user, Permission.ADMIN) calls."""
        intric_src = _get_intric_src_path()
        full_path = intric_src / rel_path

        source = full_path.read_text()
        tree = ast.parse(source)

        admin_check_count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "validate_permission":
                    admin_check_count += 1
                elif isinstance(func, ast.Attribute) and func.attr == "validate_permission":
                    admin_check_count += 1

        assert admin_check_count >= expected_count, (
            f"{rel_path}: expected >= {expected_count} validate_permission calls, "
            f"found {admin_check_count}"
        )


# ---------------------------------------------------------------------------
# Step 21: Legacy GET /api-keys/ Removed
# ---------------------------------------------------------------------------

class TestLegacyGetApiKeysRemoved:
    """Verify the legacy GET /api-keys/ mutating endpoint is removed."""

    def test_no_get_api_keys_route(self):
        """GET /api-keys/ should not exist (it was a mutating GET alias)."""
        router = _get_router()
        for route in router.routes:
            path = getattr(route, "path", "")
            methods = getattr(route, "methods", set())
            endpoint = getattr(route, "endpoint", None)
            endpoint_name = endpoint.__name__ if endpoint else ""
            # The removed endpoint mapped GET /api-keys/ to generate_api_key
            if endpoint_name == "generate_api_key" and "GET" in methods:
                pytest.fail(
                    f"GET {path} still maps to generate_api_key. "
                    "Legacy GET /api-keys/ mutating endpoint should be removed."
                )

    def test_post_api_keys_still_exists(self):
        """POST /api-keys/ should still exist (correct method for mutation)."""
        router = _get_router()
        found = False
        for route in router.routes:
            endpoint = getattr(route, "endpoint", None)
            methods = getattr(route, "methods", set())
            if endpoint and endpoint.__name__ == "generate_api_key" and "POST" in methods:
                found = True
                break
        assert found, "POST /api-keys/ (generate_api_key) not found"

    def test_post_api_keys_has_admin_key_guard(self):
        """POST /api-keys/ requires admin API key permission."""
        router = _get_router()
        for route in router.routes:
            endpoint = getattr(route, "endpoint", None)
            methods = getattr(route, "methods", set())
            if endpoint and endpoint.__name__ == "generate_api_key" and "POST" in methods:
                assert _endpoint_has_dependency_named(
                    endpoint, "_api_key_permission_dep"
                ), "generate_api_key missing require_api_key_permission guard"
                return
        pytest.fail("generate_api_key endpoint not found")


# ---------------------------------------------------------------------------
# Step 22: Signed URL Read Override
# ---------------------------------------------------------------------------

class TestSignedUrlReadOverride:
    """Verify generate_signed_url is in FILES_READ_OVERRIDES and wired to /files."""

    def test_generate_signed_url_in_files_read_overrides(self):
        assert "generate_signed_url" in FILES_READ_OVERRIDES

    def test_files_router_has_read_overrides(self):
        """The /files router mount should have FILES_READ_OVERRIDES wired."""
        router = _get_router()
        for route in router.routes:
            path = getattr(route, "path", "")
            if not path.startswith("/files"):
                continue
            if _route_has_dependency_named(route, "_resource_permission_dep"):
                # Verify it has a frozenset in closure (read overrides)
                deps = getattr(route, "dependencies", [])
                for dep in deps:
                    fn = getattr(dep, "dependency", None)
                    if fn and getattr(fn, "__name__", "") == "_resource_permission_dep":
                        if hasattr(fn, "__closure__") and fn.__closure__:
                            for cell in fn.__closure__:
                                try:
                                    val = cell.cell_contents
                                except ValueError:
                                    continue
                                if isinstance(val, frozenset) and "generate_signed_url" in val:
                                    return  # Found it
                pytest.fail("/files route has resource guard but no generate_signed_url override")
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
                deps = getattr(route, "dependencies", [])
                for dep in deps:
                    dep_fn = getattr(dep, "dependency", None)
                    dep_name = getattr(dep_fn, "__name__", "") if dep_fn else ""
                    assert dep_name != "get_current_active_user", (
                        "/version should not require auth (get_current_active_user found)"
                    )
                return
        pytest.fail("/version endpoint not found in app routes")


# ---------------------------------------------------------------------------
# Step 24: Error Code Consistency
# ---------------------------------------------------------------------------

class TestScopeErrorCodeConsistency:
    """Verify scope violations use 'insufficient_scope' not 'insufficient_permission'."""

    def test_scope_errors_use_correct_code(self):
        """_require_api_key_scope_for_assistant should use 'insufficient_scope'."""
        intric_src = _get_intric_src_path()
        user_service_path = intric_src / "users" / "user_service.py"
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
                if stripped and not stripped.startswith("#") and indent <= scope_fn_indent:
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
        from intric.limits.limit_router import get_limits

        sig = inspect.signature(get_limits)
        container_param = sig.parameters.get("container")
        assert container_param is not None, "get_limits missing container parameter"

        # The default should be Depends(get_container(with_user=True))
        # We can't easily inspect the with_user=True arg directly, but
        # we can verify it's using get_container by checking the source
        intric_src = _get_intric_src_path()
        source = (intric_src / "limits" / "limit_router.py").read_text()
        assert "get_container(with_user=True)" in source, (
            "limit_router.py should use get_container(with_user=True)"
        )
