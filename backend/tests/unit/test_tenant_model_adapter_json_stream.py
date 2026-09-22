import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import litellm
import pytest
from litellm.caching.llm_caching_handler import LLMClientCache
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

from eneo.completion_models.infrastructure.stream_collector import (
    ProviderJsonWhitespaceAbort,
    ProviderStreamBoundExceeded,
    ProviderStreamIncomplete,
)
from eneo.model_providers.domain.provider_call_observer import (
    build_provider_call_request_facts,
)
from tests.unit.test_tenant_model_adapter_non_stream import _make_adapter


def _event(content, finish=None, usage=None):
    event = {
        "id": "raw-response",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": content},
                "finish_reason": finish,
            }
        ],
    }
    if usage is not None:
        event["usage"] = usage
    return ("data: " + json.dumps(event) + "\n\n").encode()


def _usage_event():
    return (
        "data: "
        + json.dumps(
            {
                "id": "raw-response",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "test-model",
                "choices": [],
                "usage": {"prompt_tokens": 12, "completion_tokens": 9},
            }
        )
        + "\n\n"
    ).encode()


class _Body(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0, cleanup_delay=0):
        self.chunks = chunks
        self.delay = delay
        self.cleanup_delay = cleanup_delay
        self.onset = None
        self.closed = False
        self.consumed = 0

    async def __aiter__(self):
        for index, chunk in enumerate(self.chunks):
            if index == 1:
                self.onset = asyncio.get_running_loop().time()
            await asyncio.sleep(self.delay)
            self.consumed += 1
            yield chunk

    async def aclose(self):
        try:
            await asyncio.sleep(self.cleanup_delay)
        finally:
            self.closed = True


@pytest.fixture
def stream_route(monkeypatch):
    requests = []
    call_id = uuid4()
    observer = SimpleNamespace(
        started=AsyncMock(return_value=call_id),
        completed=AsyncMock(),
        rejected=AsyncMock(),
        outcome_unknown=AsyncMock(),
    )
    adapter = _make_adapter()
    adapter._prepare_kwargs = lambda model_kwargs, **kwargs: {
        "response_format": {"type": "json_object"},
        "api_base": "https://stream.invalid/v1",
        "api_key": "test-key",
        "num_retries": 0,
        "max_retries": 0,
    }
    monkeypatch.setattr(litellm, "in_memory_llm_clients_cache", LLMClientCache())
    monkeypatch.setattr(litellm, "disable_aiohttp_transport", True)
    monkeypatch.setattr(litellm, "num_retries", 0)
    monkeypatch.setattr(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._get_supported_openai_params",
        lambda model: ["stream", "stream_options", "response_format", "max_tokens"],
    )

    def serve(body):
        def handler(request):
            observer.started.assert_awaited_once()
            requests.append(json.loads(request.content))
            return httpx.Response(
                200, stream=body, headers={"content-type": "text/event-stream"}
            )

        monkeypatch.setattr(
            AsyncHTTPHandler,
            "_create_async_transport",
            staticmethod(lambda **kwargs: httpx.MockTransport(handler)),
        )

    return SimpleNamespace(
        adapter=adapter,
        observer=observer,
        call_id=call_id,
        requests=requests,
        serve=serve,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_delay", [0, 10])
async def test_http_whitespace_abort_closes_within_two_seconds_without_a_receipt(
    stream_route, cleanup_delay
):
    route = stream_route
    prefix = '{"fact":"å"}'
    body = _Body(
        [_event(prefix)] + [_event(" " * 256)] * 12 + [_event(None, "length")],
        delay=0.01,
        cleanup_delay=cleanup_delay,
    )
    route.serve(body)
    with pytest.raises(ProviderJsonWhitespaceAbort) as caught:
        await route.adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            provider_call_observer=route.observer,
        )
    assert caught.value.raw_text == prefix + " " * 1024
    assert len(route.requests) == 1
    assert route.requests[0]["stream"] is True
    assert body.closed
    assert asyncio.get_running_loop().time() - body.onset < 2.0
    route.observer.outcome_unknown.assert_awaited_once_with(
        route.call_id, "request_cancelled"
    )
    route.observer.completed.assert_not_awaited()
    route.observer.rejected.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "usage",
    [
        {"prompt_tokens": 12},
        {"completion_tokens": 9},
        {
            "prompt_tokens": 12,
            "completion_tokens": 9,
            "completion_tokens_details": {"reasoning_tokens": 3},
        },
    ],
)
async def test_http_json_success_preserves_nullable_usage_and_hashes_streaming(
    stream_route, usage
):
    route = stream_route
    route.serve(_Body([_event("{}"), _event(None, "stop", usage), b"data: [DONE]\n\n"]))
    response = await route.adapter.get_response(
        context=SimpleNamespace(),
        model_kwargs={},
        provider_call_observer=route.observer,
    )
    assert response.text == "{}"
    assert response.provider_response_id == "raw-response"
    assert response.finish_reason == "stop"
    assert response.usage.prompt_tokens == usage.get("prompt_tokens")
    assert response.usage.completion_tokens == usage.get("completion_tokens")
    assert response.usage.reasoning_tokens == usage.get(
        "completion_tokens_details", {}
    ).get("reasoning_tokens")
    actual = route.requests[0]
    expected = build_provider_call_request_facts(
        requested_model="openai/test-model",
        provider="openai",
        messages=[],
        request_kwargs={**actual, "stream": True},
        reason="initial",
    )
    assert (
        route.observer.started.await_args.args[0].provider_request_hash
        == expected.provider_request_hash
    )
    route.observer.completed.assert_awaited_once()
    route.observer.outcome_unknown.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_premature_eof_remains_incomplete(stream_route):
    route = stream_route
    route.serve(_Body([_event("{}")]))
    with pytest.raises(ProviderStreamIncomplete):
        await route.adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            provider_call_observer=route.observer,
        )
    route.observer.completed.assert_not_awaited()
    route.observer.outcome_unknown.assert_awaited_once_with(
        route.call_id, "provider_error"
    )
    assert len(route.requests) == 1


