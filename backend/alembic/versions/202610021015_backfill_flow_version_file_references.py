"""backfill file references for existing flow versions

Revision ID: 202610021015
Revises: 202610021030
Create Date: 2026-10-02 10:15:00.000000

Snapshot writers now record the files a version names in the same transaction
as the snapshot. Versions published earlier have no references, so retention
could release a file such a version still needs. This reads every version in
keyset batches and records its references, taking the same file-row key-share
lock the writer takes. A file is protected while a flow version that names it
exists; unpublishing and run-history purge do not release it, and no automatic
version cleanup exists yet. It is self-contained on purpose: the
reader below is frozen at the three places a schema-version-1 definition names
a file (a step's output_config template_asset_id and template_file_id, and the
attachments of its assistant_snapshot), so later application changes cannot
alter this migration. Inserts are idempotent. A named file or template asset
that no longer exists is skipped and counted, never a failure.

Deletion protection for versions published before this revision is complete
only after the backfill has finished. Each batch of 200 versions runs in its
own committed transaction (a fresh connection inside an autocommit block), so
locks are not held for the whole run and an interrupted run restarts safely.

Operational notes:
- Downgrade is a no-op for data: the rows stay, and application code from
  before this revision does not know them, so deleting a file such a row names
  fails with a database error (500) instead of a 409 until the upgrade is redone.
- Rolling deploy: a version published by a pod that still runs the old code
  after the migration's cursor has passed gets no references. Re-running the
  backfill after the last old pod is gone is idempotent and fills the gap.
- Offline mode (`alembic upgrade --sql`) is refused: the upgrade raises before
  this revision is stamped, because rendering it as a no-op would stamp the revision
  as done and a later online upgrade would then skip the backfill. Run
  `alembic upgrade 202610021015` against the database, then continue offline
  if needed. Deletion protection for versions published before the upgrade is
  complete only after this revision has run online.
"""

import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alembic import op

revision: str = "202610021015"
down_revision: str | None = "202610021030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BATCH_SIZE = 200
_SCHEMA_VERSION = 1
_logger = logging.getLogger("alembic.runtime.migration")

_uuid = PG_UUID(as_uuid=True)
_versions = sa.table(
    "flow_versions",
    sa.column("flow_id", _uuid),
    sa.column("version", sa.Integer),
    sa.column("tenant_id", _uuid),
    sa.column("definition_json", JSONB),
)
_files = sa.table("files", sa.column("id", _uuid), sa.column("tenant_id", _uuid))
_assets = sa.table(
    "flow_template_assets",
    sa.column("id", _uuid),
    sa.column("flow_id", _uuid),
    sa.column("tenant_id", _uuid),
    sa.column("file_id", _uuid),
)
_references = sa.table(
    "flow_version_file_references",
    sa.column("flow_id", _uuid),
    sa.column("version", sa.Integer),
    sa.column("tenant_id", _uuid),
    sa.column("file_id", _uuid),
)


@dataclass(frozen=True, slots=True)
class BackfillOutcome:
    versions_scanned: int
    skipped_missing: int


def _uuid_or_none(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _named_ids(definition: object) -> tuple[set[UUID], set[UUID]]:
    """The (file ids, template asset ids) a definition names."""
    file_ids: set[UUID] = set()
    asset_ids: set[UUID] = set()
    if not isinstance(definition, dict) or definition.get("schema_version") != (
        _SCHEMA_VERSION
    ):
        return file_ids, asset_ids
    steps = definition.get("steps")
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, dict):
            continue
        output_config = step.get("output_config")
        if isinstance(output_config, dict):
            if (
                asset := _uuid_or_none(output_config.get("template_asset_id"))
            ) is not None:
                asset_ids.add(asset)
            if (
                file := _uuid_or_none(output_config.get("template_file_id"))
            ) is not None:
                file_ids.add(file)
        snapshot = step.get("assistant_snapshot")
        attachments = (
            snapshot.get("attachments") if isinstance(snapshot, dict) else None
        )
        for attachment in attachments if isinstance(attachments, list) else []:
            if isinstance(attachment, dict) and (
                file := _uuid_or_none(attachment.get("file_id"))
            ):
                file_ids.add(file)
    return file_ids, asset_ids


