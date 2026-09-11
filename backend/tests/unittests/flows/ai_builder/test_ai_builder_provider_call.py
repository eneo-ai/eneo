from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import litellm
import pytest
from litellm.types import utils as litellm_types

from eneo.flows.ai_builder.ai_builder_provider_call import (
    ProviderCallCeilingExpired,
    ProviderSilenceExpired,
    ProviderStreamIncomplete,
    complete_with_silence_deadline,
)

_MESSAGES = [{"role": "user", "content": "Propose a flow."}]
_REQUEST = {"model": "gpt-test", "messages": _MESSAGES}


def _tool_chunk(arguments: str, *, first: bool, finish: str | None) -> object:
    call = litellm_types.ChatCompletionDeltaToolCall(
        id="call_1" if first else None,
        type="function",
        index=0,
        function=litellm_types.Function(
            name="propose_flow" if first else None, arguments=arguments
        ),
    )
    return litellm_types.ModelResponseStream(
        id="resp",
        model="gpt-test",
        choices=[
            litellm_types.StreamingChoices(
                index=0,
                delta=litellm_types.Delta(content=None, tool_calls=[call]),
                finish_reason=finish,
            )
        ],
    )


def _usage_chunk() -> object:
    return litellm_types.ModelResponseStream(
        id="resp",
        model="gpt-test",
        choices=[],
        usage=litellm_types.Usage(
            prompt_tokens=12, completion_tokens=7, total_tokens=19
        ),
    )


async def _stream(chunks: list[object], *, delay: float = 0.0):
    for chunk in chunks:
        if delay:
            await asyncio.sleep(delay)
        yield chunk


@pytest.mark.asyncio
async def test_a_streamed_tool_call_is_rebuilt_whole_with_its_usage() -> None:
    client = SimpleNamespace(
        acompletion=AsyncMock(
            return_value=_stream(
                [
                    _tool_chunk('{"name": "Sum', first=True, finish=None),
                    _tool_chunk('marise"}', first=False, finish="tool_calls"),
                    _usage_chunk(),
                ]
            )
        )
    )

    response = await complete_with_silence_deadline(
        client,
        silence_deadline_seconds=1.0,
        ceiling_seconds=5.0,
        request={**_REQUEST, "max_tokens": 50},
    )

    sent = client.acompletion.await_args.kwargs
    assert sent["stream"] is True
    assert sent["stream_options"] == {"include_usage": True}
    assert sent["timeout"] == 1.0
    assert sent["max_tokens"] == 50
    choice = response.choices[0]
    assert choice.finish_reason == "tool_calls"
    assert choice.message.tool_calls[0].function.name == "propose_flow"
    assert choice.message.tool_calls[0].function.arguments == '{"name": "Summarise"}'
    assert (response.usage.prompt_tokens, response.usage.completion_tokens) == (12, 7)


@pytest.mark.asyncio
async def test_a_slow_answer_that_keeps_flowing_is_never_cut_off() -> None:
    # Each chunk arrives within the silence deadline; the whole answer takes
    # far longer than that deadline and still completes.
    chunks = [_tool_chunk('{"name": "A', first=True, finish=None)]
    chunks += [_tool_chunk("a", first=False, finish=None) for _ in range(8)]
    chunks += [_tool_chunk('"}', first=False, finish="tool_calls")]
    client = SimpleNamespace(
        acompletion=AsyncMock(return_value=_stream(chunks, delay=0.03))
    )

    response = await complete_with_silence_deadline(
        client, silence_deadline_seconds=0.1, ceiling_seconds=5.0, request=_REQUEST
    )

    assert (
        response.choices[0].message.tool_calls[0].function.arguments
        == '{"name": "Aaaaaaaaa"}'
    )


class _Closed:
    """Whether a generator-backed stream was closed by the owner."""

    def __init__(self) -> None:
        self.closed = False


def _recording_stream(
    chunks: list[object], closed: _Closed, *, stall_after: int | None = None
):
    async def stream():
        try:
            for index, chunk in enumerate(chunks):
                if stall_after is not None and index >= stall_after:
                    await asyncio.Event().wait()
                yield chunk
        finally:
            closed.closed = True

    return stream()


