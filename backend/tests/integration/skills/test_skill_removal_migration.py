"""Exercise the removal migration on PostgreSQL within the test transaction."""

from pathlib import Path

import pytest
import sqlalchemy as sa

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


def _migration():
    config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[3] / "alembic")
    )
    revision = ScriptDirectory.from_config(config).get_revision("202609231000")
    assert revision is not None
    return revision.module


async def test_removal_migration_round_trip_keeps_live_slug_unique(db_container):
    def round_trip(connection):
        migration = _migration()
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            assert "removed_at" not in {
                column["name"]
                for column in sa.inspect(connection).get_columns("skills")
            }
            migration.upgrade()
        inspector = sa.inspect(connection)
        assert next(
            column
            for column in inspector.get_columns("skills")
            if column["name"] == "removed_at"
        )["nullable"]
        index = next(
            index
            for index in inspector.get_indexes("skills")
            if index["name"] == "uq_skills_space_id_slug"
        )
        assert index["unique"]
        assert "removed_at IS NULL" in index["dialect_options"]["postgresql_where"]

    async with db_container() as container:
        connection = await container.session().connection()
        await connection.run_sync(round_trip)


async def test_removal_migration_refuses_to_discard_retained_history(
    db_container, admin_user
):
    def downgrade(connection):
        with Operations.context(MigrationContext.configure(connection)):
            _migration().downgrade()

    async with db_container() as container:
        container.user.override(admin_user)
        service = container.organization_skill_service()
        skill = await service.create_organization_skill(
            slug="retained-migration",
            display_name="Retained",
            description="Retained history",
            instructions="Keep these instructions.",
        )
        await service.delete(skill_id=skill.id)
        connection = await container.session().connection()
        with pytest.raises(RuntimeError, match="Cannot discard Skill removal history"):
            await connection.run_sync(downgrade)
        retained = await service.get_organization_skill(skill_id=skill.id)
        assert retained.current_revision == skill.current_revision
        assert retained.removed_at is not None
