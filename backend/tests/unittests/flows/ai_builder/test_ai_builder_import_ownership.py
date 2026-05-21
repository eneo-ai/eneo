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


def _python_files() -> list[Path]:
    backend_root = Path(__file__).resolve().parents[4]
    roots = (backend_root / "src", backend_root / "tests")
    return [path for root in roots for path in root.rglob("*.py") if path.is_file()]
