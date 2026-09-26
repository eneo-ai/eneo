"""Connection check and key expiry on model providers: service and routes."""

from collections.abc import Callable
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eneo.authentication.auth_dependencies import get_current_active_user
from eneo.database.database import get_session_with_transaction
from eneo.model_providers.domain.connection_check import (
    ConnectionCheck,
    ConnectionCheckError,
    ConnectionCheckStatus,
)
from eneo.model_providers.domain.model_provider import ModelProvider
from eneo.model_providers.domain.model_provider_service import (
    UNCHANGED,
    ConnectionCheckNotSupportedException,
    ModelProviderService,
)
from eneo.model_providers.infrastructure import provider_connection_probe
from eneo.model_providers.presentation.model_provider_router import (
    get_model_provider_service,
    router,
)
from eneo.roles.permissions import Permission
from eneo.server.exception_handlers import add_exception_handlers
from eneo.settings.encryption_service import EncryptionService

KEY = "sk-live-secret-1234"
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
_ENCRYPTION = EncryptionService(Fernet.generate_key().decode())


def _provider(
    *,
    provider_type: str = "openai",
    credentials: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    key_expires_on: date | None = None,
    connection_check: ConnectionCheck | None = None,
) -> ModelProvider:
    return ModelProvider(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Leverantör",
        provider_type=provider_type,
        credentials=credentials if credentials is not None else {},
        config=config if config is not None else {},
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
        key_expires_on=key_expires_on,
        connection_check=connection_check,
    )


def _service(provider: ModelProvider) -> tuple[ModelProviderService, MagicMock]:
    """A service over one stored provider. Recording returns the provider
    with the check applied, as the repository does."""
    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=provider)

    async def record(tested: ModelProvider, check: ConnectionCheck) -> ModelProvider:
        tested.connection_check = check
        return tested

    async def update(
        updated: ModelProvider, *, clear_connection_check: bool = False
    ) -> ModelProvider:
        return updated

    repository.record_connection_check = AsyncMock(side_effect=record)
    repository.update = AsyncMock(side_effect=update)
    repository.get_by_name = AsyncMock(return_value=None)
    repository.create = AsyncMock(side_effect=lambda created: created)
    return ModelProviderService(repository, _ENCRYPTION), repository


@pytest.fixture
def respond(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Callable[[httpx.Request], httpx.Response]], list[httpx.Request]]:
    def install(
        handler: Callable[[httpx.Request], httpx.Response],
    ) -> list[httpx.Request]:
        sent: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return handler(request)

        monkeypatch.setattr(
            provider_connection_probe,
            "_http_client",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(record)),
        )
        return sent

    return install


def _encrypted(key: str = KEY) -> dict[str, Any]:
    return {"api_key": _ENCRYPTION.encrypt(key)}


