from __future__ import annotations

import pytest

from intric.server.main import get_application


@pytest.fixture(scope="module")
def openapi_spec() -> dict:
    app = get_application()
    return app.openapi()


def _resolve_component_ref(openapi_spec: dict, schema: dict) -> dict:
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema

    prefix = "#/components/schemas/"
    if not ref.startswith(prefix):
        pytest.fail(f"Unsupported OpenAPI $ref path: {ref}")

    component_name = ref.removeprefix(prefix)
    component = (
        openapi_spec.get("components", {})
        .get("schemas", {})
        .get(component_name)
    )
    assert isinstance(component, dict), f"Missing OpenAPI component schema: {component_name}"
    return component


def _extract_enum_values(openapi_spec: dict, schema: dict) -> set[str]:
    resolved = _resolve_component_ref(openapi_spec, schema)
    if "enum" in resolved:
        return {str(item) for item in resolved["enum"]}

    values: set[str] = set()
    for composition_key in ("anyOf", "oneOf", "allOf"):
        options = resolved.get(composition_key, [])
        if not isinstance(options, list):
            continue
        for option in options:
            if not isinstance(option, dict):
                continue
            option_schema = _resolve_component_ref(openapi_spec, option)
            enum_values = option_schema.get("enum", [])
            if isinstance(enum_values, list):
                values.update(str(item) for item in enum_values)
    return values


REQUIRED_PATHS: dict[str, set[str]] = {
    "/api/v1/flows/{id}/input-policy/": {"get"},
    "/api/v1/flows/{id}/files/": {"post"},
    "/api/v1/flows/{id}/runs/": {"get", "post"},
    "/api/v1/flows/{id}/runs/{run_id}/": {"get"},
    "/api/v1/flows/{id}/runs/{run_id}/cancel/": {"post"},
    "/api/v1/flows/{id}/runs/{run_id}/redispatch/": {"post"},
    "/api/v1/flows/{id}/runs/{run_id}/evidence/": {"get"},
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
    ): {"400", "403", "404", "422"},
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
        "/api/v1/flows/{id}/runs/{run_id}/cancel/",
        "post",
    ): {"403", "404", "422"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/redispatch/",
        "post",
    ): {"403", "404", "422"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/evidence/",
        "get",
    ): {"403", "404", "422"},
    (
        "/api/v1/settings/flow-input-limits",
        "patch",
    ): {"400", "403", "422"},
}

REQUIRED_TYPED_ERROR_CODES: dict[tuple[str, str], set[str]] = {
    (
        "/api/v1/flows/{id}/runs/",
        "post",
    ): {"400", "403", "404"},
    (
        "/api/v1/flows/{id}/files/",
        "post",
    ): {"400", "403", "404", "413", "415"},
    (
        "/api/v1/flows/{id}/input-policy/",
        "get",
    ): {"403", "404"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/steps/",
        "get",
    ): {"403", "404"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/cancel/",
        "post",
    ): {"403", "404"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/redispatch/",
        "post",
    ): {"403", "404"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/evidence/",
        "get",
    ): {"403", "404"},
}


def test_openapi_flow_consumer_paths_present(openapi_spec: dict) -> None:
    paths = openapi_spec.get("paths", {})
    for path, methods in REQUIRED_PATHS.items():
        assert path in paths, f"Missing path {path}"
        available = {method.lower() for method in paths[path].keys()}
        missing = {method.lower() for method in methods} - available
        assert not missing, f"Missing methods for {path}: {sorted(missing)}"


def test_openapi_legacy_flow_run_paths_absent(openapi_spec: dict) -> None:
    paths = openapi_spec.get("paths", {})
    legacy_paths = sorted(path for path in paths if path.startswith("/api/v1/flow-runs"))
    assert not legacy_paths, f"Legacy flow-run paths must be absent: {legacy_paths}"


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


def test_openapi_flow_run_control_paths_include_flow_and_run_ids(openapi_spec: dict) -> None:
    paths = openapi_spec.get("paths", {})
    targets = (
        ("/api/v1/flows/{id}/runs/{run_id}/cancel/", "post"),
        ("/api/v1/flows/{id}/runs/{run_id}/redispatch/", "post"),
        ("/api/v1/flows/{id}/runs/{run_id}/evidence/", "get"),
    )
    for path, method in targets:
        operation = paths[path][method]
        params = operation.get("parameters", [])
        names = {param.get("name") for param in params if isinstance(param, dict)}
        assert {"id", "run_id"} <= names, (
            f"{method.upper()} {path} must declare path params id and run_id"
        )


