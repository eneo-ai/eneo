from __future__ import annotations

import ast
import importlib.util
import json
import re
import types
from pathlib import Path

import pytest

from eneo.flow_packages.domain.flow_package_errors import FlowPackageErrorCode
from eneo.flows.flow_api_error_code import (
    FLOW_API_ERROR_CODES,
    FLOW_RUN_TERMINAL_ERROR_CODES,
    FLOW_TYPED_IO_ERROR_CODES,
    FlowApiErrorCode,
)

BACKEND_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = BACKEND_ROOT.parent
GENERATOR_PATH = BACKEND_ROOT / "scripts" / "generate_flow_api_error_codes_ts.py"
SDK_ERROR_CODES_JS = (
    REPO_ROOT
    / "frontend"
    / "packages"
    / "eneo-js"
    / "src"
    / "flows"
    / "flow-api-error-codes.js"
)
SDK_ERROR_CODES_DTS = SDK_ERROR_CODES_JS.with_suffix(".d.ts")
WEB_MESSAGES_DIR = REPO_ROOT / "frontend" / "apps" / "web" / "messages"
FLOW_SOURCE_ROOT = BACKEND_ROOT / "src" / "eneo" / "flows"
FLOW_API_SOURCE_ROOT = FLOW_SOURCE_ROOT / "api"
CATALOG_MODULE_PATH = FLOW_SOURCE_ROOT / "flow_api_error_code.py"
DOCS_FLOW_API_GUIDE = (
    REPO_ROOT
    / "frontend"
    / "apps"
    / "docs-site"
    / "src"
    / "content"
    / "guides"
    / "flows-api-guide.mdx"
)
FLOW_ERROR_CODE_PATTERN = re.compile(r"^flow_[a-z0-9_]+$")
FLOW_GUIDE_BACKTICKED_TOKEN_PATTERN = re.compile(r"`((?:flow|typed_io)_[a-z0-9_]+)`")
FLOW_GUIDE_NON_ERROR_CODE_TOKENS = {
    "flow_evidence": "resource permission name, not an error code",
    "flow_run_history_minimum_retention_days": (
        "retention policy field, not an error code"
    ),
    "flow_run_history_no_purge": "retention policy field, not an error code",
    "flow_run_history_retention_days": "retention policy field, not an error code",
    "flow_runtime_upload_abandonment_days": (
        "runtime upload retention field, not an error code"
    ),
    "flow_version": "published run version field, not an error code",
}
PUBLIC_FLOW_ERROR_EMITTER_PATHS = (
    FLOW_SOURCE_ROOT / "flow_access_policy.py",
    FLOW_SOURCE_ROOT / "flow_run_input_payload.py",
    FLOW_SOURCE_ROOT / "flow_run_step_inputs.py",
    FLOW_SOURCE_ROOT / "flow_run_payload_validation.py",
    FLOW_SOURCE_ROOT / "flow_runtime_file_service.py",
    FLOW_SOURCE_ROOT / "variable_resolver.py",
    FLOW_SOURCE_ROOT / "application" / "flow_run_service.py",
    FLOW_SOURCE_ROOT / "application" / "flow_run_rerun_service.py",
    FLOW_SOURCE_ROOT / "application" / "flow_run_review_checkpoint_service.py",
    FLOW_SOURCE_ROOT / "infrastructure" / "flow_run_repo.py",
)
TERMINAL_RUN_ERROR_CODE_CALL_KEYWORDS = {
    "close_active_rerun_operations_for_terminal_run": {"error_code"},
    "close_open_step_attempts_for_terminal_run": {"error_code"},
}
DOCUMENTED_DYNAMIC_TERMINAL_RUN_ERROR_CODE_PRODUCERS = {
    (
        "src/eneo/flows/application/flow_run_terminalization.py",
        "close_open_step_attempts_for_terminal_run",
        "error_code",
        "effective_error_code",
    ),
    (
        "src/eneo/flows/application/flow_run_terminalization.py",
        "close_active_rerun_operations_for_terminal_run",
        "error_code",
        "effective_error_code",
    ),
}


