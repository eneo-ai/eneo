"""Boundary contracts: AI Builder plugin-internal leaves have narrow import
allow-lists.

The Pattern Registry / Question Catalog / FCM layering is codified via
three boundary rules. Two different mechanisms are used based on where
the rule lives:

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
RULE_7_SECTION = "importlinter:contract:ai-builder-no-mcp-execution"

RULE_2_NAME = "FCM must not import AI Builder"
RULE_7_NAME = "AI Builder must not import MCP execution surfaces"

AI_BUILDER_PACKAGE = "intric.flows.ai_builder"
FCM_MODULE = "intric.flows.flow_capability_manifest"
FLOW_API_PARENT_PACKAGE = "intric.flows.api"
STALE_AI_BUILDER_REFERENCES: frozenset[str] = frozenset(
    {
        "ai_builder_materialization_bridge",
        "ai_builder_draft_plan",
        "DraftPlanEnvelope",
        "MaterializationError",
        "MaterializedDraft",
        "apply_to_draft",
    }
)
MCP_EXECUTION_MODULES: frozenset[str] = frozenset(
    {
        "intric.mcp_servers.infrastructure.proxy",
        "intric.mcp_servers.infrastructure.client",
        "intric.mcp_servers.application.mcp_server_service",
    }
)
FLOW_STEP_MCP_TOOLS_TABLE = "FlowStepMCPTools"
FLOW_STEP_MCP_TOOLS_TABLE_FILE = pathlib.Path("intric/database/tables/flow_tables.py")


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


def _modules_importing_flows_api(
    package_root: pathlib.Path,
) -> dict[str, list[str]]:
    """Return ``{relative_posix_path: [import_strings]}`` for ``.py`` files
    under ``package_root`` that pull in any ``intric.flows.api.*`` module
    by any import shape:

    - ``from intric.flows.api.<module> import X``
    - ``import intric.flows.api.<module>``
    - ``from intric.flows.api import <module>``   (parent-package form)
    - ``from intric.flows import api``            (grandparent form; then
      ``api.flow_models.X`` at the call site)

    The whole ``intric.flows.api`` surface is off-limits to AI Builder source:
    DTOs, assemblers, HTTP routers — none of them are legitimate dependencies
    of planner and proposal code.

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
                module = node.module or ""
                if module == FLOW_API_PARENT_PACKAGE:
                    for alias in node.names:
                        imports.append(f"from {module} import {alias.name}")
                elif module.startswith(f"{FLOW_API_PARENT_PACKAGE}."):
                    names = ", ".join(alias.name for alias in node.names)
                    imports.append(f"from {module} import {names}")
                elif module == "intric.flows":
                    for alias in node.names:
                        if alias.name == "api":
                            imports.append(f"from {module} import {alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if name == FLOW_API_PARENT_PACKAGE or name.startswith(
                        f"{FLOW_API_PARENT_PACKAGE}."
                    ):
                        imports.append(f"import {name}")
        if imports:
            rel = py_file.relative_to(package_root).as_posix()
            offenders[rel] = imports
    return offenders


def _stale_ai_builder_reference_offenders(
    roots: tuple[pathlib.Path, ...],
    *,
    ignored_files: frozenset[pathlib.Path],
) -> dict[str, list[str]]:
    """Use substring matches so stale names in comments/docstrings fail too."""
    offenders: dict[str, list[str]] = {}
    backend_root = _backend_root()
    ignored_resolved = {path.resolve() for path in ignored_files}
    for root in roots:
        for py_file in sorted(root.rglob("*.py")):
            if py_file.resolve() in ignored_resolved:
                continue
            text = py_file.read_text(encoding="utf-8")
            hits = sorted(
                reference
                for reference in STALE_AI_BUILDER_REFERENCES
                if reference in text
            )
            if hits:
                offenders[py_file.relative_to(backend_root).as_posix()] = hits
    return offenders


