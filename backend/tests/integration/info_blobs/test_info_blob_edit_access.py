"""Editing an info blob's metadata requires edit rights in the owning space.

The update endpoint used to skip the space check entirely (SpaceAction.EDIT
fell through the action switch) and wrote before checking, so any user in the
tenant could rename a document they were not allowed to read.
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.info_blobs.info_blob import InfoBlobUpdate
from eneo.main.exceptions import UnauthorizedException
from eneo.users.user import UserInDB


@dataclass
class Setup:
    reader: UserInDB
    org_id: UUID
    tenant_id: UUID
    admin_id: UUID
    model_id: UUID


async def _make_blob(session, *, space_id, tenant_id, admin_id, model_id):
    collection = CollectionsTable(
        name=f"c-{uuid4().hex[:6]}",
        space_id=space_id,
        tenant_id=tenant_id,
        embedding_model_id=model_id,
        size=0,
        user_id=admin_id,
    )
    session.add(collection)
    await session.flush()
    blob = InfoBlobs(
        title="Original title",
        text="text",
        size=4,
        source_id=uuid4(),
        version_state="active",
        group_id=collection.id,
        embedding_model_id=model_id,
        tenant_id=tenant_id,
        user_id=admin_id,
    )
    session.add(blob)
    await session.flush()
    return blob.id


async def _child(session, tenant_id, org_id, name):
    space = Spaces(name=name, tenant_id=tenant_id, tenant_space_id=org_id)
    session.add(space)
    await session.flush()
    return space.id


@pytest.fixture
async def setup(db_container, user_factory, embedding_model_factory):
    async with db_container() as container:
        session = container.session()
        admin = container.user()
        reader = await user_factory(session)
        org = (
            await session.scalars(
                sa.select(Spaces).where(
                    Spaces.tenant_id == admin.tenant_id,
                    Spaces.user_id.is_(None),
                    Spaces.tenant_space_id.is_(None),
                )
            )
        ).one()
        model = await embedding_model_factory(session)
        await session.flush()
        reader = await container.user_repo().get_user_by_id(reader.id)
        return Setup(reader, org.id, admin.tenant_id, admin.id, model.id)


async def _rename(container, blob_id, user_id, title):
    return await container.info_blob_service().update_info_blob(
        InfoBlobUpdate(id=blob_id, title=title, user_id=user_id)
    )


async def test_outsider_cannot_edit_a_blob_they_cannot_read(db_container, setup):
    async with db_container() as container:
        session = container.session()
        blob_id = await _make_blob(
            session,
            space_id=setup.org_id,
            tenant_id=setup.tenant_id,
            admin_id=setup.admin_id,
            model_id=setup.model_id,
        )

    async with db_container(user=setup.reader) as container:
        with pytest.raises(UnauthorizedException):
            await _rename(container, blob_id, setup.reader.id, "renamed by outsider")

    async with db_container() as container:
        title = await container.session().scalar(
            sa.select(InfoBlobs.title).where(InfoBlobs.id == blob_id)
        )
        assert title == "Original title"


@pytest.mark.parametrize(
    "role,allowed", [("viewer", False), ("editor", True), ("admin", True)]
)
async def test_edit_follows_the_space_role(db_container, setup, role, allowed):
    async with db_container() as container:
        session = container.session()
        shared = await _child(session, setup.tenant_id, setup.org_id, "Shared")
        session.add(SpacesUsers(space_id=shared, user_id=setup.reader.id, role=role))
        blob_id = await _make_blob(
            session,
            space_id=shared,
            tenant_id=setup.tenant_id,
            admin_id=setup.admin_id,
            model_id=setup.model_id,
        )

    async with db_container(user=setup.reader) as container:
        if allowed:
            updated = await _rename(container, blob_id, setup.reader.id, "Renamed")
            assert updated.title == "Renamed"
        else:
            with pytest.raises(UnauthorizedException):
                await _rename(container, blob_id, setup.reader.id, "Renamed")
