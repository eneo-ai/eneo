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

from intric.flows.api import flow_router_common as router_common_module
from intric.flows.api.flow_template_router import (
    inspect_flow_template,
    upload_flow_template_file,
)
from intric.flows.flow import FlowTemplateAsset
from intric.roles.permissions import Permission
from tests.unittests.flows.test_flow_router import (
    _enable_space_access,
    _flow,
)


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
        required_access=router_common_module.FlowApiAction.VIEW,
        load_actor_context=True,
        allow_service_key_principals=False,
    ):
        requested_flow_ids.append(str(flow_id))
        assert required_access == router_common_module.FlowApiAction.EDIT
        assert load_actor_context is True
        assert allow_service_key_principals is False
        flow = _flow(flow_id)
        flow.owner_user_id = container.user.return_value.id
        return SimpleNamespace(
            flow=flow,
            actor=MagicMock(can_edit_flows=MagicMock(return_value=True)),
        )

    monkeypatch.setattr(
        router_common_module,
        "get_flow_access_context_for_request",
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
    asset = FlowTemplateAsset.model_validate(
        {
            "id": uuid4(),
            "flow_id": uuid4(),
            "space_id": uuid4(),
            "tenant_id": user.tenant_id,
            "file_id": uuid4(),
            "name": "template.docx",
            "checksum": "checksum",
            "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "placeholders": ["summary"],
            "status": "ready",
            "last_updated_by_name": "User",
            "can_edit": True,
            "can_download": True,
            "can_select": True,
            "can_inspect": True,
        }
    )
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
        required_access=router_common_module.FlowApiAction.VIEW,
        load_actor_context=True,
        allow_service_key_principals=False,
    ):
        requested_flow_ids.append(str(flow_id))
        assert required_access == router_common_module.FlowApiAction.EDIT
        assert load_actor_context is True
        assert allow_service_key_principals is False
        flow = _flow(flow_id)
        flow.owner_user_id = container.user.return_value.id
        return SimpleNamespace(
            flow=flow,
            actor=MagicMock(can_edit_flows=MagicMock(return_value=True)),
        )

    monkeypatch.setattr(
        router_common_module,
        "get_flow_access_context_for_request",
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
    assert result.id == asset.id
