"""Validated prefixes imported into a new run, separate from provider execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from eneo.flows.domain.flow import FlowStepResult


@dataclass(frozen=True)
class FlowRunPrefixSeed:
    source_run_id: UUID
    results: tuple[FlowStepResult, ...]
    provenance: dict[str, Any]
    kind: Literal["reviewed_transcript_snapshot", "reused_prefix"]
    review_established_step_ids: frozenset[UUID] = frozenset()
    transcript: str | None = None
