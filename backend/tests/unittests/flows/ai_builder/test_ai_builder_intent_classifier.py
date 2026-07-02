"""Tests for intent classification (Phase 4.3)."""

from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_interaction_utils import (
    looks_like_information_request,
)


class TestLooksLikeInformationRequest:
    # True positives — these are genuine questions
    def test_simple_question_sv(self):
        assert looks_like_information_request("Vad betyder transcribe_only?")

    def test_simple_question_en(self):
        assert looks_like_information_request("What does output_contract do?")

    def test_how_question(self):
        assert looks_like_information_request("Hur fungerar variabelreferenser?")

    def test_can_question(self):
        assert looks_like_information_request("Kan flödet hantera PDF?")

    # True negatives — these are build requests, not questions
    def test_build_request_with_question_mark(self):
        assert not looks_like_information_request(
            "Kan du bygga ett flöde som analyserar dokument?"
        )

    def test_proposal_mention(self):
        assert not looks_like_information_request("Can you show the proposal?")

    def test_step_mention(self):
        assert not looks_like_information_request("Lägg till ett steg?")

    def test_no_question_mark(self):
        assert not looks_like_information_request("Bygg ett flöde som transkriberar")

    def test_long_message(self):
        # Long messages are build requests, not info questions
        long = "A" * 250 + "?"
        assert not looks_like_information_request(long)

    # Edge cases
    def test_empty_string(self):
        assert not looks_like_information_request("")

    def test_just_question_mark(self):
        assert looks_like_information_request("?")

    # New: action-intent verbs should be false even with ?
    def test_action_verb_bygg(self):
        assert not looks_like_information_request("Bygg ett dokumentflöde?")

    def test_action_verb_skapa(self):
        assert not looks_like_information_request("Skapa en sammanfattning?")

    def test_action_verb_lagg_till(self):
        assert not looks_like_information_request("Lägg till transkribering?")

    def test_action_verb_create(self):
        assert not looks_like_information_request("Create a transcription flow?")

    def test_action_verb_add(self):
        assert not looks_like_information_request("Add a summary step?")

    def test_action_verb_build(self):
        assert not looks_like_information_request("Build me a document analyzer?")
