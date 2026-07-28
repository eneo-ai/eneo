"""Typed Flow runtime invariant failures."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from eneo.flows.domain.flow_invariant_exceptions import FlowInvariantError


class FlowRuntimeInvariantError(FlowInvariantError):
    pass


@dataclass(frozen=True, slots=True)
class FlowPublishedDefinitionWithoutExecutableStepsError(FlowRuntimeInvariantError):
    flow_id: UUID
    flow_version: int

    def __str__(self) -> str:
        return (
            "Published flow version does not contain executable steps "
            f"(flow_id={self.flow_id}, flow_version={self.flow_version})."
        )


class MappedEvidenceNestingError(FlowRuntimeInvariantError):
    """A mapped step's call recorded a mapped envelope of its own.

    Mapped execution fans out over inputs exactly once, so evidence nests one
    level. Anything deeper means a call was assembled from another mapped step,
    which the runtime does not build — failing here keeps a structure the
    aggregates cannot describe from being recorded as if they could.
    """
