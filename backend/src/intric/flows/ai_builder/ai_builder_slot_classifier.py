from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal, cast
from uuid import UUID

from intric.main.logging import get_logger

logger = get_logger(__name__)

SlotClassificationConfidence = Literal["high", "medium", "low"]

# Tenant id is intentionally log-only; classification depends on text and slot set.
_SLOT_CLASSIFICATION_CACHE: dict[str, "SlotClassificationResult"] = {}
_MAX_CACHE_ENTRIES = 128
UNKNOWN_SLOT_VALUE = "unknown"
_SLOT_CLASSIFICATION_RESPONSE_FORMAT: dict[str, object] = {"type": "json_object"}


@dataclass(frozen=True, slots=True)
class ClassifiedSlot:
    slot_name: str
    value: str
    confidence: SlotClassificationConfidence
    reason: str


@dataclass(frozen=True, slots=True)
class SlotClassificationResult:
    slots: tuple[ClassifiedSlot, ...] = ()
    assumptions: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    cached: bool = False


async def classify_slots(
    *,
    litellm_client: Any,
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    text: str,
    allowed_slot_values: Mapping[str, Collection[str]],
    tenant_id: UUID,
    ui_language: str | None = None,
) -> SlotClassificationResult | None:
    slot_values = _normalize_allowed_slot_values(allowed_slot_values)
    if not text.strip() or not slot_values:
        return None

    slot_names = tuple(slot_values.keys())
    cache_key = slot_classification_prompt_hash(
        text=text,
        ui_language=ui_language,
        slot_names=slot_names,
    )
    cached = _SLOT_CLASSIFICATION_CACHE.get(cache_key)
    if cached is not None:
        logger.info(
            "AI Builder slot classification cache hit",
            extra=_log_context(
                tenant_id=tenant_id,
                model=litellm_model,
                slot_names=slot_names,
                cached=True,
            ),
        )
        return replace(cached, cached=True)

    started_at = time.perf_counter()
    completion_kwargs = {
        **litellm_kwargs,
        "response_format": _SLOT_CLASSIFICATION_RESPONSE_FORMAT,
    }
    try:
        response = await litellm_client.acompletion(
            model=litellm_model,
            messages=_build_slot_classification_prompt(
                text=text,
                allowed_slot_values=slot_values,
                ui_language=ui_language,
            ),
            stream=False,
            drop_params=True,
            max_tokens=500,
            temperature=0.0,
            **completion_kwargs,
        )
    except Exception:
        logger.warning(
            "AI Builder slot classification failed",
            exc_info=True,
            extra=_log_context(
                tenant_id=tenant_id,
                model=litellm_model,
                slot_names=slot_names,
                cached=False,
            ),
        )
        return None

    content = response.choices[0].message.content if response.choices else None
    if not isinstance(content, str) or not content.strip():
        return None

    result = parse_slot_classification_response(
        content,
        allowed_slot_values=slot_values,
    )
    if result is None:
        return None

    _remember_cache(cache_key, result)
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    logger.info(
        "AI Builder slot classification completed",
        extra={
            **_log_context(
                tenant_id=tenant_id,
                model=litellm_model,
                slot_names=slot_names,
                cached=False,
            ),
            "accepted_slot_count": len(result.slots),
            "assumption_count": len(result.assumptions),
            "contradiction_count": len(result.contradictions),
            "elapsed_ms": elapsed_ms,
        },
    )
    return result


def parse_slot_classification_response(
    content: str,
    *,
    allowed_slot_values: Mapping[str, Collection[str]],
) -> SlotClassificationResult | None:
    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        return None

    if not isinstance(raw, dict):
        return None
    raw_dict = cast(dict[str, Any], raw)
    raw_slots = raw_dict.get("slots", [])
    if not isinstance(raw_slots, list):
        return None

    slot_values = _normalize_allowed_slot_values(allowed_slot_values)
    slots: list[ClassifiedSlot] = []
    seen_slot_names: set[str] = set()
    for item in cast(list[object], raw_slots):
        if not isinstance(item, dict):
            continue
        item_dict = cast(dict[str, Any], item)
        slot_name = item_dict.get("slot_name")
        value = item_dict.get("value")
        confidence = item_dict.get("confidence")
        reason = item_dict.get("reason")
        if not isinstance(slot_name, str) or slot_name not in slot_values:
            continue
        if slot_name in seen_slot_names:
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        normalized_value = value.strip()
        if (
            normalized_value != UNKNOWN_SLOT_VALUE
            and normalized_value not in slot_values[slot_name]
        ):
            continue
        if confidence not in {"high", "medium", "low"}:
            continue
        slots.append(
            ClassifiedSlot(
                slot_name=slot_name,
                value=normalized_value,
                confidence=confidence,
                reason=reason.strip()
                if isinstance(reason, str) and reason.strip()
                else "slot classification",
            )
        )
        seen_slot_names.add(slot_name)

    assumptions = tuple(
        item.strip()
        for item in cast(list[object], raw_dict.get("assumptions", []))
        if isinstance(item, str) and item.strip()
    )
    contradictions = tuple(
        item.strip()
        for item in cast(list[object], raw_dict.get("contradictions", []))
        if isinstance(item, str) and item.strip()
    )
    return SlotClassificationResult(
        slots=tuple(slots),
        assumptions=assumptions,
        contradictions=contradictions,
    )


