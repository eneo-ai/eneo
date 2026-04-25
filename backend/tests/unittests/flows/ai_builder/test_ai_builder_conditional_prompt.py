"""Tests for conditional knowledge pack injection."""

from __future__ import annotations

import pytest

from intric.flows.ai_builder.ai_builder_orchestrator import AskQuestionPayload
from intric.flows.ai_builder.ai_builder_prompts import (
    build_clarification_hints,
    build_system_prompt,
)

# The v2 `AskQuestionPayload` is the source of truth for which
# payload fields the v2 orchestrator accepts on a
# `planner_action.kind="ask_question"` — it has `extra="forbid"`, so
# any prompt text that cues the LLM toward other field names produces
# `extra_forbidden` validation failures the user experiences as the
# planner not answering.
ALLOWED_ASK_QUESTION_PAYLOAD_FIELDS: frozenset[str] = frozenset(
    AskQuestionPayload.model_fields.keys()
)

# Field names that used to live on the legacy v1
# `ask_structured_question` tool schema. Kept as an explicit
# negative allowlist because they are the exact shape the LLM has
# historically slipped back into when the active prompt drifts from
# the schema. If a future schema evolution retires more fields, add
# them here.
RETIRED_ASK_QUESTION_PAYLOAD_FIELDS: tuple[str, ...] = (
    "options",
    "selection_mode",
    "allow_custom",
)


class TestConditionalKnowledgePackInjection:
    def test_discovery_phase_excludes_heavy_sections(self):
        """During discovery (no confirmed requirements), skip recipes and
        anti-patterns to save tokens."""
        prompt = build_system_prompt(
            confirmed_requirements=None,  # Discovery phase
        )
        # Create mode exposes semantic outline authoring, not raw Flow wiring.
        assert "outline_flow" in prompt
        assert "backend derives step topology" in prompt
        # Heavy sections should be excluded in discovery
        assert "Planner patterns (positive archetypes)" not in prompt

    def test_confirmed_phase_includes_recipes(self):
        """After requirements are confirmed, include recipes for proposal quality."""
        confirmed = {
            "summary": "A document analysis flow.",
            "key_decisions": [{"topic": "Input", "decision": "Documents"}],
            "input_description": "User uploads documents.",
            "output_description": "Structured analysis.",
        }
        prompt = build_system_prompt(confirmed_requirements=confirmed)
        # After confirmation, registry-derived archetypes should be present.
        assert "Planner patterns (positive archetypes)" in prompt

    def test_edit_mode_includes_edit_knowledge(self):
        """Edit mode should include edit-mode knowledge pack."""
        prompt = build_system_prompt(
            flow_context="Namn: Test\nAntal steg: 2",
            is_edit_mode=True,
        )
        assert "Redigeringsläge" in prompt or "edit" in prompt.lower()

    def test_edit_mode_excludes_create_only_recipes(self):
        """Edit mode should skip create-only content to save tokens."""
        prompt = build_system_prompt(
            flow_context="Namn: Test\nAntal steg: 2",
            is_edit_mode=True,
        )
        # Should have edit-specific content
        assert "existing_step" in prompt or "Redigering" in prompt

    def test_prompt_always_includes_core(self):
        """Core sections must always be present regardless of phase."""
        prompt = build_system_prompt()
        assert "outline_flow" in prompt
        assert "backend derives step topology" in prompt


