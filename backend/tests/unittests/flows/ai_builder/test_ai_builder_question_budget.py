"""Question-budget helper.

Build-plan intent → 0, `has_explicit_step_plan → 1`, everything else → 3.
Rich prompts must not receive FEWER questions than short prompts.
"""

from __future__ import annotations

import pytest

from eneo.flows.ai_builder import (
    ai_builder_discovery_decision_engine as decision_engine,
)
from eneo.flows.ai_builder.ai_builder_discovery_decision_engine import (
    compute_question_budget,
    has_explicit_step_plan,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage


def test_neutral_responses_spend_budget_once_per_user_requirement_question() -> None:
    conversation = [
        ConversationMessage(
            role="user",
            content="first output reply",
            metadata={
                "question_response": {"question_id": "final_output_mode"},
            },
        ),
        ConversationMessage(
            role="user",
            content="revised output reply",
            metadata={
                "question_response": {"question_id": "terminal_output"},
            },
        ),
        ConversationMessage(
            role="user",
            content="input reply",
            metadata={
                "question_response": {"question_id": "primary_runtime_input"},
            },
        ),
        ConversationMessage(
            role="user",
            content="schema selection",
            metadata={
                "question_response": {"question_id": "output_schema_conflict"},
            },
        ),
    ]

    assert decision_engine._answered_user_requirement_question_count(conversation) == 3


class TestComputeQuestionBudget:
    @pytest.mark.parametrize(
        "text",
        [
            pytest.param(
                "Vid körning laddar användaren upp en ljudfil och flödet transkriberar den.",
                id="executed-prompt-with-korning",
            ),
            pytest.param(
                "Användaren laddar upp en ljudfil och flödet transkriberar den.",
                id="executed-prompt-without-korning",
            ),
        ],
    )
    def test_executed_swedish_prompt_pair_keeps_question_budget(
        self, text: str
    ) -> None:
        assert compute_question_budget(text) == 3

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("Bygg planen!", id="bygg-planen"),
            pytest.param("BUILD THE PLAN!", id="build-the-plan"),
            pytest.param("Skapa—planen!", id="skapa-planen"),
            pytest.param("CREATE, THE PLAN!", id="create-the-plan"),
            pytest.param("Det stämmer!", id="det-stammer"),
            pytest.param("THAT IS CORRECT!", id="that-is-correct"),
            pytest.param("That—looks right!", id="that-looks-right"),
            pytest.param("Gå vidare!", id="ga-vidare"),
            pytest.param("GO, AHEAD!", id="go-ahead"),
            pytest.param("Fortsätt!", id="fortsatt"),
            pytest.param("CONTINUE!", id="continue"),
            pytest.param("KÖR!", id="kor"),
        ],
    )
    def test_supported_build_plan_intent_returns_zero(self, text: str) -> None:
        assert compute_question_budget(text) == 0

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param(
                "Användaren väljer språk för varje körning.",
                id="kor-inside-korning",
            ),
            pytest.param(
                "Beskriv hur flödet ska fortsätta efter ett fel.",
                id="fortsatt-inside-fortsatta",
            ),
            pytest.param(
                "Use continued validation for every run.",
                id="continue-inside-continued",
            ),
            pytest.param(
                "The designer will build the planner next.",
                id="build-the-plan-inside-build-the-planner",
            ),
        ],
    )
    def test_incidental_build_plan_substrings_return_three(self, text: str) -> None:
        assert compute_question_budget(text) == 3

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
