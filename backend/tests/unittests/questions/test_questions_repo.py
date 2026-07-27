from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from eneo.questions.question import QuestionAdd
from eneo.questions.questions_repo import QuestionRepository
from eneo.skills.domain.skill import (
    SkillActivationEvidenceV1,
    SkillActivationReference,
    SkillBindingSource,
    SkillExecutionReference,
    SkillTurnEffectiveMode,
)


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


async def test_add_serializes_strict_skill_activation_evidence():
    evidence = SkillActivationEvidenceV1(
        effective_mode=SkillTurnEffectiveMode.EAGER,
        available=(),
        blocked=(),
        initially_active=(),
        selected_model_id=uuid4(),
        selected_model_route="gpt-4o",
        skill_context_tokens=0,
        skill_context_token_limit=12_800,
        token_count_source="litellm",
    )
    session = AsyncMock()
    session.scalar.return_value = MagicMock(id=uuid4())
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
            skill_activation=evidence,
        )
    )

    statement = session.scalar.await_args.args[0]
    params = statement.compile(dialect=postgresql.dialect()).params
    assert params["skill_activation"] == evidence.model_dump(mode="json")


async def test_answer_finalization_does_not_rewrite_frozen_skill_activation():
    session = AsyncMock()
    repo = QuestionRepository(session)

    await repo.update_with_answer(
        question_id=uuid4(),
        tenant_id=uuid4(),
        answer="Completed",
        num_tokens_question=10,
        num_tokens_answer=5,
    )

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "skill_activation" not in str(compiled)
    assert "skill_activation" not in compiled.params


async def test_answer_finalization_replaces_initial_skill_runtime_state():
    session = AsyncMock()
    repo = QuestionRepository(session)
    reference = SkillExecutionReference(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        revision_number=4,
        content_digest="b" * 64,
        position=1,
    )
    evidence = SkillActivationEvidenceV1(
        effective_mode=SkillTurnEffectiveMode.SELECTIVE,
        available=(
            SkillActivationReference(
                activation_key="skill-1",
                skill_id=reference.skill_id,
                skill_revision_id=reference.skill_revision_id,
                revision_number=reference.revision_number,
                content_digest=reference.content_digest,
                position=reference.position,
                source=SkillBindingSource.SPACE,
            ),
        ),
        blocked=(),
        initially_active=(),
        accepted=("skill-1",),
        selected_model_id=uuid4(),
        selected_model_route="openai/gpt-4o",
        skill_context_tokens=24,
        skill_context_token_limit=12_800,
        token_count_source="litellm",
        activation_rounds=1,
    )

    await repo.update_with_answer(
        question_id=uuid4(),
        tenant_id=uuid4(),
        answer="Completed",
        skill_provenance=(reference,),
        skill_activation=evidence,
    )

    statement = session.execute.await_args.args[0]
    params = statement.compile(dialect=postgresql.dialect()).params
    assert params["skill_provenance"] == [
        {
            "skill_id": str(reference.skill_id),
            "skill_revision_id": str(reference.skill_revision_id),
            "revision_number": 4,
            "content_digest": "b" * 64,
            "position": 1,
        }
    ]
    assert params["skill_activation"] == evidence.model_dump(mode="json")


async def test_skill_runtime_state_update_is_tenant_scoped():
    session = AsyncMock()
    repo = QuestionRepository(session)
    question_id = uuid4()
    tenant_id = uuid4()
    evidence = SkillActivationEvidenceV1(
        effective_mode=SkillTurnEffectiveMode.ALWAYS_ONLY,
        available=(),
        blocked=(),
        initially_active=(),
        selected_model_id=uuid4(),
        selected_model_route="openai/gpt-4o",
        skill_context_tokens=0,
        skill_context_token_limit=12_800,
        token_count_source="litellm",
    )

    await repo.update_skill_runtime_state(
        question_id=question_id,
        tenant_id=tenant_id,
        skill_provenance=(),
        skill_activation=evidence,
    )

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "questions.id =" in str(compiled)
    assert "questions.tenant_id =" in str(compiled)
    assert question_id in compiled.params.values()
    assert tenant_id in compiled.params.values()
    assert compiled.params["skill_provenance"] == []
    assert compiled.params["skill_activation"] == evidence.model_dump(mode="json")
