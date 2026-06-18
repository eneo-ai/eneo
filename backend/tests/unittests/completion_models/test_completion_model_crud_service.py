from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from intric.completion_models.application.completion_model_crud_service import (
    CompletionModelCRUDService,
)


def _build_service(repo: AsyncMock) -> CompletionModelCRUDService:
    return CompletionModelCRUDService(
        user=SimpleNamespace(tenant_id=uuid4()),
        completion_model_repo=repo,
        security_classification_repo=AsyncMock(),
    )


def _model(*, family: str, tenant_id=None):
    return SimpleNamespace(family=family, tenant_id=tenant_id)


async def test_get_completion_models_returns_repository_models_without_global_filter():
    tenant_azure = _model(family="azure", tenant_id=uuid4())
    openai = _model(family="openai")
    repo = AsyncMock()
    repo.all.return_value = [tenant_azure, openai]
    service = _build_service(repo)

    models = await service.get_completion_models()

    assert models == [tenant_azure, openai]
    repo.all.assert_awaited_once_with()
