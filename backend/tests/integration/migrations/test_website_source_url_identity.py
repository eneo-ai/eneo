"""Source identity backfill keeps public metadata and referenced history intact."""

from collections.abc import Generator
from uuid import uuid4

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from tests.integration.migrations.test_crawl_lifecycle_round_trip import (
    _alembic_config,
    _insert_crawl_owner,
    _sync_url,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]
_PARENT = "202609031000"
_REVISION = "202609071000"


@pytest.fixture(scope="session", autouse=True)
def override_settings_for_session() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def cleanup_database() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def seed_default_models() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def encryption_service() -> Generator[None, None, None]:
    yield


@pytest.fixture(scope="module")
def migration_database() -> Generator[tuple[str, Config], None, None]:
    with PostgresContainer("pgvector/pgvector:pg16") as postgres:
        url = postgres.get_connection_url()
        yield _sync_url(url), _alembic_config(url)


def test_source_url_backfill_preserves_metadata_citations_and_ambiguities(
    migration_database,
) -> None:
    url, config = migration_database
    command.upgrade(config, _PARENT)
    ids = [uuid4() for _ in range(5)]
    source_id = uuid4()
    urls = [
        "https://EXAMPLE.com:443/policy.pdf#heading",
        "https://example.com/policy.pdf",
        "https://example.com/policy.docx",
        None,
        "policy.pdf",
    ]
    question_id = uuid4()
    with psycopg2.connect(url) as connection, connection.cursor() as cursor:
        tenant_id, user_id, website_id = _insert_crawl_owner(
            cursor, label="URL migration"
        )
        for index, (blob_id, source_url) in enumerate(zip(ids, urls)):
            cursor.execute(
                """
                INSERT INTO info_blobs (
                    id, source_id, version_state, website_id, tenant_id, user_id,
                    title, url, text, size
                ) VALUES (%s, %s, %s, %s, %s, %s, 'policy', %s, 'knowledge', 9)
                """,
                (
                    str(blob_id),
                    str(source_id if index in (0, 2) else uuid4()),
                    "superseded" if index == 2 else "active",
                    str(website_id),
                    str(tenant_id),
                    str(user_id),
                    source_url,
                ),
            )
        cursor.execute(
            """INSERT INTO questions (
                id, tenant_id, question, answer, num_tokens_question, num_tokens_answer
            ) VALUES (%s, %s, 'Question', 'Cited answer', 1, 2)""",
            (str(question_id), str(tenant_id)),
        )
        cursor.execute(
            "INSERT INTO info_blob_references (question_id, info_blob_id) VALUES (%s, %s)",
            (str(question_id), str(ids[2])),
        )
        cursor.execute(
            "SELECT id, source_id, version_state, title, url, text FROM info_blobs ORDER BY id"
        )
        before = cursor.fetchall()

    command.upgrade(config, _REVISION)
    with psycopg2.connect(url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, source_id, version_state, title, url, text FROM info_blobs ORDER BY id"
        )
        assert cursor.fetchall() == before
        cursor.execute("SELECT id, website_source_url FROM info_blobs")
        keys = dict(cursor.fetchall())
        assert [keys[str(blob_id)] for blob_id in ids] == [
            "https://example.com/policy.pdf",
            "https://example.com/policy.pdf",
            "https://example.com/policy.docx",
            None,
            None,
        ]
        cursor.execute(
            "SELECT info_blob_id FROM info_blob_references WHERE question_id = %s",
            (str(question_id),),
        )
        assert cursor.fetchone()[0] == str(ids[2])
        # URLs above the B-tree text-entry limit remain valid source identities.
        long_url = "https://example.com/" + "a" * 10_000
        cursor.execute(
            "UPDATE info_blobs SET website_source_url = %s WHERE id = %s",
            (long_url, str(ids[3])),
        )
        cursor.execute(
            "SELECT indisvalid FROM pg_index WHERE indexrelid = 'ix_info_blobs_active_website_source_url'::regclass"
        )
        assert cursor.fetchone()[0] is True

    command.downgrade(config, _PARENT)
    with psycopg2.connect(url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, source_id, version_state, title, url, text FROM info_blobs ORDER BY id"
        )
        assert cursor.fetchall() == before
        cursor.execute(
            "SELECT info_blob_id FROM info_blob_references WHERE question_id = %s",
            (str(question_id),),
        )
        assert cursor.fetchone()[0] == str(ids[2])
