from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.assistants.references import ReferencesService
from eneo.info_blobs.info_blob import InfoBlobChunkInDBWithScore, InfoBlobInDB
from tests.fixtures import TEST_UUID


def _create_chunk_with_score(score: float, info_blob_id: str = TEST_UUID):
    return InfoBlobChunkInDBWithScore(
        info_blob_id=info_blob_id,
        score=score,
        user_id=1,
        id=TEST_UUID,
        chunk_no=1,
        text="chunk",
        group_id=1,
        embedding=[1, 2, 3],
        tenant_id=TEST_UUID,
        info_blob_title="title",
    )


def test_remove_duplicate_chunk_keep_highest_score_one_info_blob():
    service = ReferencesService(AsyncMock(), AsyncMock())

    chunks = [
        _create_chunk_with_score(0.9),
        _create_chunk_with_score(0.3),
        _create_chunk_with_score(0.1),
    ]

    pruned_chunks = service._get_info_blob_chunks_without_duplicates(chunks)

    assert pruned_chunks == [_create_chunk_with_score(0.9)]


def test_remove_duplicate_chunks_multiple_info_blobs():
    service = ReferencesService(AsyncMock(), AsyncMock())

    blob_2_id = uuid4()
    blob_3_id = uuid4()

    chunks = [
        _create_chunk_with_score(0.9),
        _create_chunk_with_score(0.7, blob_2_id),
        _create_chunk_with_score(0.3),
        _create_chunk_with_score(0.25, blob_2_id),
        _create_chunk_with_score(0.1),
        _create_chunk_with_score(0.001, blob_3_id),
    ]

    pruned_chunks = service._get_info_blob_chunks_without_duplicates(chunks)

    assert pruned_chunks == [
        _create_chunk_with_score(0.9),
        _create_chunk_with_score(0.7, blob_2_id),
        _create_chunk_with_score(0.001, blob_3_id),
    ]


@pytest.mark.parametrize(
    ("num_questions", "expected_answer"),
    (
        (1, "Question 0\nAnswer 0\nnext question"),
        (2, "Question 0\nAnswer 0\nQuestion 1\nAnswer 1\nnext question"),
        (0, "next question"),
    ),
)
def test_concatenate_session_and_question(num_questions: int, expected_answer: str):
    def get_questions(num_questions: int):
        questions = []
        for i in range(num_questions):
            question = MagicMock()
            question.question = f"Question {i}"
            question.answer = f"Answer {i}"
            questions.append(question)

        return questions

    questions = get_questions(num_questions)
    session = MagicMock()
    session.questions = questions

    service = ReferencesService(AsyncMock(), AsyncMock())
    concatenated_session = service._concatenate_conversation("next question", session)
    assert concatenated_session == expected_answer


def test_concatenate_session_is_null():
    service = ReferencesService(AsyncMock(), AsyncMock())
    concatenated_session = service._concatenate_conversation("next question", None)
    assert concatenated_session == "next question"


def _service_with_datastore():
    datastore = MagicMock()
    datastore.semantic_search = AsyncMock(return_value=[])
    return ReferencesService(AsyncMock(), datastore), datastore


def _patch_min_score(monkeypatch, min_score):
    monkeypatch.setattr(
        "eneo.assistants.references.get_settings",
        lambda: MagicMock(inject_knowledge_min_score=min_score),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("version", (1, 2))
async def test_inject_retrieval_applies_configured_relevance_floor(
    monkeypatch, version
):
    _patch_min_score(monkeypatch, 0.3)
    service, datastore = _service_with_datastore()

    await service._query_datastore_if_groups_or_websites(
        "question",
        collections=[MagicMock(embedding_model=MagicMock())],
        websites=[],
        num_chunks=10,
        version=version,
    )

    assert datastore.semantic_search.await_args.kwargs["min_score"] == 0.3


@pytest.mark.asyncio
async def test_relevance_floor_is_off_when_unset(monkeypatch):
    _patch_min_score(monkeypatch, None)
    service, datastore = _service_with_datastore()

    await service._query_datastore_if_groups_or_websites(
        "question",
        collections=[MagicMock(embedding_model=MagicMock())],
        websites=[],
        num_chunks=10,
        version=2,
    )

    assert datastore.semantic_search.await_args.kwargs["min_score"] is None


@pytest.mark.asyncio
async def test_info_blob_references_hydrate_original_availability_once():
    blob_ids = [uuid4(), uuid4()]
    repository = AsyncMock()
    repository.get_by_ids.return_value = [
        InfoBlobInDB(
            id=blob_ids[0],
            embedding_model_id=uuid4(),
            user_id=uuid4(),
            tenant_id=uuid4(),
            size=10,
            source_id=uuid4(),
            version_state="active",
            text="available",
        ),
        InfoBlobInDB(
            id=blob_ids[1],
            embedding_model_id=uuid4(),
            user_id=uuid4(),
            tenant_id=uuid4(),
            size=12,
            source_id=uuid4(),
            version_state="active",
            text="unavailable",
        ),
    ]

    async def hydrate(blobs):
        blobs[0].original_available = True
        blobs[1].original_available = False

    repository.hydrate_original_availability.side_effect = hydrate
    service = ReferencesService(repository, AsyncMock())

    result = await service._get_info_blobs_from_chunks(
        [
            _create_chunk_with_score(0.9, blob_ids[0]),
            _create_chunk_with_score(0.8, blob_ids[1]),
        ]
    )

    repository.get_by_ids.assert_awaited_once_with(blob_ids)
    repository.get.assert_not_called()
    repository.hydrate_original_availability.assert_awaited_once_with(result)
    assert [blob.original_available for blob in result] == [True, False]


@pytest.mark.asyncio
async def test_info_blob_references_skip_repository_for_empty_chunks():
    repository = AsyncMock()
    service = ReferencesService(repository, AsyncMock())

    assert await service._get_info_blobs_from_chunks([]) == []

    repository.get_by_ids.assert_not_awaited()
    repository.hydrate_original_availability.assert_not_awaited()
