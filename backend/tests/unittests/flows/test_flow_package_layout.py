from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
FLOW_ROOT = BACKEND_ROOT / "src" / "eneo" / "flows"
FLOW_PACKAGE_ARTIFACT_ROOT = BACKEND_ROOT / "src" / "eneo" / "flow_packages" / "domain"

EXPECTED_ROOT_MODULES = 64
EXPECTED_ROOT_PACKAGES = 6


def _imported_modules(module_path: Path) -> set[str]:
    tree = ast.parse(module_path.read_text(), filename=str(module_path))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    package_parts = [
        "eneo",
        "flows",
        *module_path.relative_to(FLOW_ROOT).parent.parts,
    ]
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        if node.level == 0:
            imported_modules.add(node.module)
            continue

        parent_hops = node.level - 1
        imported_modules.add(
            ".".join((*package_parts[: len(package_parts) - parent_hops], node.module))
        )

    return imported_modules


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


def test_runtime_contracts_are_owned_by_domain_without_a_compatibility_module() -> None:
    assert (FLOW_ROOT / "domain" / "runtime.py").is_file()
    assert not (FLOW_ROOT / "runtime" / "models.py").exists()


def test_recovery_policy_is_owned_by_domain_without_a_compatibility_module() -> None:
    assert (FLOW_ROOT / "domain" / "flow_run_recovery_policy.py").is_file()
    assert not (FLOW_ROOT / "application" / "flow_run_recovery_policy.py").exists()


def test_run_contract_schemas_are_owned_by_api_without_a_compatibility_module() -> None:
    assert (FLOW_ROOT / "api" / "flow_run_contract_models.py").is_file()
    assert not (FLOW_ROOT / "flow_run_contract_models.py").exists()


def test_evidence_modules_are_owned_by_application_without_compatibility_modules() -> (
    None
):
    evidence_modules = (
        "flow_run_evidence.py",
        "flow_run_evidence_bundle.py",
        "flow_run_evidence_export_manifest.py",
        "flow_run_evidence_export_summary.py",
        "flow_run_export_json.py",
    )

    for module_name in evidence_modules:
        assert (FLOW_ROOT / "application" / module_name).is_file()
        assert not (FLOW_ROOT / module_name).exists()


def test_flow_domain_does_not_import_outer_flow_layers() -> None:
    forbidden_prefixes = (
        "eneo.flows.api",
        "eneo.flows.infrastructure",
        "eneo.flows.runtime",
    )
    violations: list[str] = []

    for module_path in sorted((FLOW_ROOT / "domain").rglob("*.py")):
        for imported_module in sorted(_imported_modules(module_path)):
            if imported_module.startswith(forbidden_prefixes):
                violations.append(
                    f"{module_path.relative_to(FLOW_ROOT)}: {imported_module}"
                )

    assert not violations, "Flow domain imports outer layers: " + ", ".join(violations)


def test_portable_package_artifact_modules_do_not_depend_on_flow_verticals() -> None:
    artifact_modules = (
        "flow_package_checksum.py",
        "flow_package_errors.py",
        "flow_package_limits.py",
        "flow_package_manifest.py",
        "flow_package_provenance.py",
    )
    forbidden_prefixes = (
        "eneo.apps",
        "eneo.assistants",
        "eneo.flow_packages.api",
        "eneo.flow_packages.application",
        "eneo.flow_packages.infrastructure",
        "eneo.flows",
    )

    violations: list[str] = []
    for module_name in artifact_modules:
        module_path = FLOW_PACKAGE_ARTIFACT_ROOT / module_name
        tree = ast.parse(module_path.read_text(), filename=str(module_path))
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_modules.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        for imported_module in sorted(imported_modules):
            if imported_module.startswith(forbidden_prefixes):
                violations.append(f"{module_name}: {imported_module}")

    assert not violations, (
        "Portable package artifact mechanics must remain dependency-clean until "
        "a second concrete package vertical earns extraction: " + ", ".join(violations)
    )


def test_flow_root_layout_ratchet() -> None:
    root_modules = {
        path.stem for path in FLOW_ROOT.glob("*.py") if path.name != "__init__.py"
    }
    root_packages = {
        path.name for path in FLOW_ROOT.iterdir() if (path / "__init__.py").is_file()
    }

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
