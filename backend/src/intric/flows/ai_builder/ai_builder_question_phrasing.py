"""AI phrasing for a deterministic clarification question.

The deterministic engine decides which question to ask; slot identity, the
question id, and the answer options stay catalog-owned. This module only
rewrites the human-facing preamble into warmer, example-led copy, and escalates
the wording when the same question has already gone unanswered. It returns
``None`` on any failure so the caller keeps the canonical catalog wording — the
model can improve phrasing but never change what is asked.
"""

from __future__ import annotations

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
    question_id: str,
    ask_count: int,
    ui_language: str | None,
    tenant_id: UUID,
) -> str | None:
    """Rewrite a clarification preamble into friendlier, example-led copy.

    Returns the improved text, or ``None`` to fall back to ``baseline_text``.
    """
    if not baseline_text.strip():
        return None
    try:
        response = await litellm_client.acompletion(
            model=litellm_model,
            messages=_build_phrasing_prompt(baseline_text, ask_count, ui_language),
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
    baseline_text: str,
    ask_count: int,
    ui_language: str | None,
) -> list[dict[str, str]]:
    language = "English" if ui_language == "en" else "Swedish"
    system = (
        f"You rewrite a flow-builder clarification question into warm, concrete "
        f"{language} for a non-technical municipality user. Keep the exact same "
        "meaning and the same decision being asked. Add one short concrete "
        "example so it is easy to answer. Keep it to 1-3 sentences. Never invent "
        "new options, never change what is asked, never add markdown. Return only "
        "the rewritten question text."
    )
    reask = (
        "The user has already been asked this and has not answered clearly. "
        "Rephrase it differently and more concretely with a helpful example "
        "rather than repeating the same wording.\n\n"
        if ask_count >= 1
        else ""
    )
    user = f"{reask}Question to rewrite:\n{baseline_text}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
