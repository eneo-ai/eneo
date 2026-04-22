"""Tests for signal-aware recipe selection (Phase 3.2)."""

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
