"""Boundaries of the citation read-access fallback.

The fallback in InfoBlobService._can_perform_action lets a user read a blob
from any space they belong to that sees the blob's source. These cases pin
where that stops, so a later change cannot widen it unnoticed:

* a source distributed to a sibling child space the reader is not in
* organization-space viewer/editor membership is not upgraded by the fallback
* tenant-scoped service keys gain nothing from membership they do not have
* a user group from another tenant cannot grant membership
* assistant-scoped user keys never enter the fallback
* the original-file path follows the same rule as the text preview
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.authentication.auth_models import (
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
)
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.groups_spaces_table import GroupsSpaces
from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.database.tables.spaces_table import Spaces, SpacesUserGroups, SpacesUsers
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import usergroups_users_table
from eneo.main.exceptions import UnauthorizedException
from eneo.users.user import UserInDB


@dataclass
class Boundary:
    reader: UserInDB
    reader_space_id: UUID  # personal space, already UNLINKED from org
    org_id: UUID
    tenant_id: UUID
    admin_id: UUID
    model_id: UUID


async def _make_blob(session, *, space_id, tenant_id, admin_id, model_id):
    coll = CollectionsTable(
        name=f"c-{uuid4().hex[:6]}",
        space_id=space_id,
        tenant_id=tenant_id,
        embedding_model_id=model_id,
        size=0,
        user_id=admin_id,
    )
    session.add(coll)
    await session.flush()
    blob = InfoBlobs(
        title="t",
        text="secret text",
        size=11,
        source_id=uuid4(),
        version_state="active",
        group_id=coll.id,
        embedding_model_id=model_id,
        tenant_id=tenant_id,
        user_id=admin_id,
    )
    session.add(blob)
    await session.flush()
    return coll.id, blob.id


@pytest.fixture
async def boundary(db_container, user_factory, embedding_model_factory):
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
        # Personal space deliberately NOT linked to the org, so the only
        # access path under test is the one each case sets up.
        personal = Spaces(
            name="Reader personal", tenant_id=admin.tenant_id, user_id=reader.id
        )
        session.add(personal)
        model = await embedding_model_factory(session)
        await session.flush()
        reader = await container.user_repo().get_user_by_id(reader.id)
        return Boundary(
            reader, personal.id, org.id, admin.tenant_id, admin.id, model.id
        )


async def _child(session, tenant_id, org_id, name):
    s = Spaces(name=name, tenant_id=tenant_id, tenant_space_id=org_id)
    session.add(s)
    await session.flush()
    return s.id


async def test_distribution_to_sibling_child_space_does_not_leak(
    db_container, boundary
):
    async with db_container() as container:
        session = container.session()
        a = await _child(session, boundary.tenant_id, boundary.org_id, "A owner")
        c = await _child(session, boundary.tenant_id, boundary.org_id, "C reader")
        d = await _child(session, boundary.tenant_id, boundary.org_id, "D other")
        session.add(SpacesUsers(space_id=c, user_id=boundary.reader.id, role="viewer"))
        coll_id, blob_id = await _make_blob(
            session,
            space_id=a,
            tenant_id=boundary.tenant_id,
            admin_id=boundary.admin_id,
            model_id=boundary.model_id,
        )
        await session.execute(
            sa.insert(GroupsSpaces).values(collection_id=coll_id, space_id=d)
        )
        await session.flush()

    async with db_container(user=boundary.reader) as container:
        with pytest.raises(UnauthorizedException):
            await container.info_blob_service().get_by_id(blob_id)

    # control: distribute to the reader's space -> allowed
    async with db_container() as container:
        await container.session().execute(
            sa.insert(GroupsSpaces).values(collection_id=coll_id, space_id=c)
        )
    async with db_container(user=boundary.reader) as container:
        assert (await container.info_blob_service().get_by_id(blob_id)).text


@pytest.mark.parametrize(
    "role,allowed", [("viewer", False), ("editor", False), ("admin", True)]
)
async def test_org_space_membership_role_semantics_preserved(
    db_container, boundary, role, allowed
):
    async with db_container() as container:
        session = container.session()
        session.add(
            SpacesUsers(space_id=boundary.org_id, user_id=boundary.reader.id, role=role)
        )
        _, blob_id = await _make_blob(
            session,
            space_id=boundary.org_id,
            tenant_id=boundary.tenant_id,
            admin_id=boundary.admin_id,
            model_id=boundary.model_id,
        )
        await session.flush()

    async with db_container(user=boundary.reader) as container:
        if allowed:
            assert (await container.info_blob_service().get_by_id(blob_id)).text
        else:
            with pytest.raises(UnauthorizedException):
                await container.info_blob_service().get_by_id(blob_id)


def _key(tenant_id, *, owner, scope_type, scope_id, permission):
    return ApiKeyV2InDB(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_user_id=owner,
        ownership=ApiKeyOwnership.SERVICE if owner is None else ApiKeyOwnership.USER,
        name="k",
        key_prefix="test_",
        key_suffix="test",
        key_type=ApiKeyType.SK,
        key_hash="h",
        hash_version="sha256",
        permission=permission,
        state=ApiKeyState.ACTIVE,
        scope_type=scope_type,
        scope_id=scope_id,
    )


@pytest.mark.parametrize(
    "permission,owned_by_org,allowed",
    [
        (
            ApiKeyPermission.READ,
            True,
            False,
        ),  # org VIEWER has no read; fallback yields nothing
        (ApiKeyPermission.ADMIN, True, True),  # org ADMIN (pre-existing path)
        (
            ApiKeyPermission.READ,
            False,
            True,
        ),  # shared space VIEWER via tenant key (pre-existing)
    ],
)
async def test_tenant_service_key_gains_nothing_from_fallback(
    db_container, boundary, permission, owned_by_org, allowed
):
    async with db_container() as container:
        session = container.session()
        space_id = (
            boundary.org_id
            if owned_by_org
            else await _child(session, boundary.tenant_id, boundary.org_id, "shared")
        )
        _, blob_id = await _make_blob(
            session,
            space_id=space_id,
            tenant_id=boundary.tenant_id,
            admin_id=boundary.admin_id,
            model_id=boundary.model_id,
        )
        await session.flush()
        key = _key(
            boundary.tenant_id,
            owner=None,
            scope_type=ApiKeyScopeType.TENANT,
            scope_id=None,
            permission=permission,
        )
        service_user = await container.user_service()._build_service_user(key)

    async with db_container(user=service_user) as container:
        if allowed:
            assert (await container.info_blob_service().get_by_id(blob_id)).text
        else:
            with pytest.raises(UnauthorizedException):
                await container.info_blob_service().get_by_id(blob_id)


@pytest.mark.parametrize("group_tenant", ["foreign", "own"])
async def test_group_membership_must_be_same_tenant(
    db_container, boundary, tenant_factory, group_tenant
):
    async with db_container() as container:
        session = container.session()
        c = await _child(session, boundary.tenant_id, boundary.org_id, "C reader")
        g_tenant = (
            (await tenant_factory(session)).id
            if group_tenant == "foreign"
            else boundary.tenant_id
        )
        group = UserGroups(name="G", tenant_id=g_tenant)
        session.add(group)
        await session.flush()
        group_id = group.id
        await session.execute(
            sa.insert(usergroups_users_table).values(
                user_id=boundary.reader.id, user_group_id=group_id
            )
        )
        session.add(SpacesUserGroups(space_id=c, user_group_id=group_id, role="viewer"))
        _, blob_id = await _make_blob(
            session,
            space_id=boundary.org_id,
            tenant_id=boundary.tenant_id,
            admin_id=boundary.admin_id,
            model_id=boundary.model_id,
        )
        await session.flush()
        reader = await container.user_repo().get_user_by_id(boundary.reader.id)

    assert group_id in reader.user_groups_ids  # user object itself carries the group
    async with db_container(user=reader) as container:
        if group_tenant == "own":
            assert (await container.info_blob_service().get_by_id(blob_id)).text
        else:
            with pytest.raises(UnauthorizedException):
                await container.info_blob_service().get_by_id(blob_id)


async def test_assistant_scoped_user_key_skips_fallback(db_container, boundary):
    async with db_container() as container:
        session = container.session()
        c = await _child(session, boundary.tenant_id, boundary.org_id, "C reader")
        session.add(SpacesUsers(space_id=c, user_id=boundary.reader.id, role="admin"))
        _, blob_id = await _make_blob(
            session,
            space_id=boundary.org_id,
            tenant_id=boundary.tenant_id,
            admin_id=boundary.admin_id,
            model_id=boundary.model_id,
        )
        await session.flush()

    key = _key(
        boundary.tenant_id,
        owner=boundary.reader.id,
        scope_type=ApiKeyScopeType.ASSISTANT,
        scope_id=uuid4(),
        permission=ApiKeyPermission.ADMIN,
    )
    reader = boundary.reader.model_copy(update={"active_api_key": key})
    async with db_container(user=reader) as container:
        with pytest.raises(UnauthorizedException):
            await container.info_blob_service().get_by_id(blob_id)
    # control: same membership without a key -> allowed
    async with db_container(user=boundary.reader) as container:
        assert (await container.info_blob_service().get_by_id(blob_id)).text


async def test_original_file_access_follows_the_preview_rule(db_container, boundary):
    """The signed-url path for originals goes through the same read check, so a
    reader who may preview the text may also fetch the original, and nobody
    else can."""
    from eneo.info_blobs.info_blob_service import InfoBlobOriginalUnavailableError

    async with db_container() as container:
        session = container.session()
        child = await _child(
            session, boundary.tenant_id, boundary.org_id, "Linked child"
        )
        session.add(
            SpacesUsers(space_id=child, user_id=boundary.reader.id, role="viewer")
        )
        _, blob_id = await _make_blob(
            session,
            space_id=boundary.org_id,
            tenant_id=boundary.tenant_id,
            admin_id=boundary.admin_id,
            model_id=boundary.model_id,
        )
        await session.flush()

    async with db_container(user=boundary.reader) as container:
        # Authorised: the check passes and only the missing stored original stops it.
        with pytest.raises(InfoBlobOriginalUnavailableError):
            await container.info_blob_service().ensure_original_available(blob_id)
