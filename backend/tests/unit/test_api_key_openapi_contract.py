import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = ROOT / "specs" / "001-api-key-management" / "contracts" / "api-spec.json"


REQUIRED_PATHS = {
    "/api/v1/api-keys": {"get", "post"},
    "/api/v1/api-keys/{id}": {"get", "patch", "delete"},
    "/api/v1/api-keys/{id}/revoke": {"post"},
    "/api/v1/api-keys/{id}/rotate": {"post"},
    "/api/v1/api-keys/{id}/suspend": {"post"},
    "/api/v1/api-keys/{id}/reactivate": {"post"},
    "/api/v1/users/api-keys/": {"get", "post"},
    "/api/v1/assistants/{id}/api-keys/": {"get"},
    "/api/v1/admin/api-keys": {"get"},
    "/api/v1/admin/api-keys/{id}": {"get"},
    "/api/v1/admin/api-keys/{id}/suspend": {"post"},
    "/api/v1/admin/api-keys/{id}/reactivate": {"post"},
    "/api/v1/admin/api-keys/{id}/revoke": {"post"},
    "/api/v1/admin/api-key-policy": {"patch"},
}


SAMPLE_REQUIRED = [
    ("/api/v1/api-keys", "post"),
    ("/api/v1/api-keys", "get"),
    ("/api/v1/api-keys/{id}", "patch"),
    ("/api/v1/api-keys/{id}/revoke", "post"),
    ("/api/v1/admin/api-key-policy", "patch"),
]


def load_spec() -> dict:
    return json.loads(SPEC_PATH.read_text())


def test_openapi_paths_present():
    spec = load_spec()
    paths = spec.get("paths", {})

    for path, methods in REQUIRED_PATHS.items():
        assert path in paths, f"Missing path {path}"
        available = {method.lower() for method in paths[path].keys()}
        missing = {method.lower() for method in methods} - available
        assert not missing, f"Missing methods for {path}: {sorted(missing)}"


def test_api_key_schema_fields():
    spec = load_spec()
    api_key = spec["components"]["schemas"]["ApiKey"]
    props = api_key.get("properties", {})

    for field in ("created_at", "updated_at", "rotated_from_key_id"):
        assert field in props, f"Missing ApiKey.{field} in schema"


def test_code_samples_present():
    spec = load_spec()
    paths = spec.get("paths", {})

    for path, method in SAMPLE_REQUIRED:
        op = paths[path][method]
        samples = op.get("x-codeSamples")
        assert samples, f"Missing x-codeSamples for {method.upper()} {path}"