def _stream_client(stream: object) -> SimpleNamespace:
    return SimpleNamespace(acompletion=AsyncMock(return_value=stream))


@pytest.mark.asyncio
async def test_a_stream_that_ends_without_a_finish_reason_is_incomplete() -> None:
    # What arrived would parse; the provider never said it was done.
    closed = _Closed()
    stream = _recording_stream(
        [_tool_chunk('{"name": "A"}', first=True, finish=None)], closed
    )
    with pytest.raises(ProviderStreamIncomplete):
        await complete_with_silence_deadline(
            _stream_client(stream),
            silence_deadline_seconds=1.0,
            ceiling_seconds=5.0,
            request=_REQUEST,
        )
    assert closed.closed is True


@pytest.mark.asyncio
async def test_silence_expiry_closes_the_stream_and_names_itself() -> None:
    closed = _Closed()
    stream = _recording_stream(
        [
            _tool_chunk('{"name": "A', first=True, finish=None),
            _tool_chunk('"}', first=False, finish="tool_calls"),
        ],
        closed,
        stall_after=1,
    )
    with pytest.raises(ProviderSilenceExpired):
        await complete_with_silence_deadline(
            _stream_client(stream),
            silence_deadline_seconds=0.05,
            ceiling_seconds=5.0,
            request=_REQUEST,
        )
    assert closed.closed is True


@pytest.mark.asyncio
async def test_absent_provider_usage_stays_absent_after_rebuilding() -> None:
    closed = _Closed()
    stream = _recording_stream(
        [
            _tool_chunk('{"name": "A', first=True, finish=None),
            _tool_chunk('"}', first=False, finish="tool_calls"),
        ],
        closed,
    )
    response = await complete_with_silence_deadline(
        _stream_client(stream),
        silence_deadline_seconds=1.0,
        ceiling_seconds=5.0,
        request=_REQUEST,
    )
    assert response.usage is None
    assert closed.closed is True


def test_the_ceiling_cannot_be_below_the_silence_deadline() -> None:
    with pytest.raises(ValueError):
        asyncio.run(
            complete_with_silence_deadline(
                SimpleNamespace(acompletion=AsyncMock()),
                silence_deadline_seconds=10,
                ceiling_seconds=5,
                request=_REQUEST,
            )
        )


@pytest.mark.asyncio
async def test_silence_after_the_first_bytes_expires_the_deadline() -> None:
    async def stalls():
        yield _tool_chunk('{"name": "A', first=True, finish=None)
        await asyncio.sleep(1.0)
        yield _tool_chunk('"}', first=False, finish="tool_calls")

    client = SimpleNamespace(acompletion=AsyncMock(return_value=stalls()))
    with pytest.raises(ProviderSilenceExpired):
        await complete_with_silence_deadline(
            client, silence_deadline_seconds=0.05, ceiling_seconds=5.0, request=_REQUEST
        )


@pytest.mark.asyncio
async def test_silence_before_the_first_byte_expires_the_deadline() -> None:
    async def never(**_kwargs: object) -> object:
        await asyncio.Event().wait()
        return None

    client = SimpleNamespace(acompletion=AsyncMock(side_effect=never))
    with pytest.raises(ProviderSilenceExpired):
        await complete_with_silence_deadline(
            client, silence_deadline_seconds=0.05, ceiling_seconds=5.0, request=_REQUEST
        )


@pytest.mark.asyncio
async def test_the_ceiling_bounds_an_answer_that_never_ends() -> None:
    async def endless():
        while True:
            await asyncio.sleep(0.01)
            yield _tool_chunk("a", first=False, finish=None)

    client = SimpleNamespace(acompletion=AsyncMock(return_value=endless()))
    with pytest.raises(ProviderCallCeilingExpired):
        await complete_with_silence_deadline(
            client, silence_deadline_seconds=0.05, ceiling_seconds=0.1, request=_REQUEST
        )


