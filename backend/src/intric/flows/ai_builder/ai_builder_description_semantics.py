"""Semantic signature and description provenance for AI Builder flows.

Owns the concept of "what kind of flow is this?" (entry input, terminal output)
and "who owns the description?" (manual vs builder-managed with hash tracking).
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Literal

from pydantic import BaseModel

from intric.flows.flow_authoring_spec import (
    StepSpec,
)


class FlowSemanticSignature(BaseModel):
    """Captures the semantic identity of a flow: what goes in and what comes out."""

    entry_input_type: str | None = None
    entry_input_source: str | None = None
    terminal_output_type: str | None = None
    terminal_output_mode: str | None = None

    @classmethod
    def from_steps(cls, steps: list[StepSpec]) -> FlowSemanticSignature:
        if not steps:
            return cls()
        entry = steps[0]
        terminal = steps[-1]
        return cls(
            entry_input_type=entry.input_type.value,
            entry_input_source=entry.input_source.value,
            terminal_output_type=terminal.output_type.value,
            terminal_output_mode=terminal.output_mode.value,
        )

    def has_semantic_change(self, other: FlowSemanticSignature) -> bool:
        return self != other


class DescriptionProvenance(BaseModel):
    """Tracks who owns a flow description and when it was last generated."""

    mode: Literal["manual", "builder_managed"] = "manual"
    semantic_signature: FlowSemanticSignature | None = None
    last_generated_hash: str | None = None
    version: int = 1


def description_hash(text: str | None) -> str:
    normalized = (text or "").strip().replace("\r\n", "\n")
    normalized = unicodedata.normalize("NFC", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


_description_hash = description_hash
