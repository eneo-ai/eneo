"""Canonical OpenAI-format payload pieces shared by the adapter and token counting.

TenantModelAdapter builds the real request from these builders and
context_builder counts the same dicts — one source of truth, so the counted
shape cannot drift from the sent shape.
"""

import base64
import json
from typing import Any
from uuid import NAMESPACE_OID, UUID, uuid4, uuid5

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


class TurnToolCallIds:
    """Give each invocation one id for its events, approvals and tool result."""

    def __init__(self, namespace: UUID | None = None) -> None:
        self._namespace = namespace or uuid4()
        self._used: set[str] = set()

    def claim(self, provider_id: str) -> str:
        if not provider_id:
            return provider_id
        call_id = provider_id
        ordinal = len(self._used)
        while call_id in self._used:
            # Nine alphanumerics also fit providers with strict tool-id formats.
            call_id = uuid5(self._namespace, f"{provider_id}:{ordinal}").hex[:9]
            ordinal += 1
        self._used.add(call_id)
        return call_id


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
        # Previously stored turns can contain repeated provider ids. Reconstruct
        # the same pairs when counting tokens and when sending the follow-up.
        ids = TurnToolCallIds(NAMESPACE_OID)
        calls = [(ids.claim(tc.tool_call_id), tc) for tc in tool_calls]
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
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
                    for call_id, tc in calls
                ],
            }
        )
        for call_id, tc in calls:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
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
