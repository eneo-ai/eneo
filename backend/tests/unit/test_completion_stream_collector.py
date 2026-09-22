import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import litellm
import pytest
from litellm.types.utils import ModelResponseStream, Usage

from eneo.completion_models.infrastructure import stream_collector
from eneo.completion_models.infrastructure.stream_collector import (
    ProviderJsonWhitespaceAbort,
    ProviderStreamBoundExceeded,
    ProviderStreamCollector,
    ProviderStreamIncomplete,
)
from eneo.flows.ai_builder.ai_builder_provider_call import (
    ProviderSilenceExpired,
    complete_with_silence_deadline,
)


@pytest.mark.asyncio
async def test_lazy_native_stream_setup_keeps_the_builder_silence_deadline():
    async def never(**kwargs):
        await asyncio.Event().wait()

    response = litellm.CustomStreamWrapper(
        completion_stream=None,
        model="gpt-test",
        logging_obj=MagicMock(model_call_details={}),
        make_call=AsyncMock(side_effect=never),
    )
    with pytest.raises(ProviderSilenceExpired):
        await complete_with_silence_deadline(
            SimpleNamespace(acompletion=AsyncMock(return_value=response)),
            silence_deadline_seconds=0.01,
            ceiling_seconds=0.1,
            request={"model": "gpt-test", "messages": []},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("response_format", ["json_object", "json_schema"])
async def test_native_json_completion_aborts_a_whitespace_run(response_format):
    async def stream():
        for content, finish in [
            ('{"fact":1}' + "\n        " * 200, None),
            ("", "stop"),
        ]:
            yield ModelResponseStream(
                choices=[
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": content},
                        "finish_reason": finish,
                    }
                ],
            )

    client = SimpleNamespace(acompletion=AsyncMock(return_value=stream()))
    with pytest.raises(Exception, match="JSON whitespace") as caught:
        await complete_with_silence_deadline(
            client,
            silence_deadline_seconds=1,
            ceiling_seconds=5,
            request={
                "model": "openai/test",
                "messages": [{"role": "user", "content": "JSON"}],
                "response_format": {"type": response_format},
            },
        )
    assert type(caught.value).__name__ == "ProviderJsonWhitespaceAbort"
    assert client.acompletion.await_count == 1


def _chunk(content=None, *, finish=None, **delta):
    return ModelResponseStream(
        id="provider-response",
        model="gpt-test",
        choices=[
            {
                "index": 0,
                "delta": {"role": "assistant", "content": content, **delta},
                "finish_reason": finish,
            }
        ],
    )


async def _collect(chunks, *, response_format="json_object", terminal=True):
    async def stream():
        for chunk in chunks:
            yield chunk
        if terminal:
            yield _chunk(finish="stop")

    async with ProviderStreamCollector() as collector:
        return await collector.collect(
            stream(),
            request={
                "messages": [],
                "response_format": {"type": response_format},
            },
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("sizes", [(1,), (17, 3, 91, 8), (1024,)])
async def test_incident_aborts_at_1024_under_different_chunking(sizes):
    prefix = '{"fact":"å"}'
    padding = ("\n        " * 114)[:1024]
    chunks = [_chunk(prefix)]
    offset = 0
    while offset < len(padding):
        size = sizes[len(chunks) % len(sizes)]
        chunks.append(_chunk(padding[offset : offset + size]))
        offset += size
    with pytest.raises(ProviderJsonWhitespaceAbort) as caught:
        await _collect(chunks)
    assert caught.value.raw_text == prefix + padding
    response = await _collect([_chunk(prefix + padding[:-1])])
    assert response.choices[0].message.content == prefix + padding[:-1]


@pytest.mark.asyncio
async def test_leading_whitespace_counts_and_non_content_events_do_not_reset_it():
    with pytest.raises(ProviderJsonWhitespaceAbort) as caught:
        await _collect(
            [
                _chunk(" " * 600),
                _chunk(reasoning_content="reasoning" + " " * 4000),
                _chunk(tool_calls=[{"index": 0, "function": {"arguments": "value"}}]),
                _chunk(),
                _chunk(" \t\r\n" * 106),
            ]
        )
    assert caught.value.raw_text == " " * 600 + " \t\r\n" * 106


@pytest.mark.asyncio
async def test_progress_within_a_chunk_resets_whitespace():
    text = '{"a":' + " " * 1023 + '1,"b":' + "\n" * 1023 + "2}"
    response = await _collect([_chunk(text)])
    assert response.choices[0].message.content == text


@pytest.mark.asyncio
async def test_quotes_and_escapes_cross_deltas_without_counting_string_padding():
    text = json.dumps({"a": '\\"' + " " * 2048 + '"\\', "b": list(range(4000))})
    response = await _collect([_chunk(text[i : i + 7]) for i in range(0, len(text), 7)])
    assert response.choices[0].message.content == text


@pytest.mark.asyncio
@pytest.mark.parametrize("response_format", ["text", "other"])
async def test_non_native_json_does_not_enable_the_detector(response_format):
    text = " " * 2048
    response = await _collect([_chunk(text)], response_format=response_format)
    assert response.choices[0].message.content == text


@pytest.mark.asyncio
async def test_reconstruction_keeps_usage_reasoning_and_tool_calls():
    prompt, completion = 12, 9
    first = _chunk(
        reasoning_content="reasoning",
        tool_calls=[
            {
                "index": 0,
                "id": "call-1",
                "type": "function",
                "function": {"name": "lookup", "arguments": '{"q":'},
            }
        ],
    )
    last = _chunk(
        finish="tool_calls",
        tool_calls=[{"index": 0, "function": {"arguments": '"answer"}'}}],
    )
    last.usage = Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        completion_tokens_details={"reasoning_tokens": 3},
    )
    response = await _collect([first, last], terminal=False)
    assert response.id == "provider-response"
    assert response.choices[0].finish_reason == "tool_calls"
    tool = response.choices[0].message.tool_calls[0]
    assert (tool.id, tool.function.name, tool.function.arguments) == (
        "call-1",
        "lookup",
        '{"q":"answer"}',
    )
    assert response.usage.prompt_tokens == prompt
    assert response.usage.completion_tokens == completion
    assert response.usage.completion_tokens_details.reasoning_tokens == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("bound", ["event_count", "retained_bytes"])
async def test_stream_exhaustion_names_the_bound(monkeypatch, bound):
    monkeypatch.setattr(stream_collector, "STREAM_EVENT_LIMIT", 2)
    monkeypatch.setattr(stream_collector, "STREAM_RETAINED_BYTES_LIMIT", 2048)
    chunks = [_chunk("x" * 2048)] if bound == "retained_bytes" else [_chunk()] * 3
    with pytest.raises(ProviderStreamBoundExceeded) as caught:
        await _collect(chunks)
    assert caught.value.bound == bound


@pytest.mark.asyncio
async def test_premature_eof_does_not_become_a_success():
    with pytest.raises(ProviderStreamIncomplete):
        await _collect([_chunk("{}")], terminal=False)


@pytest.mark.asyncio
async def test_cancelled_collection_closes_without_replacing_cancellation():
    closed = asyncio.Event()
    started = asyncio.Event()

    class Stream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            started.set()
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()
            raise RuntimeError("cleanup failed")

    async def collect():
        async with ProviderStreamCollector() as collector:
            await collector.collect(Stream(), request={})

    task = asyncio.create_task(collect())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
