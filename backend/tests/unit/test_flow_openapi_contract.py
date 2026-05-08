from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from intric.flows.enums import RerunDependencyKind
from intric.server.main import get_application


@pytest.fixture(scope="module")
def openapi_spec() -> dict:
    app = get_application()
    return app.openapi()


@pytest.fixture(scope="module")
def flow_route_operations() -> dict[tuple[str, str], str]:
    app = get_application()
    operations: dict[tuple[str, str], str] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.path.startswith("/api/v1/flows"):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            operations[(route.path, method.lower())] = route.operation_id or ""
    return operations


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


def _extract_enum_values(openapi_spec: dict, schema: dict) -> set[str]:
    resolved = _resolve_component_ref(openapi_spec, schema)
    if "enum" in resolved:
        return {str(item) for item in resolved["enum"]}
    if "const" in resolved:
        return {str(resolved["const"])}

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


def _get_operation(openapi_spec: dict, path: str, method: str) -> dict:
    return openapi_spec.get("paths", {}).get(path, {}).get(method, {})


def _find_parameter(operation: dict, *, name: str, location: str) -> dict:
    for parameter in operation.get("parameters", []):
        if not isinstance(parameter, dict):
            continue
        if parameter.get("name") == name and parameter.get("in") == location:
            return parameter
    pytest.fail(
        f"Missing OpenAPI parameter {location}:{name} on operation "
        f"{operation.get('operationId', '<unknown>')}"
    )


REQUIRED_PATHS: dict[str, set[str]] = {
    "/api/v1/flows/{id}/published/": {"get"},
    "/api/v1/flows/{id}/input-policy/": {"get"},
    "/api/v1/flows/{id}/files/": {"post"},
    "/api/v1/flows/{id}/run-contract/": {"get"},
    "/api/v1/flows/{id}/steps/{step_id}/runtime-files/": {"post"},
    "/api/v1/flows/{id}/template-files/": {"post"},
    "/api/v1/flows/{id}/template-inspect/": {"get"},
    "/api/v1/flows/{id}/runs/": {"get", "post"},
    "/api/v1/flows/{id}/runs/{run_id}/": {"get"},
    "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/active/": {"get"},
    "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/": {"patch"},
    "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve/": {
        "post"
    },
    "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/": {
        "post"
    },
    "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/": {
        "post"
    },
    "/api/v1/flows/{id}/runs/{run_id}/cancel/": {"post"},
    "/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/rerun/": {"post"},
    "/api/v1/flows/{id}/runs/{run_id}/redispatch/": {"post"},
    "/api/v1/flows/{id}/runs/{run_id}/evidence/": {"get"},
    "/api/v1/flows/{id}/runs/{run_id}/evidence/export": {"get"},
    "/api/v1/flows/{id}/runs/{run_id}/steps/": {"get"},
    "/api/v1/flows/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/": {"post"},
    "/api/v1/settings/flow-input-limits": {"get", "patch"},
}

REQUIRED_SCHEMAS = {
    "FlowInputPolicyPublic",
    "FlowRuntimePublic",
    "FlowRunContractPublic",
    "FlowRunStepRerunRequest",
    "FlowRunStepRerunResponse",
    "FlowRunReviewCheckpointPublic",
    "FlowRunReviewCheckpointEditRequest",
    "FlowRunReviewCheckpointApproveRequest",
    "FlowRunReviewCheckpointRejectRequest",
    "FlowRunReviewCheckpointResumeRequest",
    "FlowRunReviewCheckpointResumeResponse",
    "FlowRunReviewCheckpointEvidencePublic",
    "FlowRunRerunOperationPublic",
    "FlowRunRerunInvalidatedStepPublic",
    "FlowRunEvidenceResponse",
    "FlowFinalOutputContractPublic",
    "FlowOutputDelivery",
    "FormFieldPublic",
    "FlowRuntimeInputContractPublic",
    "FlowReviewStepContractPublic",
    "FlowRunStepPublic",
    "FlowInputLimitsPublic",
    "FlowTemplateAssetPublic",
    "FlowTemplateReadinessPublic",
    "FlowTemplateInspectionPublic",
}

