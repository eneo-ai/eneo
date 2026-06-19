from __future__ import annotations

import importlib.util
import json
import sys
import types
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

FLOW_API_ERROR_CODE_SOURCE = BACKEND_SRC / "intric" / "flows" / "flow_api_error_code.py"

TARGET_JS = (
    REPO_ROOT
    / "frontend"
    / "packages"
    / "intric-js"
    / "src"
    / "flows"
    / "flow-api-error-codes.js"
)
TARGET_DTS = TARGET_JS.with_suffix(".d.ts")


def _load_flow_api_error_code_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "flow_api_error_code",
        FLOW_API_ERROR_CODE_SOURCE,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Could not load Flow API error code catalog from {FLOW_API_ERROR_CODE_SOURCE}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    flow_api_error_code = _load_flow_api_error_code_module()
    error_codes = tuple(flow_api_error_code.FLOW_API_ERROR_CODES)
    error_code_values = tuple(code.value for code in error_codes)
    error_code_entries = tuple((code.name, code.value) for code in error_codes)

    constant_lines = ["export const FLOW_API_ERROR_CODE = Object.freeze({"]
    for index, (name, value) in enumerate(error_code_entries):
        comma = "," if index < len(error_code_entries) - 1 else ""
        constant_lines.append(f"  {name}: {json.dumps(value)}{comma}")
    constant_lines.append("});")

    constant_type_lines = ["export declare const FLOW_API_ERROR_CODE: Readonly<{"]
    for name, value in error_code_entries:
        constant_type_lines.append(f"  {name}: {json.dumps(value)};")
    constant_type_lines.append("}>;")

    TARGET_JS.write_text(
        "\n".join(
            [
                "// Generated from backend/src/intric/flows/flow_api_error_code.py. Do not edit by hand.",
                *constant_lines,
                *object_freeze_string_array("FLOW_API_ERROR_CODES", error_code_values),
                "",
            ]
        ),
        encoding="utf-8",
    )
    TARGET_DTS.write_text(
        "\n".join(
            [
                "// Generated from backend/src/intric/flows/flow_api_error_code.py. Do not edit by hand.",
                *constant_type_lines,
                *string_literal_union_lines("FlowApiErrorCode", error_code_values),
                "export declare const FLOW_API_ERROR_CODES: readonly FlowApiErrorCode[];",
                "",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
