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
