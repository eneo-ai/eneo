from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.authentication.auth_models import (
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
)
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.groups_spaces_table import GroupsSpaces
from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.database.tables.integration_knowledge_spaces_table import (
    IntegrationKnowledgesSpaces,
)
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.spaces_table import Spaces, SpacesUserGroups, SpacesUsers
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import usergroups_users_table
from eneo.database.tables.websites_spaces_table import WebsitesSpaces
from eneo.database.tables.websites_table import Websites
from eneo.main.exceptions import UnauthorizedException
from eneo.users.user import UserInDB
from eneo.websites.domain.crawl_run import CrawlType


@dataclass
class Knowledge:
    reader: UserInDB
    org_id: UUID
    reader_space_id: UUID
    source_type: type[CollectionsTable] | type[Websites] | type[IntegrationKnowledge]
    source_id: UUID
    blob_id: UUID
    text: str


@pytest.fixture
async def knowledge(
    request,
    db_container,
    user_factory,
    user_integration_factory,
    embedding_model_factory,
):
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
        session.add(SpacesUsers(space_id=org.id, user_id=admin.id, role="admin"))
        reader_space = Spaces(
            name="Reader's space",
            tenant_id=admin.tenant_id,
            user_id=reader.id,
            tenant_space_id=org.id,
        )
        session.add(reader_space)
        model = await embedding_model_factory(session)
        source_type = getattr(request, "param", "website")
        source_fields = dict(
            name="Organization knowledge",
            space_id=org.id,
            tenant_id=admin.tenant_id,
            embedding_model_id=model.id,
            size=0,
        )
        if source_type == "collection":
            source = CollectionsTable(**source_fields, user_id=admin.id)
        elif source_type == "website":
            source = Websites(
                **source_fields,
                user_id=admin.id,
                url="https://example.com/rules",
                download_files=True,
                crawl_type=CrawlType.CRAWL,
                update_interval="never",
            )
        else:
            integration = await user_integration_factory(session)
            source = IntegrationKnowledge(
                **source_fields,
                url="https://example.com/rules",
                user_integration_id=integration.id,
            )
        session.add(source)
        await session.flush()
        text = "Source content to verify the answer."
        blob = InfoBlobs(
            title="Reglemente",
            text=text,
            size=len(text.encode()),
            source_id=uuid4(),
            version_state="active",
            group_id=source.id if source_type == "collection" else None,
            website_id=source.id if source_type == "website" else None,
            integration_knowledge_id=source.id
            if source_type == "integration"
            else None,
            embedding_model_id=model.id,
            tenant_id=admin.tenant_id,
            user_id=admin.id,
        )
        session.add(blob)
        await session.flush()
        reader = await container.user_repo().get_user_by_id(reader.id)
        return Knowledge(
            reader, org.id, reader_space.id, type(source), source.id, blob.id, text
        )


@pytest.mark.parametrize(
    "knowledge", ["collection", "website", "integration"], indirect=True
)
async def test_user_can_preview_inherited_organization_knowledge(
    db_container, knowledge
):
    async with db_container() as container:
        assert (
            await container.info_blob_service().get_by_id(knowledge.blob_id)
        ).text == knowledge.text

    async with db_container(user=knowledge.reader) as container:
        assert (
            await container.info_blob_service().get_by_id(knowledge.blob_id)
        ).text == knowledge.text
        with pytest.raises(UnauthorizedException):
            await container.space_service().get_space(knowledge.org_id)
        with pytest.raises(UnauthorizedException):
            await container.info_blob_service().delete(knowledge.blob_id)


@pytest.mark.parametrize(
    "knowledge", ["collection", "website", "integration"], indirect=True
)
@pytest.mark.parametrize("destination", ["reader", "organization"])
async def test_preview_access_tracks_distribution(db_container, knowledge, destination):
    if knowledge.source_type is CollectionsTable:
        distribution = GroupsSpaces
        source_column = GroupsSpaces.collection_id
    elif knowledge.source_type is Websites:
        distribution = WebsitesSpaces
        source_column = WebsitesSpaces.website_id
    else:
        distribution = IntegrationKnowledgesSpaces
        source_column = IntegrationKnowledgesSpaces.integration_knowledge_id

    async with db_container() as container:
        session = container.session()
        owner_space = Spaces(
            name="Source owner's space",
            tenant_id=knowledge.reader.tenant_id,
            tenant_space_id=knowledge.org_id,
        )
        session.add(owner_space)
        await session.flush()
        await session.execute(
            sa.update(knowledge.source_type)
            .where(knowledge.source_type.id == knowledge.source_id)
            .values(space_id=owner_space.id)
        )

    async with db_container(user=knowledge.reader) as container:
        with pytest.raises(UnauthorizedException):
            await container.info_blob_service().get_by_id(knowledge.blob_id)

    target_id = (
        knowledge.reader_space_id if destination == "reader" else knowledge.org_id
    )
    async with db_container() as container:
        await container.session().execute(
            sa.insert(distribution).values(
                {source_column: knowledge.source_id, distribution.space_id: target_id}
            )
        )

    async with db_container(user=knowledge.reader) as container:
        assert (
            await container.info_blob_service().get_by_id(knowledge.blob_id)
        ).text == knowledge.text

    async with db_container() as container:
        await container.session().execute(
            sa.delete(distribution).where(source_column == knowledge.source_id)
        )

    async with db_container(user=knowledge.reader) as container:
        with pytest.raises(UnauthorizedException):
            await container.info_blob_service().get_by_id(knowledge.blob_id)


