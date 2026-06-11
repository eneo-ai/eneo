from unittest.mock import patch

from intric.tokens.token_utils import (
    count_message_tokens,
    count_tokens,
    count_tool_tokens,
)

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Generate an image based on a text prompt.",
            "parameters": {
                "type": "object",
                "properties": {"prompt": {"type": "string"}},
                "required": ["prompt"],
            },
        },
    }
]


def test_count_tokens_empty_text():
    assert count_tokens("") == 0


def test_count_message_tokens_includes_scaffolding_overhead():
    text = "hello world"
    assert count_message_tokens([{"role": "user", "content": text}]) > count_tokens(
        text
    )


def test_count_message_tokens_counts_image_blocks():
    base = count_message_tokens([{"role": "user", "content": "hi"}])
    with_image = count_message_tokens(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hi"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,aGVsbG8="},
                    },
                ],
            }
        ]
    )
    assert with_image >= base + 85


def test_count_tool_tokens_positive():
    assert count_tool_tokens(_TOOLS) > 0


def test_count_tool_tokens_empty():
    assert count_tool_tokens([]) == 0


def test_count_message_tokens_fallback_when_litellm_fails():
    messages = [
        {"role": "user", "content": "x" * 400},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,a"}}
            ],
        },
    ]
    with patch(
        "intric.tokens.token_utils.litellm.token_counter",
        side_effect=RuntimeError("boom"),
    ):
        tokens = count_message_tokens(messages)

    # len//4 for the text + flat image estimate + per-message overhead
    assert tokens == 100 + 4 + 85 + 4


def test_count_tool_tokens_fallback_when_litellm_fails():
    with patch(
        "intric.tokens.token_utils.litellm.token_counter",
        side_effect=RuntimeError("boom"),
    ):
        assert count_tool_tokens(_TOOLS) > 0
