"""Validated prefixes imported into a new run, separate from provider execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from eneo.flows.domain.flow import FlowStepResult
from eneo.flows.domain.step_output import InlineTranscript
from eneo.flows.domain.transcript_source import TranscriptSource


@dataclass(frozen=True)
class FlowRunPrefixSeed:
    source_run_id: UUID
    results: tuple[FlowStepResult, ...]
    provenance: dict[str, Any]
    kind: Literal["reviewed_transcript_snapshot", "reused_prefix"]
    review_established_step_ids: frozenset[UUID] = frozenset()
    transcript: InlineTranscript | None = None
    transcript_sources: Mapping[UUID, TranscriptSource] = field(
        default_factory=dict[UUID, TranscriptSource]
    )
    # The source run's speaker-label choice, accepted when that run was created.
    # It is kept as it is; only a caller's new choice is checked against what
    # the run contract offers now.
    speaker_labels: bool | None = None
