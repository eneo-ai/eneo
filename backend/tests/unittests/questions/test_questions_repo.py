from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from eneo.questions.questions_repo import QuestionRepository


async def test_get_by_tenant_filters_out_questions_without_session_id():
    repo = QuestionRepository(AsyncMock())
    repo.delegate.get_models_from_query = AsyncMock(return_value=[])

    await repo.get_by_tenant(
        tenant_id=uuid4(),
        start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2024, 1, 31, tzinfo=timezone.utc),
    )

    stmt = repo.delegate.get_models_from_query.await_args.args[0]
    compiled = str(stmt.compile(dialect=postgresql.dialect()))

    assert "questions.session_id IS NOT NULL" in compiled
