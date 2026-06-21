from __future__ import annotations

import json

from intric.flows.ai_builder.ai_builder_flow_schema_values import (
    builder_input_source_values,
    builder_input_type_values,
    builder_output_mode_values,
    builder_output_type_values,
)
from intric.flows.ai_builder.ai_builder_knowledge_pack import (
    build_prompt_knowledge_sections,
    build_role_and_protocol,
    build_structured_reference_block,
)
from intric.flows.flow_capability_manifest import CAPABILITY_REGISTRY


def test_build_prompt_knowledge_sections_for_create_discovery_is_compact() -> None:
    sections = build_prompt_knowledge_sections(
        is_edit_mode=False,
        has_confirmed_requirements=False,
    )

    assert any("Outline-flow-kompilering" in section for section in sections)
    assert not any("Create-läge: vanliga mönster" in section for section in sections)
    assert not any("Validation Repair Examples" in section for section in sections)


def test_build_prompt_knowledge_sections_for_create_after_confirmation_stays_compact() -> (
    None
):
    sections = build_prompt_knowledge_sections(
        is_edit_mode=False,
        has_confirmed_requirements=True,
    )

    assert any("Outline-flow-kompilering" in section for section in sections)
    assert not any(
        "Create-läge: kompilerad datamodell" in section for section in sections
    )
    assert not any("Create-läge: vanliga mönster" in section for section in sections)
    assert not any("Validation Repair Examples" in section for section in sections)


def test_create_mode_after_confirmation_teaches_variable_system() -> None:
    """The variable system block is the planner's ONLY guide to
    `{{ step_a.output.structured.field }}` selectors. Withholding it
    in create mode forced the planner to default to `all_previous_steps`
    even when targeted refs would have served — the production failure
    mode behind multi-minute first-token latency on document-stitching
    flows. Edit mode already gets this content; create mode must too,
    once requirements are confirmed and the planner is generating
    flow shape rather than asking discovery questions."""

    sections = build_prompt_knowledge_sections(
        is_edit_mode=False,
        has_confirmed_requirements=True,
    )

    assert any("Variabelsystemet" in section for section in sections), (
        "Variable system teaching missing from confirmed-requirements create prompt"
    )
    assert any("step_a.output.structured" in section for section in sections), (
        "Targeted JSON-field selector example must reach the create-mode planner"
    )


def test_create_mode_after_confirmation_teaches_underlag_design() -> None:
    """`input_bindings.question` ("Underlag till steget") is the
    PRIMARY mechanism for selective context composition. The
    instructions-and-underlag block teaches the
    `previous_step` + targeted underlag pattern as a deliberate
    alternative to `all_previous_steps`. Without it the planner
    cannot reason about when to choose one over the other."""

    sections = build_prompt_knowledge_sections(
        is_edit_mode=False,
        has_confirmed_requirements=True,
    )

    assert any("Instruktioner vs Underlag" in section for section in sections), (
        "Underlag/instruktioner teaching missing from confirmed-requirements create prompt"
    )
    assert any("Selektiv sammansättning" in section for section in sections), (
        "Selective composition pattern (the explicit AB shape) must be visible"
    )


def test_create_mode_after_confirmation_teaches_all_previous_steps_anti_pattern() -> (
    None
):
    """The anti-patterns block explicitly flags
    `all_previous_steps` as token-explosive in long flows and points
    the planner to `previous_step` + variable-driven underlag as the
    structural alternative. This is the single highest-leverage
    teaching for the targeted-underlag goal — keeping it in edit mode
    only means the create-mode planner cannot self-correct the
    bloat."""

    sections = build_prompt_knowledge_sections(
        is_edit_mode=False,
        has_confirmed_requirements=True,
    )

    assert any("Antimönster" in section for section in sections), (
        "Anti-patterns block missing from confirmed-requirements create prompt"
    )
    assert any(
        "Alla steg använder all_previous_steps" in section for section in sections
    ), "Specific anti-pattern naming all_previous_steps is the load-bearing teaching"


