from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderProviderOutcomeUnknownException,
    record_ai_builder_provider_failure,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    latest_pending_structured_question,
)

if TYPE_CHECKING:
    from eneo.completion_models.infrastructure.completion_service import (
        ResolvedCompletionModelRoute,
    )


@dataclass(frozen=True, slots=True)
class PendingQuestionResolution:
    question_id: str
    selected_option_ids: tuple[str, ...]
    selected_values: tuple[str, ...]

    def to_question_answer(self) -> dict[str, object]:
        return {
            "question_id": self.question_id,
            "selected_option_ids": list(self.selected_option_ids),
            "selected_values": list(self.selected_values),
        }


async def adjudicate_pending_question_answer(
    *,
    litellm_client: Any,
    completion_model_route: ResolvedCompletionModelRoute,
    conversation: list[ConversationMessage],
    user_message: str,
    before_provider_call: Callable[[], Awaitable[None]] | None = None,
) -> PendingQuestionResolution | None:
    pending = latest_pending_structured_question(conversation)
    if not isinstance(pending, dict):
        return None

    question_id = pending.get("question_id")
    question = pending.get("question")
    options = pending.get("options")
    if (
        not isinstance(question_id, str)
        or not isinstance(question, str)
        or not isinstance(options, list)
    ):
        return None

    valid_option_ids: dict[str, str] = {}
    for option in cast(list[object], options):
        if not isinstance(option, dict):
            continue
        option_dict = cast(dict[str, Any], option)
        option_id = option_dict.get("id")
        if not isinstance(option_id, str):
            continue
        option_value = option_dict.get("value", option_id)
        valid_option_ids[option_id] = (
            option_value if isinstance(option_value, str) else option_id
        )
    if not valid_option_ids:
        return None

    completion_kwargs = completion_model_route.filter_unsupported_model_kwargs(
        ModelKwargs(temperature=0.0)
    )
    if before_provider_call is not None:
        await before_provider_call()
    try:
        response = await litellm_client.acompletion(
            model=completion_model_route.litellm_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify a user's freeform answer to a structured question. "
                        "Return JSON only in the format "
                        '{"selected_option_id": string|null, "reason": string}.'
                    ),
                },
                {
                    "role": "user",
                    "content": _build_answer_prompt(
                        question=question,
                        options=cast(list[dict[str, Any]], options),
                        user_message=user_message,
                    ),
                },
            ],
            stream=False,
            drop_params=True,
            max_tokens=120,
            **completion_kwargs,
        )
    except Exception as error:
        record_ai_builder_provider_failure(
            error,
            stage="semantic_adjudication",
        )
        raise AIBuilderProviderOutcomeUnknownException() from error

    content = response.choices[0].message.content if response.choices else None
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        return None
    option_id = (
        cast(dict[str, Any], raw).get("selected_option_id")
        if isinstance(raw, dict)
        else None
    )
    if not isinstance(option_id, str) or option_id not in valid_option_ids:
        return None

    selected_value = valid_option_ids[option_id]
    return PendingQuestionResolution(
        question_id=question_id,
        selected_option_ids=(option_id,),
        selected_values=(selected_value,),
    )


def _build_answer_prompt(
    *,
    question: str,
    options: list[dict[str, Any]],
    user_message: str,
) -> str:
    option_lines: list[str] = []
    for option in options:
        option_id = option.get("id")
        label = option.get("label")
        description = option.get("description")
        if not isinstance(option_id, str) or not isinstance(label, str):
            continue
        suffix = (
            f" — {description}" if isinstance(description, str) and description else ""
        )
        option_lines.append(f"- {option_id}: {label}{suffix}")
    return (
        f"Question:\n{question}\n\n"
        f"Options:\n{chr(10).join(option_lines)}\n\n"
        f"User answer:\n{user_message}\n\n"
        "Return the best matching option id or null if the answer is too ambiguous."
    )
