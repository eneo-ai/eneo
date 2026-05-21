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
    "AIBuilderDoneEvent",
    "AIBuilderErrorEvent",
    "AIBuilderPlanEventData",
    "AIBuilderPlanEvent",
    "AIBuilderQuestionEvent",
    "AIBuilderRequirementsSummaryEvent",
    "AIBuilderStatusEvent",
    "AIBuilderTextEvent",
    "AIBuilderUsageEvent",
    "BuilderPlanEditResult",
    "CompiledEditResult",
    "ApplyPlanRequest",
    "ApplyResultResponse",
    "CreateSessionRequest",
    "FlowEditDiff",
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

AI_BUILDER_STREAM_EVENT_REFS = {
    "text": "#/components/schemas/AIBuilderTextEvent",
    "status": "#/components/schemas/AIBuilderStatusEvent",
    "question": "#/components/schemas/AIBuilderQuestionEvent",
    "requirements_summary": "#/components/schemas/AIBuilderRequirementsSummaryEvent",
    "plan": "#/components/schemas/AIBuilderPlanEvent",
    "usage": "#/components/schemas/AIBuilderUsageEvent",
    "error": "#/components/schemas/AIBuilderErrorEvent",
    "done": "#/components/schemas/AIBuilderDoneEvent",
}


def _schema_refs(schema: object) -> set[str]:
    refs: set[str] = set()
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if isinstance(ref, str):
            refs.add(ref)
        for value in schema.values():
            refs.update(_schema_refs(value))
    elif isinstance(schema, list):
        for value in schema:
            refs.update(_schema_refs(value))
    return refs


def _direct_one_of_refs(schema: object) -> set[str]:
    if not isinstance(schema, dict):
        return set()
    one_of = schema.get("oneOf")
    if not isinstance(one_of, list):
        return set()
    refs: set[str] = set()
    for item in one_of:
        if isinstance(item, dict) and isinstance(item.get("$ref"), str):
            refs.add(item["$ref"])
    return refs


def _send_message_stream_content(openapi_spec: dict) -> dict:
    operation = openapi_spec["paths"][
        "/api/v1/flows/ai-builder/sessions/{session_id}/messages"
    ]["post"]
    return operation["responses"]["200"]["content"]


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


def test_openapi_plan_response_and_plan_event_share_edit_result_schema(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    plan_response = schemas["PlanResponse"]
    plan_event = schemas["AIBuilderPlanEventData"]

    assert "#/components/schemas/BuilderPlanEditResult" in _schema_refs(
        plan_response["properties"]["edit_result_json"]
    )
    assert "#/components/schemas/BuilderPlanEditResult" in _schema_refs(
        plan_event["properties"]["edit_result_json"]
    )
    assert not {
        "edit_diff",
        "edit_confidence",
        "edit_warnings",
        "edit_advisories",
        "edit_risk_flags",
    }.intersection(plan_event["properties"])


def test_openapi_ai_builder_sse_plan_event_payload_is_typed(openapi_spec: dict) -> None:
    schema = openapi_spec["components"]["schemas"]["AIBuilderPlanEvent"]

    assert "#/components/schemas/AIBuilderPlanEventData" in _schema_refs(schema)


def test_openapi_ai_builder_sse_event_stream_is_discriminated(
    openapi_spec: dict,
) -> None:
    schema = _send_message_stream_content(openapi_spec)["text/event-stream"]["schema"]

    assert schema["discriminator"]["propertyName"] == "event"
    assert schema["discriminator"]["mapping"] == AI_BUILDER_STREAM_EVENT_REFS
    assert _direct_one_of_refs(schema) == set(AI_BUILDER_STREAM_EVENT_REFS.values())


def test_openapi_ai_builder_sse_stream_uses_only_event_wrappers(
    openapi_spec: dict,
) -> None:
    schema = _send_message_stream_content(openapi_spec)["text/event-stream"]["schema"]

    assert _direct_one_of_refs(schema) == set(AI_BUILDER_STREAM_EVENT_REFS.values())
    assert not {
        "#/components/schemas/StructuredQuestionOptionPayload",
        "#/components/schemas/KeyDecisionPayload",
        "#/components/schemas/RequirementsSummaryPayload",
        "#/components/schemas/AIBuilderPublicError",
    }.intersection(_direct_one_of_refs(schema))


def test_openapi_ai_builder_stream_response_does_not_advertise_json(
    openapi_spec: dict,
) -> None:
    assert set(_send_message_stream_content(openapi_spec)) == {"text/event-stream"}


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
