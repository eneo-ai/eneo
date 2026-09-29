"""The requester's intake answers, rendered once, given to every arm alike.

A case configures the answers its synthetic requester gives when the Builder
asks an intake question (`question_answer_overrides`). The Builder arm meets
them only for the questions it asks; an arm that authors without a Builder
would otherwise see all of them, which is unequal information. The oracle
experiment therefore gives both arms the same text up front: the Builder's
first message is the request followed by this block, and the expert author
reads the same block. `intake_message` is the one function that builds it, so
the two cannot drift, and its digest is recorded in the receipt of each leg.

A pure leaf: standard library plus the question catalog.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, cast

ANSWERS_HEADING = "Mina svar på frågor om flödet:"


def render_answers(overrides: Mapping[str, Any]) -> str:
    """The configured answers in words: the catalog's question and the chosen option."""

    from eneo.flows.ai_builder.question_catalog import (
        QUESTION_CATALOG,
        render_question,
    )

    lines = [ANSWERS_HEADING]
    for slot, answer in overrides.items():
        answer = cast(Mapping[str, Any], answer)
        question = render_question(slot, "sv") if slot in QUESTION_CATALOG else None
        heading = question.question if question is not None else slot
        if "selected_option_id" in answer:
            chosen = str(answer["selected_option_id"])
            option = next(
                (o for o in (question.options if question else ()) if o.id == chosen),
                None,
            )
            lines.append(f"- {heading}")
            lines.append(
                f"  - Svar: {option.label if option else chosen}"
                + (f" ({option.description})" if option and option.description else "")
            )
        elif "input_fields" in answer:
            lines.append(f"- {heading}")
            lines.append("  - Formulärfält som den som kör flödet fyller i:")
            for item in cast(list[Mapping[str, Any]], answer["input_fields"]):
                value = cast(Mapping[str, Any], item.get("value") or {})
                options = value.get("options") or []
                lines.append(
                    f"    - `{value.get('name')}` ({value.get('type')}, "
                    f"{'obligatoriskt' if value.get('required') else 'valfritt'}): "
                    f"{value.get('label')}"
                    + (f"; alternativ: {', '.join(options)}" if options else "")
                )
        else:
            lines.append(f"- {heading}: {json.dumps(answer, ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def join_intake(prompt: str, answers_block: str) -> str:
    """The request as an arm receives it: the prompt, then the answers block.

    The one join. An arm's first message and the staged author brief
    (`request.md` and `answers.md`, the latter empty when a case has no
    answers) are both put together by it, and a freeze recomputes the digest
    from the staged bytes with it.
    """

    return f"{prompt}\n\n{answers_block}" if answers_block else prompt


def intake_message(prompt: str, overrides: Mapping[str, Any] | None) -> str:
    """The request as an arm receives it up front: the prompt, then the answers.

    `overrides` is the case's RESOLVED answers (`configured_question_answers`:
    the synthetic profile's answers with the case's own on top), never the raw
    case overrides.
    """

    return join_intake(prompt, render_answers(overrides) if overrides else "")


def intake_sha256(prompt: str, overrides: Mapping[str, Any] | None) -> str:
    return hashlib.sha256(intake_message(prompt, overrides).encode("utf-8")).hexdigest()


def staged_intake_sha256(request_md: bytes, answers_md: bytes) -> str:
    """The digest of the brief exactly as staged, from its bytes alone."""

    return hashlib.sha256(
        join_intake(request_md.decode("utf-8"), answers_md.decode("utf-8")).encode(
            "utf-8"
        )
    ).hexdigest()
