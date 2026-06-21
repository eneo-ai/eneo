from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from intric.flows.application.flow_authoring_command import (
    AIBuilderFlowAuthoringOrigin,
    CreateFlowAuthoringCommand,
    FlowAuthoringCommandService,
)
from intric.flows.application.flow_draft_materialization import (
    FlowDraftStepChangeKind,
)
from intric.flows.flow_authoring_spec import FlowDraftSpecCore


async def assert_create_spec_prepares_through_authoring_command_async(
    spec: FlowDraftSpecCore,
) -> None:
    prepared = await FlowAuthoringCommandService().prepare(
        command=CreateFlowAuthoringCommand(
            space_id=uuid4(),
            spec=spec,
            origin=AIBuilderFlowAuthoringOrigin(
                session_id=uuid4(),
                plan_id=uuid4(),
                spec_hash=spec.spec_hash(),
                applied_at=datetime.now(UTC),
            ),
        ),
        flow_service=MagicMock(),
    )

    assert prepared.preview.steps_created == len(prepared.spec.steps)
    assert prepared.preview.steps_updated == 0
    assert prepared.preview.steps_removed == 0
    assert {step.change_kind for step in prepared.preview.step_changes} == {
        FlowDraftStepChangeKind.ADDED
    }
    assert prepared.preview.spec_hash == prepared.spec.spec_hash()


def assert_create_spec_prepares_through_authoring_command(
    spec: FlowDraftSpecCore,
) -> None:
    # Sync tests use this wrapper; async tests call the coroutine to avoid nesting event loops.
    asyncio.run(assert_create_spec_prepares_through_authoring_command_async(spec))
