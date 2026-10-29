from pathlib import Path

import pytest
import sqlalchemy as sa

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


def _migration():
    root = Path(__file__).resolve().parents[3]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    revision = ScriptDirectory.from_config(config).get_revision("202610291900")
    assert revision is not None
    return revision.module


async def test_reference_migration_round_trip_preserves_exact_revision_constraints(
    db_container,
):
    def round_trip(connection):
        with Operations.context(MigrationContext.configure(connection)):
            _migration().downgrade()
            assert (
                "skill_revision_dependencies"
                not in sa.inspect(connection).get_table_names()
            )
            _migration().upgrade()
        inspector = sa.inspect(connection)
        assert inspector.get_pk_constraint("skill_revision_dependencies")[
            "constrained_columns"
        ] == ["source_revision_id", "target_skill_id"]
        constraints = {
            row["name"]: row
            for row in inspector.get_foreign_keys("skill_revision_dependencies")
        }
        target = constraints["fk_skill_dependencies_target_revision"]
        assert target["referred_columns"] == ["skill_id", "id"]
        assert target["options"]["deferrable"]
        assert (
            constraints["fk_skill_dependencies_source_revision"]["options"]["ondelete"]
            == "CASCADE"
        )

    async with db_container() as container:
        connection = await container.session().connection()
        await connection.run_sync(round_trip)


async def test_reference_migration_refuses_to_discard_approved_closure(
    db_container, admin_user
):
    async with db_container() as container:
        container.user.override(admin_user)
        service = container.organization_skill_service()
        helper = await service.create_organization_skill(
            slug="reference-migration-helper",
            display_name="Helper",
            description="Plain language",
            instructions="Write clearly.",
        )
        await service.publish(
            skill_id=helper.id, expected_revision_id=helper.current_revision.id
        )
        await service.create_organization_skill(
            slug="reference-migration-parent",
            display_name="Parent",
            description="Communication",
            instructions=f"Use [Helper](eneo-skill:{helper.id}@{helper.current_revision.id}).",
        )

        def downgrade(connection):
            with Operations.context(MigrationContext.configure(connection)):
                _migration().downgrade()

        connection = await container.session().connection()
        with pytest.raises(
            RuntimeError, match="Cannot discard approved Skill reference history"
        ):
            await connection.run_sync(downgrade)
