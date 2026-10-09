"""Execute production persistence against real SQLite rows and foreign keys.

Only the async driver is adapted. PostgreSQL locking and the complete loader are
covered separately by integration tests; this suite starts no external services.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant_repo import AssistantRepository
from eneo.assistants.assistant_update import AssistantUpdate
from eneo.database.tables.app_table import Apps
from eneo.database.tables.assistant_table import (
    AssistantIntegrationKnowledge,
    AssistantMCPServers,
    AssistantMCPServerTools,
    Assistants,
    AssistantsFiles,
    AssistantsGroups,
    AssistantsWebsites,
)
from eneo.database.tables.capabilities_table import (
    AssistantCapabilities,
    SpaceCapabilities,
)
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.group_chats_table import (
    GroupChatsAssistantsMapping,
    GroupChatsTable,
)
from eneo.database.tables.groups_spaces_table import GroupsSpaces
from eneo.database.tables.mcp_server_table import (
    MCPServerTools,
    SpacesMCPServers,
    SpacesMCPServerTools,
)
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.service_table import Services
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import (
    Spaces,
    SpacesCompletionModels,
    SpacesEmbeddingModels,
    SpacesTranscriptionModels,
    SpacesUserGroups,
    SpacesUsers,
)
from eneo.database.tables.websites_spaces_table import WebsitesSpaces
from eneo.database.tables.websites_table import Websites
from eneo.group_chat.infrastructure.group_chat_repo import GroupChatRepository
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.spaces.space_repo import SpaceRepository
from eneo.spaces.space_update import SpaceUpdate
from eneo.sysadmin.stored_model_configuration import (
    ConfigurationRepair,
    StoredModelConfigurationRepository,
    configuration_fingerprint,
)
from eneo.websites.infrastructure.website_repo import WebsiteRepository


@pytest.fixture
def persisted():
    models = (
        Spaces,
        SpacesUsers,
        SpacesUserGroups,
        SpacesCompletionModels,
        SpacesEmbeddingModels,
        SpacesTranscriptionModels,
        SpacesMCPServers,
        SpacesMCPServerTools,
        SpaceCapabilities,
        Assistants,
        AssistantsGroups,
        AssistantsWebsites,
        AssistantsFiles,
        AssistantIntegrationKnowledge,
        AssistantMCPServers,
        AssistantMCPServerTools,
        AssistantCapabilities,
        GroupChatsTable,
        GroupChatsAssistantsMapping,
        Apps,
        Services,
        CollectionsTable,
        GroupsSpaces,
        Websites,
        WebsitesSpaces,
        MCPServerTools,
        Sessions,
        Questions,
    )
    names = {model.__table__.name for model in models}
    metadata = sa.MetaData()
    tables = {}
    for model in models:
        columns = []
        for column in model.__table__.columns:
            # Use the actual column types/PKs and all in-scope cascading FKs.
            foreign_keys = [
                sa.ForeignKey(fk.target_fullname, ondelete=fk.ondelete)
                for fk in column.foreign_keys
                if fk.target_fullname.split(".")[0] in names
            ]
            columns.append(
                sa.Column(
                    column.name,
                    sa.JSON() if isinstance(column.type, JSONB) else column.type,
                    *foreign_keys,
                    primary_key=column.primary_key,
                    nullable=column.nullable,
                    default=column.default,
                    server_default=sa.text("(lower(hex(randomblob(16))))")
                    if column.name == "id"
                    else column.server_default,
                )
            )
        tables[model] = sa.Table(model.__table__.name, metadata, *columns)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        metadata.create_all(connection)
        session = AsyncMock()
        session.execute.side_effect = connection.execute
        session.scalar.side_effect = connection.scalar
        session.scalars.side_effect = connection.scalars
        tenant_id, space_id, user_id = uuid4(), uuid4(), uuid4()
        connection.execute(
            sa.insert(tables[Spaces]).values(
                id=space_id, name="Original", tenant_id=tenant_id
            )
        )
        assistant_id, corrupt_id, chat_id = uuid4(), uuid4(), uuid4()
        for key, options in [
            (assistant_id, {"temperature": 0.4, "top_p": 0.8}),
            (corrupt_id, {"temperature": "hot"}),
        ]:
            connection.execute(
                sa.insert(tables[Assistants]).values(
                    id=key,
                    name="Assistant",
                    space_id=space_id,
                    user_id=user_id,
                    completion_model_kwargs=options,
                    is_default=False,
                    logging_enabled=True,
                    published=False,
                )
            )
        connection.execute(
            sa.insert(tables[GroupChatsTable]).values(
                id=chat_id, space_id=space_id, user_id=user_id, name="Chat"
            )
        )
        for key in [assistant_id, corrupt_id]:
            connection.execute(
                sa.insert(tables[GroupChatsAssistantsMapping]).values(
                    group_chat_id=chat_id, assistant_id=key, user_description="Keep"
                )
            )
        space_repo = SpaceRepository(
            session=session,
            user=SimpleNamespace(tenant_id=tenant_id),
            factory=MagicMock(),
            file_content_loader=MagicMock(),
            completion_model_repo=MagicMock(),
            embedding_model_repo=MagicMock(),
            transcription_model_repo=MagicMock(),
            http_auth_encryption=MagicMock(),
        )
        assistant_repo = AssistantRepository(
            session=session,
            user=SimpleNamespace(tenant_id=tenant_id),
            factory=MagicMock(),
            file_repo=MagicMock(),
            file_content_loader=MagicMock(),
            completion_model_repo=MagicMock(),
        )
        statements = []
        sa.event.listen(
            connection,
            "before_cursor_execute",
            lambda conn,
            cursor,
            statement,
            parameters,
            context,
            executemany: statements.append(statement),
        )
        yield SimpleNamespace(
            connection=connection,
            session=session,
            tables=tables,
            tenant_id=tenant_id,
            space_id=space_id,
            user_id=user_id,
            assistant_id=assistant_id,
            corrupt_id=corrupt_id,
            chat_id=chat_id,
            space_repo=space_repo,
            assistant_repo=assistant_repo,
            chat_repo=GroupChatRepository(session),
            statements=statements,
        )
    engine.dispose()


async def test_reloading_chat_after_write_refreshes_a_retained_orm_identity(persisted):
    from sqlalchemy.orm import Session

    # Keep the ORM row alive: a fresh projection must not depend on garbage
    # collection clearing the identity map between operations.
    with Session(bind=persisted.connection) as sync_session:
        session = AsyncMock()
        session.execute.side_effect = sync_session.execute
        persisted.space_repo.session = session
        old_rows = await persisted.space_repo._get_group_chats(persisted.space_id)
        assert len(old_rows[0].group_chat_assistants) == 2
        await persisted.chat_repo.update(
            persisted.chat_id, persisted.space_id, members={}
        )
        new_rows = await persisted.space_repo._get_group_chats(persisted.space_id)
        assert new_rows[0] is old_rows[0]
        assert new_rows[0].group_chat_assistants == []


def snapshot(db, *, exclude=()):
    return {
        model.__name__: db.connection.execute(sa.select(table)).all()
        for model, table in db.tables.items()
        if model not in exclude
    }


def add_hidden_mappings(db):
    for model, target in [
        (SpacesUsers, "user_id"),
        (SpacesUserGroups, "user_group_id"),
        (SpacesCompletionModels, "completion_model_id"),
        (SpacesEmbeddingModels, "embedding_model_id"),
        (SpacesTranscriptionModels, "transcription_model_id"),
        (SpacesMCPServers, "mcp_server_id"),
    ]:
        values = {"space_id": db.space_id, target: uuid4()}
        if model in (SpacesUsers, SpacesUserGroups):
            values["role"] = "viewer"
        db.connection.execute(sa.insert(db.tables[model]).values(**values))


def add_resource_rows(db):
    organization_id = uuid4()
    db.connection.execute(
        sa.insert(db.tables[Spaces]).values(
            id=organization_id, name="Organization", tenant_id=db.tenant_id
        )
    )
    db.connection.execute(
        sa.update(Spaces)
        .where(Spaces.id == db.space_id)
        .values(tenant_space_id=organization_id)
    )
    for owner in (db.space_id, organization_id):
        collection_id, website_id = uuid4(), uuid4()
        db.connection.execute(
            sa.insert(db.tables[CollectionsTable]).values(
                id=collection_id,
                space_id=owner,
                tenant_id=db.tenant_id,
                user_id=db.user_id,
                name="Knowledge",
                size=0,
            )
        )
        db.connection.execute(
            sa.insert(db.tables[Websites]).values(
                id=website_id,
                space_id=owner,
                tenant_id=db.tenant_id,
                user_id=db.user_id,
                embedding_model_id=uuid4(),
                url="https://example.org/",
                name="Site",
                size=0,
                download_files=False,
                crawl_type="crawl",
                update_interval="never",
            )
        )
        db.connection.execute(
            sa.insert(db.tables[AssistantsGroups]).values(
                assistant_id=db.assistant_id, group_id=collection_id
            )
        )
        db.connection.execute(
            sa.insert(db.tables[AssistantsWebsites]).values(
                assistant_id=db.assistant_id, website_id=website_id
            )
        )
    db.connection.execute(
        sa.insert(db.tables[AssistantIntegrationKnowledge]).values(
            assistant_id=db.assistant_id, integration_knowledge_id=uuid4()
        )
    )
    db.connection.execute(
        sa.insert(db.tables[AssistantsFiles]).values(
            assistant_id=db.assistant_id, file_id=uuid4(), inline_text=False
        )
    )
    db.connection.execute(
        sa.insert(db.tables[Apps]).values(
            id=uuid4(),
            name="App",
            tenant_id=db.tenant_id,
            user_id=db.user_id,
            space_id=db.space_id,
            published=False,
            completion_model_kwargs={},
        )
    )
    db.connection.execute(
        sa.insert(db.tables[Services]).values(
            id=uuid4(),
            name="Service",
            user_id=db.user_id,
            space_id=db.space_id,
            prompt="Keep",
            completion_model_kwargs={},
        )
    )
    session_id = uuid4()
    db.connection.execute(
        sa.insert(db.tables[Sessions]).values(
            id=session_id,
            name="History",
            user_id=db.user_id,
            assistant_id=db.corrupt_id,
        )
    )
    db.connection.execute(
        sa.insert(db.tables[Questions]).values(
            id=uuid4(),
            session_id=session_id,
            tenant_id=db.tenant_id,
            assistant_id=db.corrupt_id,
            question="Keep",
            answer="Keep",
            num_tokens_question=1,
            num_tokens_answer=1,
        )
    )


async def test_empty_settings_write_changes_no_rows_or_mapping_timestamps(persisted):
    add_hidden_mappings(persisted)
    add_resource_rows(persisted)
    before = snapshot(persisted)
    persisted.statements.clear()
    await persisted.space_repo.update_settings(persisted.space_id, SpaceUpdate())
    assert snapshot(persisted) == before
    assert not any(
        sql.startswith(("DELETE", "INSERT", "UPDATE")) for sql in persisted.statements
    )


async def test_space_rename_preserves_every_child_row(persisted):
    add_hidden_mappings(persisted)
    add_resource_rows(persisted)
    before = snapshot(persisted, exclude=(Spaces,))
    await persisted.space_repo.update_settings(
        persisted.space_id, SpaceUpdate(name="Renamed")
    )
    assert snapshot(persisted, exclude=(Spaces,)) == before
    assert (
        persisted.connection.scalar(
            sa.select(Spaces.name).where(Spaces.id == persisted.space_id)
        )
        == "Renamed"
    )


async def test_membership_edit_does_not_remove_hidden_members(persisted):
    add_hidden_mappings(persisted)
    before = persisted.connection.execute(
        sa.select(SpacesUsers.user_id, SpacesUsers.role)
    ).all()
    await persisted.space_repo.add_member(
        persisted.space_id,
        SimpleNamespace(id=persisted.user_id, role=SpaceRoleValue.ADMIN),
    )
    after = persisted.connection.execute(
        sa.select(SpacesUsers.user_id, SpacesUsers.role)
    ).all()
    assert set(after) == {*before, (persisted.user_id, "admin")}


async def test_unchanged_selection_emits_no_delete_or_insert_and_empty_clears(
    persisted,
):
    add_hidden_mappings(persisted)
    ids = list(
        persisted.connection.scalars(
            sa.select(SpacesCompletionModels.completion_model_id)
        )
    )
    persisted.statements.clear()
    await persisted.space_repo.update_settings(
        persisted.space_id, SpaceUpdate(completion_model_ids=ids)
    )
    assert not any(sql.startswith(("DELETE", "INSERT")) for sql in persisted.statements)
    await persisted.space_repo.update_settings(
        persisted.space_id, SpaceUpdate(completion_model_ids=[])
    )
    assert (
        list(
            persisted.connection.scalars(
                sa.select(SpacesCompletionModels.completion_model_id)
            )
        )
        == []
    )
    assert list(
        persisted.connection.scalars(
            sa.select(SpacesEmbeddingModels.embedding_model_id)
        )
    )


async def test_assistant_rename_preserves_raw_options_and_invalid_siblings(persisted):
    before = snapshot(persisted, exclude=(Assistants,))
    await persisted.assistant_repo.apply_update(
        persisted.assistant_id, persisted.space_id, AssistantUpdate(name="Renamed")
    )
    assert snapshot(persisted, exclude=(Assistants,)) == before
    values = dict(
        persisted.connection.execute(
            sa.select(Assistants.id, Assistants.completion_model_kwargs)
        ).all()
    )
    assert values[persisted.assistant_id] == {"temperature": 0.4, "top_p": 0.8}
    assert values[persisted.corrupt_id] == {"temperature": "hot"}


async def test_explicit_assistant_delete_preserves_invalid_sibling_and_its_seat(
    persisted,
):
    await persisted.assistant_repo.delete(persisted.assistant_id, persisted.space_id)
    assert list(persisted.connection.scalars(sa.select(Assistants.id))) == [
        persisted.corrupt_id
    ]
    assert list(
        persisted.connection.scalars(
            sa.select(GroupChatsAssistantsMapping.assistant_id)
        )
    ) == [persisted.corrupt_id]


async def test_chat_rename_preserves_hidden_seats_but_explicit_empty_clears_them(
    persisted,
):
    seats = persisted.connection.execute(
        sa.select(persisted.tables[GroupChatsAssistantsMapping])
    ).all()
    await persisted.chat_repo.update(
        persisted.chat_id, persisted.space_id, name="Renamed"
    )
    assert (
        persisted.connection.execute(
            sa.select(persisted.tables[GroupChatsAssistantsMapping])
        ).all()
        == seats
    )
    await persisted.chat_repo.update(persisted.chat_id, persisted.space_id, members={})
    assert (
        list(
            persisted.connection.scalars(
                sa.select(GroupChatsAssistantsMapping.assistant_id)
            )
        )
        == []
    )
    assert len(list(persisted.connection.scalars(sa.select(Assistants.id)))) == 2


async def test_foreign_space_cannot_change_an_assistant(persisted):
    before = snapshot(persisted)
    with pytest.raises(NotFoundException):
        await persisted.assistant_repo.apply_update(
            persisted.assistant_id, uuid4(), AssistantUpdate(name="No")
        )
    assert snapshot(persisted) == before


async def test_classification_change_checks_stored_models_but_preserves_function_markers(
    persisted,
):
    from eneo.database.tables.ai_models_table import (
        CompletionModels,
        EmbeddingModels,
        TranscriptionModels,
    )
    from eneo.database.tables.mcp_server_table import MCPServers
    from eneo.database.tables.security_classifications_table import (
        SecurityClassification,
    )

    # These projections need only classification fields, independent of model
    # availability/deprecation and independent of domain hydration.
    metadata = sa.MetaData()
    classification = sa.Table(
        SecurityClassification.__tablename__,
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid()),
        sa.Column("security_level", sa.Integer()),
    )
    catalogs = {}
    for model in (CompletionModels, EmbeddingModels, TranscriptionModels, MCPServers):
        catalogs[model] = sa.Table(
            model.__tablename__,
            metadata,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("security_classification_id", sa.Uuid()),
            *([sa.Column("purpose", sa.String())] if model is MCPServers else []),
        )
    metadata.create_all(persisted.connection)
    low, high = uuid4(), uuid4()
    persisted.connection.execute(
        sa.insert(classification),
        [
            {"id": low, "tenant_id": persisted.tenant_id, "security_level": 1},
            {"id": high, "tenant_id": persisted.tenant_id, "security_level": 3},
        ],
    )
    survivors = {}
    for model, mapping, key in (
        (CompletionModels, SpacesCompletionModels, "completion_model_id"),
        (EmbeddingModels, SpacesEmbeddingModels, "embedding_model_id"),
        (TranscriptionModels, SpacesTranscriptionModels, "transcription_model_id"),
        (MCPServers, SpacesMCPServers, "mcp_server_id"),
    ):
        safe_id = uuid4()
        survivors[mapping] = {safe_id}
        for model_id, class_id in ((uuid4(), None), (uuid4(), low), (safe_id, high)):
            values = {"id": model_id, "security_classification_id": class_id}
            if model is MCPServers:
                values["purpose"] = "general"
            persisted.connection.execute(sa.insert(catalogs[model]).values(**values))
            persisted.connection.execute(
                sa.insert(persisted.tables[mapping]).values(
                    **{"space_id": persisted.space_id, key: model_id}
                )
            )
    marker_id = uuid4()
    persisted.connection.execute(
        sa.insert(catalogs[MCPServers]).values(id=marker_id, purpose="image_generation")
    )
    persisted.connection.execute(
        sa.insert(persisted.tables[SpacesMCPServers]).values(
            space_id=persisted.space_id, mcp_server_id=marker_id
        )
    )
    survivors[SpacesMCPServers].add(marker_id)
    await persisted.space_repo.update_settings(
        persisted.space_id, SpaceUpdate(minimum_security_level=2)
    )
    for mapping, expected in survivors.items():
        target = next(
            column
            for column in persisted.tables[mapping].primary_key
            if column.name != "space_id"
        )
        assert set(persisted.connection.scalars(sa.select(target))) == expected


async def test_create_assistant_uses_same_relation_writer_and_preserves_initial_settings(
    persisted,
):
    from eneo.assistants.assistant_factory import AssistantFactory
    from tests.fixtures import TEST_USER

    assistant = AssistantFactory(MagicMock(), MagicMock()).create_assistant(
        "New assistant",
        TEST_USER,
        persisted.space_id,
        insight_enabled=True,
        data_retention_days=30,
        metadata_json={"color": "blue"},
    )
    assistant.enabled_capabilities = ["image_generation"]
    await persisted.assistant_repo.add(assistant)
    row = persisted.connection.execute(
        sa.select(persisted.tables[Assistants]).where(
            persisted.tables[Assistants].c.id == assistant.id,
        )
    ).one()
    assert row.insight_enabled is True
    assert row.data_retention_days == 30
    assert row.metadata_json == {"color": "blue"}
    assert list(
        persisted.connection.scalars(
            sa.select(AssistantCapabilities.purpose).where(
                AssistantCapabilities.assistant_id == assistant.id,
            )
        )
    ) == ["image_generation"]
    assert set(persisted.connection.scalars(sa.select(Assistants.id))) == {
        assistant.id,
        persisted.assistant_id,
        persisted.corrupt_id,
    }


async def test_inspection_paginates_scanned_rows_without_exposing_other_tenants(
    persisted,
):
    repo = StoredModelConfigurationRepository(persisted.session)
    first = await repo.inspect(persisted.tenant_id, "assistant", after=None, limit=1)
    assert first.scanned == 1 and first.next_after is not None
    second = await repo.inspect(
        persisted.tenant_id, "assistant", after=first.next_after, limit=1
    )
    assert second.scanned == 1 and second.next_after is None
    assert [row.resource_id for row in [*first.invalid, *second.invalid]] == [
        persisted.corrupt_id
    ]
    other = await repo.inspect(uuid4(), "assistant", after=None, limit=100)
    assert other.scanned == 0 and other.invalid == []


def test_repair_rejects_invalid_options_before_any_write():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ConfigurationRepair.model_validate(
            {
                "expected_fingerprint": "0" * 64,
                "replacement": {"temperature": "hot"},
                "dry_run": False,
            }
        )


async def test_inspection_and_idempotent_repair_preserve_identity_and_seats(persisted):
    repo = StoredModelConfigurationRepository(persisted.session)
    report = await repo.inspect(persisted.tenant_id, "assistant", after=None, limit=100)
    assert report.scanned == 2
    assert [row.resource_id for row in report.invalid] == [persisted.corrupt_id]
    assert "hot" not in report.model_dump_json()
    repair = ConfigurationRepair(
        expected_fingerprint=report.invalid[0].fingerprint,
        replacement=ModelKwargs(temperature=0.5),
    )
    before = snapshot(persisted)
    assert (
        await repo.repair(
            persisted.tenant_id, "assistant", persisted.corrupt_id, repair
        )
    ).status == "would_repair"
    assert snapshot(persisted) == before
    repair.dry_run = False
    assert (
        await repo.repair(
            persisted.tenant_id, "assistant", persisted.corrupt_id, repair
        )
    ).status == "repaired"
    assert (
        await repo.repair(
            persisted.tenant_id, "assistant", persisted.corrupt_id, repair
        )
    ).status == "unchanged"
    assert snapshot(persisted, exclude=(Assistants,)) == {
        key: value for key, value in before.items() if key != "Assistants"
    }
    assert (
        await repo.inspect(persisted.tenant_id, "assistant", after=None, limit=100)
    ).invalid == []


async def test_repair_rejects_changed_or_foreign_source(persisted):
    repo = StoredModelConfigurationRepository(persisted.session)
    request = ConfigurationRepair(
        expected_fingerprint=configuration_fingerprint({"temperature": "old"}),
        replacement=ModelKwargs(),
        dry_run=False,
    )
    before = snapshot(persisted)
    with pytest.raises(BadRequestException, match="changed"):
        await repo.repair(
            persisted.tenant_id, "assistant", persisted.corrupt_id, request
        )
    with pytest.raises(NotFoundException):
        await repo.repair(uuid4(), "assistant", persisted.corrupt_id, request)
    assert snapshot(persisted) == before


async def test_website_rename_preserves_unreadable_auth_and_blocks_origin_change(
    persisted,
):
    website_id = uuid4()
    persisted.connection.execute(
        sa.insert(persisted.tables[Websites]).values(
            id=website_id,
            space_id=persisted.space_id,
            tenant_id=persisted.tenant_id,
            user_id=persisted.user_id,
            embedding_model_id=uuid4(),
            url="https://example.org/old",
            name="Site",
            size=0,
            download_files=False,
            crawl_type="crawl",
            update_interval="never",
            http_auth_username="name",
            encrypted_auth_password="unreadable-ciphertext",
            http_auth_domain="example.org",
        )
    )
    repo = WebsiteRepository(persisted.session, MagicMock())
    await repo.update(website_id, persisted.space_id, name="Renamed")
    assert (
        persisted.connection.scalar(sa.select(Websites.encrypted_auth_password))
        == "unreadable-ciphertext"
    )
    with pytest.raises(BadRequestException):
        await repo.update(website_id, persisted.space_id, url="https://other.org/")
    await repo.update(
        website_id, persisted.space_id, url="https://other.org/", http_auth=None
    )
    assert (
        persisted.connection.scalar(sa.select(Websites.encrypted_auth_password)) is None
    )


async def test_mcp_override_must_belong_to_selected_server_and_diff_preserves_rows(
    persisted,
):
    server_id, tool_id, foreign_tool_id = uuid4(), uuid4(), uuid4()
    for key, server in [(tool_id, server_id), (foreign_tool_id, uuid4())]:
        persisted.connection.execute(
            sa.insert(persisted.tables[MCPServerTools]).values(
                id=key,
                mcp_server_id=server,
                name="Tool",
            )
        )
    await persisted.assistant_repo.add_mcp_server(
        persisted.assistant_id, persisted.space_id, server_id
    )
    with pytest.raises(BadRequestException, match="outside assistant MCP servers"):
        await persisted.assistant_repo.apply_update(
            persisted.assistant_id,
            persisted.space_id,
            AssistantUpdate(mcp_tools=[(foreign_tool_id, True)]),
        )
    await persisted.assistant_repo.apply_update(
        persisted.assistant_id,
        persisted.space_id,
        AssistantUpdate(mcp_tools=[(tool_id, False)]),
    )
    assert (
        persisted.connection.scalar(sa.select(AssistantMCPServerTools.is_enabled))
        is False
    )
    persisted.statements.clear()
    await persisted.assistant_repo.apply_update(
        persisted.assistant_id,
        persisted.space_id,
        AssistantUpdate(mcp_tools=[(tool_id, False)]),
    )
    assert not any(sql.startswith(("DELETE", "INSERT")) for sql in persisted.statements)


async def test_space_tool_overrides_validate_ownership_preserve_noops_and_clear(
    persisted,
):
    server_id, tool_id, foreign_tool_id = uuid4(), uuid4(), uuid4()
    for key, server in [(tool_id, server_id), (foreign_tool_id, uuid4())]:
        persisted.connection.execute(
            sa.insert(persisted.tables[MCPServerTools]).values(
                id=key,
                mcp_server_id=server,
                name="Tool",
            )
        )
    await persisted.space_repo.update_settings(
        persisted.space_id, SpaceUpdate(mcp_server_ids=[server_id])
    )
    with pytest.raises(BadRequestException, match="not assigned"):
        await persisted.space_repo.update_settings(
            persisted.space_id, SpaceUpdate(mcp_tools=[(foreign_tool_id, True)])
        )
    await persisted.space_repo.update_settings(
        persisted.space_id, SpaceUpdate(mcp_tools=[(tool_id, False)])
    )
    assert (
        persisted.connection.scalar(sa.select(SpacesMCPServerTools.is_enabled)) is False
    )
    persisted.statements.clear()
    await persisted.space_repo.update_settings(
        persisted.space_id, SpaceUpdate(mcp_tools=[(tool_id, False)])
    )
    assert not any(sql.startswith(("DELETE", "INSERT")) for sql in persisted.statements)
    await persisted.space_repo.update_settings(
        persisted.space_id, SpaceUpdate(mcp_tools=[])
    )
    assert (
        list(
            persisted.connection.scalars(
                sa.select(SpacesMCPServerTools.mcp_server_tool_id)
            )
        )
        == []
    )


async def test_assistant_move_preserves_history_and_destination_links(persisted):
    target = uuid4()
    persisted.connection.execute(
        sa.insert(persisted.tables[Spaces]).values(
            id=target, name="Target", tenant_id=persisted.tenant_id
        )
    )
    collection_id = uuid4()
    persisted.connection.execute(
        sa.insert(persisted.tables[CollectionsTable]).values(
            id=collection_id,
            space_id=persisted.space_id,
            tenant_id=persisted.tenant_id,
            user_id=persisted.user_id,
            name="Collection",
            size=0,
        )
    )
    persisted.connection.execute(
        sa.insert(persisted.tables[GroupsSpaces]).values(
            group_id=collection_id, space_id=target
        )
    )
    session_id = uuid4()
    persisted.connection.execute(
        sa.insert(persisted.tables[Sessions]).values(
            id=session_id,
            assistant_id=persisted.assistant_id,
            user_id=persisted.user_id,
            name="History",
        )
    )
    persisted.connection.execute(
        sa.insert(persisted.tables[Questions]).values(
            id=uuid4(),
            session_id=session_id,
            assistant_id=persisted.assistant_id,
            tenant_id=persisted.tenant_id,
            question="Keep",
            answer="Keep",
            num_tokens_question=1,
            num_tokens_answer=1,
        )
    )
    before = snapshot(persisted, exclude=(Assistants, GroupChatsAssistantsMapping))
    await persisted.assistant_repo.move(
        persisted.assistant_id, persisted.space_id, target
    )
    assert (
        snapshot(persisted, exclude=(Assistants, GroupChatsAssistantsMapping)) == before
    )
    assert (
        persisted.connection.scalar(
            sa.select(Assistants.space_id).where(
                Assistants.id == persisted.assistant_id
            )
        )
        == target
    )
    assert list(
        persisted.connection.scalars(
            sa.select(GroupChatsAssistantsMapping.assistant_id)
        )
    ) == [persisted.corrupt_id]