REQUIRED_OPERATION_IDS: dict[tuple[str, str], str] = {
    ("/api/v1/flows/", "post"): "create_flow",
    ("/api/v1/flows/", "get"): "list_flows",
    ("/api/v1/flows/{id}/", "get"): "get_flow",
    ("/api/v1/flows/{id}/published/", "get"): "get_published_flow_runtime",
    ("/api/v1/flows/{id}/", "patch"): "update_flow",
    ("/api/v1/flows/{id}/", "delete"): "delete_flow",
    ("/api/v1/flows/{id}/publish/", "post"): "publish_flow",
    ("/api/v1/flows/{id}/unpublish/", "post"): "unpublish_flow",
    ("/api/v1/flows/{id}/assistants/", "post"): "create_flow_assistant",
    ("/api/v1/flows/{id}/assistants/{assistant_id}/", "get"): "get_flow_assistant",
    ("/api/v1/flows/{id}/assistants/{assistant_id}/", "patch"): "update_flow_assistant",
    (
        "/api/v1/flows/{id}/assistants/{assistant_id}/",
        "delete",
    ): "delete_flow_assistant",
    ("/api/v1/flows/{id}/template-files/", "post"): "upload_flow_template_file",
    ("/api/v1/flows/{id}/template-inspect/", "get"): "inspect_flow_template",
    ("/api/v1/flows/{id}/run-contract/", "get"): "get_flow_run_contract",
    (
        "/api/v1/flows/{id}/steps/{step_id}/runtime-files/",
        "post",
    ): "upload_flow_runtime_file",
    ("/api/v1/flows/{id}/runs/", "post"): "create_flow_run",
    ("/api/v1/flows/{id}/runs/", "get"): "list_flow_runs_alias",
    ("/api/v1/flows/{id}/input-policy/", "get"): "get_flow_input_policy",
    ("/api/v1/flows/{id}/files/", "post"): "upload_flow_file",
    ("/api/v1/flows/{id}/runs/{run_id}/", "get"): "get_flow_run_alias",
    (
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/active/",
        "get",
    ): "get_active_flow_run_review_checkpoint",
    (
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/",
        "patch",
    ): "edit_flow_run_review_checkpoint",
    (
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve/",
        "post",
    ): "approve_flow_run_review_checkpoint",
    (
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/",
        "post",
    ): "reject_flow_run_review_checkpoint",
    (
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/",
        "post",
    ): "resume_flow_run_review_checkpoint",
    ("/api/v1/flows/{id}/runs/{run_id}/cancel/", "post"): "cancel_flow_run_alias",
    (
        "/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/rerun/",
        "post",
    ): "rerun_flow_run_step",
    (
        "/api/v1/flows/{id}/runs/{run_id}/redispatch/",
        "post",
    ): "redispatch_flow_run_alias",
    (
        "/api/v1/flows/{id}/runs/{run_id}/evidence/",
        "get",
    ): "get_flow_run_evidence_alias",
    (
        "/api/v1/flows/{id}/runs/{run_id}/evidence/export",
        "get",
    ): "export_flow_run_evidence_alias",
    ("/api/v1/flows/{id}/runs/{run_id}/steps/", "get"): "list_flow_run_steps",
    (
        "/api/v1/flows/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/",
        "post",
    ): "generate_flow_run_artifact_signed_url",
    ("/api/v1/flows/{id}/graph/", "get"): "get_flow_graph",
}

REQUIRED_ERROR_RESPONSES: dict[tuple[str, str], set[str]] = {
    (
        "/api/v1/flows/{id}/published/",
        "get",
    ): {"403", "404"},
    (
        "/api/v1/flows/{id}/run-contract/",
        "get",
    ): {"400", "403", "404"},
    (
        "/api/v1/flows/{id}/steps/{step_id}/runtime-files/",
        "post",
    ): {"400", "403", "404", "413", "415", "422"},
    (
        "/api/v1/flows/{id}/template-files/",
        "post",
    ): {"400", "403", "404", "413", "415", "422"},
    (
        "/api/v1/flows/{id}/template-inspect/",
        "get",
    ): {"400", "403", "404", "422"},
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
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/active/",
        "get",
    ): {"403", "404", "422"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/",
        "patch",
    ): {"400", "403", "404", "422"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve/",
        "post",
    ): {"400", "403", "404", "422"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/",
        "post",
    ): {"400", "403", "404", "422"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/",
        "post",
    ): {"400", "403", "404", "422"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/rerun/",
        "post",
    ): {"400", "403", "404", "422"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/redispatch/",
        "post",
    ): {"403", "404", "422"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/evidence/",
        "get",
    ): {"403", "404", "422"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/evidence/export",
        "get",
    ): {"400", "403", "404", "422", "503"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/",
        "post",
    ): {"403", "404", "410", "422"},
    (
        "/api/v1/settings/flow-input-limits",
        "patch",
    ): {"400", "403", "422"},
}

