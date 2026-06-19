from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.routing import APIRoute
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from intric.authentication.auth_models import (
    FLOW_EVIDENCE_SERVICE_KEY_PERMISSION_RECIPE,
)
from intric.flows.api.flow_run_status_capability_models import (
    flow_run_status_capabilities_public,
)
from intric.flows.api.flow_runtime_endpoint_registry import (
    flow_runtime_endpoint_operation_ids,
    flow_runtime_path_field_operations,
)
from intric.flows.api.flow_runtime_paths import (
    FlowReviewCheckpointRuntimePathsPublic,
    FlowRuntimePathsPublic,
    build_flow_runtime_paths,
)
from intric.flows.enums import RerunDependencyKind
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.flow_metadata import FlowFormFieldType
from intric.main.exceptions import ErrorCodes
from intric.server.main import get_application
from intric.settings.setting_service import FLOW_SETTINGS_INVALID_PAYLOAD_CODE

FLOW_SETTINGS_PATH_PREFIX = "/api/v1/settings/flow-"


def _is_non_ai_builder_flow_related_path(path: str) -> bool:
    if path.startswith("/api/v1/flows/ai-builder"):
        return False
    return path.startswith("/api/v1/flows") or path.startswith(
        FLOW_SETTINGS_PATH_PREFIX
    )


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
        if not _is_non_ai_builder_flow_related_path(route.path):
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


def _error_example_values(
    operation: dict,
    *,
    status_code: str,
) -> dict[str, dict[str, object]]:
    examples = (
        operation.get("responses", {})
        .get(status_code, {})
        .get("content", {})
        .get("application/json", {})
        .get("examples", {})
    )
    assert isinstance(examples, dict)
    values: dict[str, dict[str, object]] = {}
    for code, example in examples.items():
        assert isinstance(example, dict), f"{code} example wrapper must be an object"
        value = example.get("value", {})
        assert isinstance(value, dict), f"{code} example value must be an object"
        values[str(code)] = value
    return values


def _schema_allows_null(schema: dict) -> bool:
    options = schema.get("anyOf") or schema.get("oneOf") or []
    return any(
        isinstance(option, dict) and option.get("type") == "null" for option in options
    )


def _assert_required_uuid_property(schema: dict, field_name: str) -> None:
    assert field_name in schema.get("required", [])
    property_schema = schema.get("properties", {}).get(field_name, {})
    assert property_schema.get("type") == "string"
    assert property_schema.get("format") == "uuid"
    assert not _schema_allows_null(property_schema)


def _path_for_operation_id(openapi_spec: dict, operation_id: str) -> str:
    for path, methods in openapi_spec.get("paths", {}).items():
        for operation in methods.values():
            if (
                isinstance(operation, dict)
                and operation.get("operationId") == operation_id
            ):
                return path
    pytest.fail(f"Missing OpenAPI operationId: {operation_id}")


def _path_for_operation_id_and_method(
    openapi_spec: dict,
    *,
    operation_id: str,
    method: str,
) -> str:
    for path, methods in openapi_spec.get("paths", {}).items():
        operation = methods.get(method)
        if isinstance(operation, dict) and operation.get("operationId") == operation_id:
            return path
    pytest.fail(f"Missing OpenAPI {method.upper()} operationId: {operation_id}")


def _iter_non_ai_builder_flow_operations(
    openapi_spec: dict,
) -> Iterator[tuple[str, str, dict]]:
    for path, methods in openapi_spec.get("paths", {}).items():
        if not _is_non_ai_builder_flow_related_path(path):
            continue
        for method, operation in methods.items():
            if method not in {"delete", "get", "patch", "post", "put"}:
                continue
            if isinstance(operation, dict):
                yield path, method, operation


def _schema_has_example(openapi_spec: dict, schema: dict, *, depth: int = 0) -> bool:
    if depth > 6:
        return False
    resolved = _resolve_component_ref(openapi_spec, schema)
    if "example" in resolved or "examples" in resolved:
        return True
    items = resolved.get("items")
    if isinstance(items, dict) and _schema_has_example(
        openapi_spec, items, depth=depth + 1
    ):
        return True
    for composition_key in ("anyOf", "oneOf", "allOf"):
        options = resolved.get(composition_key, [])
        if not isinstance(options, list):
            continue
        for option in options:
            if isinstance(option, dict) and _schema_has_example(
                openapi_spec, option, depth=depth + 1
            ):
                return True
    return False


def _content_has_example(openapi_spec: dict, content: dict) -> bool:
    for media_object in content.values():
        if not isinstance(media_object, dict):
            continue
        if media_object.get("example") or media_object.get("examples"):
            return True
        schema = media_object.get("schema")
        if isinstance(schema, dict) and _schema_has_example(openapi_spec, schema):
            return True
    return False


def _iter_explicit_openapi_examples(
    content: dict,
) -> Iterator[tuple[str, dict, object]]:
    for media_type, media_object in content.items():
        if not isinstance(media_object, dict):
            continue
        schema = media_object.get("schema")
        if not isinstance(schema, dict):
            continue
        if "example" in media_object:
            yield f"{media_type}.example", schema, media_object["example"]
        examples = media_object.get("examples", {})
        if not isinstance(examples, dict):
            continue
        for example_name, example_object in examples.items():
            if not isinstance(example_object, dict) or "value" not in example_object:
                continue
            yield (
                f"{media_type}.examples.{example_name}",
                schema,
                example_object["value"],
            )


def _openapi_registry(openapi_spec: dict) -> Registry:
    return Registry().with_resource(
        "urn:openapi",
        Resource.from_contents(openapi_spec, default_specification=DRAFT202012),
    )


def _with_absolute_openapi_refs(value: object) -> object:
    if isinstance(value, dict):
        rewritten: dict[object, object] = {}
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str) and item.startswith("#/"):
                rewritten[key] = f"urn:openapi{item}"
            else:
                rewritten[key] = _with_absolute_openapi_refs(item)
        return rewritten
    if isinstance(value, list):
        return [_with_absolute_openapi_refs(item) for item in value]
    return value


def _validate_openapi_example(
    *,
    openapi_spec: dict,
    schema: dict,
    example: object,
) -> list[str]:
    rewritten_schema = _with_absolute_openapi_refs(schema)
    assert isinstance(rewritten_schema, dict)
    validator = Draft202012Validator(
        rewritten_schema,
        registry=_openapi_registry(openapi_spec),
    )
    return [error.message for error in validator.iter_errors(example)]


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
    "/api/v1/flows/{id}/run-contract/": {"get"},
    "/api/v1/flows/{id}/steps/{step_id}/runtime-files/": {"post"},
    "/api/v1/flows/{id}/runtime-files/{file_id}/": {"delete"},
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
    "/api/v1/flows/runs/status-capabilities/": {"get"},
    "/api/v1/flows/{id}/runs/{run_id}/evidence/": {"get"},
    "/api/v1/flows/{id}/runs/{run_id}/evidence/export": {"get"},
    "/api/v1/flows/{id}/runs/{run_id}/steps/": {"get"},
    "/api/v1/flows/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/": {"post"},
    "/api/v1/settings/flow-input-limits": {"get", "patch"},
    "/api/v1/settings/flow-document-render-limits": {"get", "patch"},
    "/api/v1/settings/flow-runtime-policy": {"get", "patch"},
    "/api/v1/settings/flow-evidence-policy": {"get", "patch"},
    "/api/v1/settings/flow-retention-policy": {"get", "patch"},
    "/api/v1/settings/flow-classification-retention-policies": {"get"},
    "/api/v1/settings/flow-classification-retention-policies/{security_classification_id}": {
        "put",
        "delete",
    },
}

RUNTIME_PATH_FIELD_OPERATIONS = flow_runtime_path_field_operations()


def _runtime_path_field_paths() -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    for field_name in FlowRuntimePathsPublic.model_fields:
        if field_name == "review_checkpoints":
            paths.update(
                ("review_checkpoints", review_field)
                for review_field in FlowReviewCheckpointRuntimePathsPublic.model_fields
            )
            continue
        paths.add((field_name,))
    return paths


def _runtime_path_value(
    runtime_paths: dict[str, object],
    field_path: tuple[str, ...],
) -> str:
    value: object = runtime_paths
    for field_name in field_path:
        assert isinstance(value, dict)
        value = value[field_name]
    assert isinstance(value, str)
    return value


