"""Validation-repair examples registry tests.

Pins the structured-data contract that replaces the hand-prose
`_VALIDATION_REPAIR_EXAMPLES` constant in `ai_builder_knowledge_pack_create`.
The renderer must preserve the bilingual headings/labels the existing
prompt-level tests assert against
(`test_ai_builder_prompts.py::test_prompt_contains_validation_repair_examples`).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from intric.flows.ai_builder.ai_builder_validation_repair import (
    VALIDATION_REPAIR_EXAMPLES_REGISTRY,
    ValidationRepairExample,
    render_validation_repair_examples,
)


class TestValidationRepairExampleDataclass:
    def test_dataclass_is_frozen_with_three_fields(self) -> None:
        example = ValidationRepairExample(
            bad_draft="bad",
            validation_error="error",
            corrected_draft="fix",
        )
        assert example.bad_draft == "bad"
        assert example.validation_error == "error"
        assert example.corrected_draft == "fix"
        with pytest.raises(FrozenInstanceError):
            example.bad_draft = "mutated"  # type: ignore[misc]


class TestValidationRepairRegistryContract:
    def test_registry_contains_three_canonical_repair_pairs(self) -> None:
        """The hand-prose constant carried exactly three repair pairs:
        variable-references-in-instructions, output_fields-without-json,
        and template_fill-without-docx. The migration must not drop or
        bundle any of them — each is a distinct validation rule the
        planner needs to learn separately."""
        assert len(VALIDATION_REPAIR_EXAMPLES_REGISTRY) == 3

    def test_registry_covers_three_canonical_validation_rules(self) -> None:
        """Each repair pair targets a specific validator failure mode the
        planner must learn to avoid. Pin the three rules by content
        substring rather than positional order so a future reorder for
        pedagogical reasons does not break the contract."""
        joined = " ".join(
            f"{ex.bad_draft} | {ex.validation_error} | {ex.corrected_draft}"
            for ex in VALIDATION_REPAIR_EXAMPLES_REGISTRY
        )
        assert (
            "variable references are not allowed in create_flow instructions" in joined
        )
        assert "output_fields require output_type=json" in joined
        assert "template_fill requires output_type=docx" in joined

    def test_registry_entries_have_non_empty_fields(self) -> None:
        for example in VALIDATION_REPAIR_EXAMPLES_REGISTRY:
            assert example.bad_draft.strip(), "bad_draft must be non-empty"
            assert example.validation_error.strip(), (
                "validation_error must be non-empty"
            )
            assert example.corrected_draft.strip(), "corrected_draft must be non-empty"


class TestRenderValidationRepairExamples:
    def test_render_emits_top_level_header(self) -> None:
        """`# Validation Repair Examples` is the existing top-level header
        that `test_ai_builder_knowledge_pack.py` asserts as a substring of
        the rendered create-proposal sections."""
        rendered = render_validation_repair_examples()
        assert "# Validation Repair Examples" in rendered

    def test_render_emits_bilingual_subheading(self) -> None:
        """Sub-heading `Felaktigt utkast → valideringsfel → korrigerat
        utkast` carries the Swedish vocabulary that
        `test_prompt_contains_validation_repair_examples` matches against
        (`felaktigt utkast`, `valideringsfel`, `korrigerat utkast` —
        case-folded)."""
        rendered = render_validation_repair_examples()
        assert "Felaktigt utkast" in rendered
        assert "valideringsfel" in rendered
        assert "korrigerat utkast" in rendered

    def test_render_emits_bilingual_per_entry_labels(self) -> None:
        """Each repair entry uses the English `Bad draft:`, `Validation
        error:`, `Corrected draft:` labels — these are what the planner
        prompt asserts against (case-folded as `bad draft`, `validation
        error`, `corrected draft`)."""
        rendered = render_validation_repair_examples()
        assert "Bad draft:" in rendered
        assert "Validation error:" in rendered
        assert "Corrected draft:" in rendered

    def test_render_includes_every_registered_example(self) -> None:
        """Silent-drop guard: every example in the registry must surface
        in the render. A missed entry would leak a validation rule the
        planner never sees."""
        rendered = render_validation_repair_examples()
        for example in VALIDATION_REPAIR_EXAMPLES_REGISTRY:
            assert example.bad_draft in rendered, (
                f"bad_draft {example.bad_draft!r} missing from rendered output"
            )
            assert example.validation_error in rendered, (
                f"validation_error {example.validation_error!r} missing from "
                "rendered output"
            )
            assert example.corrected_draft in rendered, (
                f"corrected_draft {example.corrected_draft!r} missing from "
                "rendered output"
            )

    def test_render_is_deterministic(self) -> None:
        """Two invocations must return the exact same bytes. A non-
        deterministic render would poison LLM prompt caching."""
        assert (
            render_validation_repair_examples() == render_validation_repair_examples()
        )

    def test_render_emits_entries_in_registry_declaration_order(self) -> None:
        """Reorder guard: rendered output places each registry entry's
        bad_draft in the same order as the registry tuple. The
        substring + silent-drop guards above would still pass after a
        silent reorder, so the byte-level entry sequence the old
        `_VALIDATION_REPAIR_EXAMPLES` constant locked in needs its own
        assertion."""
        rendered = render_validation_repair_examples()
        positions = [
            rendered.index(example.bad_draft)
            for example in VALIDATION_REPAIR_EXAMPLES_REGISTRY
        ]
        assert positions == sorted(positions), (
            f"bad_draft positions out of registry order: {positions}"
        )

    def test_render_matches_expected_block_byte_for_byte(self) -> None:
        """Golden guard on the full rendered block. Any change to the
        header/subheader text, per-entry label prose, blank-line
        structure, or entry ordering must flip this test — the planner
        prompt-level tests only check substrings, so structural drift
        could otherwise slip past CI."""
        expected = "\n".join(
            [
                "# Validation Repair Examples",
                "",
                "## Felaktigt utkast → valideringsfel → korrigerat utkast",
                "",
                "- Bad draft:",
                "  `{{ step_b.output.text }}` i `instructions`",
                "- Validation error:",
                "  `variable references are not allowed in create_flow instructions`",
                "- Corrected draft:",
                "  skriv bara vanliga instruktioner och låt backend kompilera underlaget",
                "",
                "- Bad draft:",
                '  `output_type="text"` tillsammans med `output_fields`',
                "- Validation error:",
                "  `output_fields require output_type=json`",
                "- Corrected draft:",
                '  byt till `output_type="json"` eller ta bort `output_fields`',
                "",
                "- Bad draft:",
                (
                    '  `document_delivery_mode="template_fill"` tillsammans med '
                    '`output_type="pdf"`'
                ),
                "- Validation error:",
                "  `template_fill requires output_type=docx`",
                "- Corrected draft:",
                "  använd genererad PDF eller byt dokumenttypen till DOCX",
            ]
        )
        assert render_validation_repair_examples() == expected
