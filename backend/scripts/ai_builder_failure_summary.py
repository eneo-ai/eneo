"""Group persisted Flow AI Builder failures so the next fix is chosen from data.

Reads three stores the product already writes — builder session turns with
terminal failure states, failed flow runs, and client-reported errors — and
prints per-family counts with sample ids for the last N days. Read-only; no new
telemetry is collected here. Sample ids are the entry point for root-cause work:
a session id resolves to the full stored conversation, plan and error turn.

Usage (settings come from the environment, like every backend script):
    uv run python scripts/ai_builder_failure_summary.py --days 7
    uv run python scripts/ai_builder_failure_summary.py --days 7 --format json
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_failure_ledger import FailureSummary


def _ensure_backend_src_importable() -> None:
    backend_src = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
    if backend_src not in sys.path:
        sys.path.insert(0, backend_src)


_ensure_backend_src_importable()


async def _collect(days: int) -> "FailureSummary":
    from sqlalchemy.ext.asyncio import create_async_engine

    from eneo.flows.ai_builder.ai_builder_failure_ledger import (
        collect_failure_summary,
    )
    from eneo.main.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with engine.connect() as conn:
        report = await collect_failure_summary(conn, since=since)
    await engine.dispose()
    return report


def _render_markdown(report: "FailureSummary") -> str:
    lines = [f"# AI Builder failures since {report.since.isoformat()}", ""]
    for title, section in (
        (
            "Builder turn failure snapshot (current state, by session update time)",
            report.builder_turn_failure_snapshot,
        ),
        ("Flow run failures", report.flow_run_failures),
        ("Client-reported errors", report.client_errors),
    ):
        lines.append(f"## {title}")
        if not section.families:
            lines.append("- none")
        for family in section.families:
            lines.append(
                f"- {family.group} / {family.detail}: {family.occurrences}"
                f" — samples {family.sample_ids}"
            )
        if section.truncated:
            lines.append(f"- … truncated: {section.total_families} families total")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    from eneo.flows.ai_builder.ai_builder_failure_ledger import MAX_WINDOW_DAYS

    # The same bound the sysadmin endpoint enforces, from the one owner.
    parser.add_argument(
        "--days", type=int, default=7, choices=range(1, MAX_WINDOW_DAYS + 1)
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()
    report = asyncio.run(_collect(args.days))
    if args.format == "json":
        print(report.model_dump_json(indent=2))
    else:
        print(_render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
