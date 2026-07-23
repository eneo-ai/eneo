"""Tests for confidence-scored signal inference (Phase 4.1)."""

from __future__ import annotations

import pytest

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

    @pytest.mark.parametrize(
        ("swedish_text", "english_text", "question_id", "value", "confidence"),
        [
            pytest.param(
                "flera filer",
                "multiple files",
                "document_material_scope",
                "multiple_documents_case",
                "medium",
                id="multiple-files",
            ),
            pytest.param(
                "flera underlagsfiler",
                "multiple source files",
                "document_material_scope",
                "multiple_documents_case",
                "medium",
                id="multiple-source-files",
            ),
            pytest.param(
                "flera pdf",
                "multiple pdf",
                "document_material_scope",
                "multiple_documents_case",
                "medium",
                id="multiple-pdf",
            ),
            pytest.param(
                "klistra in",
                "paste as text",
                "primary_runtime_input",
                "text",
                "low",
                id="generic-text-input",
            ),
        ],
    )
    def test_matched_swedish_and_english_prompts_score_equivalently(
        self,
        swedish_text: str,
        english_text: str,
        question_id: str,
        value: str,
        confidence: str,
    ) -> None:
        pair_confidences: list[str] = []
        for text in (swedish_text, english_text):
            signals = score_conversation_signals([], freeform_text=text)
            matching_signals = [
                signal
                for signal in signals
                if signal.question_id == question_id and signal.value == value
            ]
            assert len(matching_signals) == 1
            pair_confidences.append(matching_signals[0].confidence)

        assert pair_confidences == [confidence, confidence]
        if confidence == "low":
            assert has_low_confidence_signals(
                score_conversation_signals([], freeform_text=swedish_text)
            )

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
        signals = score_conversation_signals([], freeform_text="klistra in")

        assert any(
            signal.question_id == "primary_runtime_input"
            and signal.value == "text"
            and signal.confidence == "low"
            for signal in signals
        )
        assert has_low_confidence_signals(signals)

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
