"""A provider's stored key, and any secret header, is never sent to a destination
it was not entered for."""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from eneo.audit.domain.action_types import ActionType
from eneo.main.config import get_settings
from eneo.main.exceptions import BadRequestException
from eneo.model_providers.domain import model_provider_service
from eneo.model_providers.domain.model_provider import ModelProvider
from eneo.model_providers.domain.model_provider_service import (
    ModelProviderService,
    effective_endpoint,
    normalize_destination,
)
from eneo.model_providers.domain.outbound_header_writes import OutboundHeaderWrite
from eneo.model_providers.presentation.model_provider_models import (
    ModelProviderUpdate,
)
from eneo.model_providers.presentation.model_provider_router import update_provider
from eneo.settings.encryption_service import EncryptionService


@pytest.fixture(autouse=True)
def _no_embedding_lock(monkeypatch):
    """The embedding-provider lock is a database concern outside this test."""
    monkeypatch.setattr(
        model_provider_service, "guard_embedding_provider_update", AsyncMock()
    )


def _provider(
    provider_type: str = "openai",
    *,
    config: dict | None = None,
    credentials: dict | None = None,
) -> ModelProvider:
    now = datetime.now(timezone.utc)
    return ModelProvider(
        id=uuid4(),
        tenant_id=uuid4(),
        name="provider",
        provider_type=provider_type,
        credentials={"api_key": "encrypted"} if credentials is None else credentials,
        config={} if config is None else config,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def _service(provider: ModelProvider) -> tuple[ModelProviderService, AsyncMock]:
    repository = AsyncMock()
    repository.get_by_id.return_value = provider
    repository.get_by_name.return_value = None
    repository.update.side_effect = lambda p: p
    repository.session = MagicMock()
    encryption = MagicMock()
    encryption.encrypt.side_effect = lambda value: f"enc({value})"
    return ModelProviderService(
        repository=repository, encryption=encryption
    ), repository


class TestDestinationNormalization:
    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("https://api.example.com", "https://api.example.com/"),
            ("https://api.example.com", "HTTPS://API.Example.com"),
            ("https://api.example.com", "https://api.example.com:443"),
            ("http://vllm:8000", "http://vllm:8000/"),
            ("http://vllm", "http://vllm:80"),
            ("https://api.example.com/v1", "https://api.example.com/v1/"),
        ],
    )
    def test_equivalent_destinations_compare_equal(self, left: str, right: str):
        assert normalize_destination(left) == normalize_destination(right)

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("https://api.example.com", "http://api.example.com"),
            ("https://api.example.com", "https://api.example.org"),
            ("https://api.example.com", "https://api.example.com:8443"),
            ("https://api.example.com", "https://api.example.com/v1"),
            ("https://api.example.com/v1", "https://api.example.com/v2"),
            ("https://api.example.com", "https://api.example.com?region=eu"),
        ],
    )
    def test_different_destinations_compare_unequal(self, left: str, right: str):
        assert normalize_destination(left) != normalize_destination(right)

    def test_blank_and_missing_are_no_destination(self):
        assert normalize_destination(None) is None
        assert normalize_destination("   ") is None

    def test_effective_endpoint_falls_back_to_the_provider_default(self):
        assert effective_endpoint("openai", {}) == "https://api.openai.com"
        assert (
            effective_endpoint("openai", {"endpoint": " "}) == "https://api.openai.com"
        )
        assert effective_endpoint("openai", {"endpoint": "https://x"}) == "https://x"
        assert effective_endpoint("hosted_vllm", {}) is None


