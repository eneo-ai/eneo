"""Orchestrates attachment observation end-to-end.

`observe_attachment_with_cache` is the entry point the upload pipeline
calls: it composes deterministic signal extraction, sha256 content
addressing, per-tenant cache lookup, the LLM observation call, and
persistence into one reusable function. The function is pure in the
sense that every collaborator is injected — repo, LLM client, and
deterministic extractor — so the caller swaps them for tests without
patching imports.

Cache semantics: a hit returns the persisted observation without
touching the LLM. A miss runs the signal extractor and the LLM
observation call, then persists the resulting row for future hits.
When the LLM observation fails (see `observe_attachment`), the cache
is NOT populated with a null row — the next upload re-attempts
instead of inheriting a prior transient failure.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable
from uuid import UUID

from intric.flows.ai_builder.attachment_observation import (
    AttachmentObservation,
    DeterministicSignals,
)
from intric.flows.ai_builder.attachment_observation_repo import (
    AttachmentObservationRepo,
)
from intric.flows.ai_builder.attachment_observer import observe_attachment
from intric.flows.ai_builder.deterministic_signals_extractor import (
    extract_deterministic_signals,
)

DeterministicExtractor = Callable[..., DeterministicSignals]
ObserverFn = Callable[..., Any]


async def observe_attachment_with_cache(
    *,
    repo: AttachmentObservationRepo,
    litellm_client: Any,
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    tenant_id: UUID,
    digest_version: int,
    fcm_version: int,
    pattern_registry_version: int,
    filename: str,
    mime: str,
    raw_bytes: bytes,
    content_sample: str,
    content_sample_char_budget: int = 4_000,
    max_output_tokens: int = 1_500,
    extractor: DeterministicExtractor = extract_deterministic_signals,
    observer: ObserverFn = observe_attachment,
) -> AttachmentObservation | None:
    """Return the cached or freshly-observed attachment observation.

    Miss path: extractor runs on `raw_bytes`, observer produces the
    full observation, repo persists the row. A failed observer call
    returns ``None`` without touching the cache so transient LLM
    failures don't poison the per-tenant row.

    Hit path: no extractor run, no LLM call, no observer. The cached
    observation is returned verbatim; `last_accessed_at` is bumped
    by the repo so LRU pruning reflects recent use.

    `extractor` and `observer` are injected for testability. Production
    callers use the module-level defaults.
    """
    content_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    cached = await repo.get(
        tenant_id=tenant_id,
        content_sha256=content_sha256,
        digest_version=digest_version,
        fcm_version=fcm_version,
        pattern_registry_version=pattern_registry_version,
    )
    if cached is not None:
        return cached

    signals = extractor(
        raw_bytes=raw_bytes,
        mime=mime,
        filename=filename,
    )
    observation = await observer(
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        tenant_id=tenant_id,
        content_sha256=content_sha256,
        digest_version=digest_version,
        fcm_version=fcm_version,
        pattern_registry_version=pattern_registry_version,
        filename=filename,
        mime=mime,
        signals=signals,
        content_sample=content_sample,
        content_sample_char_budget=content_sample_char_budget,
        max_output_tokens=max_output_tokens,
    )
    if observation is None:
        return None

    await repo.upsert(observation=observation, signals=signals)
    return observation
