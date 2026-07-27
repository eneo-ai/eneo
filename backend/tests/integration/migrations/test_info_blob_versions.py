from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import pytest
from psycopg2.extras import execute_values
from sqlalchemy import create_engine, inspect
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from eneo.database.tables.info_blobs_table import InfoBlobs

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_POSTGRES_13_IMAGE = (
    "pgvector/pgvector:pg13@"
    "sha256:751a89c96f7c32cb8133472f711c274853378fb5f8b55dd9fa0e9d3f1471bfc3"
)
_PARENT_REVISION = "202607262200"
_VERSION_REVISION = "202607271000"


@pytest.fixture(scope="session", autouse=True)
def override_settings_for_session() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def cleanup_database() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def seed_default_models() -> Generator[None, None, None]:
    yield


def _alembic_config(database_url: str) -> Config:
    backend_dir = Path(__file__).resolve().parents[3]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migration_database() -> Generator[tuple[str, Config], None, None]:
    postgres = PostgresContainer(
        image=_POSTGRES_13_IMAGE,
        username="info_blob_versions",
        password="info_blob_versions_password",
        dbname="info_blob_versions",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)
        command.upgrade(config, _PARENT_REVISION)
        yield database_url.replace("+psycopg2", ""), config


def _seed_legacy_info_blob(connection) -> UUID:
    tenant_id = uuid4()
    user_id = uuid4()
    embedding_model_id = uuid4()
    info_blob_id = uuid4()
    with connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (%s, %s, 1000000, 'active')
            """,
            (str(tenant_id), f"info-blob-versions-{tenant_id.hex[:8]}"),
        )
        cursor.execute(
            """
            INSERT INTO users (id, tenant_id, email, used_tokens, state)
            VALUES (%s, %s, %s, 0, 'active')
            """,
            (str(user_id), str(tenant_id), f"{user_id.hex}@example.test"),
        )
        cursor.execute(
            """
            INSERT INTO embedding_models (
                id, name, open_source, family, stability, hosting
            )
            VALUES (%s, 'migration model', true, 'openai', 'stable', 'self-hosted')
            """,
            (str(embedding_model_id),),
        )
        cursor.execute(
            """
            INSERT INTO info_blobs (
                id, text, title, size, user_id, tenant_id, embedding_model_id
            )
            VALUES (%s, 'legacy text', 'legacy.txt', 11, %s, %s, %s)
            """,
            (
                str(info_blob_id),
                str(user_id),
                str(tenant_id),
                str(embedding_model_id),
            ),
        )
    return info_blob_id


def _seed_multi_batch_legacy_rows(
    connection,
    *,
    legacy_id: UUID,
) -> list[UUID]:
    with connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT user_id, tenant_id, embedding_model_id
            FROM info_blobs
            WHERE id = %s
            """,
            (str(legacy_id),),
        )
        user_id, tenant_id, embedding_model_id = cursor.fetchone()
        ids = [uuid4() for _ in range(1_001)]
        execute_values(
            cursor,
            """
            INSERT INTO info_blobs (
                id, text, title, size, user_id, tenant_id, embedding_model_id
            ) VALUES %s
            """,
            [
                (
                    str(info_blob_id),
                    "legacy batch text",
                    f"legacy-batch-{index}.txt",
                    17,
                    user_id,
                    tenant_id,
                    embedding_model_id,
                )
                for index, info_blob_id in enumerate(ids)
            ],
        )
    return ids


