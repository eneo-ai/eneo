from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from eneo.questions.question import QuestionAdd
from eneo.questions.questions_repo import QuestionRepository, QuestionSessionPartner
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


async def test_get_session_partner_uses_tenant_scoped_scalar_join():
    question_id = uuid4()
    tenant_id = uuid4()
    assistant_id = uuid4()
    result = MagicMock()
    result.one_or_none.return_value = (assistant_id, None)
    session = AsyncMock()
    session.execute.return_value = result
    repo = QuestionRepository(session)

    partner = await repo.get_session_partner(
        id=question_id,
        tenant_id=tenant_id,
    )

    assert partner == QuestionSessionPartner(
        assistant_id=assistant_id,
        group_chat_id=None,
    )
    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "FROM questions JOIN sessions" in sql
    assert "questions.id =" in sql
    assert "questions.tenant_id =" in sql
    assert "questions.question" not in sql
    assert "questions.answer" not in sql
    assert question_id in compiled.params.values()
    assert tenant_id in compiled.params.values()


async def test_get_for_tenant_is_scoped_before_hydration():
    question_id = uuid4()
    tenant_id = uuid4()
    repo = QuestionRepository(AsyncMock())
    repo.delegate.get_model_from_query = AsyncMock(return_value=None)

    question = await repo.get_for_tenant(id=question_id, tenant_id=tenant_id)

    assert question is None
    statement = repo.delegate.get_model_from_query.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "questions.id =" in sql
    assert "questions.tenant_id =" in sql
    assert question_id in compiled.params.values()
    assert tenant_id in compiled.params.values()


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
        context_prompt_tokens=6,
        context_completion_tokens=4,
        skill_context_tokens=3,
    )

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert compiled.params["context_prompt_tokens"] == 6
    assert compiled.params["context_completion_tokens"] == 4
    assert compiled.params["skill_context_tokens"] == 3
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


async def test_skill_activation_evidence_read_is_bounded_to_one_turn():
    question_id = uuid4()
    session_id = uuid4()
    tenant_id = uuid4()
    evidence = SkillActivationEvidenceV1(
        effective_mode=SkillTurnEffectiveMode.EAGER,
        available=(),
        blocked=(),
        initially_active=(),
        selected_model_id=uuid4(),
        selected_model_route="gpt-4o",
        skill_context_tokens=0,
        skill_context_token_limit=1_000,
        token_count_source="litellm",
    )
    session = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = SimpleNamespace(
        skill_activation_data=evidence.model_dump(mode="json")
    )
    session.execute.return_value = result
    file_loader = MagicMock()
    repo = QuestionRepository(session, file_content_loader=file_loader)

    stored = await repo.get_skill_activation_evidence(
        id=question_id,
        session_id=session_id,
        tenant_id=tenant_id,
    )

    assert stored is not None
    assert stored.evidence == evidence
    file_loader.assert_not_called()
    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert sql.startswith("SELECT questions.skill_activation")
    assert "questions.id =" in sql
    assert "questions.session_id =" in sql
    assert "questions.tenant_id =" in sql
    assert "questions.question" not in sql
    assert "questions.answer" not in sql
    assert {question_id, session_id, tenant_id}.issubset(set(compiled.params.values()))


async def test_skill_activation_evidence_read_rejects_untyped_body_fields():
    evidence = SkillActivationEvidenceV1(
        effective_mode=SkillTurnEffectiveMode.EAGER,
        available=(),
        blocked=(),
        initially_active=(),
        selected_model_id=uuid4(),
        selected_model_route="gpt-4o",
        skill_context_tokens=0,
        skill_context_token_limit=1_000,
        token_count_source="litellm",
    ).model_dump(mode="json")
    evidence["instructions"] = "secret-instructions"
    session = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = SimpleNamespace(skill_activation_data=evidence)
    session.execute.return_value = result
    repo = QuestionRepository(session, file_content_loader=MagicMock())

    with pytest.raises(ValidationError):
        await repo.get_skill_activation_evidence(
            id=uuid4(),
            session_id=uuid4(),
            tenant_id=uuid4(),
        )


async def test_turn_without_activation_evidence_is_distinct_from_missing_message():
    session = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = SimpleNamespace(skill_activation_data=None)
    session.execute.return_value = result
    repo = QuestionRepository(session)

    stored = await repo.get_skill_activation_evidence(
        id=uuid4(),
        session_id=uuid4(),
        tenant_id=uuid4(),
    )

    assert stored is not None
    assert stored.evidence is None
