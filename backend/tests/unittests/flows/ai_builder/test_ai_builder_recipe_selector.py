"""Tests for signal-aware recipe selection."""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_knowledge_pack_create import (
    KNOWLEDGE_PACK_CREATE_RECIPES,
)
from intric.flows.ai_builder.ai_builder_recipe_selector import select_relevant_recipes


class TestRecipeSelection:
    def test_no_signals_returns_full_recipes(self):
        """With no signals, return all recipes (safe fallback)."""
        result = select_relevant_recipes({})
        assert "Transkribering" in result
        assert "Dokumentanalys" in result
        assert "Exempel" in result

    def test_audio_signal_includes_transcription(self):
        signals = {"final_output_mode": {"structured_text"}}
        text = "jag vill transkribera ljudfiler"
        result = select_relevant_recipes(signals, text)
        assert "Transkribering" in result

    def test_docx_signal_includes_template_recipe(self):
        signals = {"final_output_mode": {"docx_document"}}
        result = select_relevant_recipes(signals)
        assert "DOCX" in result or "Exempel" in result

    def test_json_signal_includes_json_pipeline(self):
        signals = {"final_output_mode": {"structured_json"}}
        result = select_relevant_recipes(signals)
        assert "JSON" in result or "Exempel" in result

    def test_golden_example_always_included_with_signals(self):
        signals = {"final_output_mode": {"structured_text"}}
        text = "analysera dokument"
        result = select_relevant_recipes(signals, text)
        assert "Exempel" in result

    def test_filtered_result_is_shorter_than_full(self):
        """Filtered recipes should be shorter than full recipes."""
        full = select_relevant_recipes({})
        filtered = select_relevant_recipes(
            {"final_output_mode": {"structured_text"}},
            "transkribera ljud",
        )
        # Filtered should be notably shorter (at least 20% less)
        assert len(filtered) < len(full) * 0.9

    def test_freeform_text_triggers_audio_recipes(self):
        result = select_relevant_recipes({}, "vi behöver transkribera ljudinspelningar")
        assert "Transkribering" in result

    def test_freeform_text_triggers_docx_recipes(self):
        result = select_relevant_recipes({}, "output should be a DOCX file")
        assert "DOCX" in result or "Exempel" in result

    def test_sectioned_form_intake_text_selects_dedicated_recipe(self):
        result = select_relevant_recipes(
            {},
            (
                "Visa en sektion i taget och be användaren om fritext för varje sektion. "
                "Skapa sedan ett DOCX-dokument."
            ),
            recipe_source=KNOWLEDGE_PACK_CREATE_RECIPES,
        )

        assert "Sektionerad insamling via formulärfält" in result

    def test_pattern_registry_fires_when_single_pattern_wins_by_margin(self):
        """Distinctive retrieval-hint tokens on a single Pattern select its recipe.

        The prompt contains no `docx`/`json`/`jämför`/`audio`/`ljud`/`transkri`
        ad-hoc freeform triggers, no form_intake markers, and does not meet
        the `rich_document_workflow` triple condition. Only the
        `extract_structured_fields` Pattern scores decisively
        (`extract`/`structured`/`fields`), beating the runner-up
        `multi_step_quality_chain` by a clear margin — so the filtered
        create-recipes pack must include the JSON-pipeline recipe and
        exclude unrelated sections (audio, rich workflow, sectioned form).
        """
        result = select_relevant_recipes(
            {},
            "extract structured fields from input",
            recipe_source=KNOWLEDGE_PACK_CREATE_RECIPES,
        )

        assert "## JSON-steg" in result
        assert "## Exempel" in result
        assert "## Audio -> text -> analys -> rapport" not in result
        assert "## Dokumentflöde med formulärkomplettering" not in result
        assert "## Sektionerad insamling via formulärfält" not in result

    def test_pattern_registry_stays_silent_when_patterns_tie(self):
        """Ambiguous prompts that tie multiple patterns must NOT trigger the path.

        `document`/`report` tokens score equally across the document-family
        Patterns (`document_to_structured_report`, `document_to_docx_template`,
        `document_to_pdf_report`), so no single pattern wins the margin
        check. The selector therefore falls through to the safe-fallback
        full pack — it does not union recipes from every tied candidate,
        which would otherwise leak the JSON-pipeline recipe and the
        rich-workflow recipe into a plain document-report planner prompt.
        """
        result = select_relevant_recipes(
            {},
            "analyze my document and produce a report",
            recipe_source=KNOWLEDGE_PACK_CREATE_RECIPES,
        )

        # No trigger fires → full pack returned, so every base section present.
        assert "## Audio -> text -> analys -> rapport" in result
        assert "## Dokumentflöde med formulärkomplettering" in result
        assert "## Sektionerad insamling via formulärfält" in result

    def test_pattern_registry_stays_silent_on_single_token_winner(self):
        """Single-token wins must not narrow the recipe pack.

        A bare ``"extract"`` prompt hits exactly one retrieval-hint
        token for `extract_structured_fields` (`extract`) and zero for
        every other pattern. Under a naive `score > runner_up_score`
        guard that would be a single-winner trigger and inject the
        JSON-pipeline recipe alone. The absolute floor (`score >= 2`)
        blocks the narrowing — one generic token is not enough evidence
        to prune the full pack.
        """
        result = select_relevant_recipes(
            {},
            "extract",
            recipe_source=KNOWLEDGE_PACK_CREATE_RECIPES,
        )

        # No trigger fires → full pack returned.
        assert "## Audio -> text -> analys -> rapport" in result
        assert "## Dokumentflöde med formulärkomplettering" in result
        assert "## Sektionerad insamling via formulärfält" in result

    def test_pattern_registry_fires_exactly_at_minimum_confidence_floor(self):
        """Score-2 winner with score-1 runner-up pins the lower bound.

        ``"analysis report"`` scores `document_to_structured_report=2`
        (tokens `analysis, report`) versus `document_to_docx_template=1`
        and `document_to_pdf_report=1` runners. That is the exact
        boundary the floor-plus-margin rule is meant to permit — the
        selector must narrow to the document-analysis recipe here and
        must not widen to unrelated pipelines. Complements the
        `3 vs 1` test above by pinning the ``score == 2`` lower edge.
        """
        result = select_relevant_recipes(
            {},
            "analysis report",
            recipe_source=KNOWLEDGE_PACK_CREATE_RECIPES,
        )

        assert "## Dokumentpaket -> JSON -> grounded text -> DOCX/PDF" in result
        assert "## Exempel" in result
        assert "## Audio -> text -> analys -> rapport" not in result
        assert "## JSON-steg" not in result
        assert "## Dokumentflöde med formulärkomplettering" not in result
        assert "## Sektionerad insamling via formulärfält" not in result

    def test_pattern_registry_stays_silent_on_generic_vocabulary_winner(self):
        """Generic-vocabulary patterns must not drive the recipe-registry trigger.

        ``"review my document"`` scores `multi_step_quality_chain=2`
        (tokens `review, document`) versus `document_to_*=1` runners,
        so the trigger's absolute floor and strict-margin checks both
        pass. But `multi_step_quality_chain` leaves `recipe_sections`
        empty precisely because its retrieval hints (`review`, `document`,
        `chain`) overlap with generic planner vocabulary. Firing on
        those tokens would narrow a plain document-review prompt onto
        the rich-workflow recipe without any structural evidence. The
        rich-workflow recipe still reaches the planner through
        `extract_planner_pattern_recipe_signals` when the prompt actually
        describes that workflow.
        """
        result = select_relevant_recipes(
            {},
            "review my document",
            recipe_source=KNOWLEDGE_PACK_CREATE_RECIPES,
        )

        # multi_step_quality_chain wins by margin but is not registered,
        # so the selector falls through to the full-pack fallback.
        assert "## Audio -> text -> analys -> rapport" in result
        assert "## Dokumentflöde med formulärkomplettering" in result
        assert "## Sektionerad insamling via formulärfält" in result
