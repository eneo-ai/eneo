from contextlib import closing, contextmanager

import psycopg2

from alembic import command


def current_revisions(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        return {row[0] for row in cur.fetchall()}


def reset_public_schema(conn) -> None:
    """Drop all schema data, including conftest seed rows, for migration replay tests."""
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
        cur.execute("CREATE SCHEMA public")
        cur.execute("GRANT ALL ON SCHEMA public TO PUBLIC")


@contextmanager
def at_revision(cfg, revision: str):
    """Hold the shared test database at ``revision``, then put it back at head.

    ``command.upgrade(cfg, revision)`` does nothing when an earlier test left the
    database at head (or anywhere later), so a test that checks the schema at that
    revision passes alone and fails in the suite. Downgrading from head is no
    answer either: some migrations cannot be downgraded (202609041000 asks for a
    backup restore). Replaying from an empty schema reaches ``revision`` from any
    starting point, and head is restored on exit so the next test starts from a
    known schema.
    """
    url = cfg.get_main_option("sqlalchemy.url").replace("+psycopg2", "")
    with closing(psycopg2.connect(url)) as conn:
        conn.autocommit = True
        reset_public_schema(conn)
    command.upgrade(cfg, revision)
    try:
        yield
    finally:
        command.upgrade(cfg, "head")
