from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

AI_BUILDER_MODELS_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_models")
)
AI_BUILDER_DOMAIN_MODELS_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_domain_models")
)
AI_BUILDER_PROPOSAL_PROCESSOR_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_proposal_processor")
)
BANNED_PROPOSAL_PROCESSOR_IMPORTS = frozenset(
    {AI_BUILDER_PROPOSAL_PROCESSOR_MODULE, "ai_builder_proposal_processor"}
)
PROPOSAL_TOOL_MODULES = (
    Path("src/eneo/flows/ai_builder/ai_builder_create_proposal.py"),
    Path("src/eneo/flows/ai_builder/ai_builder_edit_proposal.py"),
)
PROPOSAL_PLAN_STORE_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_plan_store")
)
PROPOSAL_POLICY_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_proposal_policy")
)
PROPOSAL_FINALIZATION_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_proposal_finalization")
)
PROPOSAL_REPAIR_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_proposal_repair")
)
PROPOSAL_SUBMISSION_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_proposal_submission")
)
SCOPED_PLAN_REVISION_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_scoped_plan_revision")
)
PROPOSAL_TOOL_CONTRACTS_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_proposal_tool_contracts")
)
BANNED_PROPOSAL_TOOL_IMPORT_MODULES = frozenset(
    {
        PROPOSAL_PLAN_STORE_MODULE,
        "eneo.flows.ai_builder.ai_builder_events",
        "eneo.flows.ai_builder.ai_builder_repo",
    }
)
BANNED_PROPOSAL_TOOL_NAMES = frozenset(
    {
        "AIBuilderRepository",
        "MCPClarificationFn",
        "ProposalToolDeps",
        "build_plan_event",
        "format_revision_feedback",
        "format_validation_feedback",
        "proposal_deps",
        "store_plan_and_update_conversation",
    }
)
PROCESSOR_FINALIZATION_METHODS = frozenset(
    {
        "_create_quality_result",
        "_edit_quality_result",
        "_finalize_compiled_proposal",
        "_mcp_policy_feedback",
        "_retry_context",
        "mcp_clarification_events_if_needed",
    }
)
BACKEND_QUESTION_PERSISTENCE_PATH = Path(
    "src/eneo/flows/ai_builder/ai_builder_backend_question_persistence.py"
)
BACKEND_QUESTION_PERSISTENCE_PUBLIC_NAMES = frozenset(
    {
        "BackendQuestionPersistenceResult",
        "persist_backend_question",
    }
)
FINALIZATION_OWNER_NAMES = frozenset(
    {"CompiledProposalFinalizationRequest", "CompiledProposalFinalizer"}
)
FINALIZATION_FORBIDDEN_COMPLETION_NAMES = frozenset(
    {"ProposalCompletionFn", "ProposalCompletionRequest"}
)
FINALIZATION_REQUEST_COMPLETION_FIELD_NAMES = frozenset(
    {"litellm_model", "litellm_kwargs", "max_output_tokens"}
)
OBSOLETE_MODEL_TOOL_RUNTIME_PATHS = (
    Path("src/eneo/flows/ai_builder/ai_builder_question_recovery.py"),
    Path("src/eneo/flows/ai_builder/ai_builder_confirm_requirements.py"),
)
OBSOLETE_MODEL_TOOL_RUNTIME_MODULES = frozenset(
    {
        "eneo.flows.ai_builder.ai_builder_question_recovery",
        "eneo.flows.ai_builder.ai_builder_confirm_requirements",
    }
)
PROPOSAL_REPAIR_ALLOWED_ANY_NAMES = frozenset(
    {
        "arguments",
        "correction_messages",
        "llm_messages",
        "tool_call",
        "value",
    }
)
PROPOSAL_SUBMISSION_METHODS = frozenset(
    {
        "active_submission_tool_schemas",
        "_finalize_invocation_proposal",
        "_handle_propose_flow_tool_call",
        "_process_submission_invocation",
        "_proposal_retry_config",
        "retry_forced_proposal_after_text",
        "_active_submission_tool_schemas",
    }
)
PROPOSAL_SUBMISSION_REQUIRED_PRIVATE_METHODS = frozenset(
    {
        "_active_submission_tool_schemas",
        "_build_self_correction_request",
        "_finalize_invocation_proposal",
        "_handle_propose_flow_tool_call",
        "_process_submission_invocation",
        "_proposal_retry_config",
        "_record_failed_proposal_attempt_repair",
        "_retry_forced_proposal_after_text",
        "_run_proposal_self_correction",
    }
)
PROPOSAL_SUBMISSION_FORBIDDEN_IMPORT_MODULES = frozenset(
    {
        "eneo.flows.ai_builder.ai_builder_backend_question_persistence",
        "eneo.flows.ai_builder.ai_builder_discovery_runtime",
        "eneo.flows.ai_builder.ai_builder_requirements_state",
        "eneo.flows.ai_builder.ai_builder_tool_names",
    }
)
PROPOSAL_SUBMISSION_FORBIDDEN_IMPORT_NAMES = frozenset(
    {
        "assistant_metadata_with_usage",
        "process_scoped_step_revision_if_requested",
        "scoped_step_revision_assistant_text",
    }
)
PROPOSAL_SUBMISSION_STALE_PRIVATE_METHODS = frozenset(
    {
        "_create_propose_flow_retry_config",
        "_edit_flow_retry_config",
        "_edit_propose_flow_retry_config",
        "_finalize_retry_compiled_proposal",
        "_handle_create_propose_flow_tool_call",
        "_handle_edit_propose_flow_tool_call",
        "_handle_edit_flow_tool_call",
        "_handle_outline_flow_tool_call",
        "_outline_flow_retry_config",
        "_process_retry_invocation",
        "_preflight_scoped_step_revision_if_requested",
    }
)
PROPOSAL_SUBMISSION_PUBLIC_METHODS = frozenset(
    {
        "contains_submission_tool_call",
        "dispatch_submission_tool_call",
        "run_active_submission_attempt",
    }
)
LEGACY_SUBMISSION_TOOL_CONSTANTS = frozenset(
    {"EDIT_FLOW_TOOL_NAME", "OUTLINE_FLOW_TOOL_NAME"}
)
AI_BUILDER_TOOL_NAME_OWNERS = {
    "ASK_STRUCTURED_QUESTION_TOOL_NAME": Path(
        "src/eneo/flows/ai_builder/ai_builder_tool_names.py"
    ),
    "CONFIRM_REQUIREMENTS_TOOL_NAME": Path(
        "src/eneo/flows/ai_builder/ai_builder_tool_names.py"
    ),
    "PROPOSE_FLOW_TOOL_NAME": Path("src/eneo/flows/ai_builder/ai_builder_tools.py"),
}
PRIVATE_TOOL_NAME_DUPLICATES = frozenset(
    f"_{name}" for name in AI_BUILDER_TOOL_NAME_OWNERS
)
PROPOSAL_SUBMISSION_ALLOWED_ANY_NAMES = frozenset(
    {
        "arguments",
        "assistant_metadata",
        "available_kbs",
        "available_models",
        "correction_messages",
        "litellm_client",
        "litellm_kwargs",
        "llm_messages",
        "tool_call",
        "tool_schemas",
    }
)
ARCHITECTURE_ERROR_HELPERS = frozenset(
    {
        "build_proposal_architecture_error_event",
        "record_proposal_architecture_failure",
    }
)
AI_BUILDER_TEST_MODULE = ".".join(("tests", "unittests", "flows", "ai_builder"))
PROPOSAL_PROCESSOR_TEST_MODULE = ".".join(
    (AI_BUILDER_TEST_MODULE, "test_ai_builder_proposal_processor")
)
PROPOSAL_TURN_BUILDERS_IMPORT_MODULE = ".".join(
    (AI_BUILDER_TEST_MODULE, "proposal_turn_builders")
)
PROPOSAL_TURN_TEST_DOUBLES_IMPORT_MODULE = ".".join(
    (AI_BUILDER_TEST_MODULE, "proposal_turn_test_doubles")
)
PROPOSAL_TEST_TOPOLOGY_FILES = (
    Path("tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py"),
    Path("tests/unittests/flows/ai_builder/test_ai_builder_proposal_submission.py"),
)
PROPOSAL_TURN_BUILDER_TEST_MODULE = Path(
    "tests/unittests/flows/ai_builder/proposal_turn_builders.py"
)
PROPOSAL_TURN_TEST_DOUBLES_MODULE = Path(
    "tests/unittests/flows/ai_builder/proposal_turn_test_doubles.py"
)
AI_BUILDER_PLANNER_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_planner")
)
SERVER_DECISION_DISPATCH_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_server_decision_dispatch")
)
PLANNER_REQUEST_PREPARATION_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_planner_request_preparation")
)
PLANNER_FAILURE_EVENTS_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_planner_failure_events")
)
SEND_LEASE_MODULE = ".".join(("eneo", "flows", "ai_builder", "ai_builder_send_lease"))
USER_QUESTION_METADATA_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_user_question_metadata")
)
SERVER_DECISION_DISPATCH_PATH = Path(
    "src/eneo/flows/ai_builder/ai_builder_server_decision_dispatch.py"
)
PLANNER_REQUEST_PREPARATION_PATH = Path(
    "src/eneo/flows/ai_builder/ai_builder_planner_request_preparation.py"
)
PLANNER_FAILURE_EVENTS_PATH = Path(
    "src/eneo/flows/ai_builder/ai_builder_planner_failure_events.py"
)
SEND_LEASE_PATH = Path("src/eneo/flows/ai_builder/ai_builder_send_lease.py")
USER_QUESTION_METADATA_PATH = Path(
    "src/eneo/flows/ai_builder/ai_builder_user_question_metadata.py"
)
PLANNER_PATH = Path("src/eneo/flows/ai_builder/ai_builder_planner.py")
PROPOSAL_INTENT_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_proposal_intent")
)
PROPOSAL_INTENT_PATH = Path("src/eneo/flows/ai_builder/ai_builder_proposal_intent.py")
CREATE_PROPOSAL_PATH = Path("src/eneo/flows/ai_builder/ai_builder_create_proposal.py")
SCOPED_PLAN_REVISION_PATH = Path(
    "src/eneo/flows/ai_builder/ai_builder_scoped_plan_revision.py"
)
CREATE_COMPILER_PATH = Path("src/eneo/flows/ai_builder/ai_builder_create_compiler.py")
CREATE_COMPILER_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_create_compiler")
)
EDIT_COMPILER_PATH = Path("src/eneo/flows/ai_builder/ai_builder_edit_compiler.py")
EDIT_COMPILER_ALLOWED_TYPE_IGNORE_LINES = frozenset[int]()
AUTHORING_PROJECTION_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_authoring_projection")
)
FLOW_AUTHORING_SNAPSHOT_MODULE = ".".join(
    ("eneo", "flows", "application", "flow_authoring_snapshot")
)
NEW_STEP_COMPILER_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_new_step_compiler")
)
RUNTIME_INPUT_FIELDS_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_runtime_input_fields")
)
REPAIR_TRANSPORT_MODULE = ".".join(
    ("eneo", "flows", "ai_builder", "ai_builder_repair_transport")
)
REPAIR_TRANSPORT_PATH = Path("src/eneo/flows/ai_builder/ai_builder_repair_transport.py")
CREATE_COMPILER_PUBLIC_NAMES = frozenset(
    {
        "CreateCompileContext",
        "compile_create_intent_to_spec",
        "create_compile_context_from_planning_state",
    }
)
PROPOSAL_INTENT_BANNED_COMPILER_NAMES = frozenset(
    {
        "ArchitectureCommit",
        "ArchitectureCommitDraft",
        "ArchitectureEnvelope",
        "AIBuilderArchitectureError",
        "CreateCompileContext",
        "PlanningState",
        "compile_create_intent_to_spec",
        "derive_architecture_commit_draft",
        "materialize_step_skeleton",
        "create_compile_context_from_planning_state",
        "resolve_step_skeleton_patterns",
    }
)
DELETED_CREATE_FORM_FIELD_DRAFT = "CreateFormFieldDraft"
SERVER_DECISION_DISPATCH_PUBLIC_NAMES = frozenset(
    {
        "ServerDecisionDispatchRequest",
        "ServerDecisionDispatchResult",
        "ServerDecisionProposalContinuation",
        "ServerDecisionTelemetry",
        "build_requirements_summary_payload",
        "dispatch_server_decision",
    }
)
PLANNER_REQUEST_PREPARATION_PUBLIC_NAMES = frozenset(
    {
        "PlannerRequestPreparationInput",
        "PreparedPromptMessages",
        "ProposalPrepared",
        "ServerOutputPrepared",
        "build_proposal_prepared",
        "conversation_message_to_llm_message",
        "prepare_planner_request",
    }
)
PLANNER_FAILURE_EVENTS_PUBLIC_NAMES = frozenset(
    {
        "build_planner_upstream_error_event",
        "build_session_send_lease_lost_event",
    }
)
SEND_LEASE_PUBLIC_NAMES = frozenset(
    {
        "ClaimedSessionSendTurn",
        "claim_ai_builder_send_turn",
    }
)
USER_QUESTION_METADATA_PUBLIC_NAMES = frozenset(
    {
        "UserQuestionMetadataResolution",
        "resolve_user_question_metadata",
    }
)
PURE_PROPOSAL_TURN_BUILDER_BANNED_IMPORTS = frozenset(
    {
        "pytest",
        "types",
        "unittest.mock",
        "eneo.flows.ai_builder.ai_builder_proposal_processor",
        "eneo.flows.ai_builder.ai_builder_proposal_submission",
    }
)
PURE_PROPOSAL_TURN_BUILDER_BANNED_NAMES = frozenset(
    {
        "AIBuilderProposalProcessor",
        "ProposalSubmissionOwner",
        "AsyncMock",
        "MagicMock",
        "Mock",
        "SimpleNamespace",
    }
)
PROPOSAL_TURN_TEST_DOUBLES_BANNED_DECORATORS = frozenset({"fixture", "pytest.fixture"})