def _load_generator_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generate_flow_api_error_codes_ts", GENERATOR_PATH
    )
    if spec is None or spec.loader is None:
        pytest.fail(f"Could not load generator module from {GENERATOR_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _flow_error_message_keys(locale: str) -> set[str]:
    messages = json.loads((WEB_MESSAGES_DIR / f"{locale}.json").read_text())
    return {key for key in messages if key.startswith("flow_error_")}


def test_flow_api_error_code_values_are_unique_and_ordered() -> None:
    enum_values = tuple(FlowApiErrorCode)

    assert FLOW_API_ERROR_CODES == enum_values
    assert len(FLOW_API_ERROR_CODES) == len(set(FLOW_API_ERROR_CODES))


def test_flow_run_terminal_error_codes_are_public_error_codes() -> None:
    assert FLOW_RUN_TERMINAL_ERROR_CODES <= set(FLOW_API_ERROR_CODES)


def test_flow_typed_io_error_codes_are_public_error_codes() -> None:
    assert FLOW_TYPED_IO_ERROR_CODES <= set(FLOW_API_ERROR_CODES)


def test_flow_typed_io_exception_literal_codes_are_cataloged() -> None:
    literal_codes: dict[str, list[str]] = {}

    for path, tree in _flow_module_trees().items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node.func) != "TypedIOValidationException":
                continue
            for keyword in node.keywords:
                if keyword.arg != "code":
                    continue
                if not isinstance(keyword.value, ast.Constant):
                    continue
                if not isinstance(keyword.value.value, str):
                    continue
                literal_codes.setdefault(keyword.value.value, []).append(
                    f"{path.relative_to(BACKEND_ROOT)}:{keyword.value.lineno}"
                )

    typed_io_codes = {code.value for code in FLOW_TYPED_IO_ERROR_CODES}
    missing_codes = {
        code: locations
        for code, locations in sorted(literal_codes.items())
        if code not in typed_io_codes
    }

    assert missing_codes == {}


@pytest.mark.parametrize("locale", ["en", "sv"])
def test_flow_api_error_codes_match_localized_messages(locale: str) -> None:
    expected_keys = {f"flow_error_{code.value}" for code in FLOW_API_ERROR_CODES}

    assert _flow_error_message_keys(locale) == expected_keys


def test_flow_producer_code_uses_catalog_for_localized_error_codes() -> None:
    catalog_codes = {code.value for code in FLOW_API_ERROR_CODES}
    raw_cataloged_codes: list[str] = []

    for path in FLOW_SOURCE_ROOT.rglob("*.py"):
        if path == CATALOG_MODULE_PATH:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg not in {"code", "error_code"}:
                    continue
                if not isinstance(keyword.value, ast.Constant):
                    continue
                if not isinstance(keyword.value.value, str):
                    continue
                if keyword.value.value not in catalog_codes:
                    continue
                raw_cataloged_codes.append(
                    f"{path.relative_to(BACKEND_ROOT)}:{keyword.value.lineno} "
                    f"{keyword.arg}={keyword.value.value!r}"
                )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values, strict=True):
                if not isinstance(key, ast.Constant) or key.value != "code":
                    continue
                if not isinstance(value, ast.Constant):
                    continue
                if not isinstance(value.value, str):
                    continue
                if value.value not in catalog_codes:
                    continue
                raw_cataloged_codes.append(
                    f"{path.relative_to(BACKEND_ROOT)}:{value.lineno} "
                    f"'code': {value.value!r}"
                )
    assert raw_cataloged_codes == []


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _assignment_string_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Assign):
        value = node.value
    elif isinstance(node, ast.AnnAssign):
        value = node.value
    else:
        return None
    if not isinstance(value, ast.Constant):
        return None
    if not isinstance(value.value, str):
        return None
    return value.value


def _module_name_for_path(path: Path) -> str:
    relative = path.relative_to(BACKEND_ROOT / "src").with_suffix("")
    return ".".join(relative.parts)


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    constants: dict[str, str] = {}
    for node in tree.body:
        value = _assignment_string_value(node)
        if value is None:
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = value
            continue
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            constants[node.target.id] = value
    return constants


def _flow_module_trees() -> dict[Path, ast.Module]:
    return {
        path: ast.parse(path.read_text(), filename=str(path))
        for path in FLOW_SOURCE_ROOT.rglob("*.py")
    }


