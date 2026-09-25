from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from eneo.database.tables.skill_table import SkillRevisions, Skills
from eneo.skills.domain.skill import SkillHasBindingsError, SkillSlugConflictError
from eneo.skills.infrastructure.skill_repo_impl import SkillRepoImpl


async def test_create_translates_the_skill_slug_constraint():
    original = SimpleNamespace(constraint_name="uq_skills_space_id_slug")
    session = AsyncMock()
    session.execute.side_effect = IntegrityError("insert", {}, original)
    repo = SkillRepoImpl(session)

    with pytest.raises(SkillSlugConflictError):
        await repo.create(
            space_id=uuid4(),
            slug="payroll",
            display_name="Payroll",
            description="Answers payroll questions",
            instructions="Use approved guidance.",
            content_digest="a" * 64,
            created_by_user_id=uuid4(),
        )


async def test_create_preserves_unrelated_integrity_failures():
    original = SimpleNamespace(constraint_name="some_other_constraint")
    error = IntegrityError("insert", {}, original)
    session = AsyncMock()
    session.execute.side_effect = error
    repo = SkillRepoImpl(session)

    with pytest.raises(IntegrityError) as raised:
        await repo.create(
            space_id=uuid4(),
            slug="payroll",
            display_name="Payroll",
            description="Answers payroll questions",
            instructions="Use approved guidance.",
            content_digest="a" * 64,
            created_by_user_id=uuid4(),
        )

    assert raised.value is error


async def test_delete_translates_a_binding_created_during_deletion():
    now = datetime.now(timezone.utc)
    skill_id = uuid4()
    skill_row = Skills(
        id=skill_id,
        space_id=uuid4(),
        slug="payroll",
        is_active=True,
        current_revision_number=1,
        created_by_user_id=uuid4(),
        created_at=now,
        updated_at=now,
    )
    revision_row = SkillRevisions(
        id=uuid4(),
        skill_id=skill_id,
        revision_number=1,
        display_name="Payroll",
        description="Answers payroll questions",
        instructions="Use approved guidance.",
        content_digest="a" * 64,
        created_by_user_id=uuid4(),
        created_at=now,
    )
    locked_result = MagicMock()
    locked_result.one_or_none.return_value = (skill_row, revision_row)
    delete_error = IntegrityError("delete", {}, Exception("foreign key violation"))
    session = AsyncMock()
    session.execute.side_effect = [locked_result, delete_error]
    repo = SkillRepoImpl(session)
    repo._is_bound = AsyncMock(return_value=False)
    repo._has_nonterminal_app_run = AsyncMock(return_value=False)

    with pytest.raises(SkillHasBindingsError):
        await repo.delete(skill_id=skill_id)
