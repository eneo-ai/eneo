from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from eneo.skills.infrastructure.skill_repo_impl import SkillRepoImpl


class _RowsResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def tuples(self) -> "_RowsResult":
        return self

    def all(self) -> list[tuple[object, ...]]:
        return self._rows


async def test_skill_catalog_projects_only_body_free_current_revision_fields():
    now = datetime.now(timezone.utc)
    skill_id = uuid4()
    space_id = uuid4()
    revision_id = uuid4()
    creator_id = uuid4()
    session = AsyncMock()
    session.execute.return_value = _RowsResult(
        [
            (
                skill_id,
                space_id,
                "beta-skill",
                True,
                3,
                creator_id,
                now,
                now,
                revision_id,
                "Beta Skill",
                "A body-free catalog description",
                "d" * 64,
            )
        ]
    )
    repo = SkillRepoImpl(session)

    entries = await repo.list_catalog_entries(
        space_id=space_id,
        limit=3,
        after_slug="alpha-skill",
        query="Beta_100%",
    )

    assert len(entries) == 1
    assert entries[0].current_revision_id == revision_id
    assert entries[0].slug == "beta-skill"
    assert not hasattr(entries[0], "instructions")

    statement = session.execute.await_args.args[0]
    selected_keys = [column.key for column in statement.selected_columns]
    assert selected_keys == [
        "id",
        "space_id",
        "slug",
        "is_active",
        "current_revision_number",
        "created_by_user_id",
        "created_at",
        "updated_at",
        "current_revision_id",
        "display_name",
        "description",
        "content_digest",
    ]
    compiled = statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    sql = str(compiled)
    assert "skill_revisions.instructions" not in sql
    assert "skills.slug > 'alpha-skill'" in sql
    assert "ORDER BY skills.slug" in sql
    assert "LIMIT 3" in sql
    assert "ESCAPE" in sql


async def test_skill_catalog_count_uses_the_same_normalized_filter_scope():
    session = AsyncMock()
    session.scalar.return_value = 7
    repo = SkillRepoImpl(session)
    space_id = uuid4()

    count = await repo.count_catalog_entries(
        space_id=space_id,
        query="Payroll",
    )

    assert count == 7
    statement = session.scalar.await_args.args[0]
    compiled = statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    sql = str(compiled)
    assert "skills.space_id =" in sql
    assert str(space_id) in sql
    assert "skill_revisions.display_name" in sql
    assert "skill_revisions.description" in sql
    assert "skills.slug" in sql
