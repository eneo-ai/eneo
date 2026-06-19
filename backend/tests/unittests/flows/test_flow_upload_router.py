from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import (
    AsyncMock,
    MagicMock,
)
from uuid import uuid4

import pytest
from fastapi import UploadFile

from intric.audit.domain.action_types import ActionType
from intric.flows.api import flow_access_context as flow_access_context_module
from intric.flows.api.flow_models import FlowRunContractPublic
from intric.flows.api.flow_upload_router import (
    delete_flow_runtime_file,
    get_flow_run_contract,
    upload_flow_runtime_file,
)
from intric.flows.flow_access_policy import FlowApiAction


@pytest.mark.asyncio
async def test_get_flow_run_contract_enforces_scope_and_returns_contract(monkeypatch):
    flow_id = uuid4()
    container = MagicMock()
    run_contract_service = AsyncMock()
    container.flow_service.return_value = AsyncMock()
    container.flow_run_contract_service.return_value = run_contract_service

    async def fake_enforce(
        request,
        _container,
        *,
        flow_id,
        required_access=FlowApiAction.VIEW,
        allow_service_key_principals=False,
        require_published_for_service_key=False,
    ):
        assert required_access == FlowApiAction.VIEW
        assert allow_service_key_principals is True
        assert require_published_for_service_key is True

    monkeypatch.setattr(flow_access_context_module, "enforce_flow_scope", fake_enforce)
    run_contract_service.get_run_contract.return_value = FlowRunContractPublic(
        flow_id=flow_id,
        published_flow_version=2,
        form_fields=[],
        steps_requiring_input=[],
        aggregate_max_files=3,
        template_readiness=[],
    )

    result = await get_flow_run_contract(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    run_contract_service.get_run_contract.assert_awaited_once_with(flow_id=flow_id)
    assert result.published_flow_version == 2


@pytest.mark.asyncio
async def test_upload_flow_runtime_file_calls_step_upload_service(monkeypatch):
    flow_id = uuid4()
    step_id = uuid4()
    file_id = uuid4()
    container = MagicMock()
    upload_service = AsyncMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    container.flow_runtime_file_service.return_value = upload_service

    async def fake_enforce(
        request,
        _container,
        *,
        flow_id,
        required_access=FlowApiAction.VIEW,
        allow_service_key_principals=False,
        require_published_for_service_key=False,
    ):
        assert required_access == FlowApiAction.RUN
        assert allow_service_key_principals is True
        assert require_published_for_service_key is True

    monkeypatch.setattr(flow_access_context_module, "enforce_flow_scope", fake_enforce)
    upload_service.upload_runtime_file_for_step.return_value = SimpleNamespace(
        id=file_id,
        name="audio.mp3",
        size=123,
        mimetype="audio/mpeg",
    )

    result = await upload_flow_runtime_file(
        id=flow_id,
        step_id=step_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        upload_file=UploadFile(filename="audio.mp3", file=BytesIO(b"audio")),
        container=container,
    )

    upload_service.upload_runtime_file_for_step.assert_awaited_once()
    audit_service.log_async.assert_awaited_once()
    assert result.id == file_id


@pytest.mark.asyncio
async def test_delete_flow_runtime_file_calls_runtime_file_service(monkeypatch):
    flow_id = uuid4()
    file_id = uuid4()
    container = MagicMock()
    runtime_file_service = AsyncMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    file_type = SimpleNamespace(value="document")
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    container.flow_runtime_file_service.return_value = runtime_file_service

    async def fake_enforce(
        request,
        _container,
        *,
        flow_id,
        required_access=FlowApiAction.VIEW,
        allow_service_key_principals=False,
        require_published_for_service_key=False,
    ):
        assert required_access == FlowApiAction.RUN
        assert allow_service_key_principals is True
        assert require_published_for_service_key is True

    monkeypatch.setattr(flow_access_context_module, "enforce_flow_scope", fake_enforce)
    runtime_file_service.delete_runtime_file.return_value = SimpleNamespace(
        id=file_id,
        name="source.pdf",
        size=321,
        mimetype="application/pdf",
        file_type=file_type,
    )

    result = await delete_flow_runtime_file(
        id=flow_id,
        file_id=file_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert result is None
    runtime_file_service.delete_runtime_file.assert_awaited_once_with(
        flow_id=flow_id,
        file_id=file_id,
    )
    audit_service.log_async.assert_awaited_once()
    audit_kwargs = audit_service.log_async.await_args.kwargs
    assert audit_kwargs["action"] == ActionType.FILE_DELETED
    assert audit_kwargs["entity_id"] == file_id
    extra = audit_kwargs["metadata"]["extra"]
    assert extra["flow_id"] == str(flow_id)
    assert extra["file_id"] == str(file_id)
    assert extra["file_type"] == "document"
    assert extra["runtime_role"] == "flow_runtime_step_input"