class TestUpdateWithNewDestination:
    async def test_endpoint_change_without_credentials_is_rejected_before_writing(self):
        provider = _provider(config={"endpoint": "https://api.example.com"})
        service, repository = _service(provider)

        with pytest.raises(BadRequestException, match="new API key"):
            await service.update(
                provider.id, config={"endpoint": "https://other.example.com"}
            )

        repository.update.assert_not_awaited()
        assert provider.config == {"endpoint": "https://api.example.com"}
        assert provider.credentials == {"api_key": "encrypted"}

    @pytest.mark.parametrize("api_key", ["", "   ", "...abcd", "****", "••••"])
    async def test_blank_or_masked_replacement_is_rejected(self, api_key: str):
        provider = _provider(config={"endpoint": "https://api.example.com"})
        service, repository = _service(provider)

        with pytest.raises(BadRequestException):
            await service.update(
                provider.id,
                config={"endpoint": "https://other.example.com"},
                credentials={"api_key": api_key},
            )

        repository.update.assert_not_awaited()

    async def test_masked_value_is_rejected_even_without_destination_change(self):
        provider = _provider(config={"endpoint": "https://api.example.com"})
        service, repository = _service(provider)

        with pytest.raises(BadRequestException, match="masked"):
            await service.update(provider.id, credentials={"api_key": "...abcd"})

        repository.update.assert_not_awaited()

    async def test_endpoint_change_with_replacement_key_is_stored_encrypted(self):
        provider = _provider(config={"endpoint": "https://api.example.com"})
        service, repository = _service(provider)

        updated = await service.update(
            provider.id,
            config={"endpoint": "https://other.example.com"},
            credentials={"api_key": "sk-new"},
        )

        repository.update.assert_awaited_once()
        assert updated.config["endpoint"] == "https://other.example.com"
        assert updated.credentials["api_key"] == "enc(sk-new)"

    @pytest.mark.parametrize(
        "equivalent",
        [
            "https://api.example.com/",
            "HTTPS://API.EXAMPLE.COM",
            "https://api.example.com:443",
        ],
    )
    async def test_equivalent_endpoint_keeps_the_stored_key(self, equivalent: str):
        provider = _provider(config={"endpoint": "https://api.example.com"})
        service, repository = _service(provider)

        updated = await service.update(provider.id, config={"endpoint": equivalent})

        repository.update.assert_awaited_once()
        assert updated.credentials == {"api_key": "encrypted"}

    async def test_name_only_edit_keeps_the_stored_key(self):
        provider = _provider(config={"endpoint": "https://api.example.com"})
        service, repository = _service(provider)

        updated = await service.update(provider.id, name="renamed")

        repository.update.assert_awaited_once()
        assert updated.name == "renamed"
        assert updated.credentials == {"api_key": "encrypted"}

    async def test_setting_the_default_endpoint_explicitly_is_not_a_change(self):
        provider = _provider("openai", config={})
        service, repository = _service(provider)

        await service.update(
            provider.id, config={"endpoint": "https://api.openai.com/"}
        )

        repository.update.assert_awaited_once()

    async def test_leaving_the_default_endpoint_requires_a_new_key(self):
        provider = _provider("openai", config={})
        service, repository = _service(provider)

        with pytest.raises(BadRequestException, match="new API key"):
            await service.update(
                provider.id, config={"endpoint": "https://proxy.example.com"}
            )

        repository.update.assert_not_awaited()

    async def test_credentialless_provider_may_change_endpoint(self):
        provider = _provider(
            "hosted_vllm", config={"endpoint": "http://vllm-a:8000"}, credentials={}
        )
        service, repository = _service(provider)

        updated = await service.update(
            provider.id, config={"endpoint": "http://vllm-b:8000"}
        )

        repository.update.assert_awaited_once()
        assert updated.config["endpoint"] == "http://vllm-b:8000"


GATEWAY = "https://gateway-a.internal/v1"
ELSEWHERE = "https://elsewhere.example/v1"


def _secret_header(**overrides: Any) -> dict[str, Any]:
    return {
        "id": "h1",
        "name": "X-Credential",
        "value": "enc(sk-a)",
        "encoding": "none",
        "secret": True,
        "on_missing": "omit",
        "fallback": None,
        "classification": None,
        **overrides,
    }


def _keep(**kwargs: Any) -> OutboundHeaderWrite:
    """The stored secret, sent back as an editor does."""
    return OutboundHeaderWrite(
        id="h1", name="X-Credential", encoding="none", secret=True, **kwargs
    )