class TestCheckConnection:
    async def test_success_is_recorded(self, respond) -> None:
        sent = respond(lambda request: httpx.Response(200, json={"data": []}))
        provider = _provider(credentials=_encrypted())
        service, repository = _service(provider)

        stored, check = await service.check_connection(provider.id)

        assert check.status is ConnectionCheckStatus.OK
        repository.record_connection_check.assert_awaited_once_with(provider, check)
        assert stored.connection_check == check
        # The stored key is decrypted for the call's header and nowhere else.
        assert sent[0].headers["Authorization"] == f"Bearer {KEY}"

    async def test_rejected_key_is_recorded_as_authentication_failure(
        self, respond
    ) -> None:
        respond(lambda request: httpx.Response(401, json={"error": {"message": KEY}}))
        provider = _provider(credentials=_encrypted())
        service, _ = _service(provider)

        stored, check = await service.check_connection(provider.id)

        assert check.status is ConnectionCheckStatus.FAILED
        assert check.error is ConnectionCheckError.AUTHENTICATION_FAILED
        payload = str(stored.to_dict())
        assert KEY not in payload
        assert "Incorrect" not in payload and "message" not in payload

    async def test_timeout_and_network_errors_are_recorded(self, respond) -> None:
        def slow(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        respond(slow)
        provider = _provider(
            provider_type="hosted_vllm",
            config={"endpoint": "https://llm.example.se"},
        )
        service, _ = _service(provider)

        _stored, check = await service.check_connection(provider.id)

        assert check.error is ConnectionCheckError.TIMEOUT

        def refused(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        respond(refused)
        _stored, check = await service.check_connection(provider.id)

        assert check.error is ConnectionCheckError.UNREACHABLE

    async def test_a_missing_required_key_fails_without_calling_out(
        self, respond
    ) -> None:
        sent = respond(lambda request: httpx.Response(200))
        provider = _provider(credentials={})
        service, repository = _service(provider)

        _stored, check = await service.check_connection(provider.id)

        assert check.error is ConnectionCheckError.MISSING_CREDENTIALS
        assert sent == []
        repository.record_connection_check.assert_awaited_once()

    async def test_a_server_without_auth_is_called_without_a_key(self, respond) -> None:
        sent = respond(lambda request: httpx.Response(200, json={"data": []}))
        provider = _provider(
            provider_type="hosted_vllm",
            config={"endpoint": "https://llm.example.se/v1"},
        )
        service, _ = _service(provider)

        _stored, check = await service.check_connection(provider.id)

        assert check.status is ConnectionCheckStatus.OK
        assert str(sent[0].url) == "https://llm.example.se/v1/models"

    async def test_unsupported_types_raise_and_record_nothing(self, respond) -> None:
        sent = respond(lambda request: httpx.Response(200))
        provider = _provider(provider_type="perplexity", credentials=_encrypted())
        service, repository = _service(provider)

        with pytest.raises(ConnectionCheckNotSupportedException):
            await service.check_connection(provider.id)

        assert sent == []
        repository.record_connection_check.assert_not_awaited()

    def test_a_stored_category_from_a_newer_release_still_reads_as_failed(
        self,
    ) -> None:
        # After a rollback the provider list must not break on it.
        assert (
            ConnectionCheckError.parse("certificate_expired")
            is ConnectionCheckError.PROVIDER_ERROR
        )
        assert ConnectionCheckError.parse("timeout") is ConnectionCheckError.TIMEOUT


class TestUpdateAndCreate:
    async def test_new_credentials_clear_the_check(self) -> None:
        provider = _provider(
            credentials=_encrypted(), connection_check=ConnectionCheck.ok()
        )
        service, repository = _service(provider)

        await service.update(provider.id, credentials={"api_key": "sk-new-key-5678"})

        assert repository.update.await_args.kwargs == {"clear_connection_check": True}

    async def test_an_unchanged_config_keeps_the_check(self) -> None:
        provider = _provider(config={"endpoint": "https://llm.example.se"})
        service, repository = _service(provider)

        await service.update(
            provider.id, name="Nytt namn", config={"endpoint": "https://llm.example.se"}
        )

        assert repository.update.await_args.kwargs == {"clear_connection_check": False}

    async def test_a_changed_endpoint_clears_the_check(self) -> None:
        provider = _provider(config={"endpoint": "https://llm.example.se"})
        service, repository = _service(provider)

        await service.update(provider.id, config={"endpoint": "https://ny.example.se"})

        assert repository.update.await_args.kwargs == {"clear_connection_check": True}

    async def test_key_expiry_is_kept_set_or_cleared(self) -> None:
        provider = _provider(key_expires_on=date(2026, 10, 12))
        service, _ = _service(provider)

        kept = await service.update(provider.id, is_active=False)
        assert kept.key_expires_on == date(2026, 10, 12)

        moved = await service.update(provider.id, key_expires_on=date(2027, 1, 31))
        assert moved.key_expires_on == date(2027, 1, 31)

        cleared = await service.update(provider.id, key_expires_on=None)
        assert cleared.key_expires_on is None

    async def test_create_stores_the_key_expiry(self) -> None:
        service, repository = _service(_provider())

        created = await service.create(
            tenant_id=uuid4(),
            name="OpenAI",
            provider_type="openai",
            credentials={"api_key": KEY},
            config={},
            key_expires_on=date(2026, 12, 31),
        )

        assert created.key_expires_on == date(2026, 12, 31)
        assert created.connection_check is None
        assert repository.create.await_args.args[0].key_expires_on == date(2026, 12, 31)


def _client(service: Any, *, admin: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/model-providers")
    add_exception_handlers(app)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(
        tenant_id=uuid4(), permissions=[Permission.ADMIN] if admin else []
    )
    app.dependency_overrides[get_session_with_transaction] = lambda: MagicMock()
    app.dependency_overrides[get_model_provider_service] = lambda: service
    return TestClient(app, raise_server_exceptions=False)


def _fake_service(provider: ModelProvider, check: ConnectionCheck) -> MagicMock:
    service = MagicMock()
    provider.connection_check = check
    service.check_connection = AsyncMock(return_value=(provider, check))
    service.update = AsyncMock(return_value=provider)
    service.create = AsyncMock(return_value=provider)
    service.masked_api_key = MagicMock(return_value="...cret")
    return service


def _path(provider_id: UUID, action: str) -> str:
    return f"/model-providers/{provider_id}/{action}/"


class TestRoutes:
    def test_connection_check_returns_the_stored_result_without_secrets(
        self,
    ) -> None:
        provider = _provider(
            credentials=_encrypted(), key_expires_on=date(2026, 10, 12)
        )
        check = ConnectionCheck(
            status=ConnectionCheckStatus.FAILED,
            checked_at=NOW,
            error=ConnectionCheckError.AUTHENTICATION_FAILED,
        )
        client = _client(_fake_service(provider, check))

        response = client.post(_path(provider.id, "connection-check"))

        assert response.status_code == 200
        body = response.json()
        assert body["connection_check"] == {
            "status": "failed",
            "checked_at": "2026-09-26T12:00:00Z",
            "error": "authentication_failed",
        }
        assert body["connection_check_supported"] is True
        assert body["key_expires_on"] == "2026-10-12"
        # Like every provider response, it names the key by its masked tail,
        # so the UI still sees a configured key after a check.
        assert body["masked_api_key"] == "...cret"
        assert KEY not in response.text
        assert "credentials" not in body

    def test_connection_check_requires_admin(self) -> None:
        service = _fake_service(_provider(), ConnectionCheck.ok())
        client = _client(service, admin=False)

        for action in ("connection-check", "test"):
            response = client.post(_path(uuid4(), action))
            assert response.status_code == 403

        service.check_connection.assert_not_awaited()

    def test_unsupported_provider_answers_400(self) -> None:
        service = MagicMock()
        service.check_connection = AsyncMock(
            side_effect=ConnectionCheckNotSupportedException("not supported")
        )

        response = _client(service).post(_path(uuid4(), "connection-check"))

        assert response.status_code == 400

    @pytest.mark.parametrize(
        ("check", "expected"),
        [
            (
                ConnectionCheck.ok(),
                {"success": True, "message": "Connection successful"},
            ),
            (
                ConnectionCheck.failed(ConnectionCheckError.AUTHENTICATION_FAILED),
                {"success": False, "error": "Invalid API key"},
            ),
            (
                ConnectionCheck.failed(ConnectionCheckError.RATE_LIMITED),
                {"success": False, "error": "Connection test failed: rate_limited"},
            ),
        ],
    )
    def test_deprecated_test_route_keeps_its_answer_shape(
        self, check: ConnectionCheck, expected: dict[str, object]
    ) -> None:
        client = _client(_fake_service(_provider(), check))

        response = client.post(_path(uuid4(), "test"))

        assert response.status_code == 200
        assert response.json() == expected

    def test_deprecated_test_route_reports_unsupported_types(self) -> None:
        service = MagicMock()
        service.check_connection = AsyncMock(
            side_effect=ConnectionCheckNotSupportedException("not supported")
        )

        response = _client(service).post(_path(uuid4(), "test"))

        assert response.json() == {"success": False, "error": "not supported"}

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            ({"name": "Nytt namn"}, UNCHANGED),
            ({"key_expires_on": None}, None),
            ({"key_expires_on": "2026-10-12"}, date(2026, 10, 12)),
        ],
    )
    def test_update_leaves_out_or_clears_the_expiry(
        self, body: dict[str, object], expected: object
    ) -> None:
        service = _fake_service(_provider(), ConnectionCheck.ok())

        response = _client(service).put(f"/model-providers/{uuid4()}/", json=body)

        assert response.status_code == 200
        assert service.update.await_args.kwargs["key_expires_on"] == expected

    def test_create_passes_the_expiry(self) -> None:
        service = _fake_service(_provider(), ConnectionCheck.ok())

        response = _client(service).post(
            "/model-providers/",
            json={
                "name": "OpenAI",
                "provider_type": "openai",
                "credentials": {"api_key": KEY},
                "key_expires_on": "2026-12-31",
            },
        )

        assert response.status_code == 200
        assert service.create.await_args.kwargs["key_expires_on"] == date(2026, 12, 31)

    def test_openapi_documents_the_check_and_deprecates_the_old_test(self) -> None:
        openapi = _client(MagicMock()).app.openapi()  # type: ignore[attr-defined]

        check = openapi["paths"]["/model-providers/{provider_id}/connection-check/"]
        assert check["post"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ] == {"$ref": "#/components/schemas/ModelProviderPublic"}
        assert openapi["paths"]["/model-providers/{provider_id}/test/"]["post"][
            "deprecated"
        ]
