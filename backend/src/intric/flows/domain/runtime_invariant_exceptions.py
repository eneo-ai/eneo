"""Typed Flow runtime invariant failures."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from intric.flows.domain.flow_invariant_exceptions import FlowInvariantError


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
