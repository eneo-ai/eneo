import importlib
import os
import subprocess
import sys
from pathlib import Path

from fastapi.routing import APIRoute


def test_server_main_imports_without_circular_flow_template_validation_cycle() -> None:
    module = importlib.import_module("intric.server.main")

    assert module is not None


def test_server_main_imports_in_fresh_python_process() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    source_path = str(backend_root / "src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{source_path}:{existing_pythonpath}" if existing_pythonpath else source_path
    )

    result = subprocess.run(
        [sys.executable, "-c", "import intric.server.main"],
        cwd=backend_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_flow_template_validation_delegates_to_files_domain_helpers() -> None:
    files_validation = importlib.import_module("intric.files.docx_template_validation")
    flow_validation = importlib.import_module("intric.flows.flow_template_validation")

    assert (
        flow_validation.validate_docx_template_archive
        is files_validation.validate_docx_template_archive
    )
    assert (
        flow_validation.validate_template_extension
        is files_validation.validate_template_extension
    )
    assert (
        flow_validation.normalize_template_extraction_error
        is files_validation.normalize_template_extraction_error
    )


def test_intric_flows_package_does_not_import_services_as_side_effect() -> None:
    sys.modules.pop("intric.flows", None)
    sys.modules.pop("intric.flows.application.flow_service", None)
    sys.modules.pop("intric.flows.application.flow_run_service", None)

    importlib.import_module("intric.flows")

    assert "intric.flows.application.flow_service" not in sys.modules
    assert "intric.flows.application.flow_run_service" not in sys.modules


def test_intric_flows_runtime_package_does_not_import_celery_as_side_effect() -> None:
    sys.modules.pop("intric.flows.runtime", None)
    sys.modules.pop("intric.flows.runtime.celery_app", None)
    sys.modules.pop("intric.flows.runtime.celery_execution_backend", None)

    importlib.import_module("intric.flows.runtime")

    assert "intric.flows.runtime.celery_app" not in sys.modules
    assert "intric.flows.runtime.celery_execution_backend" not in sys.modules


def test_flow_canonical_layer_imports_are_available() -> None:
    domain = importlib.import_module("intric.flows.domain")
    application = importlib.import_module("intric.flows.application")
    infrastructure = importlib.import_module("intric.flows.infrastructure")
    flow_service = importlib.import_module("intric.flows.application.flow_service")
    flow_run_service = importlib.import_module(
        "intric.flows.application.flow_run_service"
    )
    flow_repo = importlib.import_module("intric.flows.infrastructure.flow_repo")
    flow_run_repo = importlib.import_module("intric.flows.infrastructure.flow_run_repo")
    flow_version_repo = importlib.import_module(
        "intric.flows.infrastructure.flow_version_repo"
    )
    flow_dispatch = importlib.import_module("intric.flows.application.flow_dispatch")

    assert domain.Flow.__module__ == "intric.flows.domain.flow"
    assert application.FlowService is flow_service.FlowService
    assert application.FlowRunService is flow_run_service.FlowRunService
    assert infrastructure.FlowRepository is flow_repo.FlowRepository
    assert infrastructure.FlowRunRepository is flow_run_repo.FlowRunRepository
    assert (
        infrastructure.FlowVersionRepository is flow_version_repo.FlowVersionRepository
    )
    assert (
        application.dispatch_flow_run_after_commit
        is flow_dispatch.dispatch_flow_run_after_commit
    )


def test_flow_and_ai_builder_routes_have_unique_contracts_and_docs() -> None:
    module = importlib.import_module("intric.server.main")
    app = module.app

    flow_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1/flows")
    ]

    seen_method_paths: set[tuple[str, str]] = set()
    duplicate_method_paths: list[tuple[str, str]] = []
    seen_operation_ids: set[str] = set()
    duplicate_operation_ids: list[str] = []
    missing_docs: list[str] = []

    for route in flow_routes:
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            key = (method, route.path)
            if key in seen_method_paths:
                duplicate_method_paths.append(key)
            seen_method_paths.add(key)

        if route.operation_id is None:
            duplicate_operation_ids.append(f"{route.path}:<missing>")
        elif route.operation_id in seen_operation_ids:
            duplicate_operation_ids.append(route.operation_id)
        else:
            seen_operation_ids.add(route.operation_id)

        if not route.summary or not route.description:
            missing_docs.append(route.path)

    assert duplicate_method_paths == []
    assert duplicate_operation_ids == []
    assert missing_docs == []