def _header_service(
    header: dict[str, Any] | None = None,
) -> tuple[ModelProvider, ModelProviderService, AsyncMock]:
    """A completion-only gateway authenticated solely by a secret header."""
    provider = _provider("hosted_vllm", config={"endpoint": GATEWAY}, credentials={})
    provider.outbound_headers = [header or _secret_header()]
    service, repository = _service(provider)
    service.encryption.decrypt.side_effect = lambda value: value[4:-1]
    return provider, service, repository


class TestSecretHeadersOnNewDestination:
    """Like the API key, a stored secret header value or fallback is never sent
    to a destination it was not entered for."""

    @pytest.mark.parametrize(
        "edit",
        [
            {"config": {"endpoint": ELSEWHERE}},
            {"config": {"endpoint": ELSEWHERE}, "outbound_headers": [_keep()]},
            # The request resolves `endpoint` from credentials before config.
            {"credentials": {"endpoint": ELSEWHERE}},
        ],
    )
    async def test_moving_without_re_entering_is_rejected_before_writing(
        self, edit: dict[str, Any]
    ):
        _, service, repository = _header_service()

        with pytest.raises(BadRequestException, match="'X-Credential'"):
            await service.update(uuid4(), **edit)

        repository.update.assert_not_awaited()

    async def test_a_stored_secret_fallback_must_be_re_entered_too(self):
        _, service, repository = _header_service(
            _secret_header(fallback="enc(fb-a)", on_missing="fallback")
        )

        with pytest.raises(BadRequestException, match="'X-Credential'"):
            await service.update(
                uuid4(),
                config={"endpoint": ELSEWHERE},
                outbound_headers=[
                    _keep(on_missing="fallback", value="sk-b", value_supplied=True)
                ],
            )

        repository.update.assert_not_awaited()

    @pytest.mark.parametrize(
        ("writes", "stored_values"),
        [
            ([_keep(value="sk-b", value_supplied=True)], ["enc(sk-b)"]),
            ([], []),
        ],
    )
    async def test_re_entering_or_removing_the_secret_allows_the_move(
        self, writes: list[OutboundHeaderWrite], stored_values: list[str]
    ):
        _, service, repository = _header_service()

        updated = await service.update(
            uuid4(), config={"endpoint": ELSEWHERE}, outbound_headers=writes
        )

        repository.update.assert_awaited_once()
        assert updated.config["endpoint"] == ELSEWHERE
        assert [header["value"] for header in updated.outbound_headers] == (
            stored_values
        )

    @pytest.mark.parametrize(
        "edit",
        [
            {"name": "renamed"},
            {"config": {"endpoint": "HTTPS://GATEWAY-A.internal/v1/"}},
            {"outbound_headers": [_keep()]},
        ],
    )
    async def test_edits_that_keep_the_destination_keep_the_secret(
        self, edit: dict[str, Any]
    ):
        _, service, repository = _header_service()

        updated = await service.update(uuid4(), **edit)

        repository.update.assert_awaited_once()
        assert updated.outbound_headers[0]["value"] == "enc(sk-a)"


def _encryption() -> EncryptionService:
    return EncryptionService(Fernet.generate_key().decode())


def _key_from_a_previous_encryption_key(
    credentials: dict[str, Any] | None = None,
) -> tuple[ModelProvider, ModelProviderService, AsyncMock]:
    """A gateway with a plain header, whose stored API key was encrypted
    before ENCRYPTION_KEY changed and no longer decrypts."""
    provider = _provider(
        "hosted_vllm",
        config={"endpoint": GATEWAY},
        credentials={
            "api_key": _encryption().encrypt("sk-old-key"),
            **(credentials or {}),
        },
    )
    provider.outbound_headers = [
        _secret_header(id="h2", name="X-Region", value="eu-north", secret=False)
    ]
    repository = AsyncMock()
    # Each load is its own snapshot, as rows read from the database are.
    repository.get_by_id.side_effect = lambda *_, **__: deepcopy(provider)
    repository.get_by_name.return_value = None
    repository.update.side_effect = lambda p: p
    repository.session = MagicMock()
    service = ModelProviderService(repository=repository, encryption=_encryption())
    return provider, service, repository


