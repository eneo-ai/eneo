from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import (
    AsyncMock,
    MagicMock,
)
from uuid import UUID, uuid4

import pytest
from fastapi import UploadFile

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.signed_urls import verify_signed_token
from eneo.files.file_models import SignedURLRequest
from eneo.flows.api import flow_access_context as flow_access_context_module
from eneo.flows.api import flow_template_router as flow_template_router_module
from eneo.flows.api.flow_template_router import (
    delete_flow_template_file,
    generate_flow_template_signed_url,
    inspect_flow_template,
    list_flow_template_files,
    upload_flow_template_file,
)
from eneo.flows.domain.flow import FlowTemplateAsset
from eneo.flows.flow_access_policy import FlowApiAction
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import (
    AuditLoggingUnavailableException,
    ErrorCodes,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission
from tests.unittests.flows.test_flow_router import (
    _enable_space_access,
    _flow,
)


def _template_asset(*, flow_id: UUID, tenant_id: UUID) -> FlowTemplateAsset:
    return FlowTemplateAsset.model_validate(
        {
            "id": uuid4(),
            "flow_id": flow_id,
            "space_id": uuid4(),
            "tenant_id": tenant_id,
            "file_id": uuid4(),
            "name": "template.docx",
            "checksum": "checksum",
            "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "placeholders": ["summary"],
            "status": "ready",
            "last_updated_by_name": "User",
        }
    )


class _TemplateDownloadTransaction:
    def __init__(
        self,
        events: list[str],
        *,
        exit_error: Exception | None = None,
    ) -> None:
        self._events = events
        self._exit_error = exit_error

    async def __aenter__(self) -> None:
        self._events.append("transaction_enter")

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self._events.append("transaction_exit")
        if self._exit_error is not None:
            raise self._exit_error
        return False


@pytest.mark.asyncio
async def test_list_flow_template_files_projects_editor_capabilities(monkeypatch):
    container = MagicMock()
    template_asset_service = AsyncMock()
    user = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), permissions=[Permission.FLOWS]
    )
    flow_id = uuid4()
    asset = _template_asset(flow_id=flow_id, tenant_id=user.tenant_id)
    container.flow_template_asset_service.return_value = template_asset_service
    container.user.return_value = user
    template_asset_service.list_assets.return_value = [asset]

    requested_flow_ids: list[str] = []

    async def allow_edit_access(request, _container, *, flow_id):
        requested_flow_ids.append(str(flow_id))
        return SimpleNamespace(flow=_flow(flow_id), actor=MagicMock())

    monkeypatch.setattr(
        flow_template_router_module,
        "require_flow_edit_access",
        allow_edit_access,
    )

    result = await list_flow_template_files(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert requested_flow_ids == [str(flow_id)]
    template_asset_service.list_assets.assert_awaited_once_with(flow_id=flow_id)
    assert len(result) == 1
    assert result[0].id == asset.id
    assert result[0].status == asset.status
    assert result[0].can_edit is True
    assert result[0].can_download is True
    assert result[0].can_select is True
    assert result[0].can_inspect is True


@pytest.mark.asyncio
async def test_inspect_flow_template_enforces_scope_and_calls_service(monkeypatch):
    container = MagicMock()
    template_asset_service = AsyncMock()
    container.flow_template_asset_service.return_value = template_asset_service
    flow_id = uuid4()
    file_id = uuid4()
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )
    container.flow_service.return_value = AsyncMock()
    container.flow_service.return_value.get_flow.return_value = _flow(flow_id)
    _enable_space_access(container)
    template_asset_service.inspect_asset.return_value = {
        "file_id": file_id,
        "file_name": "rapport.docx",
        "placeholders": [
            {"name": "summary", "location": "body", "preview": "{{summary}}"}
        ],
        "extracted_text_preview": "Titel: {{summary}}",
    }

    requested_flow_ids: list[str] = []

    async def fake_access_context(
        request,
        _container,
        *,
        flow_id,
        required_access=FlowApiAction.VIEW,
        load_actor_context=True,
        allow_service_key_principals=False,
    ):
        requested_flow_ids.append(str(flow_id))
        assert required_access == FlowApiAction.EDIT
        assert load_actor_context is True
        assert allow_service_key_principals is False
        flow = _flow(flow_id)
        flow.owner_user_id = container.user.return_value.id
        return SimpleNamespace(
            flow=flow,
            actor=MagicMock(can_edit_flows=MagicMock(return_value=True)),
        )

    monkeypatch.setattr(
        flow_access_context_module,
        "resolve_flow_access_context",
        fake_access_context,
    )

    result = await inspect_flow_template(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        file_id=file_id,
        container=container,
    )

    assert requested_flow_ids == [str(flow_id)]
    template_asset_service.inspect_asset.assert_awaited_once_with(
        flow_id=flow_id, asset_id=file_id
    )
    assert result["file_name"] == "rapport.docx"
    assert result["extracted_text_preview"] == "Titel: {{summary}}"


