from __future__ import annotations

import asyncio
import importlib.util
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    Flows,
    FlowVersionFileReferences,
    FlowVersions,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.users_table import Users
from eneo.flows.published_definition import published_definition_checksum

_FLOW_ID = UUID("00000000-0000-0000-0000-00000000f10a")


def _migration():
    path = (
        Path(__file__).parents[3]
        / "alembic/versions/202610021015_backfill_flow_version_file_references.py"
    )
    spec = importlib.util.spec_from_file_location("backfill_batches_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _definition(file_id: UUID) -> dict[str, object]:
    return {
        "schema_version": 1,
        "steps": [{"assistant_snapshot": {"attachments": [{"file_id": str(file_id)}]}}],
    }


async def _references(database: DatabaseSessionManager) -> set[tuple[int, UUID]]:
    async with database.session() as session, session.begin():
        rows = await session.execute(
            sa.select(
                FlowVersionFileReferences.version, FlowVersionFileReferences.file_id
            ).where(FlowVersionFileReferences.flow_id == _FLOW_ID)
        )
        return {(version, file_id) for version, file_id in rows.all()}


@pytest.mark.asyncio
async def test_each_backfill_batch_commits_before_the_next_and_a_restart_completes(
    object_content_database: DatabaseSessionManager,
) -> None:
    async with object_content_database.session() as session, session.begin():
        row = (await session.execute(sa.select(Users.tenant_id, Users.id))).one()
        tenant_id, user_id = row.tenant_id, row.id
        space = await session.scalar(sa.select(Spaces).where(Spaces.user_id == user_id))
        if space is None:
            space = Spaces(name="Backfill space", tenant_id=tenant_id, user_id=user_id)
            session.add(space)
            await session.flush()
        files = [
            Files(
                name=f"v{n}.txt",
                mimetype="text/plain",
                file_type="text",
                owner_type="user",
                owner_user_id=user_id,
                tenant_id=tenant_id,
            )
            for n in (1, 2, 3)
        ]
        session.add_all(files)
        await session.execute(sa.delete(Flows).where(Flows.id == _FLOW_ID))
        session.add(
            Flows(
                id=_FLOW_ID,
                name=f"Backfill {uuid4().hex}",
                tenant_id=tenant_id,
                space_id=space.id,
            )
        )
        await session.flush()
        file_ids = [file.id for file in files]
        for version, file_id in enumerate(file_ids, start=1):
            definition = _definition(file_id)
            session.add(
                FlowVersions(
                    flow_id=_FLOW_ID,
                    version=version,
                    tenant_id=tenant_id,
                    definition_json=definition,
                    definition_checksum=published_definition_checksum(definition),
                )
            )
    assert await _references(object_content_database) == set()

    migration = _migration()
    engine = sa.create_engine(
        object_content_database._engine.url.set(drivername="postgresql+psycopg2")  # type: ignore[union-attr]
    )
    observer = sa.create_engine(engine.url)
    observed: list[set[tuple[int, UUID]]] = []

    def observed_now() -> set[tuple[int, UUID]]:
        with observer.connect() as other:
            return {
                (version, file_id)
                for version, file_id in other.execute(
                    sa.text(
                        "SELECT version, file_id FROM flow_version_file_references "
                        "WHERE flow_id = :flow_id"
                    ),
                    {"flow_id": _FLOW_ID},
                )
            }

    def interrupted(batch_size: int, fail_on: int) -> None:
        batches = 0

        @contextmanager
        def begin() -> Iterator[sa.Connection]:
            nonlocal batches
            batches += 1
            if batches >= 2:
                # Another connection sees every batch finished before this one.
                observed.append(observed_now())
            with engine.begin() as connection:
                yield connection
                if batches == fail_on:
                    raise RuntimeError("interrupted")

        migration.backfill_flow_version_file_references(begin, batch_size=batch_size)

    try:
        with pytest.raises(RuntimeError, match="interrupted"):
            await asyncio.to_thread(interrupted, 1, 3)
        # Batches 1 and 2 are committed and visible to a separate connection;
        # the interrupted third batch rolled back.
        assert observed[0] == {(1, file_ids[0])}
        assert observed[1] == {(1, file_ids[0]), (2, file_ids[1])}
        assert await _references(object_content_database) == {
            (1, file_ids[0]),
            (2, file_ids[1]),
        }

        await asyncio.to_thread(
            migration.backfill_flow_version_file_references,
            engine.begin,
            batch_size=1,
        )
        assert await _references(object_content_database) == {
            (n, file_ids[n - 1]) for n in (1, 2, 3)
        }
    finally:
        engine.dispose()
        observer.dispose()
