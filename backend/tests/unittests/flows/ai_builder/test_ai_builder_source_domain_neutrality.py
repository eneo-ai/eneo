"""Lockdown: banned specialty tokens must not appear in any string
literal inside the AI Builder source tree, nor in the rendered output
of the `ai_builder_discovery_questions` question builders.

The AI Builder is general-purpose — it helps users build procurement,
onboarding, transcription, extraction, comparison, support-triage, and
template-fill flows. Swedish decision-support / case-management
vocabulary AND the English `decision support` compound must not appear
in any detection tuple, heuristic phrase list, prompt fragment,
knowledge-pack section, or code comment inside
`backend/src/intric/flows/ai_builder/`.

User-visible labels are pinned in three places:
- `TestDomainNeutrality::test_no_banned_tokens_in_any_rendered_template`
  in `test_question_catalog.py` covers the `QUESTION_CATALOG` registry.
- `TestDiscoveryQuestionsRenderNeutrality` below covers the
  `ai_builder_discovery_questions` builders, which produce the
  user-facing options/labels/descriptions the discovery flow asks at
  runtime.
- `TestSourceDomainNeutrality` below scans every source file for
  banned-token substrings as a belt-and-braces source-level guard.

Any future change that reintroduces specialty vocabulary fails here
before landing.
"""

from __future__ import annotations

from pathlib import Path

from intric.flows.ai_builder.ai_builder_discovery_models import DiscoveryLanguage
from intric.flows.ai_builder.ai_builder_discovery_questions import (
    comparison_scope_conflict_question,
    comparison_scope_question,
    document_kind_question,
    document_material_scope_question,
    docx_output_mode_question,
    final_output_mode_question,
    final_output_scope_question,
    final_pdf_type_question,
    flow_input_architecture_question,
    input_material_mode_question,
    output_reader_question,
    pdf_generation_mode_question,
    processing_scope_question,
    runtime_metadata_fields_question,
    structured_analysis_need_question,
)

# Banned specialty tokens for the source-wide scan. Substring matches
# (not whole-word) so compounds like `beslutsunderlagsmall` or
# `handläggaren` are caught too. Tokens that are safe to appear in
# input-recognizer tuples but unsafe in user-facing rendered output
# live in `_BANNED_RENDER_ONLY_TOKENS` below. The render-surface tests
# combine both lists; the source-wide scan uses only this one.
_BANNED_SPECIALTY_TOKENS: tuple[str, ...] = (
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
    "guldexempel",
    "kommunanalys",
    "ärendeanalys",
    "ansvarig_namnd",
    "juridiska risker",
    "ekonomiska konsekvenser",
    "ärendedokument",
    "ärendeunderlag",
    "kommunala handlingar",
    "huvudärende",
    "ärendepaket",
    "ärendeintag",
    "ärendesammanfattning",
    "ärende åt gången",
)

# Render-surface-only banned tokens. These are safe to appear in
# input-recognizer tuples (where the builder must still understand the
# user's words) but must never appear in user-facing rendered output —
# question labels, option descriptions, knowledge-pack copy, benchmark
# prompts. Catalog-render coverage lives in `test_question_catalog.py`.
_BANNED_RENDER_ONLY_TOKENS: tuple[str, ...] = (
    "diarienummer",
    "case number",
)

_AI_BUILDER_SRC = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "src"
    / "intric"
    / "flows"
    / "ai_builder"
)

_BENCHMARK_CASES_FILE = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "integration"
    / "flows"
    / "ai_builder"
    / "benchmark"
    / "cases.py"
)


