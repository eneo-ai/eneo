"""Question-budget helper.

`has_explicit_step_plan → 1`, everything else → 3. Rich prompts must not
receive FEWER questions than short prompts.
"""

from __future__ import annotations

import pytest

from intric.flows.ai_builder.ai_builder_discovery_decision_engine import (
    compute_question_budget,
    has_explicit_step_plan,
)


class TestComputeQuestionBudget:
    def test_explicit_step_plan_in_swedish_returns_one(self) -> None:
        assert (
            compute_question_budget(
                "Steg 1: ladda upp PDF. Steg 2: extrahera JSON. Steg 3: generera DOCX."
            )
            == 1
        )

    def test_explicit_step_plan_in_english_returns_one(self) -> None:
        assert (
            compute_question_budget(
                "step 1 transcribe, step 2 summarize, step 3 output DOCX"
            )
            == 1
        )

    def test_three_step_phrase_returns_one(self) -> None:
        assert compute_question_budget("please build a 3-step flow") == 1
        assert compute_question_budget("a three steps pipeline") == 1

    def test_rich_prompt_without_explicit_plan_returns_three(self) -> None:
        rich_prompt = (
            "Users upload a PDF case document. The flow should extract decision"
            " fields, produce a summary with risks and opportunities, and"
            " generate a DOCX output with the analyst's name."
        )
        assert compute_question_budget(rich_prompt) == 3

    def test_short_prompt_returns_three(self) -> None:
        assert compute_question_budget("summarize my document") == 3

    def test_empty_text_returns_three(self) -> None:
        assert compute_question_budget("") == 3

    def test_rich_prompt_does_not_get_fewer_questions_than_short(self) -> None:
        short = compute_question_budget("hi")
        rich = compute_question_budget(
            "Upload a PDF, extract case metadata and JSON fields, compare"
            " against policy, output a DOCX decision-support memo."
        )
        assert rich >= short


class TestHasExplicitStepPlan:
    @pytest.mark.parametrize(
        "text",
        [
            "steg 1 och steg 2",
            "step 1 upload, step 2 transcribe",
            "a 3-step flow",
            "three steps please",
            "tre steg",
            "Step 1: transcribe. Step 2: summarize.",
            "STEG 1 OCH STEG 2 — ALLT I VERSALER",
        ],
    )
    def test_positive(self, text: str) -> None:
        assert has_explicit_step_plan(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "summarize my document",
            "Upload a PDF and generate a DOCX output",
            "step by step, explain the flow",
            "please describe this stegvis",
            "a stepwise analysis, but no numbered plan",
        ],
    )
    def test_negative(self, text: str) -> None:
        assert has_explicit_step_plan(text) is False
