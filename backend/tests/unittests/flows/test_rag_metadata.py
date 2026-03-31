from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from intric.flows.runtime.rag_metadata import build_chunk_snippet, build_rag_references


def test_build_chunk_snippet_uses_interior_slice_for_long_text():
    text = "a" * 100 + "MIDDLE" + "b" * 120
    snippet = build_chunk_snippet(text, max_chars=40)

    assert len(snippet) == 40
    assert "MIDDLE" in snippet


def test_build_rag_references_aggregates_hits_and_caps_chunks():
    source_id = uuid4()
    chunks = [
        SimpleNamespace(
            info_blob_id=source_id,
            info_blob_title="Source 1",
            chunk_no=2,
            score=0.8,
            text="chunk two",
        ),
        SimpleNamespace(
            info_blob_id=source_id,
            info_blob_title="Source 1",
            chunk_no=1,
            score=0.95,
            text="chunk one",
        ),
        SimpleNamespace(
            info_blob_id=source_id,
            info_blob_title="Source 1",
            chunk_no=3,
            score=0.5,
            text="chunk three",
        ),
    ]

    references, truncated = build_rag_references(
        chunks,
        max_sources=25,
        max_chunks_per_source=2,
    )

    assert truncated is False
    assert len(references) == 1
    assert references[0]["id"] == str(source_id)
    assert references[0]["hit_count"] == 3
    assert references[0]["best_score"] == 0.95
    assert len(references[0]["chunks"]) == 2
    assert references[0]["chunks"][0]["chunk_no"] == 1


def test_build_rag_references_truncates_sources_and_handles_invalid_scores():
    chunks = []
    for index in range(4):
        source_id = uuid4()
        chunks.append(
            SimpleNamespace(
                info_blob_id=source_id,
                info_blob_title=f"Source {index}",
                chunk_no=1,
                score="nan" if index == 0 else 0.9 - (index * 0.1),
                text=f"source {index}",
            )
        )

    references, truncated = build_rag_references(
        chunks,
        max_sources=3,
        max_chunks_per_source=5,
    )

    assert truncated is True
    assert len(references) == 3
    assert references[0]["best_score"] >= references[1]["best_score"] >= references[2]["best_score"]


def test_build_rag_references_enriches_source_metadata_when_available():
    source_id = uuid4()
    references, truncated = build_rag_references(
        [
            SimpleNamespace(
                info_blob_id=source_id,
                info_blob_title="https://kunskap.example.se/beslut/underlag",
                chunk_no=1,
                score=0.82,
                text="relevant chunk",
            )
        ],
        source_metadata_by_id={
            str(source_id): {
                "source_title": "Beslut till underlag",
                "source_url": "https://kunskap.example.se/beslut/underlag",
                "source_kind": "website",
                "source_container_kind": "website",
                "source_container_name": "Kunskapsbanken",
                "source_container_id": "website-1",
            }
        },
    )

    assert truncated is False
    assert references[0]["title"] == "Beslut till underlag"
    assert references[0]["source_title"] == "Beslut till underlag"
    assert references[0]["source_url"] == "https://kunskap.example.se/beslut/underlag"
    assert references[0]["source_kind"] == "website"
    assert references[0]["source_container_name"] == "Kunskapsbanken"
    assert references[0]["usage_state"] == "retrieved_candidate"