def test_openapi_flow_consumer_error_contracts(openapi_spec: dict) -> None:
    paths = openapi_spec.get("paths", {})
    for (path, method), expected_codes in REQUIRED_ERROR_RESPONSES.items():
        responses = paths[path][method].get("responses", {})
        missing = expected_codes - set(responses.keys())
        assert not missing, f"{method.upper()} {path} missing response codes: {sorted(missing)}"


def test_openapi_flow_consumer_typed_error_schemas(openapi_spec: dict) -> None:
    paths = openapi_spec.get("paths", {})
    for (path, method), expected_codes in REQUIRED_TYPED_ERROR_CODES.items():
        responses = paths[path][method].get("responses", {})
        for code in expected_codes:
            payload = responses.get(code, {})
            content = payload.get("content", {})
            app_json = content.get("application/json", {})
            schema = app_json.get("schema", {})
            resolved = _resolve_component_ref(openapi_spec, schema)
            assert schema, f"{method.upper()} {path} {code} must include JSON schema"
            assert resolved.get("title") == "GeneralError", (
                f"{method.upper()} {path} {code} should use GeneralError schema"
            )


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


def test_openapi_flow_input_policy_example_matches_runtime_audio_defaults(
    openapi_spec: dict,
) -> None:
    example = (
        openapi_spec.get("components", {})
        .get("schemas", {})
        .get("FlowInputPolicyPublic", {})
        .get("example", {})
    )
    assert isinstance(example, dict)
    assert example.get("input_type") == "audio"
    assert example.get("max_files_per_run") == 10


def test_openapi_flow_input_policy_schema_exposes_enum_constraints(
    openapi_spec: dict,
) -> None:
    schema = (
        openapi_spec.get("components", {})
        .get("schemas", {})
        .get("FlowInputPolicyPublic", {})
    )
    properties = schema.get("properties", {})

    input_type_values = _extract_enum_values(openapi_spec, properties.get("input_type", {}))
    input_source_values = _extract_enum_values(openapi_spec, properties.get("input_source", {}))

    assert {"text", "json", "image", "audio", "document", "file", "any"} <= input_type_values
    assert {
        "flow_input",
        "previous_step",
        "all_previous_steps",
        "http_get",
        "http_post",
    } <= input_source_values


def test_openapi_flow_run_create_schema_has_request_example(openapi_spec: dict) -> None:
    schema = (
        openapi_spec.get("components", {})
        .get("schemas", {})
        .get("FlowRunCreateRequest", {})
    )
    example = schema.get("example")
    assert isinstance(example, dict), "FlowRunCreateRequest schema must include an example"
    assert "file_ids" in example
    assert "input_payload_json" in example


def test_openapi_flow_run_create_example_shape_is_consumer_valid(openapi_spec: dict) -> None:
    schema = (
        openapi_spec.get("components", {})
        .get("schemas", {})
        .get("FlowRunCreateRequest", {})
    )
    example = schema.get("example", {})
    assert isinstance(example, dict), "FlowRunCreateRequest example must be a JSON object"
    assert set(example.keys()) <= {"file_ids", "input_payload_json"}

    file_ids = example.get("file_ids")
    assert isinstance(file_ids, list), "FlowRunCreateRequest.example.file_ids must be a list"
    assert all(isinstance(item, str) and item.strip() for item in file_ids)

    input_payload_json = example.get("input_payload_json")
    assert isinstance(input_payload_json, dict), (
        "FlowRunCreateRequest.example.input_payload_json must be a JSON object"
    )


def test_openapi_flow_step_create_schema_exposes_enum_constraints(openapi_spec: dict) -> None:
    schema = (
        openapi_spec.get("components", {})
        .get("schemas", {})
        .get("FlowStepCreateRequest", {})
    )
    properties = schema.get("properties", {})
    for field in ("input_source", "input_type", "output_mode", "output_type", "mcp_policy"):
        field_schema = properties.get(field, {})
        enum_values = _extract_enum_values(openapi_spec, field_schema)
        assert enum_values, f"{field} must include enum-constrained OpenAPI values"


def test_openapi_flow_step_create_enum_values_match_contract(openapi_spec: dict) -> None:
    schema = (
        openapi_spec.get("components", {})
        .get("schemas", {})
        .get("FlowStepCreateRequest", {})
    )
    properties = schema.get("properties", {})
    expected = {
        "input_source": {
            "flow_input",
            "previous_step",
            "all_previous_steps",
            "http_get",
            "http_post",
        },
        "input_type": {"text", "json", "image", "audio", "document", "file", "any"},
        "output_mode": {"pass_through", "http_post", "transcribe_only"},
        "output_type": {"text", "json", "pdf", "docx"},
        "mcp_policy": {"inherit", "restricted"},
    }
    for field, expected_values in expected.items():
        enum_values = _extract_enum_values(openapi_spec, properties.get(field, {}))
        missing = expected_values - enum_values
        assert not missing, f"{field} missing enum values: {sorted(missing)}"


