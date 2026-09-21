"""Validated prefixes imported into a new run, separate from provider execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from eneo.flows.domain.flow import FlowStepResult
from eneo.flows.domain.transcript_source import TranscriptSource


@dataclass(frozen=True)
class FlowRunPrefixSeed:
    source_run_id: UUID
    results: tuple[FlowStepResult, ...]
    provenance: dict[str, Any]
    kind: Literal["reviewed_transcript_snapshot", "reused_prefix"]
    review_established_step_ids: frozenset[UUID] = frozenset()
    transcript: str | None = None
    transcript_sources: Mapping[UUID, TranscriptSource] = field(
        default_factory=dict[UUID, TranscriptSource]
    )
