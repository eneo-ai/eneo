"""Outline-flow architecture rules registry tests.

Pins the structured-data contract that replaces the hand-prose
low-level Flow mechanics in legacy create-mode prompts.
The renderer must preserve the top-level header the existing
prompt-level tests assert against
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
            heading="Vad modellen anger",
            rules=("rule one", "rule two"),
        )
        assert section.heading == "Vad modellen anger"
        assert section.rules == ("rule one", "rule two")
        with pytest.raises(FrozenInstanceError):
            section.heading = "mutated"  # type: ignore[misc]


class TestFlowArchitectureRegistryContract:
    def test_registry_contains_three_canonical_sections(self) -> None:
        assert len(FLOW_ARCHITECTURE_SECTIONS) == 3

    def test_registry_covers_three_canonical_headings(self) -> None:
        """Pin each expected section heading by content, not index, so a
        future reorder for pedagogical reasons does not break the
        contract."""
        headings = {section.heading for section in FLOW_ARCHITECTURE_SECTIONS}
        assert "Vad modellen anger" in headings
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
        """`# Outline-flow-kompilering` is the top-level header asserted
        as a substring by
        `test_build_prompt_knowledge_sections_for_create_proposal_includes_full_create_guidance`
        and `test_prompt_contains_knowledge_pack_sections`."""
        rendered = render_flow_architecture()
        assert "# Outline-flow-kompilering" in rendered

    def test_render_emits_lead_paragraph(self) -> None:
        """The lead paragraph explains the create-mode contract (planner
        describes intent, backend compiles the canonical flow spec).
        Silent deletion would leave the header orphaned from the section
        bullets."""
        rendered = render_flow_architecture()
        assert (
            "I create-läge beskriver modellen bara avsikten i `propose_flow`. "
            "Backend kompilerar outline till kanonisk flödesspecifikation."
        ) in rendered

    def test_render_emits_every_section_heading(self) -> None:
        rendered = render_flow_architecture()
        assert "## Vad modellen anger" in rendered
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
                "# Outline-flow-kompilering",
                "",
                (
                    "I create-läge beskriver modellen bara avsikten i `propose_flow`. "
                    "Backend kompilerar outline till kanonisk flödesspecifikation."
                ),
                "",
                "## Vad modellen anger",
                (
                    "- `flow_name`, `flow_description` och `plan_rationale` "
                    "som vanlig text"
                ),
                (
                    "- `runtime_input` beskriver bara huvudingången vid körning "
                    "(`text`, `json`, `document`, `file` eller `audio`)"
                ),
                (
                    "- `input_fields` modellerar sekundära inmatningsfält/input variables "
                    "som användaren fyller i vid sidan av huvudunderlaget"
                ),
                "- `steps[].name` och `steps[].task` beskriver semantiska arbetssteg",
                (
                    "- `steps[].output_fields` används när ett steg ska producera "
                    "strukturerade datapunkter för senare arbete"
                ),
                "- `steps[].uses_input_fields` refererar till namn i `input_fields`",
                (
                    "- `final_output_type` anger slutartefakten (`text`, `json`, "
                    "`pdf` eller `docx`)"
                ),
                "",
                "## Vad backend äger",
                "- input source/type och upload/runtime config",
                "- `underlag` / input bindings och variabelinjektion mellan steg",
                "- stegrefar (`plan_step_ref`)",
                "- `output_mode`",
                "- `document_delivery_mode` för PDF/DOCX-leverans",
                "- `uses_previous_fields` och fältnivåreferenser mellan JSON-steg",
                "- kontrakt / JSON Schema från `output_fields`",
                "",
                "## Praktiska regler",
                "- Skriv inga template-variabler som `{{ ... }}` i outline-fält",
                "- Skriv inga ID:n, hashvärden, tidsstämplar, råa bindings eller rå JSON Schema",
                "- Använd flera tydliga steg för komplexa flöden i stället för ett överlastat steg",
                (
                    "- Lägg körningsmetadata som ska återanvändas i `input_fields`, "
                    "inte gömt i prompttext"
                ),
                (
                    "- Lägg inte huvudtexten, dokumentet, filen eller ljudet som ett "
                    "`input_field`; backend kopplar huvudingången från arkitekturen"
                ),
                (
                    "- Använd `output_fields` när senare steg behöver stabila fält; "
                    "backend gör steget strukturerat"
                ),
                (
                    "- Beskriv syntes/jämförelse semantiskt; backend avgör när flera "
                    "tidigare steg ska kopplas in som källa"
                ),
                (
                    "- För DOCX/PDF räcker `final_output_type`; backend skapar "
                    "leveranssteget eller dokumentläget"
                ),
                (
                    "- Citations kan begäras bara som semantisk önskan på textsteg; "
                    "backend validerar om det stöds"
                ),
            ]
        )
        assert render_flow_architecture() == expected
