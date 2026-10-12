"""Export discovery uses the same conversation access boundary as rendering."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from eneo.conversations import conversations_router as router
from eneo.conversations.document_export import (
    DocumentExportAvailability,
    DocumentExportFormatAvailability,
    DocumentExportUnavailable,
)
from eneo.sessions.session import DocumentExportRequest


def context():
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    conversation = SimpleNamespace(id=uuid4())
    audit = SimpleNamespace(log_async=AsyncMock())
    container = SimpleNamespace(
        session=lambda: None,
        user=lambda: user,
        tenant=lambda: None,
        session_service=lambda: SimpleNamespace(
            get_session_by_uuid=AsyncMock(return_value=conversation)
        ),
        assistant_service=lambda: object(),
        file_service=lambda: object(),
        mcp_proxy_session_factory=lambda: object(),
        audit_service=lambda: audit,
    )
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    return container, conversation, audit, request


async def test_discovery_authorizes_before_resolving_and_does_not_render_or_audit():
    container, conversation, audit, request = context()
    events = []

    async def scope(**kwargs):
        events.append("scope")

    async def access(*args):
        events.append("access")

    expected = DocumentExportAvailability(
        docx=DocumentExportFormatAvailability(available=True),
        pdf=DocumentExportFormatAvailability(
            available=False, reason="format_unsupported"
        ),
    )

    async def availability(**kwargs):
        events.append("resolve")
        assert kwargs["conversation"] is conversation
        return expected

    response = Response()
    with (
        patch.object(router, "_validate_conversation_scope", scope),
        patch.object(router, "_authorize_session_access", access),
        patch.object(router, "build_identity_headers", return_value={}),
        patch.object(router, "document_export_availability", availability),
        patch.object(router, "export_document", new_callable=AsyncMock) as render,
    ):
        result = await router.get_document_export_availability(
            session_id=conversation.id,
            file_id=uuid4(),
            http_request=request,
            response=response,
            container=container,
        )
    assert result == expected
    assert events == ["scope", "access", "resolve"]
    assert response.headers["cache-control"] == "no-store"
    render.assert_not_awaited()
    audit.log_async.assert_not_awaited()


async def test_discovery_does_not_probe_a_provider_when_conversation_access_is_denied():
    container, conversation, _, request = context()
    with (
        patch.object(router, "_validate_conversation_scope", new_callable=AsyncMock),
        patch.object(
            router,
            "_authorize_session_access",
            AsyncMock(side_effect=HTTPException(404)),
        ),
        patch.object(
            router, "document_export_availability", new_callable=AsyncMock
        ) as probe,
    ):
        with pytest.raises(HTTPException) as error:
            await router.get_document_export_availability(
                session_id=conversation.id,
                file_id=uuid4(),
                http_request=request,
                response=Response(),
                container=container,
            )
    assert error.value.status_code == 404
    probe.assert_not_awaited()


async def test_incompatible_export_preserves_conflict_response_and_audit_reason():
    container, conversation, audit, request = context()
    file_id = uuid4()
    with (
        patch.object(router, "_validate_conversation_scope", new_callable=AsyncMock),
        patch.object(router, "_authorize_session_access", new_callable=AsyncMock),
        patch.object(router, "build_identity_headers", return_value={}),
        patch.object(
            router.AuditMetadata,
            "standard",
            side_effect=lambda **kwargs: kwargs["extra"],
        ),
        patch.object(
            router,
            "export_document",
            AsyncMock(side_effect=DocumentExportUnavailable("format_unsupported")),
        ),
    ):
        with pytest.raises(HTTPException) as error:
            await router.export_conversation_document(
                session_id=conversation.id,
                file_id=file_id,
                request=DocumentExportRequest(format="pdf"),
                http_request=request,
                container=container,
            )
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "document_export_unavailable"
    audit.log_async.assert_awaited_once()
    recorded = audit.log_async.call_args.kwargs
    assert recorded["tenant_id"] == container.user().tenant_id
    assert recorded["entity_id"] == file_id
    assert recorded["metadata"]["reason"] == "format_unsupported"
    assert recorded["outcome"].value == "failure"
