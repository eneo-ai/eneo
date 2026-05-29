"""AI phrasing for a deterministic clarification question.

The deterministic engine decides which question to ask; slot identity, the
question id, and the answer options stay catalog-owned. This module only
rewrites the conversational lead-in into warmer, example-led copy, and escalates
the wording when the same question has already gone unanswered. The model is
shown the actual question and its options so the rewritten lead-in stays aligned
with what is really being asked, but it returns text only and never the
structured payload. Any failure returns ``None`` so the caller keeps the
canonical catalog wording.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from intric.main.logging import get_logger

logger = get_logger(__name__)


async def phrase_clarification_question(
    *,
    litellm_client: Any,
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    baseline_text: str,
    question_text: str,
    options: Sequence[str],
    question_id: str,
    ask_count: int,
    ui_language: str | None,
    tenant_id: UUID,
) -> str | None:
    """Rewrite a clarification lead-in into friendlier, example-led copy.

    The model sees the deterministic ``question_text`` and ``options`` so the
    rewritten lead-in stays aligned with what is asked; it returns text only, or
    ``None`` to fall back to ``baseline_text``.
    """
    if not baseline_text.strip():
        return None
    try:
        response = await litellm_client.acompletion(
            model=litellm_model,
            messages=_build_phrasing_prompt(
                baseline_text=baseline_text,
                question_text=question_text,
                options=options,
                ask_count=ask_count,
                ui_language=ui_language,
            ),
            stream=False,
            drop_params=True,
            max_tokens=400,
            temperature=0.4,
            **litellm_kwargs,
        )
    except Exception:
        logger.warning(
            "AI Builder question phrasing failed",
            exc_info=True,
            extra={
                "tenant_id": str(tenant_id),
                "model": litellm_model,
                "question_id": question_id,
            },
        )
        return None

    content = response.choices[0].message.content if response.choices else None
    if not isinstance(content, str) or not content.strip():
        return None
    return content.strip()


def _build_phrasing_prompt(
    *,
    baseline_text: str,
    question_text: str,
    options: Sequence[str],
    ask_count: int,
    ui_language: str | None,
) -> list[dict[str, str]]:
    language = "English" if ui_language == "en" else "Swedish"
    system = (
        "You rewrite the conversational lead-in to a flow-builder clarification "
        f"question into warm, concrete {language} for a non-technical municipality "
        "user. The user will then see a fixed question with fixed clickable options "
        "(given below). Keep the same meaning and the same choices, add one short "
        "concrete example drawn from the options, and keep it to 1-3 sentences. "
        "Never invent or contradict options, never add markdown. Return only the "
        "rewritten lead-in text."
    )
    options_block = "\n".join(f"- {option}" for option in options) or "- (free text)"
    reask = (
        "The user has already been asked this and has not answered clearly. "
        "Rephrase the lead-in differently and more concretely with a helpful "
        "example rather than repeating the same wording.\n\n"
        if ask_count >= 1
        else ""
    )
    user = (
        f"{reask}"
        f"Question the user will see:\n{question_text}\n\n"
        f"Clickable options:\n{options_block}\n\n"
        f"Current lead-in to rewrite:\n{baseline_text}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
