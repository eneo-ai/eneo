from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.authentication.principal_types import PrincipalType
from eneo.flows import FlowFactory
from eneo.flows.domain.flow_run_exceptions import (
    FlowRunNotFoundError,
    FlowRunPersistenceInvariantError,
)
from eneo.flows.enums import FlowOutputType
from eneo.flows.flow_review_policy import FlowStepReviewMode
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.principal import FlowPrincipal


@pytest.mark.asyncio
async def test_create_or_get_review_checkpoint_raises_persistence_invariant_when_insert_and_lookup_return_no_row() -> (
    None
):
    session = AsyncMock()
    session.scalar.side_effect = [None, None]
    repo = FlowRunReviewCheckpointRepository(
        session=session,
        factory=FlowFactory(),
        audit_outbox_repo=AsyncMock(),
    )

    with pytest.raises(FlowRunPersistenceInvariantError) as exc_info:
        await repo.create_or_get_review_checkpoint_for_attempt(
            tenant_id=uuid4(),
            flow_id=uuid4(),
            flow_run_id=uuid4(),
            step_id=uuid4(),
            step_order=1,
            attempt_no=1,
            original_payload_json=None,
            current_payload_json=None,
            requester_principal_type=PrincipalType.USER,
            requester_user_id=uuid4(),
            requester_service_id=None,
            review_mode=FlowStepReviewMode.EDIT,
            output_type=FlowOutputType.JSON,
        )

    assert exc_info.value.operation == "create_review_checkpoint"


@pytest.mark.asyncio
async def test_approve_review_checkpoint_raises_flow_run_not_found_error_when_parent_run_is_missing() -> (
    None
):
    session = AsyncMock()
    session.scalar.return_value = None
    repo = FlowRunReviewCheckpointRepository(
        session=session,
        factory=FlowFactory(),
        audit_outbox_repo=AsyncMock(),
    )
    run_id = uuid4()
    tenant_id = uuid4()
    flow_id = uuid4()

    with pytest.raises(FlowRunNotFoundError) as exc_info:
        await repo.approve_review_checkpoint(
            checkpoint_id=uuid4(),
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=run_id,
            expected_revision=1,
            principal=FlowPrincipal(
                principal_type=PrincipalType.USER,
                principal_user_id=uuid4(),
            ),
        )

    assert exc_info.value.run_id == run_id
    assert exc_info.value.tenant_id == tenant_id
    assert exc_info.value.flow_id == flow_id


@pytest.mark.asyncio
async def test_open_review_checkpoint_raises_flow_run_not_found_error_when_parent_run_is_missing() -> (
    None
):
    session = AsyncMock()
    session.scalar.return_value = None
    repo = FlowRunReviewCheckpointRepository(
        session=session,
        factory=FlowFactory(),
        audit_outbox_repo=AsyncMock(),
    )
    run_id = uuid4()
    tenant_id = uuid4()
    flow_id = uuid4()

    with pytest.raises(FlowRunNotFoundError) as exc_info:
        await repo.open_review_checkpoint_for_completed_step(
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=run_id,
            step_id=uuid4(),
            step_order=1,
            attempt_no=1,
            requester_principal=FlowPrincipal(
                principal_type=PrincipalType.USER,
                principal_user_id=uuid4(),
            ),
            next_step_ids=[],
            review_mode=FlowStepReviewMode.EDIT,
            output_type=FlowOutputType.JSON,
        )

    assert exc_info.value.run_id == run_id
    assert exc_info.value.tenant_id == tenant_id
    assert exc_info.value.flow_id == flow_id


@pytest.mark.asyncio
async def test_expire_review_checkpoint_for_reconciliation_raises_flow_run_not_found_error_when_parent_run_is_missing() -> (
    None
):
    session = AsyncMock()
    session.scalar.return_value = None
    repo = FlowRunReviewCheckpointRepository(
        session=session,
        factory=FlowFactory(),
        audit_outbox_repo=AsyncMock(),
    )
    run_id = uuid4()
    tenant_id = uuid4()

    with pytest.raises(FlowRunNotFoundError) as exc_info:
        await repo.expire_review_checkpoint_for_reconciliation(
            checkpoint_id=uuid4(),
            flow_run_id=run_id,
            tenant_id=tenant_id,
            expires_before=datetime.now(timezone.utc),
        )

    assert exc_info.value.run_id == run_id
    assert exc_info.value.tenant_id == tenant_id
    assert exc_info.value.flow_id is None
