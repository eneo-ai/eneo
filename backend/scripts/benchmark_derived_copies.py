"""Measure the copy check in conversation reads, the copies window and removal.

Seeds disposable PostgreSQL (both supported major versions) with conversations,
copies with skewed edge counts and their sources, then runs the repositories'
own statements and records EXPLAIN (ANALYZE, BUFFERS) of every statement that
reads the edges, selects the window's questions or removes a question: the
median of five warm runs without per-node timing, the same read without the
check, and from one timed plan how much the check's own subplans took. The
removal of one question of the largest copy is measured as it is and with the
edge check it no longer repeats. Last, the reads with no copies stored, as in
an installation where no feature stores copies. Requires development
dependencies and Docker. No application database is used.

uv run python scripts/benchmark_derived_copies.py --output /tmp/copies-benchmark.json
"""

import argparse
import asyncio
import json
import re
import statistics
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg2
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

# The application module defines every model the repositories hydrate.
import eneo.server.main  # noqa: F401  # isort: skip
from eneo.data_retention.derivations import copy_session_valid
from eneo.data_retention.infrastructure.derived_copy_repo import (
    DerivedCopyRepository,
    edge_position,
)
from eneo.data_retention.infrastructure.retention_sql import question_in_widget
from eneo.database.tables.questions_table import Questions
from eneo.sessions.sessions_repo import SessionRepository

IMAGES = ("pgvector/pgvector:pg13", "pgvector/pgvector:pg16")
SESSIONS = 20_000
TURNS = 10
ASSISTANTS = 10
# Every tenth session of each Assistant is a copy, so a list page of 50 holds
# five; copy k has max(1, 5000 / k^1.2) edges: one with 5000, most with one.
COPY_EVERY = 10
MAX_EDGES = 5_000
WINDOW = 500
WARM_RUNS = 5

SEED = """
INSERT INTO tenants (id, name, quota_limit, state)
VALUES ('00000000-0000-0000-0000-000000000001', 'bench', 1000000000000, 'active');
INSERT INTO users (id, tenant_id, email, username, state, used_tokens, quota_limit)
VALUES ('00000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001',
        'bench@example.test', 'bench', 'active', 0, 1000000000000);
INSERT INTO spaces (id, tenant_id, name)
VALUES ('00000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001', 'bench');
INSERT INTO assistants (id, name, user_id, space_id, logging_enabled, is_default,
                        published, insight_enabled, type)
SELECT ('00000000-0000-0000-0001-' || lpad(a::text, 12, '0'))::uuid, 'bench ' || a,
       '00000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000003',
       false, false, false, false, 'assistant'
FROM generate_series(0, %(assistants)s - 1) a;
INSERT INTO sessions (id, name, user_id, assistant_id, created_at, updated_at)
SELECT ('00000000-0000-0000-0002-' || lpad(n::text, 12, '0'))::uuid, 'conversation ' || n,
       '00000000-0000-0000-0000-000000000002',
       ('00000000-0000-0000-0001-' || lpad((n %% %(assistants)s)::text, 12, '0'))::uuid,
       now() - make_interval(mins => %(sessions)s - n),
       now() - make_interval(mins => %(sessions)s - n)
FROM generate_series(1, %(sessions)s) n;
INSERT INTO questions (id, question, answer, num_tokens_question, num_tokens_answer,
                       tenant_id, session_id, assistant_id, created_at, updated_at)
SELECT gen_random_uuid(), repeat('question ', 40), repeat('answer ', 80), 40, 80,
       '00000000-0000-0000-0000-000000000001', s.id, s.assistant_id,
       s.created_at + make_interval(secs => t), s.created_at + make_interval(secs => t)
FROM sessions s, generate_series(1, %(turns)s) t;
CREATE TEMP TABLE source_pool AS
SELECT q.id, row_number() OVER (ORDER BY q.id) AS rn
FROM questions q JOIN sessions s ON s.id = q.session_id
WHERE (substr(s.name, 14)::int / %(assistants)s) %% %(copy_every)s <> 0;
CREATE TEMP TABLE copies AS
SELECT s.id, row_number() OVER (ORDER BY s.created_at DESC) AS k
FROM sessions s
WHERE (substr(s.name, 14)::int / %(assistants)s) %% %(copy_every)s = 0;
INSERT INTO content_derivations (copy_session_id, source_question_id)
SELECT c.id, p.id
FROM copies c
CROSS JOIN LATERAL generate_series(
    1, greatest(1, floor(%(max_edges)s / power(c.k, 1.2)))::int) e
JOIN source_pool p
  ON p.rn = 1 + ((c.k * 7919 + e * 104729) %% (SELECT count(*) FROM source_pool))
ON CONFLICT DO NOTHING;
ANALYZE;
"""

