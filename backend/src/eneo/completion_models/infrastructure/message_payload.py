"""Canonical OpenAI-format payload pieces shared by the adapter and token counting.

TenantModelAdapter builds the real request from these builders and
context_builder counts the same dicts — one source of truth, so the counted
shape cannot drift from the sent shape.
"""

import base64
import json
from typing import Any

from eneo.ai_models.completion_models.completion_model import MessageToolCall
from eneo.files.file_models import File


def build_image_block(file: File) -> dict[str, Any]:
    blob = file.blob
    if blob is None:
        raise ValueError("Image file is missing blob data")

    image_data = base64.b64encode(blob).decode("utf-8")
    # detail is explicit (not provider-default "auto") so token counting can
    # mirror the real cost deterministically; uploads are already downscaled
    # to MAX_IMAGE_DIMENSION, where auto resolves to high anyway.
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{file.mimetype};base64,{image_data}",
            "detail": "high",
        },
    }


def build_content(text: str, images: list[File]) -> str | list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    if text:
        content.append({"type": "text", "text": text})

    for image in images:
        content.append(build_image_block(image))

    if len(content) == 1 and content[0].get("type") == "text":
        return text
    return content


def build_turn_messages(
    question: str,
    answer: str | None,
    images: list[File],
    tool_calls: list[MessageToolCall],
) -> list[dict[str, Any]]:
    """One persisted Q&A turn in the canonical replay shape.

    The user message, then — when tools ran — a pre-tool assistant message
    carrying only `tool_calls`, one `role: tool` entry per call, and the final
    answer. This matches what the live flow produces during generation and
    keeps causal order intact.
    """
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": build_content(question, images)}
    ]
    if tool_calls:
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": tc.tool_name,
                            "arguments": (
                                json.dumps(tc.arguments)
                                if tc.arguments is not None
                                else "{}"
                            ),
                        },
                    }
                    for tc in tool_calls
                ],
            }
        )
        for tc in tool_calls:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.tool_call_id,
                    "content": tc.result,
                }
            )
        if answer:
            messages.append({"role": "assistant", "content": answer})
    else:
        messages.append({"role": "assistant", "content": answer or "[image generated]"})
    return messages


def countable_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adapt canonical messages for litellm's token counter.

    litellm cannot price `tool_calls` structures or None content, so the
    tool-call list is counted as its JSON serialization — which is what the
    provider receives — and extra keys are dropped.
    """
    countable: list[dict[str, Any]] = []
    for message in messages:
        if message.get("tool_calls"):
            countable.append(
                {
                    "role": message["role"],
                    "content": json.dumps(message["tool_calls"]),
                }
            )
        else:
            countable.append(
                {"role": message["role"], "content": message.get("content") or ""}
            )
    return countable
