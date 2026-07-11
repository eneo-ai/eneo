from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_flow_run_service import (
    _file_repo,
    _flow,
    _flow_repo,
    _run,
    _step_result_record,
    _trace_user,
    _version,
)

from eneo.files.file_models import FileType
from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.application.flow_run_evidence_service import FlowRunEvidenceService
from eneo.flows.flow_run_step_input_file import FlowRunStepInputFileMetadata
from eneo.flows.infrastructure.flow_run_rerun_repo import FlowRunRerunRepository
from eneo.flows.published_definition import published_definition_checksum
from eneo.main.exceptions import UnauthorizedException


def _flow_run_rerun_repo() -> AsyncMock:
    repo = AsyncMock(spec=FlowRunRerunRepository)
    repo.list_rerun_operations_for_run.return_value = []
    repo.list_rerun_invalidated_steps_for_run.return_value = []
    return repo


@pytest.mark.asyncio
async def test_get_evidence_loads_run_through_access_policy(user):
    user = _trace_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = _flow_run_rerun_repo()
    review_checkpoint_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user)
    run = _run(user=user, flow_id=flow.id)
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    review_checkpoint_repo.list_review_checkpoints_for_run.return_value = []
    flow_run_repo.list_result_files.return_value = []
    flow_run_repo.list_current_step_input_file_metadata_by_step_result_id.return_value = {}
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_run_review_checkpoint_repo=review_checkpoint_repo,
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
    )

    evidence = (await service.get_redacted_evidence_bundle(run_id=run.id)).to_dict()

    assert evidence["run"]["id"] == str(run.id)
    flow_run_repo.get.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        flow_id=None,
    )


@pytest.mark.asyncio
async def test_get_evidence_preserves_corrupt_snapshot_with_integrity_status(user):
    user = _trace_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = _flow_run_rerun_repo()
    review_checkpoint_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user)
    run = _run(user=user, flow_id=flow.id)
    version = _version(user=user, flow=flow, version=run.flow_version).model_copy(
        update={"definition_checksum": "stored-checksum-does-not-match"}
    )
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    review_checkpoint_repo.list_review_checkpoints_for_run.return_value = []
    flow_run_repo.list_result_files.return_value = []
    flow_version_repo.get.return_value = version
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_run_review_checkpoint_repo=review_checkpoint_repo,
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
    )

    evidence = (await service.get_redacted_evidence_bundle(run_id=run.id)).to_dict()

    assert evidence["definition_snapshot"] == version.definition_json
    assert evidence["definition_integrity"] == {
        "status": "invalid",
        "expected_checksum": "stored-checksum-does-not-match",
        "current_checksum": published_definition_checksum(version.definition_json),
    }
    flow_version_repo.get.assert_awaited_once_with(
        flow_id=run.flow_id,
        version=run.flow_version,
        tenant_id=user.tenant_id,
    )


@pytest.mark.asyncio
async def test_get_evidence_populates_runtime_input_file_metadata_from_repo(user):
    user = _trace_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = _flow_run_rerun_repo()
    review_checkpoint_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user)
    run = _run(user=user, flow_id=flow.id)
    stale_payload_file_id = uuid4()
    relational_file_id = uuid4()
    result = _step_result_record(
        run,
        step_order=1,
        input_payload_json={
            "runtime_input": {
                "file_ids": [str(stale_payload_file_id)],
                "files_count": 1,
            }
        },
    )
    assert result.id is not None
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = [result]
    flow_run_repo.list_step_attempts.return_value = []
    review_checkpoint_repo.list_review_checkpoints_for_run.return_value = []
    flow_run_repo.list_result_files.return_value = []
    flow_run_repo.list_current_step_input_file_metadata_by_step_result_id.return_value = {
        result.id: (
            FlowRunStepInputFileMetadata(
                file_id=relational_file_id,
                name="relational.pdf",
                checksum="relational-checksum",
                size=256,
                mimetype="application/pdf",
                file_type=FileType.DOCUMENT,
                text_length=12,
                has_text=True,
                has_transcription=False,
            ),
        )
    }
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_run_review_checkpoint_repo=review_checkpoint_repo,
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
    )

    evidence = (await service.get_redacted_evidence_bundle(run_id=run.id)).to_dict()

    assert evidence["step_results"][0]["runtime_input_file_ids"] == [
        str(relational_file_id)
    ]
    runtime_input = evidence["step_results"][0]["input_payload_json"]["runtime_input"]
    assert runtime_input["files"] == [
        {
            "id": str(relational_file_id),
            "name": "relational.pdf",
            "checksum": "relational-checksum",
            "size": 256,
            "mimetype": "application/pdf",
            "file_type": "document",
            "text_length": 12,
            "has_text": True,
            "has_transcription": False,
        }
    ]
    flow_run_repo.list_current_step_input_file_metadata_by_step_result_id.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        step_results=[result],
    )


@pytest.mark.asyncio
async def test_export_evidence_json_rejects_injected_run_id_mismatch(user):
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=AsyncMock(),
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=AsyncMock(),
        file_repo=_file_repo(),
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
    flow_run_rerun_repo = _flow_run_rerun_repo()
    review_checkpoint_repo = AsyncMock()
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
    review_checkpoint_repo.list_review_checkpoints_for_run.return_value = []
    flow_run_repo.list_result_files.return_value = []
    flow_run_repo.list_current_step_input_file_metadata_by_step_result_id.return_value = {}
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_run_review_checkpoint_repo=review_checkpoint_repo,
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        access_policy=access_policy,
    )

    await service.get_redacted_evidence_bundle(run_id=run.id, run=run)

    ensure_can_access_run.assert_awaited_once_with(
        run,
        access_kind="evidence_view",
    )
    flow_run_repo.get.assert_not_awaited()
