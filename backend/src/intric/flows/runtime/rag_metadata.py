from __future__ import annotations

from typing import Any


def build_chunk_snippet(text: str, *, max_chars: int = 200) -> str:
    normalized = text.strip()
    if len(normalized) <= max_chars:
        return normalized
    start = max((len(normalized) - max_chars) // 2, 0)
    return normalized[start : start + max_chars]


def build_rag_references(
    info_blob_chunks: list[Any],
    *,
    max_sources: int = 25,
    max_chunks_per_source: int = 5,
    snippet_chars: int = 200,
) -> tuple[list[dict[str, Any]], bool]:
    references_by_source: dict[str, dict[str, Any]] = {}

    for chunk in info_blob_chunks:
        info_blob_id = getattr(chunk, "info_blob_id", None)
        if info_blob_id is None:
            continue

        source_id = str(info_blob_id)
        entry = references_by_source.get(source_id)
        if entry is None:
            entry = {
                "id": source_id,
                "id_short": source_id[:8],
                "title": _truncate_title(getattr(chunk, "info_blob_title", None)),
                "hit_count": 0,
                "best_score": 0.0,
                "chunks": [],
            }
            references_by_source[source_id] = entry

        score_value = _safe_score(getattr(chunk, "score", 0.0))
        entry["hit_count"] += 1
        entry["best_score"] = max(entry["best_score"], score_value)

        if len(entry["chunks"]) >= max_chunks_per_source:
            continue

        chunk_text = str(getattr(chunk, "text", "") or "")
        entry["chunks"].append(
            {
                "chunk_no": int(getattr(chunk, "chunk_no", 0) or 0),
                "score": round(score_value, 4),
                "snippet": build_chunk_snippet(chunk_text, max_chars=snippet_chars),
            }
        )

    references = list(references_by_source.values())
    references.sort(
        key=lambda reference: (
            -int(reference["hit_count"]),
            -float(reference["best_score"]),
            str(reference["id"]),
        ),
    )
    references_truncated = len(references) > max_sources
    references = references[:max_sources]

    for reference in references:
        reference["best_score"] = round(float(reference["best_score"]), 4)
        reference["chunks"].sort(
            key=lambda chunk: (-float(chunk["score"]), int(chunk["chunk_no"])),
        )

    return references, references_truncated


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
