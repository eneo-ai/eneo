"""Index website publications by normalized source URL without rewriting metadata.

Revision ID: 202609071000
Revises: 202609031000

Stop website publishers before upgrading and restarting them together. Historical
blob/source IDs, titles, public URLs and citations remain intact. Missing URLs and
ambiguous active identities require operator review, never guessed basenames.
"""

from urllib.parse import urlsplit, urlunsplit

import sqlalchemy as sa

from alembic import op

revision = "202609071000"
down_revision = "202609031000"
branch_labels = None
depends_on = None

_INDEX = "ix_info_blobs_active_website_source_url"


def _normalize_url(url: str) -> str | None:
    # Frozen equivalent of websites.domain.source_url.normalize_url. Migrations
    # must not depend on future changes to application normalization.
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname
    if scheme not in {"http", "https"} or not hostname:
        return None
    host = hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if port and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    return urlunsplit((scheme, host, parsed.path or "/", parsed.query, ""))


def _backfill() -> None:
    connection = op.get_bind()
    last_id = None
    while True:
        rows = connection.execute(
            sa.text("""
                SELECT id, url FROM info_blobs
                WHERE website_id IS NOT NULL AND url IS NOT NULL
                  AND website_source_url IS NULL
                  AND (:last_id IS NULL OR id > CAST(:last_id AS UUID))
                ORDER BY id LIMIT 1000
            """),
            {"last_id": last_id},
        ).all()
        if not rows:
            break
        updates = [
            {"id": row.id, "url": normalized}
            for row in rows
            if (normalized := _normalize_url(row.url)) is not None
        ]
        if updates:
            connection.execute(
                sa.text(
                    "UPDATE info_blobs SET website_source_url = :url WHERE id = :id"
                ),
                updates,
            )
        last_id = rows[-1].id


def upgrade() -> None:
    op.execute(
        "ALTER TABLE info_blobs ADD COLUMN IF NOT EXISTS website_source_url TEXT"
    )
    _backfill()
    # Partial index creation can be retried after a failed concurrent build.
    with op.get_context().autocommit_block():
        invalid = (
            op.get_bind()
            .execute(
                sa.text("""
                SELECT NOT indisvalid FROM pg_index
                WHERE indexrelid = to_regclass(:name)
            """),
                {"name": _INDEX},
            )
            .scalar()
        )
        if invalid:
            op.drop_index(_INDEX, table_name="info_blobs", postgresql_concurrently=True)
        op.create_index(
            _INDEX,
            "info_blobs",
            ["website_id", sa.text("md5(website_source_url)")],
            postgresql_where=sa.text(
                "version_state = 'active' AND website_source_url IS NOT NULL"
            ),
            postgresql_concurrently=True,
            if_not_exists=True,
        )
    unresolved, ambiguous, mixed_families = (
        op.get_bind()
        .execute(
            sa.text("""
            SELECT
                (SELECT count(*) FROM info_blobs WHERE website_id IS NOT NULL
                    AND website_source_url IS NULL),
                (SELECT count(*) FROM (
                    SELECT website_id, website_source_url FROM info_blobs
                    WHERE website_id IS NOT NULL AND website_source_url IS NOT NULL
                        AND version_state = 'active'
                    GROUP BY website_id, website_source_url HAVING count(*) > 1
                ) AS duplicates),
                (SELECT count(*) FROM (
                    SELECT source_id FROM info_blobs WHERE website_id IS NOT NULL
                    GROUP BY source_id HAVING count(DISTINCT website_source_url) > 1
                ) AS mixed)
        """)
        )
        .one()
    )
    print(
        f"Website source URL inventory: unresolved_rows={unresolved}, "
        f"ambiguous_active_urls={ambiguous}, mixed_historical_families={mixed_families}. "
        "No legacy rows or citations were removed."
    )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            _INDEX,
            table_name="info_blobs",
            postgresql_concurrently=True,
            if_exists=True,
        )
    op.drop_column("info_blobs", "website_source_url")
