from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

AI_BUILDER_MODELS_MODULE = ".".join(
    ("intric", "flows", "ai_builder", "ai_builder_models")
)
AI_BUILDER_DOMAIN_MODELS_MODULE = ".".join(
    ("intric", "flows", "ai_builder", "ai_builder_domain_models")
)
AI_BUILDER_PROPOSAL_PROCESSOR_MODULE = ".".join(
    ("intric", "flows", "ai_builder", "ai_builder_proposal_processor")
)
BANNED_PROPOSAL_PROCESSOR_IMPORTS = frozenset(
    {AI_BUILDER_PROPOSAL_PROCESSOR_MODULE, "ai_builder_proposal_processor"}
)
PROPOSAL_TOOL_MODULES = (
    Path("src/intric/flows/ai_builder/ai_builder_create_proposal.py"),
    Path("src/intric/flows/ai_builder/ai_builder_edit_proposal.py"),
)
PROPOSAL_PLAN_STORE_MODULE = ".".join(
    ("intric", "flows", "ai_builder", "ai_builder_plan_store")
)
PROPOSAL_POLICY_MODULE = ".".join(
    ("intric", "flows", "ai_builder", "ai_builder_proposal_policy")
)
PROPOSAL_FINALIZATION_MODULE = ".".join(
    ("intric", "flows", "ai_builder", "ai_builder_proposal_finalization")
)
PROPOSAL_REPAIR_MODULE = ".".join(
    ("intric", "flows", "ai_builder", "ai_builder_proposal_repair")
)
PROPOSAL_REPAIR_RUNTIME_MODULE = ".".join(
    ("intric", "flows", "ai_builder", "ai_builder_proposal_repair_runtime")
)
PROPOSAL_SUBMISSION_MODULE = ".".join(
    ("intric", "flows", "ai_builder", "ai_builder_proposal_submission")
)
PROPOSAL_TOOL_CONTRACTS_MODULE = ".".join(
    ("intric", "flows", "ai_builder", "ai_builder_proposal_tool_contracts")
)
BANNED_PROPOSAL_TOOL_IMPORT_MODULES = frozenset(
    {
        PROPOSAL_PLAN_STORE_MODULE,
        "intric.flows.ai_builder.ai_builder_events",
        "intric.flows.ai_builder.ai_builder_repo",
    }
)
BANNED_PROPOSAL_TOOL_NAMES = frozenset(
    {
        "AIBuilderRepository",
        "MCPClarificationFn",
        "ProposalToolDeps",
        "build_plan_event",
        "format_create_contextual_quality_feedback",
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
    "src/intric/flows/ai_builder/ai_builder_backend_question_persistence.py"
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
FINALIZATION_REPAIR_IMPORT_NAMES = frozenset(
    {
        "attempt_description_repair",
        "extract_description_provenance",
        "ProposalCompletionFn",
        "replace",
        "should_attempt_description_repair",
    }
)
FINALIZATION_REQUEST_REPAIR_FIELD_NAMES = frozenset(
    {"litellm_model", "litellm_kwargs", "max_output_tokens"}
)
QUESTION_RECOVERY_METHODS = frozenset(
    {"request_non_question_continuation", "_handle_structured_question"}
)
CONFIRM_REQUIREMENTS_METHODS = frozenset(
    {"_process_confirm_requirements_arguments", "_confirm_requirements_retry_config"}
)
QUESTION_RECOVERY_ALLOWED_ANY_NAMES = frozenset(
    {
        "assistant_metadata",
        "litellm_client",
        "litellm_kwargs",
        "llm_messages",
        "tool_call",
        "tool_calls",
        "tool_schemas",
    }
)
CONFIRM_REQUIREMENTS_ALLOWED_ANY_NAMES = frozenset(
    {
        "arguments",
        "assistant_metadata",
        "litellm_client",
        "litellm_kwargs",
    }
)
PROPOSAL_REPAIR_RUNTIME_METHODS = frozenset(
    {
        "_request_tool_self_correction",
        "retry_forced_tool_after_text",
    }
)
PROPOSAL_REPAIR_RUNTIME_ALLOWED_ANY_NAMES = frozenset(
    {
        "assistant_metadata",
        "build_assistant_metadata",
        "correction_messages",
        "litellm_kwargs",
        "llm_messages",
        "tool_call",
        "tool_schemas",
    }
)
PROPOSAL_SUBMISSION_METHODS = frozenset(
    {
        "active_submission_tool_name",
        "active_submission_tool_schemas",
        "_outline_flow_retry_config",
        "_edit_flow_retry_config",
        "_handle_outline_flow_tool_call",
        "_handle_edit_flow",
        "preflight_scoped_model_revision_if_requested",
        "retry_forced_proposal_after_text",
        "_active_submission_tool_schemas",
    }
)
PROPOSAL_SUBMISSION_PUBLIC_METHODS = frozenset(
    {
        "contains_submission_tool_call",
        "dispatch_submission_tool_call",
        "run_active_submission_attempt",
    }
)
SUBMISSION_TOOL_NAME_EXPRESSIONS = frozenset(
    {
        "edit_flow",
        "outline_flow",
        "EDIT_FLOW_TOOL_NAME",
        "OUTLINE_FLOW_TOOL_NAME",
    }
)
SUBMISSION_TOOL_SELECTION_VALUES = frozenset({"edit_flow", "outline_flow"})
ACTIVE_SUBMISSION_TOOL_NAME_OWNER = Path(
    "src/intric/flows/ai_builder/ai_builder_tools.py"
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
    ("intric", "flows", "ai_builder", "ai_builder_planner")
)
ACCEPTED_ACTION_RENDERING_MODULE = ".".join(
    ("intric", "flows", "ai_builder", "ai_builder_accepted_action_rendering")
)
PLANNER_ACTION_DISPATCH_MODULE = ".".join(
    ("intric", "flows", "ai_builder", "ai_builder_planner_action_dispatch")
)
PLANNER_REQUEST_PREPARATION_MODULE = ".".join(
    ("intric", "flows", "ai_builder", "ai_builder_planner_request_preparation")
)
PLANNER_FAILURE_EVENTS_MODULE = ".".join(
    ("intric", "flows", "ai_builder", "ai_builder_planner_failure_events")
)
ACCEPTED_ACTION_RENDERING_PATH = Path(
    "src/intric/flows/ai_builder/ai_builder_accepted_action_rendering.py"
)
PLANNER_ACTION_DISPATCH_PATH = Path(
    "src/intric/flows/ai_builder/ai_builder_planner_action_dispatch.py"
)
PLANNER_REQUEST_PREPARATION_PATH = Path(
    "src/intric/flows/ai_builder/ai_builder_planner_request_preparation.py"
)
PLANNER_FAILURE_EVENTS_PATH = Path(
    "src/intric/flows/ai_builder/ai_builder_planner_failure_events.py"
)
PLANNER_PATH = Path("src/intric/flows/ai_builder/ai_builder_planner.py")
CREATE_OUTLINE_MODULE = ".".join(
    ("intric", "flows", "ai_builder", "ai_builder_create_outline")
)
CREATE_OUTLINE_PATH = Path("src/intric/flows/ai_builder/ai_builder_create_outline.py")
CREATE_COMPILER_PATH = Path("src/intric/flows/ai_builder/ai_builder_create_compiler.py")
CREATE_COMPILER_PUBLIC_NAMES = frozenset(
    {
        "OutlineCompileContext",
        "compile_create_draft",
        "compile_outline_to_create_draft",
        "outline_compile_context_from_planning_state",
        "runtime_metadata_state_from_planning_state",
    }
)
CREATE_OUTLINE_BANNED_COMPILER_NAMES = frozenset(
    {
        "ArchitectureCommit",
        "ArchitectureCommitDraft",
        "ArchitectureEnvelope",
        "AIBuilderArchitectureError",
        "FlowCreateDraft",
        "OutlineCompileContext",
        "PlanningState",
        "compile_outline_to_create_draft",
        "derive_architecture_commit_draft",
        "materialize_step_skeleton",
        "outline_compile_context_from_planning_state",
        "resolve_step_skeleton_patterns",
        "runtime_metadata_state_from_planning_state",
    }
)
ACCEPTED_ACTION_RENDERING_PUBLIC_NAMES = frozenset(
    {
        "RequirementsSummaryRenderContext",
        "build_accepted_action_events",
        "build_accepted_action_messages",
        "build_requirements_summary_data",
    }
)
PLANNER_ACTION_DISPATCH_PUBLIC_NAMES = frozenset(
    {
        "BackendSelectedQuestionDispatchRequest",
        "DispatchedActionEventRequest",
        "build_dispatched_action_events",
        "dispatch_backend_selected_question_if_any",
    }
)
PLANNER_REQUEST_PREPARATION_PUBLIC_NAMES = frozenset(
    {
        "DiscoveryBlockPrepared",
        "NormalPlannerPrepared",
        "PlannerRequestPreparationInput",
        "PreparedPromptMessages",
        "ProposalPrepared",
        "ServerOutputPrepared",
        "conversation_message_to_llm_dict",
        "prepare_planner_request",
    }
)
PLANNER_FAILURE_EVENTS_PUBLIC_NAMES = frozenset(
    {
        "PlannerTurnResultEventRequest",
        "build_planner_turn_error_event",
        "build_planner_upstream_error_event",
        "build_session_send_lease_lost_event",
        "record_planner_turn_result",
    }
)
PLANNER_ACTION_CLASSES = frozenset(
    {"AskQuestionAction", "CommitArchitectureAction", "ConfirmRequirementsAction"}
)
PURE_PROPOSAL_TURN_BUILDER_BANNED_IMPORTS = frozenset(
    {
        "pytest",
        "types",
        "unittest.mock",
        "intric.flows.ai_builder.ai_builder_proposal_processor",
        "intric.flows.ai_builder.ai_builder_proposal_submission",
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
    path = backend_root / Path("src/intric/flows/ai_builder/ai_builder_plan_store.py")
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
        "src/intric/flows/ai_builder/ai_builder_proposal_finalization.py"
    )
    processor_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_processor.py"
    )
    contracts_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_tool_contracts.py"
    )
    critic_paths = (
        backend_root
        / Path("src/intric/flows/ai_builder/ai_builder_plan_quality_critic.py"),
        backend_root
        / Path("src/intric/flows/ai_builder/ai_builder_create_feedback.py"),
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
            "intric.flows.ai_builder.ai_builder_discovery_runtime",
            "intric.flows.ai_builder.ai_builder_slot_classifier",
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


def test_compiled_proposal_finalization_does_not_own_edit_repair() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    finalization_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_finalization.py"
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
                if alias.name in FINALIZATION_REPAIR_IMPORT_NAMES
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
            repair_field_names = sorted(
                request_field_names & FINALIZATION_REQUEST_REPAIR_FIELD_NAMES
            )
            if repair_field_names:
                fields = ", ".join(repair_field_names)
                violations.append(
                    f"{finalization_path}:{node.lineno} request fields {fields}"
                )

    assert violations == []


def test_proposal_processor_no_longer_owns_completion_boundary() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    processor_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_processor.py"
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


def test_proposal_completion_has_single_typed_completion_boundary() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    completion_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_completion.py"
    )
    completion_tree = ast.parse(
        completion_path.read_text(), filename=str(completion_path)
    )

    acompletion_refs = [
        node
        for node in ast.walk(completion_tree)
        if isinstance(node, ast.Attribute) and node.attr == "acompletion"
    ]
    violations: list[str] = []
    if len(acompletion_refs) != 1:
        lines = ", ".join(str(node.lineno) for node in acompletion_refs) or "none"
        violations.append(f"{completion_path}: acompletion refs {lines}")

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


def test_proposal_completion_dependency_direction_stays_leaf_owned() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    completion_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_completion.py"
    )
    telemetry_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py"
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
            "intric.flows.ai_builder.ai_builder_proposal_processor",
            "intric.flows.ai_builder.ai_builder_planner",
        }:
            violations.append(f"{completion_path}:{node.lineno} imports {node.module}")

    for node in ast.walk(telemetry_tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module == "intric.flows.ai_builder.ai_builder_proposal_completion":
            violations.append(f"{telemetry_path}:{node.lineno} imports {node.module}")

    assert violations == []


def _submission_tool_name_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if node.value in SUBMISSION_TOOL_SELECTION_VALUES:
            return node.value
        return None
    if isinstance(node, ast.Name):
        if node.id == "EDIT_FLOW_TOOL_NAME":
            return "edit_flow"
        if node.id == "OUTLINE_FLOW_TOOL_NAME":
            return "outline_flow"
    return None


def _selection_assignment_values(statements: list[ast.stmt]) -> dict[str, str]:
    values: dict[str, str] = {}
    for statement in statements:
        targets: list[ast.AST]
        value: ast.AST
        if isinstance(statement, ast.Assign):
            targets = list(statement.targets)
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
            value = statement.value
        else:
            continue
        tool_name = _submission_tool_name_value(value)
        if tool_name is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                values[target.id] = tool_name
    return values


def test_active_submission_tool_name_has_single_owner() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    src_root = backend_root / Path("src/intric/flows/ai_builder")
    violations: list[str] = []
    helper_definitions: list[str] = []

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
                helper_definitions.append(f"{rel_path}:{node.lineno}:{node.name}")
                if rel_path != ACTIVE_SUBMISSION_TOOL_NAME_OWNER:
                    violations.append(f"{rel_path}:{node.lineno} defines {node.name}")

            if rel_path == ACTIVE_SUBMISSION_TOOL_NAME_OWNER:
                continue

            if isinstance(node, ast.IfExp):
                selected = {
                    value
                    for value in (
                        _submission_tool_name_value(node.body),
                        _submission_tool_name_value(node.orelse),
                    )
                    if value is not None
                }
                if selected == SUBMISSION_TOOL_SELECTION_VALUES:
                    violations.append(
                        f"{rel_path}:{node.lineno} selects active submission tool "
                        "with a ternary"
                    )

            if isinstance(node, ast.If):
                body_values = _selection_assignment_values(node.body)
                else_values = _selection_assignment_values(node.orelse)
                for target_name, body_value in body_values.items():
                    else_value = else_values.get(target_name)
                    if {body_value, else_value} == SUBMISSION_TOOL_SELECTION_VALUES:
                        violations.append(
                            f"{rel_path}:{node.lineno} selects active submission "
                            f"tool in if/else assignment to {target_name}"
                        )

    owner_definitions = [
        definition
        for definition in helper_definitions
        if definition.startswith(f"{ACTIVE_SUBMISSION_TOOL_NAME_OWNER}:")
        and definition.endswith(":active_submission_tool_name")
    ]
    if len(owner_definitions) != 1:
        violations.append(
            "active_submission_tool_name must have exactly one owner definition; "
            f"found {helper_definitions}"
        )

    assert violations == []


def test_question_recovery_has_single_owner_and_typed_boundary() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    processor_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_processor.py"
    )
    question_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_question_recovery.py"
    )
    processor_tree = ast.parse(processor_path.read_text(), filename=str(processor_path))
    question_text = question_path.read_text()
    question_tree = ast.parse(question_text, filename=str(question_path))
    violations: list[str] = []

    processor_class = next(
        node
        for node in ast.walk(processor_tree)
        if isinstance(node, ast.ClassDef) and node.name == "AIBuilderProposalProcessor"
    )
    for node in processor_class.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in QUESTION_RECOVERY_METHODS
        ):
            violations.append(f"{processor_path}:{node.lineno} defines {node.name}")

    request_class = next(
        node
        for node in ast.walk(question_tree)
        if isinstance(node, ast.ClassDef)
        and node.name == "StructuredQuestionRecoveryRequest"
    )
    request_fields = [
        stmt.target.id
        for stmt in request_class.body
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
    ]
    if len(request_fields) > 12:
        violations.append(
            f"{question_path}:{request_class.lineno} fields {request_fields}"
        )

    tracked_completion_import_count = 0
    direct_completion_import_count = 0
    for node in ast.walk(question_tree):
        if isinstance(node, ast.ImportFrom):
            if node.module in BANNED_PROPOSAL_PROCESSOR_IMPORTS:
                violations.append(
                    f"{question_path}:{node.lineno} imports {node.module}"
                )
            if node.module == "intric.flows.ai_builder.ai_builder_proposal_completion":
                for alias in node.names:
                    if alias.name == "call_proposal_completion_with_usage":
                        tracked_completion_import_count += 1
                    if alias.name == "call_proposal_completion":
                        direct_completion_import_count += 1

        if isinstance(node, ast.ClassDef) and node.name.endswith(
            ("Processor", "Service", "Manager")
        ):
            violations.append(f"{question_path}:{node.lineno} defines {node.name}")

        if isinstance(node, ast.Attribute) and node.attr == "acompletion":
            violations.append(f"{question_path}:{node.lineno} calls acompletion")

        if isinstance(node, ast.Name) and node.id in {
            "AIBuilderProposalProcessor",
            "ProposalContext",
            "handle_tool_call",
            "from_context",
        }:
            violations.append(f"{question_path}:{node.lineno} uses {node.id}")

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.args.kwarg is not None:
                annotation = node.args.kwarg.annotation
                if annotation is not None and ast.unparse(annotation) == "Any":
                    violations.append(
                        f"{question_path}:{node.lineno} defines **kwargs: Any"
                    )
            for arg in [*node.args.args, *node.args.kwonlyargs]:
                if _annotation_uses_any(arg.annotation) and (
                    arg.arg not in QUESTION_RECOVERY_ALLOWED_ANY_NAMES
                ):
                    violations.append(
                        f"{question_path}:{node.lineno} arg {arg.arg} uses Any"
                    )

        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if _annotation_uses_any(node.annotation) and (
                node.target.id not in QUESTION_RECOVERY_ALLOWED_ANY_NAMES
            ):
                violations.append(
                    f"{question_path}:{node.lineno} field {node.target.id} uses Any"
                )

    if tracked_completion_import_count:
        violations.append(
            f"{question_path}: call_proposal_completion_with_usage imports "
            f"{tracked_completion_import_count}"
        )
    if direct_completion_import_count != 1:
        violations.append(
            f"{question_path}: call_proposal_completion imports "
            f"{direct_completion_import_count}"
        )
    if question_text.count('"question-recovery"') != 1:
        violations.append(f"{question_path}: question-recovery literal count changed")

    assert violations == []


