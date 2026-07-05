"""Tests for confidence-scored signal inference (Phase 4.1)."""

from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_signal_confidence import (
    has_low_confidence_signals,
    high_confidence_signals,
    score_conversation_signals,
)


class TestSignalConfidence:
    def test_structured_answers_are_high_confidence(self):
        conversation = [
            ConversationMessage(
                role="user",
                content="Dokument",
                metadata={
                    "question_answer": {
                        "question_id": "primary_runtime_input",
                        "selected_option_ids": ["documents"],
                        "selected_values": ["documents"],
                    },
                },
            ),
        ]
        signals = score_conversation_signals(conversation)
        doc_signals = [s for s in signals if s.question_id == "primary_runtime_input"]
        assert len(doc_signals) >= 1
        assert all(s.confidence == "high" for s in doc_signals)
        assert all(s.source == "structured_answer" for s in doc_signals)

    def test_freeform_text_gets_medium_or_low(self):
        conversation = [
            ConversationMessage(
                role="user",
                content="jag vill analysera pdf dokument",
            ),
        ]
        signals = score_conversation_signals(
            conversation,
            freeform_text="jag vill analysera pdf dokument",
        )
        text_signals = [s for s in signals if s.source == "freeform_text"]
        assert len(text_signals) >= 1
        assert all(s.confidence in ("medium", "low") for s in text_signals)

    def test_structured_answer_overrides_text_inference(self):
        conversation = [
            ConversationMessage(
                role="user",
                content="Avtal och kontrakt",
                metadata={
                    "question_answer": {
                        "question_id": "document_kind",
                        "selected_option_ids": ["contracts_agreements"],
                        "selected_values": ["contracts_agreements"],
                    },
                },
            ),
        ]
        signals = score_conversation_signals(
            conversation,
            freeform_text="avtal och kontrakt",
        )
        # Should only have high-confidence structured answer, not duplicate text inference
        doc_kind = [s for s in signals if s.question_id == "document_kind"]
        assert all(s.source == "structured_answer" for s in doc_kind)

    def test_has_low_confidence_detects_weak_signals(self):
        conversation = [
            ConversationMessage(
                role="user",
                content="single file please",
            ),
        ]
        signals = score_conversation_signals(
            conversation,
            freeform_text="single file please",
        )
        # "single" and "file" are common words → low confidence
        if signals:
            low = [s for s in signals if s.confidence == "low"]
            assert has_low_confidence_signals(signals) == (len(low) > 0)

    def test_high_confidence_signals_filter(self):
        conversation = [
            ConversationMessage(
                role="user",
                content="Ett ärende",
                metadata={
                    "question_answer": {
                        "question_id": "processing_scope",
                        "selected_option_ids": ["single_case"],
                        "selected_values": ["single_case"],
                    },
                },
            ),
        ]
        signals = score_conversation_signals(conversation)
        high = high_confidence_signals(signals)
        assert "processing_scope" in high
        assert "single_case" in high["processing_scope"]

    def test_sorted_by_confidence(self):
        conversation = [
            ConversationMessage(
                role="user",
                content="Dokument",
                metadata={
                    "question_answer": {
                        "question_id": "primary_runtime_input",
                        "selected_option_ids": ["documents"],
                        "selected_values": ["documents"],
                    },
                },
            ),
            ConversationMessage(
                role="user",
                content="jag vill jämföra leverantörsavtal",
            ),
        ]
        signals = score_conversation_signals(
            conversation,
            freeform_text="jag vill jämföra leverantörsavtal",
        )
        if len(signals) >= 2:
            # First signal should be high confidence (structured)
            assert signals[0].confidence == "high"
