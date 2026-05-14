from types import TracebackType
from typing import Generic, TypeVar, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.info_blobs_table import InfoBlobs
from intric.database.tables.model_providers_table import ModelProviders
from intric.database.tables.websites_table import Websites
from intric.main.config import get_settings
from intric.tenants.crawler_settings_helper import TenantCrawlerSettings
from intric.tenants.tenant import TenantInDB
from intric.users.user import UserInDB
from intric.websites.domain.crawl_run import CrawlType
from intric.worker.crawl.bootstrap import (
    EmbeddingModelSpecError,
    HttpAuthDecryptionError,
    TenantIsolationError,
    WebsiteNotFoundError,
    bootstrap_crawl,
    build_embedding_model_spec,
)
from intric.worker.crawl.persistence import ExistingBlobState
from intric.worker.crawl_context import EmbeddingModelSpec

_T = TypeVar("_T")


class _ScalarResult(Generic[_T]):
    def __init__(self, value: _T | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> _T | None:
        return self._value


class _ProviderSession:
    def __init__(self, provider: ModelProviders | None = None) -> None:
        self.provider = provider
        self.execute_count = 0

    async def execute(self, _stmt: object) -> _ScalarResult[ModelProviders]:
        self.execute_count += 1
        return _ScalarResult(self.provider)


def _model(
    *,
    family: str = "openai",
    litellm_model_name: str | None = "stored/model",
    max_input: int | None = 8191,
    provider_id: UUID | None = None,
) -> EmbeddingModels:
    return EmbeddingModels(
        id=uuid4(),
        name="text-embedding-3-small",
        open_source=False,
        dimensions=1536,
        max_input=max_input,
        max_batch_size=64,
        family=family,
        litellm_model_name=litellm_model_name,
        provider_id=provider_id,
    )


def _provider(*, provider_id: UUID, is_active: bool = True) -> ModelProviders:
    return ModelProviders(
        id=provider_id,
        provider_type="openai",
        credentials={"api_key": "encrypted"},
        config={"base_url": "https://api.openai.com/v1"},
        is_active=is_active,
    )


def _session(provider: ModelProviders | None = None) -> AsyncSession:
    return cast(AsyncSession, _ProviderSession(provider))


class _BlobResult:
    def __init__(self, rows: tuple[tuple[str | None, bytes | None, UUID | None], ...]):
        self._rows = rows

    def tuples(self) -> tuple[tuple[str | None, bytes | None, UUID | None], ...]:
        return self._rows


class _BootstrapSession:
    def __init__(
        self,
        *,
        website: Websites | None,
        provider: ModelProviders | None = None,
        blob_rows: tuple[tuple[str | None, bytes | None, UUID | None], ...] = (),
    ) -> None:
        self.website = website
        self.provider = provider
        self.blob_rows = blob_rows

    async def execute(
        self,
        statement: Select[tuple[object]],
    ) -> _ScalarResult[Websites] | _ScalarResult[ModelProviders] | _BlobResult:
        entity = statement.column_descriptions[0].get("entity")
        if entity is Websites:
            return _ScalarResult(self.website)
        if entity is ModelProviders:
            return _ScalarResult(self.provider)
        if entity is InfoBlobs:
            return _BlobResult(self.blob_rows)
        raise AssertionError(f"Unhandled bootstrap statement entity: {entity!r}")


class _BootstrapSessionScope:
    def __init__(self, session: _BootstrapSession) -> None:
        self.session = session
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self) -> AsyncSession:
        self.enter_count += 1
        return cast(AsyncSession, self.session)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exit_count += 1


class _HttpAuthService:
    def __init__(self, decrypted_password: str = "secret") -> None:
        self.decrypted_password = decrypted_password
        self.calls: list[str] = []

    def decrypt_password(self, encrypted_password: str) -> str:
        self.calls.append(encrypted_password)
        return self.decrypted_password


class _FailingHttpAuthService:
    def decrypt_password(self, encrypted_password: str) -> str:
        raise ValueError(f"cannot decrypt {encrypted_password}")


def _tenant(*, tenant_id: UUID | None = None) -> TenantInDB:
    return TenantInDB(
        id=tenant_id or uuid4(),
        name="test-tenant",
        slug="test-tenant",
        quota_limit=0,
        quota_used=0,
    )