@pytest.mark.asyncio
async def test_unsupported_route_sends_the_original_non_streaming_request(
    stream_route, monkeypatch
):
    route = stream_route
    monkeypatch.setattr(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._get_supported_openai_params",
        lambda model: ["max_tokens", "response_format"],
    )
    raw = "{}" + " " * 2048
    whole = {
        "id": "whole-response",
        "object": "chat.completion",
        "created": 1,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": raw},
                "finish_reason": "stop",
            }
        ],
    }
    route.serve(_Body([json.dumps(whole).encode()]))
    response = await route.adapter.get_response(
        context=SimpleNamespace(),
        model_kwargs={},
        provider_call_observer=route.observer,
    )
    assert response.text == raw
    assert len(route.requests) == 1
    request = route.requests[0]
    assert request.get("stream", False) is False
    assert "stream_options" not in request
    expected = build_provider_call_request_facts(
        requested_model="openai/test-model",
        provider="openai",
        messages=[],
        request_kwargs=request,
        reason="initial",
    )
    assert (
        route.observer.started.await_args.args[0].provider_request_hash
        == expected.provider_request_hash
    )
    route.observer.completed.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cause", ["cancelled", "deadline", "event_count", "retained_bytes"]
)
async def test_http_stream_failures_keep_their_cause_and_never_complete(
    stream_route, monkeypatch, cause
):
    from eneo.completion_models.infrastructure import stream_collector

    route = stream_route
    body = _Body([_event("{")] + [_event('"x"')] * 10, delay=0.01)
    route.serve(body)

    async def request():
        return await route.adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            provider_call_observer=route.observer,
        )

    if cause == "cancelled":
        task = asyncio.create_task(request())
        while body.onset is None:
            await asyncio.sleep(0.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif cause == "deadline":
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.03):
                await request()
    else:
        monkeypatch.setattr(stream_collector, "STREAM_EVENT_LIMIT", 2)
        if cause == "retained_bytes":
            monkeypatch.setattr(stream_collector, "STREAM_RETAINED_BYTES_LIMIT", 1)
        with pytest.raises(ProviderStreamBoundExceeded) as caught:
            await request()
        assert caught.value.bound == cause
    assert body.closed
    assert len(route.requests) == 1
    route.observer.completed.assert_not_awaited()
    route.observer.rejected.assert_not_awaited()
    route.observer.outcome_unknown.assert_awaited_once_with(
        route.call_id,
        "request_cancelled" if cause in {"deadline", "cancelled"} else "provider_error",
    )


