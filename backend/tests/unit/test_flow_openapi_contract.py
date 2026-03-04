from __future__ import annotations

import pytest

from intric.server.main import get_application


@pytest.fixture(scope="module")
def openapi_spec() -> dict:
    app = get_application()
    return app.openapi()


REQUIRED_PATHS: dict[str, set[str]] = {
    "/api/v1/flows/{id}/input-policy/": {"get"},
    "/api/v1/flows/{id}/files/": {"post"},
    "/api/v1/flows/{id}/runs/": {"get", "post"},
    "/api/v1/flows/{id}/runs/{run_id}/": {"get"},
    "/api/v1/flows/{id}/runs/{run_id}/steps/": {"get"},
    "/api/v1/settings/flow-input-limits": {"get", "patch"},
}

REQUIRED_SCHEMAS = {
    "FlowInputPolicyPublic",
    "FlowRunStepPublic",
    "FlowInputLimitsPublic",
}

REQUIRED_ERROR_RESPONSES: dict[tuple[str, str], set[str]] = {
    (
        "/api/v1/flows/{id}/runs/",
        "post",
    ): {"403", "404", "422"},
    (
        "/api/v1/flows/{id}/files/",
        "post",
    ): {"400", "403", "404", "413", "415", "422"},
    (
        "/api/v1/flows/{id}/input-policy/",
        "get",
    ): {"403", "404"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/steps/",
        "get",
    ): {"403", "404"},
    (
        "/api/v1/settings/flow-input-limits",
        "patch",
    ): {"400", "403", "422"},
}


def test_openapi_flow_consumer_paths_present(openapi_spec: dict) -> None:
    paths = openapi_spec.get("paths", {})
    for path, methods in REQUIRED_PATHS.items():
        assert path in paths, f"Missing path {path}"
        available = {method.lower() for method in paths[path].keys()}
        missing = {method.lower() for method in methods} - available
        assert not missing, f"Missing methods for {path}: {sorted(missing)}"


def test_openapi_flow_consumer_operations_have_docs(openapi_spec: dict) -> None:
    paths = openapi_spec.get("paths", {})
    for path, methods in REQUIRED_PATHS.items():
        for method in methods:
            operation = paths[path][method.lower()]
            summary = operation.get("summary")
            description = operation.get("description")
            assert isinstance(summary, str) and summary.strip(), (
                f"{method.upper()} {path} is missing summary"
            )
            assert isinstance(description, str) and description.strip(), (
                f"{method.upper()} {path} is missing description"
            )


def test_openapi_flow_consumer_error_contracts(openapi_spec: dict) -> None:
    paths = openapi_spec.get("paths", {})
    for (path, method), expected_codes in REQUIRED_ERROR_RESPONSES.items():
        responses = paths[path][method].get("responses", {})
        missing = expected_codes - set(responses.keys())
        assert not missing, f"{method.upper()} {path} missing response codes: {sorted(missing)}"


def test_openapi_flow_consumer_schemas_present(openapi_spec: dict) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    missing = REQUIRED_SCHEMAS - set(schemas.keys())
    assert not missing, f"Missing OpenAPI schemas: {sorted(missing)}"


def test_openapi_flow_input_policy_schema_contains_consumer_hints(openapi_spec: dict) -> None:
    flow_input_policy = (
        openapi_spec.get("components", {})
        .get("schemas", {})
        .get("FlowInputPolicyPublic", {})
    )
    properties = flow_input_policy.get("properties", {})
    assert "max_files_per_run" in properties
    assert "recommended_run_payload" in properties