def _flow_module_constants_by_name(
    module_trees: dict[Path, ast.Module],
) -> dict[str, dict[str, str]]:
    return {
        _module_name_for_path(path): _module_string_constants(tree)
        for path, tree in module_trees.items()
    }


def _visible_string_constants(
    *,
    tree: ast.Module,
    path: Path,
    constants_by_module: dict[str, dict[str, str]],
) -> dict[str, str]:
    constants = dict(constants_by_module.get(_module_name_for_path(path), {}))
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level != 0 or node.module is None:
            continue
        imported_constants = constants_by_module.get(node.module)
        if imported_constants is None:
            continue
        for alias in node.names:
            if alias.name not in imported_constants:
                continue
            constants[alias.asname or alias.name] = imported_constants[alias.name]
    return constants


def _flow_api_error_code_value_expr(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "value"
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "FlowApiErrorCode"
    )


def _static_string_code_value(
    node: ast.AST,
    *,
    constants: dict[str, str],
) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _terminal_code_keywords(
    node: ast.Call,
) -> tuple[str, set[str]] | None:
    call_name = _call_name(node.func)
    if call_name is None:
        return None
    keyword_names = TERMINAL_RUN_ERROR_CODE_CALL_KEYWORDS.get(call_name)
    if keyword_names is None:
        return None
    return call_name, keyword_names


def test_flow_api_error_response_literal_codes_are_cataloged() -> None:
    catalog_codes = {code.value for code in FLOW_API_ERROR_CODES}
    uncataloged_codes: list[str] = []

    for path in FLOW_API_SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node.func) != "error_response":
                continue
            for keyword in node.keywords:
                if keyword.arg != "code":
                    continue
                if not isinstance(keyword.value, ast.Constant):
                    continue
                if not isinstance(keyword.value.value, str):
                    continue
                code = keyword.value.value
                if (
                    FLOW_ERROR_CODE_PATTERN.fullmatch(code)
                    and code not in catalog_codes
                ):
                    uncataloged_codes.append(
                        f"{path.relative_to(BACKEND_ROOT)}:{keyword.value.lineno} "
                        f"code={code!r}"
                    )

    assert uncataloged_codes == []


def test_static_terminal_run_error_codes_use_public_catalog() -> None:
    catalog_codes = {code.value for code in FLOW_API_ERROR_CODES}
    module_trees = _flow_module_trees()
    constants_by_module = _flow_module_constants_by_name(module_trees)
    violations: list[str] = []

    for path, tree in module_trees.items():
        if path == CATALOG_MODULE_PATH:
            continue
        visible_constants = _visible_string_constants(
            tree=tree,
            path=path,
            constants_by_module=constants_by_module,
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call = _terminal_code_keywords(node)
            if call is None:
                continue
            call_name, keyword_names = call
            for keyword in node.keywords:
                if keyword.arg not in keyword_names:
                    continue
                if _flow_api_error_code_value_expr(keyword.value):
                    continue
                static_value = _static_string_code_value(
                    keyword.value,
                    constants=visible_constants,
                )
                if static_value is None:
                    continue
                location = f"{path.relative_to(BACKEND_ROOT)}:{keyword.value.lineno}"
                if static_value not in catalog_codes:
                    violations.append(
                        f"{location} {call_name}.{keyword.arg}={static_value!r} "
                        "is not in FlowApiErrorCode"
                    )
                    continue
                violations.append(
                    f"{location} {call_name}.{keyword.arg}={static_value!r} "
                    "duplicates FlowApiErrorCode instead of using the enum"
                )

    assert violations == []


def test_dynamic_terminal_run_error_code_producers_are_intentional() -> None:
    module_trees = _flow_module_trees()
    constants_by_module = _flow_module_constants_by_name(module_trees)
    dynamic_producers: set[tuple[str, str, str, str]] = set()

    for path, tree in module_trees.items():
        if path == CATALOG_MODULE_PATH:
            continue
        visible_constants = _visible_string_constants(
            tree=tree,
            path=path,
            constants_by_module=constants_by_module,
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call = _terminal_code_keywords(node)
            if call is None:
                continue
            call_name, keyword_names = call
            for keyword in node.keywords:
                if keyword.arg not in keyword_names:
                    continue
                if _flow_api_error_code_value_expr(keyword.value):
                    continue
                static_value = _static_string_code_value(
                    keyword.value,
                    constants=visible_constants,
                )
                if static_value is not None:
                    continue
                dynamic_producers.add(
                    (
                        str(path.relative_to(BACKEND_ROOT)),
                        call_name,
                        keyword.arg,
                        ast.unparse(keyword.value),
                    )
                )

    assert dynamic_producers == DOCUMENTED_DYNAMIC_TERMINAL_RUN_ERROR_CODE_PRODUCERS


def _literal_flow_code_occurrences(paths: tuple[Path, ...]) -> list[tuple[str, str]]:
    occurrences: list[tuple[str, str]] = []

    for path in paths:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg not in {"code", "error_code"}:
                        continue
                    value = keyword.value
                    if not isinstance(value, ast.Constant):
                        continue
                    if not isinstance(value.value, str):
                        continue
                    if FLOW_ERROR_CODE_PATTERN.fullmatch(value.value):
                        occurrences.append(
                            (
                                f"{path.relative_to(BACKEND_ROOT)}:{value.lineno}",
                                value.value,
                            )
                        )
                continue
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=True):
                    if not isinstance(key, ast.Constant) or key.value != "code":
                        continue
                    if not isinstance(value, ast.Constant):
                        continue
                    if not isinstance(value.value, str):
                        continue
                    if FLOW_ERROR_CODE_PATTERN.fullmatch(value.value):
                        occurrences.append(
                            (
                                f"{path.relative_to(BACKEND_ROOT)}:{value.lineno}",
                                value.value,
                            )
                        )
                continue
            assignment_value = _assignment_string_value(node)
            if assignment_value is None:
                continue
            if FLOW_ERROR_CODE_PATTERN.fullmatch(assignment_value):
                occurrences.append(
                    (
                        f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}",
                        assignment_value,
                    )
                )

    return occurrences