@pytest.mark.asyncio
async def test_upload_flow_template_file_enforces_scope_and_uses_docx_template_save(
    monkeypatch,
):
    container = MagicMock()
    template_asset_service = AsyncMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), permissions=[Permission.FLOWS]
    )
    flow_id = uuid4()
    asset = _template_asset(flow_id=flow_id, tenant_id=user.tenant_id)
    container.flow_template_asset_service.return_value = template_asset_service
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    container.flow_service.return_value = AsyncMock()
    container.flow_service.return_value.get_flow.return_value = _flow(flow_id)
    _enable_space_access(container)
    template_asset_service.upload_asset.return_value = asset
    upload = UploadFile(
        filename="template.docx",
        file=BytesIO(b"fake"),
        headers={
            "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        },
    )

    requested_flow_ids: list[str] = []

    async def fake_access_context(
        request,
        _container,
        *,
        flow_id,
        required_access=FlowApiAction.VIEW,
        load_actor_context=True,
        allow_service_key_principals=False,
    ):
        requested_flow_ids.append(str(flow_id))
        assert required_access == FlowApiAction.EDIT
        assert load_actor_context is True
        assert allow_service_key_principals is False
        flow = _flow(flow_id)
        flow.owner_user_id = container.user.return_value.id
        return SimpleNamespace(
            flow=flow,
            actor=MagicMock(can_edit_flows=MagicMock(return_value=True)),
        )

    monkeypatch.setattr(
        flow_access_context_module,
        "resolve_flow_access_context",
        fake_access_context,
    )

    result = await upload_flow_template_file(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        upload_file=upload,
        container=container,
    )

    assert requested_flow_ids == [str(flow_id)]
    template_asset_service.upload_asset.assert_awaited_once_with(
        flow_id=flow_id, upload_file=upload
    )
    audit_service.log_async.assert_awaited_once()
    audit_kwargs = audit_service.log_async.await_args.kwargs
    assert asset.id != asset.file_id
    assert audit_kwargs["entity_id"] == asset.file_id
    assert result.id == asset.id
    assert result.can_edit is True
    assert result.can_download is True
    assert result.can_select is True
    assert result.can_inspect is True


@pytest.mark.asyncio
async def test_generate_flow_template_signed_url_uses_template_file_tenant(
    monkeypatch,
):
    container = MagicMock()
    template_asset_service = AsyncMock()
    audit_service = AsyncMock()
    container.flow_template_asset_service.return_value = template_asset_service
    container.audit_service.return_value = audit_service
    events: list[str] = []
    container.session().begin.return_value = _TemplateDownloadTransaction(events)
    flow_id = uuid4()
    asset_id = uuid4()
    asset_file_id = uuid4()
    file_tenant_id = uuid4()
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )
    container.user.return_value = user

    async def allow_edit_access(request, _container, *, flow_id):
        return SimpleNamespace(flow=_flow(flow_id), actor=MagicMock())

    monkeypatch.setattr(
        flow_template_router_module,
        "require_flow_edit_access",
        allow_edit_access,
    )
    original_build_signed_download_response = (
        flow_template_router_module.build_signed_download_response
    )

    async def record_audit(**kwargs):
        events.append("audit_log")

    def record_url_build(**kwargs):
        events.append("url_build")
        return original_build_signed_download_response(**kwargs)

    audit_service.log.side_effect = record_audit
    monkeypatch.setattr(
        flow_template_router_module,
        "build_signed_download_response",
        record_url_build,
    )
    asset = SimpleNamespace(
        id=asset_id,
        file_id=asset_file_id,
        name="template.docx",
        space_id=uuid4(),
    )
    template_asset_service.get_asset_with_file.return_value = (
        asset,
        SimpleNamespace(id=asset_file_id, tenant_id=file_tenant_id),
    )

    response = await generate_flow_template_signed_url(
        id=flow_id,
        file_id=uuid4(),
        request=SimpleNamespace(base_url="https://app.example.com/"),
        signed_url_req=SignedURLRequest(expires_in=120),
        container=container,
    )

    template_asset_service.get_asset_with_file.assert_awaited_once()
    audit_service.log.assert_awaited_once()
    audit_kwargs = audit_service.log.await_args.kwargs
    assert audit_kwargs["required"] is True
    assert audit_kwargs["action"] == ActionType.FILE_SIGNED_URL_MINTED
    assert audit_kwargs["entity_type"] == EntityType.FILE
    assert audit_kwargs["entity_id"] == asset_file_id
    assert audit_kwargs["metadata"]["extra"] == {
        "flow_id": str(flow_id),
        "template_asset_id": str(asset_id),
        "file_id": str(asset_file_id),
        "download_purpose": "flow_template",
    }
    assert response.url.startswith(
        f"https://app.example.com/api/v1/files/{asset_file_id}/download/?token="
    )
    token = response.url.split("token=", 1)[1]
    payload = verify_signed_token(
        token,
        expected_file_id=asset_file_id,
        expected_tenant_id=file_tenant_id,
    )
    assert payload is not None
    assert payload["expires_at"] == response.expires_at
    assert events == [
        "transaction_enter",
        "audit_log",
        "transaction_exit",
        "url_build",
    ]