BANNED_DOMAIN_MODEL_IMPORTS = frozenset(
    {
        "AssistantSpec",
        "AssistantSpecLocalRefNotPortableError",
        "AssistantToCreate",
        "AssistantToDelete",
        "AssistantToUpdate",
        "CompiledStep",
        "FlowDraftSpecCore",
        "FormFieldSpec",
        "InputSource",
        "InputType",
        "JsonObject",
        "MCPPolicy",
        "OutputMode",
        "OutputType",
        "StepChangeKind",
        "StepSpec",
    }
)


def test_ai_builder_model_imports_use_canonical_owners() -> None:
    assert importlib.util.find_spec(AI_BUILDER_MODELS_MODULE) is None

    violations: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module == AI_BUILDER_MODELS_MODULE:
                violations.append(f"{path}:{node.lineno} imports {node.module}")
                continue
            if node.module != AI_BUILDER_DOMAIN_MODELS_MODULE:
                continue
            imported_banned_names = sorted(
                alias.name
                for alias in node.names
                if alias.name == "*" or alias.name in BANNED_DOMAIN_MODEL_IMPORTS
            )
            if imported_banned_names:
                names = ", ".join(imported_banned_names)
                violations.append(
                    f"{path}:{node.lineno} imports {names} from {node.module}"
                )

    assert violations == []


def test_proposal_tool_modules_do_not_import_proposal_processor() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    violations: list[str] = []

    for relative_path in PROPOSAL_TOOL_MODULES:
        path = backend_root / relative_path
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module in BANNED_PROPOSAL_PROCESSOR_IMPORTS:
                violations.append(f"{path}:{node.lineno} imports {node.module}")

    assert violations == []


def test_proposal_tool_modules_do_not_own_active_send_finalization() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    violations: list[str] = []

    for relative_path in PROPOSAL_TOOL_MODULES:
        path = backend_root / relative_path
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (
                node.module in BANNED_PROPOSAL_TOOL_IMPORT_MODULES
            ):
                violations.append(f"{path}:{node.lineno} imports {node.module}")
            if isinstance(node, ast.Name) and node.id in BANNED_PROPOSAL_TOOL_NAMES:
                violations.append(f"{path}:{node.lineno} uses {node.id}")
            if isinstance(node, ast.arg) and node.arg in BANNED_PROPOSAL_TOOL_NAMES:
                violations.append(f"{path}:{node.lineno} arg {node.arg}")

    assert violations == []


def test_plan_store_does_not_import_proposal_policy_or_own_feedback_formatting() -> (
    None
):
    backend_root = Path(__file__).resolve().parents[4]
    path = backend_root / Path("src/eneo/flows/ai_builder/ai_builder_plan_store.py")
    tree = ast.parse(path.read_text(), filename=str(path))
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == PROPOSAL_POLICY_MODULE:
            violations.append(f"{path}:{node.lineno} imports {node.module}")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
            "_requires_reference_guidance",
            "format_revision_feedback",
            "format_validation_feedback",
        }:
            violations.append(f"{path}:{node.lineno} defines {node.name}")

    assert violations == []


def test_compiled_proposal_finalization_has_single_owner() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    finalization_spec = importlib.util.find_spec(PROPOSAL_FINALIZATION_MODULE)
    assert finalization_spec is not None

    finalization_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_finalization.py"
    )
    processor_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_processor.py"
    )
    contracts_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_tool_contracts.py"
    )
    critic_paths = (
        backend_root
        / Path("src/eneo/flows/ai_builder/ai_builder_plan_quality_critic.py"),
        backend_root / Path("src/eneo/flows/ai_builder/ai_builder_create_feedback.py"),
    )

    finalization_tree = ast.parse(
        finalization_path.read_text(), filename=str(finalization_path)
    )
    owner_names = {
        node.name
        for node in ast.walk(finalization_tree)
        if isinstance(node, ast.ClassDef)
    }
    assert FINALIZATION_OWNER_NAMES <= owner_names

    violations: list[str] = []
    processor_tree = ast.parse(processor_path.read_text(), filename=str(processor_path))
    for node in ast.walk(processor_tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in PROCESSOR_FINALIZATION_METHODS
        ):
            violations.append(f"{processor_path}:{node.lineno} defines {node.name}")

    for path in (finalization_path, contracts_path):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (
                node.module in BANNED_PROPOSAL_PROCESSOR_IMPORTS
            ):
                violations.append(f"{path}:{node.lineno} imports {node.module}")

    for path in critic_paths:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == PROPOSAL_POLICY_MODULE
            ):
                violations.append(f"{path}:{node.lineno} imports {node.module}")

    assert violations == []


def test_backend_question_persistence_has_no_discovery_runtime_owner() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    persistence_path = backend_root / BACKEND_QUESTION_PERSISTENCE_PATH
    persistence_tree = ast.parse(
        persistence_path.read_text(), filename=str(persistence_path)
    )
    violations: list[str] = []

    public_names = _top_level_public_names(persistence_tree)
    if public_names != BACKEND_QUESTION_PERSISTENCE_PUBLIC_NAMES:
        violations.append(f"{persistence_path}: public names {sorted(public_names)}")

    for module in _imported_modules(persistence_tree):
        if module in {
            "eneo.flows.ai_builder.ai_builder_discovery_runtime",
            "eneo.flows.ai_builder.ai_builder_slot_classifier",
        }:
            violations.append(f"{persistence_path}: imports {module}")

    for node in ast.walk(persistence_tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "emit_discovery_followup_if_needed"
        ):
            violations.append(f"{persistence_path}:{node.lineno} defines {node.name}")
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "persist_backend_question"
        ):
            parameter_names = {argument.arg for argument in node.args.kwonlyargs}
            runtime_parameters = {
                "litellm_client",
                "litellm_model",
                "litellm_kwargs",
                "ui_language",
            }
            overlap = sorted(parameter_names & runtime_parameters)
            if overlap:
                violations.append(
                    f"{persistence_path}:{node.lineno} accepts runtime params {overlap}"
                )

    assert violations == []


