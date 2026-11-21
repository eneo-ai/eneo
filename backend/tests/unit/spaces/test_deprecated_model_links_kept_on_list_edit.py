"""A space's model-list edit must keep links to deprecated models.

space_factory leaves deprecated models out of the read projection, so a save
built from what the caller saw cannot name them. The write side therefore has
to keep those links instead of deleting them as unseen rows.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from eneo.database.tables.ai_models_table import (
    CompletionModels,
    EmbeddingModels,
    TranscriptionModels,
)
from eneo.database.tables.spaces_table import (
    Spaces,
    SpacesCompletionModels,
    SpacesEmbeddingModels,
    SpacesTranscriptionModels,
)
from eneo.spaces.space_repo import SpaceRepository
from eneo.spaces.space_update import SpaceUpdate


@pytest.fixture
def persisted():
    models = (
        Spaces,
        SpacesCompletionModels,
        SpacesEmbeddingModels,
        SpacesTranscriptionModels,
        CompletionModels,
        EmbeddingModels,
        TranscriptionModels,
    )
    names = {model.__table__.name for model in models}
    metadata = sa.MetaData()
    tables = {}
    for model in models:
        columns = []
        for column in model.__table__.columns:
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
        tenant_id, space_id = uuid4(), uuid4()
        connection.execute(
            sa.insert(tables[Spaces]).values(
                id=space_id, name="Original", tenant_id=tenant_id
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
        yield SimpleNamespace(
            connection=connection,
            tables=tables,
            tenant_id=tenant_id,
            space_id=space_id,
            space_repo=space_repo,
        )
    engine.dispose()


def add_deprecated_completion_model(db, *, deprecated: bool) -> SimpleNamespace:
    model_id = uuid4()
    db.connection.execute(
        sa.insert(db.tables[CompletionModels]).values(
            id=model_id,
            name=f"model-{model_id}",
            nickname=f"model-{model_id}",
            open_source=True,
            max_input_tokens=8192,
            max_output_tokens=8192,
            is_deprecated=deprecated,
            family="test-family",
            stability="stable",
            hosting="cloud",
        )
    )
    return SimpleNamespace(id=model_id, deprecated=deprecated)


def add_deprecated_embedding_model(db, *, deprecated: bool) -> SimpleNamespace:
    model_id = uuid4()
    db.connection.execute(
        sa.insert(db.tables[EmbeddingModels]).values(
            id=model_id,
            name=f"model-{model_id}",
            open_source=True,
            is_deprecated=deprecated,
            family="test-family",
            stability="stable",
            hosting="cloud",
        )
    )
    return SimpleNamespace(id=model_id, deprecated=deprecated)


def add_deprecated_transcription_model(db, *, deprecated: bool) -> SimpleNamespace:
    model_id = uuid4()
    db.connection.execute(
        sa.insert(db.tables[TranscriptionModels]).values(
            id=model_id,
            name=f"model-{model_id}",
            model_name=f"model-{model_id}",
            is_deprecated=deprecated,
            family="test-family",
            stability="stable",
            hosting="cloud",
            base_url="https://example.invalid",
        )
    )
    return SimpleNamespace(id=model_id, deprecated=deprecated)


def link(db, assoc_table, target_attr, model_id):
    db.connection.execute(
        sa.insert(db.tables[assoc_table]).values(
            space_id=db.space_id, **{target_attr: model_id}
        )
    )


def stored_ids(db, assoc_table, target_attr):
    return set(
        db.connection.scalars(
            sa.select(getattr(db.tables[assoc_table].c, target_attr))
        )
    )


async def test_list_edit_keeps_the_deprecated_completion_model_link(persisted):
    hidden = add_deprecated_completion_model(persisted, deprecated=True)
    visible = add_deprecated_completion_model(persisted, deprecated=False)
    link(persisted, SpacesCompletionModels, "completion_model_id", hidden.id)
    link(persisted, SpacesCompletionModels, "completion_model_id", visible.id)

    await persisted.space_repo.update_settings(
        persisted.space_id, SpaceUpdate(completion_model_ids=[visible.id])
    )

    assert stored_ids(persisted, SpacesCompletionModels, "completion_model_id") == {
        hidden.id,
        visible.id,
    }


async def test_empty_list_edit_keeps_the_deprecated_completion_model_link(persisted):
    hidden = add_deprecated_completion_model(persisted, deprecated=True)
    link(persisted, SpacesCompletionModels, "completion_model_id", hidden.id)

    await persisted.space_repo.update_settings(
        persisted.space_id, SpaceUpdate(completion_model_ids=[])
    )

    assert stored_ids(persisted, SpacesCompletionModels, "completion_model_id") == {
        hidden.id,
    }


async def test_list_edit_keeps_deprecated_embedding_and_transcription_links(persisted):
    embedding = add_deprecated_embedding_model(persisted, deprecated=True)
    transcription = add_deprecated_transcription_model(persisted, deprecated=True)
    link(persisted, SpacesEmbeddingModels, "embedding_model_id", embedding.id)
    link(persisted, SpacesTranscriptionModels, "transcription_model_id", transcription.id)

    await persisted.space_repo.update_settings(
        persisted.space_id,
        SpaceUpdate(embedding_model_ids=[], transcription_model_ids=[]),
    )

    assert stored_ids(persisted, SpacesEmbeddingModels, "embedding_model_id") == {
        embedding.id,
    }
    assert stored_ids(
        persisted, SpacesTranscriptionModels, "transcription_model_id"
    ) == {transcription.id}


async def test_list_edit_still_replaces_visible_links(persisted):
    visible = add_deprecated_completion_model(persisted, deprecated=False)
    replacement = add_deprecated_completion_model(persisted, deprecated=False)
    link(persisted, SpacesCompletionModels, "completion_model_id", visible.id)

    await persisted.space_repo.update_settings(
        persisted.space_id, SpaceUpdate(completion_model_ids=[replacement.id])
    )

    assert stored_ids(persisted, SpacesCompletionModels, "completion_model_id") == {
        replacement.id,
    }
