from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.assistants.references import ReferencesService
from intric.info_blobs.info_blob import InfoBlobChunkInDBWithScore
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


@pytest.mark.asyncio
async def test_get_references_skips_info_blob_hydration_when_disabled():
    info_blobs_repo = AsyncMock()
    datastore = AsyncMock()
    service = ReferencesService(info_blobs_repo=info_blobs_repo, datastore=datastore)
    chunks = [
        _create_chunk_with_score(0.9, uuid4()),
        _create_chunk_with_score(0.7, uuid4()),
    ]
    datastore.semantic_search.return_value = chunks
    collection = MagicMock()
    collection.embedding_model = MagicMock()

    result = await service.get_references(
        question="hello",
        collections=[collection],
        include_info_blobs=False,
    )

    assert result.chunks == chunks
    assert result.no_duplicate_chunks == chunks
    assert result.info_blobs == []
    info_blobs_repo.get.assert_not_called()


@pytest.mark.asyncio
async def test_get_references_hydrates_info_blobs_by_default():
    info_blobs_repo = AsyncMock()
    datastore = AsyncMock()
    service = ReferencesService(info_blobs_repo=info_blobs_repo, datastore=datastore)
    chunk = _create_chunk_with_score(0.9, uuid4())
    datastore.semantic_search.return_value = [chunk]
    collection = MagicMock()
    collection.embedding_model = MagicMock()
    info_blob = MagicMock()
    info_blob.model_dump.return_value = {
        "id": chunk.info_blob_id,
        "tenant_id": chunk.tenant_id,
        "created_at": None,
        "updated_at": None,
        "title": "title",
        "size": 1,
        "user_id": uuid4(),
        "group_id": uuid4(),
        "website_id": None,
        "integration_knowledge_id": None,
        "url": None,
        "embedding_model_id": uuid4(),
        "text": "body",
        "sharepoint_item_id": None,
    }
    info_blobs_repo.get.return_value = info_blob

    result = await service.get_references(
        question="hello",
        collections=[collection],
    )

    assert len(result.info_blobs) == 1
    info_blobs_repo.get.assert_awaited_once_with(chunk.info_blob_id)
