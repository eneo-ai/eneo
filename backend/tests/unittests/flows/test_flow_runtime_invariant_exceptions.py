from __future__ import annotations

from uuid import uuid4

from intric.flows.domain.flow_invariant_exceptions import FlowPersistedIdMissingError
from intric.flows.domain.runtime_invariant_exceptions import (
    FlowPublishedDefinitionWithoutExecutableStepsError,
    FlowRuntimeInvariantError,
)


def test_runtime_invariants_exclude_persisted_flow_id_missing() -> None:
    assert not issubclass(FlowPersistedIdMissingError, FlowRuntimeInvariantError)
    assert issubclass(
        FlowPublishedDefinitionWithoutExecutableStepsError,
        FlowRuntimeInvariantError,
    )


def test_published_definition_without_executable_steps_error_carries_coordinates() -> (
    None
):
    flow_id = uuid4()

    exc = FlowPublishedDefinitionWithoutExecutableStepsError(
        flow_id=flow_id,
        flow_version=3,
    )

    assert exc.flow_id == flow_id
    assert exc.flow_version == 3
    assert "does not contain executable steps" in str(exc)
