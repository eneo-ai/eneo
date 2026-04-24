"""LLM-backed observation pass for AI Builder attachments.

`observe_attachment` wraps a single structured-JSON litellm call that
turns raw attachment bytes + `DeterministicSignals` into an
`AttachmentObservation`. It is the only module allowed to invoke the
LLM for the observation tier; the caller owns byte sampling, cache
lookup, persistence, and prompt-budget policy above this layer.

The function is intentionally small. It:

1. Assembles a system + user prompt that passes the deterministic
   signals verbatim — the LLM must not contradict them — plus a
   truncated content sample so typical attachments stay within a
   bounded token budget regardless of upload size.
2. Invokes `litellm_client.acompletion` with ``response_format``
   ``{"type": "json_object"}`` and ``drop_params=True`` so providers
   without JSON mode silently fall back to plain completion.
3. Parses the JSON response, merges the caller-owned identity /
   version / token_count fields, and returns a fully-validated
   `AttachmentObservation` — or ``None`` on any failure so the
   caller can log and fall back rather than crash the upload
   pipeline.
"""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

from pydantic import ValidationError

from intric.flows.ai_builder.attachment_observation import (
    AttachmentObservation,
    DeterministicSignals,
)
from intric.main.logging import get_logger

logger = get_logger(__name__)


_DEFAULT_CONTENT_SAMPLE_CHAR_BUDGET: int = 4_000
_DEFAULT_MAX_OUTPUT_TOKENS: int = 1_500


_SYSTEM_PROMPT = (
    "You observe one file upload and return structured planning "
    "evidence as JSON. You never generate the flow itself — you "
    "describe what the attachment is, what it implies, and what "
    "information is still missing.\n\n"
    "HARD RULES\n"
    "- Return ONE JSON object matching the contract below. No prose, "
    "no markdown fences, no explanations outside the JSON.\n"
    "- The deterministic signals in the user message are GROUND "
    "TRUTH. Never contradict them (no calling a 40-page document "
    "'one page', no claiming placeholders when the signal set is "
    "empty).\n"
    "- `kind` must be one of: template, form, example_output, "
    "reference, input_exemplar, transcript, spec, policy.\n"
    "- Every `confidence` is in [0.0, 1.0].\n"
    "- `capability_relevance` maps capability-IDs (e.g. "
    "`document_to_docx_template`, `extract_structured_fields`, "
    "`summarize_text`, `audio_transcription`) to a relevance score in "
    "[0.0, 1.0].\n"
    "- Keep `digest_text` under 500 tokens; it is the planner-facing "
    "summary.\n\n"
    "JSON CONTRACT\n"
    "{\n"
    '  "kind": "<AttachmentKind>",\n'
    '  "structure": {\n'
    '    "has_placeholders": <bool>,\n'
    '    "has_form_fields": <bool>,\n'
    '    "has_sections": <bool>,\n'
    '    "has_tables": <bool>,\n'
    '    "has_hierarchy": <bool>,\n'
    '    "has_unfilled_fields": <bool>\n'
    "  },\n"
    '  "digest_text": "<short planner-facing summary>",\n'
    '  "structured_fallback": null | {"mode": "dense_text"|"structural_schema", "content": "<str>"},\n'
    '  "likely_planner_implications": [\n'
    '    {"suggested_pattern_id": "<str>", "confidence": <float>, "reason": "<str>"}\n'
    "  ],\n"
    '  "missing_info_cues": ["<str>", ...],\n'
    '  "capability_relevance": {"<capability_id>": <float>, ...},\n'
    '  "likely_questions_triggered": ["<question_template_id>", ...]\n'
    "}"
)


