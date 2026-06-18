from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from intric.ai_models.completion_models.completion_models_repo import (
    CompletionModelsRepository as AdminCompletionModelsRepository,
)
from intric.ai_models.embedding_models.embedding_models_repo import (
    AdminEmbeddingModelsService,
)
from intric.completion_models.domain.completion_model_repo import (
    CompletionModelRepository,
)
from intric.embedding_models.domain.embedding_model_repo import EmbeddingModelRepository
from intric.transcription_models.domain.transcription_model_repo import (
    TranscriptionModelRepository,
)
from tests.fixtures import TEST_TENANT, TEST_USER


class _EmptyResult:
    def all(self) -> list[Any]:
        return []

    def scalars(self) -> "_EmptyResult":
        return self


class _CapturingSession:
    def __init__(self) -> None:
        self.statement: Any | None = None

    async def execute(self, statement: Any) -> _EmptyResult:
        self.statement = statement
        return _EmptyResult()


def _compiled_sql(statement: Any) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


@pytest.mark.parametrize(
    ("repo_factory", "method_name"),
    [
        (CompletionModelRepository, "all"),
        (EmbeddingModelRepository, "all"),
        (TranscriptionModelRepository, "all"),
    ],
)
async def test_domain_model_repositories_do_not_include_global_rows(
    repo_factory, method_name
):
    session = _CapturingSession()
    repo = repo_factory(session, TEST_USER)

    await getattr(repo, method_name)()

    sql = _compiled_sql(session.statement)
    assert "tenant_id IS NULL" not in sql
    assert f"tenant_id = '{TEST_USER.tenant_id}'" in sql
    assert "JOIN model_providers" in sql


async def test_admin_completion_model_repo_scopes_to_tenant_only():
    session = _CapturingSession()
    repo = AdminCompletionModelsRepository(session)

    await repo.get_models(tenant_id=TEST_TENANT.id)

    sql = _compiled_sql(session.statement)
    assert "tenant_id IS NULL" not in sql
    assert f"tenant_id = '{TEST_TENANT.id}'" in sql
    assert "JOIN model_providers" in sql


async def test_admin_embedding_model_repo_scopes_to_tenant_only():
    session = _CapturingSession()
    repo = AdminEmbeddingModelsService(session)

    await repo.get_models(tenant_id=TEST_TENANT.id)

    sql = _compiled_sql(session.statement)
    assert "tenant_id IS NULL" not in sql
    assert f"tenant_id = '{TEST_TENANT.id}'" in sql
