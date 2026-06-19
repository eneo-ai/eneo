from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.authentication.principal_types import PrincipalType
from intric.flows.api.flow_service_principal_actor_read_model import (
    FlowServicePrincipalActorPresenter,
)
from intric.flows.domain.flow import FlowRunReviewCheckpoint
from intric.flows.enums import FlowOutputType, FlowRunReviewCheckpointState
from intric.flows.flow_review_policy import FlowStepReviewMode


@pytest.mark.asyncio
async def test_present_review_checkpoint_batches_service_principal_summaries():
    tenant_id = uuid4()
    service_id = uuid4()
    repo = AsyncMock()
    repo.list_service_principals_by_ids.return_value = {
        service_id: SimpleNamespace(
            id=service_id,
            display_name="Public runtime service",
        )
    }
    checkpoint = FlowRunReviewCheckpoint(
        id=uuid4(),
        tenant_id=tenant_id,
        flow_id=uuid4(),
        flow_run_id=uuid4(),
        step_id=uuid4(),
        step_order=1,
        attempt_no=1,
        state=FlowRunReviewCheckpointState.AWAITING_REVIEW,
        revision=1,
        schema_version=1,
        review_mode=FlowStepReviewMode.VIEW,
        output_type=FlowOutputType.JSON,
        requester_principal_type=PrincipalType.SERVICE_KEY,
        requester_service_id=service_id,
        decided_by_principal_type=None,
        created_at="2026-03-20T12:00:00Z",
        updated_at="2026-03-20T12:00:00Z",
    )

    presenter = FlowServicePrincipalActorPresenter(
        api_key_repo=repo,
        tenant_id=tenant_id,
    )
    enriched = await presenter.present_review_checkpoint(checkpoint)

    assert enriched.requester_service_principal is not None
    assert enriched.requester_service_principal.id == service_id
    assert enriched.requester_service_principal.display_name == "Public runtime service"
    repo.list_service_principals_by_ids.assert_awaited_once_with(
        service_principal_ids=(service_id,),
        tenant_id=tenant_id,
    )


@pytest.mark.asyncio
async def test_present_evidence_actor_summaries_uses_one_lookup_for_all_sections():
    tenant_id = uuid4()
    requester_service_id = uuid4()
    decider_service_id = uuid4()
    rerun_service_id = uuid4()
    repo = AsyncMock()
    repo.list_service_principals_by_ids.return_value = {
        requester_service_id: SimpleNamespace(
            id=requester_service_id,
            display_name="Requester service",
        ),
        decider_service_id: SimpleNamespace(
            id=decider_service_id,
            display_name="Decider service",
        ),
        rerun_service_id: SimpleNamespace(
            id=rerun_service_id,
            display_name="Rerun service",
        ),
    }
    payload = {
        "review_checkpoints": [
            {
                "requester_service_id": str(requester_service_id),
                "decided_by_service_id": str(decider_service_id),
            }
        ],
        "rerun_operations": [
            {
                "requested_by_service_id": str(rerun_service_id),
            }
        ],
    }

    presenter = FlowServicePrincipalActorPresenter(
        api_key_repo=repo,
        tenant_id=tenant_id,
    )
    enriched = await presenter.present_evidence(payload)

    checkpoint = enriched["review_checkpoints"][0]
    assert checkpoint["requester_service_principal"]["display_name"] == (
        "Requester service"
    )
    assert checkpoint["decided_by_service_principal"]["display_name"] == (
        "Decider service"
    )
    rerun_operation = enriched["rerun_operations"][0]
    assert rerun_operation["requested_by_service_principal"]["display_name"] == (
        "Rerun service"
    )
    repo.list_service_principals_by_ids.assert_awaited_once()
    assert set(
        repo.list_service_principals_by_ids.await_args.kwargs["service_principal_ids"]
    ) == {requester_service_id, decider_service_id, rerun_service_id}