REQUIRED_TYPED_ERROR_CODES: dict[tuple[str, str], set[str]] = {
    (
        "/api/v1/flows/{id}/published/",
        "get",
    ): {"403", "404"},
    (
        "/api/v1/flows/{id}/run-contract/",
        "get",
    ): {"400", "403", "404"},
    (
        "/api/v1/flows/{id}/steps/{step_id}/runtime-files/",
        "post",
    ): {"400", "403", "404", "413", "415"},
    (
        "/api/v1/flows/{id}/template-files/",
        "post",
    ): {"400", "403", "404", "413", "415"},
    (
        "/api/v1/flows/{id}/template-inspect/",
        "get",
    ): {"400", "403", "404"},
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
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/active/",
        "get",
    ): {"403", "404"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/",
        "patch",
    ): {"400", "403", "404"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve/",
        "post",
    ): {"400", "403", "404"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/",
        "post",
    ): {"400", "403", "404"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/",
        "post",
    ): {"400", "403", "404"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/rerun/",
        "post",
    ): {"400", "403", "404"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/redispatch/",
        "post",
    ): {"403", "404"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/evidence/",
        "get",
    ): {"403", "404"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/evidence/export",
        "get",
    ): {"400", "403", "404", "503"},
    (
        "/api/v1/flows/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/",
        "post",
    ): {"403", "404", "410"},
}


def test_openapi_flow_consumer_paths_present(openapi_spec: dict) -> None:
    paths = openapi_spec.get("paths", {})
    for path, methods in REQUIRED_PATHS.items():
        assert path in paths, f"Missing path {path}"
        available = {method.lower() for method in paths[path].keys()}
        missing = {method.lower() for method in methods} - available
        assert not missing, f"Missing methods for {path}: {sorted(missing)}"


def test_openapi_flow_operation_ids_are_pinned(openapi_spec: dict) -> None:
    paths = openapi_spec.get("paths", {})
    for (path, method), expected_operation_id in REQUIRED_OPERATION_IDS.items():
        operation = paths[path][method]
        assert operation.get("operationId") == expected_operation_id


def test_flow_routes_register_pinned_operation_ids(
    flow_route_operations: dict[tuple[str, str], str],
) -> None:
    missing = sorted(
        f"{method.upper()} {path}"
        for path, method in REQUIRED_OPERATION_IDS
        if (path, method) not in flow_route_operations
    )
    assert missing == []

    for route_key, expected_operation_id in REQUIRED_OPERATION_IDS.items():
        assert flow_route_operations[route_key] == expected_operation_id


def test_openapi_legacy_flow_run_paths_absent(openapi_spec: dict) -> None:
    paths = openapi_spec.get("paths", {})
    legacy_paths = sorted(
        path for path in paths if path.startswith("/api/v1/flow-runs")
    )
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


