"""The provider API key hint shows the key's own last characters, never ciphertext."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from eneo.model_providers.domain.model_provider import ModelProvider
from eneo.model_providers.domain.model_provider_service import ModelProviderService
from eneo.model_providers.presentation.model_provider_models import (
    ModelProviderCreate,
)
from eneo.model_providers.presentation.model_provider_router import (
    create_provider,
    list_providers,
)
from eneo.roles.permissions import Permission
from eneo.settings.encryption_service import EncryptionService

API_KEY = "sk-live-0123456789abcd"


def _encryption() -> EncryptionService:
    return EncryptionService(Fernet.generate_key().decode())


def _provider(api_key: str | None) -> ModelProvider:
    now = datetime.now(timezone.utc)
    return ModelProvider(
        id=uuid4(),
        tenant_id=uuid4(),
        name="OpenAI",
        provider_type="openai",
        credentials={} if api_key is None else {"api_key": api_key},
        config={},
        is_active=True,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_encrypted_key_is_masked_from_its_plaintext():
    encryption = _encryption()
    repository = MagicMock()
    repository.get_by_name = AsyncMock(return_value=None)
    repository.create = AsyncMock(side_effect=lambda provider: provider)
    service = ModelProviderService(repository=repository, encryption=encryption)
    admin = SimpleNamespace(tenant_id=uuid4(), permissions=[Permission.ADMIN])

    created = await create_provider(
        data=ModelProviderCreate(
            name="OpenAI", provider_type="openai", credentials={"api_key": API_KEY}
        ),
        user=admin,
        service=service,
    )
    stored = repository.create.await_args.args[0]
    repository.all = AsyncMock(return_value=[stored])
    listed = await list_providers(user=admin, service=service)

    assert encryption.is_encrypted(stored.credentials["api_key"])
    assert created.masked_api_key == "...abcd"
    assert [provider.masked_api_key for provider in listed] == ["...abcd"]


@pytest.mark.parametrize(
    ("stored_key", "encryption", "expected"),
    [
        pytest.param(None, EncryptionService(None), None, id="no key"),
        pytest.param("", EncryptionService(None), None, id="empty key"),
        pytest.param(
            API_KEY, EncryptionService(None), "...abcd", id="plaintext, encryption off"
        ),
        pytest.param(
            _encryption().encrypt(API_KEY),
            _encryption(),
            "****",
            id="encrypted with another key",
        ),
        pytest.param(
            _encryption().encrypt(API_KEY),
            EncryptionService(None),
            "****",
            id="encrypted, encryption off",
        ),
        pytest.param("abcd", EncryptionService(None), "****", id="too short to hide"),
    ],
)
def test_masked_api_key_never_reveals_more_than_the_last_four(
    stored_key: str | None, encryption: EncryptionService, expected: str | None
):
    service = ModelProviderService(repository=MagicMock(), encryption=encryption)

    assert service.masked_api_key(_provider(stored_key)) == expected
