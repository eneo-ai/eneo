"""The assistant a run step ran with, as the run reads it back.

Reclaiming a step assistant clears its id on run history (step results); the
run's version snapshot still names it. Every reader that returns step results
(the run steps endpoint and the evidence bundle) reads them through here.
"""

from __future__ import annotations

from collections.abc import Sequence

from eneo.flows.domain.flow import FlowStepResult, FlowVersion
from eneo.flows.published_definition import (
    PublishedDefinitionIntegrityStatus,
    inspect_published_definition_integrity,
    parse_verified_published_definition,
)


def with_snapshot_assistant_ids(
    step_results: Sequence[FlowStepResult], version: FlowVersion
) -> list[FlowStepResult]:
    """``step_results`` with a cleared assistant id replaced by the one the
    run's verified version snapshot names for that step. A snapshot that does
    not verify, or a step it does not name, leaves the id empty."""
    if all(result.assistant_id is not None for result in step_results):
        return list(step_results)
    integrity = inspect_published_definition_integrity(
        version.definition_json,
        expected_checksum=version.definition_checksum,
        flow_version=version.version,
    )
    if integrity.status is not PublishedDefinitionIntegrityStatus.VERIFIED:
        return list(step_results)
    named = {
        identity.step_id: identity.assistant_id
        for identity in parse_verified_published_definition(
            version.definition_json,
            expected_flow_id=version.flow_id,
            expected_checksum=version.definition_checksum,
            flow_version=version.version,
        ).step_identities
    }
    return [
        result
        if result.assistant_id is not None
        else result.model_copy(update={"assistant_id": named.get(result.step_id)})
        for result in step_results
    ]
