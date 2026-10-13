"""IntegrationKnowledgeRepoImpl: the SQL it issues, without a database."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from eneo.integration.infrastructure.repo_impl.integration_knowledge_repo_impl import (
    IntegrationKnowledgeRepoImpl,
)
from eneo.main.exceptions import NotFoundException


@pytest.fixture
def session():
    return AsyncMock()


@pytest.fixture
def repo(session):
    return IntegrationKnowledgeRepoImpl(
        session=session, mapper=MagicMock(), embedding_model_repo=AsyncMock()
    )


def _compiled(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


class TestAdjustSize:
    async def test_adds_delta_in_sql_and_returns_the_new_size(self, repo, session):
        knowledge_id = uuid4()
        session.scalar.return_value = 90

        new_size = await repo.adjust_size(knowledge_id, -40)

        assert new_size == 90
        sql = _compiled(session.scalar.await_args.args[0])
        assert "UPDATE integration_knowledge SET size=greatest(" in sql
        assert "coalesce(integration_knowledge.size, 0) + -40" in sql
        assert "RETURNING integration_knowledge.size" in sql
        assert f"'{knowledge_id}'" in sql

    async def test_missing_row_raises(self, repo, session):
        session.scalar.return_value = None

        with pytest.raises(NotFoundException):
            await repo.adjust_size(uuid4(), 10)