async def observe_attachment(
    *,
    litellm_client: Any,
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    tenant_id: UUID,
    content_sha256: str,
    digest_version: int,
    fcm_version: int,
    pattern_registry_version: int,
    filename: str,
    mime: str,
    signals: DeterministicSignals,
    content_sample: str,
    content_sample_char_budget: int = _DEFAULT_CONTENT_SAMPLE_CHAR_BUDGET,
    max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS,
) -> AttachmentObservation | None:
    """Observe one attachment and return structured planning evidence.

    Returns the validated `AttachmentObservation` on success, or
    ``None`` if the LLM call fails, returns empty content, yields
    malformed JSON, or produces JSON that does not satisfy the
    schema. Every failure path logs a warning so upload-pipeline
    telemetry can still surface rates; nothing is raised so the
    caller can cache a null observation and move on.

    `content_sample_char_budget` clips the user-provided sample
    before the LLM sees it — the observation cost per attachment
    stays bounded regardless of upload size. The clip is a prefix
    slice because the planner needs the beginning of the document
    (title, first section) more than the end.
    """
    clipped_sample = content_sample[:content_sample_char_budget]
    messages = _build_messages(
        filename=filename,
        mime=mime,
        signals=signals,
        content_sample=clipped_sample,
    )

    try:
        response = await litellm_client.acompletion(
            model=litellm_model,
            messages=messages,
            stream=False,
            drop_params=True,
            max_tokens=max_output_tokens,
            temperature=0.0,
            response_format={"type": "json_object"},
            **litellm_kwargs,
        )
    except Exception as error:
        logger.warning(
            "Attachment observation LLM call failed",
            exc_info=error,
            extra={"attachment_filename": filename, "attachment_mime": mime},
        )
        return None

    content = response.choices[0].message.content if response.choices else None
    if not isinstance(content, str) or not content.strip():
        logger.warning(
            "Attachment observation returned empty content",
            extra={"attachment_filename": filename, "attachment_mime": mime},
        )
        return None

    try:
        parsed: Any = json.loads(content)
    except json.JSONDecodeError as error:
        logger.warning(
            "Attachment observation response is not JSON",
            exc_info=error,
            extra={"attachment_filename": filename, "attachment_mime": mime},
        )
        return None

    if not isinstance(parsed, dict):
        logger.warning(
            "Attachment observation JSON is not an object",
            extra={"attachment_filename": filename, "attachment_mime": mime},
        )
        return None

    llm_payload = cast(dict[str, Any], parsed)
    digest_text = llm_payload.get("digest_text")
    token_count = _estimate_token_count(
        digest_text if isinstance(digest_text, str) else ""
    )

    merged: dict[str, Any] = {
        **llm_payload,
        "tenant_id": str(tenant_id),
        "content_sha256": content_sha256,
        "digest_version": digest_version,
        "fcm_version": fcm_version,
        "pattern_registry_version": pattern_registry_version,
        "token_count": token_count,
    }

    try:
        return AttachmentObservation.model_validate(merged)
    except ValidationError as error:
        logger.warning(
            "Attachment observation schema validation failed",
            exc_info=error,
            extra={"attachment_filename": filename, "attachment_mime": mime},
        )
        return None


def _build_messages(
    *,
    filename: str,
    mime: str,
    signals: DeterministicSignals,
    content_sample: str,
) -> list[dict[str, Any]]:
    signals_json = signals.model_dump_json(indent=2)
    user_content = (
        f"Filename: {filename}\n"
        f"Declared MIME: {mime}\n\n"
        "Deterministic signals (GROUND TRUTH — never contradict):\n"
        f"{signals_json}\n\n"
        "Content sample (prefix, may be truncated):\n"
        f"---\n{content_sample}\n---\n\n"
        "Return the JSON observation now."
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _estimate_token_count(digest_text: str) -> int:
    """Cheap whitespace-split token estimate.

    Deterministic and reproducible so identical observations hash to
    the same token_count in the cache. Upgrading to a real tokenizer
    is deferred until budget-aware retrieval needs precise numbers;
    the whitespace heuristic correlates well enough with tokeniser
    output for the planner's budget-sizing decisions.
    """
    return len(digest_text.split())
