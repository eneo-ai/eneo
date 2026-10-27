"""The rerank step in semantic search.

Without a spec the search is the code that shipped before: one repository
call with the caller's limit, ``min_score`` and ``autocut`` as before. With a
spec the vector search fetches K candidates, the reranker scores the spec's
query against each candidate's text, and all K come back in reranker order
carrying reranker scores, followed by any requested chunks beyond K. A
reranker failure falls back to the old result.
"""

import asyncio
from typing import Sequence
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.embedding_models.infrastructure import datastore as datastore_module
from eneo.embedding_models.infrastructure.datastore import Datastore
from eneo.info_blobs.info_blob import InfoBlobChunkInDBWithScore
from eneo.rerank_models.domain.rerank_spec import RerankSpec
from tests.fixtures import TEST_COLLECTION, TEST_UUID


def _chunk(text: str, score: float) -> InfoBlobChunkInDBWithScore:
    return InfoBlobChunkInDBWithScore(
        id=uuid4(),
        info_blob_id=TEST_UUID,
        chunk_no=0,
        text=text,
        score=score,
        user_id=1,
        group_id=1,
        embedding=[0.0],
        tenant_id=TEST_UUID,
        info_blob_title="title",
    )


class FakeReranker:
    """Scores by a lookup table; records what it was asked."""

    def __init__(self, scores: dict[str, float]):
        self.scores = scores
        self.calls: list[tuple[str, list[str]]] = []

    async def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        self.calls.append((query, list(texts)))
        return [self.scores[text] for text in texts]


def _datastore(results: list[InfoBlobChunkInDBWithScore]) -> Datastore:
    repo = AsyncMock()
    repo.semantic_search = AsyncMock(return_value=list(results))
    embeddings = AsyncMock()
    embeddings.get_embedding_for_query = AsyncMock(return_value=[0.1, 0.2])
    return Datastore(
        tenant_id=TEST_UUID,
        info_blob_chunk_repo=repo,
        create_embeddings_service=embeddings,
    )


def _spec(reranker: FakeReranker, query: str = "the question") -> RerankSpec:
    return RerankSpec(
        reranker=reranker,
        query=query,
        model_name="rerank-v3.5",
        candidate_factor=3,
        max_candidates=5,
    )


VECTOR_ORDER = [_chunk("a", 0.9), _chunk("b", 0.8), _chunk("c", 0.7)]


class TestWithoutSpec:
    async def test_is_one_repository_call_with_the_callers_limit(self):
        datastore = _datastore(VECTOR_ORDER)

        result = await datastore.semantic_search(
            "query",
            embedding_model=TEST_COLLECTION.embedding_model,
            collections=[TEST_COLLECTION],
            num_chunks=2,
        )

        repo = datastore.chunk_repo
        assert repo.semantic_search.await_count == 1
        assert repo.semantic_search.await_args.kwargs["limit"] == 2
        assert result == VECTOR_ORDER
        assert (
            datastore.create_embeddings_service.get_embedding_for_query.await_count == 1
        )

    async def test_autocut_still_applies(self):
        datastore = _datastore(VECTOR_ORDER)

        with patch.object(datastore_module, "autocut", return_value=1) as autocut:
            result = await datastore.semantic_search(
                "query",
                embedding_model=TEST_COLLECTION.embedding_model,
                collections=[TEST_COLLECTION],
                autocut_cutoff=2,
            )

        autocut.assert_called_once_with([0.9, 0.8, 0.7], 2)
        assert result == VECTOR_ORDER[:1]