def test_flow_and_ai_builder_request_models_expose_openapi_examples() -> None:
    flow_models = importlib.import_module("intric.flows.api.flow_models")
    ai_builder_models = importlib.import_module(
        "intric.flows.ai_builder.ai_builder_models"
    )
    file_models = importlib.import_module("intric.files.file_models")
    assistant_models = importlib.import_module("intric.assistants.api.assistant_models")

    models_with_examples = [
        flow_models.FlowCreateRequest,
        flow_models.FlowUpdateRequest,
        flow_models.FlowRunCreateRequest,
        flow_models.FlowAssistantCreateRequest,
        ai_builder_models.CreateSessionRequest,
        ai_builder_models.SendMessageRequest,
        ai_builder_models.ApplyPlanRequest,
        file_models.SignedURLRequest,
        assistant_models.AssistantUpdatePublic,
    ]

    for model in models_with_examples:
        extra = getattr(model, "model_config", {}).get("json_schema_extra", {})
        assert "example" in extra and extra["example"]


def test_flow_and_ai_builder_response_models_expose_openapi_examples() -> None:
    flow_models = importlib.import_module("intric.flows.api.flow_models")
    ai_builder_models = importlib.import_module(
        "intric.flows.ai_builder.ai_builder_models"
    )

    models_with_examples = [
        flow_models.FlowPublic,
        flow_models.FlowSparsePublic,
        flow_models.FlowRunPublic,
        flow_models.FlowRunStepPublic,
        flow_models.FlowRunRedispatchResponse,
        flow_models.FlowTemplateAssetPublic,
        flow_models.FlowTemplateInspectionPublic,
        flow_models.FlowRunContractPublic,
        flow_models.GraphResponse,
        flow_models.FlowRunDebugExport,
        flow_models.FlowRunEvidenceResponse,
        flow_models.FlowRunEvidenceExportResponse,
        ai_builder_models.SessionResponse,
        ai_builder_models.SessionListResponse,
        ai_builder_models.SessionModelsResponse,
        ai_builder_models.PlanResponse,
        ai_builder_models.SessionPlansResponse,
        ai_builder_models.PlanApprovalResponse,
        ai_builder_models.ApplyResultResponse,
    ]

    for model in models_with_examples:
        extra = getattr(model, "model_config", {}).get("json_schema_extra", {})
        assert "example" in extra and extra["example"]


