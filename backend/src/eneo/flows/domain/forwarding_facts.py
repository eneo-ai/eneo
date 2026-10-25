"""Forwarding facts: how much of one model call's input repeats across the
call's inputs and reaches its output, measured by the worker while the text is
in memory.

The facts hold numbers and edge indexes only, never text. An edge index points
into the attempt's resolved input edges
(``flow_step_attempt_resolved_inputs.resolved_input_edges_jsonb``), so a reader
joins the facts to the edges' producers, hashes and sizes without reading any
content.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from eneo.flows.domain.canonical_json_hash import canonical_json_bytes
from eneo.flows.flow_run_provenance import (
    FLOW_RESOLVED_INPUT_MAX_EDGES,
    FlowResolvedInputEdgeIndex,
)

FORWARDING_FACTS_SCHEMA_VERSION: Literal[1] = 1
# Words per shingle. Eight words rarely repeat by chance in prose, while a
# quote, a copied paragraph or a relayed transcript shares nearly all of them.
FORWARDING_FACTS_SHINGLE_WORDS: Final = 8
# The stored JSON stays small next to the edges it describes (one entry per
# edge, about a hundred bytes each).
FORWARDING_FACTS_MAX_CANONICAL_BYTES: Final = 512 * 1024

ForwardingFactsNotMeasuredReason = Literal[
    "cpu_budget_exceeded",
    "computation_failed",
]

_Ratio = Annotated[float, Field(ge=0.0, le=1.0)]


def _sorted_unique_indexes(
    indexes: tuple[FlowResolvedInputEdgeIndex, ...],
) -> tuple[FlowResolvedInputEdgeIndex, ...]:
    if indexes != tuple(sorted(set(indexes))):
        raise ValueError("Edge indexes must be sorted and unique.")
    return indexes


class _ForwardingFactsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ForwardingEdgeFacts(_ForwardingFactsModel):
    """What one input edge of the call shares with the other edges and with
    the output."""

    edge_index: FlowResolvedInputEdgeIndex = Field(
        description="Index of the edge among the attempt's resolved input edges."
    )
    byte_size: int = Field(
        strict=True,
        ge=0,
        description="UTF-8 size of the edge's selected value, as the edge records it.",
    )
    shingle_count: int = Field(
        strict=True,
        ge=0,
        description=(
            "Shingles measured for this edge, after sampling. Zero for a value "
            "shorter than one shingle."
        ),
    )
    sample_every: int = Field(
        strict=True,
        ge=1,
        description="1 when every shingle was measured; k when every k-th was.",
    )
    repeated_bytes: int = Field(
        strict=True,
        ge=0,
        description=(
            "Bytes of this edge whose shingles also occur in another edge of the "
            "same call: the share of its words covered by such shingles, times "
            "its byte size."
        ),
    )
    copied_to_output_ratio: _Ratio | None = Field(
        description=(
            "Share of the output's shingles found in this edge. Null when the "
            "output is shorter than one shingle."
        ),
    )

    @model_validator(mode="after")
    def _repeated_bytes_fit_the_edge(self) -> ForwardingEdgeFacts:
        if self.repeated_bytes > self.byte_size:
            raise ValueError("repeated_bytes cannot exceed byte_size.")
        return self


class ForwardingFacts(_ForwardingFactsModel):
    """The forwarding facts of a model step attempt, measured on its first
    model call that returned output."""

    schema_version: Literal[1]
    measured: bool
    not_measured_reason: ForwardingFactsNotMeasuredReason | None = None
    shingle_words: Literal[8] = FORWARDING_FACTS_SHINGLE_WORDS
    call_count: int = Field(
        strict=True,
        ge=1,
        description=(
            "Model calls of the attempt that returned output. The facts describe "
            "the first; a mapped step makes one call per item."
        ),
    )
    edges: tuple[ForwardingEdgeFacts, ...] = Field(
        default=(), max_length=FLOW_RESOLVED_INPUT_MAX_EDGES
    )
    unmeasured_edge_indexes: Annotated[
        tuple[FlowResolvedInputEdgeIndex, ...],
        Field(max_length=FLOW_RESOLVED_INPUT_MAX_EDGES),
        AfterValidator(_sorted_unique_indexes),
    ] = Field(
        default=(),
        description=(
            "Edges of the call without text to measure: bound files, and values "
            "the worker did not hold."
        ),
    )
    output_byte_size: int = Field(default=0, strict=True, ge=0)
    output_shingle_count: int = Field(default=0, strict=True, ge=0)
    output_sample_every: int = Field(default=1, strict=True, ge=1)
    output_verbatim_ratio: _Ratio | None = Field(
        default=None,
        description=(
            "Share of the output's shingles found in any input edge of the call. "
            "Null when not measured or when the output is shorter than one shingle."
        ),
    )

    @field_validator("schema_version", mode="before")
    @classmethod
    def _schema_version_is_integer(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema_version must be the integer 1.")
        return value

    @model_validator(mode="after")
    def _consistent_and_bounded(self) -> ForwardingFacts:
        if self.measured == (self.not_measured_reason is not None):
            raise ValueError("A reason is given exactly when the call is not measured.")
        if not self.measured and (self.edges or self.output_verbatim_ratio is not None):
            raise ValueError("Facts that were not measured carry no measurements.")
        edge_indexes = [edge.edge_index for edge in self.edges]
        if edge_indexes != sorted(set(edge_indexes)):
            raise ValueError("Edge facts must be sorted by unique edge index.")
        if set(edge_indexes) & set(self.unmeasured_edge_indexes):
            raise ValueError("An edge is either measured or unmeasured.")
        canonical_size = len(canonical_json_bytes(self.model_dump(mode="json")))
        if canonical_size > FORWARDING_FACTS_MAX_CANONICAL_BYTES:
            raise ValueError(
                "Forwarding facts canonical JSON exceeds "
                f"{FORWARDING_FACTS_MAX_CANONICAL_BYTES} bytes."
            )
        return self


def not_measured_forwarding_facts(
    *,
    reason: ForwardingFactsNotMeasuredReason,
    call_count: int = 1,
) -> ForwardingFacts:
    return ForwardingFacts(
        schema_version=FORWARDING_FACTS_SCHEMA_VERSION,
        measured=False,
        not_measured_reason=reason,
        call_count=call_count,
    )


def parse_forwarding_facts(raw: object) -> ForwardingFacts | None:
    """The stored facts, or None when there are none or they cannot be read."""
    if raw is None:
        return None
    try:
        return ForwardingFacts.model_validate(raw)
    except (TypeError, ValueError):
        return None


__all__ = [
    "FORWARDING_FACTS_MAX_CANONICAL_BYTES",
    "FORWARDING_FACTS_SCHEMA_VERSION",
    "FORWARDING_FACTS_SHINGLE_WORDS",
    "ForwardingEdgeFacts",
    "ForwardingFacts",
    "ForwardingFactsNotMeasuredReason",
    "not_measured_forwarding_facts",
    "parse_forwarding_facts",
]
