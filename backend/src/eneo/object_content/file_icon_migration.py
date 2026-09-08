"""Operator controls for the temporary File/Icon migration.

Run inside the maintenance worker environment:
    python -m eneo.object_content.file_icon_migration preflight|status|pause|resume|cleanup
"""

import argparse
import asyncio
import json
import sys
from contextlib import redirect_stdout
from dataclasses import asdict

import sqlalchemy as sa
from pydantic import ValidationError


async def _preflight(timeout_seconds: int) -> tuple[str, int]:
    from eneo.main.config import get_settings
    from eneo.object_content.file_icon_preflight import (
        FileIconPreflightReport,
        PreflightIssue,
        run_file_icon_preflight,
    )

    try:
        report = await run_file_icon_preflight(
            get_settings().database_url, timeout_seconds=timeout_seconds
        )
    except (ValidationError, ValueError):
        report = FileIconPreflightReport(
            blockers=[
                PreflightIssue(
                    "invalid_configuration",
                    "Preflight configuration is invalid. Check the worker's database and OBJECT_CONTENT settings; values are omitted to protect credentials.",
                )
            ]
        )
    return json.dumps(asdict(report), indent=2), {
        "ready": 0,
        "blocked": 2,
        "incomplete": 3,
    }[report.outcome]


async def _run(command: str) -> str:
    from eneo.database.database import DatabaseSessionManager
    from eneo.main.config import get_settings
    from eneo.main.logging import get_logger
    from eneo.object_content.file_icon_backfill import (
        FileIconBackfillSettings,
        read_file_icon_backfill_status,
        set_file_icon_backfill_paused,
    )

    logger = get_logger(__name__)
    database = DatabaseSessionManager()
    database.init(get_settings().database_url)
    try:
        if command == "cleanup":
            from eneo.object_content.file_icon_cleanup import (
                cleanup_file_icon_legacy_storage,
            )

            async with database.connect() as connection:
                cleaned = await connection.run_sync(cleanup_file_icon_legacy_storage)
            return json.dumps(
                {
                    "legacy_cleaned": True,
                    "changed": cleaned,
                    "detail": "Legacy columns removed"
                    if cleaned
                    else "Legacy columns were already cleaned",
                },
                indent=2,
            )
        elif command == "status":
            settings = FileIconBackfillSettings()
            async with database.session() as session, session.begin():
                await session.execute(
                    sa.text(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                    )
                )
                status = await read_file_icon_backfill_status(session, settings)
            return json.dumps(asdict(status), indent=2)
        else:
            paused = command == "pause"
            async with database.session() as session, session.begin():
                await set_file_icon_backfill_paused(session, paused=paused)
            logger.info(
                "object_content.file_icon_migration_pause_changed",
                extra={"paused": paused},
            )
            return json.dumps(
                {
                    "paused": paused,
                    "detail": (
                        "New migration claims are paused; an already claimed batch may finish"
                        if paused
                        else "Migration claims may resume; capacity and failure recovery checks still apply"
                    ),
                },
                indent=2,
            )
    finally:
        await database.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("preflight", "status", "pause", "resume", "cleanup")
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=60,
        help="Total preflight scan deadline in seconds (default: 60)",
    )
    arguments = parser.parse_args()
    if arguments.timeout_seconds < 1:
        parser.error("--timeout-seconds must be positive")
    # App loggers bind their console stream on import. Keep diagnostics on
    # stderr and reserve stdout for one complete JSON result.
    with redirect_stdout(sys.stderr):
        if arguments.command == "preflight":
            result, exit_code = asyncio.run(_preflight(arguments.timeout_seconds))
        elif arguments.command == "cleanup":
            from sqlalchemy.exc import SQLAlchemyError

            from eneo.object_content.file_icon_cleanup import FileIconCleanupRefused

            try:
                result = asyncio.run(_run(arguments.command))
                exit_code = 0
            except FileIconCleanupRefused as error:
                result = json.dumps(
                    {"outcome": "blocked", "detail": str(error)}, indent=2
                )
                exit_code = 2
            except SQLAlchemyError:
                result = json.dumps(
                    {
                        "outcome": "incomplete",
                        "detail": "Cleanup could not finish. Check database connectivity, schema, permissions and locks, then run status before retrying. No automatic retry was attempted.",
                    },
                    indent=2,
                )
                exit_code = 3
        else:
            result = asyncio.run(_run(arguments.command))
            exit_code = 0
    print(result)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
