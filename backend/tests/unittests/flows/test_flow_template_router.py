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

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.authentication.signed_urls import verify_signed_token
from intric.files.file_models import SignedURLRequest
from intric.flows.api import flow_access_context as flow_access_context_module
from intric.flows.api import flow_template_router as flow_template_router_module
from intric.flows.api.flow_template_router import (
    delete_flow_template_file,
    generate_flow_template_signed_url,
    inspect_flow_template,
    list_flow_template_files,
    upload_flow_template_file,
)
from intric.flows.domain.flow import FlowTemplateAsset
from intric.flows.flow_access_policy import FlowApiAction
from intric.main.exceptions import UnauthorizedException
from intric.roles.permissions import Permission
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
    container.flow_template_asset_service.return_value = template_asset_service
    flow_id = uuid4()
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
    template_asset_service.get_asset_with_file.return_value = (
        SimpleNamespace(file_id=asset_file_id),
        SimpleNamespace(tenant_id=file_tenant_id),
    )

    response = await generate_flow_template_signed_url(
        id=flow_id,
        file_id=uuid4(),
        request=SimpleNamespace(base_url="https://app.example.com/"),
        signed_url_req=SignedURLRequest(expires_in=120),
        container=container,
    )

    template_asset_service.get_asset_with_file.assert_awaited_once()
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
