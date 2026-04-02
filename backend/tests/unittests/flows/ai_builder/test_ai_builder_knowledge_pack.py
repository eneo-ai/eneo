from __future__ import annotations

from intric.flows.ai_builder.ai_builder_knowledge_pack import (
    build_prompt_knowledge_sections,
    build_role_and_protocol,
    build_structured_reference_block,
)


def test_build_prompt_knowledge_sections_for_create_discovery_is_compact() -> None:
    sections = build_prompt_knowledge_sections(
        is_edit_mode=False,
        has_confirmed_requirements=False,
    )

    assert any("Create-flow-kompilering" in section for section in sections)
    assert not any("Create-läge: vanliga mönster" in section for section in sections)
    assert not any("Validation Repair Examples" in section for section in sections)


def test_build_prompt_knowledge_sections_for_create_proposal_includes_full_create_guidance() -> None:
    sections = build_prompt_knowledge_sections(
        is_edit_mode=False,
        has_confirmed_requirements=True,
    )

    assert any("Create-flow-kompilering" in section for section in sections)
    assert any("Create-läge: kompilerad datamodell" in section for section in sections)
    assert any("Create-läge: vanliga mönster" in section for section in sections)
    assert any("Validation Repair Examples" in section for section in sections)


def test_build_prompt_knowledge_sections_for_edit_mode_uses_edit_guidance() -> None:
    sections = build_prompt_knowledge_sections(
        is_edit_mode=True,
        has_confirmed_requirements=False,
    )

    assert any("Flödesarkitektur" in section for section in sections)
    assert any("Variabelsystemet" in section for section in sections)
    assert any("Redigeringsläge (Edit Mode)" in section for section in sections)
    assert any("Input- och utdatakontrakt" in section for section in sections)


def test_role_and_reference_blocks_switch_submission_tool_by_mode() -> None:
    create_role = build_role_and_protocol(is_edit_mode=False)
    edit_role = build_role_and_protocol(is_edit_mode=True)
    create_reference = build_structured_reference_block(is_edit_mode=False)
    edit_reference = build_structured_reference_block(is_edit_mode=True)

    assert "create_flow" in create_role
    assert "edit_flow" in edit_role
    assert '"submission_tool": "create_flow"' in create_reference
    assert '"submission_tool": "edit_flow"' in edit_reference
