"""Every feature that stores copies registers the copy's sources."""

import ast
import re
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


_EDGE_TABLE = "ContentDerivations"
_RAW_EDGE_WRITE = re.compile(
    r"(?i:delete\s+from|update|truncate(?:\s+table)?)\s+content_derivations\b"
)


def _edge_uses(function: FunctionNode) -> set[str]:
    """What this function does with the edges table itself rather than with its
    columns: the statement or call it passes the table to, or "construct" for
    a new ORM instance. A column read such as ``ContentDerivations.id`` is no
    use; an ORM load or instance is, since it could change an edge unseen."""
    uses: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == _EDGE_TABLE:
            uses.add("construct")
        elif any(
            isinstance(argument, ast.Name) and argument.id == _EDGE_TABLE
            for argument in node.args
        ):
            uses.add(
                str(
                    getattr(node.func, "id", None) or getattr(node.func, "attr", "")
                ).lower()
            )
    return uses


def test_edges_are_only_added_and_only_removed_with_their_session():
    """Mutant: a path deletes or changes an edge of an existing copy. A copy
    found invalid must stay invalid, because the derived copies task removes
    its questions without reading the edges again."""
    uses: dict[str, set[str]] = {}
    for path in SOURCE_ROOT.rglob("*.py"):
        source = path.read_text()
        assert not _RAW_EDGE_WRITE.search(source), f"{path} writes edges in SQL"
        if _EDGE_TABLE not in source:
            continue
        module = ".".join(
            ("eneo", *path.relative_to(SOURCE_ROOT).with_suffix("").parts)
        )
        for function in _functions(ast.parse(source)):
            if found := _edge_uses(function):
                uses[f"{module}:{function.name}"] = found

    assert uses == {
        "eneo.data_retention.derivations:register_derivations": {"insert"},
        "eneo.data_retention.infrastructure.derived_copy_repo:"
        "delete_edges_of_removed_sessions": {"delete"},
    }


def test_the_edge_check_sees_each_kind_of_use():
    """Mutant: the detector misses a use, so the check above passes vacuously."""
    tree = ast.parse(
        "def add():\n    insert(ContentDerivations).values(x)\n"
        "def change():\n    sa.Update(ContentDerivations).values(x)\n"
        "def remove():\n    sa.delete(ContentDerivations).where(x)\n"
        "def load():\n    session.get(ContentDerivations, x)\n"
        "def make():\n    session.add(ContentDerivations(copy_session_id=x))\n"
        "def columns():\n    sa.select(ContentDerivations.id)\n"
        "def other():\n    sa.delete(Questions).where(x)\n"
    )
    found = {node.name: _edge_uses(node) for node in _functions(tree)}
    assert found == {
        "add": {"insert"},
        "change": {"update"},
        "remove": {"delete"},
        "load": {"get"},
        "make": {"construct"},
        "columns": set(),
        "other": set(),
    }
    assert _RAW_EDGE_WRITE.search("DELETE FROM content_derivations WHERE x")
    assert not _RAW_EDGE_WRITE.search("uq_content_derivations_copy_source")