def test_proposal_completion_has_single_request_boundary() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    contracts_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_tool_contracts.py"
    )
    completion_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_completion.py"
    )
    submission_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_submission.py"
    )
    proposal_callers = [
        backend_root / Path("src/intric/flows/ai_builder/ai_builder_edit_repair.py"),
        backend_root
        / Path("src/intric/flows/ai_builder/ai_builder_proposal_repair.py"),
        submission_path,
        backend_root
        / Path("src/intric/flows/ai_builder/ai_builder_question_recovery.py"),
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


def test_planner_completion_has_single_provider_boundary() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    completion_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_planner_completion.py"
    )
    repair_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_repair.py"
    )
    pipeline_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_orchestration_pipeline.py"
    )

    completion_tree = ast.parse(
        completion_path.read_text(), filename=str(completion_path)
    )
    violations: list[str] = []

    acompletion_refs = [
        node
        for node in ast.walk(completion_tree)
        if isinstance(node, ast.Attribute) and node.attr == "acompletion"
    ]
    if len(acompletion_refs) != 1:
        lines = ", ".join(str(node.lineno) for node in acompletion_refs) or "none"
        violations.append(f"{completion_path}: acompletion refs {lines}")

    for path in (repair_path, pipeline_path):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "acompletion":
                violations.append(f"{path}:{node.lineno} calls acompletion")

    completion_imports = _imported_modules(completion_tree)
    banned_imports = {
        "intric.flows.ai_builder.ai_builder_repair",
        "intric.flows.ai_builder.ai_builder_orchestration_pipeline",
        "intric.flows.ai_builder.ai_builder_planner_turn",
        "intric.flows.ai_builder.ai_builder_router",
        "intric.flows.ai_builder.ai_builder_api_models",
    }
    for module in sorted(completion_imports & banned_imports):
        violations.append(f"{completion_path}: imports {module}")

    repair_tree = ast.parse(repair_path.read_text(), filename=str(repair_path))
    for node in ast.walk(repair_tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in {
            "CompletionMetadata",
            "completion_metadata_from_response",
        }:
            violations.append(f"{repair_path}:{node.lineno} defines {node.name}")

    assert violations == []


def test_confirm_requirements_has_single_owner_and_typed_boundary() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    processor_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_processor.py"
    )
    confirm_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_confirm_requirements.py"
    )
    processor_text = processor_path.read_text()
    confirm_text = confirm_path.read_text()
    processor_tree = ast.parse(processor_text, filename=str(processor_path))
    confirm_tree = ast.parse(confirm_text, filename=str(confirm_path))
    violations: list[str] = []

    processor_class = next(
        node
        for node in ast.walk(processor_tree)
        if isinstance(node, ast.ClassDef) and node.name == "AIBuilderProposalProcessor"
    )
    for node in processor_class.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in CONFIRM_REQUIREMENTS_METHODS
        ):
            violations.append(f"{processor_path}:{node.lineno} defines {node.name}")
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_handle_confirm_requirements"
        ):
            source = ast.get_source_segment(processor_text, node) or ""
            if "ASK_STRUCTURED_QUESTION_TOOL_NAME" in source:
                violations.append(
                    f"{processor_path}:{node.lineno} confirm handler owns ask stub"
                )

    for node in ast.walk(processor_tree):
        if isinstance(node, ast.Name) and node.id == "parse_confirm_requirements":
            violations.append(f"{processor_path}:{node.lineno} parses requirements")

    for node in ast.walk(confirm_tree):
        if isinstance(node, ast.ImportFrom) and (
            node.module in BANNED_PROPOSAL_PROCESSOR_IMPORTS
        ):
            violations.append(f"{confirm_path}:{node.lineno} imports {node.module}")

        if isinstance(node, ast.ClassDef):
            if node.name == "ConfirmRequirementsOutcome":
                violations.append(f"{confirm_path}:{node.lineno} defines {node.name}")
            if node.name.endswith(("Processor", "Service", "Manager")):
                violations.append(f"{confirm_path}:{node.lineno} defines {node.name}")

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.args.kwarg is not None:
                annotation = node.args.kwarg.annotation
                if annotation is not None and ast.unparse(annotation) == "Any":
                    violations.append(
                        f"{confirm_path}:{node.lineno} defines **kwargs: Any"
                    )
            for arg in [*node.args.args, *node.args.kwonlyargs]:
                if _annotation_uses_any(arg.annotation) and (
                    arg.arg not in CONFIRM_REQUIREMENTS_ALLOWED_ANY_NAMES
                ):
                    violations.append(
                        f"{confirm_path}:{node.lineno} arg {arg.arg} uses Any"
                    )

        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if _annotation_uses_any(node.annotation) and (
                node.target.id not in CONFIRM_REQUIREMENTS_ALLOWED_ANY_NAMES
            ):
                violations.append(
                    f"{confirm_path}:{node.lineno} field {node.target.id} uses Any"
                )

    if 'tool_calls=[{"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}]' not in confirm_text:
        violations.append(f"{confirm_path}: missing synthetic ask-question stub")

    assert violations == []


