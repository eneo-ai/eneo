from __future__ import annotations

from collections.abc import Iterator

import pytest

from intric.flow_packages.domain.flow_package_errors import FlowPackageExportErrorCode
from intric.main.models import GeneralError
from intric.server.main import get_application

FLOW_PACKAGE_OPERATIONS: dict[tuple[str, str], str] = {
    ("/api/v1/flow-packages/validate/", "post"): "validate_flow_package",
    (
        "/api/v1/spaces/{id}/flow-packages/import-plan/",
        "post",
    ): "create_flow_package_import_plan",
    (
        "/api/v1/spaces/{id}/flow-packages/imports/",
        "post",
    ): "import_flow_package_as_draft",
    ("/api/v1/flows/{id}/package-exports/", "post"): "export_flow_package",
}


@pytest.fixture(scope="module")
def openapi_spec() -> dict:
    app = get_application()
    return app.openapi()


def test_openapi_flow_package_operations_are_explicit(
    openapi_spec: dict,
) -> None:
    live_operations = {
        (path, method): operation.get("operationId")
        for path, method, operation in _iter_flow_package_operations(openapi_spec)
    }

    assert live_operations == FLOW_PACKAGE_OPERATIONS


def test_openapi_flow_package_operations_have_docs(openapi_spec: dict) -> None:
    for path, method in FLOW_PACKAGE_OPERATIONS:
        operation = _operation(openapi_spec, path, method)
        assert operation.get("tags") == ["flow-packages"]
        assert isinstance(operation.get("summary"), str) and operation["summary"]
        description = operation.get("description")
        assert isinstance(description, str) and len(description.strip()) >= 150


def test_openapi_flow_package_uploads_use_binary_package_file(
    openapi_spec: dict,
) -> None:
    upload_operations = {
        ("/api/v1/flow-packages/validate/", "post"),
        ("/api/v1/spaces/{id}/flow-packages/import-plan/", "post"),
    }
    for path, method in upload_operations:
        request_schema = (
            _operation(openapi_spec, path, method)
            .get("requestBody", {})
            .get("content", {})
            .get("multipart/form-data", {})
            .get("schema", {})
        )
        resolved = _resolve_component_ref(openapi_spec, request_schema)
        properties = resolved.get("properties", {})
        required = set(resolved.get("required", []))

        assert "package_file" in required
        assert properties.get("package_file", {}).get("type") == "string"
        assert properties.get("package_file", {}).get("format") == "binary"


def test_openapi_flow_package_export_request_uses_manifest_metadata(
    openapi_spec: dict,
) -> None:
    operation = _operation(
        openapi_spec,
        "/api/v1/flows/{id}/package-exports/",
        "post",
    )
    request_schema = (
        operation.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )
    resolved = _resolve_component_ref(openapi_spec, request_schema)

    assert resolved.get("title") == "FlowPackageExportRequest"
    assert set(resolved.get("required", [])) == {
        "package_id",
        "package_version",
        "name",
    }
    assert "schema_version" not in resolved.get("properties", {})


def test_openapi_flow_package_import_request_uses_typed_json_bindings(
    openapi_spec: dict,
) -> None:
    operation = _operation(
        openapi_spec,
        "/api/v1/spaces/{id}/flow-packages/imports/",
        "post",
    )
    content = operation.get("requestBody", {}).get("content", {})
    assert set(content) == {"application/json"}

    resolved = _resolve_component_ref(
        openapi_spec,
        content["application/json"].get("schema", {}),
    )
    properties = resolved.get("properties", {})

    assert resolved.get("title") == "FlowPackageImportRequest"
    assert "package_base64" in set(resolved.get("required", []))
    assert properties.get("package_base64", {}).get("type") == "string"
    selected_bindings = properties.get("selected_bindings", {})
    assert selected_bindings.get("type") == "array"
    binding_item = _resolve_component_ref(
        openapi_spec,
        selected_bindings.get("items", {}),
    )
    assert binding_item.get("title") == "FlowPackageImportResourceBindingRequest"
    slot_ref = _resolve_component_ref(
        openapi_spec,
        binding_item.get("properties", {}).get("slot_ref", {}),
    )
    assert slot_ref.get("title") == "FlowPackageImportResourceSlotRefRequest"


def test_openapi_flow_package_export_returns_binary_package(
    openapi_spec: dict,
) -> None:
    response_content = (
        _operation(openapi_spec, "/api/v1/flows/{id}/package-exports/", "post")
        .get("responses", {})
        .get("200", {})
        .get("content", {})
    )
    package_schema = response_content.get(
        "application/vnd.eneo.flow-package+zip",
        {},
    ).get("schema", {})

    assert package_schema == {"type": "string", "format": "binary"}