def test_question_and_requirements_events_use_typed_payload_boundary() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    discovery_models_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_discovery_models.py"
    )
    events_path = backend_root / Path("src/eneo/flows/ai_builder/ai_builder_events.py")
    mcp_intent_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_mcp_intent.py"
    )
    conversation_metadata_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_conversation_metadata.py"
    )
    dispatch_path = backend_root / SERVER_DECISION_DISPATCH_PATH
    violations: list[str] = []

    discovery_tree = ast.parse(
        discovery_models_path.read_text(), filename=str(discovery_models_path)
    )
    backend_question = next(
        node
        for node in ast.walk(discovery_tree)
        if isinstance(node, ast.ClassDef) and node.name == "BackendQuestion"
    )
    question_data_annotation = None
    for statement in backend_question.body:
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == "question_data"
        ):
            question_data_annotation = ast.unparse(statement.annotation)
    if question_data_annotation != "StructuredQuestionPayload":
        violations.append(
            f"{discovery_models_path}:{backend_question.lineno} "
            f"question_data={question_data_annotation}"
        )

    events_tree = ast.parse(events_path.read_text(), filename=str(events_path))
    # Static shape guard; matches exact annotation strings in target files.
    expected_event_parameters = {
        "build_question_event": "StructuredQuestionPayload",
        "build_requirements_summary_event": "RequirementsSummaryPayload",
    }
    for function_name, expected_annotation in expected_event_parameters.items():
        function = next(
            node
            for node in ast.walk(events_tree)
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        )
        first_arg = function.args.args[0]
        annotation = ast.unparse(first_arg.annotation) if first_arg.annotation else None
        if annotation != expected_annotation:
            violations.append(
                f"{events_path}:{function.lineno} {function_name} param={annotation}"
            )

    mcp_tree = ast.parse(mcp_intent_path.read_text(), filename=str(mcp_intent_path))
    mcp_function = next(
        node
        for node in ast.walk(mcp_tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "build_mcp_resource_selection_question"
    )
    mcp_return = ast.unparse(mcp_function.returns) if mcp_function.returns else None
    if mcp_return != "tuple[StructuredQuestionPayload, str]":
        violations.append(
            f"{mcp_intent_path}:{mcp_function.lineno} return={mcp_return}"
        )

    metadata_tree = ast.parse(
        conversation_metadata_path.read_text(), filename=str(conversation_metadata_path)
    )
    expected_metadata_parameters = {
        "metadata_for_assistant_question": "StructuredQuestionPayload",
        "requirements_summary_to_metadata": "RequirementsSummaryPayload",
    }
    for function_name, expected_annotation in expected_metadata_parameters.items():
        function = next(
            node
            for node in ast.walk(metadata_tree)
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        )
        first_arg = function.args.args[0]
        annotation = ast.unparse(first_arg.annotation) if first_arg.annotation else None
        if annotation != expected_annotation:
            violations.append(
                f"{conversation_metadata_path}:{function.lineno} {function_name} "
                f"param={annotation}"
            )

    dispatch_tree = ast.parse(dispatch_path.read_text(), filename=str(dispatch_path))
    rendering_function = next(
        (
            node
            for node in ast.walk(dispatch_tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "build_requirements_summary_payload"
        ),
        None,
    )
    if rendering_function is None:
        violations.append(
            f"{dispatch_path}: missing build_requirements_summary_payload"
        )
    else:
        rendering_return = (
            ast.unparse(rendering_function.returns)
            if rendering_function.returns
            else None
        )
        if rendering_return != "RequirementsSummaryPayload":
            violations.append(
                f"{dispatch_path}:{rendering_function.lineno} return={rendering_return}"
            )

    assert violations == []


def test_compiled_proposal_finalization_has_no_completion_boundary() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    finalization_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_finalization.py"
    )
    finalization_tree = ast.parse(
        finalization_path.read_text(), filename=str(finalization_path)
    )

    violations: list[str] = []
    for node in ast.walk(finalization_tree):
        if isinstance(node, ast.ImportFrom):
            imported_names = {
                alias.name
                for alias in node.names
                if alias.name in FINALIZATION_FORBIDDEN_COMPLETION_NAMES
            }
            if imported_names:
                names = ", ".join(sorted(imported_names))
                violations.append(f"{finalization_path}:{node.lineno} imports {names}")
        if (
            isinstance(node, ast.ClassDef)
            and node.name == "CompiledProposalFinalizationRequest"
        ):
            request_field_names = {
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            }
            completion_field_names = sorted(
                request_field_names & FINALIZATION_REQUEST_COMPLETION_FIELD_NAMES
            )
            if completion_field_names:
                fields = ", ".join(completion_field_names)
                violations.append(
                    f"{finalization_path}:{node.lineno} request fields {fields}"
                )

    assert violations == []


def test_proposal_processor_no_longer_owns_completion_boundary() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    processor_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_processor.py"
    )
    processor_tree = ast.parse(processor_path.read_text(), filename=str(processor_path))

    acompletion_refs = [
        node
        for node in ast.walk(processor_tree)
        if isinstance(node, ast.Attribute) and node.attr == "acompletion"
    ]
    violations: list[str] = []
    if acompletion_refs:
        lines = ", ".join(str(node.lineno) for node in acompletion_refs) or "none"
        violations.append(f"{processor_path}: acompletion refs {lines}")

    for node in ast.walk(processor_tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        kwarg = node.args.kwarg
        if kwarg is None:
            continue
        annotation = ast.unparse(kwarg.annotation) if kwarg.annotation else ""
        if kwarg.arg == "kwargs" and annotation == "Any":
            violations.append(f"{processor_path}:{node.lineno} defines **kwargs: Any")

    assert violations == []


def test_litellm_completion_has_single_typed_completion_boundary() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    completion_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_litellm_completion.py"
    )
    old_completion_paths = (
        backend_root
        / Path("src/eneo/flows/ai_builder/ai_builder_proposal_completion.py"),
        backend_root
        / Path("src/eneo/flows/ai_builder/ai_builder_planner_completion.py"),
    )
    completion_text = completion_path.read_text()
    completion_tree = ast.parse(completion_text, filename=str(completion_path))

    acompletion_refs = [
        node
        for node in ast.walk(completion_tree)
        if isinstance(node, ast.Attribute) and node.attr == "acompletion"
    ]
    violations: list[str] = []
    stale_paths = [str(path) for path in old_completion_paths if path.exists()]
    if stale_paths:
        violations.append(f"stale completion modules exist: {stale_paths}")
    if len(acompletion_refs) != 1:
        lines = ", ".join(str(node.lineno) for node in acompletion_refs) or "none"
        violations.append(f"{completion_path}: acompletion refs {lines}")
    if "_ProposalCompletion" in completion_text:
        violations.append(f"{completion_path}: still defines proposal view classes")
    if "ProposalCompletionUsage" in completion_text:
        violations.append(f"{completion_path}: still references proposal usage type")

    for node in ast.walk(completion_tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        kwarg = node.args.kwarg
        if kwarg is None:
            continue
        annotation = ast.unparse(kwarg.annotation) if kwarg.annotation else ""
        if kwarg.arg == "kwargs" and annotation == "Any":
            violations.append(f"{completion_path}:{node.lineno} defines **kwargs: Any")

    assert violations == []


def test_litellm_completion_dependency_direction_stays_leaf_owned() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    completion_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_litellm_completion.py"
    )
    telemetry_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_telemetry.py"
    )
    completion_tree = ast.parse(
        completion_path.read_text(), filename=str(completion_path)
    )
    telemetry_tree = ast.parse(telemetry_path.read_text(), filename=str(telemetry_path))

    violations: list[str] = []
    for node in ast.walk(completion_tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module in {
            "eneo.flows.ai_builder.ai_builder_proposal_processor",
            "eneo.flows.ai_builder.ai_builder_planner",
        }:
            violations.append(f"{completion_path}:{node.lineno} imports {node.module}")

    for node in ast.walk(telemetry_tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module == "eneo.flows.ai_builder.ai_builder_litellm_completion":
            violations.append(f"{telemetry_path}:{node.lineno} imports {node.module}")

    assert violations == []


def _assignment_target_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return [target.id for target in targets if isinstance(target, ast.Name)]


def test_ai_builder_tool_names_have_single_owners() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    src_root = backend_root / Path("src/eneo/flows/ai_builder")
    violations: list[str] = []
    owner_definitions: dict[str, list[str]] = {
        name: [] for name in AI_BUILDER_TOOL_NAME_OWNERS
    }

    for path in src_root.rglob("*.py"):
        rel_path = path.relative_to(backend_root)
        tree = ast.parse(path.read_text(), filename=str(path))

        for node in ast.walk(tree):
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) and node.name in {
                "active_submission_tool_name",
                "_active_submission_tool_name",
            }:
                violations.append(f"{rel_path}:{node.lineno} defines {node.name}")

            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue

            target_names = set(_assignment_target_names(node))
            for legacy_name in sorted(target_names & LEGACY_SUBMISSION_TOOL_CONSTANTS):
                violations.append(f"{rel_path}:{node.lineno} defines {legacy_name}")
            for private_name in sorted(target_names & PRIVATE_TOOL_NAME_DUPLICATES):
                violations.append(
                    f"{rel_path}:{node.lineno} defines duplicate {private_name}"
                )

            for name, owner in AI_BUILDER_TOOL_NAME_OWNERS.items():
                if name not in target_names:
                    continue
                definition = f"{rel_path}:{node.lineno}:{name}"
                owner_definitions[name].append(definition)
                if rel_path != owner:
                    violations.append(f"{rel_path}:{node.lineno} defines {name}")

    for name, definitions in owner_definitions.items():
        if len(definitions) != 1:
            violations.append(
                f"{name} must have exactly one owner definition; found {definitions}"
            )

    assert violations == []


def test_obsolete_model_visible_ask_confirm_runtime_is_deleted() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    processor_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_processor.py"
    )
    tools_path = backend_root / Path("src/eneo/flows/ai_builder/ai_builder_tools.py")
    parsing_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_tool_parsing.py"
    )
    processor_tree = ast.parse(processor_path.read_text(), filename=str(processor_path))
    tools_tree = ast.parse(tools_path.read_text(), filename=str(tools_path))
    parsing_tree = ast.parse(parsing_path.read_text(), filename=str(parsing_path))
    violations: list[str] = []

    for rel_path in OBSOLETE_MODEL_TOOL_RUNTIME_PATHS:
        if (backend_root / rel_path).exists():
            violations.append(f"{rel_path}: obsolete model-visible runtime exists")

    processor_class = next(
        node
        for node in ast.walk(processor_tree)
        if isinstance(node, ast.ClassDef) and node.name == "AIBuilderProposalProcessor"
    )
    obsolete_processor_methods = {
        "handle_tool_call",
        "_dispatch_known_tool_call",
        "_handle_question_recovery_dispatch",
        "_handle_confirm_requirements",
    }
    for node in processor_class.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in obsolete_processor_methods
        ):
            violations.append(f"{processor_path}:{node.lineno} defines {node.name}")

    obsolete_tool_functions = {
        "build_all_tool_schemas",
        "build_ask_structured_question_tool_schema",
        "build_confirm_requirements_tool_schema",
        "build_discovery_complete_tool_schemas",
        "build_free_discovery_tool_schemas",
    }
    obsolete_parser_functions = {
        "parse_structured_question",
        "parse_confirm_requirements",
    }
    for tree, path, banned_functions in (
        (tools_tree, tools_path, obsolete_tool_functions),
        (parsing_tree, parsing_path, obsolete_parser_functions),
    ):
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in banned_functions
            ):
                violations.append(f"{path}:{node.lineno} defines {node.name}")

    obsolete_runtime_names = {
        "ConfirmRequirementsProcessingRequest",
        "ConfirmRequirementsRetryConfigRequest",
        "RecoveredToolDispatchRequest",
        "StructuredQuestionRecoveryRequest",
        "build_confirm_requirements_retry_config",
        "process_confirm_requirements",
        "stream_structured_question_tool_call",
        *obsolete_parser_functions,
        *obsolete_tool_functions,
    }
    source_root = backend_root / "src/eneo/flows/ai_builder"
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module in OBSOLETE_MODEL_TOOL_RUNTIME_MODULES:
                    violations.append(f"{path}:{node.lineno} imports {node.module}")
                imported_names = {alias.name for alias in node.names}
                for name in sorted(imported_names & obsolete_runtime_names):
                    violations.append(f"{path}:{node.lineno} imports {name}")
            elif isinstance(node, ast.Name) and node.id in obsolete_runtime_names:
                violations.append(f"{path}:{node.lineno} references {node.id}")

    assert violations == []