def _modules_importing_mcp_execution(
    package_root: pathlib.Path,
) -> dict[str, list[str]]:
    """Return AI Builder modules importing MCP execution surfaces directly.

    AI Builder planning may read MCP server/tool metadata. It must not import
    the MCP proxy/client runtime or the MCP management service that opens
    client sessions. This catches the direct import shapes a future edit might
    use while keeping read-only domain/presentation MCP shapes available.
    """
    offenders: dict[str, list[str]] = {}
    execution_parent_aliases: dict[str, frozenset[str]] = {
        "intric.mcp_servers.infrastructure": frozenset({"proxy", "client"}),
        "intric.mcp_servers.application": frozenset({"mcp_server_service"}),
    }
    for py_file in sorted(package_root.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if any(
                    module == forbidden or module.startswith(f"{forbidden}.")
                    for forbidden in MCP_EXECUTION_MODULES
                ):
                    names = ", ".join(alias.name for alias in node.names)
                    imports.append(f"from {module} import {names}")
                    continue
                allowed_aliases = execution_parent_aliases.get(module)
                if allowed_aliases is not None:
                    for alias in node.names:
                        if alias.name in allowed_aliases:
                            imports.append(f"from {module} import {alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if any(
                        name == forbidden or name.startswith(f"{forbidden}.")
                        for forbidden in MCP_EXECUTION_MODULES
                    ):
                        imports.append(f"import {name}")
        if imports:
            rel = py_file.relative_to(package_root).as_posix()
            offenders[rel] = imports
    return offenders


def _source_references_to_flow_step_mcp_tools(
    source_root: pathlib.Path,
) -> dict[str, list[str]]:
    """Return source references to the removed flow-step MCP join table."""
    offenders: dict[str, list[str]] = {}
    for py_file in sorted(source_root.rglob("*.py")):
        rel = py_file.relative_to(source_root).as_posix()
        if pathlib.Path(rel) == FLOW_STEP_MCP_TOOLS_TABLE_FILE:
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        references: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "intric.database.tables.flow_tables":
                    for alias in node.names:
                        if alias.name == FLOW_STEP_MCP_TOOLS_TABLE:
                            references.append(f"from {module} import {alias.name}")
            elif isinstance(node, ast.Name) and node.id == FLOW_STEP_MCP_TOOLS_TABLE:
                references.append(FLOW_STEP_MCP_TOOLS_TABLE)
            elif (
                isinstance(node, ast.Attribute)
                and node.attr == FLOW_STEP_MCP_TOOLS_TABLE
            ):
                references.append(FLOW_STEP_MCP_TOOLS_TABLE)
        if references:
            offenders[rel] = references
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


class TestDeprecatedFlowStepMcpToolsTable:
    """Flow step MCP access is assistant-owned, not stored on the old join."""

    def test_no_source_code_references_deprecated_flow_step_mcp_tools_table(
        self,
    ) -> None:
        offenders = _source_references_to_flow_step_mcp_tools(_backend_root() / "src")
        assert not offenders, (
            "`FlowStepMCPTools` was removed. Per-step MCP server/tool "
            "selection must stay on the flow-managed assistant via "
            "`assistant_mcp_servers` and `assistant_mcp_server_tools`.\n"
            f"Offenders: {offenders}"
        )


class TestRule7AiBuilderNoMcpExecutionContract:
    """Rule 7 — AI Builder planning can see MCP metadata, not execute tools."""

    def _package_root(self) -> pathlib.Path:
        return _backend_root() / "src" / "intric" / "flows" / "ai_builder"

    def test_section_exists(self) -> None:
        assert _config().has_section(RULE_7_SECTION), (
            f"Missing section [{RULE_7_SECTION}] in .importlinter"
        )

    def test_contract_name(self) -> None:
        assert _config().get(RULE_7_SECTION, "name") == RULE_7_NAME

    def test_contract_type_is_forbidden(self) -> None:
        assert _config().get(RULE_7_SECTION, "type") == "forbidden"

    def test_source_modules_is_exactly_ai_builder_package(self) -> None:
        assert _config_lines(_config(), RULE_7_SECTION, "source_modules") == {
            AI_BUILDER_PACKAGE,
        }

    def test_forbidden_modules_are_exactly_mcp_execution_surfaces(self) -> None:
        assert (
            _config_lines(_config(), RULE_7_SECTION, "forbidden_modules")
            == MCP_EXECUTION_MODULES
        )

    def test_no_ignore_imports_carveouts(self) -> None:
        assert _config_lines(_config(), RULE_7_SECTION, "ignore_imports") == set()

    def test_no_direct_imports_of_mcp_execution_surfaces(self) -> None:
        offenders = _modules_importing_mcp_execution(self._package_root())
        assert not offenders, (
            "AI Builder may consume MCP metadata but must not import MCP "
            "client/proxy execution surfaces. Tool execution belongs to "
            "published Flow runtime.\n"
            f"Offenders: {offenders}"
        )

    def test_helper_catches_all_offending_mcp_import_shapes(
        self, tmp_path: pathlib.Path
    ) -> None:
        shapes = {
            "proxy_from.py": (
                "from intric.mcp_servers.infrastructure.proxy import MCPProxySession\n"
            ),
            "client_from.py": (
                "from intric.mcp_servers.infrastructure.client import MCPClient\n"
            ),
            "service_from.py": (
                "from intric.mcp_servers.application.mcp_server_service "
                "import MCPServerService\n"
            ),
            "parent_proxy_from.py": (
                "from intric.mcp_servers.infrastructure import proxy\n"
            ),
            "parent_client_from.py": (
                "from intric.mcp_servers.infrastructure import client\n"
            ),
            "parent_service_from.py": (
                "from intric.mcp_servers.application import mcp_server_service\n"
            ),
            "bare_proxy_import.py": (
                "import intric.mcp_servers.infrastructure.proxy\n"
            ),
            "nested/deep_client_import.py": (
                "import intric.mcp_servers.infrastructure.client.mcp_client\n"
            ),
        }
        for rel_name, src in shapes.items():
            target = tmp_path / rel_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(src, encoding="utf-8")

        offenders = _modules_importing_mcp_execution(tmp_path)
        assert set(offenders) == set(shapes), (
            "MCP execution import helper missed at least one import shape.\n"
            f"Expected: {set(shapes)}\nGot: {set(offenders)}"
        )

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
        assert RULE_7_NAME in combined, (
            f"Contract '{RULE_7_NAME}' was not evaluated by lint-imports.\n"
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

    The permitted-sibling allow-list below is the full set; any new
    sibling import must extend it deliberately, not by accident.
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

    The carve-out is surgical because the slot-vocabulary leaf itself
    cannot sibling-import anything (its own AST-scan purity test enforces
    that), so depending on it does not leak the resolver's closure.
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


class TestRule6FlowApiBoundary:
    """Rule 6 — AI Builder source must not depend on Flow API adapters."""

    def _package_root(self) -> pathlib.Path:
        return _backend_root() / "src" / "intric" / "flows" / "ai_builder"

    def test_no_ai_builder_source_imports_flows_api(self) -> None:
        offenders = _modules_importing_flows_api(self._package_root())
        assert not offenders, (
            f"No AI Builder source module may import `{FLOW_API_PARENT_PACKAGE}`; "
            "HTTP/API DTOs and assemblers belong outside planner/proposal code.\n"
            f"Offenders: {offenders}"
        )

    def test_materialization_bridge_names_are_not_reintroduced(self) -> None:
        backend_root = _backend_root()
        roots = (
            backend_root / "src" / "intric" / "flows" / "ai_builder",
            backend_root / "tests" / "unittests" / "flows" / "ai_builder",
            backend_root / "tests" / "integration" / "flows" / "ai_builder",
        )
        offenders = _stale_ai_builder_reference_offenders(
            roots,
            ignored_files=frozenset({pathlib.Path(__file__)}),
        )
        assert not offenders, (
            "The retired materialization bridge names must not be reintroduced. "
            "Use compile_create_draft, compile_changeset, or AIBuilderRepository "
            f"directly.\nOffenders: {offenders}"
        )

    def test_helper_catches_all_offending_import_shapes(
        self, tmp_path: pathlib.Path
    ) -> None:
        """The ACL helper must catch every import shape that reaches any
        ``intric.flows.api.*`` module, including the parent-package form
        and non-`flow_models` leaves (e.g. `flow_assembler`). Without this
        fixture check, a silent helper regression would leave the
        production-tree ACL test passing because no offenders exist today
        — a green that would mask a future real offender.
        """
        shapes = {
            "qualified_from.py": "from intric.flows.api.flow_models import X\n",
            "parent_from.py": "from intric.flows.api import flow_models\n",
            "bare_import.py": "import intric.flows.api.flow_models\n",
            # Non-`flow_models` leaf under intric.flows.api — pins that the
            # ACL is a package guard, not a single-module guard. If a future
            # refactor narrows the helper back to flow_models only, this
            # fixture goes missing and the test fires.
            "assembler_from.py": ("from intric.flows.api.flow_assembler import X\n"),
            # Router leaf — pins that HTTP router imports are also off-limits.
            "router_from.py": ("from intric.flows.api.flow_router import router\n"),
            # Grandparent-package form — `from intric.flows import api` hands
            # the caller the whole subpackage as a module object; a later
            # attribute access (`api.flow_models.X`) would bypass the other
            # shapes. Mirrors the Rule 3/4 grandparent guard for
            # `from intric.flows import ai_builder`.
            "grandparent_from.py": "from intric.flows import api\n",
            # Nested offender also pins the recursive scan + relative-path
            # keying the helper uses. If this drops back to a flat glob, the
            # nested fixture goes missing and the test fires.
            "nested/deep_from.py": "from intric.flows.api.flow_models import Y\n",
        }
        for rel_name, src in shapes.items():
            target = tmp_path / rel_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(src, encoding="utf-8")
        offenders = _modules_importing_flows_api(tmp_path)
        assert set(offenders) == set(shapes), (
            "Helper missed at least one import shape.\n"
            f"Expected: {set(shapes)}\nGot: {set(offenders)}"
        )
