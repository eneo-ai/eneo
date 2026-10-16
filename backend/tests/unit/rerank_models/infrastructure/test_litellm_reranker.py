"""The LiteLLM reranker: one transport call, scores mapped back by index."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from eneo.rerank_models.infrastructure import litellm_reranker
from eneo.rerank_models.infrastructure.litellm_reranker import LiteLLMReranker


def _response(*items: tuple[int, float]):
    return SimpleNamespace(
        results=[{"index": index, "relevance_score": score} for index, score in items]
    )


def _reranker(**overrides) -> LiteLLMReranker:
    values = dict(
        route="cohere/rerank-v3.5",
        provider_kwargs={"api_key": "key", "api_base": "http://reranker:8000"},
        outbound_headers=None,
        timeout_seconds=7,
    )
    values.update(overrides)
    return LiteLLMReranker(**values)


async def test_sends_query_documents_and_provider_settings():
    arerank = AsyncMock(return_value=_response((0, 0.1), (1, 0.9)))

    with patch.object(litellm_reranker.litellm_transport, "arerank", arerank):
        scores = await _reranker().rerank("q", ["first", "second"])

    kwargs = arerank.await_args.kwargs
    assert kwargs["model"] == "cohere/rerank-v3.5"
    assert kwargs["query"] == "q"
    assert kwargs["documents"] == ["first", "second"]
    assert kwargs["top_n"] == 2
    assert kwargs["timeout"] == 7
    assert kwargs["api_key"] == "key"
    assert kwargs["api_base"] == "http://reranker:8000"
    assert scores == [0.1, 0.9]


async def test_scores_follow_input_order_whatever_the_provider_returns():
    arerank = AsyncMock(return_value=_response((2, 0.7), (0, 0.3), (1, 0.5)))

    with patch.object(litellm_reranker.litellm_transport, "arerank", arerank):
        scores = await _reranker().rerank("q", ["a", "b", "c"])

    assert scores == [0.3, 0.5, 0.7]


async def test_a_candidate_the_provider_leaves_out_scores_zero():
    arerank = AsyncMock(return_value=_response((1, 0.8)))

    with patch.object(litellm_reranker.litellm_transport, "arerank", arerank):
        scores = await _reranker().rerank("q", ["a", "b"])

    assert scores == [0.0, 0.8]


async def test_object_results_are_read_like_dicts():
    arerank = AsyncMock(
        return_value=SimpleNamespace(
            results=[SimpleNamespace(index=0, relevance_score=0.4)]
        )
    )

    with patch.object(litellm_reranker.litellm_transport, "arerank", arerank):
        scores = await _reranker().rerank("q", ["a"])

    assert scores == [0.4]