REQUIRED_SCHEMAS = {
    "FlowRuntimePublic",
    "FlowReviewCheckpointRuntimePathsPublic",
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
    "FlowServicePrincipalActorPublic",
    "FlowRunRerunOperationPublic",
    "FlowRunRerunInvalidatedStepPublic",
    "FlowRunEvidenceResponse",
    "FlowFinalOutputContractPublic",
    "FlowOutputDelivery",
    "FlowRuntimeUploadPolicyPublic",
    "FormFieldPublic",
    "FlowRuntimeInputContractPublic",
    "FlowReviewStepContractPublic",
    "FlowRunStepPublic",
    "FlowStepDiagnosticPublic",
    "FlowRunStatusCapabilitiesPublic",
    "FlowRunStatusCapabilityPublic",
    "FlowInputLimitsPublic",
    "FlowTemplateAssetPublic",
    "FlowTemplateReadinessPublic",
    "FlowTemplateInspectionPublic",
}

RUNTIME_REQUIRED_OPERATION_IDS = flow_runtime_endpoint_operation_ids(
    api_prefix="/api/v1"
)

NON_RUNTIME_REQUIRED_OPERATION_IDS: dict[tuple[str, str], str] = {
    ("/api/v1/flows/", "post"): "create_flow",
    ("/api/v1/flows/", "get"): "list_flows",
    ("/api/v1/flows/{id}/", "get"): "get_flow",
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
    ("/api/v1/settings/flow-input-limits", "get"): "get_flow_input_limits",
    ("/api/v1/settings/flow-input-limits", "patch"): "update_flow_input_limits",
    (
        "/api/v1/settings/flow-document-render-limits",
        "get",
    ): "get_flow_document_render_limits",
    (
        "/api/v1/settings/flow-document-render-limits",
        "patch",
    ): "update_flow_document_render_limits",
    ("/api/v1/settings/flow-runtime-policy", "get"): "get_flow_runtime_policy",
    ("/api/v1/settings/flow-runtime-policy", "patch"): "update_flow_runtime_policy",
    ("/api/v1/settings/flow-evidence-policy", "get"): "get_flow_evidence_policy",
    (
        "/api/v1/settings/flow-evidence-policy",
        "patch",
    ): "update_flow_evidence_policy",
    ("/api/v1/settings/flow-retention-policy", "get"): "get_flow_retention_policy",
    (
        "/api/v1/settings/flow-retention-policy",
        "patch",
    ): "update_flow_retention_policy",
    (
        "/api/v1/settings/flow-classification-retention-policies",
        "get",
    ): "list_flow_classification_retention_policies",
    (
        "/api/v1/settings/flow-classification-retention-policies/{security_classification_id}",
        "put",
    ): "put_flow_classification_retention_policy",
    (
        "/api/v1/settings/flow-classification-retention-policies/{security_classification_id}",
        "delete",
    ): "delete_flow_classification_retention_policy",
}

REQUIRED_OPERATION_IDS: dict[tuple[str, str], str] = {
    **NON_RUNTIME_REQUIRED_OPERATION_IDS,
    **RUNTIME_REQUIRED_OPERATION_IDS,
}


def test_flow_runtime_operation_ids_are_owned_by_endpoint_registry() -> None:
    assert set(NON_RUNTIME_REQUIRED_OPERATION_IDS).isdisjoint(
        RUNTIME_REQUIRED_OPERATION_IDS
    )
    assert set(NON_RUNTIME_REQUIRED_OPERATION_IDS.values()).isdisjoint(
        RUNTIME_REQUIRED_OPERATION_IDS.values()
    )


REQUIRED_ERROR_RESPONSES: dict[tuple[str, str], set[str]] = {
    (
        "/api/v1/flows/{id}/",
        "get",
    ): {"403", "404"},
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
        "/api/v1/flows/{id}/runtime-files/{file_id}/",
        "delete",
    ): {"400", "403", "404", "409", "422"},
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
        "get",
    ): {"403"},
    (
        "/api/v1/settings/flow-input-limits",
        "patch",
    ): {"400", "403", "422"},
    (
        "/api/v1/settings/flow-document-render-limits",
        "get",
    ): {"403"},
    (
        "/api/v1/settings/flow-document-render-limits",
        "patch",
    ): {"400", "403", "422"},
    (
        "/api/v1/settings/flow-runtime-policy",
        "get",
    ): {"403"},
    (
        "/api/v1/settings/flow-runtime-policy",
        "patch",
    ): {"400", "403", "422"},
    (
        "/api/v1/settings/flow-evidence-policy",
        "get",
    ): {"403"},
    (
        "/api/v1/settings/flow-evidence-policy",
        "patch",
    ): {"400", "403", "422"},
    (
        "/api/v1/settings/flow-retention-policy",
        "get",
    ): {"403"},
    (
        "/api/v1/settings/flow-retention-policy",
        "patch",
    ): {"400", "403", "422"},
    (
        "/api/v1/settings/flow-classification-retention-policies",
        "get",
    ): {"403"},
    (
        "/api/v1/settings/flow-classification-retention-policies/{security_classification_id}",
        "put",
    ): {"403", "404", "422"},
    (
        "/api/v1/settings/flow-classification-retention-policies/{security_classification_id}",
        "delete",
    ): {"403", "404", "422"},
}

FLOW_SETTINGS_INVALID_PAYLOAD_MESSAGES: dict[str, str] = {
    "/api/v1/settings/flow-input-limits": (
        "At least one flow input limit field must be provided."
    ),
    "/api/v1/settings/flow-document-render-limits": (
        "At least one flow document render limit field must be provided."
    ),
    "/api/v1/settings/flow-runtime-policy": (
        "At least one flow runtime policy field must be provided."
    ),
    "/api/v1/settings/flow-evidence-policy": (
        "At least one flow evidence policy field must be provided."
    ),
    "/api/v1/settings/flow-retention-policy": (
        "At least one flow retention policy field must be provided."
    ),
}

REQUIRED_TYPED_ERROR_CODES: dict[tuple[str, str], set[str]] = {
    (
        "/api/v1/flows/{id}/",
        "get",
    ): {"403", "404"},
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
        "/api/v1/flows/{id}/runtime-files/{file_id}/",
        "delete",
    ): {"400", "403", "404", "409"},
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
    ("/api/v1/settings/flow-input-limits", "get"): {"403"},
    ("/api/v1/settings/flow-input-limits", "patch"): {"400", "403"},
    ("/api/v1/settings/flow-document-render-limits", "get"): {"403"},
    (
        "/api/v1/settings/flow-document-render-limits",
        "patch",
    ): {"400", "403"},
    ("/api/v1/settings/flow-runtime-policy", "get"): {"403"},
    ("/api/v1/settings/flow-runtime-policy", "patch"): {"400", "403"},
    ("/api/v1/settings/flow-evidence-policy", "get"): {"403"},
    ("/api/v1/settings/flow-evidence-policy", "patch"): {"400", "403"},
    ("/api/v1/settings/flow-retention-policy", "get"): {"403"},
    ("/api/v1/settings/flow-retention-policy", "patch"): {"400", "403"},
    (
        "/api/v1/settings/flow-classification-retention-policies",
        "get",
    ): {"403"},
    (
        "/api/v1/settings/flow-classification-retention-policies/{security_classification_id}",
        "put",
    ): {"403", "404"},
    (
        "/api/v1/settings/flow-classification-retention-policies/{security_classification_id}",
        "delete",
    ): {"403", "404"},
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


def test_openapi_flow_operation_ids_do_not_use_alias_suffix(
    openapi_spec: dict,
) -> None:
    paths = openapi_spec.get("paths", {})
    alias_operation_ids = sorted(
        f"{method.upper()} {path}: {operation.get('operationId')}"
        for path, methods in paths.items()
        if isinstance(path, str) and path.startswith("/api/v1/flows/")
        for method, operation in methods.items()
        if isinstance(operation, dict)
        and str(operation.get("operationId", "")).endswith("_alias")
    )

    assert alias_operation_ids == []


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


def test_flow_routes_removed_flow_file_upload_route_absent(
    flow_route_operations: dict[tuple[str, str], str],
) -> None:
    removed_route = ("/api/v1/flows/{id}/files/", "post")
    removed_operation_id = "upload_flow" + "_file"

    assert removed_route not in flow_route_operations
    assert removed_operation_id not in set(flow_route_operations.values())


def test_openapi_legacy_flow_run_paths_absent(openapi_spec: dict) -> None:
    paths = openapi_spec.get("paths", {})
    legacy_paths = sorted(
        path for path in paths if path.startswith("/api/v1/flow-runs")
    )
    assert not legacy_paths, f"Legacy flow-run paths must be absent: {legacy_paths}"


def test_openapi_removed_runtime_policy_surface_absent(openapi_spec: dict) -> None:
    paths = openapi_spec.get("paths", {})
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    # Keep removed public-surface tokens split so the strict absence grep catches
    # accidental real references while this test still guards the old names.
    removed_path = "/api/v1/flows/{id}/input" + "-policy/"
    removed_schema = "FlowInput" + "PolicyPublic"
    removed_field = "input" + "_policy"

    assert removed_path not in paths
    assert removed_schema not in schemas
    runtime_paths = schemas.get("FlowRuntimePathsPublic", {})
    assert removed_field not in runtime_paths.get("properties", {})


