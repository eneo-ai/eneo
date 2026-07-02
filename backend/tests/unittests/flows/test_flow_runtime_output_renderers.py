from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

FLOW_RUNTIME_ROOT = (
    Path(__file__).resolve().parents[3] / "src" / "eneo" / "flows" / "runtime"
)
DOCUMENT_RENDERING_DEPENDENCIES = frozenset(
    {"docx", "docxtpl", "weasyprint", "markdown_it"}
)
ALLOWED_DOCUMENT_RENDERING_DEPENDENCY_PATHS = frozenset(
    {"celery_preflight.py", "docx_template_runtime.py"}
)
ALLOWED_DOCUMENT_RENDERING_DEPENDENCY_PREFIXES = ("document_rendering/",)


@dataclass(frozen=True, order=True)
class _DocumentDependencyUse:
    relative_path: str
    module: str
    expression: str


def _runtime_python_files() -> list[Path]:
    return [
        path
        for path in FLOW_RUNTIME_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _module_root(module: str | None) -> str | None:
    if module is None:
        return None
    return module.split(".", maxsplit=1)[0]


def _is_document_dependency(module: str | None) -> bool:
    root = _module_root(module)
    return root is not None and root in DOCUMENT_RENDERING_DEPENDENCIES


def _document_dependency_uses_in_tree(
    tree: ast.AST, *, relative_path: str
) -> frozenset[_DocumentDependencyUse]:
    uses: set[_DocumentDependencyUse] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_document_dependency(alias.name):
                    uses.add(
                        _DocumentDependencyUse(
                            relative_path=relative_path,
                            module=_module_root(alias.name) or alias.name,
                            expression=ast.unparse(node),
                        )
                    )
        elif isinstance(node, ast.ImportFrom) and _is_document_dependency(node.module):
            uses.add(
                _DocumentDependencyUse(
                    relative_path=relative_path,
                    module=_module_root(node.module) or node.module or "",
                    expression=ast.unparse(node),
                )
            )
        elif _is_import_module_call(node):
            module_arg = node.args[0]
            if isinstance(module_arg, ast.Constant) and isinstance(
                module_arg.value, str
            ):
                module = module_arg.value
                if _is_document_dependency(module):
                    uses.add(
                        _DocumentDependencyUse(
                            relative_path=relative_path,
                            module=_module_root(module) or module,
                            expression=ast.unparse(node),
                        )
                    )
    return frozenset(uses)


def _is_import_module_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or not node.args:
        return False
    if isinstance(node.func, ast.Name) and node.func.id == "__import__":
        return True
    if isinstance(node.func, ast.Name) and node.func.id == "import_module":
        return True
    return isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"


def _runtime_document_dependency_uses() -> frozenset[_DocumentDependencyUse]:
    uses: set[_DocumentDependencyUse] = set()
    for path in _runtime_python_files():
        relative_path = path.relative_to(FLOW_RUNTIME_ROOT).as_posix()
        tree = ast.parse(path.read_text(), filename=str(path))
        uses.update(
            _document_dependency_uses_in_tree(tree, relative_path=relative_path)
        )
    return frozenset(uses)


def _is_allowed_document_dependency_use(use: _DocumentDependencyUse) -> bool:
    return use.relative_path in ALLOWED_DOCUMENT_RENDERING_DEPENDENCY_PATHS or any(
        use.relative_path.startswith(prefix)
        for prefix in ALLOWED_DOCUMENT_RENDERING_DEPENDENCY_PREFIXES
    )


def _format_uses(uses: Iterable[_DocumentDependencyUse]) -> str:
    return "\n".join(
        f"- {use.relative_path}::{use.module}::{use.expression}" for use in sorted(uses)
    )


def test_document_rendering_dependencies_stay_in_rendering_leaves():
    unexpected = {
        use
        for use in _runtime_document_dependency_uses()
        if not _is_allowed_document_dependency_use(use)
    }

    assert unexpected == set(), (
        "Low-level DOCX/PDF/Markdown rendering dependencies belong in "
        "runtime/document_rendering or runtime/docx_template_runtime. "
        "Worker preflight may stay in celery_preflight.py. If this is a "
        "legitimate exception, add it to "
        "ALLOWED_DOCUMENT_RENDERING_DEPENDENCY_PATHS or "
        "ALLOWED_DOCUMENT_RENDERING_DEPENDENCY_PREFIXES with a narrow reason.\n"
        + _format_uses(unexpected)
    )


def test_document_dependency_import_scanner_reports_forbidden_runtime_import():
    tree = ast.parse(
        "from docx import Document\n\ndef render():\n    return Document()\n"
    )

    assert _DocumentDependencyUse(
        relative_path="executor.py",
        module="docx",
        expression="from docx import Document",
    ) in _document_dependency_uses_in_tree(tree, relative_path="executor.py")


def test_document_dependency_import_scanner_reports_builtin_import():
    tree = ast.parse("def render():\n    return __import__('weasyprint')\n")

    assert _DocumentDependencyUse(
        relative_path="executor.py",
        module="weasyprint",
        expression="__import__('weasyprint')",
    ) in _document_dependency_uses_in_tree(tree, relative_path="executor.py")
