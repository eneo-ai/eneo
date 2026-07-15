from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from eneo.questions.question import QuestionAdd
from eneo.questions.questions_repo import QuestionRepository
from eneo.skills.domain.skill import SkillExecutionReference


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


async def test_add_serializes_skill_provenance_as_json_safe_revision_references():
    reference = SkillExecutionReference(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        revision_number=3,
        content_digest="a" * 64,
        position=0,
    )
    session = AsyncMock()
    record = MagicMock(id=uuid4())
    session.scalar.return_value = record
    repo = QuestionRepository(session)
    repo._add_references = AsyncMock(return_value=[])  # type: ignore[method-assign]
    repo.get = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]

    await repo.add(
        QuestionAdd(
            question="Question",
            answer="",
            num_tokens_question=1,
            num_tokens_answer=0,
            tenant_id=uuid4(),
            session_id=uuid4(),
            skill_provenance=[reference],
        )
    )

    statement = session.scalar.await_args.args[0]
    params = statement.compile(dialect=postgresql.dialect()).params
    assert params["skill_provenance"] == [
        {
            "skill_id": str(reference.skill_id),
            "skill_revision_id": str(reference.skill_revision_id),
            "revision_number": 3,
            "content_digest": "a" * 64,
            "position": 0,
        }
    ]
