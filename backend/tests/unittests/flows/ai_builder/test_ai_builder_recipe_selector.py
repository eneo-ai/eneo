"""Tests for signal-aware recipe selection."""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_create_recipes import (
    KNOWLEDGE_PACK_CREATE_RECIPES_SECTIONS,
    render_knowledge_pack_create_recipes,
)
from intric.flows.ai_builder.ai_builder_recipe_selector import (
    SIGNAL_TO_RECIPES,
    select_relevant_recipes,
)
from intric.flows.ai_builder.pattern_registry import PATTERN_REGISTRY


class TestRecipeSelection:
    def test_no_signals_returns_full_recipes(self):
        """With no signals, return the full recipe source unchanged."""
        source = render_knowledge_pack_create_recipes()
        result = select_relevant_recipes({}, recipe_source=source)
        assert result == source

    def test_audio_signal_includes_transcription(self):
        signals = {"final_output_mode": {"structured_text"}}
        text = "jag vill transkribera ljudfiler"
        result = select_relevant_recipes(
            signals, text, recipe_source=render_knowledge_pack_create_recipes()
        )
        assert "## Audio -> text -> analys -> rapport" in result

    def test_docx_signal_includes_template_recipe(self):
        signals = {"final_output_mode": {"docx_document"}}
        result = select_relevant_recipes(
            signals, recipe_source=render_knowledge_pack_create_recipes()
        )
        assert "DOCX" in result and "Exempel" in result

    def test_json_signal_includes_json_pipeline(self):
        signals = {"final_output_mode": {"structured_json"}}
        result = select_relevant_recipes(
            signals, recipe_source=render_knowledge_pack_create_recipes()
        )
        assert "## JSON-steg" in result and "Exempel" in result

    def test_golden_example_always_included_with_signals(self):
        signals = {"final_output_mode": {"structured_text"}}
        text = "analysera dokument"
        result = select_relevant_recipes(
            signals, text, recipe_source=render_knowledge_pack_create_recipes()
        )
        assert "Exempel" in result

    def test_filtered_result_is_shorter_than_full(self):
        """Filtered recipes should be shorter than full recipes."""
        source = render_knowledge_pack_create_recipes()
        full = select_relevant_recipes({}, recipe_source=source)
        filtered = select_relevant_recipes(
            {"final_output_mode": {"structured_text"}},
            "transkribera ljud",
            recipe_source=source,
        )
        # Filtered should be notably shorter (at least 20% less)
        assert len(filtered) < len(full) * 0.9

    def test_freeform_text_triggers_audio_recipes(self):
        result = select_relevant_recipes(
            {},
            "vi behöver transkribera ljudinspelningar",
            recipe_source=render_knowledge_pack_create_recipes(),
        )
        assert "## Audio -> text -> analys -> rapport" in result

    def test_freeform_text_triggers_docx_recipes(self):
        result = select_relevant_recipes(
            {},
            "output should be a DOCX file",
            recipe_source=render_knowledge_pack_create_recipes(),
        )
        assert "DOCX" in result and "Exempel" in result

    def test_comparison_signal_includes_comparison_recipe(self):
        """The comparison signal must resolve to the structured comparison
        section, not silently no-op. Before this slice, `RECIPE_SECTIONS`
        advertised `comparison` but the structured pack had no matching
        section — the marker matched nothing, so the signal fired without
        effect. Pins that the section exists and is selected."""
        result = select_relevant_recipes(
            {},
            "jämför två offerter sida vid sida",
            recipe_source=render_knowledge_pack_create_recipes(),
        )
        assert "## Jämförelseflöden med flera indata" in result

    def test_sectioned_form_intake_text_selects_dedicated_recipe(self):
        result = select_relevant_recipes(
            {},
            (
                "Visa en sektion i taget och be användaren om fritext för varje sektion. "
                "Skapa sedan ett DOCX-dokument."
            ),
            recipe_source=render_knowledge_pack_create_recipes(),
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
            recipe_source=render_knowledge_pack_create_recipes(),
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
            recipe_source=render_knowledge_pack_create_recipes(),
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
            recipe_source=render_knowledge_pack_create_recipes(),
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
            recipe_source=render_knowledge_pack_create_recipes(),
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
            recipe_source=render_knowledge_pack_create_recipes(),
        )

        # multi_step_quality_chain wins by margin but is not registered,
        # so the selector falls through to the full-pack fallback.
        assert "## Audio -> text -> analys -> rapport" in result
        assert "## Dokumentflöde med formulärkomplettering" in result
        assert "## Sektionerad insamling via formulärfält" in result


