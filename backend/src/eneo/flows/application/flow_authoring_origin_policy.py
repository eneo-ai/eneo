from __future__ import annotations

from typing import Protocol

from eneo.flows.application.flow_draft_materialization import FlowDraftChangeSet
from eneo.flows.domain.flow import Flow
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore


class FlowAuthoringOriginPolicy(Protocol):
    def effective_spec(
        self,
        *,
        spec: FlowDraftSpecCore,
        current_flow: Flow | None,
    ) -> FlowDraftSpecCore: ...

    def stamp_metadata(
        self,
        *,
        changeset: FlowDraftChangeSet,
    ) -> FlowDraftChangeSet: ...


class NoopFlowAuthoringOriginPolicy:
    def effective_spec(
        self,
        *,
        spec: FlowDraftSpecCore,
        current_flow: Flow | None,
    ) -> FlowDraftSpecCore:
        return spec

    def stamp_metadata(
        self,
        *,
        changeset: FlowDraftChangeSet,
    ) -> FlowDraftChangeSet:
        return changeset