def test_flow_routes_removed_runtime_policy_route_absent(
    flow_route_operations: dict[tuple[str, str], str],
) -> None:
    removed_path = "/api/v1/flows/{id}/input" + "-policy/"
    assert (removed_path, "get") not in flow_route_operations


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


def test_openapi_all_flow_operations_have_reviewable_dx_docs(
    openapi_spec: dict,
) -> None:
    short_descriptions: list[str] = []
    for path, method, operation in _iter_non_ai_builder_flow_operations(openapi_spec):
        description = str(operation.get("description") or "").strip()
        if len(description) < 150:
            short_descriptions.append(
                f"{method.upper()} {path} ({operation.get('operationId')})"
            )

    assert short_descriptions == []


def test_openapi_all_flow_request_bodies_have_examples(
    openapi_spec: dict,
) -> None:
    missing_examples: list[str] = []
    for path, method, operation in _iter_non_ai_builder_flow_operations(openapi_spec):
        request_body = operation.get("requestBody", {})
        if not isinstance(request_body, dict):
            continue
        content = request_body.get("content", {})
        if not isinstance(content, dict) or "application/json" not in content:
            continue
        json_content = {"application/json": content["application/json"]}
        if not _content_has_example(openapi_spec, json_content):
            missing_examples.append(
                f"{method.upper()} {path} ({operation.get('operationId')})"
            )

    assert missing_examples == []


def test_openapi_flow_error_examples_follow_openapi_media_object_rules(
    openapi_spec: dict,
) -> None:
    invalid_media_objects: list[str] = []
    for path, method, operation in _iter_non_ai_builder_flow_operations(openapi_spec):
        for status_code, response in operation.get("responses", {}).items():
            if not isinstance(response, dict):
                continue
            content = response.get("content", {})
            if not isinstance(content, dict):
                continue
            for media_type, media_object in content.items():
                if not isinstance(media_object, dict):
                    continue
                if "example" in media_object and "examples" in media_object:
                    invalid_media_objects.append(
                        f"{method.upper()} {path} {status_code} {media_type}"
                    )

    assert invalid_media_objects == []


def test_openapi_flow_settings_invalid_payload_examples_match_runtime_code(
    openapi_spec: dict,
) -> None:
    paths = openapi_spec.get("paths", {})
    for path, expected_message in FLOW_SETTINGS_INVALID_PAYLOAD_MESSAGES.items():
        response = paths[path]["patch"]["responses"]["400"]
        media_object = response["content"]["application/json"]
        example = media_object["example"]
        assert example["message"] == expected_message
        assert example["code"] == FLOW_SETTINGS_INVALID_PAYLOAD_CODE


def test_openapi_flow_settings_update_requests_reject_unknown_fields(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    strict_request_schemas = {
        "FlowDocumentRenderLimitsUpdate",
        "FlowEvidencePolicyUpdate",
        "FlowClassificationRetentionPolicyUpdate",
        "FlowInputLimitsUpdate",
        "FlowRetentionPolicyUpdate",
        "FlowRuntimePolicyUpdate",
    }

    missing_strict_contract = [
        schema_name
        for schema_name in sorted(strict_request_schemas)
        if schemas.get(schema_name, {}).get("additionalProperties") is not False
    ]

    assert missing_strict_contract == []


def test_openapi_tenant_update_public_does_not_expose_raw_flow_settings(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    schema = schemas.get("TenantUpdatePublic", {})

    assert "flow_settings" not in schema.get("properties", {})
    assert schema.get("additionalProperties") is False


def test_openapi_flow_evidence_policy_update_rejects_null_flags(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    schema = schemas.get("FlowEvidencePolicyUpdate", {})

    assert schema.get("additionalProperties") is False
    required_fields = set(schema.get("required", []))
    properties = schema.get("properties", {})
    flag_fields = (
        "allow_sensitive_flow_exports",
        "allow_space_admin_raw_export_class3",
        "allow_run_owner_raw_export_class3",
        "allow_service_key_raw_export_class3",
    )

    for field_name in flag_fields:
        property_schema = properties.get(field_name, {})
        assert field_name not in required_fields
        assert property_schema.get("type") == "boolean"
        assert property_schema.get("nullable") is not True
        assert not _schema_allows_null(property_schema)
        assert "default" not in property_schema

    example = schema.get("example", {})
    assert example
    assert all(value is not None for value in example.values())


def test_openapi_flow_retention_policy_exposes_implemented_field_only(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})

    for component_name in ("FlowRetentionPolicyPublic", "FlowRetentionPolicyUpdate"):
        component = schemas.get(component_name, {})
        assert set(component.get("properties", {})) == {"run_debug_evidence_days"}

    assert schemas["FlowRetentionPolicyUpdate"].get("additionalProperties") is False


def test_openapi_flow_retention_surfaces_are_disambiguated(
    openapi_spec: dict,
) -> None:
    paths = openapi_spec.get("paths", {})
    debug_retention = paths["/api/v1/settings/flow-retention-policy"]["get"]
    classification_retention = paths[
        "/api/v1/settings/flow-classification-retention-policies"
    ]["get"]

    debug_description = str(debug_retention.get("description", "")).lower()
    classification_description = str(
        classification_retention.get("description", "")
    ).lower()

    assert "debug-evidence" in debug_description
    assert "full run history" not in debug_description
    assert "full run history" in classification_description
    assert "step history" in classification_description
    assert "debug-evidence" in classification_description
    assert "security_enabled" in classification_description


def test_openapi_flow_classification_retention_policy_contract(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})

    row_schema = schemas.get("FlowClassificationRetentionPolicyPublic", {})
    row_properties = row_schema.get("properties", {})
    assert set(row_properties) == {
        "security_classification_id",
        "data_retention_days",
    }
    assert row_properties["security_classification_id"]["format"] == "uuid"
    assert row_properties["data_retention_days"]["minimum"] == 1
    assert row_properties["data_retention_days"]["maximum"] == 2555

    list_schema = schemas.get("FlowClassificationRetentionPoliciesPublic", {})
    assert set(list_schema.get("properties", {})) == {"policies"}

    update_schema = schemas.get("FlowClassificationRetentionPolicyUpdate", {})
    assert set(update_schema.get("properties", {})) == {"data_retention_days"}
    assert update_schema.get("additionalProperties") is False
    assert update_schema["properties"]["data_retention_days"]["minimum"] == 1
    assert update_schema["properties"]["data_retention_days"]["maximum"] == 2555


def test_openapi_all_flow_success_responses_have_examples(
    openapi_spec: dict,
) -> None:
    missing_examples: list[str] = []
    for path, method, operation in _iter_non_ai_builder_flow_operations(openapi_spec):
        for status_code, response in operation.get("responses", {}).items():
            if not str(status_code).startswith("2"):
                continue
            if not isinstance(response, dict):
                continue
            content = response.get("content", {})
            if not isinstance(content, dict) or not content:
                continue
            if not _content_has_example(openapi_spec, content):
                missing_examples.append(
                    f"{method.upper()} {path} {status_code} "
                    f"({operation.get('operationId')})"
                )

    assert missing_examples == []


def test_openapi_all_flow_error_responses_have_examples(
    openapi_spec: dict,
) -> None:
    missing_examples: list[str] = []
    for path, method, operation in _iter_non_ai_builder_flow_operations(openapi_spec):
        for status_code, response in operation.get("responses", {}).items():
            if str(status_code).startswith("2") or str(status_code) == "422":
                continue
            if not isinstance(response, dict):
                continue
            content = response.get("content", {})
            if not isinstance(content, dict) or not content:
                continue
            if not _content_has_example(openapi_spec, content):
                missing_examples.append(
                    f"{method.upper()} {path} {status_code} "
                    f"({operation.get('operationId')})"
                )

    assert missing_examples == []


def test_openapi_flow_explicit_examples_validate_against_schemas(
    openapi_spec: dict,
) -> None:
    failures: list[str] = []
    for path, method, operation in _iter_non_ai_builder_flow_operations(openapi_spec):
        request_body = operation.get("requestBody", {})
        if isinstance(request_body, dict):
            for example_name, schema, example in _iter_explicit_openapi_examples(
                request_body.get("content", {})
            ):
                errors = sorted(
                    _validate_openapi_example(
                        openapi_spec=openapi_spec,
                        schema=schema,
                        example=example,
                    )
                )
                failures.extend(
                    f"{method.upper()} {path} request {example_name}: {message}"
                    for message in errors
                )

        for status_code, response in operation.get("responses", {}).items():
            if not isinstance(response, dict):
                continue
            for example_name, schema, example in _iter_explicit_openapi_examples(
                response.get("content", {})
            ):
                errors = sorted(
                    _validate_openapi_example(
                        openapi_spec=openapi_spec,
                        schema=schema,
                        example=example,
                    )
                )
                failures.extend(
                    f"{method.upper()} {path} response {status_code} "
                    f"{example_name}: {message}"
                    for message in errors
                )

    assert failures == []


def test_openapi_flow_schema_examples_validate_against_schemas(
    openapi_spec: dict,
) -> None:
    failures: list[str] = []
    for schema_name, schema in (
        openapi_spec.get("components", {}).get("schemas", {}).items()
    ):
        if not isinstance(schema_name, str) or not schema_name.startswith("Flow"):
            continue
        if not isinstance(schema, dict):
            continue
        if "example" not in schema:
            continue
        errors = sorted(
            _validate_openapi_example(
                openapi_spec=openapi_spec,
                schema=schema,
                example=schema["example"],
            )
        )
        failures.extend(f"{schema_name}: {message}" for message in errors)

    assert failures == []


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
        "output_contract",
        "next_step_ids",
        "requester_user_id",
        "requester_principal_type",
        "requester_service_principal",
        "decided_by_user_id",
        "decided_by_principal_type",
        "decided_by_service_principal",
        "edited_at",
        "approved_at",
        "rejected_at",
        "resumed_at",
        "cancelled_at",
        "expires_at",
        "expired_at",
        "created_at",
        "updated_at",
    } <= set(properties)
    assert "requester_service_id" not in properties
    assert "decided_by_service_id" not in properties
    assert "step_snapshot_available" not in properties
    assert "resume_idempotency_key" not in properties
    assert {"review_mode", "output_type"} <= set(schema.get("required", []))


