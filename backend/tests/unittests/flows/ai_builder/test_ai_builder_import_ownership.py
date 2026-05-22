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


def test_proposal_processor_has_single_typed_completion_boundary() -> None:
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
    if len(acompletion_refs) != 1:
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


def _python_files() -> list[Path]:
    backend_root = Path(__file__).resolve().parents[4]
    roots = (backend_root / "src", backend_root / "tests")
    return [path for root in roots for path in root.rglob("*.py") if path.is_file()]
