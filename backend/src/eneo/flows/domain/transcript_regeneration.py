"""A reviewed prefix imported into a new run, separate from provider execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from eneo.flows.domain.flow import FlowStepResult


@dataclass(frozen=True)
class TranscriptRegenerationSeed:
    source_run_id: UUID
    transcript_step_id: UUID
    transcript: str
    provenance: dict[str, Any]
    # Only the validated transcription prefix is reused. All later steps remain pending.
    results: tuple[FlowStepResult, ...]
