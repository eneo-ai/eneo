"""Default-surface domain-neutrality for AI Builder discovery questions.

AI Builder is a general-purpose flow builder. It supports specialty
flows — decision-support memos, tjänsteskrivelse drafting, remiss
processing — alongside procurement, onboarding, transcription,
extraction, comparison, template fill, and everything else the Flow
Capability Manifest can express. Specialty support means the builder
must be free to recognize specialty vocabulary in user input, describe
it in knowledge-pack copy, and serve it through its recipes.

What the builder must NOT do is assume specialty framing as the
default. The discovery flow asks the same seed questions to every
user, independent of scenario. Those seed questions, and the options
they offer, must stay domain-neutral so a procurement user is not
nudged toward decision-support framing before stating intent.

This module fences the discovery-question render surface: every option
label and description for every builder in
`ai_builder_discovery_questions`, in both Swedish and English. The
`QUESTION_CATALOG` render surface has the equivalent fence in
`test_question_catalog.py`. Render-surface fences are the *only*
lockdown that remains — recognizer tuples, knowledge-pack prose, and
benchmark cases are free to reference specialty vocabulary.
"""

from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_discovery_models import DiscoveryLanguage
from eneo.flows.ai_builder.ai_builder_discovery_questions import (
    comparison_scope_conflict_question,
    comparison_scope_question,
    document_material_scope_question,
    docx_output_mode_question,
    final_output_scope_question,
    final_pdf_type_question,
    flow_input_architecture_question,
    output_reader_question,
    pdf_generation_mode_question,
    post_processing_goal_question,
    primary_runtime_input_question,
    processing_scope_question,
    runtime_metadata_fields_question,
    terminal_output_question,
)

# Tokens that must not appear in the default-surface discovery questions
# (the seed questions shown before the builder has learned the user's
# scenario). Substring matches (not whole-word) so compounds like
# `beslutsunderlagsmall` or `handläggaren` are caught too. Specialty
# vocabulary is welcome in recognizer tuples, knowledge-pack examples,
# and benchmark cases — it is banned here because the default options
# must be neutral.
_BANNED_DEFAULT_RENDER_TOKENS: tuple[str, ...] = (
    "tjänsteskriv",
    "beslutsunderlag",
    "beslutsstöd",
    "beslutsförslag",
    "nämnden",
    "nämnder",
    "remiss",
    "handläggar",
    "ärendenummer",
    "decision support",
    "decision-support",
    "kommunärende",
    "municipal case",
    "ärendedokument",
    "ärendeunderlag",
    "kommunala handlingar",
    "huvudärende",
    "ärendepaket",
    "ärendeintag",
    "ärendesammanfattning",
    "ärende åt gången",
    "diarienummer",
    "case number",
)


class TestDiscoveryQuestionsRenderNeutrality:
    """The discovery-question builders return `DiscoveryQuestionSuggestion`
    values whose labels and descriptions reach the user at runtime in
    both Swedish and English, before any scenario has been established.
    A future edit that surfaces specialty framing in those default
    options must fail here before landing.
    """

    @staticmethod
    def _all_rendered_strings() -> list[tuple[str, str, str]]:
        """Return ``(builder_name, locale, rendered_blob)`` for every
        (builder, locale) combination in the discovery-questions module.
        """
        builders = (
            ("processing_scope", processing_scope_question),
            ("primary_runtime_input", primary_runtime_input_question),
            ("flow_input_architecture", flow_input_architecture_question),
            ("document_material_scope", document_material_scope_question),
            ("post_processing_goal", post_processing_goal_question),
            ("comparison_scope_conflict", comparison_scope_conflict_question),
            ("comparison_scope", comparison_scope_question),
            ("terminal_output", terminal_output_question),
            ("docx_output_mode", docx_output_mode_question),
            ("output_reader", output_reader_question),
            ("final_output_scope", final_output_scope_question),
            ("runtime_metadata_fields", runtime_metadata_fields_question),
            ("final_pdf_type", final_pdf_type_question),
            ("pdf_generation_mode", pdf_generation_mode_question),
        )
        locales: tuple[DiscoveryLanguage, ...] = ("sv", "en")
        rendered: list[tuple[str, str, str]] = []
        for name, builder in builders:
            for locale in locales:
                suggestion = builder(locale)
                parts: list[str] = [suggestion.question]
                for option in suggestion.options:
                    parts.append(option.label)
                    parts.append(option.description)
                rendered.append((name, locale, "\n".join(parts)))
        return rendered

    @pytest.mark.parametrize("locale", ["sv", "en"])
    def test_comparison_conflict_reuses_canonical_options(
        self, locale: DiscoveryLanguage
    ) -> None:
        canonical = comparison_scope_question(locale)
        conflict = comparison_scope_conflict_question(locale)

        assert conflict.options == canonical.options
        assert conflict.exposure == canonical.exposure

    def test_no_specialty_framing_in_default_discovery_questions(self) -> None:
        offenders: list[tuple[str, str, str]] = []
        for builder_name, locale, blob in self._all_rendered_strings():
            lowered = blob.casefold()
            for token in _BANNED_DEFAULT_RENDER_TOKENS:
                if token.casefold() in lowered:
                    offenders.append((builder_name, locale, token))
        assert not offenders, (
            "Specialty framing leaked into default discovery-question "
            "options:\n"
            + "\n".join(
                f"  {builder_name} [{locale}] [{token}]"
                for builder_name, locale, token in offenders
            )
        )