@pytest.mark.asyncio
async def test_a_whole_answer_is_accepted_as_it_is() -> None:
    whole = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
    )
    client = SimpleNamespace(acompletion=AsyncMock(return_value=whole))

    response = await complete_with_silence_deadline(
        client, silence_deadline_seconds=1.0, ceiling_seconds=5.0, request=_REQUEST
    )

    assert response is whole


@pytest.mark.asyncio
async def test_an_empty_stream_is_incomplete() -> None:
    client = SimpleNamespace(acompletion=AsyncMock(return_value=_stream([])))

    with pytest.raises(ProviderStreamIncomplete):
        await complete_with_silence_deadline(
            client, silence_deadline_seconds=1.0, ceiling_seconds=5.0, request=_REQUEST
        )


def test_the_silence_deadline_must_be_positive() -> None:
    with pytest.raises(ValueError):
        asyncio.run(
            complete_with_silence_deadline(
                SimpleNamespace(acompletion=AsyncMock()),
                silence_deadline_seconds=0,
                ceiling_seconds=5,
                request=_REQUEST,
            )
        )


# --- Through LiteLLM's real stream wrapper over a mocked HTTP transport -----

import json  # noqa: E402
import math  # noqa: E402

import httpx  # noqa: E402
from litellm.caching.llm_caching_handler import LLMClientCache  # noqa: E402
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler  # noqa: E402

_WRAPPED_REQUEST = {
    "model": "openai/gpt-test",
    "messages": _MESSAGES,
    "api_key": "test-key",
    "api_base": "https://stream.invalid/v1",
    "num_retries": 0,
    "max_retries": 0,
}


def _sse(events: list[dict[str, object]], *, done: bool = True) -> bytes:
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    if done:
        body += "data: [DONE]\n\n"
    return body.encode()


def _usage(prompt: int, completion: int) -> dict[str, int]:
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def _delta(
    content: str | None, finish: str | None, *, usage: dict[str, int] | None = None
) -> dict[str, object]:
    event: dict[str, object] = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "gpt-test",
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
    return event


def _usage_event(prompt: int, completion: int) -> dict[str, object]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "gpt-test",
        "choices": [],
        "usage": _usage(prompt, completion),
    }


def _serve(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )

    monkeypatch.setattr(
        AsyncHTTPHandler,
        "_create_async_transport",
        staticmethod(lambda **_kwargs: httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(litellm, "in_memory_llm_clients_cache", LLMClientCache())
    monkeypatch.setattr(litellm, "disable_aiohttp_transport", True)
    monkeypatch.setattr(litellm, "num_retries", 0)


@pytest.mark.filterwarnings("ignore::pydantic.warnings.PydanticDeprecatedSince211")
@pytest.mark.parametrize(
    "events",
    [
        # Usage as its own final chunk (OpenAI with include_usage).
        [_delta("Hej", None), _delta(None, "stop"), _usage_event(12, 3)],
        # Usage riding on the terminal choice chunk; the SDK recounts this
        # layout on its own (8/1 for this body) and must not win.
        [_delta("Hej", None), _delta(None, "stop", usage=_usage(12, 3))],
    ],
    ids=["separate-usage-chunk", "usage-on-terminal-choice"],
)
@pytest.mark.asyncio
async def test_a_provider_finish_reason_and_usage_come_through_the_wrapper(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, object]]
) -> None:
    _serve(monkeypatch, _sse(events))

    response = await complete_with_silence_deadline(
        litellm,
        silence_deadline_seconds=5.0,
        ceiling_seconds=10.0,
        request=_WRAPPED_REQUEST,
    )

    assert response.choices[0].message.content == "Hej"
    assert response.choices[0].finish_reason == "stop"
    assert (response.usage.prompt_tokens, response.usage.completion_tokens) == (12, 3)


def _anthropic_event(name: str, data: dict[str, object]) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


_ANTHROPIC_REQUEST = {
    "model": "anthropic/claude-test",
    "messages": _MESSAGES,
    "api_key": "test-key",
    "api_base": "https://stream.invalid",
    "num_retries": 0,
    "max_retries": 0,
}