def test_proposal_repair_runtime_has_single_owner_and_typed_boundary() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    processor_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_processor.py"
    )
    repair_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_repair.py"
    )
    runtime_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_repair_runtime.py"
    )
    assert importlib.util.find_spec(PROPOSAL_REPAIR_RUNTIME_MODULE) is not None

    processor_tree = ast.parse(processor_path.read_text(), filename=str(processor_path))
    repair_tree = ast.parse(repair_path.read_text(), filename=str(repair_path))
    runtime_text = runtime_path.read_text()
    runtime_tree = ast.parse(runtime_text, filename=str(runtime_path))
    violations: list[str] = []

    processor_class = next(
        node
        for node in ast.walk(processor_tree)
        if isinstance(node, ast.ClassDef) and node.name == "AIBuilderProposalProcessor"
    )
    for node in processor_class.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in PROPOSAL_REPAIR_RUNTIME_METHODS
        ):
            violations.append(f"{processor_path}:{node.lineno} defines {node.name}")

    for node in ast.walk(repair_tree):
        if (
            isinstance(node, ast.ClassDef)
            and node.name == "BuildSelfCorrectionErrorEvent"
        ):
            violations.append(f"{repair_path}:{node.lineno} defines {node.name}")

    for node in ast.walk(runtime_tree):
        if isinstance(node, ast.ImportFrom) and (
            node.module in BANNED_PROPOSAL_PROCESSOR_IMPORTS
        ):
            violations.append(f"{runtime_path}:{node.lineno} imports {node.module}")

        if isinstance(node, ast.ClassDef) and node.name.endswith(
            ("Processor", "Service", "Manager", "Handler")
        ):
            violations.append(f"{runtime_path}:{node.lineno} defines {node.name}")

        if isinstance(node, ast.Attribute) and node.attr == "acompletion":
            violations.append(f"{runtime_path}:{node.lineno} calls acompletion")

        if isinstance(node, ast.Name) and node.id == "litellm_client":
            violations.append(f"{runtime_path}:{node.lineno} uses litellm_client")

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.args.kwarg is not None:
                annotation = node.args.kwarg.annotation
                if annotation is not None and ast.unparse(annotation) == "Any":
                    violations.append(
                        f"{runtime_path}:{node.lineno} defines **kwargs: Any"
                    )
            for arg in [*node.args.args, *node.args.kwonlyargs]:
                if _annotation_uses_any(arg.annotation) and (
                    arg.arg not in PROPOSAL_REPAIR_RUNTIME_ALLOWED_ANY_NAMES
                ):
                    violations.append(
                        f"{runtime_path}:{node.lineno} arg {arg.arg} uses Any"
                    )

        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if _annotation_uses_any(node.annotation) and (
                node.target.id not in PROPOSAL_REPAIR_RUNTIME_ALLOWED_ANY_NAMES
            ):
                violations.append(
                    f"{runtime_path}:{node.lineno} field {node.target.id} uses Any"
                )

    if "BuildSelfCorrectionErrorEvent" in runtime_text:
        violations.append(f"{runtime_path}: preserves single-use error-event callback")

    assert violations == []