@pytest.mark.asyncio
async def test_litellm_reads_native_events_from_completion_stream(
    stream_route, monkeypatch
):
    route = stream_route
    request_completion = route.adapter._request_completion
    observed = []

    async def capture_stream(**kwargs):
        response = await request_completion(**kwargs)
        assert isinstance(response, litellm.CustomStreamWrapper)
        native_stream = response.completion_stream
        assert callable(native_stream.__aiter__)
        assert callable(native_stream.__anext__)
        observed.append(await anext(native_stream))
        return response

    monkeypatch.setattr(route.adapter, "_request_completion", capture_stream)
    route.serve(_Body([_event("prefix"), _event("{}"), _event(None, "stop")]))
    response = await route.adapter.get_response(
        context=SimpleNamespace(),
        model_kwargs={},
        provider_call_observer=route.observer,
    )
    assert len(observed) == 1
    assert observed[0].choices[0].delta.content == "prefix"
    assert response.text == "{}"


@pytest.mark.asyncio
@pytest.mark.parametrize("bound", ["event_count", "retained_bytes"])
@pytest.mark.parametrize("cleanup_delay", [0, 10])
@pytest.mark.filterwarnings("ignore::pydantic.warnings.PydanticDeprecatedSince211")
async def test_http_suppressed_usage_hits_each_bound_during_consumption(
    stream_route, monkeypatch, bound, cleanup_delay
):
    from eneo.completion_models.infrastructure import stream_collector

    route = stream_route
    monkeypatch.setattr(
        stream_collector, "STREAM_EVENT_LIMIT", 4 if bound == "event_count" else 1000
    )
    monkeypatch.setattr(
        stream_collector,
        "STREAM_RETAINED_BYTES_LIMIT",
        4096 if bound == "retained_bytes" else 1_000_000,
    )
    body = _Body(
        [_event("{}")]
        + [_usage_event()] * 100
        + [_event(None, "stop"), b"data: [DONE]\n\n"],
        cleanup_delay=cleanup_delay,
    )
    route.serve(body)
    request_completion = route.adapter._request_completion
    responses = []

    async def capture_stream(**kwargs):
        response = await request_completion(**kwargs)
        assert isinstance(response, litellm.CustomStreamWrapper)
        responses.append(response)
        return response

    monkeypatch.setattr(route.adapter, "_request_completion", capture_stream)
    with pytest.raises(ProviderStreamBoundExceeded) as caught:
        await route.adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            provider_call_observer=route.observer,
        )
    assert caught.value.bound == bound
    assert caught.value.limit == (4 if bound == "event_count" else 4096)
    assert body.consumed < len(body.chunks)
    assert body.closed
    assert asyncio.get_running_loop().time() - body.onset < 2.0
    retained = responses[0].chunks
    assert len(retained) <= stream_collector.STREAM_EVENT_LIMIT
    assert (
        sum(len(chunk.model_dump_json().encode()) for chunk in retained)
        <= stream_collector.STREAM_RETAINED_BYTES_LIMIT
    )
    assert len(route.requests) == 1
    route.observer.completed.assert_not_awaited()
    route.observer.rejected.assert_not_awaited()
    route.observer.outcome_unknown.assert_awaited_once_with(
        route.call_id, "provider_error"
    )


def test_actual_stream_choice_changes_fingerprint():
    kwargs = dict(
        requested_model="openai/test-model",
        provider="openai",
        messages=[],
        reason="initial",
    )
    plain = build_provider_call_request_facts(**kwargs, request_kwargs={})
    streamed = build_provider_call_request_facts(
        **kwargs, request_kwargs={"stream": True}
    )
    assert plain.provider_request_hash != streamed.provider_request_hash
    material = {
        "request_schema_version": 2,
        "requested_model": "openai/test-model",
        "provider": "openai",
        "messages": [],
        "controls": {},
        "stream": True,
    }
    assert (
        streamed.provider_request_hash
        == hashlib.sha256(
            json.dumps(
                material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    )