@pytest.mark.filterwarnings("ignore::pydantic.warnings.PydanticDeprecatedSince211")
@pytest.mark.asyncio
async def test_usage_split_across_provider_events_is_combined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Anthropic reports input tokens with the first event and output tokens
    # with the last; neither usage object alone is the request's usage.
    body = "".join(
        [
            _anthropic_event(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "model": "claude-test",
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 12, "output_tokens": 0},
                    },
                },
            ),
            _anthropic_event(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            _anthropic_event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hej"},
                },
            ),
            _anthropic_event(
                "content_block_stop", {"type": "content_block_stop", "index": 0}
            ),
            _anthropic_event(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 3},
                },
            ),
            _anthropic_event("message_stop", {"type": "message_stop"}),
        ]
    ).encode()
    _serve(monkeypatch, body)

    response = await complete_with_silence_deadline(
        litellm,
        silence_deadline_seconds=5.0,
        ceiling_seconds=10.0,
        request=_ANTHROPIC_REQUEST,
    )

    assert response.choices[0].message.content == "Hej"
    assert (
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
        response.usage.total_tokens,
    ) == (12, 3, 15)


@pytest.mark.asyncio
async def test_a_wrapped_stream_without_a_provider_finish_reason_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The wrapper synthesizes "stop" on a bare end of stream; the provider
    # never said it was done, so the owner does not accept the answer.
    _serve(monkeypatch, _sse([_delta('{"suggestions": []}', None)]))

    with pytest.raises(ProviderStreamIncomplete):
        await complete_with_silence_deadline(
            litellm,
            silence_deadline_seconds=5.0,
            ceiling_seconds=10.0,
            request=_WRAPPED_REQUEST,
        )


@pytest.mark.asyncio
async def test_usage_the_wrapper_made_up_is_not_the_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch, _sse([_delta("Hej", None), _delta(None, "stop")]))

    response = await complete_with_silence_deadline(
        litellm,
        silence_deadline_seconds=5.0,
        ceiling_seconds=10.0,
        request=_WRAPPED_REQUEST,
    )

    assert response.choices[0].finish_reason == "stop"
    assert response.usage is None


@pytest.mark.asyncio
async def test_a_timeout_the_client_raises_itself_is_not_local_silence() -> None:
    client = SimpleNamespace(acompletion=AsyncMock(side_effect=TimeoutError("sdk")))

    with pytest.raises(TimeoutError) as raised:
        await complete_with_silence_deadline(
            client,
            silence_deadline_seconds=10.0,
            ceiling_seconds=20.0,
            request=_REQUEST,
        )

    assert not isinstance(raised.value, ProviderSilenceExpired)
    assert not isinstance(raised.value, ProviderCallCeilingExpired)


class _SlowToClose:
    """An iterator whose release takes longer than the call's ceiling."""

    def __init__(self) -> None:
        self.closed = False
        self._yielded = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._yielded:
            await asyncio.Event().wait()
        self._yielded = True
        return _tool_chunk('{"name": "A', first=True, finish=None)

    async def aclose(self) -> None:
        await asyncio.sleep(0.1)
        self.closed = True


@pytest.mark.asyncio
async def test_cleanup_finishes_even_when_the_ceiling_interrupts_it() -> None:
    stream = _SlowToClose()

    with pytest.raises(ProviderSilenceExpired):
        await complete_with_silence_deadline(
            _stream_client(stream),
            silence_deadline_seconds=0.05,
            ceiling_seconds=0.08,
            request=_REQUEST,
        )
    assert stream.closed is True


@pytest.mark.parametrize("ceiling", [math.inf, math.nan])
def test_non_finite_durations_are_refused(ceiling: float) -> None:
    with pytest.raises(ValueError):
        asyncio.run(
            complete_with_silence_deadline(
                SimpleNamespace(acompletion=AsyncMock()),
                silence_deadline_seconds=1.0,
                ceiling_seconds=ceiling,
                request=_REQUEST,
            )
        )