@pytest.mark.asyncio
async def test_generate_flow_template_signed_url_translates_audit_commit_failure(
    monkeypatch,
):
    container = MagicMock()
    template_asset_service = AsyncMock()
    audit_service = AsyncMock()
    container.flow_template_asset_service.return_value = template_asset_service
    container.audit_service.return_value = audit_service
    events: list[str] = []
    container.session().begin.return_value = _TemplateDownloadTransaction(
        events,
        exit_error=RuntimeError("commit unavailable"),
    )
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )
    container.user.return_value = user
    asset_file_id = uuid4()
    template_asset_service.get_asset_with_file.return_value = (
        SimpleNamespace(
            id=uuid4(),
            file_id=asset_file_id,
            name="template.docx",
            space_id=uuid4(),
        ),
        SimpleNamespace(id=asset_file_id, tenant_id=user.tenant_id),
    )

    async def allow_edit_access(request, _container, *, flow_id):
        return SimpleNamespace(flow=_flow(flow_id), actor=MagicMock())

    async def record_audit(**kwargs):
        events.append("audit_log")

    def unexpected_url_build(**kwargs):
        raise AssertionError("URL generation must not happen when audit commit fails.")

    audit_service.log.side_effect = record_audit
    monkeypatch.setattr(
        flow_template_router_module,
        "require_flow_edit_access",
        allow_edit_access,
    )
    monkeypatch.setattr(
        flow_template_router_module,
        "build_signed_download_response",
        unexpected_url_build,
    )

    with pytest.raises(AuditLoggingUnavailableException) as exc_info:
        await generate_flow_template_signed_url(
            id=uuid4(),
            file_id=uuid4(),
            request=SimpleNamespace(base_url="https://app.example.com/"),
            signed_url_req=SignedURLRequest(expires_in=120),
            container=container,
        )

    assert events == ["transaction_enter", "audit_log", "transaction_exit"]
    assert (
        exc_info.value.code
        == FlowApiErrorCode.TEMPLATE_DOWNLOAD_AUDIT_UNAVAILABLE.value
    )


