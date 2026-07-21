from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import EncryptionNotConfiguredException
from eneo.model_providers.domain.model_provider_service import ModelProviderService
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