def test_openapi_flow_run_control_paths_include_flow_and_run_ids(
    openapi_spec: dict,
) -> None:
    paths = openapi_spec.get("paths", {})
    targets = (
        ("/api/v1/flows/{id}/runs/{run_id}/cancel/", "post"),
        ("/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/active/", "get"),
        (
            "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/",
            "patch",
        ),
        (
            "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve/",
            "post",
        ),
        (
            "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/",
            "post",
        ),
        (
            "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/",
            "post",
        ),
        ("/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/rerun/", "post"),
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
        if "{step_id}" in path:
            assert "step_id" in names, (
                f"{method.upper()} {path} must declare path param step_id"
            )
        if "{checkpoint_id}" in path:
            assert "checkpoint_id" in names, (
                f"{method.upper()} {path} must declare path param checkpoint_id"
            )


def test_openapi_flow_consumer_error_contracts(openapi_spec: dict) -> None:
    paths = openapi_spec.get("paths", {})
    for (path, method), expected_codes in REQUIRED_ERROR_RESPONSES.items():
        responses = paths[path][method].get("responses", {})
        missing = expected_codes - set(responses.keys())
        assert not missing, (
            f"{method.upper()} {path} missing response codes: {sorted(missing)}"
        )


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


def test_openapi_flow_review_checkpoint_schema_is_public_contract(
    openapi_spec: dict,
) -> None:
    schema = (
        openapi_spec.get("components", {})
        .get("schemas", {})
        .get("FlowRunReviewCheckpointPublic", {})
    )
    properties = schema.get("properties", {})

    assert {
        "id",
        "tenant_id",
        "flow_id",
        "flow_run_id",
        "step_id",
        "step_order",
        "attempt_no",
        "state",
        "revision",
        "schema_version",
        "original_payload_json",
        "current_payload_json",
        "step_label",
        "review_mode",
        "output_type",
        "step_snapshot_available",
        "output_contract",
        "next_step_ids",
        "requester_user_id",
        "requester_principal_type",
        "decided_by_user_id",
        "decided_by_principal_type",
        "edited_at",
        "approved_at",
        "rejected_at",
        "resumed_at",
        "cancelled_at",
        "created_at",
        "updated_at",
    } <= set(properties)
    assert "resume_idempotency_key" not in properties


def test_openapi_flow_review_checkpoint_schema_documents_consumer_snapshot(
    openapi_spec: dict,
) -> None:
    schema = (
        openapi_spec.get("components", {})
        .get("schemas", {})
        .get("FlowRunReviewCheckpointPublic", {})
    )
    properties = schema.get("properties", {})

    snapshot_available = properties.get("step_snapshot_available", {})
    output_contract = properties.get("output_contract", {})
    assert snapshot_available.get("type") == "boolean"
    assert "external review UIs" in snapshot_available.get("description", "")
    assert "legacy checkpoints" in snapshot_available.get("description", "")
    assert "step_snapshot_available" in output_contract.get("description", "")
    assert "output contract" in output_contract.get("description", "").lower()


def test_openapi_run_contract_guides_consumer_forms_uploads_and_review(
    openapi_spec: dict,
) -> None:
    operation = _get_operation(
        openapi_spec,
        "/api/v1/flows/{id}/run-contract/",
        "get",
    )
    description = operation.get("description", "")
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    run_contract = schemas.get("FlowRunContractPublic", {}).get("properties", {})
    final_output = schemas.get("FlowFinalOutputContractPublic", {}).get("properties", {})
    form_field = schemas.get("FormFieldPublic", {}).get("properties", {})
    review_step = schemas.get("FlowReviewStepContractPublic", {}).get("properties", {})

    assert "step_inputs[step_id].file_ids" in description
    assert "terminal output type" in description
    assert "steps_requiring_review" in description
    assert "awaiting_review" in description
    assert "generated file download" in run_contract["final_output"]["description"]
    assert "artifact" in final_output["delivery"]["description"]
    assert "generated file download" in final_output["output_type"]["description"]
    assert "input_payload_json" in form_field["name"]["description"]
    assert "review screens" in run_contract["steps_requiring_review"]["description"]
    assert "Review behavior" in review_step["review_mode"]["description"]
    assert "output contract" in review_step["output_contract"]["description"]


def test_openapi_review_checkpoint_endpoint_docs_guide_human_in_loop_clients(
    openapi_spec: dict,
) -> None:
    active_operation = _get_operation(
        openapi_spec,
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/active/",
        "get",
    )
    edit_operation = _get_operation(
        openapi_spec,
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/",
        "patch",
    )
    resume_operation = _get_operation(
        openapi_spec,
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/",
        "post",
    )

    active_description = active_operation.get("description", "")
    edit_description = edit_operation.get("description", "")
    resume_description = resume_operation.get("description", "")

    assert "status` is `awaiting_review`" in active_description
    assert "step_snapshot_available" in active_description
    assert "without reading the mutable flow draft" in active_description
    assert "full corrected `current_payload_json`, not a patch" in edit_description
    assert "flow_review_stale_revision" in edit_description
    assert "202 Accepted" in resume_description
    assert "Idempotency-Key" in resume_description


def test_openapi_active_review_checkpoint_response_is_nullable(
    openapi_spec: dict,
) -> None:
    operation = _get_operation(
        openapi_spec,
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/active/",
        "get",
    )
    response_schema = (
        operation.get("responses", {})
        .get("200", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )
    options = response_schema.get("anyOf") or response_schema.get("oneOf") or []

    assert any(
        option.get("$ref") == "#/components/schemas/FlowRunReviewCheckpointPublic"
        for option in options
        if isinstance(option, dict)
    )
    assert any(
        option.get("type") == "null" for option in options if isinstance(option, dict)
    )


def test_openapi_resume_review_checkpoint_uses_idempotency_header(
    openapi_spec: dict,
) -> None:
    operation = _get_operation(
        openapi_spec,
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/",
        "post",
    )
    parameter = _find_parameter(operation, name="Idempotency-Key", location="header")

    assert parameter.get("required") is False


def test_openapi_flow_public_run_and_step_expose_result_files(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    for component_name in ("FlowRunPublic", "FlowRunStepPublic"):
        properties = schemas.get(component_name, {}).get("properties", {})
        result_files = _resolve_component_ref(
            openapi_spec, properties.get("result_files", {})
        )
        items = _resolve_component_ref(openapi_spec, result_files.get("items", {}))

        assert result_files.get("type") == "array"
        assert items.get("title") == "FlowRunStepResultFile"

    evidence_properties = schemas.get("FlowRunEvidenceResponse", {}).get(
        "properties", {}
    )
    assert "result_files" in evidence_properties


def test_openapi_flow_run_evidence_response_exposes_rerun_lineage(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    evidence_schema = schemas.get("FlowRunEvidenceResponse", {})
    evidence_properties = evidence_schema.get("properties", {})
    step_result_properties = schemas.get("FlowRunStepPublic", {}).get("properties", {})

    assert {"rerun_operations", "rerun_invalidated_steps"}.issubset(
        evidence_schema.get("required", [])
    )
    assert "current_attempt_no" in step_result_properties
    rerun_operations = _resolve_component_ref(
        openapi_spec, evidence_properties.get("rerun_operations", {})
    )
    rerun_operation = _resolve_component_ref(
        openapi_spec, rerun_operations.get("items", {})
    )
    assert rerun_operations.get("type") == "array"
    assert rerun_operation.get("title") == "FlowRunRerunOperationPublic"
    assert set(rerun_operation.get("properties", {})) >= {
        "id",
        "flow_run_id",
        "rerun_step_id",
        "root_attempt_no",
        "root_attempt_id",
        "status",
        "request_fingerprint",
        "expected_run_revision",
        "accepted_run_revision",
        "reason",
        "input_payload_json",
        "step_inputs_json",
        "requested_by_principal_type",
        "requested_by_user_id",
    }

    rerun_invalidated_steps = _resolve_component_ref(
        openapi_spec, evidence_properties.get("rerun_invalidated_steps", {})
    )
    rerun_invalidated_step = _resolve_component_ref(
        openapi_spec, rerun_invalidated_steps.get("items", {})
    )
    assert rerun_invalidated_steps.get("type") == "array"
    assert rerun_invalidated_step.get("title") == "FlowRunRerunInvalidatedStepPublic"
    invalidated_properties = rerun_invalidated_step.get("properties", {})
    assert set(invalidated_properties) >= {
        "id",
        "operation_id",
        "step_id",
        "step_order",
        "invalidation_order",
        "role",
        "dependency_sources_json",
        "prior_step_result_id",
        "prior_attempt_id",
        "new_attempt_no",
        "new_attempt_id",
    }
    dependency_sources = _resolve_component_ref(
        openapi_spec, invalidated_properties["dependency_sources_json"]
    )
    dependency_source_values = _extract_enum_values(
        openapi_spec, dependency_sources.get("items", {})
    )
    assert dependency_source_values == {kind.value for kind in RerunDependencyKind}


def test_openapi_flow_pagination_response_shape_is_current(
    openapi_spec: dict,
) -> None:
    targets = {
        "/api/v1/flows/": "OffsetPaginatedResponse_FlowSparsePublic_",
        "/api/v1/flows/{id}/runs/": "OffsetPaginatedResponse_FlowRunPublic_",
    }
    schemas = openapi_spec.get("components", {}).get("schemas", {})

    for path, expected_component in targets.items():
        operation = _get_operation(openapi_spec, path, "get")
        response_schema = (
            operation.get("responses", {})
            .get("200", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema", {})
        )
        assert response_schema.get("$ref") == (
            f"#/components/schemas/{expected_component}"
        )
        component = schemas.get(expected_component, {})
        assert set(component.get("properties", {})) == {
            "items",
            "count",
            "has_more",
        }
        assert set(component.get("required", [])) == {
            "items",
            "count",
            "has_more",
        }

    assert "PaginatedResponse_FlowSparsePublic_" not in schemas
    assert "PaginatedResponse_FlowRunPublic_" not in schemas


def test_openapi_flow_input_policy_schema_contains_consumer_hints(
    openapi_spec: dict,
) -> None:
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

    input_type_values = _extract_enum_values(
        openapi_spec, properties.get("input_type", {})
    )
    input_source_values = _extract_enum_values(
        openapi_spec, properties.get("input_source", {})
    )

    assert {
        "text",
        "json",
        "image",
        "audio",
        "document",
        "file",
        "any",
    } <= input_type_values
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
    assert isinstance(example, dict), (
        "FlowRunCreateRequest schema must include an example"
    )
    assert "input_payload_json" in example


def test_openapi_flow_run_create_example_shape_is_consumer_valid(
    openapi_spec: dict,
) -> None:
    schema = (
        openapi_spec.get("components", {})
        .get("schemas", {})
        .get("FlowRunCreateRequest", {})
    )
    example = schema.get("example", {})
    assert isinstance(example, dict), (
        "FlowRunCreateRequest example must be a JSON object"
    )
    assert set(example.keys()) <= {
        "expected_flow_version",
        "input_payload_json",
        "step_inputs",
    }

    assert isinstance(example.get("expected_flow_version"), int)

    input_payload_json = example.get("input_payload_json")
    assert isinstance(input_payload_json, dict), (
        "FlowRunCreateRequest.example.input_payload_json must be a JSON object"
    )
    step_inputs = example.get("step_inputs")
    assert isinstance(step_inputs, dict)
    assert step_inputs, (
        "FlowRunCreateRequest.example.step_inputs must include at least one step"
    )


def test_openapi_flow_run_create_schema_removes_top_level_file_ids(
    openapi_spec: dict,
) -> None:
    schema = (
        openapi_spec.get("components", {})
        .get("schemas", {})
        .get("FlowRunCreateRequest", {})
    )
    properties = schema.get("properties", {})
    assert "file_ids" not in properties
    assert "step_inputs" in properties


def test_openapi_flow_run_create_schema_documents_step_file_routing(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    create_properties = schemas.get("FlowRunCreateRequest", {}).get("properties", {})
    step_run_input = schemas.get("StepRunInput", {}).get("properties", {})

    assert "run contract" in create_properties["expected_flow_version"]["description"]
    assert "form_fields" in create_properties["input_payload_json"]["description"]
    assert "Per-step runtime inputs" in create_properties["step_inputs"]["description"]
    assert "route uploads" in create_properties["step_inputs"]["description"]
    assert "specific step" in step_run_input["file_ids"]["description"]


def test_openapi_flow_run_step_rerun_contract(openapi_spec: dict) -> None:
    operation = _get_operation(
        openapi_spec,
        "/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/rerun/",
        "post",
    )
    request_schema = (
        operation.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )
    request_resolved = _resolve_component_ref(openapi_spec, request_schema)
    assert request_resolved.get("title") == "FlowRunStepRerunRequest"
    assert request_resolved.get("additionalProperties") is False
    assert set(request_resolved.get("required", [])) == {
        "expected_run_revision",
        "reason",
    }

    request_properties = request_resolved.get("properties", {})
    expected_revision = request_properties.get("expected_run_revision", {})
    reason = request_properties.get("reason", {})
    assert expected_revision.get("minimum") == 1
    assert reason.get("minLength") == 1
    assert reason.get("maxLength") == 1024
    assert "file_ids" not in request_properties
    assert "step_inputs" in request_properties

    response_schema = (
        operation.get("responses", {})
        .get("202", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )
    response_resolved = _resolve_component_ref(openapi_spec, response_schema)
    assert response_resolved.get("title") == "FlowRunStepRerunResponse"

    response_properties = response_resolved.get("properties", {})
    run_description = str(response_properties.get("run", {}).get("description", ""))
    assert "current persisted run state" in run_description.lower()
    assert "expected_run_revision" in run_description

    operation_description = " ".join(
        str(operation.get("description", "")).lower().split()
    )
    assert "202 accepted" in operation_description
    assert "idempotent replay" in operation_description
    assert "use the response `status`" in operation_description


def test_openapi_flow_run_revision_documents_rerun_compare_token(
    openapi_spec: dict,
) -> None:
    schema = (
        openapi_spec.get("components", {}).get("schemas", {}).get("FlowRunPublic", {})
    )
    properties = schema.get("properties", {})
    revision = properties.get("revision", {})

    assert revision.get("type") == "integer"
    assert "revision" in set(schema.get("required", []))
    description = str(revision.get("description", ""))
    assert "compare token" in description.lower()
    assert "expected_run_revision" in description


def test_openapi_flow_step_create_schema_exposes_enum_constraints(
    openapi_spec: dict,
) -> None:
    schema = (
        openapi_spec.get("components", {})
        .get("schemas", {})
        .get("FlowStepCreateRequest", {})
    )
    properties = schema.get("properties", {})
    for field in (
        "input_source",
        "input_type",
        "output_mode",
        "output_type",
        "mcp_policy",
    ):
        field_schema = properties.get(field, {})
        enum_values = _extract_enum_values(openapi_spec, field_schema)
        assert enum_values, f"{field} must include enum-constrained OpenAPI values"


def test_openapi_flow_step_create_enum_values_match_contract(
    openapi_spec: dict,
) -> None:
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
        "output_mode": {
            "pass_through",
            "http_post",
            "transcribe_only",
            "template_fill",
        },
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
    targets = (
        "/api/v1/flows/{id}/files/",
        "/api/v1/flows/{id}/steps/{step_id}/runtime-files/",
    )
    for path in targets:
        request_schema = (
            openapi_spec.get("paths", {})
            .get(path, {})
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

    upload_paths = (
        "/api/v1/flows/{id}/files/",
        "/api/v1/flows/{id}/steps/{step_id}/runtime-files/",
    )
    for upload_path in upload_paths:
        files_post = openapi_spec.get("paths", {}).get(upload_path, {}).get("post", {})
        files_request_schema = (
            files_post.get("requestBody", {})
            .get("content", {})
            .get("multipart/form-data", {})
            .get("schema", {})
        )
        files_request_resolved = _resolve_component_ref(
            openapi_spec, files_request_schema
        )
        upload_file_schema = files_request_resolved.get("properties", {}).get(
            "upload_file", {}
        )
        assert upload_file_schema.get("type") == "string"
        assert upload_file_schema.get("format") == "binary"
        assert "contentMediaType" not in upload_file_schema


def test_openapi_flow_evidence_export_documents_json_attachment(
    openapi_spec: dict,
) -> None:
    operation = _get_operation(
        openapi_spec,
        "/api/v1/flows/{id}/runs/{run_id}/evidence/export",
        "get",
    )
    response = operation.get("responses", {}).get("200", {})
    schema = response.get("content", {}).get("application/json", {}).get("schema", {})
    resolved = _resolve_component_ref(openapi_spec, schema)
    headers = response.get("headers", {})

    assert resolved.get("title") == "FlowRunEvidenceExportResponse"
    manifest_schema = resolved.get("properties", {}).get("manifest", {})
    manifest = _resolve_component_ref(openapi_spec, manifest_schema)
    assert manifest.get("title") == "EvidenceExportManifest"
    manifest_properties = manifest.get("properties", {})
    assert manifest.get("additionalProperties") is False
    assert set(manifest_properties) >= {
        "schema_version",
        "content_hash",
        "content_hash_input",
        "exported_at",
        "tenant_id",
        "run_id",
        "trace_id",
        "flow_id",
        "export_reason",
        "detail_mode",
        "retention_state_summary",
        "artifact_availability_summary",
        "review_checkpoint_summary",
    }
    assert _extract_enum_values(
        openapi_spec, manifest_properties["schema_version"]
    ) == {"flow-evidence-export.v5"}
    assert _extract_enum_values(
        openapi_spec, manifest_properties["content_hash_input"]
    ) == {
        "raw",
        "redacted",
    }
    assert _extract_enum_values(
        openapi_spec, manifest_properties["provenance_persisted_version_status"]
    ) == {
        "not_tracked",
        "tracked",
        "corrupt",
        "retention_purged",
    }
    retention_summary = _resolve_component_ref(
        openapi_spec, manifest_properties["retention_state_summary"]
    )
    assert "artifact_content_purged_count" in retention_summary.get("properties", {})
    artifact_summary = _resolve_component_ref(
        openapi_spec, manifest_properties["artifact_availability_summary"]
    )
    artifact_summary_properties = artifact_summary.get("properties", {})
    assert artifact_summary.get("additionalProperties") is False
    assert set(artifact_summary_properties) >= {
        "tracking_state",
        "artifact_count",
        "available_count",
        "content_purged_count",
        "total_size_bytes",
        "artifacts",
        "note",
    }
    assert _extract_enum_values(
        openapi_spec, artifact_summary_properties["tracking_state"]
    ) == {"tracked"}
    assert manifest_properties["flow_version"].get("type") == "integer"
    assert "anyOf" not in manifest_properties["flow_version"]
    assert not manifest_properties["flow_version"].get("nullable", False)
    bundle_schema = resolved.get("properties", {}).get("bundle", {})
    assert bundle_schema.get("type") == "object"
    assert bundle_schema.get("additionalProperties") is True
    assert "Content-Disposition" in headers
    assert "attachment" in str(headers["Content-Disposition"]).lower()
    bad_request_example = (
        operation.get("responses", {})
        .get("400", {})
        .get("content", {})
        .get("application/json", {})
        .get("example", {})
    )
    assert bad_request_example.get("code") == "flow_evidence_export_reason_required"


def test_openapi_flow_error_responses_include_general_error_examples(
    openapi_spec: dict,
) -> None:
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
            assert (
                isinstance(example.get("message"), str) and example["message"].strip()
            )
            assert "intric_error_code" in example
            assert isinstance(example.get("code"), str) and example["code"].strip()


def test_openapi_general_error_schema_guides_client_control_flow(
    openapi_spec: dict,
) -> None:
    schema = (
        openapi_spec.get("components", {}).get("schemas", {}).get("GeneralError", {})
    )
    properties = schema.get("properties", {})

    assert "branch on `code`" in properties["message"]["description"]
    assert "LLM tool control flow" in properties["code"]["description"]
    assert "Correlation id" in properties["request_id"]["description"]
    assert "machine-readable data" in properties["details"]["description"]


def test_openapi_flow_file_upload_error_codes_are_machine_readable(
    openapi_spec: dict,
) -> None:
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
        (
            "/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/rerun/",
            "post",
        ): ("400", "403", "404"),
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


def test_openapi_create_flow_run_documents_idempotency_contract(
    openapi_spec: dict,
) -> None:
    operation = _get_operation(openapi_spec, "/api/v1/flows/{id}/runs/", "post")
    header = _find_parameter(
        operation,
        name="Idempotency-Key",
        location="header",
    )

    description = str(header.get("description", ""))
    assert "same key" in description.lower()
    assert "existing run" in description.lower()
    assert "flow_run_idempotency_conflict" in description
    assert "retained" in description.lower()

    operation_description = str(operation.get("description", ""))
    assert (
        "Service-key principals may create published-flow runs in v1"
        in operation_description
    )
    assert "matching run row is retained" in operation_description.lower()

    conflict_response = operation.get("responses", {}).get("400", {})
    assert "flow_run_idempotency_conflict" in str(
        conflict_response.get("description", "")
    )


def test_openapi_flow_run_forbidden_docs_list_current_codes(
    openapi_spec: dict,
) -> None:
    operation = _get_operation(openapi_spec, "/api/v1/flows/{id}/runs/", "post")
    forbidden_description = str(
        operation.get("responses", {}).get("403", {}).get("description", "")
    )

    assert "insufficient_scope" in forbidden_description
    assert "flow_run_access_denied" in forbidden_description


def test_openapi_flow_runtime_visibility_docs_are_explicit(openapi_spec: dict) -> None:
    get_run_description = str(
        _get_operation(openapi_spec, "/api/v1/flows/{id}/runs/{run_id}/", "get").get(
            "description", ""
        )
    )
    steps_description = str(
        _get_operation(
            openapi_spec, "/api/v1/flows/{id}/runs/{run_id}/steps/", "get"
        ).get("description", "")
    )
    artifact_description = str(
        _get_operation(
            openapi_spec,
            "/api/v1/flows/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/",
            "post",
        ).get("description", "")
    )
    evidence_description = str(
        _get_operation(
            openapi_spec, "/api/v1/flows/{id}/runs/{run_id}/evidence/", "get"
        ).get("description", "")
    )
    export_description = str(
        _get_operation(
            openapi_spec,
            "/api/v1/flows/{id}/runs/{run_id}/evidence/export",
            "get",
        ).get("description", "")
    )

    assert (
        "service-key principals can inspect only their own runs" in get_run_description
    )
    assert (
        "same-space admins and owners can inspect run metadata" in get_run_description
    )
    assert "space owner and space admin" in steps_description.lower()
    assert "inspect content for runs in their space" in steps_description.lower()
    artifact_description_lower = artifact_description.lower()
    assert (
        "service-key principals are supported for their own runtime artifacts"
        in artifact_description_lower
    )
    assert "trusted in-space operators" in artifact_description_lower
    assert "space admin" in evidence_description.lower()
    assert (
        "service keys may inspect only their own-run evidence"
        in evidence_description.lower()
    )
    assert "redacted/default export" in export_description.lower()


def test_openapi_evidence_export_query_params_are_documented(
    openapi_spec: dict,
) -> None:
    operation = _get_operation(
        openapi_spec,
        "/api/v1/flows/{id}/runs/{run_id}/evidence/export",
        "get",
    )
    params = {
        param.get("name"): param
        for param in operation.get("parameters", [])
        if isinstance(param, dict)
    }
    format_schema = params["format"].get("schema", {})
    assert "detail" in params
    assert "format" in params
    assert "reason" in params
    assert _extract_enum_values(openapi_spec, format_schema) == {"json"}
    assert format_schema.get("default") == "json"
    assert "redacted" in str(params["detail"].get("description", "")).lower()
    reason_description = str(params["reason"].get("description", "")).lower()
    assert "raw exports require" in reason_description
    assert "explicit non-default reason" in reason_description


def test_openapi_flow_authoring_docs_explain_owner_override_semantics(
    openapi_spec: dict,
) -> None:
    update_operation = _get_operation(openapi_spec, "/api/v1/flows/{id}/", "patch")
    update_description = str(update_operation.get("description", ""))
    forbidden_description = str(
        update_operation.get("responses", {}).get("403", {}).get("description", "")
    )

    assert "draft owner" in update_description.lower()
    assert "space owner" in update_description.lower()
    assert "tenant admin" in update_description.lower()
    assert "flow_owner_required" in forbidden_description
