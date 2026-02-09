from __future__ import annotations

import pytest

from intric.server.main import get_application


@pytest.fixture(scope="module")
def openapi_spec() -> dict:
    app = get_application()
    return app.openapi()


REQUIRED_PATHS = {
    "/api/v1/api-keys": {"get", "post"},
    "/api/v1/api-keys/{id}": {"get", "patch", "delete"},
    "/api/v1/api-keys/{id}/revoke": {"post"},
    "/api/v1/api-keys/{id}/rotate": {"post"},
    "/api/v1/api-keys/{id}/suspend": {"post"},
    "/api/v1/api-keys/{id}/reactivate": {"post"},
    "/api/v1/users/api-keys/": {"post"},
    "/api/v1/assistants/{id}/api-keys/": {"get"},
    "/api/v1/admin/api-keys": {"get"},
    "/api/v1/admin/api-keys/{id}": {"get"},
    "/api/v1/admin/api-keys/{id}/suspend": {"post"},
    "/api/v1/admin/api-keys/{id}/reactivate": {"post"},
    "/api/v1/admin/api-keys/{id}/revoke": {"post"},
    "/api/v1/admin/api-key-policy": {"patch"},
}

REQUIRED_SCHEMA_FIELDS = [
    "id",
    "key_prefix",
    "key_suffix",
    "name",
    "key_type",
    "permission",
    "scope_type",
    "state",
    "created_at",
    "updated_at",
    "rotated_from_key_id",
]


def test_openapi_paths_present(openapi_spec: dict):
    paths = openapi_spec.get("paths", {})

    for path, methods in REQUIRED_PATHS.items():
        assert path in paths, f"Missing path {path}"
        available = {method.lower() for method in paths[path].keys()}
        missing = {method.lower() for method in methods} - available
        assert not missing, f"Missing methods for {path}: {sorted(missing)}"


def test_api_key_schema_fields(openapi_spec: dict):
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    assert "ApiKeyV2" in schemas, "Missing ApiKeyV2 schema in OpenAPI components"

    props = schemas["ApiKeyV2"].get("properties", {})
    for field in REQUIRED_SCHEMA_FIELDS:
        assert field in props, f"Missing ApiKeyV2.{field} in schema"