def test_create_discovery_omits_underlag_and_anti_pattern_blocks() -> None:
    """Pre-confirmation discovery is intentionally compact — the
    planner's job there is to ask clarifying questions, not to
    compose flow shape. Adding the variable/underlag/anti-pattern
    blocks at that phase pollutes context for no benefit. Only
    after `confirm_requirements` should the heavier teaching ship."""

    sections = build_prompt_knowledge_sections(
        is_edit_mode=False,
        has_confirmed_requirements=False,
    )

    assert not any("Variabelsystemet" in section for section in sections), (
        "Variable system must not pollute pre-confirmation discovery prompt"
    )
    assert not any("Instruktioner vs Underlag" in section for section in sections), (
        "Underlag teaching must not pollute pre-confirmation discovery prompt"
    )
    assert not any("Antimönster" in section for section in sections), (
        "Anti-patterns must not pollute pre-confirmation discovery prompt"
    )


def test_build_prompt_knowledge_sections_for_edit_mode_uses_edit_guidance() -> None:
    sections = build_prompt_knowledge_sections(
        is_edit_mode=True,
        has_confirmed_requirements=False,
    )

    assert any("Flödesarkitektur" in section for section in sections)
    assert any("Variabelsystemet" in section for section in sections)
    assert any("Redigeringsläge (Edit Mode)" in section for section in sections)
    assert any("Input- och utdatakontrakt" in section for section in sections)


def test_build_prompt_knowledge_sections_includes_registry_rendered_pack_in_create_mode() -> (
    None
):
    sections = build_prompt_knowledge_sections(
        is_edit_mode=False,
        has_confirmed_requirements=True,
    )

    assert any("Flow capabilities (engine truth)" in section for section in sections), (
        "registry-rendered capabilities header missing from create-mode prompt"
    )
    assert any(
        "Planner patterns (positive archetypes)" in section for section in sections
    ), "registry-rendered positive patterns header missing"
    assert any("Discovery questions" in section for section in sections), (
        "registry-rendered discovery questions header missing"
    )


def test_build_prompt_knowledge_sections_omits_registry_pack_without_confirmed_requirements() -> (
    None
):
    sections = build_prompt_knowledge_sections(
        is_edit_mode=False,
        has_confirmed_requirements=False,
    )

    assert not any(
        "Flow capabilities (engine truth)" in section for section in sections
    ), "registry-rendered pack must not leak into the pre-requirements discovery prompt"


def test_build_prompt_knowledge_sections_includes_registry_pack_in_edit_mode() -> None:
    sections = build_prompt_knowledge_sections(
        is_edit_mode=True,
        has_confirmed_requirements=False,
    )

    assert any("Flow capabilities (engine truth)" in section for section in sections), (
        "edit-mode prompt must include the registry-rendered pack so edits stay "
        "consistent with create-mode guarantees"
    )
    assert any(
        "Planner patterns (positive archetypes)" in section for section in sections
    ), "edit-mode prompt must include planner archetypes alongside capabilities"


def test_role_and_reference_blocks_switch_submission_tool_by_mode() -> None:
    create_role = build_role_and_protocol(is_edit_mode=False)
    edit_role = build_role_and_protocol(is_edit_mode=True)
    create_reference = build_structured_reference_block(is_edit_mode=False)
    edit_reference = build_structured_reference_block(is_edit_mode=True)

    assert "propose_flow" in create_role
    assert "propose_flow" in edit_role
    assert '"submission_tool": "propose_flow"' in create_reference
    assert '"submission_tool": "propose_flow"' in edit_reference


def test_structured_reference_is_generated_from_flow_capability_sources() -> None:
    reference = build_structured_reference_block(is_edit_mode=False)
    payload = _extract_json_block(reference)

    assert payload["flow_capability_source"] == (
        "AI Builder schema values + Flow Capability Manifest"
    )
    assert "input_source" not in payload
    assert "output_mode" not in payload
    assert "semantic_input_strategy" not in payload
    assert payload["input_type"] == builder_input_type_values()
    assert payload["output_type"] == builder_output_type_values()
    assert payload["builder_capabilities"] == sorted(
        cap.id for cap in CAPABILITY_REGISTRY.values() if cap.exposure == "builder"
    )


def test_edit_structured_reference_keeps_raw_flow_wiring_surface() -> None:
    reference = build_structured_reference_block(is_edit_mode=True)
    payload = _extract_json_block(reference)

    assert payload["input_source"] == builder_input_source_values()
    assert payload["output_mode"] == builder_output_mode_values()


def _extract_json_block(markdown: str) -> dict[str, object]:
    start = markdown.index("```json") + len("```json")
    end = markdown.index("```", start)
    return json.loads(markdown[start:end])
