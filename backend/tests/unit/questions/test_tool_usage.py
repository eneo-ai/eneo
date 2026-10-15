"""Tool-reported model usage folds into the question row only from Eneo's own
tools, on the turn's model, with sane counts."""

from uuid import uuid4

from eneo.questions.question import ToolCallInfo
from eneo.questions.tool_usage import tool_usage_tokens


def _call(*, is_internal=True, model_id=None, tokens_in=120, tokens_out=30, meta=None):
    payload = (
        meta
        if meta is not None
        else {
            "gen_ai.usage.input_tokens": tokens_in,
            "gen_ai.usage.output_tokens": tokens_out,
            "eneo.completion_model_id": str(model_id),
        }
    )
    return ToolCallInfo(
        server_name="knowledge",
        tool_name="digest_documents",
        mcp_tool_name="knowledge__digest_documents",
        is_internal=is_internal,
        meta=payload,
    )


def test_sums_internal_calls_on_the_same_model():
    model_id = uuid4()
    calls = [
        _call(model_id=model_id),
        _call(model_id=model_id, tokens_in=5, tokens_out=1),
    ]

    assert tool_usage_tokens(calls, model_id) == (125, 31)


def test_other_models_external_servers_and_missing_meta_do_not_count():
    model_id = uuid4()
    calls = [
        _call(model_id=uuid4()),
        _call(model_id=model_id, is_internal=False),
        _call(model_id=model_id, is_internal=None),
        _call(meta={}),
    ]

    assert tool_usage_tokens(calls, model_id) == (0, 0)
    assert tool_usage_tokens(None, model_id) == (0, 0)
    assert tool_usage_tokens([_call(model_id=model_id)], None) == (0, 0)


def test_invalid_counts_skip_the_row():
    model_id = uuid4()
    bad = [
        _call(model_id=model_id, tokens_in=-1),
        _call(model_id=model_id, tokens_out="30"),
        _call(model_id=model_id, tokens_in=True),
        _call(model_id=model_id, tokens_in=10**9),
    ]

    assert tool_usage_tokens([*bad, _call(model_id=model_id)], model_id) == (120, 30)
