"""Read-only planning facts for the temporary File/Icon upgrade."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from alembic.script import ScriptDirectory
from alembic.script.revision import ResolutionError
from alembic.util.exc import CommandError
from eneo.object_content.configuration import ObjectContentCoreSettings

_MIB = 1024 * 1024
_FOUNDATION = "202607151200"
_EXPAND = "202607231700"
_POLICY = "202607251700"
_CAPACITY = "202608281130"


@dataclass(frozen=True, slots=True)
class PreflightSizeBands:
    """Counts of remaining items; all bounds refer to logical bytes."""

    empty: int
    up_to_1_mib: int
    over_1_up_to_16_mib: int
    over_16_up_to_200_mib: int
    over_200_mib: int


@dataclass(frozen=True, slots=True)
class PreflightVariant:
    owner_kind: str
    variant: str
    source_count: int
    source_bytes: int
    available_reference_count: int
    available_reference_bytes: int
    remaining_count: int
    remaining_bytes: int
    maximum_remaining_item_bytes: int
    oversized_count: int
    size_bands: PreflightSizeBands


@dataclass(slots=True)
class PreflightCapacity:
    remaining_logical_bytes: int | None = None
    campaign_admitted_logical_bytes: int | None = None
    estimated_extra_database_bytes: int | None = None
    generated_wal_bytes: int | None = None
    retained_wal_bytes: int | None = None
    host_free_bytes: int | None = None
    detail: str = (
        "Remaining logical payload is an estimate before admission. Existing legacy "
        "bytes stay in PostgreSQL. Database allocation, generated WAL, retained WAL "
        "and host free space require separate measurements; null means unknown. "
        "This command neither approves capacity nor reserves disk. Recheck status "
        "after admission for the worker's capacity decision."
    )


@dataclass(frozen=True, slots=True)
class PreflightIssue:
    code: str
    detail: str


@dataclass(slots=True)
class FileIconPreflightReport:
    format_version: int = 1
    outcome: Literal["ready", "blocked", "incomplete"] = "incomplete"
    schema_state: Literal["pre_expand", "expanded", "unsupported"] = "unsupported"
    alembic_revision: str | None = None
    server_encoding: str | None = None
    inline_maximum_bytes: int | None = None
    selected_new_write_target: str | None = None
    campaign_state: str | None = None
    variants: list[PreflightVariant] = field(default_factory=list[PreflightVariant])
    capacity: PreflightCapacity = field(default_factory=PreflightCapacity)
    blockers: list[PreflightIssue] = field(default_factory=list[PreflightIssue])


async def _read_schema(
    connection: AsyncConnection,
    report: FileIconPreflightReport,
    migration_directory: Path,
) -> set[str] | None:
    report.server_encoding = await connection.scalar(sa.text("SHOW server_encoding"))
    if report.server_encoding != "UTF8":
        report.blockers.append(
            PreflightIssue(
                "unsupported_encoding",
                "The legacy inventory requires UTF8 server encoding.",
            )
        )

    rows = await connection.execute(
        sa.text(
            """
            SELECT c.relname, a.attname,
                   CASE WHEN t.typname IN ('varchar', 'bpchar') THEN 'text'
                        ELSE t.typname END AS type_name
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
            JOIN pg_catalog.pg_type t ON t.oid = a.atttypid
            WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p')
              AND a.attnum > 0 AND NOT a.attisdropped
              AND c.relname IN (
                  'alembic_version', 'files', 'icons', 'object_contents',
                  'file_content_references', 'icon_content_references',
                  'file_icon_backfill_items', 'file_icon_backfill_campaign',
                  'object_content_deployment_policy'
              )
            """
        )
    )
    columns: dict[str, dict[str, str]] = {}
    for table, column, type_name in rows:
        columns.setdefault(table, {})[column] = type_name

    if columns.get("alembic_version", {}).get("version_num") != "text":
        report.blockers.append(
            PreflightIssue(
                "unsupported_schema",
                "A readable Alembic revision is required; use the supported upgrade path.",
            )
        )
        return None
    revisions = (
        await connection.scalars(
            sa.text("SELECT version_num FROM alembic_version LIMIT 2")
        )
    ).all()
    if len(revisions) != 1:
        report.blockers.append(
            PreflightIssue(
                "unsupported_revision",
                "Expected one installed Alembic revision. Resolve the migration state before upgrading.",
            )
        )
        return None
    report.alembic_revision = revisions[0]
    try:
        scripts = ScriptDirectory(str(migration_directory))
        installed = scripts.get_revision(revisions[0])
        if installed.revision != revisions[0]:
            raise CommandError("An exact revision is required")
        ancestors = {
            revision.revision
            for revision in scripts.iterate_revisions(revisions[0], "base")
        }
    except (CommandError, ResolutionError):
        report.blockers.append(
            PreflightIssue(
                "unsupported_revision",
                "The installed revision is not in this release's migration chain. Use its matching release and documented upgrade path.",
            )
        )
        return None

    required = {
        "files": {
            "id": "uuid",
            "file_type": "text",
            "parent_file_id": "uuid",
            "text": "text",
            "blob": "bytea",
            "transcription": "text",
        },
        "icons": {"id": "uuid", "blob": "bytea"},
    }
    unexpected: set[str] = set()
    if _FOUNDATION in ancestors:
        required.update(
            {
                "object_contents": {"id": "uuid", "state": "text"},
                "file_content_references": {
                    "file_id": "uuid",
                    "variant": "text",
                    "ordinal": "int4",
                    "content_id": "uuid",
                },
                "icon_content_references": {
                    "icon_id": "uuid",
                    "variant": "text",
                    "content_id": "uuid",
                },
            }
        )
    else:
        unexpected.update(
            ("object_contents", "file_content_references", "icon_content_references")
        )
    if _EXPAND in ancestors:
        required.update(
            {
                "file_icon_backfill_items": {
                    "owner_kind": "text",
                    "owner_id": "uuid",
                    "variant": "text",
                    "ordinal": "int4",
                    "payload_size_estimate": "int8",
                    "state": "text",
                },
                "file_icon_backfill_campaign": {"state": "text", "target_kind": "text"},
            }
        )
        if _CAPACITY in ancestors:
            required["file_icon_backfill_campaign"]["capacity_admitted_bytes"] = "int8"
            required["file_icon_backfill_items"]["capacity_admitted"] = "bool"
    else:
        unexpected.update(("file_icon_backfill_items", "file_icon_backfill_campaign"))
    if _POLICY in ancestors:
        required["object_content_deployment_policy"] = {
            "id": "int2",
            "new_write_storage_target": "text",
        }
    else:
        unexpected.add("object_content_deployment_policy")

    mismatches = [
        f"{table}.{name}"
        for table, expected in required.items()
        for name, kind in expected.items()
        if columns.get(table, {}).get(name) != kind
    ]
    mismatches.extend(sorted(unexpected.intersection(columns)))
    if _EXPAND in ancestors:
        freezes = await connection.scalar(
            sa.text(
                """
            SELECT count(*) FROM pg_catalog.pg_trigger t
            JOIN pg_catalog.pg_class c ON c.oid = t.tgrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema() AND t.tgenabled IN ('O', 'A')
              AND ((c.relname = 'files' AND t.tgname IN (
                  'freeze_files_legacy_payload_insert', 'freeze_files_legacy_payload_update'))
                OR (c.relname = 'icons' AND t.tgname IN (
                  'freeze_icons_legacy_payload_insert', 'freeze_icons_legacy_payload_update')))
            """
            )
        )
        if freezes != 4:
            mismatches.append("legacy write fence")
    if mismatches:
        report.blockers.append(
            PreflightIssue(
                "unsupported_schema",
                "Schema does not match this revision: "
                + ", ".join(mismatches)
                + ". Stop before upgrade writes. An older destructive revision sharing the same ID requires its pre-upgrade backup; do not stamp past it.",
            )
        )
        return None
    report.schema_state = "expanded" if _EXPAND in ancestors else "pre_expand"
    return ancestors


def _source_query(has_references: bool) -> str:
    # Keep these four source groups equivalent to frozen inventory 202607231745.
    # Only AVAILABLE references are excluded: failed references still need recovery.
    file_join = (
        """
        LEFT JOIN file_content_references r
          ON r.file_id = source.owner_id AND r.variant = source.variant AND r.ordinal = 0
        LEFT JOIN object_contents c ON c.id = r.content_id
    """
        if has_references
        else ""
    )
    icon_join = (
        """
        LEFT JOIN icon_content_references r ON r.icon_id = icon.id AND r.variant = 'primary'
        LEFT JOIN object_contents c ON c.id = r.content_id
    """
        if has_references
        else ""
    )
    available = "coalesce(c.state = 'available', false)" if has_references else "false"
    return f"""
        SELECT 'file' AS owner_kind, source.variant, source.size_bytes,
               {available} AS available
        FROM (
            SELECT id AS owner_id,
                   CASE WHEN file_type = 'text' THEN 'extracted_text'
                        WHEN file_type = 'audio' THEN 'original'
                        WHEN parent_file_id IS NOT NULL THEN 'derived_page'
                        ELSE 'legacy_image' END AS variant,
                   CASE WHEN file_type = 'text' THEN octet_length(text)::bigint
                        ELSE octet_length(blob)::bigint END AS size_bytes
            FROM files
            WHERE CASE WHEN file_type = 'text' THEN text IS NOT NULL
                       ELSE blob IS NOT NULL END
            UNION ALL
            SELECT id, 'original', octet_length(blob)::bigint FROM files
            WHERE file_type = 'text' AND blob IS NOT NULL
            UNION ALL
            SELECT id, 'transcription', octet_length(transcription)::bigint FROM files
            WHERE transcription IS NOT NULL
        ) source {file_join}
        UNION ALL
        SELECT 'icon', 'primary', octet_length(icon.blob)::bigint, {available}
        FROM icons icon {icon_join} WHERE icon.blob IS NOT NULL
    """


async def _inspect(
    connection: AsyncConnection,
    report: FileIconPreflightReport,
    migration_directory: Path,
    inline_maximum_bytes: int,
) -> None:
    ancestors = await _read_schema(connection, report, migration_directory)
    if ancestors is None or report.blockers:
        report.outcome = "blocked"
        return
    report.selected_new_write_target = "postgres_inline"
    if _POLICY in ancestors:
        report.selected_new_write_target = await connection.scalar(
            sa.text(
                "SELECT new_write_storage_target FROM object_content_deployment_policy WHERE id = 1"
            )
        )
    if report.selected_new_write_target not in ("postgres_inline", "object_store"):
        report.blockers.append(
            PreflightIssue(
                "missing_storage_policy",
                "Restore the deployment storage policy before upgrading.",
            )
        )
    if _EXPAND in ancestors:
        capacity_column = (
            "capacity_admitted_bytes" if _CAPACITY in ancestors else "NULL"
        )
        campaign = (
            await connection.execute(
                sa.text(
                    f"SELECT state, {capacity_column} AS admitted FROM file_icon_backfill_campaign"
                )
            )
        ).one_or_none()
        if campaign is not None:
            report.campaign_state = campaign.state
            report.capacity.campaign_admitted_logical_bytes = campaign.admitted

    rows = await connection.execute(
        sa.text(f"""
        WITH source AS ({_source_query(_FOUNDATION in ancestors)})
        SELECT owner_kind, variant, count(*) AS source_count,
               sum(size_bytes) AS source_bytes,
               count(*) FILTER (WHERE available) AS available_reference_count,
               coalesce(sum(size_bytes) FILTER (WHERE available), 0) AS available_reference_bytes,
               count(*) FILTER (WHERE NOT available) AS remaining_count,
               coalesce(sum(size_bytes) FILTER (WHERE NOT available), 0) AS remaining_bytes,
               coalesce(max(size_bytes) FILTER (WHERE NOT available), 0) AS maximum_remaining_item_bytes,
               count(*) FILTER (WHERE NOT available AND size_bytes > :maximum) AS oversized_count,
               count(*) FILTER (WHERE NOT available AND size_bytes = 0) AS empty,
               count(*) FILTER (WHERE NOT available AND size_bytes > 0 AND size_bytes <= :mib) AS small,
               count(*) FILTER (WHERE NOT available AND size_bytes > :mib AND size_bytes <= 16 * :mib) AS medium,
               count(*) FILTER (WHERE NOT available AND size_bytes > 16 * :mib AND size_bytes <= 200 * :mib) AS large,
               count(*) FILTER (WHERE NOT available AND size_bytes > 200 * :mib) AS extra_large
        FROM source GROUP BY owner_kind, variant ORDER BY owner_kind, variant
    """),
        {"maximum": inline_maximum_bytes, "mib": _MIB},
    )
    for row in rows.mappings():
        report.variants.append(
            PreflightVariant(
                owner_kind=row["owner_kind"],
                variant=row["variant"],
                source_count=row["source_count"],
                source_bytes=int(row["source_bytes"]),
                available_reference_count=row["available_reference_count"],
                available_reference_bytes=int(row["available_reference_bytes"]),
                remaining_count=row["remaining_count"],
                remaining_bytes=int(row["remaining_bytes"]),
                maximum_remaining_item_bytes=row["maximum_remaining_item_bytes"],
                oversized_count=row["oversized_count"],
                size_bands=PreflightSizeBands(
                    row["empty"],
                    row["small"],
                    row["medium"],
                    row["large"],
                    row["extra_large"],
                ),
            )
        )
    report.capacity.remaining_logical_bytes = sum(
        row.remaining_bytes for row in report.variants
    )
    if any(row.oversized_count for row in report.variants):
        report.blockers.append(
            PreflightIssue(
                "oversized_legacy_items",
                "Remaining legacy items exceed OBJECT_CONTENT_INLINE_MAXIMUM_BYTES. Resolve the per-item limit and measure database memory/capacity before starting adoption; batch limits do not override it.",
            )
        )
    if (
        any(row.remaining_count for row in report.variants)
        and report.selected_new_write_target == "object_store"
    ):
        report.blockers.append(
            PreflightIssue(
                "unsupported_legacy_target",
                "Select PostgreSQL inline for legacy adoption. Direct legacy-to-object-store adoption is unsupported; verified moves can follow completion.",
            )
        )
    if report.campaign_state == "halted":
        report.blockers.append(
            PreflightIssue(
                "halted_campaign",
                "Inspect migration status and follow the halt-recovery procedure before resuming.",
            )
        )
    report.outcome = "blocked" if report.blockers else "ready"


async def run_file_icon_preflight(
    database_url: str,
    *,
    core_settings: ObjectContentCoreSettings | None = None,
    timeout_seconds: int = 60,
    migration_directory: Path = Path("alembic"),
) -> FileIconPreflightReport:
    """Scan metadata in one bounded, read-only snapshot without fetching payloads.

    Run from the release's backend directory, as in the maintenance worker image.
    The total deadline also bounds connection setup and all statements together.
    """
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be positive")
    settings = core_settings or ObjectContentCoreSettings()
    report = FileIconPreflightReport(inline_maximum_bytes=settings.inline_maximum_bytes)
    engine = create_async_engine(
        make_url(database_url).set(drivername="postgresql+asyncpg"),
        poolclass=NullPool,
        connect_args={"timeout": min(timeout_seconds, 10)},
        hide_parameters=True,
    )
    try:
        async with (
            asyncio.timeout(timeout_seconds),
            engine.connect() as connection,
            connection.begin(),
        ):
            await connection.execute(
                sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            await connection.execute(
                sa.text(
                    "SELECT set_config('statement_timeout', :timeout, true), set_config('lock_timeout', '2000', true)"
                ),
                {"timeout": str(timeout_seconds * 1000)},
            )
            await _inspect(
                connection, report, migration_directory, settings.inline_maximum_bytes
            )
    except Exception:
        # Driver errors may contain SQL, hostnames and credentials. No partial
        # scan is reported as complete, and no automatic retry extends its load.
        report.outcome = "incomplete"
        report.variants.clear()
        report.capacity.remaining_logical_bytes = None
        report.blockers.append(
            PreflightIssue(
                "inspection_incomplete",
                "Preflight could not finish. Check database connectivity, read permissions and locks; rerun with --timeout-seconds increased if the scan needs a larger budget.",
            )
        )
    finally:
        await engine.dispose()
    return report
