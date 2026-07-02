from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from eneo.flows.runtime.rag_reference_quality import choose_display_chunk
from eneo.flows.source_display import (
    format_source_container_label,
    format_source_display_name,
)


def _empty_chunk_payloads() -> list[dict[str, Any]]:
    return []


def _empty_metadata() -> dict[str, Any]:
    return {}


def build_chunk_snippet(text: str, *, max_chars: int = 200) -> str:
    normalized = text.strip()
    if len(normalized) <= max_chars:
        return normalized
    start = max((len(normalized) - max_chars) // 2, 0)
    return normalized[start : start + max_chars]


@dataclass
class _RagReference:
    id: str
    id_short: str
    title: str | None
    source_title_raw: str | None
    source_order: int
    matched_chunk_count: int = 0
    best_score: float = 0.0
    chunks: list[dict[str, Any]] = field(default_factory=_empty_chunk_payloads)
    display_candidates: list[dict[str, Any]] = field(
        default_factory=_empty_chunk_payloads
    )
    metadata: dict[str, Any] = field(default_factory=_empty_metadata)
    usage_state: str = "retrieved_candidate"

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "id_short": self.id_short,
            "title": self.title,
            "source_title_raw": self.source_title_raw,
            "matched_chunk_count": self.matched_chunk_count,
            "best_score": round(self.best_score, 4),
            "chunks": self.chunks,
            "usage_state": self.usage_state,
        }
        payload.update(self.metadata)
        return payload


def build_rag_references(
    info_blob_chunks: list[Any],
    *,
    source_metadata_by_id: Mapping[str, Mapping[str, object]] | None = None,
    max_sources: int = 25,
    max_chunks_per_source: int = 5,
    snippet_chars: int = 200,
) -> tuple[list[dict[str, Any]], bool]:
    references_by_source: dict[str, _RagReference] = {}

    for chunk_index, chunk in enumerate(info_blob_chunks):
        info_blob_id = getattr(chunk, "info_blob_id", None)
        if info_blob_id is None:
            continue

        source_id = str(info_blob_id)
        entry = references_by_source.get(source_id)
        if entry is None:
            source_metadata = (
                source_metadata_by_id.get(source_id) if source_metadata_by_id else None
            )
            raw_reference_title = (
                source_metadata.get("source_title")
                if source_metadata is not None
                else None
            ) or getattr(chunk, "info_blob_title", None)
            reference_title = _truncate_title(raw_reference_title)
            entry = _RagReference(
                id=source_id,
                id_short=source_id[:8],
                title=reference_title,
                source_title_raw=reference_title,
                source_order=chunk_index,
            )
            if source_metadata is not None:
                _attach_source_metadata(entry, source_metadata)
            references_by_source[source_id] = entry

        score_value = _safe_score(getattr(chunk, "score", 0.0))
        entry.matched_chunk_count += 1
        entry.best_score = max(entry.best_score, score_value)

        chunk_text = str(getattr(chunk, "text", "") or "")
        chunk_snippet = build_chunk_snippet(chunk_text, max_chars=snippet_chars)
        if not chunk_snippet.strip():
            continue

        chunk_payload = {
            "chunk_no": int(getattr(chunk, "chunk_no", 0) or 0),
            "score": round(score_value, 4),
            "snippet": chunk_snippet,
            "text": chunk_text,
        }
        entry.display_candidates.append(chunk_payload)

        if len(entry.chunks) >= max_chunks_per_source:
            continue

        entry.chunks.append(
            {
                "chunk_no": chunk_payload["chunk_no"],
                "score": chunk_payload["score"],
                "snippet": chunk_payload["snippet"],
            }
        )

    references = list(references_by_source.values())
    references.sort(
        key=lambda reference: (
            -reference.matched_chunk_count,
            -reference.best_score,
            reference.source_order,
        ),
    )
    references_truncated = len(references) > max_sources
    references = references[:max_sources]

    reference_payloads: list[dict[str, Any]] = []
    for reference in references:
        reference.chunks.sort(key=_chunk_sort_key)
        payload = reference.to_payload()
        display_chunk = choose_display_chunk(reference.display_candidates)
        if display_chunk is not None:
            payload.update(display_chunk)
        reference_payloads.append(payload)

    return reference_payloads, references_truncated


def _chunk_sort_key(chunk: dict[str, Any]) -> tuple[float, int]:
    return (-float(chunk["score"]), int(chunk["chunk_no"]))


def _safe_score(score: Any) -> float:
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        return 0.0
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


def _attach_source_metadata(
    entry: _RagReference,
    source_metadata: Mapping[str, object],
) -> None:
    source_title = _truncate_title(source_metadata.get("source_title"))
    if source_title:
        entry.title = source_title
        entry.source_title_raw = source_title
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
                entry.metadata["source_container_label"] = (
                    format_source_container_label(entry.to_payload())
                )