def test_openapi_flow_package_error_responses_are_typed(
    openapi_spec: dict,
) -> None:
    expected_statuses = {
        ("/api/v1/flow-packages/validate/", "post"): {"400", "403", "413"},
        (
            "/api/v1/spaces/{id}/flow-packages/import-plan/",
            "post",
        ): {"400", "403", "404", "413"},
        (
            "/api/v1/spaces/{id}/flow-packages/imports/",
            "post",
        ): {"400", "403", "404", "413"},
        ("/api/v1/flows/{id}/package-exports/", "post"): {
            "400",
            "403",
            "404",
            "413",
        },
    }

    for route_key, status_codes in expected_statuses.items():
        path, method = route_key
        responses = _operation(openapi_spec, path, method).get("responses", {})
        for status_code in status_codes:
            schema = (
                responses.get(status_code, {})
                .get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
            resolved = _resolve_component_ref(openapi_spec, schema)
            assert resolved.get("title") == GeneralError.__name__


def test_openapi_flow_package_error_examples_are_actionable(
    openapi_spec: dict,
) -> None:
    validate_responses = _operation(
        openapi_spec,
        "/api/v1/flow-packages/validate/",
        "post",
    ).get("responses", {})
    import_plan_responses = _operation(
        openapi_spec,
        "/api/v1/spaces/{id}/flow-packages/import-plan/",
        "post",
    ).get("responses", {})
    import_responses = _operation(
        openapi_spec,
        "/api/v1/spaces/{id}/flow-packages/imports/",
        "post",
    ).get("responses", {})
    export_responses = _operation(
        openapi_spec,
        "/api/v1/flows/{id}/package-exports/",
        "post",
    ).get("responses", {})

    zip_example = _examples(validate_responses, "400")["zip_unsafe"]["value"]
    assert zip_example["code"] == "flow_package_zip_unsafe"
    assert zip_example["context"] == {"reason": "bad_zip"}
    package_error_codes = {
        example["value"]["code"]
        for example in _examples(validate_responses, "400").values()
    }
    assert {
        "flow_package_checksum_mismatch",
        "flow_package_local_resource_refs_not_portable",
        "flow_package_manifest_invalid",
        "flow_package_kind_unsupported",
        "flow_package_schema_unsupported",
        "flow_package_zip_unsafe",
    }.issubset(package_error_codes)

    too_large_example = _examples(validate_responses, "413")["file_too_large"]["value"]
    assert too_large_example["code"] == "flow_package_file_too_large"
    assert "max_package_upload_bytes" in too_large_example["context"]
    assert {
        "file_size_bytes",
        "file_size_human",
        "max_size_bytes",
        "max_size_human",
    } <= set(too_large_example["details"])

    scope_example = _examples(import_plan_responses, "403")["api_key_scope"]["value"]
    assert scope_example["code"] == "insufficient_scope"
    assert scope_example["context"] == {"auth_layer": "api_key_scope"}

    import_bad_request_codes = {
        example["value"]["code"]
        for example in _examples(import_responses, "400").values()
    }
    assert {
        "duplicate_slot_binding",
        "flow_package_base64_invalid",
        "flow_package_import_missing_required_resource_binding",
        "flow_package_import_mcp_manual_setup_required",
        "flow_package_import_selected_model_ineligible",
        "flow_package_import_unavailable_local_resource",
        "transcription_model_required",
    }.issubset(import_bad_request_codes)

    export_bad_request_codes = {
        example["value"]["code"]
        for example in _examples(export_responses, "400").values()
    }
    assert export_bad_request_codes == {
        code.value
        for code in FlowPackageExportErrorCode
        if code is not FlowPackageExportErrorCode.PACKAGE_BYTES_TOO_LARGE
    }

    export_too_large = _examples(export_responses, "413")["package_too_large"]["value"]
    assert (
        export_too_large["code"]
        == FlowPackageExportErrorCode.PACKAGE_BYTES_TOO_LARGE.value
    )


def test_openapi_flow_package_response_schemas_are_public_contracts(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    validation_schema = schemas.get("FlowPackageValidationPublic", {})
    plan_schema = schemas.get("FlowPackageImportPlan", {})
    import_schema = schemas.get("FlowPackageImportPublic", {})

    assert validation_schema.get("additionalProperties") is False
    assert set(validation_schema.get("required", [])) == {
        "package_id",
        "package_version",
        "package_kind",
        "payload_schema",
        "name",
        "description",
        "content_checksum",
        "spec_hash",
        "steps_count",
        "requirements_count",
        "requirements_by_kind",
    }
    assert (
        validation_schema.get("example", {})
        .get("requirements_by_kind", {})
        .get("model")
        == 1
    )

    assert plan_schema.get("additionalProperties") is False
    assert {
        "package_kind",
        "payload_schema",
        "package_summary",
    } <= set(plan_schema.get("required", []))
    summary_schema = _resolve_component_ref(
        openapi_spec,
        plan_schema.get("properties", {}).get("package_summary", {}),
    )
    assert summary_schema.get("title") == "FlowPackageImportPlanSummary"
    assert set(summary_schema.get("required", [])) == {
        "name",
        "description",
        "spec_hash",
        "steps_count",
        "requirements_count",
        "requirements_by_kind",
    }
    plan_properties = plan_schema.get("properties", {})
    for computed_plan_field in ("can_install_as_draft", "can_publish_after_import"):
        assert computed_plan_field in plan_properties
        assert computed_plan_field in plan_schema.get("required", [])
        assert plan_properties.get(computed_plan_field, {}).get("readOnly") is True

    assert import_schema.get("additionalProperties") is False
    assert set(import_schema.get("required", [])) == {
        "import_id",
        "flow_id",
        "flow_name",
        "package_id",
        "package_version",
        "content_checksum",
        "steps_created",
        "resource_bindings_count",
    }

    status_schema = schemas.get("FlowPackageImportPlanStatus", {})
    status_values = set(status_schema.get("enum", []))
    assert "resolved_compatible" not in status_values
    assert "manual_setup_required" in status_values
    assert "unsupported" in status_values
    model_resolution_schema = schemas.get("FlowPackageModelDependencyResolution", {})
    assert "install_blocks" in model_resolution_schema.get("required", [])
    assert "selection_required_for_install" in model_resolution_schema.get(
        "required", []
    )
    assert "auto_select_allowed" in model_resolution_schema.get("required", [])
    assert "policy_status" in model_resolution_schema.get("required", [])


def test_openapi_flow_package_import_plan_preserves_discriminator(
    openapi_spec: dict,
) -> None:
    plan_schema = (
        openapi_spec.get("components", {})
        .get("schemas", {})
        .get("FlowPackageImportPlan", {})
    )
    dependency_items = (
        plan_schema.get("properties", {})
        .get("dependency_resolutions", {})
        .get("items", {})
    )
    discriminator = dependency_items.get("discriminator", {})

    assert discriminator.get("propertyName") == "kind"
    assert set(discriminator.get("mapping", {}).keys()) == {
        "knowledge",
        "mcp_tool",
        "model",
        "template_asset",
    }


def _iter_flow_package_operations(
    openapi_spec: dict,
) -> Iterator[tuple[str, str, dict]]:
    for path, methods in openapi_spec.get("paths", {}).items():
        if not _is_flow_package_path(path):
            continue
        for method, operation in methods.items():
            if method in {"delete", "get", "patch", "post", "put"} and isinstance(
                operation,
                dict,
            ):
                yield path, method, operation


def _is_flow_package_path(path: str) -> bool:
    return (
        path.startswith("/api/v1/flow-packages/")
        or path.startswith("/api/v1/spaces/{id}/flow-packages/")
        or path.startswith("/api/v1/flows/{id}/package-exports/")
    )


def _operation(openapi_spec: dict, path: str, method: str) -> dict:
    operation = openapi_spec.get("paths", {}).get(path, {}).get(method)
    assert isinstance(operation, dict), f"Missing OpenAPI operation {method} {path}"
    return operation


def _resolve_component_ref(openapi_spec: dict, schema: dict) -> dict:
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema

    prefix = "#/components/schemas/"
    if not ref.startswith(prefix):
        pytest.fail(f"Unsupported OpenAPI $ref path: {ref}")

    component_name = ref.removeprefix(prefix)
    component = (
        openapi_spec.get("components", {}).get("schemas", {}).get(component_name)
    )
    assert isinstance(component, dict), (
        f"Missing OpenAPI component schema: {component_name}"
    )
    return component


def _examples(responses: dict, status_code: str) -> dict:
    examples = (
        responses.get(status_code, {})
        .get("content", {})
        .get("application/json", {})
        .get("examples", {})
    )
    assert isinstance(examples, dict)
    return examples
