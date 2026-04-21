"""FCM scaffold (Phase A.0).

Covers: version constant, dataclass shape (engine-truth fields only),
registry seeding from `INPUT_TYPE_POLICIES`, and the `not_exposed_reason`
invariant. Chain validation, tuple-matrix coverage, and critic invariants
land with A.1 / A.3 and are deliberately out of scope here.
"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from intric.flows.enums import FlowInputType, FlowOutputType
from intric.flows.flow_capability_manifest import (
    CAPABILITY_REGISTRY,
    CHAIN_COMPATIBILITY,
    FCM_VERSION,
    FlowCapability,
)
from intric.flows.step_chain_rules import COMPATIBLE_TYPE_COERCIONS
from intric.flows.type_policies import INPUT_TYPE_POLICIES


def _flow_capability_manifest_source() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "src"
        / "intric"
        / "flows"
        / "flow_capability_manifest.py"
    )


def test_fcm_version_is_one() -> None:
    assert FCM_VERSION == 1


def test_flow_capability_is_frozen_with_engine_truth_fields() -> None:
    capability = FlowCapability(
        id="fixture",
        label="fixture",
        description="fixture",
        applies_to_tuples=(),
        required_config=(),
        invariants=(),
        exposure="builder",
        not_exposed_reason=None,
    )
    assert capability.id == "fixture"
    assert capability.exposure == "builder"
    assert capability.applies_to_tuples == ()
    with pytest.raises(FrozenInstanceError):
        capability.id = "mutated"  # type: ignore[misc]


def test_registry_has_one_entry_per_input_type_policy() -> None:
    seeded_ids = {
        cap.id for cap in CAPABILITY_REGISTRY.values() if cap.id.startswith("input_")
    }
    expected_ids = {f"input_{key}" for key in INPUT_TYPE_POLICIES}
    assert seeded_ids == expected_ids


@pytest.mark.parametrize("input_key", sorted(INPUT_TYPE_POLICIES.keys()))
def test_registry_exposure_tracks_policy_supported_flag(input_key: str) -> None:
    policy = INPUT_TYPE_POLICIES[input_key]
    capability = CAPABILITY_REGISTRY[f"input_{input_key}"]
    if policy.supported:
        assert capability.exposure == "builder"
        assert capability.not_exposed_reason is None
    else:
        assert capability.exposure == "not_exposed"
        assert capability.not_exposed_reason is not None
        assert capability.not_exposed_reason.strip() != ""


def test_not_exposed_capability_requires_reason() -> None:
    with pytest.raises(ValueError, match="not_exposed_reason"):
        FlowCapability(
            id="fixture",
            label="fixture",
            description="fixture",
            applies_to_tuples=(),
            required_config=(),
            invariants=(),
            exposure="not_exposed",
            not_exposed_reason=None,
        )


def test_engine_only_capability_requires_reason() -> None:
    with pytest.raises(ValueError, match="not_exposed_reason"):
        FlowCapability(
            id="fixture",
            label="fixture",
            description="fixture",
            applies_to_tuples=(),
            required_config=(),
            invariants=(),
            exposure="engine_only",
            not_exposed_reason=None,
        )


def test_engine_only_capability_accepts_valid_reason() -> None:
    """Positive path: `engine_only` with a non-empty reason is constructible.
    Guards against future regressions where the symmetric invariant starts
    rejecting valid states by mistake."""
    capability = FlowCapability(
        id="engine_only_fixture",
        label="fixture",
        description="fixture",
        applies_to_tuples=(),
        required_config=(),
        invariants=(),
        exposure="engine_only",
        not_exposed_reason="Engine-internal plumbing; no builder surface.",
    )
    assert capability.exposure == "engine_only"
    assert capability.not_exposed_reason is not None


def test_builder_exposure_rejects_spurious_reason() -> None:
    """Engine-truth cannot admit contradictory state. A builder-exposed
    capability cannot carry a `not_exposed_reason`."""
    with pytest.raises(ValueError, match="not_exposed_reason"):
        FlowCapability(
            id="fixture",
            label="fixture",
            description="fixture",
            applies_to_tuples=(),
            required_config=(),
            invariants=(),
            exposure="builder",
            not_exposed_reason="spurious reason that should be rejected",
        )


def test_capability_registry_is_immutable() -> None:
    """`CAPABILITY_REGISTRY` is a `MappingProxyType`; mutation at runtime
    must fail. The manifest is canonical — consumers must not patch it."""
    from intric.flows.flow_capability_manifest import CAPABILITY_REGISTRY

    with pytest.raises(TypeError):
        CAPABILITY_REGISTRY["input_new"] = CAPABILITY_REGISTRY["input_text"]  # type: ignore[index]
    with pytest.raises(TypeError):
        del CAPABILITY_REGISTRY["input_text"]  # type: ignore[misc]


def test_chain_compatibility_is_frozen_and_typed_with_enums() -> None:
    """`CHAIN_COMPATIBILITY` must be a frozenset of
    `(FlowOutputType, FlowInputType)` pairs — i.e. typed, not bare strings."""
    assert isinstance(CHAIN_COMPATIBILITY, frozenset)
    for pair in CHAIN_COMPATIBILITY:
        assert isinstance(pair, tuple) and len(pair) == 2
        out_type, in_type = pair
        assert isinstance(out_type, FlowOutputType), (
            f"CHAIN_COMPATIBILITY key {pair!r} — out-type must be a FlowOutputType"
        )
        assert isinstance(in_type, FlowInputType), (
            f"CHAIN_COMPATIBILITY key {pair!r} — in-type must be a FlowInputType"
        )


def test_chain_compatibility_mirrors_legacy_compatible_type_coercions() -> None:
    """Parity test. Phase A.1a mirrors `COMPATIBLE_TYPE_COERCIONS` into the
    FCM without touching consumers; the two sets must stay in lockstep
    until Phase G deletes the legacy table. A drift here is a bug."""
    fcm_as_strings = {(out.value, inp.value) for out, inp in CHAIN_COMPATIBILITY}
    assert fcm_as_strings == COMPATIBLE_TYPE_COERCIONS, (
        "CHAIN_COMPATIBILITY has drifted from COMPATIBLE_TYPE_COERCIONS.\n"
        f"Missing from FCM: {COMPATIBLE_TYPE_COERCIONS - fcm_as_strings}\n"
        f"Extra in FCM:    {fcm_as_strings - COMPATIBLE_TYPE_COERCIONS}"
    )


def test_fcm_module_has_no_ai_builder_imports() -> None:
    """Redundant with the P0.7 `importlinter` contract but keeps the invariant
    obvious in this test module: engine capability truth must not depend on
    planner strategy."""
    tree = ast.parse(_flow_capability_manifest_source().read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "ai_builder" not in module.split("."), (
                f"forbidden import from ai_builder: {module}"
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert "ai_builder" not in alias.name.split("."), (
                    f"forbidden import from ai_builder: {alias.name}"
                )
