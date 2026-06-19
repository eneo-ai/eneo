from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

from intric.flows.flow_run_input_envelope import FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS

BACKEND_ROOT = Path(__file__).resolve().parents[3]
GENERATOR_PATH = (
    BACKEND_ROOT / "scripts" / "generate_flow_run_reserved_input_payload_keys_ts.py"
)
SDK_RESERVED_KEYS_JS = (
    BACKEND_ROOT
    / ".."
    / "frontend"
    / "packages"
    / "intric-js"
    / "src"
    / "flows"
    / "flow-run-reserved-input-payload-keys.js"
).resolve()
SDK_RESERVED_KEYS_DTS = SDK_RESERVED_KEYS_JS.with_suffix(".d.ts")


def _load_generator_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generate_flow_run_reserved_input_payload_keys_ts", GENERATOR_PATH
    )
    if spec is None or spec.loader is None:
        pytest.fail(f"Could not load generator module from {GENERATOR_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reserved_input_payload_keys_are_sorted_for_sdk_output() -> None:
    generator = _load_generator_module()

    assert tuple(sorted(FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS)) == (
        "expected_flow_version",
        "file_ids",
        "step_inputs",
        "transkribering",
    )
    assert generator._reserved_input_payload_keys_from_source() == tuple(
        sorted(FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS)
    )


def test_checked_in_sdk_reserved_input_payload_keys_match_backend_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _load_generator_module()
    generated_js = tmp_path / "flow-run-reserved-input-payload-keys.js"
    generated_dts = tmp_path / "flow-run-reserved-input-payload-keys.d.ts"

    monkeypatch.setattr(generator, "TARGET_JS", generated_js)
    monkeypatch.setattr(generator, "TARGET_DTS", generated_dts)

    generator.main()

    assert generated_js.read_text(encoding="utf-8") == SDK_RESERVED_KEYS_JS.read_text(
        encoding="utf-8"
    )
    assert generated_dts.read_text(encoding="utf-8") == SDK_RESERVED_KEYS_DTS.read_text(
        encoding="utf-8"
    )