class TestReplacingAnUndecryptableKey:
    """Resolving the destination never decrypts the key, so the edit that
    replaces an undecryptable key commits instead of rolling back."""

    @pytest.mark.parametrize(
        ("credentials", "expected"),
        [
            ({}, GATEWAY),
            # The request resolves `endpoint` from credentials before config.
            ({"endpoint": ELSEWHERE}, ELSEWHERE),
        ],
    )
    def test_endpoint_resolves_without_the_key(
        self, credentials: dict[str, Any], expected: str
    ):
        provider, service, _ = _key_from_a_previous_encryption_key(credentials)

        assert service.request_endpoint(provider) == expected

    @pytest.mark.parametrize(
        ("headers", "kept", "audited"),
        [
            (None, ["X-Region"], []),
            ([], [], [ActionType.MODEL_PROVIDER_HEADERS_UPDATED]),
        ],
        ids=["headers-kept", "headers-cleared"],
    )
    async def test_the_update_replacing_it_commits(
        self,
        headers: list[dict[str, Any]] | None,
        kept: list[str],
        audited: list[ActionType],
    ):
        stored, service, repository = _key_from_a_previous_encryption_key()
        audit = AsyncMock()
        admin = SimpleNamespace(
            id=uuid4(), tenant_id=stored.tenant_id, username="admin", email=None
        )

        public = await update_provider(
            provider_id=stored.id,
            data=ModelProviderUpdate(
                credentials={"api_key": "sk-new-key"}, outbound_headers=headers
            ),
            user=admin,
            service=service,
            audit=audit,
        )

        [written] = repository.update.await_args.args
        assert service.encryption.decrypt(written.credentials["api_key"]) == (
            "sk-new-key"
        )
        assert [header["name"] for header in written.outbound_headers] == kept
        assert public.config == {"endpoint": GATEWAY}
        assert [
            call.kwargs["action"] for call in audit.log_async.await_args_list
        ] == audited


def _admin(provider: ModelProvider) -> Any:
    return SimpleNamespace(
        id=uuid4(), tenant_id=provider.tenant_id, username="admin", email=None
    )


def _snapshots(
    provider: ModelProvider, encryption: Any
) -> tuple[ModelProviderService, AsyncMock]:
    repository = AsyncMock()
    # Each load is its own snapshot, as rows read from the database are.
    repository.get_by_id.side_effect = lambda *_, **__: deepcopy(provider)
    repository.get_by_name.return_value = None
    repository.update.side_effect = lambda p: p
    repository.session = MagicMock()
    return ModelProviderService(
        repository=repository, encryption=encryption
    ), repository


def _secret_from_a_previous_encryption_key(
    **overrides: Any,
) -> tuple[ModelProvider, ModelProviderService, AsyncMock]:
    """A gateway whose secret header was encrypted before ENCRYPTION_KEY
    changed and no longer decrypts."""
    previous = _encryption()
    provider = _provider("hosted_vllm", config={"endpoint": GATEWAY}, credentials={})
    provider.outbound_headers = [
        _secret_header(value=previous.encrypt("sk-a"), **overrides)
    ]
    service, repository = _snapshots(provider, _encryption())
    return provider, service, repository