class TestSignalToRecipesDriftGuard:
    """`SIGNAL_TO_RECIPES` and `Pattern.recipe_sections` are two parallel
    inputs into `select_relevant_recipes`. A typo or rename on either
    side would silently stop narrowing the recipe pack — the selector
    would fall through to the full-pack fallback and the caller would
    never know. These tests pin the shared invariant: both inputs must
    reference `RecipeSection.section_id` values that actually exist.
    """

    def _known_section_keys(self) -> frozenset[str]:
        return frozenset(
            section.section_id for section in KNOWLEDGE_PACK_CREATE_RECIPES_SECTIONS
        )

    def test_every_signal_maps_to_a_real_recipe_section(self) -> None:
        known = self._known_section_keys()
        for signal, sections in SIGNAL_TO_RECIPES.items():
            assert sections, (
                f"SIGNAL_TO_RECIPES[{signal!r}] is empty — leave the entry "
                "off the map rather than map a signal to nothing"
            )
            unknown = frozenset(sections) - known
            assert not unknown, (
                f"SIGNAL_TO_RECIPES[{signal!r}] references unknown "
                f"section_id(s) {sorted(unknown)}; must be a subset of "
                f"{sorted(known)}"
            )

    def test_freeform_trigger_signals_exist_in_map(self) -> None:
        """`select_relevant_recipes` looks up these four signal keys via
        `.get(..., [])` when scanning freeform text. Removing one from
        the map would make the freeform path silently stop contributing
        recipes, so pin the contract here."""
        freeform_signal_keys = {
            "audio",
            "docx_document",
            "comparison",
            "structured_json",
        }
        missing = freeform_signal_keys - SIGNAL_TO_RECIPES.keys()
        assert not missing, (
            f"select_relevant_recipes references signal keys that are no "
            f"longer in SIGNAL_TO_RECIPES: {sorted(missing)}"
        )

    def test_pattern_recipe_sections_agree_on_section_universe(self) -> None:
        """Same invariant, pattern side: every `Pattern.recipe_sections`
        value is a real section_id. The pattern-registry suite already
        pins exact seeds, but this cross-module check catches the case
        where a section is renamed in recipes and the pattern seed
        happens to match the new name coincidentally."""
        known = self._known_section_keys()
        for pattern in PATTERN_REGISTRY.values():
            unknown = frozenset(pattern.recipe_sections) - known
            assert not unknown, (
                f"Pattern {pattern.id!r}: recipe_sections references "
                f"unknown section_id(s) {sorted(unknown)}"
            )

    def test_signal_and_pattern_sections_cover_same_section_universe(
        self,
    ) -> None:
        """The union of both sources must be a subset of the known
        sections — and at least one side must reference every dedicated
        section (today every one of them flows through at least one of
        the two paths, so a section added without a route is likely
        dead weight)."""
        known = self._known_section_keys()
        routed_via_signals: set[str] = set()
        for sections in SIGNAL_TO_RECIPES.values():
            routed_via_signals.update(sections)
        routed_via_patterns: set[str] = set()
        for pattern in PATTERN_REGISTRY.values():
            routed_via_patterns.update(pattern.recipe_sections)
        routed = routed_via_signals | routed_via_patterns
        # `golden_example` is always added by `select_relevant_recipes`
        # once any narrowing fires, so it has no explicit signal or
        # pattern route and is expected to be absent from `routed`.
        unroutable = known - routed - {"golden_example"}
        assert not unroutable, (
            f"Recipe sections {sorted(unroutable)} are not reachable via "
            "any signal or pattern — they would never activate the "
            "filtered pack and are dead weight"
        )
