import pytest
from dependency_injector import providers

from eneo.main.container.container import Container


@pytest.mark.integration
@pytest.mark.asyncio
async def test_model_repositories_resolve_with_tenant_scope_without_user(
    async_session,
    test_tenant,
):
    container = Container(
        session=providers.Object(async_session),
        tenant=providers.Object(test_tenant),
    )

    completion_repo = container.completion_model_repo2()
    embedding_repo = container.embedding_model_repo2()
    transcription_repo = container.transcription_model_repo()

    assert isinstance(await completion_repo.all(with_deprecated=True), list)
    assert isinstance(await embedding_repo.all(with_deprecated=True), list)
    assert isinstance(await transcription_repo.all(with_deprecated=True), list)
