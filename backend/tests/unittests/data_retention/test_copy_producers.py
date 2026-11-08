"""Every feature that stores copies registers the copy's sources."""

import ast
from importlib.util import find_spec
from pathlib import Path

from eneo.data_retention import derivations
from eneo.data_retention.derivations import KNOWN_COPY_PRODUCERS

SOURCE_ROOT = Path(derivations.__file__).resolve().parents[1]
FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def _registers(function: FunctionNode) -> bool:
    return any(
        isinstance(node, ast.Call)
        and "register_derivations"
        in (getattr(node.func, "id", None), getattr(node.func, "attr", None))
        for node in ast.walk(function)
    )


def _functions(tree: ast.AST) -> list[FunctionNode]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _module_path(module: str) -> Path:
    spec = find_spec(module)
    assert spec is not None and spec.origin is not None, module
    return Path(spec.origin)


def test_each_known_producer_registers_its_sources():
    """Mutant: a listed producer stops calling register_derivations."""
    for producer in KNOWN_COPY_PRODUCERS:
        module, name = producer.split(":")
        tree = ast.parse(_module_path(module).read_text())
        matches = [node for node in _functions(tree) if node.name == name]
        assert matches, f"{producer} does not exist"
        assert all(_registers(node) for node in matches), (
            f"{producer} returns copied content without registering its sources"
        )


def test_every_registering_function_is_a_known_producer():
    """Mutant: a new producer registers edges but is not listed, so the check
    above would never notice it dropping the call."""
    listed = set(KNOWN_COPY_PRODUCERS)
    port = Path(derivations.__file__).resolve()
    for path in SOURCE_ROOT.rglob("*.py"):
        if path.resolve() == port:
            continue
        source = path.read_text()
        if "register_derivations" not in source:
            continue
        module = ".".join(
            ("eneo", *path.relative_to(SOURCE_ROOT).with_suffix("").parts)
        ).removesuffix(".__init__")
        for function in _functions(ast.parse(source)):
            if _registers(function):
                assert f"{module}:{function.name}" in listed, (
                    f"{module}:{function.name} registers copies; list it in "
                    "KNOWN_COPY_PRODUCERS"
                )


def test_the_check_tells_a_registering_producer_from_one_that_does_not():
    """Mutant: the detector accepts any function, so both checks pass vacuously."""
    tree = ast.parse(
        "async def copies(session):\n"
        "    await register_derivations(copy_session_id=s,"
        " source_question_ids=q)\n"
        "    return content\n"
        "async def leaks(session):\n"
        "    return content\n"
        "async def by_module(session):\n"
        "    await derivations.register_derivations("
        " copy_session_id=s, source_question_ids=q)\n"
    )
    found = {node.name: _registers(node) for node in _functions(tree)}
    assert found == {"copies": True, "leaks": False, "by_module": True}
