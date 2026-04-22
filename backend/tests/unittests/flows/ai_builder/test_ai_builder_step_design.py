"""Step design rules registry tests.

Pins the structured-data contract that replaces the hand-prose
`_KNOWLEDGE_PACK_CREATE_STEP_DESIGN` constant in
`ai_builder_knowledge_pack_create`. The renderer must preserve the
top-level header the existing prompt-level tests assert against
(`test_ai_builder_prompts.py::test_prompt_contains_knowledge_pack_sections`
and `test_ai_builder_knowledge_pack.py` substring guards).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from intric.flows.ai_builder.ai_builder_step_design import (
    STEP_DESIGN_SECTIONS,
    StepDesignRule,
    StepDesignSection,
    render_step_design,
)


class TestStepDesignRuleDataclass:
    def test_rule_dataclass_is_frozen_with_default_empty_sub_rules(self) -> None:
        rule = StepDesignRule(text="rule body")
        assert rule.text == "rule body"
        assert rule.sub_rules == ()
        with pytest.raises(FrozenInstanceError):
            rule.text = "mutated"  # type: ignore[misc]

    def test_rule_accepts_sub_rules(self) -> None:
        rule = StepDesignRule(text="header", sub_rules=("a", "b"))
        assert rule.sub_rules == ("a", "b")


class TestStepDesignSectionDataclass:
    def test_section_dataclass_is_frozen_with_heading_and_rules(self) -> None:
        section = StepDesignSection(
            heading="Instruktioner",
            rules=(StepDesignRule(text="rule"),),
        )
        assert section.heading == "Instruktioner"
        assert len(section.rules) == 1
        with pytest.raises(FrozenInstanceError):
            section.heading = "mutated"  # type: ignore[misc]


class TestStepDesignRegistryContract:
    def test_registry_contains_four_canonical_sections(self) -> None:
        """Pin the four hand-prose section headings from the replaced
        constant — Instruktioner / JSON-utdata / Formulär och runtime /
        Dokumentleverans — so a silent drop or merge trips CI."""
        assert len(STEP_DESIGN_SECTIONS) == 4

    def test_registry_covers_four_canonical_headings(self) -> None:
        """Pin each expected section heading by content, not index, so a
        future reorder for pedagogical reasons does not break the
        contract."""
        headings = {section.heading for section in STEP_DESIGN_SECTIONS}
        assert "Instruktioner" in headings
        assert "JSON-utdata via `output_fields`" in headings
        assert "Formulär och runtime" in headings
        assert "Dokumentleverans" in headings

    def test_registry_entries_have_non_empty_rules(self) -> None:
        for section in STEP_DESIGN_SECTIONS:
            assert section.heading.strip(), "section heading must be non-empty"
            assert len(section.rules) > 0, (
                f"section {section.heading!r} must have at least one rule"
            )
            for rule in section.rules:
                assert rule.text.strip(), (
                    f"rule in section {section.heading!r} must have non-empty text"
                )


class TestRenderStepDesign:
    def test_render_emits_top_level_header(self) -> None:
        """`# Create-läge: kompilerad datamodell` is the top-level header
        asserted as a substring by
        `test_build_prompt_knowledge_sections_for_create_proposal_includes_full_create_guidance`
        and `test_prompt_contains_knowledge_pack_sections`."""
        rendered = render_step_design()
        assert "# Create-läge: kompilerad datamodell" in rendered

    def test_render_emits_every_section_heading(self) -> None:
        rendered = render_step_design()
        assert "## Instruktioner" in rendered
        assert "## JSON-utdata via `output_fields`" in rendered
        assert "## Formulär och runtime" in rendered
        assert "## Dokumentleverans" in rendered

    def test_render_includes_every_registered_rule(self) -> None:
        """Silent-drop guard: every rule in the registry must surface in
        the render, including nested sub-rules. A missed entry would
        leak a field-usage rule the planner never sees."""
        rendered = render_step_design()
        for section in STEP_DESIGN_SECTIONS:
            for rule in section.rules:
                assert rule.text in rendered, (
                    f"rule {rule.text!r} missing from rendered output"
                )
                for sub in rule.sub_rules:
                    assert sub in rendered, (
                        f"sub-rule {sub!r} under {rule.text!r} missing from "
                        "rendered output"
                    )

    def test_render_is_deterministic(self) -> None:
        """Two invocations must return the exact same bytes. A non-
        deterministic render would poison LLM prompt caching."""
        assert render_step_design() == render_step_design()

    def test_render_emits_sections_in_registry_declaration_order(self) -> None:
        """Reorder guard: rendered output places each registry section's
        heading in the same order as the registry tuple."""
        rendered = render_step_design()
        positions = [
            rendered.index(f"## {section.heading}") for section in STEP_DESIGN_SECTIONS
        ]
        assert positions == sorted(positions), (
            f"section heading positions out of registry order: {positions}"
        )

    def test_render_matches_expected_block_byte_for_byte(self) -> None:
        """Golden guard on the full rendered block. Any change to the
        header text, section heading prose, bullet wording, nested
        bullet indentation, or blank-line structure must flip this test.
        The prompt-level tests only check substrings, so structural
        drift could otherwise slip past CI."""
        expected = "\n".join(
            [
                "# Create-läge: kompilerad datamodell",
                "",
                "## Instruktioner",
                (
                    "- `instructions` ska vara ren uppgiftsbeskrivning — inga "
                    "`{{ ... }}`-variabler"
                ),
                "- Beskriv roll, krav, format och begränsningar tydligt",
                (
                    "- Backend kompilerar underlaget från `input_source`, tidigare "
                    "steg och formulärfält"
                ),
                (
                    "- Backend kompilerar även explicita fältbindningar från "
                    "`uses_previous_fields`"
                ),
                (
                    "- Instruktioner får gärna vara LÅNGA och detaljerade när "
                    "uppgiften kräver flera regler, formatkrav eller beslutslogik"
                ),
                "",
                "## JSON-utdata via `output_fields`",
                '- `output_fields` används bara för `output_type="json"`',
                "- Max nesting depth 3: toppnivåfält, barnfält och ett barnbarnsled",
                "- Bra mönster:",
                "  - objekt med scalar-fält",
                "  - array med objektposter",
                "  - objekt/array som innehåller ett extra lager scalar-fält",
                "- Undvik djupare träd än så; platta hellre ut strukturen",
                "",
                "## Formulär och runtime",
                (
                    "- Modellera användarens körningsdata som `form_fields` i "
                    "stället för dold prompttext"
                ),
                "- Referera till dessa med `uses_form_fields`",
                (
                    "- När ett senare steg bara behöver vissa JSON-fält från ett "
                    "tidigare steg: använd `uses_previous_fields`"
                ),
                (
                    "- Om användaren måste ladda upp filer vid körning: sätt "
                    "`runtime_upload=true`"
                ),
                "",
                "## Dokumentleverans",
                (
                    '- `document_delivery_mode="generated"` för vanliga genererade '
                    "PDF/DOCX-dokument"
                ),
                '- `document_delivery_mode="template_fill"` bara för DOCX',
            ]
        )
        assert render_step_design() == expected