class TestSourceDomainNeutrality:
    def test_no_banned_tokens_in_any_ai_builder_source_file(self) -> None:
        assert _AI_BUILDER_SRC.is_dir(), (
            f"AI Builder source directory not found: {_AI_BUILDER_SRC}"
        )

        offenders: list[tuple[str, int, str, str]] = []
        for path in sorted(_AI_BUILDER_SRC.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            lowered = text.casefold()
            for token in _BANNED_SPECIALTY_TOKENS:
                if token.casefold() not in lowered:
                    continue
                for line_no, line in enumerate(text.splitlines(), start=1):
                    if token.casefold() in line.casefold():
                        offenders.append(
                            (
                                str(
                                    path.relative_to(
                                        _AI_BUILDER_SRC.parent.parent.parent
                                    )
                                ),
                                line_no,
                                token,
                                line.strip(),
                            )
                        )

        assert not offenders, (
            "Banned specialty tokens found in AI Builder source:\n"
            + "\n".join(
                f"  {path}:{line_no} [{token}] {snippet}"
                for path, line_no, token, snippet in offenders
            )
        )

    def test_no_banned_tokens_in_benchmark_cases(self) -> None:
        """Benchmark prompts are the worked-example set the evaluation
        harness feeds to the planner. A specialty token in a benchmark
        prompt teaches the LLM that specialty framing is normal, even
        when the source tree is clean. Fence benchmarks alongside source.
        """
        assert _BENCHMARK_CASES_FILE.is_file(), (
            f"Benchmark cases file not found: {_BENCHMARK_CASES_FILE}"
        )
        text = _BENCHMARK_CASES_FILE.read_text(encoding="utf-8")
        offenders: list[tuple[int, str, str]] = []
        lowered = text.casefold()
        for token in _BANNED_SPECIALTY_TOKENS + _BANNED_RENDER_ONLY_TOKENS:
            if token.casefold() not in lowered:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if token.casefold() in line.casefold():
                    offenders.append((line_no, token, line.strip()))
        assert not offenders, (
            "Banned specialty tokens found in benchmark cases.py:\n"
            + "\n".join(
                f"  {_BENCHMARK_CASES_FILE.name}:{line_no} [{token}] {snippet}"
                for line_no, token, snippet in offenders
            )
        )


class TestDiscoveryQuestionsRenderNeutrality:
    """The discovery-question builders return `DiscoveryQuestionSuggestion`
    values whose labels/descriptions reach the user at runtime in both
    Swedish and English. A future edit that reintroduces a banned token
    into any option copy or question prompt must fail here before
    landing — this guards the render surface complementarily to the
    source-level scan above and to the `QUESTION_CATALOG` render
    lockdown in `test_question_catalog.py`.
    """

    @staticmethod
    def _all_rendered_strings() -> list[tuple[str, str, str]]:
        """Return ``(builder_name, locale, rendered_blob)`` for every
        (builder, locale) combination in the discovery-questions module.
        """
        builders = (
            ("processing_scope", processing_scope_question),
            ("input_material_mode", input_material_mode_question),
            ("flow_input_architecture", flow_input_architecture_question),
            ("document_kind", document_kind_question),
            ("document_material_scope", document_material_scope_question),
            ("comparison_scope_conflict", comparison_scope_conflict_question),
            ("comparison_scope", comparison_scope_question),
            ("final_output_mode", final_output_mode_question),
            ("docx_output_mode", docx_output_mode_question),
            ("output_reader", output_reader_question),
            ("final_output_scope", final_output_scope_question),
            ("runtime_metadata_fields", runtime_metadata_fields_question),
            ("structured_analysis_need", structured_analysis_need_question),
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

    def test_no_banned_tokens_in_any_rendered_discovery_question(self) -> None:
        offenders: list[tuple[str, str, str]] = []
        for builder_name, locale, blob in self._all_rendered_strings():
            lowered = blob.casefold()
            for token in _BANNED_SPECIALTY_TOKENS + _BANNED_RENDER_ONLY_TOKENS:
                if token.casefold() in lowered:
                    offenders.append((builder_name, locale, token))
        assert not offenders, (
            "Banned specialty tokens found in rendered discovery questions:\n"
            + "\n".join(
                f"  {builder_name} [{locale}] [{token}]"
                for builder_name, locale, token in offenders
            )
        )
