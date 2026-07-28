from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from eneo.flows.domain.rag_evidence import (
    RetrievedKnowledgeEvidence,
    RetrievedPassage,
    RetrievedSource,
)
from eneo.flows.domain.rag_evidence_policy import FlowRagEvidencePolicy
from eneo.flows.runtime.rag_reference_quality import choose_display_chunk
from eneo.flows.source_display import (
    format_source_container_label,
    format_source_display_name,
)
from eneo.info_blobs.info_blob import InfoBlobChunkInDBWithScore

DISPLAY_SNIPPET_CHARS = 200


def build_chunk_snippet(text: str, *, max_chars: int = DISPLAY_SNIPPET_CHARS) -> str:
    """Bounded preview for the knowledge-trace list, not the recorded passage."""
    normalized = text.strip()
    if len(normalized) <= max_chars:
        return normalized
    start = max((len(normalized) - max_chars) // 2, 0)
    return normalized[start : start + max_chars]


def _empty_chunks() -> list[InfoBlobChunkInDBWithScore]:
    return []


def _empty_metadata() -> dict[str, str]:
    return {}


@dataclass
class _SourceAccumulator:
    source_id: str
    title: str | None
    source_order: int
    matched_chunk_count: int = 0
    best_score: float = 0.0
    chunks: list[InfoBlobChunkInDBWithScore] = field(default_factory=_empty_chunks)
    metadata: dict[str, str] = field(default_factory=_empty_metadata)


def build_retrieved_knowledge_evidence(
    info_blob_chunks: Sequence[InfoBlobChunkInDBWithScore],
    *,
    source_metadata_by_id: Mapping[str, Mapping[str, object]] | None = None,
    policy: FlowRagEvidencePolicy,
) -> RetrievedKnowledgeEvidence:
    """Record every retrieved source, with passage detail bounded by policy.

    Source identity is never dropped: a step that retrieved from 400 documents
    yields 400 entries. Only the verbatim passage text is bounded, and every
    bound that bites is reported as a count rather than a flag.
    """
    accumulators: dict[str, _SourceAccumulator] = {}

    for chunk_index, chunk in enumerate(info_blob_chunks):
        source_id = str(chunk.info_blob_id)
        entry = accumulators.get(source_id)
        if entry is None:
            source_metadata = (
                source_metadata_by_id.get(source_id) if source_metadata_by_id else None
            )
            raw_title = (
                source_metadata.get("source_title")
                if source_metadata is not None
                else None
            ) or chunk.info_blob_title
            entry = _SourceAccumulator(
                source_id=source_id,
                title=_truncate_title(raw_title),
                source_order=chunk_index,
            )
            if source_metadata is not None:
                _collect_source_metadata(entry, source_metadata)
            accumulators[source_id] = entry

        entry.matched_chunk_count += 1
        entry.best_score = max(entry.best_score, _safe_score(chunk.score))
        entry.chunks.append(chunk)

    ordered = sorted(
        accumulators.values(),
        key=lambda entry: (
            -entry.matched_chunk_count,
            -entry.best_score,
            entry.source_order,
        ),
    )

    remaining_step_bytes = policy.max_recorded_passage_bytes_per_step
    sources: list[RetrievedSource] = []

    for source_index, entry in enumerate(ordered):
        passages: list[RetrievedPassage] = []
        if source_index < policy.max_sources_with_recorded_passages:
            for chunk in _passage_candidates(
                entry.chunks, limit=policy.max_recorded_passages_per_source
            ):
                retrieved_text = chunk.text.strip()
                allowance = min(
                    len(retrieved_text.encode("utf-8")),
                    policy.max_recorded_passage_bytes,
                    remaining_step_bytes,
                )
                # A candidate too large for what remains is truncated to fit
                # rather than skipped, and an exhausted budget skips this
                # candidate without abandoning smaller ones behind it.
                passage = (
                    RetrievedPassage.record(
                        chunk_no=chunk.chunk_no,
                        score=round(_safe_score(chunk.score), 4),
                        retrieved_text=retrieved_text,
                        max_bytes=allowance,
                    )
                    if allowance > 0
                    else None
                )
                if passage is None:
                    continue
                passages.append(passage)
                remaining_step_bytes -= passage.recorded_bytes

        sources.append(
            _build_source(
                entry,
                passages=passages,
                display_candidates=entry.chunks,
            )
        )

    return RetrievedKnowledgeEvidence(sources=sources)


def _passage_candidates(
    chunks: Sequence[InfoBlobChunkInDBWithScore],
    *,
    limit: int,
) -> list[InfoBlobChunkInDBWithScore]:
    """Highest-scoring passages first, keeping identical repeats distinct."""
    recordable = [chunk for chunk in chunks if chunk.text.strip()]
    recordable.sort(key=lambda chunk: (-_safe_score(chunk.score), chunk.chunk_no))
    return recordable[: max(0, limit)]


def _build_source(
    entry: _SourceAccumulator,
    *,
    passages: list[RetrievedPassage],
    display_candidates: Sequence[InfoBlobChunkInDBWithScore],
) -> RetrievedSource:
    display = choose_display_chunk(
        [
            {
                "chunk_no": chunk.chunk_no,
                "snippet": build_chunk_snippet(chunk.text),
                "text": chunk.text,
            }
            for chunk in display_candidates
        ]
    )
    metadata = entry.metadata
    return RetrievedSource(
        id=entry.source_id,
        id_short=entry.source_id[:8],
        title=entry.title,
        source_title=metadata.get("source_title"),
        source_title_raw=entry.title,
        source_display_name=metadata.get("source_display_name"),
        source_url=metadata.get("source_url"),
        source_kind=metadata.get("source_kind"),
        source_container_kind=metadata.get("source_container_kind"),
        source_container_name=metadata.get("source_container_name"),
        source_container_name_raw=metadata.get("source_container_name_raw"),
        source_container_label=metadata.get("source_container_label"),
        source_container_id=metadata.get("source_container_id"),
        matched_chunk_count=entry.matched_chunk_count,
        recorded_passage_count=len(passages),
        best_score=round(entry.best_score, 4),
        passages=passages,
        display_snippet=_display_value(display, "display_snippet"),
        display_chunk_no=_display_chunk_no(display),
        display_selection_reason=_display_value(display, "display_selection_reason"),
        snippet_quality=_display_value(display, "snippet_quality"),
        quality_flags=_display_flags(display),
        boilerplate_likelihood=_display_likelihood(display),
    )


def _display_value(display: dict[str, Any] | None, key: str) -> str | None:
    if display is None:
        return None
    value = display.get(key)
    return value if isinstance(value, str) else None


def _display_chunk_no(display: dict[str, Any] | None) -> int | None:
    if display is None:
        return None
    value = display.get("display_chunk_no")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _display_flags(display: dict[str, Any] | None) -> list[str]:
    if display is None:
        return []
    value = display.get("quality_flags")
    if not isinstance(value, list):
        return []
    return [flag for flag in cast(list[object], value) if isinstance(flag, str)]


def _display_likelihood(display: dict[str, Any] | None) -> float | None:
    if display is None:
        return None
    value = display.get("boilerplate_likelihood")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _safe_score(score: float) -> float:
    numeric = float(score)
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        return 0.0
    return numeric


def _truncate_title(title: object, *, max_chars: int = 200) -> str | None:
    if title is None:
        return None
    text = str(title).strip()
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _collect_source_metadata(
    entry: _SourceAccumulator,
    source_metadata: Mapping[str, object],
) -> None:
    source_title = _truncate_title(source_metadata.get("source_title"))
    if source_title:
        entry.title = source_title
        entry.metadata["source_title"] = source_title
        entry.metadata["source_display_name"] = format_source_display_name(source_title)
    for key in (
        "source_url",
        "source_kind",
        "source_container_kind",
        "source_container_name",
        "source_container_id",
    ):
        value = source_metadata.get(key)
        if isinstance(value, str) and value.strip():
            stripped = value.strip()
            entry.metadata[key] = stripped
            if key == "source_container_name":
                entry.metadata["source_container_name_raw"] = stripped
                container_label = format_source_container_label(dict(entry.metadata))
                if container_label is not None:
                    entry.metadata["source_container_label"] = container_label
