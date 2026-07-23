"""Confidence scoring for discovery signal inference.

Wraps the existing signal inference system with confidence scores so that
low-confidence signals can be flagged for confirmation rather than silently
accepted. This prevents over-questioning (asking about something the user
already implied) while catching genuine ambiguity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    StructuredQuestionAnswerMetadata,
    question_answer_from_metadata,
    question_answer_question_id,
)
from eneo.flows.ai_builder.ai_builder_discovery_signal_inference import (
    infer_answer_signals_from_text,
    normalize_signal_text,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)

Confidence = Literal["high", "medium", "low"]

# ``text`` is the intentionally broad fallback signal emitted for generic text
# input markers. Other canonical values carry enough semantic specificity to be
# treated as medium-confidence freeform evidence.
_GENERIC_SIGNAL_VALUES = frozenset({"text"})


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
        answer = question_answer_from_metadata(message.metadata)
        if answer is None:
            continue
        question_id = question_answer_question_id(answer)
        if question_id is None:
            continue
        structured_ids.add(question_id)
        for value in _structured_answer_values(answer):
            scored.append(
                ScoredSignal(
                    question_id=question_id,
                    value=value,
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
                confidence = _score_text_signal_confidence(value)
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


def _structured_answer_values(
    answer: StructuredQuestionAnswerMetadata,
) -> tuple[str, ...]:
    values: list[str] = []
    for raw_values in (answer.selected_values, answer.selected_option_ids):
        if raw_values is None:
            continue
        values.extend(str(value) for value in raw_values if value is not None)
    return tuple(value for value in values if value.strip())


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


def _score_text_signal_confidence(value: str) -> Confidence:
    """Score confidence for a text-inferred signal.

    Canonical-value scoring keeps equivalent Swedish and English matches equal.
    """
    if normalize_signal_text(value) in _GENERIC_SIGNAL_VALUES:
        return "low"

    return "medium"
