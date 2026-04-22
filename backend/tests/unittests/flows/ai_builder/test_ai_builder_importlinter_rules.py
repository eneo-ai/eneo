"""Boundary contracts: AI Builder plugin-internal leaves have narrow import
allow-lists.

Phase A of the architecture rewrite codifies the Pattern Registry / Question
Catalog / FCM layering with three boundary rules. Two different mechanisms
are used based on where the rule lives:

- **Rule 2 (importlinter)** — the Flow Capability Manifest is engine truth
  and lives outside the plugin namespace, so a dedicated
  ``.importlinter`` forbidden-contract (`fcm-no-ai-builder`) expresses the
  rule cleanly: source (``intric.flows.flow_capability_manifest``) is a
  sibling of the forbidden parent package (``intric.flows.ai_builder``).
  The dedicated contract is belt-and-suspenders with the broader
  ``flows-engine-no-ai-builder`` contract and gives an FCM-specific
  failure message.
- **Rules 3 & 4 (AST-scan)** — Pattern Registry and Question Catalog
  *live inside* ``intric.flows.ai_builder``, so an importlinter
  ``forbidden`` contract with ``forbidden_modules =
  intric.flows.ai_builder`` rejects them with "Modules have shared
  descendants" (source is a descendant of forbidden). Enumerating every
  sibling in ``forbidden_modules`` would be brittle (80+ entries, one
  config change per new sibling). Instead we use the same AST-scan
  mechanism that pins the ``ai_builder_slot_vocabulary`` leaf — fail at
  pytest speed on any *direct* sibling import. Transitive purity is
  enforced by chaining: each node's scan keeps its direct-import surface
  narrow, so depending on a scanned module cannot drag in the resolver's
  closure.

Both mechanisms run in CI (importlinter via
``flows-engine-no-ai-builder`` already, now the FCM rule too; AST tests
via pytest). The chosen asymmetry reflects importlinter's structural
constraint, not a weakening of the architectural intent.
"""

from __future__ import annotations

import ast
import configparser
import pathlib
import subprocess
from pathlib import Path

RULE_2_SECTION = "importlinter:contract:fcm-no-ai-builder"

RULE_2_NAME = "FCM must not import AI Builder"

AI_BUILDER_PACKAGE = "intric.flows.ai_builder"
FCM_MODULE = "intric.flows.flow_capability_manifest"
FLOW_MODELS_API_MODULE = "intric.flows.api.flow_models"
FLOW_API_PARENT_PACKAGE = "intric.flows.api"
FLOW_MODELS_API_MODULE_LEAF = "flow_models"
BRIDGE_MODULE_NAME = "ai_builder_materialization_bridge"


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _config() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(_backend_root() / ".importlinter", encoding="utf-8")
    return parser


def _config_lines(
    parser: configparser.ConfigParser, section: str, key: str
) -> set[str]:
    raw = parser.get(section, key, fallback="")
    return {line.strip() for line in raw.splitlines() if line.strip()}


