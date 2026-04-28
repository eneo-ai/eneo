from __future__ import annotations

from typing import Any, Mapping

from intric.flows.runtime.rag_reference_quality import choose_display_chunk
from intric.flows.source_display import (
    format_source_container_label,
    format_source_display_name,
)


def build_chunk_snippet(text: str, *, max_chars: int = 200) -> str:
    normalized = text.strip()
    if len(normalized) <= max_chars:
        return normalized
    start = max((len(normalized) - max_chars) // 2, 0)
    return normalized[start : start + max_chars]


def build_rag_references(
    info_blob_chunks: list[Any],
    *,
    source_metadata_by_id: Mapping[str, Mapping[str, Any]] | None = None,
    max_sources: int = 25,
    max_chunks_per_source: int = 5,
    snippet_chars: int = 200,
) -> tuple[list[dict[str, Any]], bool]:
    references_by_source: dict[str, dict[str, Any]] = {}

    for chunk_index, chunk in enumerate(info_blob_chunks):
        info_blob_id = getattr(chunk, "info_blob_id", None)
        if info_blob_id is None:
            continue

        source_id = str(info_blob_id)
        entry = references_by_source.get(source_id)
        if entry is None:
            source_metadata = (
                source_metadata_by_id.get(source_id, {})
                if source_metadata_by_id
                else {}
            )
            reference_title = _truncate_title(
                source_metadata.get("source_title")
                or getattr(chunk, "info_blob_title", None)
            )
            entry = {
                "id": source_id,
                "id_short": source_id[:8],
                "title": reference_title,
                "source_title_raw": reference_title,
                "matched_chunk_count": 0,
                "best_score": 0.0,
                "chunks": [],
                "_display_candidates": [],
                "_source_order": chunk_index,
                "usage_state": "retrieved_candidate",
            }
            _attach_source_metadata(entry, source_metadata)
            references_by_source[source_id] = entry

        score_value = _safe_score(getattr(chunk, "score", 0.0))
        entry["matched_chunk_count"] += 1
        entry["best_score"] = max(entry["best_score"], score_value)

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
        entry["_display_candidates"].append(chunk_payload)

        if len(entry["chunks"]) >= max_chunks_per_source:
            continue

        entry["chunks"].append(
            {
                "chunk_no": chunk_payload["chunk_no"],
                "score": chunk_payload["score"],
                "snippet": chunk_payload["snippet"],
            }
        )

    references = list(references_by_source.values())
    references.sort(
        key=lambda reference: (
            -int(reference["matched_chunk_count"]),
            -float(reference["best_score"]),
            int(reference["_source_order"]),
        ),
    )
    references_truncated = len(references) > max_sources
    references = references[:max_sources]

    for reference in references:
        reference["best_score"] = round(float(reference["best_score"]), 4)
        reference.pop("_source_order", None)
        reference["chunks"].sort(
            key=_chunk_sort_key,
        )
        display_chunk = choose_display_chunk(reference.pop("_display_candidates", []))
        if display_chunk is not None:
            reference.update(display_chunk)

    return references, references_truncated


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


def _truncate_title(title: Any, *, max_chars: int = 200) -> str | None:
    if title is None:
        return None
    text = str(title).strip()
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _attach_source_metadata(
    entry: dict[str, Any],
    source_metadata: Mapping[str, Any],
) -> None:
    source_title = _truncate_title(source_metadata.get("source_title"))
    if source_title:
        entry["source_title"] = source_title
        entry["source_title_raw"] = source_title
        entry["source_display_name"] = format_source_display_name(source_title)
        entry["title"] = source_title
    for key in (
        "source_url",
        "source_kind",
        "source_container_kind",
        "source_container_name",
        "source_container_id",
    ):
        value = source_metadata.get(key)
        if isinstance(value, str) and value.strip():
            entry[key] = value.strip()
            if key == "source_container_name":
                entry["source_container_name_raw"] = value.strip()
                entry["source_container_label"] = format_source_container_label(entry)