def _backfill_batch(
    connection: sa.Connection, cursor: tuple[UUID, int] | None, batch_size: int
) -> tuple[tuple[UUID, int] | None, int, int]:
    """One keyset batch: (next cursor or None when done, versions, skipped)."""
    query = (
        sa.select(
            _versions.c.flow_id,
            _versions.c.version,
            _versions.c.tenant_id,
            _versions.c.definition_json,
        )
        .order_by(_versions.c.flow_id, _versions.c.version)
        .limit(batch_size)
    )
    if cursor is not None:
        query = query.where(
            sa.tuple_(_versions.c.flow_id, _versions.c.version) > cursor
        )
    batch = connection.execute(query).all()
    skipped = 0
    for flow_id, version, tenant_id, definition in batch:
        file_ids, asset_ids = _named_ids(definition)
        named = len(file_ids) + len(asset_ids)
        if not named:
            continue
        resolved = connection.execute(
            sa.union_all(
                sa.select(_files.c.id, _files.c.id).where(
                    _files.c.tenant_id == tenant_id, _files.c.id.in_(file_ids)
                ),
                sa.select(_assets.c.id, _assets.c.file_id).where(
                    _assets.c.flow_id == flow_id,
                    _assets.c.tenant_id == tenant_id,
                    _assets.c.id.in_(asset_ids),
                ),
            )
        ).all()
        locked = set(
            connection.execute(
                sa.select(_files.c.id)
                .where(
                    _files.c.tenant_id == tenant_id,
                    _files.c.id.in_({file_id for _, file_id in resolved}),
                )
                .with_for_update(read=True, key_share=True)
            ).scalars()
        )
        resolved = [row for row in resolved if row[1] in locked]
        skipped += named - len({named_id for named_id, _ in resolved})
        if resolved:
            connection.execute(
                pg_insert(_references)
                .values(
                    [
                        {
                            "flow_id": flow_id,
                            "version": version,
                            "tenant_id": tenant_id,
                            "file_id": file_id,
                        }
                        for file_id in sorted({fid for _, fid in resolved})
                    ]
                )
                .on_conflict_do_nothing(
                    index_elements=["flow_id", "version", "file_id"]
                )
            )
    next_cursor = (batch[-1].flow_id, batch[-1].version) if batch else None
    return next_cursor, len(batch), skipped


def backfill_flow_version_file_references(
    begin: Callable[[], AbstractContextManager[sa.Connection]],
    *,
    batch_size: int = _BATCH_SIZE,
) -> BackfillOutcome:
    """Backfill in batches; ``begin()`` opens one transaction per batch, so a
    batch commits (and releases its file locks) before the next one starts and
    an interrupted run keeps the batches it finished. Rerunning is idempotent."""
    scanned = skipped = 0
    cursor: tuple[UUID, int] | None = None
    while True:
        with begin() as connection:
            cursor, batch_scanned, batch_skipped = _backfill_batch(
                connection, cursor, batch_size
            )
        scanned += batch_scanned
        skipped += batch_skipped
        if cursor is None:
            return BackfillOutcome(versions_scanned=scanned, skipped_missing=skipped)


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Revision 202610021015 backfills data and must run online: run "
            "`alembic upgrade 202610021015` against the database, then "
            "continue offline if needed."
        )
    bind = op.get_bind()
    # Commit what the migration run holds, then give every batch its own
    # connection and transaction so none holds locks for the whole backfill.
    with op.get_context().autocommit_block():
        outcome = backfill_flow_version_file_references(bind.engine.begin)
    _logger.info(
        "flow version file references: %d versions scanned, %d named ids skipped",
        outcome.versions_scanned,
        outcome.skipped_missing,
    )


def downgrade() -> None:
    # Intentionally a no-op for data: the references are valid retention state,
    # and rows written by the snapshot writer cannot be told apart from backfilled ones.
    pass
