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
    "/api/v1/admin/api-keys/lookup": {"post"},
    "/api/v1/admin/api-keys/{id}": {"get", "patch"},
    "/api/v1/admin/api-keys/{id}/usage": {"get"},
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


def test_resource_permissions_document_flow_runtime_review_levels(openapi_spec: dict):
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    properties = schemas["ResourcePermissions"].get("properties", {})

    flows_description = properties["flows"].get("description", "")
    assert "published flows" in flows_description
    assert "run contracts" in flows_description
    assert "active human-review checkpoints" in flows_description
    assert "create published-flow runs" in flows_description
    assert "edit, approve, reject, or resume human-review checkpoints" in flows_description
    assert "runs created by that same API key" in flows_description

    evidence_description = properties["flow_evidence"].get("description", "")
    assert "separate from `flows`" in evidence_description
    assert "does not grant run creation" in evidence_description
    assert "human-review checkpoint edit" in evidence_description