def test_proposal_submission_has_single_owner_and_typed_boundary() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    processor_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_processor.py"
    )
    submission_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_submission.py"
    )
    runtime_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_repair_runtime.py"
    )
    architecture_errors_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_architecture_errors.py"
    )
    assert importlib.util.find_spec(PROPOSAL_SUBMISSION_MODULE) is not None

    processor_text = processor_path.read_text()
    processor_tree = ast.parse(processor_text, filename=str(processor_path))
    submission_text = submission_path.read_text()
    submission_tree = ast.parse(submission_text, filename=str(submission_path))
    runtime_tree = ast.parse(runtime_path.read_text(), filename=str(runtime_path))
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
        "process_outline_arguments",
        "process_edit_arguments",
        "repair_compiled_edit_description_if_needed",
        "build_outline_flow_tool_schema",
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
        "preflight_scoped_model_revision_if_requested(",
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
        public_methods = {
            node.name
            for node in submission_classes[0].body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        }
        if public_methods != PROPOSAL_SUBMISSION_PUBLIC_METHODS:
            violations.append(
                f"{submission_path}:{submission_classes[0].lineno} public methods "
                f"{sorted(public_methods)}"
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
        runtime_defs = [
            node.lineno
            for node in ast.walk(runtime_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == helper_name
        ]
        if runtime_defs:
            violations.append(
                f"{runtime_path}: defines {helper_name} at {runtime_defs}"
            )

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

    if "Callable[..., Any]" in submission_text:
        violations.append(f"{submission_path}: defines Callable[..., Any]")

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


def test_planner_action_rendering_and_dispatch_have_canonical_owners() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    planner_path = backend_root / PLANNER_PATH
    rendering_path = backend_root / ACCEPTED_ACTION_RENDERING_PATH
    dispatch_path = backend_root / PLANNER_ACTION_DISPATCH_PATH
    violations: list[str] = []

    for path in (rendering_path, dispatch_path):
        if not path.is_file():
            violations.append(f"{path}: missing planner action owner module")

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
    for method_name in {
        "_dispatch_server_question",
        "_dispatch_chained_server_action_after_commit",
    }:
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
        if _isinstance_matches_planner_action(node):
            violations.append(
                f"{planner_path}:{node.lineno} directly checks planner action type"
            )

    if rendering_path.is_file():
        rendering_text = rendering_path.read_text()
        rendering_tree = ast.parse(rendering_text, filename=str(rendering_path))
        public_names = _top_level_public_names(rendering_tree)
        if public_names != ACCEPTED_ACTION_RENDERING_PUBLIC_NAMES:
            violations.append(f"{rendering_path}: public names {sorted(public_names)}")
        for module in _imported_modules(rendering_tree):
            if module in {
                AI_BUILDER_PLANNER_MODULE,
                AI_BUILDER_PROPOSAL_PROCESSOR_MODULE,
                "intric.flows.ai_builder.ai_builder_repo",
                "intric.flows.ai_builder.ai_builder_backend_question_persistence",
            }:
                violations.append(f"{rendering_path}: imports {module}")
        for node in ast.walk(rendering_tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "intric.flows.ai_builder.ai_builder_planner_turn"
            ):
                banned_names = sorted(
                    alias.name for alias in node.names if alias.name != "TurnTelemetry"
                )
                if banned_names:
                    names = ", ".join(banned_names)
                    violations.append(f"{rendering_path}:{node.lineno} imports {names}")
        for node in ast.walk(rendering_tree):
            if (
                isinstance(node, ast.Dict)
                and node.keys
                and all(isinstance(key, ast.Constant) for key in node.keys)
                and {"event", "data"} <= {key.value for key in node.keys}
            ):
                violations.append(f"{rendering_path}:{node.lineno} builds SSE dict")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                docstring = ast.get_docstring(node)
                if docstring is not None and len(docstring.splitlines()) > 6:
                    violations.append(f"{rendering_path}:{node.lineno} long docstring")

    if dispatch_path.is_file():
        dispatch_tree = ast.parse(
            dispatch_path.read_text(), filename=str(dispatch_path)
        )
        public_names = _top_level_public_names(dispatch_tree)
        if public_names != PLANNER_ACTION_DISPATCH_PUBLIC_NAMES:
            violations.append(f"{dispatch_path}: public names {sorted(public_names)}")
        for module in _imported_modules(dispatch_tree):
            if module in {
                AI_BUILDER_PLANNER_MODULE,
                AI_BUILDER_PROPOSAL_PROCESSOR_MODULE,
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
    for method_name in {
        "_prepare_planner_request",
        "_should_emit_forced_followup",
    }:
        if method_name in planner_methods:
            violations.append(f"{planner_path}: AIBuilderPlanner defines {method_name}")
    for helper_name in {
        "_count_free_discovery_turns",
        "_emit_planner_failure_event",
        "_extract_first_validation_loc",
        "_get_mvs_forced_followup",
    }:
        if helper_name in _top_level_names(planner_tree):
            violations.append(f"{planner_path}: defines {helper_name}")
    for module in _imported_modules(planner_tree):
        if module == "intric.flows.ai_builder.ai_builder_discovery_runtime":
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
    outline_path = backend_root / CREATE_OUTLINE_PATH
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
                if alias.name in CREATE_OUTLINE_BANNED_COMPILER_NAMES
            }
            if imported_names:
                names = ", ".join(sorted(imported_names))
                violations.append(f"{outline_path}:{node.lineno} imports {names}")
        if (
            isinstance(node, ast.Name)
            and node.id in CREATE_OUTLINE_BANNED_COMPILER_NAMES
        ):
            violations.append(f"{outline_path}:{node.lineno} references {node.id}")

    for path in (backend_root / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.ImportFrom)
                or node.module != CREATE_OUTLINE_MODULE
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
    if "build_outline_flow_tool_schema" in compiler_text:
        violations.append(f"{compiler_path}: builds outline LLM tool schema")

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


def _isinstance_matches_planner_action(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Name) or node.func.id != "isinstance":
        return False
    if len(node.args) < 2:
        return False
    checked = node.args[1]
    if isinstance(checked, ast.Name):
        return checked.id in PLANNER_ACTION_CLASSES
    if isinstance(checked, ast.Tuple):
        return any(
            isinstance(element, ast.Name) and element.id in PLANNER_ACTION_CLASSES
            for element in checked.elts
        )
    return False


def _python_files() -> list[Path]:
    backend_root = Path(__file__).resolve().parents[4]
    roots = (backend_root / "src", backend_root / "tests")
    return [path for root in roots for path in root.rglob("*.py") if path.is_file()]