def slot_classification_prompt_hash(
    *,
    text: str,
    ui_language: str | None,
    slot_names: Iterable[str],
) -> str:
    return hashlib.sha256(
        _classification_cache_payload(
            text=text,
            ui_language=ui_language,
            slot_names=slot_names,
        ).encode("utf-8")
    ).hexdigest()


def _build_slot_classification_prompt(
    *,
    text: str,
    allowed_slot_values: Mapping[str, frozenset[str]],
    ui_language: str | None,
) -> list[dict[str, str]]:
    dimension_lines = [
        f"- {slot_name}: {', '.join(sorted(values))}"
        for slot_name, values in sorted(allowed_slot_values.items())
    ]
    language_hint = (
        "Classify Swedish user intent."
        if ui_language != "en"
        else "Classify English user intent."
    )
    system = (
        "You classify unresolved flow-builder intent into constrained slot values. "
        "Return JSON only. Never explain outside the schema. "
        "Use a slot only when the conversation provides real evidence. "
        "Interpret natural Swedish and English phrasing by meaning, not by exact "
        "keywords. The allowed values are framework concepts, so choose a value only "
        "when a normal product user would reasonably expect that architecture. "
        "Distinguish runtime source material from intermediate work and final "
        "deliverables. Uploaded files are document input; pasted or typed prose is "
        "text input; uploaded or recorded speech for transcription is audio input. "
        "A requested final document is terminal_output, not primary input. "
        "If the final deliverable is a DOCX, Word, PDF, or document artifact, choose "
        "that artifact as terminal_output even when the document contains a readable "
        "report, memo, or summary. Treat structured JSON mentioned as helpful "
        "intermediate/API context as structured_analysis_need, not terminal_output, "
        "unless the user says the final response/output itself must be JSON. "
        "Readable summaries, memos, and reports are structured_text terminal output; "
        "machine-readable records or downstream integration payloads are "
        "structured_json terminal output. "
        "For runtime metadata, choose no_extra_metadata when all needed data comes "
        "from the source material and no separate per-run fields are requested. "
        "If the user says values should be derived from source material, do not "
        "classify that as runtime form fields. "
        "If still ambiguous, use value `unknown` with confidence `low` and explain "
        "what question should be asked in contradictions."
    )
    user = (
        f"{language_hint}\n\n"
        "Conversation summary:\n"
        f"{text}\n\n"
        "Unresolved slots and allowed values:\n"
        f"{chr(10).join(dimension_lines)}\n\n"
        "Return JSON with this shape:\n"
        "{"
        '"slots": [{"slot_name": str, "value": str, "confidence": "high"|"medium"|"low", "reason": str}], '
        '"assumptions": [str], '
        '"contradictions": [str]'
        "}\n"
        "Use only the listed slot_name values and option values."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _classification_cache_payload(
    *,
    text: str,
    ui_language: str | None,
    slot_names: Iterable[str],
) -> str:
    return json.dumps(
        {
            "text": text,
            "ui_language": ui_language,
            "slot_names": sorted(slot_names),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _normalize_allowed_slot_values(
    allowed_slot_values: Mapping[str, Collection[str]],
) -> dict[str, frozenset[str]]:
    return {
        slot_name: frozenset(value for value in values if value)
        for slot_name, values in sorted(allowed_slot_values.items())
        if slot_name and values
    }


def _remember_cache(key: str, result: SlotClassificationResult) -> None:
    if len(_SLOT_CLASSIFICATION_CACHE) >= _MAX_CACHE_ENTRIES:
        oldest_key = next(iter(_SLOT_CLASSIFICATION_CACHE))
        _SLOT_CLASSIFICATION_CACHE.pop(oldest_key, None)
    _SLOT_CLASSIFICATION_CACHE[key] = result


def _log_context(
    *,
    tenant_id: UUID,
    model: str,
    slot_names: Iterable[str],
    cached: bool,
) -> dict[str, object]:
    return {
        "tenant_id": str(tenant_id),
        "model": model,
        "slot_names": tuple(sorted(slot_names)),
        "cached": cached,
    }
