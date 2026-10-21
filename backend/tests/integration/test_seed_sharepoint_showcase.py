"""The showcase seed's --remove never disables a SharePoint setup made real."""

from collections.abc import Iterator

import psycopg2
import psycopg2.extensions
import pytest

from scripts import seed_sharepoint_showcase as seed


@pytest.fixture
def cursor(test_settings) -> Iterator[psycopg2.extensions.cursor]:
    """A cursor whose work is rolled back: the seed's rows have fixed ids."""
    connection = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    try:
        cur = connection.cursor()
        yield cur
        cur.close()
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
async def seeded_connection(
    db_container, tenant_factory, user_factory, test_settings, cursor
):
    async with db_container() as container:
        session = container.session()
        tenant_id = str((await tenant_factory(session)).id)
        user_id = str((await user_factory(session, tenant_id=tenant_id)).id)
    if (
        seed.one(
            cursor, "SELECT 1 FROM integrations WHERE integration_type = 'sharepoint'"
        )
        is None
    ):
        cursor.execute(
            """INSERT INTO integrations (name, description, integration_type)
               VALUES ('SharePoint', 'SharePoint', 'sharepoint')"""
        )
    seed.resolve_user_integration(cursor, test_settings, tenant_id, user_id)
    return cursor


def _present(cursor) -> set[str]:
    rows = {
        "connection": ("user_integrations", seed.sid("user-integration")),
        "tenant app": ("tenant_sharepoint_apps", seed.sid("tenant-app")),
        "tenant integration": ("tenant_integrations", seed.sid("tenant-integration")),
    }
    return {
        name
        for name, (table, row_id) in rows.items()
        if seed.one(cursor, f"SELECT 1 FROM {table} WHERE id = %s", str(row_id))
    }


async def test_remove_drops_the_fake_connection_it_created(seeded_connection):
    assert _present(seeded_connection) == {
        "connection",
        "tenant app",
        "tenant integration",
    }

    assert seed.remove_connection(seeded_connection) == []

    assert _present(seeded_connection) == set()


async def test_remove_keeps_an_app_given_real_credentials_with_what_it_needs(
    seeded_connection,
):
    seeded_connection.execute(
        "UPDATE tenant_sharepoint_apps SET client_id = %s WHERE id = %s",
        ("11111111-2222-4333-8444-555555555555", str(seed.sid("tenant-app"))),
    )

    kept = seed.remove_connection(seeded_connection)

    assert len(kept) == 1 and "real credentials" in kept[0]
    assert _present(seeded_connection) == {
        "connection",
        "tenant app",
        "tenant integration",
    }
