from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_flow_run_service import _flow, _flow_repo, _run, _trace_user, _version

from intric.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from intric.flows.application.flow_run_evidence_service import FlowRunEvidenceService
from intric.main.exceptions import UnauthorizedException


@pytest.mark.asyncio
async def test_get_evidence_loads_run_through_access_policy(user):
    user = _trace_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user)
    run = _run(user=user, flow_id=flow.id)
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    flow_run_repo.list_rerun_operations_for_run.return_value = []
    flow_run_repo.list_rerun_invalidated_steps_for_run.return_value = []
    flow_run_repo.list_review_checkpoints_for_run.return_value = []
    flow_run_repo.list_result_files.return_value = []
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )

    evidence = (await service.get_redacted_evidence_bundle(run_id=run.id)).to_dict()

    assert evidence["run"]["id"] == str(run.id)
    flow_run_repo.get.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        flow_id=None,
    )


@pytest.mark.asyncio
async def test_export_evidence_json_rejects_injected_run_id_mismatch(user):
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=AsyncMock(),
        flow_version_repo=AsyncMock(),
    )
    run = _run(user=user, flow_id=uuid4())

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.export_evidence_json(
            run_id=uuid4(),
            run=run,
        )

    assert exc_info.value.code == "flow_run_access_denied"
    assert exc_info.value.context == {"auth_layer": "flow_run_argument"}


@pytest.mark.asyncio
async def test_preloaded_run_is_revalidated_before_evidence_is_returned(
    user,
    monkeypatch,
):
    user = _trace_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user)
    run = _run(user=user, flow_id=flow.id)
    access_policy = FlowRunAccessPolicy(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
    )
    ensure_can_access_run = AsyncMock()
    monkeypatch.setattr(
        access_policy,
        "ensure_can_access_run",
        ensure_can_access_run,
    )
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    flow_run_repo.list_rerun_operations_for_run.return_value = []
    flow_run_repo.list_rerun_invalidated_steps_for_run.return_value = []
    flow_run_repo.list_review_checkpoints_for_run.return_value = []
    flow_run_repo.list_result_files.return_value = []
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        access_policy=access_policy,
    )

    await service.get_redacted_evidence_bundle(run_id=run.id, run=run)

    ensure_can_access_run.assert_awaited_once_with(
        run,
        access_kind="evidence_view",
    )
    flow_run_repo.get.assert_not_awaited()
