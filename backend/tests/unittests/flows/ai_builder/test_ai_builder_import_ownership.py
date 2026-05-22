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
DISCOVERY_FOLLOWUP_BRIDGE_METHOD = "emit_discovery_followup_if_needed"
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


def test_proposal_processor_does_not_own_discovery_followup_bridge() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    processor_path = backend_root / Path(
        "src/intric/flows/ai_builder/ai_builder_proposal_processor.py"
    )
    processor_tree = ast.parse(processor_path.read_text(), filename=str(processor_path))
    violations: list[str] = []
    class_found = False

    for node in ast.walk(processor_tree):
        if (
            not isinstance(node, ast.ClassDef)
            or node.name != "AIBuilderProposalProcessor"
        ):
            continue
        class_found = True
        for class_node in node.body:
            if (
                isinstance(class_node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and class_node.name == DISCOVERY_FOLLOWUP_BRIDGE_METHOD
            ):
                violations.append(
                    f"{processor_path}:{class_node.lineno} defines {class_node.name}"
                )

    assert class_found
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

    completion_import_count = 0
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
                        completion_import_count += 1
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

    if completion_import_count != 1:
        violations.append(
            f"{question_path}: call_proposal_completion_with_usage imports "
            f"{completion_import_count}"
        )
    if direct_completion_import_count:
        violations.append(f"{question_path}: imports call_proposal_completion")
    if question_text.count('"question-recovery"') != 1:
        violations.append(f"{question_path}: question-recovery literal count changed")

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


def _annotation_uses_any(annotation: ast.expr | None) -> bool:
    return annotation is not None and any(
        isinstance(node, ast.Name) and node.id == "Any" for node in ast.walk(annotation)
    )


def _python_files() -> list[Path]:
    backend_root = Path(__file__).resolve().parents[4]
    roots = (backend_root / "src", backend_root / "tests")
    return [path for root in roots for path in root.rglob("*.py") if path.is_file()]
