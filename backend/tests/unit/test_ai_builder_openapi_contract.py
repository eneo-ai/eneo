from __future__ import annotations

import pytest

from eneo.server.main import get_application


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
    "AIBuilderConversationMessage",
    "AIBuilderDoneEvent",
    "AIBuilderDiagnosticContext",
    "AIBuilderErrorEvent",
    "AIBuilderPlanEventData",
    "AIBuilderPlanEvent",
    "AIBuilderQuestionEvent",
    "AIBuilderRequirementsSummaryEvent",
    "AIBuilderStatus",
    "AIBuilderStatusEvent",
    "AIBuilderTextEvent",
    "AIBuilderTurnLifecycleResponse",
    "AIBuilderUsageEvent",
    "ApplyPlanRequest",
    "ApplyResultResponse",
    "CreateSessionRequest",
    "BuilderTurnState",
    "FlowEditDiff",
    "FlowBuilderEditApproval",
    "FlowBuilderProposalContent",
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


def test_openapi_plan_response_and_plan_event_share_proposal_schema(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    plan_response = schemas["PlanResponse"]
    plan_event = schemas["AIBuilderPlanEventData"]

    plan_proposal_refs = _schema_refs(plan_response["properties"]["proposal"])
    event_proposal_refs = _schema_refs(plan_event["properties"]["proposal"])
    assert plan_proposal_refs == event_proposal_refs
    assert "#/components/schemas/FlowBuilderProposalContent" in plan_proposal_refs

    public_proposal = schemas["FlowBuilderProposalContent"]
    assert "#/components/schemas/FlowBuilderEditApproval" in _schema_refs(
        public_proposal["properties"]["edit"]
    )
    assert "description_override_manual" in public_proposal["properties"]
    assert "edit_result" not in public_proposal["properties"]
    assert "reasoning" not in public_proposal["properties"]
    assert "resource_bindings" not in public_proposal["properties"]
    assert "resource_bindings_json" not in public_proposal["properties"]
    assert "edit_result_json" not in plan_response["properties"]
    assert "edit_result_json" not in plan_event["properties"]
    flattened_edit_fields = {
        "edit_diff",
        "edit_confidence",
        "edit_warnings",
        "edit_advisories",
        "edit_risk_flags",
    }
    assert not flattened_edit_fields.intersection(plan_response["properties"])
    assert not flattened_edit_fields.intersection(plan_event["properties"])


def test_openapi_flow_draft_spec_exposes_writer_refs_not_step_spec(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    flow_spec = schemas["FlowDraftSpecCore"]
    step_spec = schemas["StepSpec"]

    assert "document_body_writer_step_refs" in flow_spec["properties"]
    assert "document_body_writer_step_refs" not in step_spec["properties"]


def test_openapi_ai_builder_sse_plan_event_payload_is_typed(openapi_spec: dict) -> None:
    schema = openapi_spec["components"]["schemas"]["AIBuilderPlanEvent"]

    assert "#/components/schemas/AIBuilderPlanEventData" in _schema_refs(schema)


def test_openapi_ai_builder_error_exposes_diagnostic_context_and_details(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    public_error = schemas["AIBuilderPublicError"]

    assert "#/components/schemas/AIBuilderDiagnosticContext" in _schema_refs(
        public_error["properties"]["diagnostic_context"]
    )
    assert "details" in public_error["properties"]
    assert "context" not in public_error["properties"]


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


def test_openapi_ai_builder_status_event_exposes_status_enum(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    status = schemas["AIBuilderStatus"]
    status_data = schemas["AIBuilderStatusEventData"]

    assert status_data["properties"]["status"] == {
        "$ref": "#/components/schemas/AIBuilderStatus"
    }
    assert set(status["enum"]) == {
        "architecture_committed",
        "architecture_revised",
        "repairing",
    }


def test_openapi_ai_builder_stream_response_does_not_advertise_json(
    openapi_spec: dict,
) -> None:
    assert set(_send_message_stream_content(openapi_spec)) == {"text/event-stream"}


def test_openapi_session_response_includes_telemetry_field(openapi_spec: dict) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    session_response = schemas["SessionResponse"]
    telemetry_property = session_response["properties"].get("telemetry")
    assert telemetry_property is not None


def test_openapi_ai_builder_turn_retry_contract_is_strict(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec["components"]["schemas"]
    request = schemas["SendMessageRequest"]
    lifecycle = schemas["AIBuilderTurnLifecycleResponse"]

    assert request["additionalProperties"] is False
    assert set(request["required"]) == {"client_turn_id", "message"}
    assert request["properties"]["file_ids"]["anyOf"][0]["maxItems"] == 100
    assert request["properties"]["ui_language"]["anyOf"][0]["maxLength"] == 16
    assert (
        request["properties"]["acknowledge_duplicate_provider_spend"]["default"]
        is False
    )
    structured_answer = schemas["StructuredQuestionAnswerMetadata"]
    assert (
        structured_answer["properties"]["selected_values"]["anyOf"][0]["maxItems"] == 20
    )
    assert (
        structured_answer["properties"]["selected_values"]["anyOf"][0]["items"][
            "anyOf"
        ][0]["maxLength"]
        == 500
    )
    assert lifecycle["additionalProperties"] is False
    assert lifecycle["properties"]["retry_request"] == {
        "$ref": "#/components/schemas/SendMessageRequest"
    }
    assert set(schemas["BuilderTurnState"]["enum"]) == {
        "open",
        "processing",
        "committed",
        "failed_before_provider",
        "provider_outcome_unknown",
    }
    assert "#/components/schemas/AIBuilderTurnLifecycleResponse" in _schema_refs(
        schemas["SessionResponse"]["properties"]["latest_turn"]
    )
    assert "request_fingerprint" not in request["properties"]
    assert "request_fingerprint" not in lifecycle["properties"]


def test_openapi_ai_builder_turn_retry_errors_and_recovery_are_documented(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec["components"]["schemas"]
    error_codes = set(schemas["AIBuilderErrorCode"]["enum"])
    operation = openapi_spec["paths"][
        "/api/v1/flows/ai-builder/sessions/{session_id}/messages"
    ]["post"]
    description = operation["description"]

    assert {
        "session_turn_idempotency_conflict",
        "session_turn_provider_outcome_unknown",
    }.issubset(error_codes)
    for expected in (
        "same ID",
        "changed payload conflicts",
        "latest accepted turn",
        "failed-before-provider",
        "provider-outcome-unknown",
        "explicit acknowledgement",
        "latest_turn.retry_request",
    ):
        assert expected in description

    conflict_response = operation["responses"]["409"]
    assert "client turn ID" in conflict_response["description"]
    assert "provider outcome" in conflict_response["description"]
    assert "#/components/schemas/AIBuilderPublicError" in _schema_refs(
        conflict_response["content"]["application/json"]["schema"]
    )


def test_openapi_attachment_detach_declares_active_send_conflict(
    openapi_spec: dict,
) -> None:
    operation = openapi_spec["paths"][
        "/api/v1/flows/ai-builder/sessions/{session_id}/attachments/{file_id}"
    ]["delete"]
    conflict_response = operation["responses"]["409"]
    content = conflict_response["content"]["application/json"]

    assert "active send" in conflict_response["description"]
    assert content["schema"] == {"$ref": "#/components/schemas/AIBuilderPublicError"}
    assert content["example"]["code"] == "session_send_in_progress"


def test_openapi_session_conversation_uses_public_projection(
    openapi_spec: dict,
) -> None:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    session_response = schemas["SessionResponse"]

    conversation_refs = _schema_refs(session_response["properties"]["conversation"])
    assert "#/components/schemas/AIBuilderConversationMessage" in conversation_refs
    assert "#/components/schemas/ConversationMessage" not in conversation_refs

    public_message = schemas["AIBuilderConversationMessage"]
    public_properties = set(public_message["properties"])
    assert {
        "message_id",
        "role",
        "content",
        "timestamp",
        "question",
        "requirements_summary",
        "question_answer",
        "requirements_confirmation",
    }.issubset(public_properties)
    assert not {
        "metadata",
        "tool_calls",
        "tool_call_id",
    }.intersection(public_properties)
    assert public_message["additionalProperties"] is False


def test_openapi_ai_builder_classifier_diagnostics_are_internal(
    openapi_spec: dict,
) -> None:
    paths = openapi_spec.get("paths", {})

    assert (
        "/api/v1/flows/ai-builder/sessions/{session_id}/_diagnostics/classifier-slots"
        not in paths
    )


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