def test_generate_flow_template_signed_url_publishes_audit_failure_contract():
    from eneo.server.main import app

    operation = app.openapi()["paths"][
        "/api/v1/flows/{id}/template-files/{file_id}/signed-url/"
    ]["post"]
    response = operation["responses"]["503"]

    assert response["content"]["application/json"]["example"] == {
        "message": "Flow template download audit logging is unavailable.",
        "eneo_error_code": int(ErrorCodes.INTERNAL_SERVER_ERROR),
        "code": FlowApiErrorCode.TEMPLATE_DOWNLOAD_AUDIT_UNAVAILABLE.value,
        "context": {"audit_required": True},
    }


@pytest.mark.asyncio
async def test_delete_flow_template_file_enforces_scope_and_audits_asset_delete(
    monkeypatch,
):
    container = MagicMock()
    template_asset_service = AsyncMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), permissions=[Permission.FLOWS]
    )
    flow_id = uuid4()
    asset = FlowTemplateAsset.model_validate(
        {
            "id": uuid4(),
            "flow_id": flow_id,
            "space_id": uuid4(),
            "tenant_id": user.tenant_id,
            "file_id": uuid4(),
            "name": "template.docx",
            "checksum": "checksum",
            "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "placeholders": ["summary"],
            "status": "ready",
        }
    )
    container.flow_template_asset_service.return_value = template_asset_service
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    template_asset_service.delete_asset.return_value = asset

    requested_flow_ids: list[str] = []

    async def allow_edit_access(request, _container, *, flow_id):
        requested_flow_ids.append(str(flow_id))
        return SimpleNamespace(flow=_flow(flow_id), actor=MagicMock())

    monkeypatch.setattr(
        flow_template_router_module,
        "require_flow_edit_access",
        allow_edit_access,
    )

    response = await delete_flow_template_file(
        id=flow_id,
        file_id=asset.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.status_code == 204
    assert requested_flow_ids == [str(flow_id)]
    template_asset_service.delete_asset.assert_awaited_once_with(
        flow_id=flow_id,
        asset_id=asset.id,
    )
    audit_service.log_async.assert_awaited_once()
    audit_kwargs = audit_service.log_async.await_args.kwargs
    assert audit_kwargs["action"] == ActionType.FILE_DELETED
    assert audit_kwargs["entity_type"] == EntityType.FILE
    assert audit_kwargs["entity_id"] == asset.file_id


@pytest.mark.asyncio
async def test_generate_flow_template_signed_url_checks_edit_access_before_url_build(
    monkeypatch,
):
    container = MagicMock()
    template_asset_service = AsyncMock()
    container.flow_template_asset_service.return_value = template_asset_service
    calls: list[str] = []

    async def deny_edit_access(request, _container, *, flow_id):
        calls.append("access")
        raise UnauthorizedException("No edit access.")

    def unexpected_url_build(**kwargs):
        calls.append("url")
        raise AssertionError("URL generation must not happen before edit access.")

    monkeypatch.setattr(
        flow_template_router_module,
        "require_flow_edit_access",
        deny_edit_access,
    )
    monkeypatch.setattr(
        flow_template_router_module,
        "build_signed_download_response",
        unexpected_url_build,
    )

    with pytest.raises(UnauthorizedException):
        await generate_flow_template_signed_url(
            id=uuid4(),
            file_id=uuid4(),
            request=SimpleNamespace(base_url="https://app.example.com/"),
            signed_url_req=SignedURLRequest(),
            container=container,
        )

    assert calls == ["access"]
    template_asset_service.get_asset_with_file.assert_not_awaited()
