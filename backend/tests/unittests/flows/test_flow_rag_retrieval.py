from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.flows.runtime.rag_retrieval import (
    RAG_RETRIEVAL_FAIL_CLOSED_STATUSES,
    RAG_RETRIEVAL_STATUSES,
    RagRetrievalDeps,
    retrieve_rag_chunks,
)


def _assistant(*, has_knowledge: bool) -> SimpleNamespace:
    return SimpleNamespace(
        has_knowledge=lambda: has_knowledge,
        collections=[],
        websites=[],
        integration_knowledge_list=[],
    )


@pytest.mark.asyncio
async def test_retrieve_rag_chunks_skips_blank_question_without_service_call():
    references_service = MagicMock()
    references_service.get_references = AsyncMock()

    chunks, metadata, diagnostics = await retrieve_rag_chunks(
        assistant=_assistant(has_knowledge=True),
        question="   ",
        run_id=uuid4(),
        step_order=1,
        deps=RagRetrievalDeps(
            references_service=references_service,
            rag_retrieval_timeout_seconds=30,
            rag_max_reference_sources=25,
            rag_max_chunks_per_source=5,
            logger=MagicMock(),
        ),
    )

    assert chunks == []
    assert metadata["status"] == "skipped_no_input"
    assert diagnostics == []
    references_service.get_references.assert_not_awaited()


@pytest.mark.asyncio
async def test_retrieve_rag_chunks_returns_error_diagnostic_on_exception():
    references_service = MagicMock()
    references_service.get_references = AsyncMock(side_effect=RuntimeError("boom"))
    logger = MagicMock()

    chunks, metadata, diagnostics = await retrieve_rag_chunks(
        assistant=_assistant(has_knowledge=True),
        question="hello",
        run_id=uuid4(),
        step_order=2,
        deps=RagRetrievalDeps(
            references_service=references_service,
            rag_retrieval_timeout_seconds=30,
            rag_max_reference_sources=25,
            rag_max_chunks_per_source=5,
            logger=logger,
        ),
    )

    assert chunks == []
    assert metadata["status"] == "error"
    assert metadata["error_code"] == "rag_retrieval_failed"
    assert diagnostics[0].code == "rag_retrieval_failed"
    logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_retrieve_rag_chunks_happy_path_builds_reference_metadata():
    source_a = uuid4()
    source_b = uuid4()
    chunk_a = SimpleNamespace(
        info_blob_id=source_a, info_blob_title="alpha", text="alpha"
    )
    chunk_b = SimpleNamespace(
        info_blob_id=source_b, info_blob_title="beta", text="beta"
    )
    datastore_result = SimpleNamespace(
        chunks=[chunk_a, chunk_b],
        no_duplicate_chunks=[chunk_a, chunk_b],
    )
    references_service = MagicMock()
    references_service.get_references = AsyncMock(return_value=datastore_result)
    references_service.get_reference_metadata = AsyncMock(
        return_value={
            str(source_a): {
                "source_title": "Beslut till underlag",
                "source_url": "https://kunskap.example.se/beslut/underlag",
                "source_kind": "website",
                "source_container_kind": "website",
                "source_container_name": "Kunskapsbanken",
                "source_container_id": "website-1",
            }
        }
    )

    chunks, metadata, diagnostics = await retrieve_rag_chunks(
        assistant=_assistant(has_knowledge=True),
        question="hello",
        run_id=uuid4(),
        step_order=1,
        deps=RagRetrievalDeps(
            references_service=references_service,
            rag_retrieval_timeout_seconds=30,
            rag_max_reference_sources=25,
            rag_max_chunks_per_source=5,
            logger=MagicMock(),
        ),
    )

    assert chunks == [chunk_a, chunk_b]
    assert metadata["status"] == "success"
    assert metadata["chunks_retrieved"] == 2
    assert metadata["unique_sources"] == 2
    assert metadata["tracking"]["retrieval_tracked"] is True
    assert metadata["tracking"]["prompt_context_inclusion_tracked"] is False
    assert metadata["tracking"]["citation_tracked"] is False
    assert metadata["tracking"]["material_influence_tracked"] is False
    assert metadata["references"][0]["usage_state"] == "retrieved_candidate"
    assert metadata["references"][0]["source_kind"] == "website"
    assert metadata["references"][0]["source_container_name"] == "Kunskapsbanken"
    assert diagnostics == []


@pytest.mark.asyncio
async def test_retrieve_rag_chunks_timeout_sets_timeout_metadata_and_diagnostic(
    monkeypatch,
):
    references_service = MagicMock()
    references_service.get_references = MagicMock(return_value=object())
    logger = MagicMock()
    wait_for = AsyncMock(side_effect=asyncio.TimeoutError)
    monkeypatch.setattr("eneo.flows.runtime.rag_retrieval.asyncio.wait_for", wait_for)

    chunks, metadata, diagnostics = await retrieve_rag_chunks(
        assistant=_assistant(has_knowledge=True),
        question="hello",
        run_id=uuid4(),
        step_order=2,
        deps=RagRetrievalDeps(
            references_service=references_service,
            rag_retrieval_timeout_seconds=0.0001,
            rag_max_reference_sources=25,
            rag_max_chunks_per_source=5,
            logger=logger,
        ),
    )

    assert chunks == []
    assert metadata["status"] == "timeout"
    assert metadata["error_code"] == "rag_retrieval_timeout"
    assert diagnostics[0].code == "rag_retrieval_timeout"
    wait_for.assert_awaited_once()
    logger.warning.assert_called_once()


def test_rag_retrieval_status_family_is_closed_and_complete() -> None:
    assert RAG_RETRIEVAL_STATUSES == frozenset(
        {
            "skipped_no_service",
            "skipped_no_knowledge",
            "skipped_no_input",
            "skipped_transcribe_only",
            "success",
            "no_chunks",
            "timeout",
            "error",
        }
    )
    assert RAG_RETRIEVAL_FAIL_CLOSED_STATUSES == RAG_RETRIEVAL_STATUSES - {
        "success",
        "skipped_transcribe_only",
    }


@pytest.mark.asyncio
async def test_retrieve_rag_chunks_records_zero_chunks_as_explicit_diagnostic() -> None:
    references_service = MagicMock()
    references_service.get_references = AsyncMock(
        return_value=SimpleNamespace(chunks=[], no_duplicate_chunks=[])
    )

    chunks, metadata, diagnostics = await retrieve_rag_chunks(
        assistant=_assistant(has_knowledge=True),
        question="hello",
        run_id=uuid4(),
        step_order=3,
        deps=RagRetrievalDeps(
            references_service=references_service,
            rag_retrieval_timeout_seconds=30,
            rag_max_reference_sources=25,
            rag_max_chunks_per_source=5,
            logger=MagicMock(),
        ),
    )

    assert chunks == []
    assert metadata["status"] == "no_chunks"
    assert metadata["attempted"] is True
    assert metadata["chunks_retrieved"] == 0
    assert metadata["error_code"] is None
    assert [(item.code, item.severity) for item in diagnostics] == [
        ("rag_retrieval_no_chunks", "warning")
    ]
