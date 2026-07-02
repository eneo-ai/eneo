from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from flow_sdk_codegen import (  # noqa: E402
    object_freeze_string_array,
    string_literal_union_lines,
)

TARGET_JS = (
    REPO_ROOT
    / "frontend"
    / "packages"
    / "eneo-js"
    / "src"
    / "flows"
    / "flow-run-reserved-input-payload-keys.js"
)
TARGET_DTS = TARGET_JS.with_suffix(".d.ts")
SOURCE_DESCRIPTION = "backend/src/eneo/flows/flow_run_input_envelope.py"
FLOW_RUN_INPUT_ENVELOPE_SOURCE = (
    BACKEND_SRC / "eneo" / "flows" / "flow_run_input_envelope.py"
)


def _evaluate_constant_expression(
    node: ast.AST,
    names: dict[str, str | frozenset[str]],
) -> str | frozenset[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in names:
        return names[node.id]
    if isinstance(node, ast.Set):
        return frozenset(
            _require_string(_evaluate_constant_expression(item, names))
            for item in node.elts
        )
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "frozenset"
        and len(node.args) == 1
        and not node.keywords
    ):
        value = _evaluate_constant_expression(node.args[0], names)
        if isinstance(value, frozenset):
            return value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _require_string_set(_evaluate_constant_expression(node.left, names))
        right = _require_string_set(_evaluate_constant_expression(node.right, names))
        return left | right
    raise ValueError(
        f"Unsupported Flow run input envelope constant expression: {ast.dump(node)}"
    )


def _require_string(value: str | frozenset[str]) -> str:
    if isinstance(value, str):
        return value
    raise ValueError("Expected string constant in Flow run input envelope source.")


def _require_string_set(value: str | frozenset[str]) -> frozenset[str]:
    if isinstance(value, frozenset):
        return value
    raise ValueError("Expected string set constant in Flow run input envelope source.")


def _reserved_input_payload_keys_from_source() -> tuple[str, ...]:
    tree = ast.parse(FLOW_RUN_INPUT_ENVELOPE_SOURCE.read_text(encoding="utf-8"))
    names: dict[str, str | frozenset[str]] = {}

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        target_name = node.targets[0].id
        if not target_name.isupper() and not target_name.startswith("_"):
            continue
        try:
            names[target_name] = _evaluate_constant_expression(node.value, names)
        except ValueError:
            continue

    reserved_keys = names.get("FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS")
    if not isinstance(reserved_keys, frozenset):
        raise RuntimeError(
            f"Could not read FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS from {FLOW_RUN_INPUT_ENVELOPE_SOURCE}"
        )
    return tuple(sorted(reserved_keys))


def main() -> None:
    reserved_keys = _reserved_input_payload_keys_from_source()

    TARGET_JS.write_text(
        "\n".join(
            [
                f"// Generated from {SOURCE_DESCRIPTION}. Do not edit by hand.",
                *object_freeze_string_array(
                    "FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS", reserved_keys
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
    TARGET_DTS.write_text(
        "\n".join(
            [
                f"// Generated from {SOURCE_DESCRIPTION}. Do not edit by hand.",
                *string_literal_union_lines(
                    "FlowRunReservedInputPayloadKey", reserved_keys
                ),
                "export declare const FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS: readonly FlowRunReservedInputPayloadKey[];",
                "",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