def test_openapi_flow_review_checkpoint_schema_documents_consumer_snapshot(
    openapi_spec: dict,
) -> None:
    schema = (
        openapi_spec.get("components", {})
        .get("schemas", {})
        .get("FlowRunReviewCheckpointPublic", {})
    )
    properties = schema.get("properties", {})

    output_contract = properties.get("output_contract", {})
    expires_at = properties.get("expires_at", {})
    assert "step_snapshot_available" not in properties
    assert "step_snapshot_available" not in output_contract.get("description", "")
    assert "legacy checkpoint" not in output_contract.get("description", "")
    assert "output contract" in output_contract.get("description", "").lower()
    assert "submission deadline" in expires_at.get("description", "")
    assert "background reconciler" in expires_at.get("description", "")
    assert "Approved checkpoints" in expires_at.get("description", "")


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
    final_output = schemas.get("FlowFinalOutputContractPublic", {}).get(
        "properties", {}
    )
    form_field = schemas.get("FormFieldPublic", {}).get("properties", {})
    review_step = schemas.get("FlowReviewStepContractPublic", {}).get("properties", {})
    upload_policy = schemas.get("FlowRuntimeUploadPolicyPublic", {}).get(
        "properties", {}
    )

    assert "step_inputs[step_id].file_ids" in description
    assert "actual file size" in description
    assert "progress events continue" in description
    assert "terminal output type" in description
    assert "steps_requiring_review" in description
    assert "expires_after_seconds" in description
    assert "awaiting_review" in description
    assert "generated file download" in run_contract["final_output"]["description"]
    assert "actual file size" in run_contract["runtime_upload_policy"]["description"]
    assert "without progress" in run_contract["runtime_upload_policy"]["description"]
    assert "artifact" in final_output["delivery"]["description"]
    assert "generated file download" in final_output["output_type"]["description"]
    assert "input_payload_json" in form_field["name"]["description"]
    form_field_type_values = _extract_enum_values(openapi_spec, form_field["type"])
    assert form_field_type_values == {
        field_type.value for field_type in FlowFormFieldType
    }
    assert form_field_type_values == {"text", "multiselect", "number", "date", "select"}
    assert "review screens" in run_contract["steps_requiring_review"]["description"]
    assert "empty list" in run_contract["steps_requiring_review"]["description"]
    assert "Review behavior" in review_step["review_mode"]["description"]
    assert "output contract" in review_step["output_contract"]["description"]
    assert "expires_after_seconds" in review_step
    assert (
        "Effective review window" in review_step["expires_after_seconds"]["description"]
    )
    assert (
        "before the run reaches awaiting_review"
        in review_step["expires_after_seconds"]["description"]
    )
    assert "timeout" in upload_policy["min_timeout_seconds"]["description"].lower()
    assert "actual file size" in upload_policy["seconds_per_mebibyte"]["description"]
    assert "no-progress timeout" in upload_policy["max_timeout_seconds"]["description"]
    assert "progress" in upload_policy["idle_timeout_seconds"]["description"]