def _plugin_sibling_imports(
    module_path: pathlib.Path, permitted: frozenset[str]
) -> list[str]:
    """Return static ``intric.flows.ai_builder.*`` sibling imports from
    ``module_path`` that are not in ``permitted``. Relative imports and
    package-form imports (``from intric.flows import ai_builder``) are
    always treated as offences — no architecture lets them in.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level != 0:
                offenders.append(
                    f"relative import (level={node.level}) of '{node.module or ''}'"
                )
                continue
            module = node.module or ""
            if module == AI_BUILDER_PACKAGE:
                for alias in node.names:
                    qualified = f"{AI_BUILDER_PACKAGE}.{alias.name}"
                    if qualified not in permitted:
                        offenders.append(f"from {module} import {alias.name}")
                continue
            if module.startswith(f"{AI_BUILDER_PACKAGE}."):
                if module not in permitted:
                    names = ", ".join(alias.name for alias in node.names)
                    offenders.append(f"from {module} import {names}")
                continue
            if module == "intric.flows":
                for alias in node.names:
                    if alias.name == "ai_builder":
                        offenders.append(f"from intric.flows import {alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == AI_BUILDER_PACKAGE or name.startswith(
                    f"{AI_BUILDER_PACKAGE}."
                ):
                    if name not in permitted:
                        offenders.append(f"import {name}")

    return offenders


def _modules_importing_flow_models_api(
    package_root: pathlib.Path,
) -> dict[str, list[str]]:
    """Return ``{relative_posix_path: [import_strings]}`` for ``.py`` files
    under ``package_root`` that pull in ``intric.flows.api.flow_models`` by
    any import shape:

    - ``from intric.flows.api.flow_models import X``
    - ``import intric.flows.api.flow_models``
    - ``from intric.flows.api import flow_models``  (parent-package form)

    Recurses through sub-packages so Rule 6 stays honest if the ai_builder
    package grows nested modules. Skips every ``__init__.py``.
    """
    offenders: dict[str, list[str]] = {}
    for py_file in sorted(package_root.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == FLOW_MODELS_API_MODULE:
                    names = ", ".join(alias.name for alias in node.names)
                    imports.append(f"from {node.module} import {names}")
                elif node.module == FLOW_API_PARENT_PACKAGE:
                    for alias in node.names:
                        if alias.name == FLOW_MODELS_API_MODULE_LEAF:
                            imports.append(f"from {node.module} import {alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == FLOW_MODELS_API_MODULE:
                        imports.append(f"import {alias.name}")
        if imports:
            rel = py_file.relative_to(package_root).as_posix()
            offenders[rel] = imports
    return offenders


class TestRule2FcmNoAiBuilderContract:
    """Rule 2 — importlinter contract pins FCM's engine-truth boundary."""

    def test_section_exists(self) -> None:
        assert _config().has_section(RULE_2_SECTION), (
            f"Missing section [{RULE_2_SECTION}] in .importlinter"
        )

    def test_contract_name(self) -> None:
        assert _config().get(RULE_2_SECTION, "name") == RULE_2_NAME

    def test_contract_type_is_forbidden(self) -> None:
        assert _config().get(RULE_2_SECTION, "type") == "forbidden"

    def test_source_modules_is_exactly_fcm(self) -> None:
        assert _config_lines(_config(), RULE_2_SECTION, "source_modules") == {
            FCM_MODULE,
        }

    def test_forbidden_modules_is_exactly_ai_builder_package(self) -> None:
        assert _config_lines(_config(), RULE_2_SECTION, "forbidden_modules") == {
            AI_BUILDER_PACKAGE,
        }

    def test_no_ignore_imports_carveouts(self) -> None:
        assert _config_lines(_config(), RULE_2_SECTION, "ignore_imports") == set()

    def test_lint_imports_keeps_the_contract(self) -> None:
        result = subprocess.run(
            ["uv", "run", "lint-imports", "--no-cache"],
            cwd=_backend_root(),
            capture_output=True,
            text=True,
            check=False,
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0, (
            f"lint-imports failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert RULE_2_NAME in combined, (
            f"Contract '{RULE_2_NAME}' was not evaluated by lint-imports.\n"
            f"Combined output:\n{combined}"
        )
        assert "0 broken" in combined, (
            "lint-imports exited 0 but did not report '0 broken' — either a "
            "contract regressed or output shape changed.\n"
            f"Combined output:\n{combined}"
        )


class TestRule3PatternRegistryDirectSiblingImports:
    """Rule 3 — Pattern Registry may only import, from sibling modules
    under ``intric.flows.ai_builder``, the Question Catalog and the slot
    vocabulary. FCM lives outside the plugin package and is not considered
    a sibling here (it is a separate allow-list concern — the FCM is
    always importable by anything inside ``intric.flows``).

    In A.5b the Pattern Registry imports nothing from siblings. The rule
    is pre-positioned so that when A.6 wires Pattern Registry to consume
    Question Catalog + slot vocabulary, the permitted-sibling set below
    is extended in the same slice and nothing else slips through.
    """

    _PERMITTED_SIBLINGS: frozenset[str] = frozenset(
        {
            f"{AI_BUILDER_PACKAGE}.question_catalog",
            f"{AI_BUILDER_PACKAGE}.ai_builder_slot_vocabulary",
        }
    )

    def _module_path(self) -> pathlib.Path:
        return (
            _backend_root()
            / "src"
            / "intric"
            / "flows"
            / "ai_builder"
            / "pattern_registry.py"
        )

    def test_no_disallowed_sibling_imports(self) -> None:
        offenders = _plugin_sibling_imports(
            self._module_path(), self._PERMITTED_SIBLINGS
        )
        assert not offenders, (
            "pattern_registry.py may only import 'question_catalog' or "
            "'ai_builder_slot_vocabulary' from the ai_builder plugin. "
            "FCM imports (intric.flows.flow_capability_manifest) live "
            "outside the plugin and are unaffected by this rule.\n"
            f"Offending imports: {offenders}"
        )


class TestRule4QuestionCatalogDirectSiblingImports:
    """Rule 4 — Question Catalog is a plugin-layer leaf. Its only allowed
    sibling is ``ai_builder_slot_vocabulary``, a stdlib-only taxonomy
    module. FCM imports (outside the plugin package) remain available.

    The plan text for Rule 4 was restated at A.5b from "FCM only" to
    "FCM + slot vocabulary"; the carve-out is surgical because the
    slot-vocabulary leaf itself cannot sibling-import anything (its own
    AST-scan purity test enforces that), so depending on it does not
    leak the resolver's closure.
    """

    _PERMITTED_SIBLINGS: frozenset[str] = frozenset(
        {
            f"{AI_BUILDER_PACKAGE}.ai_builder_slot_vocabulary",
        }
    )

    def _module_path(self) -> pathlib.Path:
        return (
            _backend_root()
            / "src"
            / "intric"
            / "flows"
            / "ai_builder"
            / "question_catalog.py"
        )

    def test_only_slot_vocabulary_is_imported_from_siblings(self) -> None:
        offenders = _plugin_sibling_imports(
            self._module_path(), self._PERMITTED_SIBLINGS
        )
        assert not offenders, (
            "question_catalog.py may only import "
            "'ai_builder_slot_vocabulary' from the ai_builder plugin. "
            "FCM imports (intric.flows.flow_capability_manifest) live "
            "outside the plugin and are unaffected by this rule.\n"
            f"Offending imports: {offenders}"
        )


class TestRule6MaterializationBridgeAcl:
    """Rule 6 — Materialization Bridge ACL.

    Inside ``intric.flows.ai_builder``, only
    ``ai_builder_materialization_bridge.py`` is permitted to import from
    ``intric.flows.api.flow_models`` (the flows-domain draft-write
    surface). The bridge is a docstring-only scaffold in A.5; concrete
    implementation lands in Phase D.7.
    """

    def _package_root(self) -> pathlib.Path:
        return _backend_root() / "src" / "intric" / "flows" / "ai_builder"

    def test_bridge_is_docstring_only_scaffold(self) -> None:
        """A.5 Rule 6 wants the bridge scaffolded as an empty module with a
        role-docstring; concrete implementation lands in Phase D.7. Assert
        both: the file exists, and its top-level body is the module
        docstring and nothing else.
        """
        bridge = self._package_root() / f"{BRIDGE_MODULE_NAME}.py"
        assert bridge.exists(), (
            "Expected Materialization Bridge scaffold at "
            f"{bridge.relative_to(_backend_root())}."
        )
        tree = ast.parse(bridge.read_text(encoding="utf-8"))
        assert ast.get_docstring(tree) is not None, (
            f"{BRIDGE_MODULE_NAME}.py must have a module docstring declaring "
            "its bridge role."
        )
        body = tree.body
        assert len(body) == 1 and isinstance(body[0], ast.Expr), (
            f"{BRIDGE_MODULE_NAME}.py is the A.5 scaffold — keep it "
            "docstring-only. Concrete bridge logic lands in Phase D.7; "
            "adding code here now widens the write-surface seam before "
            "the ACL is ready to guard it.\n"
            f"Found {len(body)} top-level statements: "
            f"{[type(n).__name__ for n in body]}"
        )

    def test_only_bridge_imports_flows_api_flow_models(self) -> None:
        offenders = _modules_importing_flow_models_api(self._package_root())
        offenders.pop(f"{BRIDGE_MODULE_NAME}.py", None)
        assert not offenders, (
            "Only `ai_builder_materialization_bridge.py` may import from "
            f"`{FLOW_MODELS_API_MODULE}` inside the ai_builder plugin. "
            "All other modules must route draft-write type usage through "
            "the bridge (Rule 6 of Phase A.5; concrete bridge implementation "
            "lands in Phase D.7).\n"
            f"Offenders: {offenders}"
        )

    def test_helper_catches_all_offending_import_shapes(
        self, tmp_path: pathlib.Path
    ) -> None:
        """The ACL helper must catch every import shape that reaches
        ``intric.flows.api.flow_models``, including the parent-package
        form. Without this fixture check, a silent helper regression would
        leave the production-tree ACL test passing because no offenders
        exist today — a green that would mask a future real offender.
        """
        shapes = {
            "qualified_from.py": "from intric.flows.api.flow_models import X\n",
            "parent_from.py": "from intric.flows.api import flow_models\n",
            "bare_import.py": "import intric.flows.api.flow_models\n",
            # Nested offender also pins the recursive scan + relative-path
            # keying the helper uses. If this drops back to a flat glob, the
            # nested fixture goes missing and the test fires.
            "nested/deep_from.py": "from intric.flows.api.flow_models import Y\n",
        }
        for rel_name, src in shapes.items():
            target = tmp_path / rel_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(src, encoding="utf-8")
        offenders = _modules_importing_flow_models_api(tmp_path)
        assert set(offenders) == set(shapes), (
            "Helper missed at least one import shape.\n"
            f"Expected: {set(shapes)}\nGot: {set(offenders)}"
        )
