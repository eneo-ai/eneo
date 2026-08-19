"""Stable-schema failure-event log contract.

Terminal failure paths across the codebase should emit one structured
log line via `log_failure_event`. The shape is deliberately minimal
and Pydantic-free: a TypedDict gives IDEs and grep-friendly schemas
without a domain-model ceremony that would outgrow its first use.

Why a convention rather than an object graph:

- The primary consumer is the log query. ``rg '"event":
  "ai_builder.failure"'`` and ``rg '"failure_fingerprint": "abc12345"'``
  need to work without tooling.
- The secondary consumer is an AI agent or human operator running
  replay / repro flows. Stable field names are the interface contract;
  a Pydantic class would force every caller into the orbit of one
  module and complicate Pydantic V2 / V3 migrations.
- The tertiary consumer is a future dashboarding layer (if we ever
  build one). A flat dict slots into any structured-log shipper.

Required fields on every failure event:

- ``event`` — canonical namespaced string, e.g. ``ai_builder.failure``.
  Shared across a component so one query surfaces every terminal
  failure for that component.
- ``schema_version`` — integer bumped on breaking additions so log
  queries can gate on schema shape.
- ``component`` — coarse source label (``ai_builder``, ``flows``,
  ``assistants``).
- ``operation`` — specific operation that failed (``planner_turn``,
  ``flow_dispatch``, ``attachment_upload``).
- ``failure_kind`` — taxonomy slot the operator would pivot on
  (``parse_failed``, ``rejected``, ``upstream_timeout``).
- ``failure_code`` — fine-grained discriminator within ``failure_kind``
  (a ``RejectionCode`` value, a ``parse_error_kind``, an HTTP status).
- ``failure_fingerprint`` — short deterministic hash clustering
  recurring failures without leaking the raw body.
- ``request_id``, ``session_id``, ``tenant_id`` — correlation handles.
- ``replay_handle`` — a flat dict carrying the inputs a replay CLI
  needs to reconstruct the failing turn (session id, prompt hashes,
  planning-state version). Never carries PII.
- ``safe_detail`` — a sanitized discriminator payload (Pydantic
  ``loc/type`` summary, rejection detail, sanitized state snapshot).
  Never carries raw LLM output, attachment bytes, or user prompts.

Callers populate what they have; absent fields become ``None`` in the
log row. The TypedDict carries ``total=False`` so a caller may elide
fields it cannot fill, but the four first fields
(``event``, ``schema_version``, ``component``, ``operation``) are
always required and enforced by `log_failure_event` at runtime.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Final, TypedDict

FAILURE_EVENT_SCHEMA_VERSION: Final[int] = 1


class FailureEvent(TypedDict, total=False):
    event: str
    schema_version: int
    component: str
    operation: str
    failure_kind: str
    failure_code: str | None
    failure_fingerprint: str | None
    request_id: str | None
    session_id: str | None
    tenant_id: str | None
    replay_handle: dict[str, Any] | None
    safe_detail: dict[str, Any] | None


def log_failure_event(
    logger: logging.Logger,
    *,
    event: str,
    component: str,
    operation: str,
    failure_kind: str,
    failure_code: str | None = None,
    failure_fingerprint: str | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    tenant_id: str | None = None,
    replay_handle: dict[str, Any] | None = None,
    safe_detail: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit a stable-schema failure event on the provided logger.

    `extra` is any caller-specific context that doesn't fit the core
    schema — merged into the log row AFTER the core fields so a
    caller cannot accidentally shadow them. The core schema always
    wins on key collisions.
    """
    payload: dict[str, Any] = {
        "event": event,
        "schema_version": FAILURE_EVENT_SCHEMA_VERSION,
        "component": component,
        "operation": operation,
        "failure_kind": failure_kind,
        "failure_code": failure_code,
        "failure_fingerprint": failure_fingerprint,
        "request_id": request_id,
        "session_id": session_id,
        "tenant_id": tenant_id,
        "replay_handle": replay_handle,
        "safe_detail": safe_detail,
    }
    if extra is not None:
        merged = dict(extra)
        merged.update(payload)
        payload = merged
    logger.info("failure_event", extra=payload)


def make_failure_fingerprint(*parts: str | int | None) -> str:
    """Hash the given parts into a short, stable failure fingerprint.

    Callers build a fingerprint from a small set of discriminators
    that cluster recurring failures — e.g.
    ``(failure_kind, failure_code, first-level loc or action_kind)``.
    The digest is deterministic and short (12 hex chars) so log
    queries and canary-fixture filenames can reuse it.

    Passing ``None`` renders as an empty segment so callers do not
    have to branch on optional discriminators.
    """
    serialized = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]


def stable_hash(value: str) -> str:
    """Return a short stable hash for prompt / schema fingerprinting.

    Used for ``planner_prompt_hash`` and similar — gives
    cross-deploy deterministic identifiers so log queries can
    group turns that ran against the same prompt/schema assembly
    without carrying the bytes themselves.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def schema_fingerprint(schema: dict[str, Any]) -> str:
    """Stable hash of a Pydantic `model_json_schema()` dict.

    The dict is serialized with ``sort_keys=True`` so the hash does
    not flip across Python dict-insertion-order changes. Useful for
    detecting silent schema drift when the planner contract shape
    changes under us.
    """
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return stable_hash(canonical)


__all__ = [
    "FAILURE_EVENT_SCHEMA_VERSION",
    "FailureEvent",
    "log_failure_event",
    "make_failure_fingerprint",
    "schema_fingerprint",
    "stable_hash",
]
