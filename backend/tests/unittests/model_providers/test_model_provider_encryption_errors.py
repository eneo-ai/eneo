from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eneo.authentication.auth_dependencies import get_current_active_user
from eneo.database.database import get_session_with_transaction
from eneo.main.config import reset_settings
from eneo.main.exceptions import EncryptionNotConfiguredException, ErrorCodes
from eneo.model_providers.domain.model_provider_service import ModelProviderService
from eneo.model_providers.presentation.model_provider_router import router
from eneo.roles.permissions import Permission
from eneo.server.exception_handlers import add_exception_handlers
from eneo.settings.encryption_service import EncryptionService


@pytest.mark.asyncio
async def test_create_provider_without_encryption_key_fails_before_persistence():
    repository = MagicMock()
    repository.get_by_name = AsyncMock(return_value=None)
    repository.create = AsyncMock()
    service = ModelProviderService(
        repository=repository,
        encryption=EncryptionService(None),
    )

    with pytest.raises(EncryptionNotConfiguredException, match="ENCRYPTION_KEY"):
        await service.create(
            tenant_id=uuid4(),
            name="OpenAI",
            provider_type="openai",
            credentials={"api_key": "sk-test-key"},
            config={},
        )

    repository.create.assert_not_awaited()


def test_all_service_dependent_provider_routes_document_configuration_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENCRYPTION_KEY", "malformed-key")
    reset_settings()

    app = FastAPI()
    app.include_router(router, prefix="/model-providers")
    add_exception_handlers(app)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(
        tenant_id=uuid4(), permissions=[Permission.ADMIN]
    )
    app.dependency_overrides[get_session_with_transaction] = lambda: MagicMock()

    try:
        response = TestClient(app, raise_server_exceptions=False).get(
            "/model-providers/"
        )
    finally:
        reset_settings()

    assert response.status_code == 503
    payload = response.json()
    assert payload["eneo_error_code"] == ErrorCodes.ENCRYPTION_NOT_CONFIGURED
    assert "ENCRYPTION_KEY is invalid" in payload["message"]

    openapi = app.openapi()
    for path, method in (
        ("/model-providers/", "get"),
        ("/model-providers/{provider_id}/", "get"),
        ("/model-providers/{provider_id}/", "delete"),
    ):
        response_schema = openapi["paths"][path][method]["responses"]["503"]
        assert response_schema["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/GeneralError"
        }