class TestWithSpec:
    async def test_fetches_k_candidates_and_returns_them_all_in_reranker_order(self):
        datastore = _datastore(VECTOR_ORDER)
        reranker = FakeReranker({"a": 0.2, "b": 0.9, "c": 0.5})

        result = await datastore.semantic_search(
            "whole conversation as search string",
            embedding_model=TEST_COLLECTION.embedding_model,
            collections=[TEST_COLLECTION],
            num_chunks=1,
            rerank=_spec(reranker),
        )

        # K = min(3 * 1, 5) candidates; the search covers max(n, K) rows.
        assert datastore.chunk_repo.semantic_search.await_args.kwargs["limit"] == 3
        # The reranker sees the spec's query and the candidates' texts in order.
        assert reranker.calls == [("the question", ["a", "b", "c"])]
        # All K back, reranker order, reranker scores, never cut to n.
        assert [(c.text, c.score) for c in result] == [
            ("b", 0.9),
            ("c", 0.5),
            ("a", 0.2),
        ]

    async def test_chunks_beyond_the_cap_follow_unsorted(self):
        """The newer retrieval version asks for hundreds of chunks; the reranker
        scores K and the rest follow in vector order, never ranked above them."""
        datastore = _datastore(VECTOR_ORDER + [_chunk("d", 0.6)])
        reranker = FakeReranker({"a": 0.3, "b": 0.7})

        result = await datastore.semantic_search(
            "q",
            embedding_model=TEST_COLLECTION.embedding_model,
            collections=[TEST_COLLECTION],
            num_chunks=320,
            rerank=RerankSpec(
                reranker=reranker, query="q", model_name="m", max_candidates=2
            ),
        )

        assert datastore.chunk_repo.semantic_search.await_args.kwargs["limit"] == 320
        assert reranker.calls == [("q", ["a", "b"])]
        assert [(c.text, c.score) for c in result] == [
            ("b", 0.7),
            ("a", 0.3),
            ("c", 0.3),
            ("d", 0.3),
        ]

    async def test_autocut_is_not_applied_with_a_spec(self):
        datastore = _datastore(VECTOR_ORDER)

        with patch.object(datastore_module, "autocut") as autocut:
            result = await datastore.semantic_search(
                "q",
                embedding_model=TEST_COLLECTION.embedding_model,
                collections=[TEST_COLLECTION],
                autocut_cutoff=2,
                rerank=_spec(FakeReranker({"a": 0.1, "b": 0.2, "c": 0.3})),
            )

        autocut.assert_not_called()
        assert len(result) == 3

    async def test_min_score_filters_before_reranking(self):
        datastore = _datastore(VECTOR_ORDER)
        reranker = FakeReranker({"a": 0.5, "b": 0.6})

        result = await datastore.semantic_search(
            "q",
            embedding_model=TEST_COLLECTION.embedding_model,
            collections=[TEST_COLLECTION],
            min_score=0.75,
            rerank=_spec(reranker),
        )

        assert reranker.calls == [("the question", ["a", "b"])]
        assert [c.text for c in result] == ["b", "a"]

    async def test_no_candidates_means_no_reranker_call(self):
        datastore = _datastore([])
        reranker = FakeReranker({})

        result = await datastore.semantic_search(
            "q",
            embedding_model=TEST_COLLECTION.embedding_model,
            collections=[TEST_COLLECTION],
            rerank=_spec(reranker),
        )

        assert result == []
        assert reranker.calls == []


class TestFallback:
    @pytest.mark.parametrize(
        "error", [RuntimeError("provider down"), asyncio.TimeoutError()]
    )
    async def test_failure_yields_todays_result(self, error):
        datastore = _datastore(VECTOR_ORDER)
        reranker = MagicMock()
        reranker.rerank = AsyncMock(side_effect=error)

        with patch.object(datastore_module, "autocut", return_value=2) as autocut:
            result = await datastore.semantic_search(
                "q",
                embedding_model=TEST_COLLECTION.embedding_model,
                collections=[TEST_COLLECTION],
                num_chunks=2,
                autocut_cutoff=3,
                rerank=_spec(reranker),
            )

        # Vector order, cut to the caller's n, autocut as requested, scores untouched.
        autocut.assert_called_once_with([0.9, 0.8], 3)
        assert [(c.text, c.score) for c in result] == [("a", 0.9), ("b", 0.8)]

    async def test_wrong_score_count_is_a_failure_too(self):
        datastore = _datastore(VECTOR_ORDER)
        reranker = MagicMock()
        reranker.rerank = AsyncMock(return_value=[0.1])

        result = await datastore.semantic_search(
            "q",
            embedding_model=TEST_COLLECTION.embedding_model,
            collections=[TEST_COLLECTION],
            num_chunks=3,
            rerank=_spec(reranker),
        )

        assert [(c.text, c.score) for c in result] == [
            ("a", 0.9),
            ("b", 0.8),
            ("c", 0.7),
        ]


class TestFallbackCoversTheCallersLimit:
    async def test_a_capped_candidate_set_does_not_shrink_the_fallback(self):
        """num_chunks above the cap: the reranker saw K rows, the fallback hands
        back what the same search without a spec would, from the one query."""
        datastore = _datastore(VECTOR_ORDER)
        reranker = MagicMock()
        reranker.rerank = AsyncMock(side_effect=RuntimeError("down"))

        result = await datastore.semantic_search(
            "q",
            embedding_model=TEST_COLLECTION.embedding_model,
            collections=[TEST_COLLECTION],
            num_chunks=3,
            rerank=RerankSpec(
                reranker=reranker, query="q", model_name="m", max_candidates=2
            ),
        )

        assert datastore.chunk_repo.semantic_search.await_count == 1
        assert datastore.chunk_repo.semantic_search.await_args.kwargs["limit"] == 3
        assert reranker.rerank.await_args.args[1] == ["a", "b"]
        assert [c.text for c in result] == ["a", "b", "c"]