def _seed_legacy_duplicate_identities(
    connection,
    *,
    legacy_id: UUID,
) -> tuple[dict[str, tuple[UUID, UUID]], tuple[UUID, UUID]]:
    with connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT user_id, tenant_id, embedding_model_id
            FROM info_blobs
            WHERE id = %s
            """,
            (str(legacy_id),),
        )
        user_id, tenant_id, embedding_model_id = cursor.fetchone()

        group_id = uuid4()
        website_id = uuid4()
        space_id = uuid4()
        integration_id = uuid4()
        tenant_integration_id = uuid4()
        user_integration_id = uuid4()
        integration_knowledge_id = uuid4()
        cursor.execute(
            """
            INSERT INTO groups (
                id, name, size, user_id, tenant_id, embedding_model_id
            ) VALUES (%s, 'legacy duplicates', 0, %s, %s, %s)
            """,
            (str(group_id), user_id, tenant_id, embedding_model_id),
        )
        cursor.execute(
            """
            INSERT INTO websites (
                id, name, url, download_files, crawl_type, update_interval, size,
                tenant_id, user_id, embedding_model_id
            ) VALUES (
                %s, 'legacy website', 'https://example.test', false, 'CRAWL',
                'never', 0, %s, %s, %s
            )
            """,
            (str(website_id), tenant_id, user_id, embedding_model_id),
        )
        cursor.execute(
            """
            INSERT INTO spaces (id, name, tenant_id, user_id)
            VALUES (%s, 'legacy integration space', %s, %s)
            """,
            (str(space_id), tenant_id, user_id),
        )
        cursor.execute(
            """
            INSERT INTO integrations (id, name, description)
            VALUES (%s, %s, 'migration test integration')
            """,
            (str(integration_id), f"migration-{integration_id}"),
        )
        cursor.execute(
            """
            INSERT INTO tenant_integrations (id, tenant_id, integration_id)
            VALUES (%s, %s, %s)
            """,
            (str(tenant_integration_id), tenant_id, str(integration_id)),
        )
        cursor.execute(
            """
            INSERT INTO user_integrations (
                id, user_id, tenant_id, tenant_integration_id, authenticated
            ) VALUES (%s, %s, %s, %s, true)
            """,
            (
                str(user_integration_id),
                user_id,
                tenant_id,
                str(tenant_integration_id),
            ),
        )
        cursor.execute(
            """
            INSERT INTO integration_knowledge (
                id, name, url, space_id, embedding_model_id, tenant_id,
                user_integration_id, size
            ) VALUES (%s, 'legacy integration knowledge', NULL, %s, %s, %s, %s, 0)
            """,
            (
                str(integration_knowledge_id),
                str(space_id),
                embedding_model_id,
                tenant_id,
                str(user_integration_id),
            ),
        )

        identities: dict[str, tuple[UUID, UUID]] = {}
        rows: list[
            tuple[
                UUID, str, str | None, UUID | None, UUID | None, UUID | None, str | None
            ]
        ] = []
        for name, title, owner in (
            ("group", "group-title", (group_id, None, None)),
            ("website", "website-title", (None, website_id, None)),
            (
                "integration-title",
                "integration-title",
                (None, None, integration_knowledge_id),
            ),
        ):
            older_id, newer_id = uuid4(), uuid4()
            identities[name] = (older_id, newer_id)
            rows.extend(
                [
                    (older_id, f"older {name}", title, *owner, None),
                    (newer_id, f"newer {name}", title, *owner, None),
                ]
            )

        older_item_id, newer_item_id = uuid4(), uuid4()
        identities["integration-item"] = (older_item_id, newer_item_id)
        rows.extend(
            [
                (
                    older_item_id,
                    "older integration item",
                    "old provider title",
                    None,
                    None,
                    integration_knowledge_id,
                    "provider-item-1",
                ),
                (
                    newer_item_id,
                    "newer integration item",
                    "new provider title",
                    None,
                    None,
                    integration_knowledge_id,
                    "provider-item-1",
                ),
            ]
        )

        untitled_ids = (uuid4(), uuid4())
        rows.extend(
            [
                (untitled_ids[0], "null title", None, group_id, None, None, None),
                (untitled_ids[1], "blank title", "   ", group_id, None, None, None),
            ]
        )
        cursor.executemany(
            """
            INSERT INTO info_blobs (
                id, text, title, size, user_id, tenant_id, embedding_model_id,
                group_id, website_id, integration_knowledge_id,
                sharepoint_item_id, created_at, updated_at
            ) VALUES (
                %s, %s, %s, 10, %s, %s, %s, %s, %s, %s, %s,
                NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day'
            )
            """,
            [
                (
                    str(row[0]),
                    row[1],
                    row[2],
                    user_id,
                    tenant_id,
                    embedding_model_id,
                    str(row[3]) if row[3] is not None else None,
                    str(row[4]) if row[4] is not None else None,
                    str(row[5]) if row[5] is not None else None,
                    row[6],
                )
                for row in rows[::2]
            ],
        )
        cursor.executemany(
            """
            INSERT INTO info_blobs (
                id, text, title, size, user_id, tenant_id, embedding_model_id,
                group_id, website_id, integration_knowledge_id,
                sharepoint_item_id, created_at, updated_at
            ) VALUES (
                %s, %s, %s, 10, %s, %s, %s, %s, %s, %s, %s,
                NOW(), NOW()
            )
            """,
            [
                (
                    str(row[0]),
                    row[1],
                    row[2],
                    user_id,
                    tenant_id,
                    embedding_model_id,
                    str(row[3]) if row[3] is not None else None,
                    str(row[4]) if row[4] is not None else None,
                    str(row[5]) if row[5] is not None else None,
                    row[6],
                )
                for row in rows[1::2]
            ],
        )
    return identities, untitled_ids


def _assert_orm_parity(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        database_columns = {
            str(column["name"])
            for column in inspect(engine).get_columns(InfoBlobs.__tablename__)
        }
        orm_columns = {column.name for column in InfoBlobs.__table__.columns}
        assert database_columns == orm_columns
    finally:
        engine.dispose()


def test_info_blob_version_schema_round_trip_and_history_fence(
    migration_database,
) -> None:
    database_url, config = migration_database
    connection = psycopg2.connect(database_url)
    try:
        legacy_id = _seed_legacy_info_blob(connection)
        multi_batch_ids = _seed_multi_batch_legacy_rows(
            connection,
            legacy_id=legacy_id,
        )
        duplicate_identities, untitled_ids = _seed_legacy_duplicate_identities(
            connection,
            legacy_id=legacy_id,
        )

        command.upgrade(config, _VERSION_REVISION)

        with connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT source_id, version_state
                FROM info_blobs
                WHERE id = %s
                """,
                (str(legacy_id),),
            )
            assert cursor.fetchone() == (str(legacy_id), "active")

            cursor.execute(
                """
                SELECT count(*)
                FROM info_blobs
                WHERE id = ANY(%s::uuid[])
                  AND source_id = id
                  AND version_state = 'active'
                """,
                ([str(value) for value in multi_batch_ids],),
            )
            assert cursor.fetchone() == (len(multi_batch_ids),)

            for older_id, newer_id in duplicate_identities.values():
                cursor.execute(
                    """
                    SELECT id, source_id, version_state
                    FROM info_blobs
                    WHERE id IN (%s, %s)
                    ORDER BY created_at, id
                    """,
                    (str(older_id), str(newer_id)),
                )
                assert cursor.fetchall() == [
                    (str(older_id), str(newer_id), "superseded"),
                    (str(newer_id), str(newer_id), "active"),
                ]

            cursor.execute(
                """
                SELECT id, source_id, version_state
                FROM info_blobs
                WHERE id IN (%s, %s)
                ORDER BY id
                """,
                tuple(str(value) for value in untitled_ids),
            )
            assert cursor.fetchall() == sorted(
                [
                    (str(untitled_ids[0]), str(untitled_ids[0]), "active"),
                    (str(untitled_ids[1]), str(untitled_ids[1]), "active"),
                ]
            )

            cursor.execute(
                """
                SELECT column_default
                FROM information_schema.columns
                WHERE table_name = 'info_blobs'
                  AND column_name IN ('source_id', 'version_state')
                ORDER BY column_name
                """
            )
            assert cursor.fetchall() == [(None,), (None,)]

            cursor.execute(
                """
                SELECT user_id, tenant_id, embedding_model_id
                FROM info_blobs
                WHERE id = %s
                """,
                (str(legacy_id),),
            )
            user_id, tenant_id, embedding_model_id = cursor.fetchone()

        connection.rollback()
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.NotNullViolation):
                cursor.execute(
                    """
                    INSERT INTO info_blobs (
                        text, title, size, user_id, tenant_id, embedding_model_id
                    )
                    VALUES ('missing version', 'missing.txt', 1, %s, %s, %s)
                    """,
                    (user_id, tenant_id, embedding_model_id),
                )

        connection.rollback()
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.CheckViolation):
                cursor.execute(
                    """
                    INSERT INTO info_blobs (
                        text, title, size, user_id, tenant_id, embedding_model_id,
                        source_id, version_state
                    )
                    VALUES ('invalid', 'invalid.txt', 1, %s, %s, %s, %s, 'building')
                    """,
                    (user_id, tenant_id, embedding_model_id, str(uuid4())),
                )

        connection.rollback()
        superseded_id = uuid4()
        replacement_id = uuid4()
        with connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO info_blobs (
                    id, text, title, size, user_id, tenant_id, embedding_model_id,
                    source_id, version_state
                )
                VALUES (%s, 'history', 'legacy.txt', 7, %s, %s, %s, %s, 'superseded')
                """,
                (
                    str(superseded_id),
                    user_id,
                    tenant_id,
                    embedding_model_id,
                    str(legacy_id),
                ),
            )
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cursor.execute(
                    """
                    INSERT INTO info_blobs (
                        id, text, title, size, user_id, tenant_id,
                        embedding_model_id, source_id, version_state
                    )
                    VALUES (%s, 'second active', 'legacy.txt', 13, %s, %s, %s, %s, 'active')
                    """,
                    (
                        str(replacement_id),
                        user_id,
                        tenant_id,
                        embedding_model_id,
                        str(legacy_id),
                    ),
                )

        connection.rollback()
        normalized_ids = [
            value for identity in duplicate_identities.values() for value in identity
        ]
        normalized_ids.extend(untitled_ids)
        normalized_ids.extend(multi_batch_ids)
        with connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM info_blobs WHERE id = ANY(%s::uuid[])",
                ([str(value) for value in normalized_ids],),
            )

        _assert_orm_parity(database_url)

        command.downgrade(config, "-1")
        command.upgrade(config, _VERSION_REVISION)

        with connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE info_blobs
                SET version_state = 'superseded'
                WHERE id = %s
                """,
                (str(legacy_id),),
            )
            cursor.execute(
                """
                INSERT INTO info_blobs (
                    text, title, size, user_id, tenant_id, embedding_model_id,
                    source_id, version_state
                )
                VALUES ('replacement', 'legacy.txt', 11, %s, %s, %s, %s, 'active')
                """,
                (user_id, tenant_id, embedding_model_id, str(legacy_id)),
            )

        with pytest.raises(Exception, match="cannot remove InfoBlob version history"):
            command.downgrade(config, "-1")

        with connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM information_schema.columns
                WHERE table_name = 'info_blobs'
                  AND column_name IN ('source_id', 'version_state')
                """
            )
            assert cursor.fetchone() == (2,)
    finally:
        connection.close()