Statement = tuple[str, Any]

# The rendered read check (sessions_repo, questions_repo, analysis_repo): the
# same statement with it replaced by `true` is that read's baseline.
_READ_CHECK = re.compile(
    r"NOT \(EXISTS \(SELECT 1\s+FROM content_derivations\s+WHERE .*?"
    r"OFFSET 0\)\)\s+LIMIT ALL OFFSET 0\)\)",
    re.DOTALL,
)


# Statements worth a plan: those that read the edges, the window's selection
# and lock of the invalid copies' questions, and the removal of a question.
_MEASURED = ("content_derivations", "copy_window", "DELETE FROM questions")


async def _explained(
    engine: Any, call: Callable[[AsyncSession], Awaitable[object]]
) -> list[dict[str, object]]:
    """Run `call`, then EXPLAIN ANALYZE each measured statement it sent, once
    cold and WARM_RUNS times warm, with the same parameters, rolled back."""
    captured: list[Statement] = []

    def record(_conn, _cursor, statement, parameters, _context, _many) -> None:
        if not statement.startswith("EXPLAIN") and any(
            part in statement for part in _MEASURED
        ):
            captured.append((statement, parameters))

    sa.event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        async with AsyncSession(engine) as session, session.begin():
            await call(session)
            await session.rollback()
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", record)
    plans = []
    async with engine.connect() as connection:
        for statement, parameters in captured:
            # Totals without per-node timing, whose overhead grows with the
            # number of subplan calls; one timed plan for the check's share.
            totals = await _totals(connection, statement, parameters)
            timed = await _explain(connection, statement, parameters, timing=True)
            baseline, checks = _READ_CHECK.subn("true", statement)
            plans.append(
                {
                    "statement": statement,
                    "first_ms": totals[0],
                    "warm_ms": statistics.median(totals[1:]),
                    "baseline_warm_ms": statistics.median(
                        (await _totals(connection, baseline, parameters))[1:]
                    )
                    if checks
                    else None,
                    "timed_ms": timed["Execution Time"],
                    "timed_check_ms": round(_check_ms(timed["Plan"]), 3),
                    "timed_plan": timed["Plan"],
                }
            )
    return plans


async def _totals(connection: Any, statement: str, parameters: Any) -> list[float]:
    """Execution times of one cold and WARM_RUNS warm runs."""
    return [
        (await _explain(connection, statement, parameters, timing=False))[
            "Execution Time"
        ]
        for _ in range(1 + WARM_RUNS)
    ]


async def _explain(
    connection: Any, statement: str, parameters: Any, *, timing: bool
) -> dict[str, Any]:
    """EXPLAIN ANALYZE of the statement, rolled back."""
    options = "ANALYZE, BUFFERS, FORMAT JSON" + ("" if timing else ", TIMING OFF")
    async with connection.begin() as transaction:
        result = await connection.exec_driver_sql(
            f"EXPLAIN ({options}) " + statement, parameters
        )
        explained = result.scalar_one()[0]
        await transaction.rollback()
    return explained


def _check_ms(plan: dict[str, Any]) -> float:
    """Time spent in the subplans that read the edges: the copy check's cost,
    each a probe per row of the statement's own candidates."""

    def reads_edges(node: dict[str, Any]) -> bool:
        return node.get("Relation Name") == "content_derivations" or any(
            reads_edges(child) for child in node.get("Plans", [])
        )

    total = 0.0
    for child in plan.get("Plans", []):
        if child.get("Subplan Name") and reads_edges(child):
            total += child["Actual Total Time"] * child["Actual Loops"]
        else:
            total += _check_ms(child)
    return total


