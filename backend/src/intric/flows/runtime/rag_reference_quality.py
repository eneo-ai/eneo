from __future__ import annotations

import re
from typing import Any

WORD_PATTERN = re.compile(r"\w+", re.UNICODE)
URL_PATTERN = re.compile(r"https?://|www\.", re.IGNORECASE)
NAVIGATION_TERMS = {
    "home",
    "menu",
    "contact",
    "login",
    "logga",
    "cookies",
    "privacy",
    "search",
    "sitemap",
    "breadcrumb",
    "startsida",
    "kontakt",
}


def choose_display_chunk(
    chunks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    best_chunk: dict[str, Any] | None = None
    best_score: float | None = None
    fallback_chunk: dict[str, Any] | None = None

    for chunk in chunks:
        text = chunk.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        quality = evaluate_chunk_quality(text)
        candidate_score = quality["signal_score"]
        if fallback_chunk is None:
            fallback_chunk = {
                "display_snippet": chunk.get("snippet") or text.strip(),
                "display_chunk_no": chunk.get("chunk_no"),
                "snippet_quality": quality["snippet_quality"],
                "quality_flags": quality["quality_flags"],
                "boilerplate_likelihood": quality["boilerplate_likelihood"],
                "display_selection_reason": "fallback_first_chunk",
            }
        if best_score is None or candidate_score > best_score:
            best_score = candidate_score
            best_chunk = {
                "display_snippet": chunk.get("snippet") or text.strip(),
                "display_chunk_no": chunk.get("chunk_no"),
                "snippet_quality": quality["snippet_quality"],
                "quality_flags": quality["quality_flags"],
                "boilerplate_likelihood": quality["boilerplate_likelihood"],
                "display_selection_reason": "highest_signal_chunk",
            }

    return best_chunk or fallback_chunk


def evaluate_chunk_quality(text: str) -> dict[str, Any]:
    normalized = " ".join(text.split())
    lowered = normalized.lower()
    words = WORD_PATTERN.findall(lowered)
    word_count = len(words)
    sentence_count = sum(normalized.count(marker) for marker in ".!?")
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    link_hits = len(URL_PATTERN.findall(normalized))
    navigation_hits = sum(1 for term in NAVIGATION_TERMS if term in lowered)
    short_line_hits = sum(1 for line in lines if len(WORD_PATTERN.findall(line)) <= 3)
    repeated_ratio = _repetition_ratio(words)

    flags: list[str] = []
    penalty = 0.0

    if word_count < 18:
        flags.append("low_information_density")
        penalty += 0.35
    if sentence_count == 0 or (lines and sentence_count / max(len(lines), 1) < 0.35):
        flags.append("low_sentence_density")
        penalty += 0.25
    if link_hits >= 2:
        flags.append("high_link_density")
        penalty += 0.2
    if navigation_hits >= 2:
        flags.append("navigation_terms")
        penalty += 0.3
    if lines and short_line_hits / len(lines) >= 0.6:
        flags.append("short_line_navigation_pattern")
        penalty += 0.2
    if repeated_ratio >= 0.35:
        flags.append("repetitive_template_text")
        penalty += 0.15

    signal_score = max(0.0, round(1.0 - penalty + min(word_count, 120) / 1000, 4))
    boilerplate_likelihood = round(min(1.0, penalty), 4)
    if signal_score >= 0.75:
        snippet_quality = "high"
    elif signal_score >= 0.45:
        snippet_quality = "medium"
    else:
        snippet_quality = "low"

    return {
        "signal_score": signal_score,
        "snippet_quality": snippet_quality,
        "quality_flags": flags,
        "boilerplate_likelihood": boilerplate_likelihood,
    }


def _repetition_ratio(words: list[str]) -> float:
    if not words:
        return 0.0
    unique_words = len(set(words))
    return max(0.0, 1 - (unique_words / len(words)))
