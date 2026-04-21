from __future__ import annotations

import pytest

from intric.server.main import get_application


@pytest.fixture(scope="module")
def openapi_spec() -> dict:
    app = get_application()
    return app.openapi()


REQUIRED_PATHS: dict[str, set[str]] = {
    "/api/v1/flows/ai-builder/sessions": {"get", "post"},
    "/api/v1/flows/ai-builder/sessions/{session_id}": {"get"},
    "/api/v1/flows/ai-builder/sessions/{session_id}/messages": {"post"},
    "/api/v1/flows/ai-builder/sessions/{session_id}/models": {"get"},
    "/api/v1/flows/ai-builder/sessions/{session_id}/plans": {"get"},
    "/api/v1/flows/ai-builder/sessions/{session_id}/cancel": {"post"},
    "/api/v1/flows/ai-builder/plans/{plan_id}": {"get"},
    "/api/v1/flows/ai-builder/plans/{plan_id}/approve": {"post"},
    "/api/v1/flows/ai-builder/plans/{plan_id}/apply": {"post"},
    "/api/v1/flows/ai-builder/plans/{plan_id}/revise": {"post"},
}

REQUIRED_SCHEMAS = {
    "ApplyPlanRequest",
    "ApplyResultResponse",
    "CreateSessionRequest",
    "PlanApprovalResponse",
    "PlanResponse",
    "RevisePlanRequest",
    "SendMessageRequest",
    "SessionListResponse",
    "SessionModelsResponse",
    "SessionPlansResponse",
    "SessionResponse",
    "SessionTelemetrySummary",
}

REQUIRED_OPERATION_IDS: dict[tuple[str, str], str] = {
    ("/api/v1/flows/ai-builder/sessions", "get"): "list_ai_builder_sessions",
    ("/api/v1/flows/ai-builder/sessions", "post"): "create_ai_builder_session",
    ("/api/v1/flows/ai-builder/sessions/{session_id}", "get"): "get_ai_builder_session",
    (
        "/api/v1/flows/ai-builder/sessions/{session_id}/messages",
        "post",
    ): "send_ai_builder_message",
    (
        "/api/v1/flows/ai-builder/sessions/{session_id}/models",
        "get",
    ): "get_ai_builder_models",
    (
        "/api/v1/flows/ai-builder/sessions/{session_id}/plans",
        "get",
    ): "list_ai_builder_session_plans",
    (
        "/api/v1/flows/ai-builder/sessions/{session_id}/cancel",
        "post",
    ): "cancel_ai_builder_session",
    ("/api/v1/flows/ai-builder/plans/{plan_id}", "get"): "get_ai_builder_plan",
    (
        "/api/v1/flows/ai-builder/plans/{plan_id}/approve",
        "post",
    ): "approve_ai_builder_plan",
    ("/api/v1/flows/ai-builder/plans/{plan_id}/apply", "post"): "apply_ai_builder_plan",
    (
        "/api/v1/flows/ai-builder/plans/{plan_id}/revise",
        "post",
    ): "revise_ai_builder_plan",
}


def test_openapi_ai_builder_paths_present(openapi_spec: dict) -> None:
    paths = openapi_spec.get("paths", {})
    for path, methods in REQUIRED_PATHS.items():
        assert path in paths, f"Missing path {path}"
        available = {method.lower() for method in paths[path].keys()}
        missing = {method.lower() for method in methods} - available
        assert not missing, f"Missing methods for {path}: {sorted(missing)}"


def test_openapi_ai_builder_operation_ids_are_pinned(openapi_spec: dict) -> None:
    paths = openapi_spec.get("paths", {})
    for (path, method), expected_operation_id in REQUIRED_OPERATION_IDS.items():
        operation = paths[path][method]
        assert operation.get("operationId") == expected_operation_id


def test_openapi_ai_builder_operations_have_docs(openapi_spec: dict) -> None:
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


def test_openapi_ai_builder_required_schemas_present(openapi_spec: dict) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    missing = REQUIRED_SCHEMAS - set(schemas)
    assert not missing, f"Missing AI Builder schemas: {sorted(missing)}"


def test_openapi_session_response_includes_telemetry_field(openapi_spec: dict) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    session_response = schemas["SessionResponse"]
    telemetry_property = session_response["properties"].get("telemetry")
    assert telemetry_property is not None


def test_openapi_revise_plan_request_is_keep_current_only(openapi_spec: dict) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    revise_schema = schemas["RevisePlanRequest"]
    type_schema = revise_schema["properties"]["type"]
    allowed_values = type_schema.get("enum")
    if allowed_values is None:
        allowed_values = [type_schema.get("const")]
    assert allowed_values == ["keep_current_description"]


def test_openapi_revise_plan_docs_do_not_advertise_regenerate(
    openapi_spec: dict,
) -> None:
    operation = openapi_spec["paths"][
        "/api/v1/flows/ai-builder/plans/{plan_id}/revise"
    ]["post"]
    description = operation.get("description", "")
    assert "keep_current_description" in description
    assert "regenerate_description" not in description
