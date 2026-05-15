from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from intric.embedding_models.infrastructure.adapters.litellm_embeddings import (
    LiteLLMEmbeddingAdapter,
)
from intric.embedding_models.infrastructure.create_embeddings_service import (
    CreateEmbeddingsService,
    is_pre_resolved,
)
from intric.main.exceptions import ProviderInactiveException, ProviderNotFoundException
from intric.settings.encryption_service import EncryptionService
from intric.worker.crawl_context import EmbeddingModelSpec

_DEFAULT_CREDENTIALS = object()


@dataclass(frozen=True)
class _OrmLikeEmbeddingModel:
    id: UUID
    name: str = "text-embedding-3-small"
    provider_id: UUID | None = None
    litellm_model_name: str | None = None
    family: str | None = None
    max_input: int | None = 8191
    max_batch_size: int | None = 32
    dimensions: int | None = 1536
    open_source: bool = False


class _InactiveProvider:
    id = uuid4()
    name = "inactive"
    provider_type = "openai"
    credentials = {"api_key": "encrypted"}
    config: dict[str, object] = {}
    is_active = False


class _Result:
    def __init__(self, provider: object | None) -> None:
        self._provider = provider

    def scalar_one_or_none(self) -> object | None:
        return self._provider


class _DbSession:
    def __init__(self, provider: object | None) -> None:
        self.executed = False
        self._provider = provider

    async def execute(self, _statement: object) -> _Result:
        self.executed = True
        return _Result(self._provider)


class _NoDbSession:
    def __init__(self) -> None:
        self.executed = False

    async def execute(self, _statement: object) -> object:
        self.executed = True
        raise AssertionError("DB must not be touched on pre-resolved path")


def _embedding_spec(
    *,
    provider_type: str | None = "openai",
    provider_credentials: dict[str, object] | None | object = _DEFAULT_CREDENTIALS,
    provider_config: dict[str, object] | None = None,
) -> EmbeddingModelSpec:
    credentials = (
        {"api_key": "encrypted"}
        if provider_credentials is _DEFAULT_CREDENTIALS and provider_type is not None
        else provider_credentials
    )
    return EmbeddingModelSpec(
        id=uuid4(),
        name="text-embedding-3-small",
        litellm_model_name="openai/text-embedding-3-small",
        family=None,
        max_input=8191,
        max_batch_size=32,
        dimensions=1536,
        provider_id=uuid4(),
        provider_type=provider_type,
        provider_credentials=cast(dict[str, object] | None, credentials),
        provider_config=provider_config or {},
    )


def _encryption_service() -> EncryptionService:
    return cast(EncryptionService, object())


@pytest.mark.asyncio
async def test_pre_resolved_embedding_model_uses_no_db_session() -> None:
    session = _NoDbSession()
    model = _embedding_spec(provider_config={"endpoint": "https://example.test"})
    service = CreateEmbeddingsService(
        encryption_service=_encryption_service(),
        session=cast(AsyncSession, session),
    )

    adapter = await service._get_adapter(model)

    assert isinstance(adapter, LiteLLMEmbeddingAdapter)
    assert adapter.litellm_model == "openai/text-embedding-3-small"
    assert adapter.credential_resolver is not None
    assert adapter.credential_resolver.provider_id == model.provider_id
    assert adapter.credential_resolver.provider_type == "openai"
    assert adapter.credential_resolver.get_credential_field("api_key") == "encrypted"
    assert (
        adapter.credential_resolver.get_credential_field("endpoint")
        == "https://example.test"
    )
    assert session.executed is False


@pytest.mark.asyncio
async def test_pre_resolved_embedding_model_requires_encryption_service() -> None:
    service = CreateEmbeddingsService(encryption_service=None)

    with pytest.raises(ValueError, match="requires an encryption_service"):
        await service._get_adapter(_embedding_spec())


@pytest.mark.asyncio
async def test_db_lookup_embedding_model_requires_session() -> None:
    model = _OrmLikeEmbeddingModel(id=uuid4(), provider_id=uuid4())
    service = CreateEmbeddingsService(session=None)

    with pytest.raises(ValueError, match="requires database session"):
        await service._get_adapter(model)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "expected_exception"),
    [
        (None, ProviderNotFoundException),
        (_InactiveProvider(), ProviderInactiveException),
    ],
)
async def test_db_lookup_embedding_model_preserves_provider_failure_semantics(
    provider: object | None,
    expected_exception: type[Exception],
) -> None:
    session = _DbSession(provider)
    model = _OrmLikeEmbeddingModel(id=uuid4(), provider_id=uuid4())
    service = CreateEmbeddingsService(
        encryption_service=_encryption_service(),
        session=cast(AsyncSession, session),
    )

    with pytest.raises(expected_exception):
        await service._get_adapter(model)

    assert session.executed is True


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (_embedding_spec(), True),
        (_embedding_spec(provider_type=None), False),
        (_embedding_spec(provider_type=""), False),
        (_embedding_spec(provider_credentials=None), False),
        (_embedding_spec(provider_credentials={}), True),
        (_OrmLikeEmbeddingModel(id=uuid4(), provider_id=uuid4()), False),
    ],
)
def test_is_pre_resolved_embedding_model_truth_table(
    model: object,
    expected: bool,
) -> None:
    assert is_pre_resolved(model) is expected