def test_flow_api_router_literal_flow_codes_are_cataloged() -> None:
    catalog_codes = {code.value for code in FLOW_API_ERROR_CODES}
    literal_occurrences = _literal_flow_code_occurrences(
        tuple(FLOW_API_SOURCE_ROOT.rglob("*.py"))
    )
    unexpected = [
        f"{location} code={code!r}"
        for location, code in literal_occurrences
        if code not in catalog_codes
    ]

    assert unexpected == []


def test_public_flow_error_literals_are_cataloged() -> None:
    catalog_codes = {code.value for code in FLOW_API_ERROR_CODES}
    literal_occurrences = _literal_flow_code_occurrences(
        PUBLIC_FLOW_ERROR_EMITTER_PATHS
    )
    unexpected = [
        f"{location} code={code!r}"
        for location, code in literal_occurrences
        if code not in catalog_codes
    ]

    assert unexpected == []


def test_flow_api_guide_backticked_flow_codes_are_cataloged() -> None:
    catalog_codes = {code.value for code in FLOW_API_ERROR_CODES}
    catalog_codes.update(code.value for code in FlowPackageErrorCode)
    guide_text = DOCS_FLOW_API_GUIDE.read_text(encoding="utf-8")
    tokens = set(FLOW_GUIDE_BACKTICKED_TOKEN_PATTERN.findall(guide_text))
    allowlisted_tokens = set(FLOW_GUIDE_NON_ERROR_CODE_TOKENS)

    missing_allowlist_mentions = sorted(allowlisted_tokens - tokens)
    assert missing_allowlist_mentions == []

    uncataloged_tokens = sorted(tokens - catalog_codes - allowlisted_tokens)
    assert uncataloged_tokens == []


def test_checked_in_sdk_flow_api_error_codes_match_backend_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _load_generator_module()
    generated_js = tmp_path / "flow-api-error-codes.js"
    generated_dts = tmp_path / "flow-api-error-codes.d.ts"

    monkeypatch.setattr(generator, "TARGET_JS", generated_js)
    monkeypatch.setattr(generator, "TARGET_DTS", generated_dts)

    generator.main()

    assert generated_js.read_text(encoding="utf-8") == SDK_ERROR_CODES_JS.read_text(
        encoding="utf-8"
    )
    assert generated_dts.read_text(encoding="utf-8") == SDK_ERROR_CODES_DTS.read_text(
        encoding="utf-8"
    )
