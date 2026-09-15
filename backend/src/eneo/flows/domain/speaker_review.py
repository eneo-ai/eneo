"""Effective attribution keeps model evidence independent of reviewer decisions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PROVISIONAL_SPEAKER = "Överlappande tal – osäker talare"
UNRESOLVED_SPEAKER = "Talare går inte att avgöra"


def effective_speaker(
    segment: Mapping[str, Any], decision: Mapping[str, Any] | None = None
) -> str | None:
    if decision is not None:
        if decision.get("decision") == "unresolved":
            return UNRESOLVED_SPEAKER
        return decision.get("speaker")
    if segment.get("speaker_attribution") == "provisional":
        return PROVISIONAL_SPEAKER
    return segment.get("speaker")


def attribution_text(
    segment: Mapping[str, Any], decision: Mapping[str, Any] | None = None
) -> str:
    speaker = effective_speaker(segment, decision)
    if speaker in (PROVISIONAL_SPEAKER, UNRESOLVED_SPEAKER):
        return f"[{speaker}]: "
    return f"{speaker}: " if speaker else ""
