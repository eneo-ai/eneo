from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Protocol, cast

BACKEND_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = BACKEND_ROOT.parent
FLOW_ROOT = BACKEND_ROOT / "src" / "intric" / "flows"
PACKAGE_LAYOUT_DOC = REPO_ROOT / "docs" / "flows" / "package-layout.md"
FLOW_DEVELOPER_ARCHITECTURE_DOCS_GENERATOR = (
    BACKEND_ROOT / "scripts" / "flow_developer_architecture_docs.py"
)

EXPECTED_ROOT_MODULES = 72
EXPECTED_ROOT_PACKAGES = 7


class _LayoutRow(Protocol):
    entry: str
    kind: str
    target_home: str


class _FlowDeveloperArchitectureDocsGenerator(Protocol):
    ALLOWED_LAYOUT_KINDS: frozenset[str]
    ALLOWED_TARGET_HOMES: frozenset[str]

    def parse_package_layout_decision_table(
        self,
        package_layout_doc: Path = ...,
    ) -> dict[tuple[str, str], _LayoutRow]: ...

    def discover_flow_root_layout_entries(
        self,
        flow_root: Path = ...,
    ) -> set[tuple[str, str]]: ...


def _load_flow_developer_architecture_docs_generator() -> (
    _FlowDeveloperArchitectureDocsGenerator
):
    spec = importlib.util.spec_from_file_location(
        "flow_developer_architecture_docs",
        FLOW_DEVELOPER_ARCHITECTURE_DOCS_GENERATOR,
    )
    assert spec is not None and spec.loader is not None, (
        f"Could not load generator module from "
        f"{FLOW_DEVELOPER_ARCHITECTURE_DOCS_GENERATOR}"
    )

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast(_FlowDeveloperArchitectureDocsGenerator, module)


_LAYOUT_DOCS = _load_flow_developer_architecture_docs_generator()


def _format_layout_entries(entries: set[tuple[str, str]]) -> str:
    return ", ".join(f"{entry} ({kind})" for entry, kind in sorted(entries))


def test_ddd_flow_modules_are_no_longer_compatibility_stubs() -> None:
    targets = [
        FLOW_ROOT / "application" / "flow_service.py",
        FLOW_ROOT / "application" / "flow_run_service.py",
        FLOW_ROOT / "application" / "flow_dispatch.py",
        FLOW_ROOT / "infrastructure" / "flow_repo.py",
        FLOW_ROOT / "infrastructure" / "flow_run_repo.py",
        FLOW_ROOT / "infrastructure" / "flow_version_repo.py",
        FLOW_ROOT / "domain" / "flow.py",
    ]

    for path in targets:
        text = path.read_text()
        assert "Compatibility re-export" not in text, path.name


def test_flow_root_layout_decision_matches_filesystem() -> None:
    documented_entries = set(
        _LAYOUT_DOCS.parse_package_layout_decision_table(PACKAGE_LAYOUT_DOC)
    )
    filesystem_entries = _LAYOUT_DOCS.discover_flow_root_layout_entries(FLOW_ROOT)

    missing_from_doc = filesystem_entries - documented_entries
    stale_doc_entries = documented_entries - filesystem_entries

    assert not missing_from_doc, (
        f"{PACKAGE_LAYOUT_DOC} must list root Flow entries: "
        f"{_format_layout_entries(missing_from_doc)}"
    )
    assert not stale_doc_entries, (
        f"{PACKAGE_LAYOUT_DOC} lists removed Flow entries: "
        f"{_format_layout_entries(stale_doc_entries)}"
    )

    root_modules = {entry for entry, kind in filesystem_entries if kind == "module"}
    root_packages = {entry for entry, kind in filesystem_entries if kind == "package"}

    assert len(root_modules) == EXPECTED_ROOT_MODULES, (
        "Root-level Flow modules are frozen. Move new code into an existing "
        "package, and update the ratchet when root modules shrink. "
        f"Current count: {len(root_modules)}; expected: {EXPECTED_ROOT_MODULES}."
    )
    assert len(root_packages) == EXPECTED_ROOT_PACKAGES, (
        "Root-level Flow packages are frozen. Reuse an existing package or "
        "update the ratchet with an architecture decision. "
        f"Current count: {len(root_packages)}; expected: {EXPECTED_ROOT_PACKAGES}."
    )
