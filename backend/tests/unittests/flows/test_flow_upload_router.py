from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import (
    AsyncMock,
    MagicMock,
)
from uuid import uuid4

import pytest
from fastapi import UploadFile

from intric.authentication.auth_dependencies import ScopeFilter
from intric.flows.api import flow_router_common as router_common_module
from intric.flows.api.flow_models import (
    FlowInputSource,
    FlowInputType,
    FlowRunContractPublic,
)
from intric.flows.api.flow_upload_router import (
    get_flow_input_policy,
    get_flow_run_contract,
    upload_flow_file,
    upload_flow_runtime_file,
)
from intric.main.exceptions import BadRequestException
from intric.settings.settings import FlowInputLimitsPublic
from tests.unittests.flows.test_flow_router import (
    _enable_explicit_transaction,
    _enable_space_access,
    _flow,
    _flow_step,
)


@pytest.mark.asyncio
async def test_get_flow_run_contract_enforces_scope_and_returns_contract(monkeypatch):
    flow_id = uuid4()
    container = MagicMock()
    run_contract_service = AsyncMock()
    container.flow_service.return_value = AsyncMock()
    monkeypatch.setattr(
        router_common_module,
        "flow_run_contract_service",
        lambda _container: run_contract_service,
    )

    async def fake_enforce(
        request,
        _container,
        *,
        flow_id,
        required_access=router_common_module.FlowApiAction.VIEW,
        require_flow_lookup_without_scope=False,
        allow_service_key_principals=False,
        require_published_for_service_key=False,
    ):
        assert required_access == router_common_module.FlowApiAction.VIEW
        assert require_flow_lookup_without_scope is False
        assert allow_service_key_principals is True
        assert require_published_for_service_key is True

    monkeypatch.setattr(
        router_common_module, "enforce_flow_scope_for_request", fake_enforce
    )
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
    monkeypatch.setattr(
        router_common_module, "flow_upload_service", lambda _container: upload_service
    )

    async def fake_enforce(
        request,
        _container,
        *,
        flow_id,
        required_access=router_common_module.FlowApiAction.VIEW,
        require_flow_lookup_without_scope=False,
        allow_service_key_principals=False,
        require_published_for_service_key=False,
    ):
        assert required_access == router_common_module.FlowApiAction.RUN
        assert require_flow_lookup_without_scope is False
        assert allow_service_key_principals is True
        assert require_published_for_service_key is True

    monkeypatch.setattr(
        router_common_module, "enforce_flow_scope_for_request", fake_enforce
    )
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
async def test_get_flow_input_policy_for_audio_step_returns_audio_mime_and_limit(
    monkeypatch,
):
    container = MagicMock()
    flow_service = AsyncMock()
    settings_service = AsyncMock()
    flow_id = uuid4()

    step = _flow_step(uuid4(), 1).model_copy(update={"input_type": "audio"})
    flow_service.get_flow.return_value = _flow(flow_id).model_copy(
        update={"steps": [step]}
    )
    settings_service.get_flow_input_limits_resolved.return_value = (
        FlowInputLimitsPublic(
            file_max_size_bytes=10_000_000,
            audio_max_size_bytes=25_000_000,
            max_files_per_run=10,
            audio_max_files_per_run=10,
        )
    )
    container.flow_service.return_value = flow_service
    container.settings_service.return_value = settings_service

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    policy = await get_flow_input_policy(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert policy.input_type == FlowInputType.AUDIO
    assert policy.input_source == FlowInputSource.FLOW_INPUT
    assert policy.accepts_file_upload is True
    assert policy.max_file_size_bytes == 25_000_000
    assert policy.max_files_per_run == 10
    assert policy.recommended_run_payload is not None
    assert policy.recommended_run_payload["step_inputs"] == {
        str(step.id): {"file_ids": ["<file-id-uuid>"]}
    }
    assert "audio/mpeg" in policy.accepted_mimetypes


@pytest.mark.asyncio
async def test_get_flow_input_policy_tolerates_unexpected_policy_enums(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()

    class _BadPolicyService:
        async def get_input_policy(self, *, flow_id):
            return SimpleNamespace(
                flow_id=flow_id,
                input_type="unexpected",
                input_source="flow_input",
                accepts_file_upload=False,
                accepted_mimetypes=[],
                max_file_size_bytes=None,
                max_files_per_run=None,
                recommended_run_payload=None,
            )

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)
    monkeypatch.setattr(
        router_common_module,
        "flow_upload_service",
        lambda _container: _BadPolicyService(),
    )
    monkeypatch.setattr(
        router_common_module,
        "enforce_flow_scope_for_request",
        AsyncMock(),
    )

    policy = await get_flow_input_policy(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert policy.input_type == "unexpected"
    assert policy.input_source == FlowInputSource.FLOW_INPUT


@pytest.mark.asyncio
async def test_get_flow_input_policy_tolerates_unexpected_input_source(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()

    class _BadSourcePolicyService:
        async def get_input_policy(self, *, flow_id):
            return SimpleNamespace(
                flow_id=flow_id,
                input_type="audio",
                input_source="unexpected_source",
                accepts_file_upload=True,
                accepted_mimetypes=["audio/mpeg"],
                max_file_size_bytes=25_000_000,
                max_files_per_run=10,
                recommended_run_payload={
                    "step_inputs": {"<step-id-uuid>": {"file_ids": ["<file-id-uuid>"]}}
                },
            )

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)
    monkeypatch.setattr(
        router_common_module,
        "flow_upload_service",
        lambda _container: _BadSourcePolicyService(),
    )
    monkeypatch.setattr(
        router_common_module,
        "enforce_flow_scope_for_request",
        AsyncMock(),
    )

    policy = await get_flow_input_policy(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert policy.input_type == FlowInputType.AUDIO
    assert policy.input_source == "unexpected_source"


@pytest.mark.asyncio
async def test_upload_flow_file_rejects_when_flow_input_type_not_file_upload(
    monkeypatch,
):
    container = MagicMock()
    flow_service = AsyncMock()
    settings_service = AsyncMock()
    file_service = AsyncMock()
    flow_id = uuid4()

    step = _flow_step(uuid4(), 1).model_copy(update={"input_type": "text"})
    flow_service.get_flow.return_value = _flow(flow_id).model_copy(
        update={"steps": [step]}
    )
    settings_service.get_flow_input_limits_resolved.return_value = (
        FlowInputLimitsPublic(
            file_max_size_bytes=10_000_000,
            audio_max_size_bytes=25_000_000,
            max_files_per_run=10,
            audio_max_files_per_run=10,
        )
    )
    container.flow_service.return_value = flow_service
    container.settings_service.return_value = settings_service
    container.file_service.return_value = file_service

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    upload = UploadFile(
        filename="audio.mp3",
        file=BytesIO(b"audio"),
        headers={"content-type": "audio/mpeg"},
    )

    with pytest.raises(BadRequestException):
        await upload_flow_file(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            upload_file=upload,
            container=container,
        )
    file_service.save_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_flow_file_uses_flow_limit_override(monkeypatch):
    container = MagicMock()
    flow_service = AsyncMock()
    settings_service = AsyncMock()
    file_service = AsyncMock()
    flow_id = uuid4()
    file_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())

    step = _flow_step(uuid4(), 1).model_copy(update={"input_type": "audio"})
    flow_service.get_flow.return_value = _flow(flow_id).model_copy(
        update={"steps": [step]}
    )
    settings_service.get_flow_input_limits_resolved.return_value = (
        FlowInputLimitsPublic(
            file_max_size_bytes=10_000_000,
            audio_max_size_bytes=31_000_000,
            max_files_per_run=10,
            audio_max_files_per_run=10,
        )
    )
    file_service.save_file.return_value = SimpleNamespace(
        id=file_id,
        name="audio.mp3",
        size=1024,
        mimetype="audio/mpeg",
        file_type=SimpleNamespace(value="audio"),
        created_at=datetime.now(timezone.utc),
    )
    container.flow_service.return_value = flow_service
    container.settings_service.return_value = settings_service
    container.file_service.return_value = file_service
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()
    _enable_explicit_transaction(container)

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)
    monkeypatch.setattr(
        "intric.flows.flow_file_upload_service._sniff_mimetype",
        lambda _upload_file: "audio/mpeg",
    )

    upload = UploadFile(
        filename="audio.mp3",
        file=BytesIO(b"audio"),
        headers={"content-type": "audio/mpeg"},
    )

    result = await upload_flow_file(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        upload_file=upload,
        container=container,
    )

    assert result.id == file_id
    file_service.save_file.assert_awaited_once()
    assert file_service.save_file.await_args.kwargs["max_size"] == 31_000_000
