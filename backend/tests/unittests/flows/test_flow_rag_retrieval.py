from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.assistants.references import ReferencesService
from eneo.collections.domain.collection import Collection
from eneo.flows.domain.rag_evidence_policy import FlowRagEvidencePolicy
from eneo.flows.runtime.rag_retrieval import (
    RAG_RETRIEVAL_FAIL_CLOSED_STATUSES,
    RAG_RETRIEVAL_STATUSES,
    RagRetrievalDeps,
    retrieve_rag_chunks,
)
from eneo.info_blobs.info_blob import InfoBlobChunkInDBWithScore
from eneo.services.service import DatastoreResult
from tests.fixtures import (
    TEST_COLLECTION,
    TEST_EMBEDDING_MODEL,
    TEST_EMBEDDING_MODEL_ADA,
    TEST_USER,
    retrieved_info_blob_chunk,
)


def _assistant(
    *,
    has_knowledge: bool,
    collections: list[Collection] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        has_knowledge=lambda: has_knowledge,
        collections=collections if collections is not None else [],
        websites=[],
        integration_knowledge_list=[],
    )


def _deps(references_service: object, *, logger: object) -> RagRetrievalDeps:
    return RagRetrievalDeps(
        references_service=references_service,  # type: ignore[arg-type]
        rag_retrieval_timeout_seconds=30,
        evidence_policy=FlowRagEvidencePolicy(),
        logger=logger,  # type: ignore[arg-type]
    )


def _datastore_result(
    chunks: list[InfoBlobChunkInDBWithScore],
    *,
    embedding_model: object = TEST_EMBEDDING_MODEL,
) -> DatastoreResult:
    return DatastoreResult(
        chunks=chunks,
        no_duplicate_chunks=chunks,
        info_blobs=[],
        embedding_model_id=getattr(embedding_model, "id", None),
        embedding_model_name=getattr(embedding_model, "name", None),
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
        deps=_deps(references_service, logger=MagicMock()),
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
        deps=_deps(references_service, logger=logger),
    )

    assert chunks == []
    assert metadata["status"] == "error"
    assert metadata["error_code"] == "rag_retrieval_failed"
    assert diagnostics[0].code == "rag_retrieval_failed"
    logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_retrieve_rag_chunks_records_passages_and_source_counts():
    source_a = uuid4()
    source_b = uuid4()
    chunk_a = retrieved_info_blob_chunk(
        info_blob_id=source_a,
        info_blob_title="alpha",
        chunk_no=1,
        text="alpha stycke",
        score=0.9,
    )
    chunk_b = retrieved_info_blob_chunk(
        info_blob_id=source_b,
        info_blob_title="beta",
        chunk_no=1,
        text="beta stycke",
        score=0.8,
    )
    references_service = MagicMock()
    references_service.get_references = AsyncMock(
        return_value=_datastore_result([chunk_a, chunk_b])
    )
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
        deps=_deps(references_service, logger=MagicMock()),
    )

    assert chunks == [chunk_a, chunk_b]
    assert metadata["status"] == "success"
    assert metadata["chunks_retrieved"] == 2
    assert metadata["unique_sources"] == 2
    assert metadata["sources_with_recorded_passages"] == 2
    assert metadata["passages_recorded"] == 2
    assert metadata["passages_truncated"] == 0
    assert metadata["recorded_passage_bytes"] > 0
    assert metadata["recorded_passage_content"] == "source_text_verbatim"
    assert "references_truncated" not in metadata
    assert metadata["tracking"]["retrieval_tracked"] is True
    assert metadata["tracking"]["prompt_context_inclusion_tracked"] is False
    assert metadata["references"][0]["usage_state"] == "retrieved_candidate"
    assert metadata["references"][0]["source_kind"] == "website"
    assert metadata["references"][0]["source_container_name"] == "Kunskapsbanken"
    assert metadata["references"][0]["passages"][0]["text"] == "alpha stycke"
    assert diagnostics == []


