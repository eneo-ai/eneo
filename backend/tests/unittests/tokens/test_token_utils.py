import base64
import io
from unittest.mock import patch

from PIL import Image

from intric.tokens.token_utils import (
    count_image_tokens_from_blob,
    count_message_tokens,
    count_tokens,
    count_tool_tokens,
    log_token_count_drift,
)


def _image_data_url(width: int, height: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (230, 230, 230)).save(
        buffer, format="JPEG", quality=85
    )
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/jpeg;base64,{encoded}"


def _image_message(width: int, height: int) -> list[dict]:
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": _image_data_url(width, height),
                        "detail": "high",
                    },
                }
            ],
        }
    ]


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
    assert tokens == 100 + 4 + 1105 + 4


def test_count_tool_tokens_fallback_when_litellm_fails():
    with patch(
        "intric.tokens.token_utils.litellm.token_counter",
        side_effect=RuntimeError("boom"),
    ):
        assert count_tool_tokens(_TOOLS) > 0


def _image_blob(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (230, 230, 230)).save(
        buffer, format="JPEG", quality=85
    )
    return buffer.getvalue()


def test_count_image_tokens_from_blob_uses_provider_formula():
    blob = _image_blob(2048, 1024)
    assert count_image_tokens_from_blob(blob, "openai/gpt-4o") == 1105
    assert (
        count_image_tokens_from_blob(blob, "anthropic/claude-3-5-haiku-20241022")
        == 1568
    )


def test_count_image_tokens_from_blob_falls_back_on_unreadable_data():
    assert count_image_tokens_from_blob(b"not an image") == 1105
    assert count_image_tokens_from_blob(None) == 1105


def test_drift_logging_warns_above_threshold(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="intric.tokens.token_utils"):
        log_token_count_drift("openai/gpt-4o", predicted=1000, actual=1500)

    assert any("Token count drift" in r.message for r in caplog.records)


def test_drift_logging_silent_within_threshold(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="intric.tokens.token_utils"):
        log_token_count_drift("openai/gpt-4o", predicted=1000, actual=1100)
        log_token_count_drift("openai/gpt-4o", predicted=None, actual=1100)
        log_token_count_drift("openai/gpt-4o", predicted=1000, actual=None)
        log_token_count_drift("openai/gpt-4o", predicted=0, actual=0)

    assert not caplog.records


def test_count_message_tokens_prices_images_by_provider_formula():
    # Each provider has its own documented image cost: OpenAI's tile formula
    # gives 1105 for 2048x1024, Anthropic's patch formula 1568 (capped).
    blank = [{"role": "user", "content": ""}]
    message = _image_message(2048, 1024)

    anthropic_delta = count_message_tokens(
        message, "anthropic/claude-3-5-haiku-20241022"
    ) - count_message_tokens(blank, "anthropic/claude-3-5-haiku-20241022")
    openai_delta = count_message_tokens(
        message, "openai/gpt-4o"
    ) - count_message_tokens(blank, "openai/gpt-4o")

    assert anthropic_delta == 1568
    assert openai_delta == 1105