async def _measure(url: str) -> dict[str, object]:
    engine = create_async_engine(url)
    user = UUID("00000000-0000-0000-0000-000000000002")
    assistant = UUID("00000000-0000-0000-0001-000000000000")
    try:
        async with engine.connect() as connection:
            largest = (
                await connection.execute(
                    sa.text(
                        "SELECT copy_session_id, count(*) FROM content_derivations "
                        "GROUP BY 1 ORDER BY 2 DESC LIMIT 1"
                    )
                )
            ).one()
            edge_total = (
                await connection.execute(
                    sa.text("SELECT count(*) FROM content_derivations")
                )
            ).scalar_one()
        copy_session, copy_edges = largest

        cases: dict[str, Callable[[AsyncSession], Awaitable[object]]] = {
            "valid copy detail (largest copy)": lambda s: SessionRepository(s).get(
                copy_session
            ),
            "assistant list page of 50 with its total": lambda s: (
                SessionRepository(s).get_metadata_by_assistant(
                    assistant, user_id=user, limit=50
                )
            ),
            "recent conversations": lambda s: SessionRepository(s).get_recent_for_user(
                user_id=user,
                assistant_ids=[
                    UUID(f"00000000-0000-0000-0001-{index:012d}")
                    for index in range(ASSISTANTS)
                ],
                group_chat_ids=[],
                limit=20,
            ),
            "copies window, no invalid copy": lambda s: DerivedCopyRepository(
                s, now=_now()
            ).lock_due_page(None, WINDOW),
        }
        results: dict[str, object] = {
            "edges": edge_total,
            "largest_copy_edges": copy_edges,
        }
        for name, call in cases.items():
            results[name] = await _explained(engine, call)

        # Remove the source of the largest copy's last edge in index order, so
        # its check probes every edge before it finds the removed one.
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "DELETE FROM questions WHERE id = (SELECT source_question_id "
                    "FROM content_derivations WHERE copy_session_id = :copy "
                    "ORDER BY source_question_id DESC LIMIT 1)"
                ),
                {"copy": copy_session},
            )
            # The task's cursor before the removed edge, half a window back.
            before_removed = (
                await connection.execute(
                    sa.text(
                        "SELECT source_question_id FROM content_derivations "
                        "WHERE copy_session_id = :copy "
                        "ORDER BY source_question_id DESC OFFSET :back LIMIT 1"
                    ),
                    {"copy": copy_session, "back": WINDOW // 2},
                )
            ).scalar_one()
            copy_question = (
                await connection.execute(
                    sa.text(
                        "SELECT id FROM questions WHERE session_id = :copy "
                        "ORDER BY created_at, id LIMIT 1"
                    ),
                    {"copy": copy_session},
                )
            ).scalar_one()

        async def window(session: AsyncSession) -> object:
            page = await DerivedCopyRepository(session, now=_now()).lock_due_page(
                edge_position(copy_session, before_removed), WINDOW
            )
            assert page.roots, "the window selected no question of an invalid copy"
            return page

        async def removal(session: AsyncSession) -> object:
            removed = await DerivedCopyRepository(
                session, now=_now()
            ).delete_if_still_removed(copy_question)
            assert removed is not None, "the question of an invalid copy stayed"
            return removed

        async def removal_rereading_edges(session: AsyncSession) -> object:
            return await session.execute(
                sa.delete(Questions).where(
                    Questions.id == copy_question,
                    ~question_in_widget(),
                    ~copy_session_valid(Questions.session_id.expression),
                )
            )

        invalid: dict[str, Callable[[AsyncSession], Awaitable[object]]] = {
            "invalid copy detail (largest copy)": lambda s: SessionRepository(s).get(
                copy_session
            ),
            "invalid copy check after the miss": lambda s: SessionRepository(
                s
            ).is_removed_copy(copy_session),
            "copies window with an invalid copy": window,
            "removal of one question of the largest copy": removal,
            "the same removal rereading the copy's edges": removal_rereading_edges,
        }
        for name, call in invalid.items():
            results[name] = await _explained(engine, call)

        # What an installation without a feature that stores copies runs.
        async with engine.begin() as connection:
            await connection.execute(sa.text("TRUNCATE content_derivations"))
            await connection.execute(sa.text("ANALYZE content_derivations"))
        for name in (
            "assistant list page of 50 with its total",
            "recent conversations",
        ):
            results[f"{name}, no copies stored"] = await _explained(engine, cases[name])
        return results
    finally:
        await engine.dispose()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def benchmark(output: Path) -> None:
    results: dict[str, object] = {
        "sessions": SESSIONS,
        "questions": SESSIONS * TURNS,
        "copy_sessions": SESSIONS // COPY_EVERY,
        "window": WINDOW,
        "images": {},
    }
    for image in IMAGES:
        with PostgresContainer(image) as postgres:
            url = postgres.get_connection_url()
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", url)
            command.upgrade(config, "head")
            with psycopg2.connect(url.replace("+psycopg2", "")) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        SEED,
                        {
                            "assistants": ASSISTANTS,
                            "sessions": SESSIONS,
                            "turns": TURNS,
                            "copy_every": COPY_EVERY,
                            "max_edges": MAX_EDGES,
                        },
                    )
                connection.commit()
            measured = asyncio.run(_measure(url.replace("+psycopg2", "+asyncpg")))
            results["images"][image] = measured  # type: ignore[index]
            print(
                json.dumps(
                    {
                        "image": image,
                        **{
                            name: [
                                (
                                    plan["warm_ms"],
                                    plan["baseline_warm_ms"],
                                    plan["timed_check_ms"],
                                )
                                for plan in plans
                            ]
                            for name, plans in measured.items()
                            if isinstance(plans, list)
                        },
                    }
                ),
                flush=True,
            )
    output.write_text(json.dumps(results, indent=2, default=str) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    benchmark(parser.parse_args().output)
