from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
sys.path.insert(0, str(BACKEND_SRC))

from intric.flows.enums import (  # noqa: E402
    FLOW_RUN_STATUS_CAPABILITIES,
    FLOW_RUN_STATUS_FILTER_ORDER,
)

TARGET_JS = (
    REPO_ROOT
    / "frontend"
    / "packages"
    / "intric-js"
    / "src"
    / "flows"
    / "flow-run-status-capabilities.js"
)
TARGET_DTS = TARGET_JS.with_suffix(".d.ts")


def _js_bool(value: bool) -> str:
    return "true" if value else "false"


def _capability_literal(capability: Mapping[str, object]) -> list[str]:
    return [
        "  {",
        f'    status: {json.dumps(capability["status"])},',
        f'    is_active: {_js_bool(bool(capability["is_active"]))},',
        f'    should_poll: {_js_bool(bool(capability["should_poll"]))},',
        f'    is_terminal: {_js_bool(bool(capability["is_terminal"]))},',
        f'    is_cancellable: {_js_bool(bool(capability["is_cancellable"]))},',
        f'    is_awaiting_review: {_js_bool(bool(capability["is_awaiting_review"]))},',
        f'    can_request_redispatch: {_js_bool(bool(capability["can_request_redispatch"]))}',
        "  }",
    ]


def _capabilities_literal(capabilities: Sequence[Mapping[str, object]]) -> str:
    lines = ["["]
    for index, capability in enumerate(capabilities):
        entry = _capability_literal(capability)
        if index < len(capabilities) - 1:
            entry[-1] = f"{entry[-1]},"
        lines.extend(entry)
    lines.append("]")
    return "\n".join(lines)


def _object_freeze_string_array(name: str, values: list[str]) -> list[str]:
    lines = [f"export const {name} = Object.freeze(["]
    for index, value in enumerate(values):
        comma = "," if index < len(values) - 1 else ""
        lines.append(f"  {json.dumps(value)}{comma}")
    lines.append("]);")
    return lines


def main() -> None:
    capabilities = [
        {
            "status": capability.status.value,
            "is_active": capability.is_active,
            "should_poll": capability.should_poll,
            "is_terminal": capability.is_terminal,
            "is_cancellable": capability.is_cancellable,
            "is_awaiting_review": capability.is_awaiting_review,
            "can_request_redispatch": capability.can_request_redispatch,
        }
        for capability in FLOW_RUN_STATUS_CAPABILITIES.values()
    ]
    filter_order = [status.value for status in FLOW_RUN_STATUS_FILTER_ORDER]

    TARGET_JS.write_text(
        "\n".join(
            [
                "// Generated from backend/src/intric/flows/enums.py. Do not edit by hand.",
                f"const capabilities = {_capabilities_literal(capabilities)};",
                "",
                "export const FLOW_RUN_STATUS_CAPABILITIES = Object.freeze(",
                "  capabilities.map((capability) => Object.freeze(capability))",
                ");",
                *_object_freeze_string_array("FLOW_RUN_STATUS_FILTER_ORDER", filter_order),
                "",
            ]
        ),
        encoding="utf-8",
    )
    TARGET_DTS.write_text(
        "\n".join(
            [
                "// Generated from backend/src/intric/flows/enums.py. Do not edit by hand.",
                'import type { components } from "../types/schema";',
                "",
                'export type FlowRunStatusCapability = components["schemas"]["FlowRunStatusCapabilityPublic"];',
                'export type FlowRunStatusCapabilities = components["schemas"]["FlowRunStatusCapabilitiesPublic"];',
                "export declare const FLOW_RUN_STATUS_CAPABILITIES: readonly FlowRunStatusCapability[];",
                'export declare const FLOW_RUN_STATUS_FILTER_ORDER: readonly FlowRunStatusCapability["status"][];',
                "",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