def test_openapi_flow_file_upload_multipart_schema_uses_upload_file_field(
    openapi_spec: dict,
) -> None:
    request_schema = (
        openapi_spec.get("paths", {})
        .get("/api/v1/flows/{id}/files/", {})
        .get("post", {})
        .get("requestBody", {})
        .get("content", {})
        .get("multipart/form-data", {})
        .get("schema", {})
    )
    resolved = _resolve_component_ref(openapi_spec, request_schema)
    properties = resolved.get("properties", {})
    required = set(resolved.get("required", []))
    assert "upload_file" in properties
    assert "upload_file" in required


def test_openapi_flow_consumer_request_response_schemas(openapi_spec: dict) -> None:
    run_post = (
        openapi_spec.get("paths", {})
        .get("/api/v1/flows/{id}/runs/", {})
        .get("post", {})
    )
    run_request_schema = (
        run_post.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )
    run_request_resolved = _resolve_component_ref(openapi_spec, run_request_schema)
    assert run_request_resolved.get("title") == "FlowRunCreateRequest"

    run_response_schema = (
        run_post.get("responses", {})
        .get("201", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )
    run_response_resolved = _resolve_component_ref(openapi_spec, run_response_schema)
    assert run_response_resolved.get("title") == "FlowRunPublic"

    files_post = (
        openapi_spec.get("paths", {})
        .get("/api/v1/flows/{id}/files/", {})
        .get("post", {})
    )
    files_request_schema = (
        files_post.get("requestBody", {})
        .get("content", {})
        .get("multipart/form-data", {})
        .get("schema", {})
    )
    files_request_resolved = _resolve_component_ref(openapi_spec, files_request_schema)
    upload_file_schema = files_request_resolved.get("properties", {}).get("upload_file", {})
    assert upload_file_schema.get("type") == "string"
    assert upload_file_schema.get("format") == "binary"


def test_openapi_flow_error_responses_include_general_error_examples(openapi_spec: dict) -> None:
    paths = openapi_spec.get("paths", {})
    for (path, method), status_codes in REQUIRED_TYPED_ERROR_CODES.items():
        responses = paths[path][method].get("responses", {})
        for status_code in status_codes:
            response = responses.get(status_code, {})
            app_json = response.get("content", {}).get("application/json", {})
            example = app_json.get("example", {})
            assert isinstance(example, dict), (
                f"{method.upper()} {path} {status_code} must include JSON example"
            )
            assert isinstance(example.get("message"), str) and example["message"].strip()
            assert "intric_error_code" in example
            assert isinstance(example.get("code"), str) and example["code"].strip()


def test_openapi_flow_file_upload_error_codes_are_machine_readable(openapi_spec: dict) -> None:
    responses = (
        openapi_spec.get("paths", {})
        .get("/api/v1/flows/{id}/files/", {})
        .get("post", {})
        .get("responses", {})
    )
    expected = {
        "400": "flow_input_upload_not_supported",
        "413": "file_too_large",
        "415": "unsupported_media_type",
    }
    for status_code, error_code in expected.items():
        example = (
            responses.get(status_code, {})
            .get("content", {})
            .get("application/json", {})
            .get("example", {})
        )
        assert example.get("code") == error_code, (
            f"/flows/{{id}}/files/ {status_code} should expose code '{error_code}'"
        )


def test_openapi_flow_run_operation_error_responses_use_general_error_model(
    openapi_spec: dict,
) -> None:
    paths = openapi_spec.get("paths", {})
    run_operation_codes: dict[tuple[str, str], tuple[str, ...]] = {
        ("/api/v1/flows/{id}/runs/{run_id}/cancel/", "post"): ("403", "404"),
        ("/api/v1/flows/{id}/runs/{run_id}/redispatch/", "post"): ("403", "404"),
        ("/api/v1/flows/{id}/runs/{run_id}/evidence/", "get"): ("403", "404"),
    }
    for (path, method), status_codes in run_operation_codes.items():
        responses = paths[path][method].get("responses", {})
        for status_code in status_codes:
            response = responses.get(status_code, {})
            schema = (
                response.get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
            resolved = _resolve_component_ref(openapi_spec, schema)
            assert resolved.get("title") == "GeneralError", (
                f"{method.upper()} {path} {status_code} must return GeneralError model"
            )
