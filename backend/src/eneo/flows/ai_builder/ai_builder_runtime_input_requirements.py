"""Reduced provider projection of confirmed runtime input requirements."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eneo.flows.ai_builder.planning_state import RuntimeMetadataFieldPurpose


@dataclass(frozen=True, slots=True)
class ConfirmedRuntimeInputRequirement:
    """Exact provider-visible identity and purpose for one runtime field."""

    name: str
    purpose: RuntimeMetadataFieldPurpose


def proposal_steps_declare_runtime_input_reads(
    requirements: tuple[ConfirmedRuntimeInputRequirement, ...],
    *,
    is_pure_audio_transcription: bool,
) -> bool:
    """Whether create steps may list the confirmed runtime inputs they read."""

    return bool(requirements) and not is_pure_audio_transcription


def render_confirmed_runtime_input_requirements(
    requirements: tuple[ConfirmedRuntimeInputRequirement, ...],
) -> str:
    """Render exact identities as delimited JSON records without truncation."""

    return json.dumps(
        [
            {"name": requirement.name, "purpose": requirement.purpose}
            for requirement in requirements
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