@pytest.mark.asyncio
async def test_retrieve_rag_chunks_records_the_embedding_model_retrieval_reported():
    references_service = MagicMock()
    references_service.get_references = AsyncMock(return_value=_datastore_result([]))

    _, metadata, _ = await retrieve_rag_chunks(
        assistant=_assistant(has_knowledge=True, collections=[TEST_COLLECTION]),
        question="hello",
        run_id=uuid4(),
        step_order=1,
        deps=_deps(references_service, logger=MagicMock()),
    )

    assert metadata["embedding_model_status"] == "recorded"
    assert metadata["embedding_model"] == {
        "id": str(TEST_EMBEDDING_MODEL.id),
        "name": TEST_EMBEDDING_MODEL.name,
    }


@pytest.mark.asyncio
async def test_retrieve_rag_chunks_reports_no_model_when_retrieval_reports_none():
    references_service = MagicMock()
    references_service.get_references = AsyncMock(
        return_value=_datastore_result([], embedding_model=None)
    )

    _, metadata, _ = await retrieve_rag_chunks(
        assistant=_assistant(has_knowledge=True),
        question="hello",
        run_id=uuid4(),
        step_order=1,
        deps=_deps(references_service, logger=MagicMock()),
    )

    assert metadata["embedding_model"] is None
    assert metadata["embedding_model_status"] == "not_reported"


def test_retrieval_service_owns_the_embedding_model_precedence() -> None:
    website_collection = Collection.create(
        space_id=uuid4(),
        name="other_collection",
        embedding_model=TEST_EMBEDDING_MODEL_ADA,
        user=TEST_USER,
    )

    assert (
        ReferencesService.select_embedding_model(
            [TEST_COLLECTION, website_collection], [], []
        )
        is TEST_EMBEDDING_MODEL
    )
    assert ReferencesService.select_embedding_model([], [], []) is None


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
        deps=_deps(references_service, logger=logger),
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
    references_service.get_references = AsyncMock(return_value=_datastore_result([]))

    chunks, metadata, diagnostics = await retrieve_rag_chunks(
        assistant=_assistant(has_knowledge=True),
        question="hello",
        run_id=uuid4(),
        step_order=3,
        deps=_deps(references_service, logger=MagicMock()),
    )

    assert chunks == []
    assert metadata["status"] == "no_chunks"
    assert metadata["attempted"] is True
    assert metadata["chunks_retrieved"] == 0
    assert metadata["references"] == []
    assert metadata["sources_with_recorded_passages"] == 0
    assert metadata["passages_recorded"] == 0
    assert metadata["error_code"] is None
    assert [(item.code, item.severity) for item in diagnostics] == [
        ("rag_retrieval_no_chunks", "warning")
    ]


@pytest.mark.asyncio
async def test_recorded_passages_never_reach_the_logger() -> None:
    passage = "Personuppgift: Anna Andersson, 19700101-1234."
    references_service = MagicMock()
    references_service.get_references = AsyncMock(
        return_value=_datastore_result(
            [
                retrieved_info_blob_chunk(
                    info_blob_id=uuid4(),
                    info_blob_title="Journal",
                    chunk_no=1,
                    text=passage,
                    score=0.9,
                )
            ]
        )
    )
    references_service.get_reference_metadata = AsyncMock(
        side_effect=RuntimeError("metadata down")
    )
    logger = MagicMock()

    _, metadata, _ = await retrieve_rag_chunks(
        assistant=_assistant(has_knowledge=True),
        question="hello",
        run_id=uuid4(),
        step_order=1,
        deps=_deps(references_service, logger=logger),
    )

    assert metadata["references"][0]["passages"][0]["text"] == passage
    logged = "".join(str(call) for call in logger.mock_calls)
    assert passage not in logged
    assert "Anna Andersson" not in logged
