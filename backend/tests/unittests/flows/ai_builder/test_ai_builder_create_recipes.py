"""Create-mode recipes registry tests.

Pins the structured-data contract that replaces the hand-prose
`_KNOWLEDGE_PACK_CREATE_RECIPES` constant in
`ai_builder_knowledge_pack_create`. The renderer must preserve the
top-level header the existing prompt-level tests assert against
(`test_ai_builder_prompts.py::test_prompt_contains_knowledge_pack_sections`
and `test_ai_builder_knowledge_pack.py` substring guards).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from intric.flows.ai_builder.ai_builder_create_recipes import (
    KNOWLEDGE_PACK_CREATE_RECIPES_SECTIONS,
    RecipeBullet,
    RecipeSection,
    render_knowledge_pack_create_recipes,
)


class TestRecipeBulletDataclass:
    def test_bullet_dataclass_is_frozen_with_default_empty_subitems(self) -> None:
        bullet = RecipeBullet(text="bullet body")
        assert bullet.text == "bullet body"
        assert bullet.numbered_subitems == ()
        with pytest.raises(FrozenInstanceError):
            bullet.text = "mutated"  # type: ignore[misc]

    def test_bullet_accepts_numbered_subitems(self) -> None:
        bullet = RecipeBullet(text="header", numbered_subitems=("a", "b"))
        assert bullet.numbered_subitems == ("a", "b")


class TestRecipeSectionDataclass:
    def test_section_dataclass_is_frozen_with_heading_and_optional_bodies(self) -> None:
        section = RecipeSection(
            section_id="fixture",
            heading="Numbered section",
            numbered_items=("step one", "step two"),
        )
        assert section.section_id == "fixture"
        assert section.heading == "Numbered section"
        assert section.numbered_items == ("step one", "step two")
        assert section.bullets == ()
        assert section.code_block == ""
        assert section.code_language == "json"
        with pytest.raises(FrozenInstanceError):
            section.heading = "mutated"  # type: ignore[misc]

    def test_section_accepts_bulleted_body(self) -> None:
        section = RecipeSection(
            section_id="bulleted_fixture",
            heading="Bulleted section",
            bullets=(RecipeBullet(text="first"), RecipeBullet(text="second")),
        )
        assert len(section.bullets) == 2
        assert section.numbered_items == ()
        assert section.code_block == ""

    def test_section_accepts_code_block_body(self) -> None:
        section = RecipeSection(
            section_id="code_fixture",
            heading="Code section",
            code_block='{"a": 1}',
            code_language="json",
        )
        assert section.code_block == '{"a": 1}'
        assert section.code_language == "json"
        assert section.numbered_items == ()
        assert section.bullets == ()


class TestRecipeRegistryContract:
    def test_registry_contains_canonical_section_count(self) -> None:
        """Pin the seven canonical section entries so a silent drop or
        merge trips CI. The seventh — the comparison recipe — was added
        alongside the `RECIPE_SECTIONS['comparison']` marker cut-over so
        the `comparison` signal no longer resolves to a no-op."""
        assert len(KNOWLEDGE_PACK_CREATE_RECIPES_SECTIONS) == 7

    def test_registry_section_ids_are_canonical_and_unique(self) -> None:
        """The selector filters recipes by `section_id`, not heading
        substring. Pin the canonical id set and uniqueness so a rename
        in the recipes module or a silent duplication cannot detach a
        section from its signal trigger."""
        ids = [section.section_id for section in KNOWLEDGE_PACK_CREATE_RECIPES_SECTIONS]
        assert len(ids) == len(set(ids)), (
            f"RecipeSection section_id values must be unique; got {ids}"
        )
        assert set(ids) == {
            "document_analysis",
            "transcription",
            "json_pipeline",
            "rich_document_workflow",
            "sectioned_form_intake",
            "comparison",
            "golden_example",
        }

    def test_registry_covers_canonical_headings(self) -> None:
        """Pin each expected section heading by content, not index, so a
        future reorder for pedagogical reasons does not break the
        contract."""
        headings = {
            section.heading for section in KNOWLEDGE_PACK_CREATE_RECIPES_SECTIONS
        }
        assert "Dokumentpaket -> JSON -> grounded text -> DOCX/PDF" in headings
        assert "Audio -> text -> analys -> rapport" in headings
        assert "JSON-steg" in headings
        assert "Dokumentflöde med formulärkomplettering och kvalitetssteg" in headings
        assert "Sektionerad insamling via formulärfält" in headings
        assert "Jämförelseflöden med flera indata" in headings
        assert "Exempel: dokumentgranskning med riskanalys" in headings

    def test_registry_entries_have_exactly_one_populated_body(self) -> None:
        """Mutual-exclusivity guard: each section must use exactly one of
        `numbered_items`, `bullets`, or `code_block`. A section with two
        populated bodies would render ambiguously."""
        for section in KNOWLEDGE_PACK_CREATE_RECIPES_SECTIONS:
            populated = [
                bool(section.numbered_items),
                bool(section.bullets),
                bool(section.code_block),
            ]
            assert sum(populated) == 1, (
                f"section {section.heading!r} must populate exactly one body field"
            )

    def test_registry_entries_have_non_empty_bodies(self) -> None:
        for section in KNOWLEDGE_PACK_CREATE_RECIPES_SECTIONS:
            assert section.heading.strip(), "section heading must be non-empty"
            if section.numbered_items:
                for item in section.numbered_items:
                    assert item.strip(), (
                        f"numbered item in section {section.heading!r} must be "
                        "non-empty"
                    )
            elif section.bullets:
                for bullet in section.bullets:
                    assert bullet.text.strip(), (
                        f"bullet in section {section.heading!r} must have non-empty "
                        "text"
                    )
                    for sub in bullet.numbered_subitems:
                        assert sub.strip(), (
                            f"sub-item in section {section.heading!r} must be non-empty"
                        )
            else:
                assert section.code_block.strip(), (
                    f"code block in section {section.heading!r} must be non-empty"
                )


class TestRenderKnowledgePackCreateRecipes:
    def test_render_emits_top_level_header(self) -> None:
        """`# Create-läge: vanliga mönster` is the top-level header
        asserted as a substring by
        `test_build_prompt_knowledge_sections_for_create_proposal_includes_full_create_guidance`
        and `test_prompt_contains_knowledge_pack_sections`."""
        rendered = render_knowledge_pack_create_recipes()
        assert "# Create-läge: vanliga mönster" in rendered

    def test_render_emits_every_section_heading(self) -> None:
        rendered = render_knowledge_pack_create_recipes()
        assert "## Dokumentpaket -> JSON -> grounded text -> DOCX/PDF" in rendered
        assert "## Audio -> text -> analys -> rapport" in rendered
        assert "## JSON-steg" in rendered
        assert (
            "## Dokumentflöde med formulärkomplettering och kvalitetssteg" in rendered
        )
        assert "## Sektionerad insamling via formulärfält" in rendered
        assert "## Jämförelseflöden med flera indata" in rendered
        assert "## Exempel: dokumentgranskning med riskanalys" in rendered

    def test_render_includes_every_registered_body_fragment(self) -> None:
        """Silent-drop guard: every numbered item, bullet, nested sub-item,
        and non-empty code block line must surface in the render. A missed
        entry would leak a pattern the planner never sees."""
        rendered = render_knowledge_pack_create_recipes()
        for section in KNOWLEDGE_PACK_CREATE_RECIPES_SECTIONS:
            for item in section.numbered_items:
                assert item in rendered, (
                    f"numbered item {item!r} missing from rendered output"
                )
            for bullet in section.bullets:
                assert bullet.text in rendered, (
                    f"bullet {bullet.text!r} missing from rendered output"
                )
                for sub in bullet.numbered_subitems:
                    assert sub in rendered, (
                        f"sub-item {sub!r} under {bullet.text!r} missing from "
                        "rendered output"
                    )
            if section.code_block:
                for line in section.code_block.splitlines():
                    if line.strip():
                        assert line in rendered, (
                            f"code line {line!r} missing from rendered output"
                        )

    def test_render_is_deterministic(self) -> None:
        """Two invocations must return the exact same bytes. A non-
        deterministic render would poison LLM prompt caching."""
        assert (
            render_knowledge_pack_create_recipes()
            == render_knowledge_pack_create_recipes()
        )

    def test_render_emits_sections_in_registry_declaration_order(self) -> None:
        """Reorder guard: rendered output places each registry section's
        heading in the same order as the registry tuple."""
        rendered = render_knowledge_pack_create_recipes()
        positions = [
            rendered.index(f"## {section.heading}")
            for section in KNOWLEDGE_PACK_CREATE_RECIPES_SECTIONS
        ]
        assert positions == sorted(positions), (
            f"section heading positions out of registry order: {positions}"
        )

    def test_render_emits_fenced_code_block_for_example_section(self) -> None:
        """The example section must wrap its body in a ```json ... ```
        fence so the planner sees it as literal JSON, not prose."""
        rendered = render_knowledge_pack_create_recipes()
        assert "```json" in rendered
        assert rendered.rstrip().endswith("```")

    def test_render_matches_expected_block_byte_for_byte(self) -> None:
        """Golden guard on the full rendered block. Any change to the
        header text, section heading prose, numbered-item wording, bullet
        wording, nested-subitem indentation, embedded code body, or blank-
        line structure must flip this test. The prompt-level tests only
        check substrings, so structural drift could otherwise slip past
        CI."""
        expected = "\n".join(
            [
                "# Create-läge: vanliga mönster",
                "",
                "## Dokumentpaket -> JSON -> grounded text -> DOCX/PDF",
                '1. Steg 1: `flow_input` + `input_type="document"` + `runtime_upload=true`',
                "2. Steg 2: extrahera strukturerad JSON via `output_fields`",
                (
                    "3. Steg 3: analysera eller resonera vidare från JSON eller text, "
                    "och använd `uses_previous_fields` när bara vissa datapunkter ska "
                    "följa med"
                ),
                (
                    "4. Steg 4: skriv grounded text med `citations_requested=true` om "
                    "spårbarhet behövs"
                ),
                "5. Sista steget: generera dokumentet som `pdf` eller `docx`",
                "",
                "## Audio -> text -> analys -> rapport",
                '1. Första steget: `input_type="audio"`, `output_type="text"`',
                "2. Nästa steg: analysera transkriberingen som text",
                "3. Sista steget: skriv rapporttext eller generera dokument",
                "",
                "## JSON-steg",
                "- Beskriv fälten i `output_fields`, inte som rå JSON Schema",
                "- Håll strukturen stabil och återanvändbar för nästa steg",
                (
                    "- Om nästa steg bara behöver några datapunkter, gör JSON-steget "
                    "tydligt och smalt"
                ),
                "",
                "## Dokumentflöde med formulärkomplettering och kvalitetssteg",
                (
                    "- När användaren beskriver ett dokumentbaserat flöde som också "
                    "behöver kompletterande användarvärden, återanvändbar strukturerad "
                    "analys eller ett kvalitets-/granskningssteg ska du inte kollapsa "
                    "planen till en minimal tvåstegskedja"
                ),
                "- Preferera i stället en tydlig pipeline:",
                "  1. `flow_input` för dokumentuppladdning",
                "  2. ett JSON-steg som extraherar återanvändbara fält",
                (
                    "  3. ett analys-, kvalitets- eller granskningssteg som använder "
                    "`uses_previous_fields`"
                ),
                "  4. ett slutsteg som producerar `docx`, `pdf` eller grounded text",
                (
                    "- Om användaren nämner att vissa uppgifter kan saknas eller "
                    "behöva förtydligas ska dessa modelleras som `form_fields`, och "
                    "senare steg ska läsa dem via `uses_form_fields`"
                ),
                (
                    "- När du behöver både dokument och formulärdata i samma lösning "
                    "ska dokument förbli primär `flow_input`, medan manuella "
                    "kompletteringar ligger i `form_fields`"
                ),
                (
                    "- Om användaren uttryckligen ber om ett mer genomarbetat flöde, "
                    "kvalitetssäkring eller språkgranskning ska detta synas som egna "
                    "mellanliggande steg i planen"
                ),
                "",
                "## Sektionerad insamling via formulärfält",
                (
                    "- När användaren beskriver ett fast set rubriker/sektioner där "
                    "användaren ska lämna fritext per sektion ska du modellera detta "
                    "som `form_fields`, inte som ett eget insamlingssteg per rubrik"
                ),
                "- Skapa ett textfält per rubrik/sektion",
                (
                    "- Låt senare steg använda `uses_form_fields` för att sammanställa "
                    "och skriva sluttexten"
                ),
                (
                    "- Om användaren vill kunna hoppa över eller gå tillbaka, modellera "
                    "detta som separata styrfält eller interaktionslogik runt samma "
                    "formulärdata — inte som sju separata JSON-insamlingssteg"
                ),
                (
                    "- Slutsteget ska använda de insamlade formulärfälten för att "
                    "skapa sammanställningen med samma rubriker"
                ),
                "",
                "## Jämförelseflöden med flera indata",
                (
                    "- När användaren vill ställa två eller fler indata sida vid "
                    "sida (dokument mot dokument, text mot text, mall mot "
                    "mall) ska varje indata extraheras till samma strukturerade "
                    "form innan jämförelsen sker"
                ),
                "- Typisk kedja:",
                (
                    "  1. ett `flow_input` eller `form_fields`-steg per indata, så "
                    "att varje källa är en tydlig variabel"
                ),
                (
                    "  2. ett JSON-steg som extraherar samma fält ur varje indata "
                    "via `output_fields`"
                ),
                (
                    "  3. ett jämförelsesteg som läser varje extrakt via "
                    "`uses_previous_fields` och producerar en tabell eller "
                    "sammanställning i `text`, `json` eller `docx`"
                ),
                (
                    "- Håll fältuppsättningen identisk per indata — annars blir "
                    "jämförelsen skev och det slutliga steget måste kompensera "
                    "för asymmetrier"
                ),
                "",
                "## Exempel: dokumentgranskning med riskanalys",
                "```json",
                "{",
                '  "flow_name": "Dokumentgranskning med riskanalys",',
                (
                    '  "plan_rationale": "Extraherar först strukturerade risker och '
                    'skriver sedan grounded rapport innan slutlig DOCX-leverans.",'
                ),
                '  "form_fields": [',
                (
                    '    {"variable_name": "referens_id", "label": "Referens-ID", '
                    '"field_type": "text", "required": true, "options": []},'
                ),
                (
                    '    {"variable_name": "ansvarig_enhet", "label": "Ansvarig enhet", '
                    '"field_type": "text", "required": true, "options": []}'
                ),
                "  ],",
                '  "steps": [',
                "    {",
                '      "name": "Extrahera text och riskdata",',
                (
                    '      "instructions": "Extrahera centrala fakta och identifierade '
                    'risker som strukturerad JSON.",'
                ),
                '      "input_source": "flow_input",',
                '      "input_type": "document",',
                '      "output_type": "json",',
                '      "runtime_upload": true,',
                '      "runtime_required": true,',
                '      "runtime_max_files": 10,',
                '      "uses_form_fields": ["referens_id", "ansvarig_enhet"],',
                '      "document_delivery_mode": "not_applicable",',
                '      "citations_requested": false,',
                '      "output_fields": [',
                (
                    '        {"name": "sammanfattning", "field_type": "string", '
                    '"description": "Kort sammanfattning av dokumentet", "required": '
                    "true},"
                ),
                (
                    '        {"name": "risker", "field_type": "array", "description": '
                    '"Identifierade risker", "required": true, "item_fields": ['
                ),
                (
                    '          {"name": "rubrik", "field_type": "string", '
                    '"description": "Riskrubrik", "required": true},'
                ),
                (
                    '          {"name": "konsekvens", "field_type": "object", '
                    '"description": "Konsekvenssammanfattning", "required": false, '
                    '"fields": ['
                ),
                (
                    '            {"name": "beskrivning", "field_type": "string", '
                    '"description": "Beskrivning av konsekvensen", "required": false},'
                ),
                (
                    '            {"name": "nivå", "field_type": "string", '
                    '"description": "Allvarlighetsgrad (låg, medel, hög)", '
                    '"required": false}'
                ),
                "          ]}",
                "        ]}",
                "      ]",
                "    },",
                "    {",
                '      "name": "Grounded sammanfattning",',
                (
                    '      "instructions": "Skriv en grounded sammanfattning som '
                    "kopplar riskerna till källdokumentet och anger spårbara "
                    'referenser.",'
                ),
                '      "input_source": "previous_step",',
                '      "input_type": "json",',
                '      "output_type": "text",',
                '      "uses_form_fields": ["referens_id", "ansvarig_enhet"],',
                '      "uses_previous_fields": [',
                (
                    '        {"from_step": 1, "field_path": "sammanfattning", '
                    '"label": "Dokumentsammanfattning"},'
                ),
                (
                    '        {"from_step": 1, "field_path": "risker.0.rubrik", '
                    '"label": "Första riskrubrik"}'
                ),
                "      ],",
                '      "document_delivery_mode": "not_applicable",',
                '      "citations_requested": true',
                "    },",
                "    {",
                '      "name": "Generera DOCX-rapport",',
                (
                    '      "instructions": "Skriv en strukturerad rapport på formell '
                    'svenska med rubriker, slutsatser och rekommendationer.",'
                ),
                '      "input_source": "previous_step",',
                '      "input_type": "text",',
                '      "output_type": "docx",',
                '      "document_delivery_mode": "generated",',
                '      "uses_form_fields": ["referens_id", "ansvarig_enhet"],',
                '      "citations_requested": false',
                "    }",
                "  ]",
                "}",
                "```",
            ]
        )
        assert render_knowledge_pack_create_recipes() == expected
