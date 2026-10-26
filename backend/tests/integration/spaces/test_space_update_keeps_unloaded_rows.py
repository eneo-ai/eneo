"""Saving a space must not delete rows the loader skipped as invalid.

The space loader leaves out assistants whose stored row fails validation (for
example a non-numeric completion_model_kwargs temperature). The former aggregate save deleted rows absent from its filtered projection.
Settings writes now have no authority over assistant rows."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.app_table import Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.groups_spaces_table import GroupsSpaces
from eneo.database.tables.mcp_server_table import MCPServers, SpacesMCPServers
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.service_table import Services
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import (
    Spaces,
    SpacesCompletionModels,
    SpacesEmbeddingModels,
    SpacesUserGroups,
    SpacesUsers,
)
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import Users
from eneo.database.tables.websites_spaces_table import WebsitesSpaces
from eneo.database.tables.websites_table import Websites
from eneo.main.exceptions import BadRequestException, UnauthorizedException
from eneo.spaces.space_update import SpaceUpdate
from eneo.sysadmin.stored_model_configuration import (
    ConfigurationRepair,
    StoredModelConfigurationRepository,
)
from eneo.users.user import UserAdd, UserState

CORRUPT_KWARGS = {"temperature": "hot"}


@pytest.mark.parametrize("personal", [True, False], ids=["personal", "shared"])
async def test_nonmember_can_initialize_own_space_without_reading_tenant_hub(
    db_container, admin_user, personal
):
    async with db_container() as container:
        owner = await container.user_repo().add(
            UserAdd(
                email=f"space-owner-{uuid4().hex}@example.com",
                username="Space owner",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
            )
        )

    async with db_container(user=owner) as container:
        init_service = container.space_init_service()
        hub = await container.space_service().get_or_create_tenant_space()
        assert hub.default_assistant is None
        assert owner.id not in hub.members
        # Public reads must still enforce membership, including before the hub
        # has a default assistant. Initialization must not widen that access.
        with pytest.raises(UnauthorizedException):
            await init_service.get_space(hub.id)
        if personal:
            space = await init_service.get_personal_space()
        else:
            space = await init_service.create_space("Owner's shared space")
        assert space.default_assistant is not None
        assert space.tenant_space_id == hub.id
        with pytest.raises(UnauthorizedException):
            await init_service.get_space(hub.id)
        hub_id = hub.id
        space_id = space.id
        default_id = space.default_assistant.id

    async with db_container() as container:
        hub = await container.space_repo().one(hub_id)
        assert hub.default_assistant is not None
        assert owner.id not in hub.members
        stored_defaults = (
            await container.session().scalars(
                sa.select(Assistants.id).where(
                    Assistants.space_id == space_id, Assistants.is_default.is_(True)
                )
            )
        ).all()
        assert stored_defaults == [default_id]


async def test_invalid_relationship_rolls_back_settings_in_same_transaction(
    db_container,
    space_with_skipped_assistant,
):
    ids = space_with_skipped_assistant
    with pytest.raises(BadRequestException):
        async with db_container() as container:
            await container.space_repo().update_settings(
                ids["space_id"],
                SpaceUpdate(name="Must roll back", mcp_tools=[(uuid4(), True)]),
            )
    async with db_container() as container:
        name = await container.session().scalar(
            sa.select(Spaces.name).where(Spaces.id == ids["space_id"])
        )
        assert name == "Keep my assistants"


async def _clone_assistant(session, source_id, *, name, kwargs):
    row = (
        (
            await session.execute(
                sa.select(Assistants.__table__).where(Assistants.id == source_id)
            )
        )
        .mappings()
        .one()
    )
    values = dict(row)
    clone_id = uuid4()
    values.update(
        id=clone_id, name=name, is_default=False, completion_model_kwargs=kwargs
    )
    await session.execute(sa.insert(Assistants.__table__).values(**values))
    return clone_id


@pytest.fixture
async def space_with_skipped_assistant(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        space = await container.space_init_service().create_space("Keep my assistants")
        assert space.id is not None
        assert space.default_assistant is not None
        default_id = space.default_assistant.id

        valid_id = await _clone_assistant(
            session, default_id, name="Valid sibling", kwargs={}
        )
        corrupt_id = await _clone_assistant(
            session, default_id, name="Corrupt sibling", kwargs=CORRUPT_KWARGS
        )

    return {
        "space_id": space.id,
        "valid_id": valid_id,
        "default_id": default_id,
        "corrupt_id": corrupt_id,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_renaming_a_space_keeps_a_skipped_assistant(
    db_container, space_with_skipped_assistant
):
    ids = space_with_skipped_assistant

    async with db_container() as container:
        space = await container.space_service().get_space(ids["space_id"])
        # The corrupt sibling really is skipped on load, so this exercises the
        # path that would otherwise delete it.
        assert ids["corrupt_id"] not in {a.id for a in space.assistants}

        await container.space_service().update_space(id=ids["space_id"], name="Renamed")

    async with db_container() as container:
        session = container.session()
        space_row = await session.get(Spaces, ids["space_id"])
        assert space_row is not None
        assert space_row.name == "Renamed"

        corrupt_row = await session.get(Assistants, ids["corrupt_id"])
        assert corrupt_row is not None
        assert corrupt_row.completion_model_kwargs == CORRUPT_KWARGS
        assert await session.get(Assistants, ids["valid_id"]) is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_deleting_a_loaded_assistant_still_works_and_spares_the_skipped_one(
    db_container, space_with_skipped_assistant
):
    ids = space_with_skipped_assistant

    async with db_container() as container:
        await container.assistant_service().delete_assistant(ids["valid_id"])

    async with db_container() as container:
        session = container.session()
        assert await session.get(Assistants, ids["valid_id"]) is None
        corrupt_row = await session.get(Assistants, ids["corrupt_id"])
        assert corrupt_row is not None
        assert corrupt_row.completion_model_kwargs == CORRUPT_KWARGS


async def test_repair_restores_skipped_assistant(
    db_container,
    admin_user,
    space_with_skipped_assistant,
):
    ids = space_with_skipped_assistant
    async with db_container() as container:
        repo = StoredModelConfigurationRepository(container.session())
        page = await repo.inspect(
            admin_user.tenant_id, "assistant", after=None, limit=200
        )
        invalid = next(
            row for row in page.invalid if row.resource_id == ids["corrupt_id"]
        )
        await repo.repair(
            admin_user.tenant_id,
            "assistant",
            ids["corrupt_id"],
            ConfigurationRepair(
                expected_fingerprint=invalid.fingerprint,
                replacement=ModelKwargs(temperature=0.4),
                dry_run=False,
            ),
        )
    async with db_container() as container:
        space = await container.space_service().get_space(ids["space_id"])
        assert ids["corrupt_id"] in {assistant.id for assistant in space.assistants}


async def test_unchanged_and_rename_keep_all_child_data_and_hidden_selections(
    db_container,
    admin_user,
    space_with_skipped_assistant,
    user_factory,
    completion_model_factory,
    embedding_model_factory,
    app_factory,
    service_factory,
):
    """Definition of done: the loader is lossy, the write contract is not.

    Include owned and inherited knowledge, soft-deleted principals, disabled
    configuration and history beneath the invalid assistant. Compare every
    column, including relationship timestamps, across separate transactions.
    """
    ids = space_with_skipped_assistant
    tables = (
        Assistants,
        SpacesUsers,
        SpacesUserGroups,
        SpacesCompletionModels,
        SpacesEmbeddingModels,
        SpacesMCPServers,
        CollectionsTable,
        GroupsSpaces,
        Websites,
        WebsitesSpaces,
        Apps,
        Services,
        Sessions,
        Questions,
    )

    async def snapshot(session):
        return {
            model.__tablename__: (
                await session.execute(
                    sa.select(model.__table__).order_by(
                        *model.__table__.primary_key.columns
                    )
                )
            ).all()
            for model in tables
        }

    async with db_container() as container:
        session = container.session()
        user = await user_factory(session, deleted_at=datetime.now(timezone.utc))
        deleted_user_id = user.id
        group_id = uuid4()
        await session.execute(
            sa.insert(UserGroups).values(
                id=group_id,
                name="SCIM deleted",
                tenant_id=admin_user.tenant_id,
                state="deleted",
            )
        )
        await session.execute(
            sa.insert(SpacesUsers).values(
                space_id=ids["space_id"], user_id=user.id, role="viewer"
            )
        )
        await session.execute(
            sa.insert(SpacesUserGroups).values(
                space_id=ids["space_id"], user_group_id=group_id, role="viewer"
            )
        )
        model = await completion_model_factory(
            session, "Deprecated", is_deprecated=True
        )
        deprecated_model_id = model.id
        await session.execute(
            sa.insert(SpacesCompletionModels).values(
                space_id=ids["space_id"], completion_model_id=model.id
            )
        )
        embedding = await embedding_model_factory(session)
        await session.execute(
            sa.insert(SpacesEmbeddingModels).values(
                space_id=ids["space_id"], embedding_model_id=embedding.id
            )
        )
        server_id = uuid4()
        await session.execute(
            sa.insert(MCPServers).values(
                id=server_id,
                tenant_id=admin_user.tenant_id,
                name="Disabled",
                http_url="https://example.org/mcp",
                http_auth_type="none",
                is_enabled=False,
            )
        )
        await session.execute(
            sa.insert(SpacesMCPServers).values(
                space_id=ids["space_id"], mcp_server_id=server_id
            )
        )
        space = await container.space_service().get_space(ids["space_id"])
        for owner_id in (ids["space_id"], space.tenant_space_id):
            assert owner_id is not None
            await session.execute(
                sa.insert(CollectionsTable).values(
                    id=uuid4(),
                    name="Collection",
                    size=0,
                    user_id=admin_user.id,
                    tenant_id=admin_user.tenant_id,
                    space_id=owner_id,
                    embedding_model_id=embedding.id,
                )
            )
            await session.execute(
                sa.insert(Websites).values(
                    id=uuid4(),
                    name="Website",
                    size=0,
                    user_id=admin_user.id,
                    tenant_id=admin_user.tenant_id,
                    space_id=owner_id,
                    embedding_model_id=embedding.id,
                    url="https://example.org/",
                    download_files=False,
                    crawl_type="crawl",
                    update_interval="never",
                    encrypted_auth_password="cannot-decrypt",
                    http_auth_username="test",
                    http_auth_domain="example.org",
                )
            )
        await app_factory(session, "App", model.id, space_id=ids["space_id"])
        await service_factory(session, "Service", model.id, space_id=ids["space_id"])
        session_id = uuid4()
        await session.execute(
            sa.insert(Sessions).values(
                id=session_id,
                user_id=admin_user.id,
                name="History",
                assistant_id=ids["corrupt_id"],
            )
        )
        await session.execute(
            sa.insert(Questions).values(
                id=uuid4(),
                tenant_id=admin_user.tenant_id,
                session_id=session_id,
                assistant_id=ids["corrupt_id"],
                question="Keep question",
                answer="Keep answer",
                num_tokens_question=1,
                num_tokens_answer=1,
            )
        )
        before = await snapshot(session)

    async with db_container() as container:
        space = await container.space_service().get_space(ids["space_id"])
        assert deleted_user_id not in space.members
        assert group_id not in space.group_members
        assert deprecated_model_id not in {
            model.id for model in space.completion_models
        }
        assert server_id not in {server.id for server in space.mcp_servers}
        assert len(space.websites) == 2
        assert len(space.collections) == 2
        await container.space_repo().update_settings(space.id, SpaceUpdate())
        await container.space_service().update_space(id=space.id, name="Renamed safely")

    async with db_container() as container:
        session = container.session()
        assert await snapshot(session) == before
        await session.execute(
            sa.update(Users).where(Users.id == deleted_user_id).values(deleted_at=None)
        )
        await session.execute(
            sa.update(UserGroups).where(UserGroups.id == group_id).values(state=None)
        )
        await session.execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id == deprecated_model_id)
            .values(is_deprecated=False)
        )
        await session.execute(
            sa.update(MCPServers)
            .where(MCPServers.id == server_id)
            .values(is_enabled=True)
        )
    async with db_container() as container:
        space = await container.space_service().get_space(ids["space_id"])
        assert deleted_user_id in space.members
        assert group_id in space.group_members
        assert deprecated_model_id in {model.id for model in space.completion_models}
        assert server_id in {server.id for server in space.mcp_servers}
