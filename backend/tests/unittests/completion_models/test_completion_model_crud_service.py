from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from eneo.completion_models.application.completion_model_crud_service import (
    CompletionModelCRUDService,
)
from eneo.main.config import get_settings


def _build_service(repo: AsyncMock) -> CompletionModelCRUDService:
    return CompletionModelCRUDService(
        user=SimpleNamespace(tenant_id=uuid4()),
        completion_model_repo=repo,
        security_classification_repo=AsyncMock(),
    )


def _model(*, family: str, tenant_id=None):
    return SimpleNamespace(family=family, tenant_id=tenant_id)


async def test_get_completion_models_hides_only_global_azure_when_flag_off(
    monkeypatch,
):
    monkeypatch.setattr(get_settings(), "using_azure_models", False)
    global_azure = _model(family="azure")
    tenant_azure = _model(family="azure", tenant_id=uuid4())
    openai = _model(family="openai")
    repo = AsyncMock()
    repo.all.return_value = [global_azure, tenant_azure, openai]
    service = _build_service(repo)

    models = await service.get_completion_models()

    assert models == [tenant_azure, openai]


async def test_get_completion_models_shows_global_azure_when_flag_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "using_azure_models", True)
    global_azure = _model(family="azure")
    tenant_azure = _model(family="azure", tenant_id=uuid4())
    repo = AsyncMock()
    repo.all.return_value = [global_azure, tenant_azure]
    service = _build_service(repo)

    models = await service.get_completion_models()

    assert models == [global_azure, tenant_azure]