@pytest.mark.parametrize("membership", ["direct", "group"])
async def test_preview_access_tracks_shared_space_membership(
    db_container, knowledge, membership
):
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(Spaces)
            .where(Spaces.id == knowledge.reader_space_id)
            .values(user_id=None)
        )
        if membership == "direct":
            session.add(
                SpacesUsers(
                    space_id=knowledge.reader_space_id,
                    user_id=knowledge.reader.id,
                    role="viewer",
                )
            )
        else:
            group = UserGroups(name="Readers", tenant_id=knowledge.reader.tenant_id)
            session.add(group)
            await session.flush()
            group_id = group.id
            await session.execute(
                sa.insert(usergroups_users_table).values(
                    user_id=knowledge.reader.id, user_group_id=group.id
                )
            )
            session.add(
                SpacesUserGroups(
                    space_id=knowledge.reader_space_id,
                    user_group_id=group.id,
                    role="viewer",
                )
            )
        await session.flush()
        reader = await container.user_repo().get_user_by_id(knowledge.reader.id)

    async with db_container(user=reader) as container:
        assert (
            await container.info_blob_service().get_by_id(knowledge.blob_id)
        ).text == knowledge.text

    async with db_container() as container:
        if membership == "direct":
            await container.session().execute(
                sa.delete(SpacesUsers).where(
                    SpacesUsers.space_id == knowledge.reader_space_id
                )
            )
        else:
            await container.session().execute(
                sa.update(UserGroups)
                .where(UserGroups.id == group_id)
                .values(state="deleted")
            )

    # Reuse the snapshot to exercise the database-side deleted-group filter.
    async with db_container(user=reader) as container:
        with pytest.raises(UnauthorizedException):
            await container.info_blob_service().get_by_id(knowledge.blob_id)


async def test_preview_access_is_not_retained_after_organization_unlink(
    db_container, knowledge
):
    async with db_container() as container:
        await container.session().execute(
            sa.update(Spaces)
            .where(Spaces.id == knowledge.reader_space_id)
            .values(tenant_space_id=None)
        )
    async with db_container(user=knowledge.reader) as container:
        with pytest.raises(UnauthorizedException):
            await container.info_blob_service().get_by_id(knowledge.blob_id)


async def test_preview_cannot_cross_tenant_boundary(
    db_container, knowledge, tenant_factory, user_factory
):
    async with db_container() as container:
        session = container.session()
        tenant = await tenant_factory(session)
        reader = await user_factory(session, tenant_id=tenant.id)
        # A foreign key alone cannot authorize an organization in another tenant.
        session.add(
            Spaces(
                name="Foreign reader",
                tenant_id=tenant.id,
                user_id=reader.id,
                tenant_space_id=knowledge.org_id,
            )
        )
        await session.flush()
        reader = await container.user_repo().get_user_by_id(reader.id)
    async with db_container(user=reader) as container:
        with pytest.raises(UnauthorizedException):
            await container.info_blob_service().get_by_id(knowledge.blob_id)


@pytest.mark.parametrize("scope_type", [ApiKeyScopeType.TENANT, ApiKeyScopeType.SPACE])
async def test_preview_preserves_api_key_scope(db_container, knowledge, scope_type):
    key = ApiKeyV2InDB(
        id=uuid4(),
        tenant_id=knowledge.reader.tenant_id,
        owner_user_id=knowledge.reader.id,
        name="Reader key",
        key_prefix="test_",
        key_suffix="test",
        key_type=ApiKeyType.SK,
        key_hash="test",
        hash_version="sha256",
        permission=ApiKeyPermission.READ,
        state=ApiKeyState.ACTIVE,
        scope_type=scope_type,
        scope_id=knowledge.reader_space_id
        if scope_type == ApiKeyScopeType.SPACE
        else None,
    )
    reader = knowledge.reader.model_copy(update={"active_api_key": key})
    async with db_container(user=reader) as container:
        if scope_type == ApiKeyScopeType.TENANT:
            assert (
                await container.info_blob_service().get_by_id(knowledge.blob_id)
            ).text == knowledge.text
        else:
            with pytest.raises(UnauthorizedException):
                await container.info_blob_service().get_by_id(knowledge.blob_id)


async def test_http_preview_uses_existing_api_key_scope_guard(
    client, db_container, knowledge
):
    secret = f"test_{uuid4().hex}"
    async with db_container() as container:
        # Satisfy key-owner membership validation to reach request scope enforcement.
        container.session().add(
            SpacesUsers(
                space_id=knowledge.reader_space_id,
                user_id=knowledge.reader.id,
                role="viewer",
            )
        )
        await container.api_key_v2_repo().create(
            tenant_id=knowledge.reader.tenant_id,
            owner_user_id=knowledge.reader.id,
            created_by_user_id=container.user().id,
            scope_type="space",
            scope_id=knowledge.reader_space_id,
            permission="read",
            key_type=ApiKeyType.SK.value,
            key_hash=sha256(secret.encode()).hexdigest(),
            hash_version="sha256",
            key_prefix="test_",
            key_suffix=secret[-4:],
            name="Scoped reader",
            description=None,
            state="active",
        )

    response = await client.get(
        f"/api/v1/info-blobs/{knowledge.blob_id}/",
        headers={"X-API-Key": secret},
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "insufficient_scope"
    assert response.json()["context"]["auth_layer"] == "api_key_scope"