class TestUnreadableSecretHeader:
    """A secret that no longer decrypts is a 400 naming the header, and the
    edit that re-enters or removes it commits."""

    @pytest.mark.parametrize(
        ("overrides", "write", "part"),
        [
            ({}, _keep(), "value"),
            (
                {"fallback": "enc:fernet:v1:unreadable", "on_missing": "fallback"},
                _keep(on_missing="fallback", value="sk-b", value_supplied=True),
                "fallback",
            ),
        ],
    )
    async def test_keeping_it_is_refused_with_the_header_named(
        self, overrides: dict[str, Any], write: OutboundHeaderWrite, part: str
    ):
        _, service, repository = _secret_from_a_previous_encryption_key(**overrides)

        with pytest.raises(
            BadRequestException,
            match=f"'X-Credential': the stored secret {part} cannot be read",
        ):
            await service.update(uuid4(), name="renamed", outbound_headers=[write])

        repository.update.assert_not_awaited()

    @pytest.mark.parametrize(
        ("headers", "stored"),
        [
            (
                [{"id": "h1", "name": "X-Credential", "secret": True, "value": "sk-b"}],
                ["sk-b"],
            ),
            ([], []),
        ],
        ids=["re-entered", "removed"],
    )
    async def test_re_entering_or_removing_it_commits_and_is_audited(
        self, headers: list[dict[str, Any]], stored: list[str]
    ):
        provider, service, repository = _secret_from_a_previous_encryption_key()
        audit = AsyncMock()

        await update_provider(
            provider_id=provider.id,
            data=ModelProviderUpdate(outbound_headers=headers),
            user=_admin(provider),
            service=service,
            audit=audit,
        )

        [written] = repository.update.await_args.args
        assert [
            service.encryption.decrypt(header["value"])
            for header in written.outbound_headers
        ] == stored
        [call] = audit.log_async.await_args_list
        assert call.kwargs["action"] == ActionType.MODEL_PROVIDER_HEADERS_UPDATED

    async def test_the_preview_reports_it_as_blocked(self):
        provider, service, _ = _secret_from_a_previous_encryption_key()

        outcomes, _, blocked, reason = await service.preview_outbound_headers(
            provider, MagicMock()
        )

        assert (outcomes, blocked, reason) == ([], True, "decryption_failed")


class TestDestinationNoLongerAllowed:
    """After the allow-list is narrowed, an edit that changes neither the
    headers nor the destination still saves; sends stay blocked."""

    @pytest.fixture(autouse=True)
    def _narrowed(self, monkeypatch):
        monkeypatch.setattr(
            get_settings(),
            "outbound_headers_allowed_destinations",
            ["https://other.internal/v1"],
        )

    @pytest.mark.parametrize(
        "edit",
        [
            {"is_active": False},
            {"name": "renamed"},
            # What the edit dialog sends when only "Active" is turned off.
            {
                "name": "provider",
                "config": {"endpoint": GATEWAY},
                "is_active": False,
                "outbound_headers": [_keep()],
            },
        ],
    )
    async def test_edits_that_change_neither_save(self, edit: dict[str, Any]):
        _, service, repository = _header_service()

        await service.update(uuid4(), **edit)

        repository.update.assert_awaited_once()

    @pytest.mark.parametrize(
        "edit",
        [
            {
                "config": {"endpoint": ELSEWHERE},
                "outbound_headers": [_keep(value="sk-b", value_supplied=True)],
            },
            {
                "outbound_headers": [
                    _keep(),
                    OutboundHeaderWrite(
                        id=None, name="X-Region", value="eu", value_supplied=True
                    ),
                ]
            },
        ],
        ids=["destination-moved", "headers-changed"],
    )
    async def test_edits_that_change_either_are_refused(self, edit: dict[str, Any]):
        _, service, repository = _header_service()

        with pytest.raises(BadRequestException, match="allowed destinations"):
            await service.update(uuid4(), **edit)

        repository.update.assert_not_awaited()


class TestDestinationChangeAudit:
    """Compared the way the secret re-entry rule compares destinations."""

    @pytest.mark.parametrize(
        ("endpoint", "audited"),
        [
            ("HTTPS://GATEWAY-A.internal/v1/", []),
            (ELSEWHERE, [ActionType.MODEL_PROVIDER_DESTINATION_CHANGED]),
        ],
        ids=["another-spelling", "moved"],
    )
    async def test_only_a_real_move_is_recorded(
        self, endpoint: str, audited: list[ActionType]
    ):
        provider = _provider(
            "hosted_vllm", config={"endpoint": GATEWAY}, credentials={}
        )
        provider.outbound_headers = [
            _secret_header(name="X-Region", value="eu-north", secret=False)
        ]
        service, _ = _snapshots(provider, _encryption())
        audit = AsyncMock()

        await update_provider(
            provider_id=provider.id,
            data=ModelProviderUpdate(config={"endpoint": endpoint}),
            user=_admin(provider),
            service=service,
            audit=audit,
        )

        assert [
            call.kwargs["action"] for call in audit.log_async.await_args_list
        ] == audited
