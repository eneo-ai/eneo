from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from alembic import command
from alembic.config import Config
from eneo.database.renumbered_revisions import (
    RENUMBERED_BRANCH_REVISIONS,
    RenumberedRevision,
    RenumberedRevisionStampError,
    check_renumbered_revision_stamp,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _database(tmp_path: Path, stamps: list[str], ddl: list[str]) -> Engine:
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
        for stamp in stamps:
            connection.execute(
                text("INSERT INTO alembic_version VALUES (:stamp)"), {"stamp": stamp}
            )
        for statement in ddl:
            connection.execute(text(statement))
    return engine


def _branch_schema(revision: RenumberedRevision) -> str:
    column = revision.column or "id"
    return f"CREATE TABLE {revision.table} ({column} TEXT)"


@pytest.mark.parametrize("revision", RENUMBERED_BRANCH_REVISIONS, ids=lambda r: r.old)
def test_an_old_branch_stamp_with_the_branch_schema_is_refused_with_its_repair(
    tmp_path: Path, revision: RenumberedRevision
):
    engine = _database(tmp_path, [revision.old], [_branch_schema(revision)])

    with engine.connect() as connection:
        with pytest.raises(RenumberedRevisionStampError) as refused:
            check_renumbered_revision_stamp(connection)

    assert f"alembic stamp --purge {revision.new}" in str(refused.value)


@pytest.mark.parametrize("revision", RENUMBERED_BRANCH_REVISIONS, ids=lambda r: r.old)
def test_develops_own_stamp_at_the_same_id_passes(
    tmp_path: Path, revision: RenumberedRevision
):
    # Develop's migration of this id never creates the branch's table or column.
    ddl = [f"CREATE TABLE {revision.table} (id TEXT)"] if revision.column else []
    engine = _database(tmp_path, [revision.old], ddl)

    with engine.connect() as connection:
        check_renumbered_revision_stamp(connection)


def test_the_merged_history_applying_develops_chain_beside_the_branch_passes(
    tmp_path: Path,
):
    revision = RENUMBERED_BRANCH_REVISIONS[0]
    engine = _database(
        tmp_path, ["202609241200", revision.old], [_branch_schema(revision)]
    )

    with engine.connect() as connection:
        check_renumbered_revision_stamp(connection)


def test_a_database_without_a_version_table_passes(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")

    with engine.connect() as connection:
        check_renumbered_revision_stamp(connection)


def test_alembic_refuses_the_upgrade_and_the_repair_stamp_clears_it(tmp_path: Path):
    """Through env.py: upgrade stops before any migration runs, and the stamp
    the error names still runs."""
    revision = RENUMBERED_BRANCH_REVISIONS[2]
    engine = _database(tmp_path, [revision.old], [_branch_schema(revision)])
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", str(engine.url))

    with pytest.raises(RenumberedRevisionStampError):
        command.upgrade(config, "head")

    command.stamp(config, revision.new, purge=True)

    with engine.connect() as connection:
        stamps = list(
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars()
        )
        check_renumbered_revision_stamp(connection)
    assert stamps == [revision.new]
