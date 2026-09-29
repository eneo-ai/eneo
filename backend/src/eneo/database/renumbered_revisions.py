"""Refuse to migrate a database stamped at a revision id that changed meaning.

The tidy AI Builder branch once used 202609151000, 202609161000 and
202609181000 for its own migrations. Develop shipped different migrations
under the same ids, so the merged history renumbered the branch's three to
202609151040, 202609161010 and 202609181010. The crawler merge later took
202609031000 and 202609211200 for its head-merge migrations, so the branch's
flow_step_transcript_words and inline_external_storage migrations became
202609031001 and 202609211201. A database stamped at one of the old ids by the
branch would now be read as develop's migration of that id: Alembic would rerun
the branch's renamed migrations and skip develop's.

Such a database is recognised by the schema its branch migration left behind,
which develop's migration of the same id never creates. It is refused with the
exact repair instead of migrated.
"""

from dataclasses import dataclass

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection


@dataclass(frozen=True)
class RenumberedRevision:
    old: str
    new: str
    table: str
    column: str | None = None


RENUMBERED_BRANCH_REVISIONS: tuple[RenumberedRevision, ...] = (
    RenumberedRevision(
        old="202609151000",
        new="202609151040",
        table="flow_transcript_correction_revisions",
    ),
    RenumberedRevision(
        old="202609161000",
        new="202609161010",
        table="completion_models",
        column="context_window_tokens",
    ),
    RenumberedRevision(
        old="202609181000",
        new="202609181010",
        table="flow_runs",
        column="run_label",
    ),
    RenumberedRevision(
        old="202609031000",
        new="202609031001",
        table="flow_step_transcript_words",
    ),
    RenumberedRevision(
        old="202609211200",
        new="202609211201",
        table="object_content_reconciliation_state",
        column="inline_conversion_ready_at",
    ),
)


class RenumberedRevisionStampError(RuntimeError):
    pass


def _has_branch_schema(connection: Connection, revision: RenumberedRevision) -> bool:
    inspector = inspect(connection)
    if not inspector.has_table(revision.table):
        return False
    if revision.column is None:
        return True
    return any(
        column["name"] == revision.column
        for column in inspector.get_columns(revision.table)
    )


def check_renumbered_revision_stamp(connection: Connection) -> None:
    """Raise when the database is stamped at a branch id that develop reused.

    Only a single stamp can be the old branch's: while the merged history
    applies develop's chain beside the branch's, the version table holds one
    row per branch, and develop's own databases never have the branch schema.
    """
    if not inspect(connection).has_table("alembic_version"):
        return
    stamps = list(
        connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
    )
    if len(stamps) != 1:
        return
    for revision in RENUMBERED_BRANCH_REVISIONS:
        if stamps[0] == revision.old and _has_branch_schema(connection, revision):
            raise RenumberedRevisionStampError(
                f"This database is stamped at {revision.old}, the tidy AI Builder "
                f"branch's old id for the migration now numbered {revision.new}; "
                f"develop uses {revision.old} for a different migration. Migrating "
                "it as is would skip develop's migrations. Repair the stamp, then "
                f"migrate again: alembic stamp --purge {revision.new}"
            )
