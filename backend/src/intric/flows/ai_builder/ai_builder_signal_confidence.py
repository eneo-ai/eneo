"""Confidence scoring for discovery signal inference.

Wraps the existing signal inference system with confidence scores so that
low-confidence signals can be flagged for confirmation rather than silently
accepted. This prevents over-questioning (asking about something the user
already implied) while catching genuine ambiguity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from intric.flows.ai_builder.ai_builder_discovery_signal_inference import (
    infer_answer_signals_from_text,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage

Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class ScoredSignal:
    question_id: str
    value: str
    confidence: Confidence
    source: Literal["structured_answer", "freeform_text", "flow_default"]


def score_conversation_signals(
    conversation: list[ConversationMessage],
    freeform_text: str = "",
) -> list[ScoredSignal]:
    """Score all discovered signals by confidence.

    - Structured answers (from UI buttons): high confidence
    - Freeform text inference: medium or low confidence

    Returns signals sorted by confidence (high first).
    """
    scored: list[ScoredSignal] = []

    # 1. Extract structured answers only (from question_answer metadata)
    structured_ids: set[str] = set()
    for message in conversation:
        if message.role != "user":
            continue
        metadata = message.metadata if isinstance(message.metadata, dict) else None
        if metadata is None:
            continue
        qa = metadata.get("question_answer")
        if not isinstance(qa, dict):
            continue
        qa_dict = cast(dict[str, Any], qa)
        question_id = qa_dict.get("question_id")
        if not isinstance(question_id, str):
            continue
        structured_ids.add(question_id)
        for key in ("selected_values", "selected_option_ids"):
            raw = qa_dict.get(key)
            if isinstance(raw, list):
                for v in cast(list[object], raw):
                    if isinstance(v, str) and v.strip():
                        scored.append(
                            ScoredSignal(
                                question_id=question_id,
                                value=v,
                                confidence="high",
                                source="structured_answer",
                            )
                        )

    # 2. Freeform text inference — medium/low depending on specificity
    if freeform_text:
        text_signals = infer_answer_signals_from_text(freeform_text)
        for question_id, values in text_signals.items():
            if question_id in structured_ids:
                continue  # Already have a structured answer — skip
            for value in values:
                confidence = _score_text_signal_confidence(
                    question_id,
                    value,
                    freeform_text,
                )
                scored.append(
                    ScoredSignal(
                        question_id=question_id,
                        value=value,
                        confidence=confidence,
                        source="freeform_text",
                    )
                )

    # Sort: high first, then medium, then low
    priority = {"high": 0, "medium": 1, "low": 2}
    scored.sort(key=lambda s: priority[s.confidence])
    return scored


def has_low_confidence_signals(signals: list[ScoredSignal]) -> bool:
    """Check if any signals have low confidence (needs clarification)."""
    return any(s.confidence == "low" for s in signals)


def high_confidence_signals(
    signals: list[ScoredSignal],
) -> dict[str, set[str]]:
    """Extract only high+medium confidence signals as answer dict."""
    result: dict[str, set[str]] = {}
    for s in signals:
        if s.confidence in ("high", "medium"):
            result.setdefault(s.question_id, set()).add(s.value)
    return result


def _score_text_signal_confidence(
    question_id: str,
    value: str,
    text: str,
) -> Confidence:
    """Score confidence for a text-inferred signal.

    Specific multi-word matches are medium confidence.
    Generic single-word matches are low confidence.
    """
    # Count how many words from the value appear in the text
    value_words = set(value.replace("_", " ").split())
    text_words = set(text.casefold().split())
    overlap = value_words & text_words

    if len(overlap) >= 2:
        return "medium"

    # Single-word match with very common words → low confidence
    common_words = {"text", "data", "file", "output", "input", "single", "multiple"}
    if overlap and overlap.issubset(common_words):
        return "low"

    return "medium"
