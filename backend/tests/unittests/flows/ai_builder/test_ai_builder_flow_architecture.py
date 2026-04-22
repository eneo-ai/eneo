"""Flow-architecture rules registry tests.

Pins the structured-data contract that replaces the hand-prose
`_KNOWLEDGE_PACK_CREATE_FLOW_ARCHITECTURE` constant in
`ai_builder_knowledge_pack_create`. The renderer must preserve the
top-level header the existing prompt-level tests assert against
(`test_ai_builder_prompts.py::test_prompt_contains_knowledge_pack_sections`
and `test_ai_builder_knowledge_pack.py` substring guards).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from intric.flows.ai_builder.ai_builder_flow_architecture import (
    FLOW_ARCHITECTURE_SECTIONS,
    FlowArchitectureSection,
    render_flow_architecture,
)


class TestFlowArchitectureSectionDataclass:
    def test_section_dataclass_is_frozen_with_heading_and_rules(self) -> None:
        section = FlowArchitectureSection(
            heading="Vad du SKA ange",
            rules=("rule one", "rule two"),
        )
        assert section.heading == "Vad du SKA ange"
        assert section.rules == ("rule one", "rule two")
        with pytest.raises(FrozenInstanceError):
            section.heading = "mutated"  # type: ignore[misc]


class TestFlowArchitectureRegistryContract:
    def test_registry_contains_three_canonical_sections(self) -> None:
        """Pin the three hand-prose section headings from the replaced
        constant — `Vad du SKA ange` / `Vad backend äger` / `Praktiska
        regler` — so a silent drop or merge trips CI."""
        assert len(FLOW_ARCHITECTURE_SECTIONS) == 3

    def test_registry_covers_three_canonical_headings(self) -> None:
        """Pin each expected section heading by content, not index, so a
        future reorder for pedagogical reasons does not break the
        contract."""
        headings = {section.heading for section in FLOW_ARCHITECTURE_SECTIONS}
        assert "Vad du SKA ange" in headings
        assert "Vad backend äger" in headings
        assert "Praktiska regler" in headings

    def test_registry_entries_have_non_empty_rules(self) -> None:
        for section in FLOW_ARCHITECTURE_SECTIONS:
            assert section.heading.strip(), "section heading must be non-empty"
            assert len(section.rules) > 0, (
                f"section {section.heading!r} must have at least one rule"
            )
            for rule in section.rules:
                assert rule.strip(), (
                    f"rule in section {section.heading!r} must have non-empty text"
                )


class TestRenderFlowArchitecture:
    def test_render_emits_top_level_header(self) -> None:
        """`# Create-flow-kompilering` is the top-level header asserted
        as a substring by
        `test_build_prompt_knowledge_sections_for_create_proposal_includes_full_create_guidance`
        and `test_prompt_contains_knowledge_pack_sections`."""
        rendered = render_flow_architecture()
        assert "# Create-flow-kompilering" in rendered

    def test_render_emits_lead_paragraph(self) -> None:
        """The lead paragraph explains the create-mode contract (planner
        describes intent, backend compiles the canonical flow spec).
        Silent deletion would leave the header orphaned from the section
        bullets."""
        rendered = render_flow_architecture()
        assert (
            "I create-läge beskriver du bara avsikten i `create_flow`. "
            "Backend kompilerar utkastet till den kanoniska flödesspecifikationen."
        ) in rendered

    def test_render_emits_every_section_heading(self) -> None:
        rendered = render_flow_architecture()
        assert "## Vad du SKA ange" in rendered
        assert "## Vad backend äger" in rendered
        assert "## Praktiska regler" in rendered

    def test_render_includes_every_registered_rule(self) -> None:
        """Silent-drop guard: every rule in the registry must surface in
        the render. A missed entry would leak a field-usage rule the
        planner never sees."""
        rendered = render_flow_architecture()
        for section in FLOW_ARCHITECTURE_SECTIONS:
            for rule in section.rules:
                assert rule in rendered, f"rule {rule!r} missing from rendered output"

    def test_render_is_deterministic(self) -> None:
        """Two invocations must return the exact same bytes. A non-
        deterministic render would poison LLM prompt caching."""
        assert render_flow_architecture() == render_flow_architecture()

    def test_render_emits_sections_in_registry_declaration_order(self) -> None:
        """Reorder guard: rendered output places each registry section's
        heading in the same order as the registry tuple."""
        rendered = render_flow_architecture()
        positions = [
            rendered.index(f"## {section.heading}")
            for section in FLOW_ARCHITECTURE_SECTIONS
        ]
        assert positions == sorted(positions), (
            f"section heading positions out of registry order: {positions}"
        )

    def test_render_matches_expected_block_byte_for_byte(self) -> None:
        """Golden guard on the full rendered block. Any change to the
        header text, lead paragraph, section heading prose, bullet
        wording, or blank-line structure must flip this test. The
        prompt-level tests only check substrings, so structural drift
        could otherwise slip past CI.

        Intentional delta from the deleted constant: a three-space
        artifact inside the `Filuppladdning ...` bullet (caused by the
        old triple-quote backslash-continuation indentation) is
        normalized to a single space. No semantic change for the
        planner; documented in the slice commit body."""
        expected = "\n".join(
            [
                "# Create-flow-kompilering",
                "",
                (
                    "I create-läge beskriver du bara avsikten i `create_flow`. "
                    "Backend kompilerar utkastet till den kanoniska flödesspecifikationen."
                ),
                "",
                "## Vad du SKA ange",
                "- `instructions` — vanlig text utan variabelsyntax",
                "- `input_source`, `input_type`, `output_type`",
                (
                    "- `runtime_upload`, `runtime_required`, `runtime_max_files` "
                    "för första uppladdningssteget"
                ),
                "- `uses_form_fields` när senare steg behöver formulärvärden",
                (
                    "- `uses_previous_fields` när senare steg behöver specifika "
                    "strukturerade fält från tidigare JSON-steg"
                ),
                "- `document_delivery_mode` för PDF/DOCX-leverans",
                "- `citations_requested` för textsteg som ska ha källhänvisningar",
                "- `output_fields` för JSON-steg",
                "",
                "## Vad backend äger",
                "- stegrefar (`plan_step_ref`)",
                "- underlag / variabelinjektion mellan steg",
                "- kontrakt / JSON Schema",
                "- `output_mode`",
                "- runtime-input-config",
                "",
                "## Praktiska regler",
                '- Steg 1 MÅSTE använda `input_source="flow_input"`',
                (
                    '- Senare steg får inte använda `input_source="flow_input"`; '
                    "använd `previous_step` eller `all_previous_steps`"
                ),
                (
                    "- Sista steget MÅSTE ha `output_type` som matchar den explicit "
                    "efterfrågade slutartefakten (`text`, `json`, `pdf` eller `docx`)"
                ),
                (
                    "- När flera uppladdade dokument ska vägas samman i en gemensam "
                    "analys eller grounded sammanfattning ska ett samlande steg använda "
                    '`input_source="all_previous_steps"`'
                ),
                (
                    "- Varje objekt i `steps` måste vara ett komplett steg. "
                    "Fältdefinitioner med `name`, `field_type`, `description` och "
                    "`required` hör hemma i `output_fields`, inte som egna poster i "
                    "`steps`"
                ),
                (
                    "- Filuppladdning används via `runtime_upload=true` på ett "
                    "`flow_input`-steg med `input_type=document`, `file` eller `audio`"
                ),
                (
                    '- Använd `output_type="json"` + `output_fields` när nästa steg '
                    "behöver namngivna datapunkter"
                ),
                (
                    '- Använd `output_type="text"` för grounded sammanfattningar, '
                    "resonemang och läsbar rapporttext"
                ),
                (
                    '- Använd `output_type="docx"` eller `"pdf"` bara när steget '
                    "faktiskt levererar dokumentet"
                ),
            ]
        )
        assert render_flow_architecture() == expected