def test_flow_and_ai_builder_openapi_documents_parameters_and_error_examples() -> None:
    module = importlib.import_module("intric.server.main")
    schema = module.app.openapi()
    tags = {tag["name"]: tag for tag in schema.get("tags", [])}

    assert tags["flows"]["description"]
    assert tags["ai-builder"]["description"]

    send_message_operation = schema["paths"][
        "/api/v1/flows/ai-builder/sessions/{session_id}/messages"
    ]["post"]
    assert send_message_operation["tags"] == ["ai-builder"]
    send_message_params = {
        param["name"]: param for param in send_message_operation["parameters"]
    }
    assert send_message_params["session_id"]["description"]
    assert send_message_operation["responses"]["200"]["content"]["text/event-stream"][
        "example"
    ]
    assert (
        send_message_operation["responses"]["403"]["content"]["application/json"][
            "example"
        ]["code"]
        == "insufficient_scope"
    )
    assert (
        send_message_operation["responses"]["404"]["content"]["application/json"][
            "example"
        ]["code"]
        == "not_found"
    )

    apply_plan_operation = schema["paths"][
        "/api/v1/flows/ai-builder/plans/{plan_id}/apply"
    ]["post"]
    assert apply_plan_operation["tags"] == ["ai-builder"]
    apply_plan_params = {
        param["name"]: param for param in apply_plan_operation["parameters"]
    }
    assert apply_plan_params["plan_id"]["description"]
    assert (
        apply_plan_operation["responses"]["409"]["content"]["application/json"][
            "example"
        ]["code"]
        == "stale_revision"
    )

    get_flow_operation = schema["paths"]["/api/v1/flows/{id}/"]["get"]
    get_flow_params = {
        param["name"]: param for param in get_flow_operation["parameters"]
    }
    assert get_flow_params["id"]["description"]
    assert (
        get_flow_operation["responses"]["404"]["content"]["application/json"][
            "example"
        ]["code"]
        == "not_found"
    )

    list_steps_operation = schema["paths"]["/api/v1/flows/{id}/runs/{run_id}/steps/"][
        "get"
    ]
    assert list_steps_operation["summary"]
    assert list_steps_operation["description"]

    get_evidence_operation = schema["paths"][
        "/api/v1/flows/{id}/runs/{run_id}/evidence/"
    ]["get"]
    evidence_params = {
        param["name"]: param for param in get_evidence_operation["parameters"]
    }
    assert evidence_params["id"]["description"]
    assert evidence_params["run_id"]["description"]
    assert (
        get_evidence_operation["responses"]["503"]["content"]["application/json"][
            "example"
        ]["code"]
        == "flow_evidence_audit_logging_failed"
    )

    export_evidence_operation = schema["paths"][
        "/api/v1/flows/{id}/runs/{run_id}/evidence/export"
    ]["get"]
    export_params = {
        param["name"]: param for param in export_evidence_operation["parameters"]
    }
    assert export_params["format"]["description"]
    assert (
        export_evidence_operation["responses"]["400"]["content"]["application/json"][
            "example"
        ]["code"]
        == "flow_evidence_export_reason_required"
    )
    assert (
        export_evidence_operation["responses"]["503"]["content"]["application/json"][
            "example"
        ]["code"]
        == "flow_evidence_audit_logging_failed"
    )

    list_flows_operation = schema["paths"]["/api/v1/flows/"]["get"]
    list_flows_params = {
        param["name"]: param for param in list_flows_operation["parameters"]
    }
    assert list_flows_params["space_id"]["description"]
    assert list_flows_params["limit"]["description"]
    assert list_flows_params["offset"]["description"]

    get_flow_assistant_operation = schema["paths"][
        "/api/v1/flows/{id}/assistants/{assistant_id}/"
    ]["get"]
    get_flow_assistant_params = {
        param["name"]: param for param in get_flow_assistant_operation["parameters"]
    }
    assert get_flow_assistant_params["id"]["description"]
    assert get_flow_assistant_params["assistant_id"]["description"]
    assert (
        get_flow_assistant_operation["responses"]["404"]["content"]["application/json"][
            "example"
        ]["code"]
        == "not_found"
    )

    list_flow_runs_operation = schema["paths"]["/api/v1/flows/{id}/runs/"]["get"]
    list_flow_runs_params = {
        param["name"]: param for param in list_flow_runs_operation["parameters"]
    }
    assert list_flow_runs_params["id"]["description"]
    assert list_flow_runs_params["limit"]["description"]
    assert list_flow_runs_params["offset"]["description"]

    get_flow_graph_operation = schema["paths"]["/api/v1/flows/{id}/graph/"]["get"]
    get_flow_graph_params = {
        param["name"]: param for param in get_flow_graph_operation["parameters"]
    }
    assert get_flow_graph_params["id"]["description"]
    assert get_flow_graph_params["run_id"]["description"]

    signed_url_operation = schema["paths"][
        "/api/v1/flows/{id}/template-files/{file_id}/signed-url/"
    ]["post"]
    signed_url_params = {
        param["name"]: param for param in signed_url_operation["parameters"]
    }
    assert signed_url_params["id"]["description"]
    assert signed_url_params["file_id"]["description"]

    template_list_operation = schema["paths"]["/api/v1/flows/{id}/template-files/"][
        "get"
    ]
    assert (
        template_list_operation["responses"]["403"]["content"]["application/json"][
            "example"
        ]["code"]
        == "insufficient_scope"
    )
    assert (
        template_list_operation["responses"]["404"]["content"]["application/json"][
            "example"
        ]["code"]
        == "not_found"
    )

    run_contract_operation = schema["paths"]["/api/v1/flows/{id}/run-contract/"]["get"]
    run_contract_params = {
        param["name"]: param for param in run_contract_operation["parameters"]
    }
    assert run_contract_params["id"]["description"]

    input_policy_operation = schema["paths"]["/api/v1/flows/{id}/input-policy/"]["get"]
    input_policy_params = {
        param["name"]: param for param in input_policy_operation["parameters"]
    }
    assert input_policy_params["id"]["description"]

    upload_flow_file_operation = schema["paths"]["/api/v1/flows/{id}/files/"]["post"]
    upload_flow_file_params = {
        param["name"]: param for param in upload_flow_file_operation["parameters"]
    }
    assert upload_flow_file_params["id"]["description"]

    upload_runtime_file_operation = schema["paths"][
        "/api/v1/flows/{id}/steps/{step_id}/runtime-files/"
    ]["post"]
    upload_runtime_file_params = {
        param["name"]: param for param in upload_runtime_file_operation["parameters"]
    }
    assert upload_runtime_file_params["id"]["description"]
    assert upload_runtime_file_params["step_id"]["description"]

    create_run_operation = schema["paths"]["/api/v1/flows/{id}/runs/"]["post"]
    assert "published flow" in create_run_operation["description"].casefold()
    assert "uploaded files" in create_run_operation["description"].casefold()

    list_flows_operation = schema["paths"]["/api/v1/flows/"]["get"]
    assert "current page" in list_flows_operation["description"].casefold()

    list_flow_runs_operation = schema["paths"]["/api/v1/flows/{id}/runs/"]["get"]
    assert "current page" in list_flow_runs_operation["description"].casefold()