def _user(*, user_id: UUID | None = None, tenant: TenantInDB) -> UserInDB:
    return UserInDB(
        id=user_id or uuid4(),
        username="test-user",
        email="test@example.com",
        salt="salt",
        password="password",
        used_tokens=0,
        tenant_id=tenant.id,
        quota_used=0,
        tenant=tenant,
        state="active",
    )


def _website(
    *,
    website_id: UUID | None = None,
    tenant_id: UUID,
    user_id: UUID,
    embedding_model: EmbeddingModels | None,
    http_auth_username: str | None = None,
    encrypted_auth_password: str | None = None,
) -> Websites:
    model_id = embedding_model.id if embedding_model is not None else uuid4()
    return Websites(
        id=website_id or uuid4(),
        name="Knowledge site",
        url="https://example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval="never",
        size=0,
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=model_id,
        group_id=None,
        space_id=None,
        embedding_model=cast(EmbeddingModels, embedding_model),
        http_auth_username=http_auth_username,
        encrypted_auth_password=encrypted_auth_password,
    )


def _capture_warning_messages(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    warnings: list[str] = []
    from intric.worker.crawl import bootstrap as bootstrap_module

    def record_warning(message: str, **_kwargs: object) -> None:
        warnings.append(message)

    monkeypatch.setattr(bootstrap_module.logger, "warning", record_warning)
    return warnings


def _assert_unresolved_provider(
    spec: EmbeddingModelSpec | None,
    *,
    provider_id: UUID,
) -> None:
    assert spec is not None
    assert spec.provider_id == provider_id
    assert spec.provider_type is None
    assert spec.provider_credentials is None
    assert spec.provider_config is None
    assert spec.litellm_model_name == "stored/model"


@pytest.mark.asyncio
async def test_build_embedding_model_spec_returns_none_without_embedding_model() -> (
    None
):
    session = _ProviderSession()

    spec = await build_embedding_model_spec(cast(AsyncSession, session), None)

    assert spec is None
    assert session.execute_count == 0


@pytest.mark.asyncio
async def test_build_embedding_model_spec_uses_model_values_without_provider() -> None:
    session = _ProviderSession()
    model = _model(family="")

    spec = await build_embedding_model_spec(cast(AsyncSession, session), model)

    assert spec is not None
    assert spec.id == model.id
    assert spec.name == "text-embedding-3-small"
    assert spec.litellm_model_name == "stored/model"
    assert spec.family is None
    assert spec.max_input == 8191
    assert spec.max_batch_size == 64
    assert spec.dimensions == 1536
    assert spec.open_source is False
    assert spec.provider_id is None
    assert spec.provider_type is None
    assert spec.provider_credentials is None
    assert spec.provider_config is None
    assert session.execute_count == 0


@pytest.mark.asyncio
async def test_build_embedding_model_spec_uses_active_provider_credentials() -> None:
    provider_id = uuid4()
    provider = _provider(provider_id=provider_id)
    model = _model(provider_id=provider_id)

    spec = await build_embedding_model_spec(_session(provider), model)

    assert spec is not None
    assert spec.provider_id == provider_id
    assert spec.provider_type == "openai"
    assert spec.provider_credentials == {"api_key": "encrypted"}
    assert spec.provider_config == {"base_url": "https://api.openai.com/v1"}
    assert spec.litellm_model_name == "openai/text-embedding-3-small"


@pytest.mark.asyncio
async def test_build_embedding_model_spec_ignores_inactive_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_id = uuid4()
    provider = _provider(provider_id=provider_id, is_active=False)
    model = _model(provider_id=provider_id, litellm_model_name="stored/model")
    warnings = _capture_warning_messages(monkeypatch)

    spec = await build_embedding_model_spec(_session(provider), model)

    _assert_unresolved_provider(spec, provider_id=provider_id)
    assert warnings == ["Embedding model provider is inactive"]


@pytest.mark.asyncio
async def test_build_embedding_model_spec_handles_missing_provider_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_id = uuid4()
    model = _model(provider_id=provider_id, litellm_model_name="stored/model")
    warnings = _capture_warning_messages(monkeypatch)

    spec = await build_embedding_model_spec(_session(None), model)

    _assert_unresolved_provider(spec, provider_id=provider_id)
    assert warnings == []


@pytest.mark.asyncio
async def test_build_embedding_model_spec_raises_typed_error_without_max_input() -> (
    None
):
    provider_id = uuid4()
    session = _ProviderSession(_provider(provider_id=provider_id))
    model = _model(max_input=None, provider_id=provider_id)

    with pytest.raises(EmbeddingModelSpecError) as exc_info:
        await build_embedding_model_spec(cast(AsyncSession, session), model)

    assert "text-embedding-3-small" in str(exc_info.value)
    assert session.execute_count == 0


@pytest.mark.asyncio
async def test_bootstrap_crawl_returns_context_existing_blob_state_and_exits_session_scope() -> (
    None
):
    tenant = _tenant()
    user = _user(tenant=tenant)
    model = _model()
    website = _website(
        tenant_id=tenant.id,
        user_id=user.id,
        embedding_model=model,
    )
    content_hash = b"hash"
    session = _BootstrapSession(
        website=website,
        blob_rows=((website.url, content_hash, model.id),),
    )
    session_scope = _BootstrapSessionScope(session)

    result = await bootstrap_crawl(
        session_scope=lambda: session_scope,
        website_id=website.id,
        tenant=tenant,
        user=user,
        tenant_crawler_settings=TenantCrawlerSettings.from_overrides(None),
        settings=get_settings(),
        http_auth_password_decrypter=_HttpAuthService().decrypt_password,
    )

    assert result.website_url == "https://example.com"
    assert result.website_name == "Knowledge site"
    assert result.website_owner_id == user.id
    assert result.crawl_context.website_id == website.id
    assert result.crawl_context.tenant_id == tenant.id
    assert result.crawl_context.tenant_slug == "test-tenant"
    assert result.crawl_context.user_id == user.id
    assert result.crawl_context.embedding_model_id == model.id
    assert result.embedding_model is not None
    assert result.existing_titles == (website.url,)
    assert result.existing_blob_state_by_title == {
        website.url: ExistingBlobState(
            content_hash=content_hash,
            embedding_model_id=model.id,
        )
    }
    assert session_scope.enter_count == 1
    assert session_scope.exit_count == 1


@pytest.mark.asyncio
async def test_bootstrap_crawl_exits_session_scope_when_website_is_missing() -> None:
    tenant = _tenant()
    user = _user(tenant=tenant)
    session = _BootstrapSession(website=None)
    session_scope = _BootstrapSessionScope(session)

    with pytest.raises(WebsiteNotFoundError):
        await bootstrap_crawl(
            session_scope=lambda: session_scope,
            website_id=uuid4(),
            tenant=tenant,
            user=user,
            tenant_crawler_settings=TenantCrawlerSettings.from_overrides(None),
            settings=get_settings(),
            http_auth_password_decrypter=_HttpAuthService().decrypt_password,
        )

    assert session_scope.enter_count == 1
    assert session_scope.exit_count == 1


@pytest.mark.asyncio
async def test_bootstrap_crawl_rejects_tenant_mismatch() -> None:
    tenant = _tenant()
    other_tenant_id = uuid4()
    user = _user(tenant=tenant)
    website = _website(
        tenant_id=other_tenant_id,
        user_id=user.id,
        embedding_model=_model(),
    )
    session_scope = _BootstrapSessionScope(_BootstrapSession(website=website))

    with pytest.raises(TenantIsolationError) as exc_info:
        await bootstrap_crawl(
            session_scope=lambda: session_scope,
            website_id=website.id,
            tenant=tenant,
            user=user,
            tenant_crawler_settings=TenantCrawlerSettings.from_overrides(None),
            settings=get_settings(),
            http_auth_password_decrypter=_HttpAuthService().decrypt_password,
        )

    assert exc_info.value.website_id == website.id
    assert exc_info.value.website_tenant_id == other_tenant_id
    assert exc_info.value.container_tenant_id == tenant.id
    assert session_scope.enter_count == 1
    assert session_scope.exit_count == 1


@pytest.mark.asyncio
async def test_bootstrap_crawl_decrypts_http_auth_with_passed_service() -> None:
    tenant = _tenant()
    user = _user(tenant=tenant)
    website = _website(
        tenant_id=tenant.id,
        user_id=user.id,
        embedding_model=_model(),
        http_auth_username="crawler",
        encrypted_auth_password="encrypted-password",
    )
    session_scope = _BootstrapSessionScope(_BootstrapSession(website=website))
    auth_service = _HttpAuthService(decrypted_password="decrypted-password")

    result = await bootstrap_crawl(
        session_scope=lambda: session_scope,
        website_id=website.id,
        tenant=tenant,
        user=user,
        tenant_crawler_settings=TenantCrawlerSettings.from_overrides(None),
        settings=get_settings(),
        http_auth_password_decrypter=auth_service.decrypt_password,
    )

    assert auth_service.calls == ["encrypted-password"]
    assert result.crawl_context.http_auth_user == "crawler"
    assert result.crawl_context.http_auth_pass == "decrypted-password"
    assert session_scope.enter_count == 1
    assert session_scope.exit_count == 1


@pytest.mark.asyncio
async def test_bootstrap_crawl_wraps_http_auth_decryption_failure_without_password_leak() -> (
    None
):
    tenant = _tenant()
    user = _user(tenant=tenant)
    website = _website(
        tenant_id=tenant.id,
        user_id=user.id,
        embedding_model=_model(),
        http_auth_username="crawler",
        encrypted_auth_password="plaintext-should-not-leak",
    )
    session_scope = _BootstrapSessionScope(_BootstrapSession(website=website))

    with pytest.raises(HttpAuthDecryptionError) as exc_info:
        await bootstrap_crawl(
            session_scope=lambda: session_scope,
            website_id=website.id,
            tenant=tenant,
            user=user,
            tenant_crawler_settings=TenantCrawlerSettings.from_overrides(None),
            settings=get_settings(),
            http_auth_password_decrypter=(_FailingHttpAuthService().decrypt_password),
        )

    assert exc_info.value.website_id == website.id
    assert "plaintext-should-not-leak" not in str(exc_info.value)
    assert session_scope.enter_count == 1
    assert session_scope.exit_count == 1


@pytest.mark.asyncio
async def test_bootstrap_crawl_returns_none_embedding_model_when_website_has_no_embedding_model() -> (
    None
):
    tenant = _tenant()
    user = _user(tenant=tenant)
    website = _website(
        tenant_id=tenant.id,
        user_id=user.id,
        embedding_model=None,
    )
    session_scope = _BootstrapSessionScope(_BootstrapSession(website=website))

    result = await bootstrap_crawl(
        session_scope=lambda: session_scope,
        website_id=website.id,
        tenant=tenant,
        user=user,
        tenant_crawler_settings=TenantCrawlerSettings.from_overrides(None),
        settings=get_settings(),
        http_auth_password_decrypter=_HttpAuthService().decrypt_password,
    )

    assert result.embedding_model is None
    assert result.crawl_context.embedding_model_id is None
    assert result.crawl_context.embedding_model_name is None
    assert result.crawl_context.embedding_model_family is None
    assert result.crawl_context.embedding_model_dimensions is None
    assert result.crawl_context.embedding_model_open_source is False
    assert session_scope.enter_count == 1
    assert session_scope.exit_count == 1


@pytest.mark.asyncio
async def test_bootstrap_crawl_skips_decryption_when_no_http_auth_in_db() -> None:
    tenant = _tenant()
    user = _user(tenant=tenant)
    website = _website(
        tenant_id=tenant.id,
        user_id=user.id,
        embedding_model=_model(),
    )
    session_scope = _BootstrapSessionScope(_BootstrapSession(website=website))
    auth_service = _HttpAuthService()

    result = await bootstrap_crawl(
        session_scope=lambda: session_scope,
        website_id=website.id,
        tenant=tenant,
        user=user,
        tenant_crawler_settings=TenantCrawlerSettings.from_overrides(None),
        settings=get_settings(),
        http_auth_password_decrypter=auth_service.decrypt_password,
    )

    assert auth_service.calls == []
    assert result.crawl_context.http_auth_user is None
    assert result.crawl_context.http_auth_pass is None
    assert session_scope.enter_count == 1
    assert session_scope.exit_count == 1