def test_openapi_run_contract_response_schemas_are_closed(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    run_contract_schemas = {
        "FlowFinalOutputContractPublic",
        "FlowReviewStepContractPublic",
        "FlowRunContractPublic",
        "FlowRuntimeInputContractPublic",
        "FlowRuntimeUploadPolicyPublic",
        "FlowTemplateReadinessPublic",
        "FormFieldPublic",
    }

    missing_closed_schema = [
        schema_name
        for schema_name in sorted(run_contract_schemas)
        if schemas.get(schema_name, {}).get("additionalProperties") is not False
    ]

    assert missing_closed_schema == []


def test_openapi_flow_run_status_capabilities_guides_consumer_lifecycle(
    openapi_spec: dict,
) -> None:
    operation = _get_operation(
        openapi_spec,
        "/api/v1/flows/runs/status-capabilities/",
        "get",
    )
    description = operation.get("description", "")
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    capability_schema = schemas.get("FlowRunStatusCapabilitiesPublic", {})
    capabilities = capability_schema.get("properties", {})
    row_component = schemas.get("FlowRunStatusCapabilityPublic", {})
    row_schema = row_component.get("properties", {})

    assert capability_schema.get("additionalProperties") is False
    assert row_component.get("additionalProperties") is False
    assert capability_schema.get(
        "example"
    ) == flow_run_status_capabilities_public().model_dump(mode="json")
    assert "canonical Flow run status capability table" in description
    assert "should_poll" in description
    assert "can_request_redispatch" in description
    assert "redispatched_count: 0" in description
    assert "hard-coding status groups" in capabilities["statuses"]["description"]
    assert (
        "Recommended status filter order" in capabilities["filter_order"]["description"]
    )
    assert "continue polling" in row_schema["should_poll"]["description"]
    assert "cancel endpoint" in row_schema["is_cancellable"]["description"]
    assert (
        "server-gated by staleness"
        in row_schema["can_request_redispatch"]["description"]
    )


def test_openapi_flow_step_review_policy_documents_authoring_contract(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    create_schema = schemas.get("FlowStepCreateRequest", {}).get("properties", {})
    public_schema = schemas.get("FlowStepPublic", {}).get("properties", {})
    review_policy_schema = schemas.get("FlowStepReviewPolicy", {}).get("properties", {})

    create_description = str(create_schema["review_policy"].get("description", ""))
    public_description = str(public_schema["review_policy"].get("description", ""))
    mode_description = str(review_policy_schema["mode"].get("description", ""))
    expiry_description = str(
        review_policy_schema["expires_after_seconds"].get("description", "")
    )

    for description in (create_description, public_description):
        assert "human-in-the-loop checkpoint" in description
        assert "`view`" in description
        assert "`edit`" in description
        assert "downstream steps continue" in description
        assert "outbound delivery output modes" in description

    assert "`view` pauses the run" in mode_description
    assert "replace the output used by downstream steps" in mode_description
    assert "14 days" in expiry_description


def test_openapi_flow_step_update_uses_step_update_request_schema(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    create_schema = schemas.get("FlowStepCreateRequest", {})
    update_schema = schemas.get("FlowStepUpdateRequest", {})
    partial_update_schema = schemas.get("PartialFlowUpdateRequest", {})

    assert "id" not in create_schema.get("properties", {})
    update_id = update_schema.get("properties", {}).get("id", {})
    assert any(
        isinstance(option, dict) and option.get("format") == "uuid"
        for option in update_id.get("anyOf", [])
    )
    assert _schema_allows_null(update_id)

    steps_schema = partial_update_schema.get("properties", {}).get("steps", {})
    step_items: dict | None = None
    for option in steps_schema.get("anyOf", []):
        if isinstance(option, dict) and option.get("type") == "array":
            items = option.get("items", {})
            if isinstance(items, dict):
                step_items = items
                break
    assert step_items is not None
    assert step_items.get("$ref") == "#/components/schemas/FlowStepUpdateRequest"


def test_openapi_runtime_paths_expose_review_checkpoint_templates(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    runtime_paths = schemas.get("FlowRuntimePathsPublic", {}).get("properties", {})

    review_paths_ref = runtime_paths["review_checkpoints"]
    review_paths = _resolve_component_ref(openapi_spec, review_paths_ref)
    review_properties = review_paths.get("properties", {})

    assert review_paths.get("title") == "FlowReviewCheckpointRuntimePathsPublic"
    assert {
        "active_template",
        "edit_template",
        "approve_template",
        "reject_template",
        "resume_template",
    } <= set(review_properties)
    assert "{run_id}" in review_properties["active_template"]["description"]
    assert "{checkpoint_id}" in review_properties["edit_template"]["description"]
    assert "{checkpoint_id}" in review_properties["approve_template"]["description"]
    assert "{checkpoint_id}" in review_properties["reject_template"]["description"]
    assert "{checkpoint_id}" in review_properties["resume_template"]["description"]
    assert "current_payload_json" in review_properties["edit_template"]["description"]
    assert (
        "expected_checkpoint_revision"
        in review_properties["approve_template"]["description"]
    )
    assert (
        "expected_checkpoint_revision"
        in review_properties["resume_template"]["description"]
    )
    assert "upload_flow_file" not in runtime_paths
    assert (
        "step_inputs[step_id].file_ids"
        in runtime_paths["upload_step_runtime_file_template"]["description"]
    )
    assert (
        "same file id"
        in runtime_paths["upload_step_runtime_file_template"]["description"]
    )
    assert "{file_id}" in runtime_paths["delete_runtime_file_template"]["description"]
    assert (
        "409 conflict" in runtime_paths["delete_runtime_file_template"]["description"]
    )
    assert "committed before" in runtime_paths["create_run"]["description"]
    assert "immediately poll" in runtime_paths["create_run"]["description"]
    assert "{run_id}" in runtime_paths["cancel_run_template"]["description"]
    assert "{run_id}" in runtime_paths["rerun_step_template"]["description"]
    assert "{step_id}" in runtime_paths["rerun_step_template"]["description"]
    assert "{run_id}" in runtime_paths["redispatch_run_template"]["description"]
    assert (
        FLOW_EVIDENCE_SERVICE_KEY_PERMISSION_RECIPE
        in runtime_paths["evidence_template"]["description"]
    )
    assert "{run_id}" in runtime_paths["export_evidence_template"]["description"]
    assert "reason" in runtime_paths["export_evidence_template"]["description"]
    assert (
        "POST template" in runtime_paths["artifact_signed_url_template"]["description"]
    )
    assert (
        "SignedURLRequest"
        in runtime_paths["artifact_signed_url_template"]["description"]
    )


def test_openapi_runtime_paths_example_matches_operation_paths(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    runtime_schema = schemas.get("FlowRuntimePublic", {})
    example = runtime_schema.get("example", {})
    assert isinstance(example, dict)
    flow_id = str(example["id"])
    runtime_paths = example.get("runtime_paths", {})
    assert isinstance(runtime_paths, dict)

    assert runtime_paths == build_flow_runtime_paths(
        flow_id,
        api_prefix="/api/v1",
    ).model_dump(mode="json")
    assert _runtime_path_field_paths() == set(RUNTIME_PATH_FIELD_OPERATIONS)

    for field_path, operation in RUNTIME_PATH_FIELD_OPERATIONS.items():
        openapi_path = _path_for_operation_id_and_method(
            openapi_spec,
            operation_id=operation.operation_id,
            method=operation.method,
        )
        assert not openapi_path.startswith("/api/v1/flows/ai-builder")
        expected_path = openapi_path.replace("{id}", flow_id)
        if operation.query_suffix is not None:
            expected_path = f"{expected_path}{operation.query_suffix}"
        assert _runtime_path_value(runtime_paths, field_path) == expected_path


def test_openapi_flow_evidence_403_documents_service_key_permission_layers(
    openapi_spec: dict,
) -> None:
    for path in (
        "/api/v1/flows/{id}/runs/{run_id}/evidence/",
        "/api/v1/flows/{id}/runs/{run_id}/evidence/export",
    ):
        operation = _get_operation(openapi_spec, path, "get")
        forbidden = operation.get("responses", {}).get("403", {})
        description = forbidden.get("description", "")

        assert FLOW_EVIDENCE_SERVICE_KEY_PERMISSION_RECIPE in description
        assert "insufficient_scope" in description
        assert "insufficient_resource_permission" in description
        assert "flow_run_evidence_forbidden" in description


def test_openapi_runtime_discovery_response_schemas_are_closed(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    runtime_discovery_schemas = {
        "FlowReviewCheckpointRuntimePathsPublic",
        "FlowRuntimePathsPublic",
        "FlowRuntimePublic",
    }

    missing_closed_schema = [
        schema_name
        for schema_name in sorted(runtime_discovery_schemas)
        if schemas.get(schema_name, {}).get("additionalProperties") is not False
    ]

    assert missing_closed_schema == []


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
    approve_operation = _get_operation(
        openapi_spec,
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve/",
        "post",
    )
    reject_operation = _get_operation(
        openapi_spec,
        "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/",
        "post",
    )
    rerun_operation = _get_operation(
        openapi_spec,
        "/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/rerun/",
        "post",
    )

    active_description = active_operation.get("description", "")
    edit_description = edit_operation.get("description", "")
    approve_description = approve_operation.get("description", "")
    reject_description = reject_operation.get("description", "")
    resume_description = resume_operation.get("description", "")
    rerun_description = rerun_operation.get("description", "")

    assert "status` is `awaiting_review`" in active_description
    assert "step_snapshot_available" not in active_description
    assert "legacy checkpoint" not in active_description
    assert "without reading the mutable flow draft" in active_description
    assert "service-owned `sk_` key" in active_description
    assert "resource_permissions.flows = write" in active_description
    assert "rather than auto-approve" in active_description
    assert "same key" in active_description
    assert "submission deadline" in active_description
    assert "flow_review_expired" in active_description
    assert "background reconciler" in active_description
    assert "approval happens before `expires_at`" in active_description
    assert "full corrected `current_payload_json`, not a patch" in edit_description
    assert "typed_io_contract_violation" in edit_description
    assert "payload_field" in edit_description
    assert "flow_review_stale_revision" in edit_description
    assert "resource_permissions.flows = write" in edit_description
    assert "before the checkpoint `expires_at` deadline" in edit_description
    assert "committed before the response" in edit_description
    assert "returned id or revision" in edit_description
    assert "resume remains valid" in approve_description
    assert "before the checkpoint `expires_at` deadline" in reject_description
    assert "202 Accepted" in resume_description
    assert "Idempotency-Key" in resume_description
    assert "approved checkpoint revision" in resume_description
    assert "after the original `expires_at`" in resume_description
    assert "resource_permissions.flows = write" in resume_description
    assert "committed before the response" in resume_description
    assert "service-key principals may rerun only their own runs" in rerun_description
    assert "stable service\nprincipal ownership" in rerun_description
    assert "committed before the response" in rerun_description

    edit_400 = edit_operation["responses"]["400"]
    edit_400_text = str(edit_400)
    assert "typed_io_contract_violation" in edit_400_text
    assert "context.step_id" in edit_400_text
    assert "context.payload_field" in edit_400_text
    edit_400_examples = edit_400["content"]["application/json"]["examples"]
    assert (
        edit_400_examples["typed_io_contract_violation"]["value"]["code"]
        == "typed_io_contract_violation"
    )
    assert (
        edit_400_examples["flow_review_stale_revision"]["value"]["code"]
        == "flow_review_stale_revision"
    )
    assert (
        "current_checkpoint_revision"
        in edit_400_examples["flow_review_stale_revision"]["value"]["context"]
    )
    expired_context = edit_400_examples["flow_review_expired"]["value"]["context"]
    assert "checkpoint_id" in expired_context
    assert expired_context["state"] == "awaiting_review"
    assert "expires_at" in expired_context

    edit_200_example = edit_operation["responses"]["200"]["content"][
        "application/json"
    ]["example"]
    assert edit_200_example["state"] == "edited"
    assert edit_200_example["revision"] == 2
    assert edit_200_example["edited_at"] is not None
    assert edit_200_example["current_payload_json"] == {"text": "Edited answer."}

    approve_200_example = approve_operation["responses"]["200"]["content"][
        "application/json"
    ]["example"]
    assert approve_200_example["state"] == "approved"
    assert approve_200_example["revision"] == 3
    assert approve_200_example["approved_at"] is not None

    reject_200_example = reject_operation["responses"]["200"]["content"][
        "application/json"
    ]["example"]
    assert reject_200_example["state"] == "rejected"
    assert reject_200_example["revision"] == 3
    assert reject_200_example["rejected_at"] is not None

    resume_request_example = (
        openapi_spec.get("components", {})
        .get("schemas", {})
        .get("FlowRunReviewCheckpointResumeRequest", {})
        .get("example", {})
    )
    resume_202_example = resume_operation["responses"]["202"]["content"][
        "application/json"
    ]["example"]
    assert resume_request_example["expected_checkpoint_revision"] == 3
    assert resume_202_example["checkpoint"]["state"] == "resumed"
    assert resume_202_example["checkpoint"]["revision"] == 4
    assert resume_202_example["checkpoint"]["approved_at"] is not None
    assert resume_202_example["checkpoint"]["resumed_at"] is not None
    assert resume_202_example["run"]["status"] == "queued"


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
    parameters = operation.get("parameters", [])
    idempotency_parameters = [
        parameter
        for parameter in parameters
        if isinstance(parameter, dict)
        and parameter.get("name") == "Idempotency-Key"
        and parameter.get("in") == "header"
    ]

    assert len(idempotency_parameters) == 1
    parameter = idempotency_parameters[0]
    assert parameter.get("required") is True
    assert parameter.get("schema", {}).get("type") == "string"
    assert (
        parameter.get("description")
        == "Required caller-supplied idempotency key for review resume retries."
    )
    for path_parameter_name in ("id", "run_id", "checkpoint_id"):
        path_parameter = _find_parameter(
            operation, name=path_parameter_name, location="path"
        )
        assert path_parameter.get("required") is True


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


def test_openapi_flow_run_public_exposes_structured_error(openapi_spec: dict) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    run_properties = schemas.get("FlowRunPublic", {}).get("properties", {})
    assert "error_message" not in run_properties

    error_property = run_properties.get("error", {})
    error_options = error_property.get("anyOf") or error_property.get("oneOf") or []
    structured_error_ref = next(
        option
        for option in error_options
        if isinstance(option, dict) and option.get("type") != "null"
    )
    error_schema = _resolve_component_ref(openapi_spec, structured_error_ref)

    assert error_schema.get("title") == "FlowRunError"
    assert {"code", "message"}.issubset(set(error_schema.get("required", [])))
    assert "Clients should branch on `code`" in error_schema.get("description", "")

    details_property = error_schema.get("properties", {}).get("details", {})
    details_options = (
        details_property.get("anyOf") or details_property.get("oneOf") or []
    )
    structured_details_ref = next(
        option
        for option in details_options
        if isinstance(option, dict) and option.get("type") != "null"
    )
    details_schema = _resolve_component_ref(openapi_spec, structured_details_ref)
    assert details_schema.get("title") == "FlowRunErrorDetails"
    assert details_schema.get("additionalProperties") is False
    assert set(details_schema.get("properties", {})) == {"step_description"}


def test_openapi_flow_run_public_does_not_expose_legacy_user_mirror(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    run_properties = schemas.get("FlowRunPublic", {}).get("properties", {})

    assert "user_id" not in run_properties


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
        "input_payload",
        "root_step_input_override",
        "root_step_input_override_requested",
        "requested_by_principal_type",
        "requested_by_user_id",
        "requested_by_service_principal",
    }
    assert "input_payload_json" not in rerun_operation.get("properties", {})
    assert "step_inputs_json" not in rerun_operation.get("properties", {})
    assert "requested_by_service_id" not in rerun_operation.get("properties", {})
    root_step_input_override_property = rerun_operation.get("properties", {}).get(
        "root_step_input_override", {}
    )
    root_step_input_override_ref = next(
        (
            option
            for option in root_step_input_override_property.get("anyOf", [])
            if isinstance(option, dict) and "$ref" in option
        ),
        root_step_input_override_property,
    )
    root_step_input_override = _resolve_component_ref(
        openapi_spec,
        root_step_input_override_ref,
    )
    assert root_step_input_override.get("title") == (
        "FlowRunRerunStepInputOverridePublic"
    )
    assert set(root_step_input_override.get("properties", {})) == {
        "step_id",
        "file_ids",
    }
    assert root_step_input_override.get("required") == ["step_id", "file_ids"]
    assert (
        "explicitly cleared"
        in root_step_input_override["properties"]["file_ids"]["description"]
    )

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


def _non_null_schema(schema: dict) -> dict:
    for option in schema.get("anyOf", []) or []:
        if isinstance(option, dict) and option.get("type") != "null":
            return option
    return schema


def test_openapi_http_test_schema_uses_typed_transport_contract(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    request_properties = schemas["HttpTestRequest"]["properties"]
    response_properties = schemas["HttpTestResponse"]["properties"]

    assert request_properties["config"] == {
        "$ref": "#/components/schemas/HttpAuthoredConfig"
    }
    assert set(_extract_enum_values(openapi_spec, request_properties["method"])) == {
        "GET",
        "POST",
    }

    preview_schema = _resolve_component_ref(
        openapi_spec, _non_null_schema(response_properties["request_preview"])
    )
    assert set(preview_schema["required"]) == {
        "body_preview",
        "headers",
        "method",
        "url",
    }
    assert set(
        _extract_enum_values(openapi_spec, preview_schema["properties"]["method"])
    ) == {
        "GET",
        "POST",
    }

    error_values = _extract_enum_values(openapi_spec, response_properties["error_code"])
    assert "HTTP_INVALID_URL" in error_values
    assert "HTTP_VARIABLE_RESOLUTION_FAILED" in error_values
    assert "HTTP_UNRESOLVED_STORED_SECRET" in error_values
    assert "INVALID_CONFIG" not in error_values
    assert "HTTP_SSRF_BLOCKED" not in error_values

    bearer_token_schema = schemas["HttpAuthBearer"]["properties"]["token"]
    secret_options = [
        _resolve_component_ref(openapi_spec, option)
        for option in bearer_token_schema.get("anyOf", [])
        if isinstance(option, dict)
    ]
    assert any(
        option.get("properties", {}).get("$secret", {}).get("const") == "stored"
        for option in secret_options
    )
    assert set(
        _extract_enum_values(
            openapi_spec, schemas["HttpAuthoredConfig"]["properties"]["response_format"]
        )
    ) == {"text", "json"}


def test_openapi_flow_runtime_mutation_requests_reject_unknown_fields(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    strict_request_schemas = {
        "FlowAssistantCreateRequest",
        "FlowCreateRequest",
        "FlowStepCreateRequest",
        "FlowStepUpdateRequest",
        "HttpTestRequest",
        "PartialFlowUpdateRequest",
        "FlowRunCreateRequest",
        "FlowRunReviewCheckpointApproveRequest",
        "FlowRunReviewCheckpointEditRequest",
        "FlowRunReviewCheckpointRejectRequest",
        "FlowRunReviewCheckpointResumeRequest",
        "FlowRunStepRerunRequest",
        "StepRunInput",
    }

    missing_strict_contract = [
        schema_name
        for schema_name in sorted(strict_request_schemas)
        if schemas.get(schema_name, {}).get("additionalProperties") is not False
    ]

    assert missing_strict_contract == []


def _integer_schema_option(schema: dict) -> dict:
    if schema.get("type") == "integer":
        return schema
    for option in schema.get("anyOf", []) or []:
        if isinstance(option, dict) and option.get("type") == "integer":
            return option
    pytest.fail(f"Schema does not expose an integer option: {schema}")


def test_openapi_flow_retention_days_documents_public_range(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})

    for schema_name in (
        "FlowCreateRequest",
        "PartialFlowUpdateRequest",
        "FlowSparsePublic",
        "FlowPublic",
    ):
        properties = schemas.get(schema_name, {}).get("properties", {})
        retention_schema = properties.get("data_retention_days", {})
        integer_schema = _integer_schema_option(retention_schema)

        assert integer_schema.get("minimum") == 1
        assert integer_schema.get("maximum") == 2555
        assert _schema_allows_null(retention_schema)
        assert "full Flow run and step history" in str(
            retention_schema.get("description", "")
        )


def test_openapi_create_flow_run_documents_top_level_file_ids_error(
    openapi_spec: dict,
) -> None:
    operation = _get_operation(openapi_spec, "/api/v1/flows/{id}/runs/", "post")
    bad_request_response = operation.get("responses", {}).get("400", {})
    description = str(bad_request_response.get("description", ""))
    operation_description = str(operation.get("description", ""))

    assert "flow_run_top_level_file_ids_not_supported" in description
    assert "flow_run_top_level_file_ids_not_supported" in operation_description
    assert "step_inputs[step_id].file_ids" in operation_description


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


@pytest.mark.parametrize(
    ("path", "method", "expected_codes"),
    [
        (
            "/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/rerun/",
            "post",
            frozenset(
                {
                    FlowApiErrorCode.RUN_RERUN_REASON_REQUIRED.value,
                    FlowApiErrorCode.RUN_RERUN_REASON_TOO_LONG.value,
                    FlowApiErrorCode.RUN_RERUN_STALE_REVISION.value,
                    FlowApiErrorCode.RUN_RERUN_INVALID_TRANSITION.value,
                    FlowApiErrorCode.RUN_RERUN_STEP_NOT_FOUND.value,
                    FlowApiErrorCode.RUN_RERUN_STEP_INCOMPLETE.value,
                    FlowApiErrorCode.RUN_RERUN_STEP_INPUTS_INVALID.value,
                }
            ),
        ),
        (
            "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/",
            "patch",
            frozenset(
                {
                    FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
                    FlowApiErrorCode.REVIEW_STALE_REVISION.value,
                    FlowApiErrorCode.REVIEW_EXPIRED.value,
                    FlowApiErrorCode.REVIEW_NOT_ACTIVE.value,
                    FlowApiErrorCode.REVIEW_STEP_RESULT_NOT_FOUND.value,
                }
            ),
        ),
        (
            "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve/",
            "post",
            frozenset(
                {
                    FlowApiErrorCode.REVIEW_STALE_REVISION.value,
                    FlowApiErrorCode.REVIEW_EXPIRED.value,
                    FlowApiErrorCode.REVIEW_NOT_ACTIVE.value,
                }
            ),
        ),
        (
            "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/",
            "post",
            frozenset(
                {
                    FlowApiErrorCode.REVIEW_STALE_REVISION.value,
                    FlowApiErrorCode.REVIEW_EXPIRED.value,
                    FlowApiErrorCode.REVIEW_NOT_ACTIVE.value,
                    FlowApiErrorCode.REVIEW_REJECT_REASON_REQUIRED.value,
                    FlowApiErrorCode.REVIEW_REJECT_REASON_TOO_LONG.value,
                }
            ),
        ),
        (
            "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/",
            "post",
            frozenset(
                {
                    FlowApiErrorCode.REVIEW_IDEMPOTENCY_KEY_REQUIRED.value,
                    FlowApiErrorCode.RUN_INVALID_IDEMPOTENCY_KEY.value,
                    FlowApiErrorCode.REVIEW_STALE_REVISION.value,
                    FlowApiErrorCode.REVIEW_EXPIRED.value,
                    FlowApiErrorCode.REVIEW_NOT_ACTIVE.value,
                    FlowApiErrorCode.REVIEW_NOT_APPROVED.value,
                    FlowApiErrorCode.REVIEW_ALREADY_RESUMED.value,
                    FlowApiErrorCode.REVIEW_REJECTED.value,
                    FlowApiErrorCode.REVIEW_CANCELLED.value,
                }
            ),
        ),
    ],
)
def test_openapi_flow_runtime_mutation_error_examples_match_public_codes(
    openapi_spec: dict,
    path: str,
    method: str,
    expected_codes: frozenset[str],
) -> None:
    operation = _get_operation(openapi_spec, path, method)
    response = operation.get("responses", {}).get("400", {})
    description = str(response.get("description", ""))
    examples = _error_example_values(operation, status_code="400")

    assert set(examples) == set(expected_codes)
    for code, example in examples.items():
        assert example.get("code") == code
        assert code in description

    if FlowApiErrorCode.RUN_RERUN_STEP_INPUTS_INVALID.value in examples:
        context = examples[FlowApiErrorCode.RUN_RERUN_STEP_INPUTS_INVALID.value].get(
            "context", {}
        )
        assert "step_ids" in context
    if FlowApiErrorCode.RUN_INVALID_IDEMPOTENCY_KEY.value in examples:
        context = examples[FlowApiErrorCode.RUN_INVALID_IDEMPOTENCY_KEY.value].get(
            "context", {}
        )
        assert context.get("max_length") == 255
    if path.endswith("/resume/"):
        context = examples[FlowApiErrorCode.REVIEW_NOT_ACTIVE.value].get("context", {})
        assert context.get("status") == "cancelled"


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


def test_openapi_runtime_file_upload_multipart_schema_uses_upload_file_field(
    openapi_spec: dict,
) -> None:
    targets = ("/api/v1/flows/{id}/steps/{step_id}/runtime-files/",)
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

    upload_paths = ("/api/v1/flows/{id}/steps/{step_id}/runtime-files/",)
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


def test_openapi_flow_runtime_step_identity_fields_are_required(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    step_result = schemas.get("FlowRunStepPublic", {})
    step_attempt = schemas.get("FlowStepAttemptPublic", {})

    for field_name in ("flow_run_id", "flow_id", "tenant_id", "step_id"):
        _assert_required_uuid_property(step_result, field_name)
    _assert_required_uuid_property(step_attempt, "step_id")


def test_openapi_flow_run_step_public_database_id_stays_nullable(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    step_result = schemas.get("FlowRunStepPublic", {})
    id_property = step_result.get("properties", {}).get("id", {})

    assert "id" not in step_result.get("required", [])
    assert _schema_allows_null(id_property)


def test_openapi_flow_run_step_public_exposes_runtime_input_file_ids(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    step_result = schemas.get("FlowRunStepPublic", {})
    runtime_input_file_ids = step_result.get("properties", {}).get(
        "runtime_input_file_ids", {}
    )
    items = runtime_input_file_ids.get("items", {})

    assert "runtime_input_file_ids" not in step_result.get("required", [])
    assert runtime_input_file_ids.get("type") == "array"
    assert runtime_input_file_ids.get("description") == (
        "File ids submitted as runtime input for the current attempt of this step "
        "result."
    )
    assert items.get("type") == "string"
    assert items.get("format") == "uuid"


def test_openapi_flow_run_step_public_exposes_nullable_error_code(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    step_result = schemas.get("FlowRunStepPublic", {})
    error_code = step_result.get("properties", {}).get("error_code", {})

    assert "error_code" not in step_result.get("required", [])
    assert _schema_allows_null(error_code)
    assert "Clients should branch on this code" in error_code.get("description", "")


def test_openapi_flow_run_step_diagnostics_are_typed(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    step_result = schemas.get("FlowRunStepPublic", {})
    diagnostics_schema = schemas.get("FlowStepDiagnosticPublic", {})
    diagnostics_property = step_result.get("properties", {}).get("diagnostics", {})
    diagnostics_items = _resolve_component_ref(
        openapi_spec, diagnostics_property.get("items", {})
    )

    assert diagnostics_schema.get("additionalProperties") is False
    assert diagnostics_items.get("title") == "FlowStepDiagnosticPublic"
    assert set(diagnostics_items.get("required", [])) == {"code", "message"}
    assert diagnostics_items.get("additionalProperties") is False

    properties = diagnostics_items.get("properties", {})
    assert _extract_enum_values(openapi_spec, properties.get("severity", {})) == {
        "info",
        "warning",
        "error",
    }
    assert properties.get("severity", {}).get("default") == "warning"


def test_openapi_non_result_step_identity_exceptions_stay_nullable(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})

    for component_name in ("FlowRunError", "FlowRunDebugStep"):
        component = schemas.get(component_name, {})
        step_id_property = component.get("properties", {}).get("step_id", {})
        assert "step_id" not in component.get("required", [])
        assert _schema_allows_null(step_id_property)


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
    ) == {"flow-evidence-export.v6"}
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


def test_openapi_flow_evidence_export_documents_typed_summary_review_impact(
    openapi_spec: dict,
) -> None:
    operation = _get_operation(
        openapi_spec,
        "/api/v1/flows/{id}/runs/{run_id}/evidence/export",
        "get",
    )
    response = operation.get("responses", {}).get("200", {})
    schema = response.get("content", {}).get("application/json", {}).get("schema", {})
    export_response = _resolve_component_ref(openapi_spec, schema)
    export_properties = export_response.get("properties", {})
    summary_schema = export_properties.get("summary_typed", {})
    assert summary_schema.get("description")
    summary = _resolve_component_ref(openapi_spec, summary_schema)

    assert summary.get("title") == "EvidenceExportSummary"
    assert summary.get("additionalProperties") is False
    assert set(summary.get("properties", {})) == {
        "status",
        "trace_id",
        "steps_count",
        "completed_steps",
        "failed_steps",
        "attempts_count",
        "artifacts_count",
        "duration_ms",
        "models_used",
        "review_checkpoints",
        "final_output",
        "step_overview",
    }

    step_overview_items = (
        summary.get("properties", {}).get("step_overview", {}).get("items", {})
    )
    step_overview = _resolve_component_ref(openapi_spec, step_overview_items)
    assert step_overview.get("title") == "EvidenceStepOverview"
    assert step_overview.get("additionalProperties") is False
    step_overview_properties = step_overview.get("properties", {})
    assert set(step_overview_properties) == {
        "step_order",
        "step_id",
        "user_description",
        "status",
        "attempts_count",
        "retries",
        "duration_ms",
        "models_used",
        "artifact_names",
        "result_output_kind",
        "output_summary",
        "configured_input_type",
        "configured_output_type",
        "review_impact",
    }

    review_impact = _resolve_component_ref(
        openapi_spec, step_overview_properties["review_impact"]
    )
    assert review_impact.get("title") == "EvidenceStepReviewImpact"
    assert review_impact.get("additionalProperties") is False
    review_impact_properties = review_impact.get("properties", {})
    assert set(review_impact_properties) == {
        "checkpoint_count",
        "any_edited",
        "any_resumed",
        "any_output_changed",
        "last_event",
        "events",
    }

    review_event_items = review_impact_properties["events"].get("items", {})
    review_event = _resolve_component_ref(openapi_spec, review_event_items)
    assert review_event.get("title") == "EvidenceStepReviewEvent"
    assert review_event.get("additionalProperties") is False
    review_event_properties = review_event.get("properties", {})
    assert set(review_event_properties) == {
        "checkpoint_id",
        "state",
        "decision",
        "edited",
        "resumed",
        "attempt_no",
        "revision",
        "output_changed",
    }
    assert _extract_enum_values(openapi_spec, review_event_properties["state"]) == {
        "awaiting_review",
        "edited",
        "approved",
        "rejected",
        "resumed",
        "cancelled",
        "expired",
    }
    assert _extract_enum_values(openapi_spec, review_event_properties["decision"]) == {
        "approved",
        "rejected",
        "cancelled",
    }


def test_openapi_flow_error_responses_include_general_error_examples(
    openapi_spec: dict,
) -> None:
    paths = openapi_spec.get("paths", {})
    for (path, method), status_codes in REQUIRED_TYPED_ERROR_CODES.items():
        responses = paths[path][method].get("responses", {})
        for status_code in status_codes:
            response = responses.get(status_code, {})
            app_json = response.get("content", {}).get("application/json", {})
            examples: list[object] = []
            if "example" in app_json:
                examples.append(app_json["example"])
            for example_object in app_json.get("examples", {}).values():
                if isinstance(example_object, dict) and "value" in example_object:
                    examples.append(example_object["value"])

            assert examples, (
                f"{method.upper()} {path} {status_code} must include JSON example"
            )
            for example in examples:
                assert isinstance(example, dict), (
                    f"{method.upper()} {path} {status_code} example must be an object"
                )
                assert (
                    isinstance(example.get("message"), str)
                    and example["message"].strip()
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


def test_openapi_runtime_file_upload_error_codes_are_machine_readable(
    openapi_spec: dict,
) -> None:
    responses = (
        openapi_spec.get("paths", {})
        .get("/api/v1/flows/{id}/steps/{step_id}/runtime-files/", {})
        .get("post", {})
        .get("responses", {})
    )
    upload_400_examples = (
        responses.get("400", {})
        .get("content", {})
        .get("application/json", {})
        .get("examples", {})
    )
    upload_400_codes = {
        example.get("value", {}).get("code")
        for example in upload_400_examples.values()
        if isinstance(example, dict)
    }
    assert upload_400_codes == {
        "flow_not_published",
        "flow_run_unknown_step_input",
        "flow_run_runtime_input_disabled",
        "flow_runtime_file_empty",
    }

    expected_single_examples = {
        "413": "file_too_large",
        "415": "unsupported_media_type",
    }
    for status_code, error_code in expected_single_examples.items():
        example = (
            responses.get(status_code, {})
            .get("content", {})
            .get("application/json", {})
            .get("example", {})
        )
        assert example.get("code") == error_code, (
            "/flows/{id}/steps/{step_id}/runtime-files/ "
            f"{status_code} should expose code '{error_code}'"
        )


def test_openapi_runtime_file_delete_contract_is_machine_readable(
    openapi_spec: dict,
) -> None:
    operation = (
        openapi_spec.get("paths", {})
        .get("/api/v1/flows/{id}/runtime-files/{file_id}/", {})
        .get("delete", {})
    )
    responses = operation.get("responses", {})
    success = responses.get("204", {})
    assert "content" not in success
    assert operation.get("operationId") == "delete_flow_runtime_file"

    conflict_example = (
        responses.get("409", {})
        .get("content", {})
        .get("application/json", {})
        .get("example", {})
    )
    assert conflict_example.get("intric_error_code") == int(ErrorCodes.CONFLICT)
    assert conflict_example.get("code") == "flow_runtime_file_attached"

    parameters = operation.get("parameters", [])
    names = {param.get("name") for param in parameters if isinstance(param, dict)}
    assert {"id", "file_id"} <= names


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
    assert "service-owned `sk_` key" in operation_description
    assert "steps_requiring_review" in operation_description
    assert "resource_permissions.flows = write" in operation_description
    assert "rather than auto-approve" in operation_description
    assert "same key" in operation_description
    assert "matching run row is retained" in operation_description.lower()
    assert (
        "committed before this endpoint returns `201 Created`" in operation_description
    )
    assert "immediately poll" in operation_description

    conflict_response = operation.get("responses", {}).get("400", {})
    assert "flow_run_idempotency_conflict" in str(
        conflict_response.get("description", "")
    )
    assert "flow_run_required_step_input_missing" in str(
        conflict_response.get("description", "")
    )
    assert "context.step_ids" in str(conflict_response.get("description", ""))


def test_openapi_flow_run_forbidden_docs_list_current_codes(
    openapi_spec: dict,
) -> None:
    operation = _get_operation(openapi_spec, "/api/v1/flows/{id}/runs/", "post")
    forbidden_description = str(
        operation.get("responses", {}).get("403", {}).get("description", "")
    )

    assert "insufficient_scope" in forbidden_description
    assert "flow_run_access_denied" in forbidden_description
    assert "flow_service_key_principal_not_supported" in forbidden_description


def test_openapi_flows_tag_guides_api_key_human_review(openapi_spec: dict) -> None:
    tags = {tag.get("name"): tag for tag in openapi_spec.get("tags", [])}
    description = str(tags["flows"].get("description", ""))

    assert "human-review checkpoints" in description
    assert "service-owned API-key integrations" in description
    assert "GET /flows/{id}/published/" in description
    assert "GET /flows/{id}/run-contract/" in description
    assert "steps_requiring_review" in description


def test_openapi_flow_authoring_docs_separate_draft_and_service_key_runtime(
    openapi_spec: dict,
) -> None:
    list_description = str(
        _get_operation(openapi_spec, "/api/v1/flows/", "get").get("description", "")
    )
    draft_description = str(
        _get_operation(openapi_spec, "/api/v1/flows/{id}/", "get").get(
            "description", ""
        )
    )
    published_description = str(
        _get_operation(openapi_spec, "/api/v1/flows/{id}/published/", "get").get(
            "description", ""
        )
    )

    assert "published-flow discovery" in list_description
    assert "/published/" in list_description
    assert "runtime paths" in list_description
    assert "Admin service-key principals" in draft_description
    assert "current draft definition" in draft_description
    assert "Read and write service-key clients" in draft_description
    assert "/published/" in draft_description
    assert "external webapps" in published_description
    assert "review checkpoints" in published_description
    assert "artifact/evidence retrieval" in published_description


def test_openapi_get_flow_service_key_admin_required_points_to_published_runtime(
    openapi_spec: dict,
) -> None:
    operation = _get_operation(openapi_spec, "/api/v1/flows/{id}/", "get")
    response = operation.get("responses", {}).get("403", {})
    examples = (
        response.get("content", {}).get("application/json", {}).get("examples", {})
    )
    assert "flow_service_key_principal_not_supported" not in examples
    service_key_example = examples[FlowApiErrorCode.SERVICE_KEY_ADMIN_REQUIRED.value][
        "value"
    ]
    context = service_key_example["context"]
    hint = context["runtime_endpoint_hint"]

    assert service_key_example["intric_error_code"] == 9001
    assert (
        service_key_example["code"] == FlowApiErrorCode.SERVICE_KEY_ADMIN_REQUIRED.value
    )
    assert context["auth_layer"] == "service_key_principal"
    assert context["capability"] == "view_current_definition"
    assert context["required_role"] == "admin"
    assert hint == {
        "key": "published_flow_runtime",
        "description": "Use the published runtime projection for service-key Flow clients.",
        "endpoint_template": _path_for_operation_id(
            openapi_spec,
            "get_published_flow_runtime",
        ),
    }


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