def test_proposal_completion_has_single_request_boundary() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    contracts_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_tool_contracts.py"
    )
    completion_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_litellm_completion.py"
    )
    submission_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_submission.py"
    )
    proposal_callers = [
        backend_root / Path("src/eneo/flows/ai_builder/ai_builder_proposal_repair.py"),
        submission_path,
    ]
    contracts_tree = ast.parse(contracts_path.read_text(), filename=str(contracts_path))
    completion_text = completion_path.read_text()
    submission_text = submission_path.read_text()
    violations: list[str] = []

    protocol_class = next(
        node
        for node in ast.walk(contracts_tree)
        if isinstance(node, ast.ClassDef) and node.name == "ProposalCompletionFn"
    )
    call_method = next(
        node
        for node in protocol_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "__call__"
    )
    positional_args = [arg.arg for arg in call_method.args.args if arg.arg != "self"]
    if positional_args != ["request"]:
        violations.append(
            f"{contracts_path}:{call_method.lineno} __call__ args {positional_args}"
        )
    if call_method.args.kwonlyargs or call_method.args.vararg or call_method.args.kwarg:
        violations.append(f"{contracts_path}:{call_method.lineno} exposes kwargs")

    for path in [completion_path, *proposal_callers]:
        text = path.read_text()
        if "call_proposal_completion_with_usage" in text:
            violations.append(f"{path}: references call_proposal_completion_with_usage")

    for path in proposal_callers:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "acompletion":
                violations.append(f"{path}:{node.lineno} calls acompletion")

    if "usage_tracker.record_response" not in completion_text:
        violations.append(f"{completion_path}: completion owner does not record usage")
    if "LiteLLMProposalMessage" in submission_text:
        violations.append(
            f"{submission_path}: defines local LiteLLMProposalMessage shadow protocol"
        )

    assert violations == []


def test_edit_compiler_consumes_ordered_proposals_without_operation_ir() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    edit_compiler_path = backend_root / EDIT_COMPILER_PATH
    edit_compiler_text = edit_compiler_path.read_text()
    edit_compiler_tree = ast.parse(edit_compiler_text, filename=str(edit_compiler_path))
    violations: list[str] = []

    type_ignore_lines = {
        line_number
        for line_number, line in enumerate(edit_compiler_text.splitlines(), start=1)
        if "# type: ignore" in line
    }
    if type_ignore_lines != EDIT_COMPILER_ALLOWED_TYPE_IGNORE_LINES:
        violations.append(
            f"{edit_compiler_path}: type-ignore lines {sorted(type_ignore_lines)}"
        )

    imported_names_by_module: dict[str, set[str]] = {}
    direct_module_imports: set[str] = set()
    for node in ast.walk(edit_compiler_tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_names_by_module.setdefault(node.module, set()).update(
                alias.name for alias in node.names
            )
        elif isinstance(node, ast.Import):
            direct_module_imports.update(alias.name for alias in node.names)

    authoring_imports = imported_names_by_module.get(AUTHORING_PROJECTION_MODULE, set())
    if "compile_ordered_edit_proposal" not in authoring_imports:
        violations.append(
            f"{edit_compiler_path}: missing compile_ordered_edit_proposal import"
        )
    proposal_intent_imports = imported_names_by_module.get(
        PROPOSAL_INTENT_MODULE, set()
    )
    if "OrderedEditProposal" not in proposal_intent_imports:
        violations.append(
            f"{edit_compiler_path}: missing model-facing OrderedEditProposal import"
        )
    snapshot_imports = imported_names_by_module.get(
        FLOW_AUTHORING_SNAPSHOT_MODULE, set()
    )
    if "current_flow_authoring_spec" not in snapshot_imports:
        violations.append(
            f"{edit_compiler_path}: missing Flow authoring snapshot import"
        )

    banned_authoring_imports = {
        "_compile_existing_step_modification",
        "compile_existing_step_modification",
        "current_flow_authoring_spec",
        "flow_step_to_authoring_spec",
    }
    banned_new_step_imports = {
        "compile_new_step_draft",
        "make_plan_step_ref",
    }
    banned_imports = (
        authoring_imports & banned_authoring_imports,
        imported_names_by_module.get(NEW_STEP_COMPILER_MODULE, set())
        & banned_new_step_imports,
        direct_module_imports & {AUTHORING_PROJECTION_MODULE, NEW_STEP_COMPILER_MODULE},
    )
    if any(banned_imports):
        violations.append(
            f"{edit_compiler_path}: direct compile imports {banned_imports}"
        )

    function_names = {
        node.name
        for node in ast.walk(edit_compiler_tree)
        if isinstance(node, ast.FunctionDef)
    }
    banned_functions = {
        "_flow_step_to_spec",
        "_build_ordered_edit_proposal",
        "_apply_add",
        "_apply_modify",
        "_apply_remove",
    }
    if overlap := function_names & banned_functions:
        violations.append(
            f"{edit_compiler_path}: stale edit functions {sorted(overlap)}"
        )

    banned_annotation = "tuple[str | None, FlowStep | NewStepDraft]"
    for node in ast.walk(edit_compiler_tree):
        annotation: ast.expr | None = None
        if isinstance(node, ast.AnnAssign):
            annotation = node.annotation
        elif isinstance(node, ast.arg):
            annotation = node.annotation
        if annotation is None:
            continue
        rendered = ast.unparse(annotation)
        if banned_annotation in rendered:
            violations.append(
                f"{edit_compiler_path}:{node.lineno} annotation {rendered}"
            )

    assert violations == []


def test_old_edit_operation_ir_files_are_deleted() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    deleted_paths = (
        Path("src/eneo/flows/ai_builder/ai_builder_edit_models.py"),
        Path("src/eneo/flows/ai_builder/ai_builder_edit_normalizer.py"),
        Path("src/eneo/flows/ai_builder/ai_builder_edit_validator.py"),
        Path("src/eneo/flows/ai_builder/ai_builder_edit_mechanics.py"),
        Path("src/eneo/flows/ai_builder/ai_builder_edit_effective_steps.py"),
    )
    violations = [str(path) for path in deleted_paths if (backend_root / path).exists()]

    assert violations == []


def test_litellm_completion_owns_provider_calls_for_proposals() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    completion_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_litellm_completion.py"
    )
    completion_tree = ast.parse(
        completion_path.read_text(), filename=str(completion_path)
    )
    violations: list[str] = []
    deleted_paths = (
        Path("src/eneo/flows/ai_builder/ai_builder_repair.py"),
        Path("src/eneo/flows/ai_builder/ai_builder_orchestration_pipeline.py"),
        Path("src/eneo/flows/ai_builder/ai_builder_structured_turn.py"),
        Path("src/eneo/flows/ai_builder/ai_builder_planner_turn.py"),
        Path("src/eneo/flows/ai_builder/ai_builder_orchestrator.py"),
        Path("src/eneo/flows/ai_builder/ai_builder_response_format.py"),
    )
    for path in deleted_paths:
        if (backend_root / path).exists():
            violations.append(f"{path}: stale structured planner runtime exists")

    acompletion_refs = [
        node
        for node in ast.walk(completion_tree)
        if isinstance(node, ast.Attribute) and node.attr == "acompletion"
    ]
    if len(acompletion_refs) != 1:
        lines = ", ".join(str(node.lineno) for node in acompletion_refs) or "none"
        violations.append(f"{completion_path}: acompletion refs {lines}")

    completion_imports = _imported_modules(completion_tree)
    banned_imports = {
        "eneo.flows.ai_builder.ai_builder_repair",
        "eneo.flows.ai_builder.ai_builder_orchestration_pipeline",
        "eneo.flows.ai_builder.ai_builder_planner_turn",
        "eneo.flows.ai_builder.ai_builder_router",
        "eneo.flows.ai_builder.ai_builder_api_models",
    }
    for module in sorted(completion_imports & banned_imports):
        violations.append(f"{completion_path}: imports {module}")

    assert violations == []