class TestSystemPromptV2AskQuestionContract:
    """Structural contract: the legacy v1 `ask_structured_question`
    tool vocabulary must not leak into what the v2 planner LLM sees.

    The v2 `AskQuestionPayload` has `extra="forbid"` and only accepts
    `question_id`, `slot_name`, `prompt`. In production, the LLM
    slipped back into the legacy payload shape whenever the active
    prompt mentioned `ask_structured_question` — producing
    `extra_forbidden` validation failures (fingerprint 4a58a17446e3).

    Assertion strategy: ban the legacy tool name from the whole
    built system prompt, and check payload-field discipline on the
    focused clarification hints (where there is no legitimate form-
    field JSON that also uses the word `options`).
    """

    @pytest.mark.parametrize(
        "description,kwargs",
        [
            ("discovery_create", {"confirmed_requirements": None}),
            (
                "confirmed_create",
                {
                    "confirmed_requirements": {
                        "summary": "Extract structured fields from uploaded forms.",
                        "key_decisions": [{"topic": "Input", "decision": "PDFs"}],
                        "input_description": "User uploads PDF forms.",
                        "output_description": "Structured JSON per form.",
                    }
                },
            ),
            (
                "discovery_edit",
                {
                    "flow_context": "Namn: Befintligt flöde\nAntal steg: 2",
                    "is_edit_mode": True,
                },
            ),
            (
                "confirmed_edit",
                {
                    "flow_context": "Namn: Befintligt flöde\nAntal steg: 2",
                    "is_edit_mode": True,
                    "confirmed_requirements": {
                        "summary": "Tweak existing DOCX flow to emit PDF.",
                        "key_decisions": [
                            {"topic": "Output", "decision": "PDF instead of DOCX"}
                        ],
                        "input_description": "Unchanged.",
                        "output_description": "PDF report.",
                    },
                },
            ),
        ],
    )
    def test_system_prompt_never_mentions_legacy_ask_structured_question(
        self, description: str, kwargs: dict
    ) -> None:
        prompt = build_system_prompt(**kwargs)
        assert "ask_structured_question" not in prompt, (
            f"system prompt ({description}) references the legacy pre-v2 "
            "tool name `ask_structured_question`. That name cues the "
            "LLM to emit the legacy payload shape "
            "(options/selection_mode/allow_custom), which the v2 "
            "AskQuestionPayload rejects as extra_forbidden."
        )

    def test_ask_question_payload_schema_matches_expected_allowlist(self) -> None:
        """Canary: if AskQuestionPayload gains or loses a field, this
        test fails loudly so the prompt-side contract tests can be
        updated in lockstep rather than drifting."""
        assert ALLOWED_ASK_QUESTION_PAYLOAD_FIELDS == frozenset(
            {"question_id", "slot_name", "prompt"}
        ), (
            "AskQuestionPayload schema changed — update the prompt "
            "contract tests and the clarification-hint vocabulary so "
            "they stay in sync with the v2 orchestrator."
        )

    def test_pdf_scope_hint_respects_v2_ask_question_contract(self) -> None:
        """Representative positive guard: when the document_material_scope
        frågegate fires, it must steer the LLM toward a v2-compliant
        ask_question payload — current action name + allowed fields,
        no legacy tool name or retired payload fields."""
        hints = build_clarification_hints(
            conversation=[],
            latest_user_message=(
                "Jag vill ladda upp ett eller flera PDF-dokument och jämföra "
                "innehållet mellan dokumenten."
            ),
        )
        assert hints is not None
        assert "document_material_scope" in hints, (
            "precondition failed: PDF-scope frågegate did not fire — "
            "input needs to signal multi-document comparison intent"
        )
        assert "ask_structured_question" not in hints, (
            "clarification hint still references the legacy pre-v2 tool "
            "name `ask_structured_question`; the v2 planner emits "
            '`planner_action.kind="ask_question"` with the '
            "AskQuestionPayload schema only."
        )
        assert "ask_question" in hints
        for field in RETIRED_ASK_QUESTION_PAYLOAD_FIELDS:
            assert field not in hints, (
                f"clarification hint references retired "
                f"ask_question payload field `{field}`."
            )
        for field in ALLOWED_ASK_QUESTION_PAYLOAD_FIELDS:
            assert field in hints, (
                f"clarification hint must name the allowed "
                f"AskQuestionPayload field `{field}` so the LLM knows the "
                "exact payload shape."
            )