def test_proposal_repair_has_typed_result_projection() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    repair_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_repair.py"
    )
    repair_tree = ast.parse(repair_path.read_text(), filename=str(repair_path))
    violations: list[str] = []

    banned_names = {
        "_ToolFailureCodes",
        "_tool_result_has_events",
        "_tool_result_events",
        "_tool_result_failure_codes",
    }
    banned_imports = {"Protocol", "runtime_checkable"}

    for node in ast.walk(repair_tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported_names = {alias.name for alias in node.names}
            banned = sorted(imported_names & banned_imports)
            if banned:
                violations.append(
                    f"{repair_path}:{node.lineno} imports {', '.join(banned)}"
                )

        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in banned_names:
                violations.append(f"{repair_path}:{node.lineno} defines {node.name}")

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.args.kwarg is not None:
                annotation = node.args.kwarg.annotation
                if annotation is not None and ast.unparse(annotation) == "Any":
                    violations.append(
                        f"{repair_path}:{node.lineno} defines **kwargs: Any"
                    )
            for arg in [*node.args.args, *node.args.kwonlyargs]:
                if _annotation_uses_any(arg.annotation) and (
                    arg.arg not in PROPOSAL_REPAIR_ALLOWED_ANY_NAMES
                ):
                    violations.append(
                        f"{repair_path}:{node.lineno} arg {arg.arg} uses Any"
                    )

        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if _annotation_uses_any(node.annotation) and (
                node.target.id not in PROPOSAL_REPAIR_ALLOWED_ANY_NAMES
            ):
                violations.append(
                    f"{repair_path}:{node.lineno} field {node.target.id} uses Any"
                )

    assert violations == []


def test_stream_events_have_single_wire_encoder_boundary() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    source_root = backend_root / Path("src/eneo/flows/ai_builder")
    encoder_path = source_root / "ai_builder_events.py"
    violations: list[str] = []
    raw_event_literals: list[str] = []
    banned_internal_event_shapes = {
        "ToolProcessingResult(event=",
        "EventBatch",
        "AsyncGenerator[dict[str, str], None]",
        "events: list[dict[str, str]]",
        "tuple[dict[str, str], ...]",
        "iter_events(",
        "has_events",
    }

    for path in sorted(source_root.glob("*.py")):
        text = path.read_text()
        for banned_shape in sorted(banned_internal_event_shapes):
            if banned_shape in text:
                violations.append(f"{path}: contains {banned_shape}")

        for line_number, line in enumerate(text.splitlines(), start=1):
            compact_line = line.replace(" ", "")
            if '{"event":' in compact_line or "{'event':" in compact_line:
                raw_event_literals.append(f"{path}:{line_number}")

    if len(raw_event_literals) != 1:
        violations.append(
            "expected exactly one raw stream-event dict literal, found "
            f"{raw_event_literals}"
        )
    elif not raw_event_literals[0].startswith(str(encoder_path)):
        violations.append(
            "raw stream-event dict literal must live in ai_builder_events.py, found "
            f"{raw_event_literals[0]}"
        )

    assert violations == []


def test_proposal_repair_wrapper_stays_deleted_and_repair_owns_runtime_helpers() -> (
    None
):
    backend_root = Path(__file__).resolve().parents[4]
    processor_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_processor.py"
    )
    repair_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_repair.py"
    )
    runtime_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_repair_runtime.py"
    )
    assert not runtime_path.exists()
    assert importlib.util.find_spec(PROPOSAL_REPAIR_MODULE) is not None

    processor_tree = ast.parse(processor_path.read_text(), filename=str(processor_path))
    repair_text = repair_path.read_text()
    repair_tree = ast.parse(repair_text, filename=str(repair_path))
    violations: list[str] = []

    for node in ast.walk(repair_tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if (
                node.module
                == "eneo.flows.ai_builder.ai_builder_proposal_tool_contracts"
            ):
                for alias in node.names:
                    if alias.name == "ProposalCompletionRequest":
                        violations.append(
                            f"{repair_path}:{node.lineno} imports {alias.name}"
                        )

        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "ProposalCompletionRequest":
                violations.append(
                    f"{repair_path}:{node.lineno} builds ProposalCompletionRequest"
                )

    processor_class = next(
        node
        for node in ast.walk(processor_tree)
        if isinstance(node, ast.ClassDef) and node.name == "AIBuilderProposalProcessor"
    )
    for node in processor_class.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
            "run_tool_self_correction",
            "run_forced_tool_retry_after_text",
        }:
            violations.append(f"{processor_path}:{node.lineno} defines {node.name}")

    for node in ast.walk(repair_tree):
        if (
            isinstance(node, ast.ClassDef)
            and node.name == "BuildSelfCorrectionErrorEvent"
        ):
            violations.append(f"{repair_path}:{node.lineno} defines {node.name}")

    for node in repair_tree.body:
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "retry_forced_tool_after_text"
        ):
            violations.append(
                f"{repair_path}:{node.lineno} preserves public forced-retry core"
            )

    for name in {
        "ProposalSelfCorrectionRequest",
        "ForcedToolAfterTextRequest",
        "build_proposal_self_correction_request",
        "run_tool_self_correction",
        "run_forced_tool_retry_after_text",
    }:
        if name not in repair_text:
            violations.append(f"{repair_path}: missing {name}")

    if "BuildSelfCorrectionErrorEvent" in repair_text:
        violations.append(f"{repair_path}: preserves single-use error-event callback")

    assert violations == []


def test_proposal_submission_has_single_owner_and_typed_boundary() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    processor_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_processor.py"
    )
    submission_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_submission.py"
    )
    repair_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_repair.py"
    )
    architecture_errors_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_architecture_errors.py"
    )
    assert importlib.util.find_spec(PROPOSAL_SUBMISSION_MODULE) is not None

    processor_text = processor_path.read_text()
    processor_tree = ast.parse(processor_text, filename=str(processor_path))
    submission_text = submission_path.read_text()
    submission_tree = ast.parse(submission_text, filename=str(submission_path))
    repair_tree = ast.parse(repair_path.read_text(), filename=str(repair_path))
    architecture_errors_tree = ast.parse(
        architecture_errors_path.read_text(), filename=str(architecture_errors_path)
    )
    violations: list[str] = []

    processor_class = next(
        node
        for node in ast.walk(processor_tree)
        if isinstance(node, ast.ClassDef) and node.name == "AIBuilderProposalProcessor"
    )
    for node in processor_class.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in PROPOSAL_SUBMISSION_METHODS
        ):
            violations.append(f"{processor_path}:{node.lineno} defines {node.name}")

    for banned_import in {
        "process_create_intent_arguments",
        "process_edit_arguments",
        "build_create_flow_tool_schema",
        "build_edit_flow_tool_schema",
        "OUTLINE_FLOW_FORCED_TOOL_PROMPT",
        "EDIT_FLOW_FORCED_TOOL_PROMPT",
        "SUBMISSION_TOOL_NAMES",
    }:
        if banned_import in processor_text:
            violations.append(
                f"{processor_path}: imports or references {banned_import}"
            )

    for banned_reference in {
        "call_proposal_completion_with_usage",
        "active_submission_tool_name(",
        "active_submission_tool_schemas(",
        "_preflight_scoped_step_revision_if_requested(",
        "retry_forced_proposal_after_text(",
    }:
        if banned_reference in processor_text:
            violations.append(f"{processor_path}: references {banned_reference}")

    submission_classes = [
        node
        for node in ast.walk(submission_tree)
        if isinstance(node, ast.ClassDef) and node.name == "ProposalSubmissionOwner"
    ]
    if len(submission_classes) != 1:
        violations.append(
            f"{submission_path}: ProposalSubmissionOwner count {len(submission_classes)}"
        )
    else:
        submission_methods = {
            node.name: node
            for node in submission_classes[0].body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        public_methods = {
            node.name
            for node in submission_methods.values()
            if not node.name.startswith("_")
        }
        if public_methods != PROPOSAL_SUBMISSION_PUBLIC_METHODS:
            violations.append(
                f"{submission_path}:{submission_classes[0].lineno} public methods "
                f"{sorted(public_methods)}"
            )
        missing_private_methods = PROPOSAL_SUBMISSION_REQUIRED_PRIVATE_METHODS - set(
            submission_methods
        )
        if missing_private_methods:
            violations.append(
                f"{submission_path}:{submission_classes[0].lineno} missing private "
                f"methods {sorted(missing_private_methods)}"
            )
        stale_private_methods = PROPOSAL_SUBMISSION_STALE_PRIVATE_METHODS & set(
            submission_methods
        )
        if stale_private_methods:
            violations.append(
                f"{submission_path}:{submission_classes[0].lineno} stale private "
                f"methods {sorted(stale_private_methods)}"
            )
        for module in _imported_modules(submission_tree):
            if module in PROPOSAL_SUBMISSION_FORBIDDEN_IMPORT_MODULES:
                violations.append(f"{submission_path}: imports {module}")
        for node in ast.walk(submission_tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            imported_names = {alias.name for alias in node.names}
            forbidden_names = sorted(
                imported_names & PROPOSAL_SUBMISSION_FORBIDDEN_IMPORT_NAMES
            )
            if forbidden_names:
                violations.append(
                    f"{submission_path}:{node.lineno} imports {forbidden_names}"
                )

        retry_finalizers = [
            node
            for node in submission_methods.values()
            if node.name == "_finalize_invocation_proposal"
        ]
        if len(retry_finalizers) != 1:
            violations.append(
                f"{submission_path}:{submission_classes[0].lineno} "
                f"invocation finalizer count {len(retry_finalizers)}"
            )
        for method_name in ("_proposal_retry_config", "_process_submission_invocation"):
            method = submission_methods.get(method_name)
            if method is None:
                violations.append(f"{submission_path}: missing {method_name}")
                continue
            for child in ast.walk(method):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id == "CompiledProposalFinalizationRequest"
                ):
                    violations.append(
                        f"{submission_path}:{child.lineno} {method_name} "
                        "constructs CompiledProposalFinalizationRequest"
                    )

        finalization_request_call_count = submission_text.count(
            "CompiledProposalFinalizationRequest("
        )
        if finalization_request_call_count != 1:
            violations.append(
                f"{submission_path}: CompiledProposalFinalizationRequest calls "
                f"{finalization_request_call_count}"
            )

    for node in ast.walk(submission_tree):
        if isinstance(node, ast.ImportFrom) and (
            node.module in BANNED_PROPOSAL_PROCESSOR_IMPORTS
        ):
            violations.append(f"{submission_path}:{node.lineno} imports {node.module}")

        if isinstance(node, ast.ClassDef) and node.name.endswith(
            ("Processor", "Service", "Manager", "Handler")
        ):
            violations.append(f"{submission_path}:{node.lineno} defines {node.name}")

        if isinstance(node, ast.Attribute) and node.attr == "acompletion":
            violations.append(f"{submission_path}:{node.lineno} calls acompletion")

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.args.kwarg is not None:
                annotation = node.args.kwarg.annotation
                if annotation is not None and ast.unparse(annotation) == "Any":
                    violations.append(
                        f"{submission_path}:{node.lineno} defines **kwargs: Any"
                    )
            for arg in [*node.args.args, *node.args.kwonlyargs]:
                if _annotation_uses_any(arg.annotation) and (
                    arg.arg not in PROPOSAL_SUBMISSION_ALLOWED_ANY_NAMES
                ):
                    violations.append(
                        f"{submission_path}:{node.lineno} arg {arg.arg} uses Any"
                    )

        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if _annotation_uses_any(node.annotation) and (
                node.target.id not in PROPOSAL_SUBMISSION_ALLOWED_ANY_NAMES
            ):
                violations.append(
                    f"{submission_path}:{node.lineno} field {node.target.id} uses Any"
                )

    for helper_name in ARCHITECTURE_ERROR_HELPERS:
        owner_defs = [
            node.lineno
            for node in ast.walk(architecture_errors_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == helper_name
        ]
        if len(owner_defs) != 1:
            violations.append(
                f"{architecture_errors_path}: defines {helper_name} {len(owner_defs)} times"
            )
        for path, tree in (
            (submission_path, submission_tree),
            (repair_path, repair_tree),
        ):
            helper_defs = [
                node.lineno
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == helper_name
            ]
            if helper_defs:
                violations.append(f"{path}: defines {helper_name} at {helper_defs}")

    if "Callable[..., Any]" in submission_text:
        violations.append(f"{submission_path}: defines Callable[..., Any]")

    assert violations == []


def test_scoped_plan_revision_owns_direct_revision_without_llm_or_repair() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    scoped_path = backend_root / SCOPED_PLAN_REVISION_PATH
    create_path = backend_root / CREATE_PROPOSAL_PATH
    submission_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_submission.py"
    )
    assert importlib.util.find_spec(SCOPED_PLAN_REVISION_MODULE) is not None

    scoped_text = scoped_path.read_text()
    scoped_tree = ast.parse(scoped_text, filename=str(scoped_path))
    create_tree = ast.parse(create_path.read_text(), filename=str(create_path))
    submission_tree = ast.parse(
        submission_path.read_text(), filename=str(submission_path)
    )
    violations: list[str] = []

    forbidden_scoped_modules = {
        "eneo.flows.ai_builder.ai_builder_litellm_completion",
        "eneo.flows.ai_builder.ai_builder_proposal_repair",
    }
    for module in _imported_modules(scoped_tree):
        if module in forbidden_scoped_modules:
            violations.append(f"{scoped_path}: imports {module}")

    forbidden_scoped_names = {
        "ForcedToolAfterTextRequest",
        "ProposalSelfCorrectionRequest",
        "call_proposal_completion",
        "make_usage_tracked_proposal_completion",
        "run_forced_tool_retry_after_text",
        "run_tool_self_correction",
    }
    for node in ast.walk(scoped_tree):
        if isinstance(node, ast.Name) and node.id in forbidden_scoped_names:
            violations.append(f"{scoped_path}:{node.lineno} references {node.id}")
        if isinstance(node, ast.Name) and node.id == "Any":
            violations.append(f"{scoped_path}:{node.lineno} references Any")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "cast":
                violations.append(f"{scoped_path}:{node.lineno} casts type contract")
        if isinstance(node, ast.ImportFrom) and node.module == "typing":
            imported_names = {alias.name for alias in node.names}
            if "Any" in imported_names:
                violations.append(f"{scoped_path}:{node.lineno} imports Any")
    if "# type: ignore" in scoped_text:
        violations.append(f"{scoped_path}: contains type ignore")

    direct_revision_owner_names = {
        "process_scoped_step_revision_if_requested",
        "scoped_step_revision_assistant_text",
    }
    scoped_defs = {
        node.name
        for node in ast.walk(scoped_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing_defs = sorted(direct_revision_owner_names - scoped_defs)
    if missing_defs:
        violations.append(f"{scoped_path}: missing {missing_defs}")

    for path, tree in ((create_path, create_tree), (submission_path, submission_tree)):
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in direct_revision_owner_names:
                    violations.append(f"{path}:{node.lineno} defines {node.name}")
            if isinstance(node, ast.ImportFrom):
                imported_names = {alias.name for alias in node.names}
                forbidden_names = imported_names & direct_revision_owner_names
                if forbidden_names:
                    violations.append(
                        f"{path}:{node.lineno} imports {sorted(forbidden_names)}"
                    )

    assert violations == []


def test_proposal_submission_tests_do_not_import_processor_test_setup() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    submission_test_path = backend_root / Path(
        "tests/unittests/flows/ai_builder/test_ai_builder_proposal_submission.py"
    )
    tree = ast.parse(
        submission_test_path.read_text(), filename=str(submission_test_path)
    )
    violations: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module == PROPOSAL_PROCESSOR_TEST_MODULE:
            violations.append(
                f"{submission_test_path}:{node.lineno} imports {node.module}"
            )

    assert violations == []


def test_proposal_tests_import_canonical_setup_modules() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    expected_modules_by_path = {
        Path(
            "tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py"
        ): {
            PROPOSAL_TURN_BUILDERS_IMPORT_MODULE,
            PROPOSAL_TURN_TEST_DOUBLES_IMPORT_MODULE,
        },
        Path(
            "tests/unittests/flows/ai_builder/test_ai_builder_proposal_submission.py"
        ): {
            PROPOSAL_TURN_BUILDERS_IMPORT_MODULE,
            PROPOSAL_TURN_TEST_DOUBLES_IMPORT_MODULE,
        },
    }
    violations: list[str] = []

    for relative_path, expected_modules in expected_modules_by_path.items():
        path = backend_root / relative_path
        tree = ast.parse(path.read_text(), filename=str(path))
        imported_modules = {
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        missing_modules = sorted(expected_modules - imported_modules)
        if missing_modules:
            violations.append(f"{path}: missing imports {missing_modules}")

    assert violations == []


def test_proposal_tests_do_not_patch_private_submission_finalizer() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    violations: list[str] = []

    for relative_path in PROPOSAL_TEST_TOPOLOGY_FILES:
        path = backend_root / relative_path
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and (
                node.attr == "_compiled_proposal_finalizer"
            ):
                chain = _attribute_chain(node)
                violations.append(f"{path}:{node.lineno} reaches {chain}")

    assert violations == []


def test_proposal_submission_tests_construct_submission_owner_directly() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    submission_test_path = backend_root / Path(
        "tests/unittests/flows/ai_builder/test_ai_builder_proposal_submission.py"
    )
    tree = ast.parse(
        submission_test_path.read_text(), filename=str(submission_test_path)
    )
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "_proposal_submission":
            violations.append(
                f"{submission_test_path}:{node.lineno} reaches {_attribute_chain(node)}"
            )

    assert violations == []


def test_proposal_processor_tests_do_not_reach_into_submission_owner() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    processor_test_path = backend_root / Path(
        "tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py"
    )
    tree = ast.parse(processor_test_path.read_text(), filename=str(processor_test_path))
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "_proposal_submission":
            violations.append(
                f"{processor_test_path}:{node.lineno} reaches {_attribute_chain(node)}"
            )

    assert violations == []


def test_proposal_turn_test_setup_modules_keep_their_contracts() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    builder_path = backend_root / PROPOSAL_TURN_BUILDER_TEST_MODULE
    doubles_path = backend_root / PROPOSAL_TURN_TEST_DOUBLES_MODULE
    violations: list[str] = []

    if not builder_path.is_file():
        violations.append(f"{builder_path}: missing pure builder module")
    else:
        builder_tree = ast.parse(builder_path.read_text(), filename=str(builder_path))
        if not ast.get_docstring(builder_tree):
            violations.append(f"{builder_path}: missing ownership docstring")
        for node in ast.walk(builder_tree):
            if isinstance(node, ast.ImportFrom) and (
                node.module in PURE_PROPOSAL_TURN_BUILDER_BANNED_IMPORTS
            ):
                violations.append(f"{builder_path}:{node.lineno} imports {node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in PURE_PROPOSAL_TURN_BUILDER_BANNED_IMPORTS:
                        violations.append(
                            f"{builder_path}:{node.lineno} imports {alias.name}"
                        )
            if isinstance(node, ast.Name) and (
                node.id in PURE_PROPOSAL_TURN_BUILDER_BANNED_NAMES
            ):
                violations.append(f"{builder_path}:{node.lineno} uses {node.id}")

    if not doubles_path.is_file():
        violations.append(f"{doubles_path}: missing test-double module")
    else:
        doubles_tree = ast.parse(doubles_path.read_text(), filename=str(doubles_path))
        if not ast.get_docstring(doubles_tree):
            violations.append(f"{doubles_path}: missing ownership docstring")
        for node in ast.walk(doubles_tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    decorator_name = ast.unparse(decorator)
                    if decorator_name in PROPOSAL_TURN_TEST_DOUBLES_BANNED_DECORATORS:
                        violations.append(
                            f"{doubles_path}:{node.lineno} defines pytest fixture"
                        )

    assert violations == []


def test_server_decision_dispatch_has_canonical_owner() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    planner_path = backend_root / PLANNER_PATH
    dispatch_path = backend_root / SERVER_DECISION_DISPATCH_PATH
    violations: list[str] = []

    if not dispatch_path.is_file():
        violations.append(f"{dispatch_path}: missing server decision owner module")
    deleted_paths = (
        Path("src/eneo/flows/ai_builder/ai_builder_accepted_action_rendering.py"),
        Path("src/eneo/flows/ai_builder/ai_builder_planner_action_dispatch.py"),
        Path("src/eneo/flows/ai_builder/ai_builder_dispatcher.py"),
    )
    for path in deleted_paths:
        if (backend_root / path).exists():
            violations.append(f"{path}: stale planner action owner exists")

    planner_tree = ast.parse(planner_path.read_text(), filename=str(planner_path))
    planner_class = next(
        node
        for node in ast.walk(planner_tree)
        if isinstance(node, ast.ClassDef) and node.name == "AIBuilderPlanner"
    )
    planner_methods = {
        node.name
        for node in planner_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for method_name in {"_dispatch_server_question", "_dispatch_server_decision"}:
        if method_name in planner_methods:
            violations.append(f"{planner_path}: AIBuilderPlanner defines {method_name}")
    if "_requirements_summary_data" in _top_level_names(planner_tree):
        violations.append(f"{planner_path}: defines _requirements_summary_data")

    send_message = next(
        node
        for node in planner_class.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "send_message"
    )
    for node in ast.walk(send_message):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_build_new_messages"
        ):
            violations.append(
                f"{planner_path}:{node.lineno} defines _build_new_messages"
            )

    if dispatch_path.is_file():
        dispatch_tree = ast.parse(
            dispatch_path.read_text(), filename=str(dispatch_path)
        )
        public_names = _top_level_public_names(dispatch_tree)
        if public_names != SERVER_DECISION_DISPATCH_PUBLIC_NAMES:
            violations.append(f"{dispatch_path}: public names {sorted(public_names)}")
        for module in _imported_modules(dispatch_tree):
            if module in {
                AI_BUILDER_PLANNER_MODULE,
                AI_BUILDER_PROPOSAL_PROCESSOR_MODULE,
                "eneo.flows.ai_builder.ai_builder_orchestrator",
            }:
                violations.append(f"{dispatch_path}: imports {module}")
        for node in ast.walk(dispatch_tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith(
                ("Processor", "Manager", "Handler", "Service")
            ):
                violations.append(f"{dispatch_path}:{node.lineno} defines {node.name}")
            if isinstance(node, ast.ClassDef) and node.name.endswith("Request"):
                request_fields = [
                    stmt.target.id
                    for stmt in node.body
                    if isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                ]
                if len(request_fields) > 12:
                    violations.append(
                        f"{dispatch_path}:{node.lineno} has {len(request_fields)} fields"
                    )

    assert violations == []


def test_send_turn_lifecycle_has_canonical_owners() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    planner_path = backend_root / PLANNER_PATH
    send_lease_path = backend_root / SEND_LEASE_PATH
    metadata_path = backend_root / USER_QUESTION_METADATA_PATH
    violations: list[str] = []

    if importlib.util.find_spec(SEND_LEASE_MODULE) is None:
        violations.append(f"{send_lease_path}: missing send lease owner module")
    if importlib.util.find_spec(USER_QUESTION_METADATA_MODULE) is None:
        violations.append(
            f"{metadata_path}: missing user question metadata owner module"
        )

    planner_tree = ast.parse(planner_path.read_text(), filename=str(planner_path))
    planner_class = next(
        node
        for node in ast.walk(planner_tree)
        if isinstance(node, ast.ClassDef) and node.name == "AIBuilderPlanner"
    )
    planner_methods = {
        node.name
        for node in planner_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    stale_planner_methods = {
        "_send_lock_lease_seconds",
        "_next_send_lock_expiry",
        "_send_lock_refresh_interval_seconds",
        "_maintain_send_lock_lease",
        "_resolve_message_metadata",
    }
    for method_name in sorted(planner_methods & stale_planner_methods):
        violations.append(f"{planner_path}: AIBuilderPlanner defines {method_name}")

    planner_imports = _imported_modules(planner_tree)
    for required_module in {SEND_LEASE_MODULE, USER_QUESTION_METADATA_MODULE}:
        if required_module not in planner_imports:
            violations.append(f"{planner_path}: does not import {required_module}")

    for node in ast.walk(planner_tree):
        if isinstance(node, ast.Name) and node.id in {
            "SessionSendLease",
            "SessionSendTurn",
            "uuid4",
        }:
            violations.append(f"{planner_path}:{node.lineno} references {node.id}")

    if send_lease_path.is_file():
        send_lease_tree = ast.parse(
            send_lease_path.read_text(), filename=str(send_lease_path)
        )
        public_names = _top_level_public_names(send_lease_tree)
        if public_names != SEND_LEASE_PUBLIC_NAMES:
            violations.append(f"{send_lease_path}: public names {sorted(public_names)}")
        for module in _imported_modules(send_lease_tree):
            if module in {
                AI_BUILDER_PLANNER_MODULE,
                AI_BUILDER_PROPOSAL_PROCESSOR_MODULE,
                SERVER_DECISION_DISPATCH_MODULE,
                USER_QUESTION_METADATA_MODULE,
                "eneo.flows.ai_builder.ai_builder_litellm_completion",
            }:
                violations.append(f"{send_lease_path}: imports {module}")
        for node in ast.walk(send_lease_tree):
            if isinstance(node, ast.Name) and node.id == "Any":
                violations.append(f"{send_lease_path}:{node.lineno} references Any")

    if metadata_path.is_file():
        metadata_tree = ast.parse(
            metadata_path.read_text(), filename=str(metadata_path)
        )
        public_names = _top_level_public_names(metadata_tree)
        if public_names != USER_QUESTION_METADATA_PUBLIC_NAMES:
            violations.append(f"{metadata_path}: public names {sorted(public_names)}")
        for module in _imported_modules(metadata_tree):
            if module in {
                AI_BUILDER_PLANNER_MODULE,
                AI_BUILDER_PROPOSAL_PROCESSOR_MODULE,
                SERVER_DECISION_DISPATCH_MODULE,
                SEND_LEASE_MODULE,
                "eneo.flows.ai_builder.ai_builder_repo",
                "eneo.flows.ai_builder.ai_builder_litellm_completion",
            }:
                violations.append(f"{metadata_path}: imports {module}")
        for node in ast.walk(metadata_tree):
            if isinstance(node, ast.Name) and node.id == "Any":
                violations.append(f"{metadata_path}:{node.lineno} references Any")

    assert violations == []


def test_planner_request_preparation_has_canonical_owner() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    planner_path = backend_root / PLANNER_PATH
    preparation_path = backend_root / PLANNER_REQUEST_PREPARATION_PATH
    violations: list[str] = []

    if not preparation_path.is_file():
        violations.append(f"{preparation_path}: missing planner request owner module")

    planner_tree = ast.parse(planner_path.read_text(), filename=str(planner_path))
    planner_class = next(
        node
        for node in ast.walk(planner_tree)
        if isinstance(node, ast.ClassDef) and node.name == "AIBuilderPlanner"
    )
    planner_methods = {
        node.name
        for node in planner_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for method_name in {"_prepare_planner_request"}:
        if method_name in planner_methods:
            violations.append(f"{planner_path}: AIBuilderPlanner defines {method_name}")
    for helper_name in {
        "_emit_planner_failure_event",
        "_extract_first_validation_loc",
        "_get_mvs_forced_followup",
    }:
        if helper_name in _top_level_names(planner_tree):
            violations.append(f"{planner_path}: defines {helper_name}")
    for module in _imported_modules(planner_tree):
        if module == "eneo.flows.ai_builder.ai_builder_discovery_runtime":
            violations.append(f"{planner_path}: imports {module}")

    if preparation_path.is_file():
        preparation_tree = ast.parse(
            preparation_path.read_text(),
            filename=str(preparation_path),
        )
        public_names = _top_level_public_names(preparation_tree)
        if public_names != PLANNER_REQUEST_PREPARATION_PUBLIC_NAMES:
            violations.append(
                f"{preparation_path}: public names {sorted(public_names)}"
            )
        for module in _imported_modules(preparation_tree):
            if module in {
                AI_BUILDER_PLANNER_MODULE,
                AI_BUILDER_PROPOSAL_PROCESSOR_MODULE,
            }:
                violations.append(f"{preparation_path}: imports {module}")
        for node in ast.walk(preparation_tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith(
                ("Processor", "Manager", "Handler", "Service")
            ):
                violations.append(
                    f"{preparation_path}:{node.lineno} defines {node.name}"
                )
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "prepare_planner_request"
                and _annotation_uses_any(node.returns)
            ):
                violations.append(f"{preparation_path}:{node.lineno} returns Any")

    assert violations == []


def test_planner_failure_events_has_canonical_owner() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    planner_path = backend_root / PLANNER_PATH
    failure_events_path = backend_root / PLANNER_FAILURE_EVENTS_PATH
    violations: list[str] = []

    if not failure_events_path.is_file():
        violations.append(
            f"{failure_events_path}: missing planner failure owner module"
        )

    planner_tree = ast.parse(planner_path.read_text(), filename=str(planner_path))
    for helper_name in {
        "_emit_planner_failure_event",
        "_extract_first_validation_loc",
    }:
        if helper_name in _top_level_names(planner_tree):
            violations.append(f"{planner_path}: defines {helper_name}")

    if failure_events_path.is_file():
        failure_events_tree = ast.parse(
            failure_events_path.read_text(),
            filename=str(failure_events_path),
        )
        public_names = _top_level_public_names(failure_events_tree)
        if public_names != PLANNER_FAILURE_EVENTS_PUBLIC_NAMES:
            violations.append(
                f"{failure_events_path}: public names {sorted(public_names)}"
            )
        for module in _imported_modules(failure_events_tree):
            if module == AI_BUILDER_PLANNER_MODULE:
                violations.append(f"{failure_events_path}: imports {module}")
        for node in ast.walk(failure_events_tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith(
                ("Processor", "Manager", "Handler", "Service")
            ):
                violations.append(
                    f"{failure_events_path}:{node.lineno} defines {node.name}"
                )
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not node.name.startswith("_")
                and _annotation_uses_any(node.returns)
            ):
                violations.append(f"{failure_events_path}:{node.lineno} returns Any")

    assert violations == []


def test_create_outline_no_longer_owns_create_compiler_mechanics() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    outline_path = backend_root / PROPOSAL_INTENT_PATH
    compiler_path = backend_root / CREATE_COMPILER_PATH
    outline_tree = ast.parse(outline_path.read_text(), filename=str(outline_path))
    compiler_tree = ast.parse(compiler_path.read_text(), filename=str(compiler_path))
    violations: list[str] = []

    outline_top_level = _top_level_names(outline_tree)
    for name in sorted(outline_top_level & CREATE_COMPILER_PUBLIC_NAMES):
        violations.append(f"{outline_path}: defines {name}")

    for node in ast.walk(outline_tree):
        if isinstance(node, ast.ImportFrom):
            imported_names = {
                alias.name
                for alias in node.names
                if alias.name in PROPOSAL_INTENT_BANNED_COMPILER_NAMES
            }
            if imported_names:
                names = ", ".join(sorted(imported_names))
                violations.append(f"{outline_path}:{node.lineno} imports {names}")
        if (
            isinstance(node, ast.Name)
            and node.id in PROPOSAL_INTENT_BANNED_COMPILER_NAMES
        ):
            violations.append(f"{outline_path}:{node.lineno} references {node.id}")

    for path in (backend_root / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.ImportFrom)
                or node.module != PROPOSAL_INTENT_MODULE
            ):
                continue
            imported_names = {
                alias.name
                for alias in node.names
                if alias.name in CREATE_COMPILER_PUBLIC_NAMES or alias.name == "*"
            }
            if imported_names:
                names = ", ".join(sorted(imported_names))
                violations.append(f"{path}:{node.lineno} imports {names} from outline")

    compiler_public = _top_level_public_names(compiler_tree)
    missing_public = sorted(CREATE_COMPILER_PUBLIC_NAMES - compiler_public)
    if missing_public:
        violations.append(f"{compiler_path}: missing public names {missing_public}")

    compiler_text = compiler_path.read_text()
    if "build_create_flow_tool_schema" in compiler_text:
        violations.append(f"{compiler_path}: builds create intent LLM tool schema")

    assert violations == []


def test_create_form_fields_use_canonical_authoring_spec() -> None:
    violations: list[str] = []

    for path in _python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and (
                node.name == DELETED_CREATE_FORM_FIELD_DRAFT
            ):
                violations.append(f"{path}:{node.lineno} defines {node.name}")
            if isinstance(node, ast.ImportFrom):
                imported_names = {
                    alias.name
                    for alias in node.names
                    if alias.name == DELETED_CREATE_FORM_FIELD_DRAFT
                }
                if imported_names:
                    violations.append(
                        f"{path}:{node.lineno} imports {DELETED_CREATE_FORM_FIELD_DRAFT}"
                    )
            if (
                isinstance(node, ast.Name)
                and node.id == DELETED_CREATE_FORM_FIELD_DRAFT
            ):
                violations.append(f"{path}:{node.lineno} references {node.id}")

    assert violations == []


def test_create_proposal_does_not_own_runtime_hint_derivation() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    create_proposal_path = backend_root / CREATE_PROPOSAL_PATH
    create_proposal_tree = ast.parse(
        create_proposal_path.read_text(), filename=str(create_proposal_path)
    )
    banned_names = frozenset(
        {
            "runtime_metadata_state_from_planning_state",
            "_runtime_metadata_state_from_planning_state",
            "extract_runtime_input_field_hints",
            "runtime_metadata_allows_input_fields",
        }
    )
    violations: list[str] = []

    for node in ast.walk(create_proposal_tree):
        if isinstance(node, ast.ImportFrom) and node.module in {
            CREATE_COMPILER_MODULE,
            RUNTIME_INPUT_FIELDS_MODULE,
        }:
            imported_names = {
                alias.name for alias in node.names if alias.name in banned_names
            }
            if imported_names:
                names = ", ".join(sorted(imported_names))
                violations.append(
                    f"{create_proposal_path}:{node.lineno} imports {names}"
                )
        if isinstance(node, ast.Name) and node.id in banned_names:
            violations.append(
                f"{create_proposal_path}:{node.lineno} references {node.id}"
            )

    assert violations == []


def test_runtime_metadata_state_extraction_is_private_to_create_compiler() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    violations: list[str] = []

    for path in (backend_root / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.ImportFrom)
                or node.module != CREATE_COMPILER_MODULE
            ):
                continue
            imported_names = {
                alias.name
                for alias in node.names
                if alias.name == "_runtime_metadata_state_from_planning_state"
            }
            if imported_names:
                violations.append(
                    f"{path}:{node.lineno} imports _runtime_metadata_state_from_planning_state"
                )

    assert violations == []


def test_create_form_field_type_has_single_ai_builder_owner() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    outline_path = backend_root / PROPOSAL_INTENT_PATH
    compiler_path = backend_root / CREATE_COMPILER_PATH
    outline_tree = ast.parse(outline_path.read_text(), filename=str(outline_path))
    compiler_text = compiler_path.read_text()
    form_field_values = frozenset({"text", "number", "date", "select", "multiselect"})
    violations: list[str] = []

    if "cast(Any, hint.field_type)" in compiler_text:
        violations.append(f"{compiler_path}: casts runtime hint field_type through Any")
    if "cast(Any, field.field_type)" in compiler_text:
        violations.append(f"{compiler_path}: casts outline field_type through Any")

    for node in ast.walk(outline_tree):
        if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            continue
        values = {
            element.value
            for element in node.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
        if values == form_field_values:
            violations.append(
                f"{outline_path}:{node.lineno} hard-codes form-field type values"
            )

    assert violations == []


def test_repair_transport_facade_stays_deleted() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    repair_transport_path = backend_root / REPAIR_TRANSPORT_PATH
    proposal_repair_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_repair.py"
    )
    violations: list[str] = []

    if importlib.util.find_spec(REPAIR_TRANSPORT_MODULE) is not None:
        violations.append(f"{repair_transport_path}: repair transport facade exists")

    if repair_transport_path.exists():
        repair_tree = ast.parse(
            repair_transport_path.read_text(), filename=str(repair_transport_path)
        )
        for node in ast.walk(repair_tree):
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) and node.name in {
                "build_tool_retry_messages",
                "append_tool_retry_feedback_turn",
                "persist_tool_turn",
            }:
                violations.append(
                    f"{repair_transport_path}:{node.lineno} defines {node.name}"
                )

    proposal_repair_tree = ast.parse(
        proposal_repair_path.read_text(), filename=str(proposal_repair_path)
    )
    for node in ast.walk(proposal_repair_tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "append_retry_feedback_turn"
        ):
            violations.append(
                f"{proposal_repair_path}:{node.lineno} defines {node.name}"
            )

    for path in _python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == REPAIR_TRANSPORT_MODULE:
                    violations.append(f"{path}:{node.lineno} imports {node.module}")
                imported_names = {alias.name for alias in node.names}
                if "append_retry_feedback_turn" in imported_names:
                    violations.append(
                        f"{path}:{node.lineno} imports append_retry_feedback_turn"
                    )

    assert violations == []


def test_forced_proposal_tool_choice_has_single_owner() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    contracts_path = backend_root / Path(
        "src/eneo/flows/ai_builder/ai_builder_proposal_tool_contracts.py"
    )
    ai_builder_source_root = backend_root / Path("src/eneo/flows/ai_builder")
    duplicate_paths = [
        path for path in ai_builder_source_root.rglob("*.py") if path != contracts_path
    ]
    violations: list[str] = []

    contracts_tree = ast.parse(
        contracts_path.read_text(),
        filename=str(contracts_path),
    )
    if "forced_tool_choice" not in _top_level_public_names(contracts_tree):
        violations.append(f"{contracts_path}: missing forced_tool_choice owner")

    for path in duplicate_paths:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if any(
                keyword.arg == "tool_choice"
                and _is_forced_tool_choice_literal(keyword.value)
                for keyword in node.keywords
            ):
                violations.append(
                    f"{path}:{node.lineno} builds forced tool_choice inline"
                )

    assert violations == []


def _is_forced_tool_choice_literal(node: ast.AST) -> bool:
    if not isinstance(node, ast.Dict):
        return False
    literal_keys = {
        key.value
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    if literal_keys != {"type", "function"}:
        return False
    for key, value in zip(node.keys, node.values, strict=True):
        if (
            isinstance(key, ast.Constant)
            and key.value == "type"
            and isinstance(value, ast.Constant)
            and value.value == "function"
        ):
            return True
    return False


def test_tool_call_argument_json_parsing_has_single_owner() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    source_root = backend_root / "src/eneo/flows/ai_builder"

    violations: list[str] = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if _is_json_loads_function_arguments_call(node):
                violations.append(
                    f"{path}:{node.lineno} parses provider tool-call arguments "
                    "outside ai_builder_tool_parsing.parse_tool_call_arguments"
                )

    assert violations == []


def test_normalized_tool_calls_are_not_runtime_probed() -> None:
    violations: list[str] = []
    for path in _python_files():
        if "src/eneo/flows/ai_builder" not in path.as_posix():
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if _is_hasattr_tool_calls_call(node):
                violations.append(
                    f"{path}:{node.lineno} probes normalized message.tool_calls"
                )

    assert violations == []


def _annotation_uses_any(annotation: ast.expr | None) -> bool:
    return annotation is not None and any(
        isinstance(node, ast.Name) and node.id == "Any" for node in ast.walk(annotation)
    )


def _attribute_chain(node: ast.Attribute) -> str:
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    else:
        parts.append(ast.unparse(current))
    return ".".join(reversed(parts))


def _is_json_loads_function_arguments_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "loads"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "json"
    ):
        return False
    return any(
        isinstance(child, ast.Attribute)
        and _attribute_chain(child).endswith(".function.arguments")
        for argument in node.args
        for child in ast.walk(argument)
    )


def _is_hasattr_tool_calls_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "hasattr"
        and len(node.args) == 2
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == "tool_calls"
    )


def _top_level_public_names(tree: ast.Module) -> frozenset[str]:
    return frozenset(
        name for name in _top_level_names(tree) if not name.startswith("_")
    )


def _top_level_names(tree: ast.Module) -> frozenset[str]:
    return frozenset(
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _imported_modules(tree: ast.Module) -> frozenset[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return frozenset(modules)


def _python_files() -> list[Path]:
    backend_root = Path(__file__).resolve().parents[4]
    roots = (backend_root / "src", backend_root / "tests")
    return [path for root in roots for path in root.rglob("*.py") if path.is_file()]
