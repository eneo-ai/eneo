"""Opt-in benchmark for the staged File/Icon PostgreSQL-inline backfill.

The benchmark uses the real PostgreSQL 16 integration container and the real
``FileIconBackfill`` implementation. It is skipped unless explicitly enabled:

    ENEO_RUN_FILE_ICON_BACKFILL_BENCHMARK=1 \
    uv run pytest -s \
      tests/integration/object_content/test_file_icon_backfill_benchmark.py

Payloads are random, repeated BYTEA values so PostgreSQL cannot hide the cost
with TOAST compression. Runs above 1 GiB require an exact size confirmation;
for example, a 5 GiB run uses both size variables below:

    ENEO_RUN_FILE_ICON_BACKFILL_BENCHMARK=1 \
    ENEO_FILE_ICON_BENCHMARK_TOTAL_MIB=5120 \
    ENEO_FILE_ICON_BENCHMARK_CONFIRM_MIB=5120 \
    uv run pytest -s \
      tests/integration/object_content/test_file_icon_backfill_benchmark.py

Confirm that the disposable PostgreSQL/Docker volume has room for the legacy
payloads, inline copies, and WAL before a large run. The host filesystem cannot
reliably report a Docker volume's free space. Retire this release benchmark when
the staged contract removes the legacy columns and backfill ledger.

This benchmark verifies accounting, content digests, references, and legacy
presence. The focused integration suite owns exact inline-payload byte behavior.
"""

from __future__ import annotations

import json
import os
import platform
import resource
import secrets
import statistics
import time
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.users_table import Users
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.file_icon_backfill import (
    FileIconBackfill,
    FileIconBackfillSettings,
    FileIconBackfillState,
)

_MEBIBYTE = 1024 * 1024
_INLINE_MAXIMUM_BYTES = 200 * _MEBIBYTE
_INLINE_IO_CHUNK_BYTES = 256 * 1024
_RUN_BENCHMARK = os.getenv("ENEO_RUN_FILE_ICON_BACKFILL_BENCHMARK") == "1"

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not _RUN_BENCHMARK,
        reason="set ENEO_RUN_FILE_ICON_BACKFILL_BENCHMARK=1 to run",
    ),
]


@dataclass(frozen=True, slots=True)
class _BenchmarkConfig:
    total_mib: int
    item_kib: int
    seed_rows_per_transaction: int
    batch_rows: int
    batch_mib: int

    @property
    def target_bytes(self) -> int:
        return self.total_mib * _MEBIBYTE

    @property
    def item_bytes(self) -> int:
        return self.item_kib * 1024

    @property
    def item_count(self) -> int:
        return (self.target_bytes + self.item_bytes - 1) // self.item_bytes

    @property
    def seeded_bytes(self) -> int:
        return self.item_count * self.item_bytes


@dataclass(frozen=True, slots=True)
class _DatabaseSnapshot:
    wal_lsn: int
    database_bytes: int
    files_bytes: int
    ledger_bytes: int
    content_bytes: int
    inline_bytes: int
    server_version: str
    shared_buffers: str
    work_mem: str
    max_wal_size: str
    checkpoint_completion_target: str
    wal_compression: str
    synchronous_commit: str


@dataclass(frozen=True, slots=True)
class _BackfillMetrics:
    active_seconds: float
    active_mib_per_second: float
    batch_count: int
    batch_seconds_mean: float
    batch_seconds_p50: float
    batch_seconds_p95: float
    batch_seconds_max: float
    projected_minute_cron_seconds: float
    admitted_count: int
    claimed_count: int
    completed_count: int


@dataclass(frozen=True, slots=True)
class _VerificationResult:
    done_count: int
    failed_count: int
    reference_count: int
    inline_count: int
    content_bytes: int
    digest_mismatch_count: int
    preserved_legacy_count: int
    campaign_state: str


def _positive_env(name: str, default: int, *, maximum: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def _benchmark_config() -> _BenchmarkConfig:
    config = _BenchmarkConfig(
        total_mib=_positive_env(
            "ENEO_FILE_ICON_BENCHMARK_TOTAL_MIB",
            256,
            maximum=10 * 1024,
        ),
        item_kib=_positive_env(
            "ENEO_FILE_ICON_BENCHMARK_ITEM_KIB",
            640,
            maximum=200 * 1024,
        ),
        seed_rows_per_transaction=_positive_env(
            "ENEO_FILE_ICON_BENCHMARK_SEED_ROWS",
            64,
            maximum=1000,
        ),
        batch_rows=_positive_env(
            "ENEO_FILE_ICON_BENCHMARK_BATCH_ROWS",
            100,
            maximum=1000,
        ),
        batch_mib=_positive_env(
            "ENEO_FILE_ICON_BENCHMARK_BATCH_MIB",
            32,
            maximum=10 * 1024,
        ),
    )
    if config.total_mib > 1024 and os.getenv(
        "ENEO_FILE_ICON_BENCHMARK_CONFIRM_MIB"
    ) != str(config.total_mib):
        raise ValueError(
            "benchmarks above 1 GiB require "
            "ENEO_FILE_ICON_BENCHMARK_CONFIRM_MIB to equal the requested MiB"
        )
    return config


async def _tenant_and_user(
    database: DatabaseSessionManager,
) -> tuple[UUID, UUID]:
    async with database.session() as session, session.begin():
        return (
            await session.execute(
                sa.select(Users.tenant_id, Users.id).where(
                    Users.email == "object-content@example.test"
                )
            )
        ).one()


async def _seed_legacy_payloads(
    database: DatabaseSessionManager,
    config: _BenchmarkConfig,
) -> tuple[int, bytes, float]:
    tenant_id, user_id = await _tenant_and_user(database)
    payload = secrets.token_bytes(config.item_bytes)
    payload_sha256 = sha256(payload).digest()
    checksum = payload_sha256.hex()
    seeded_rows = 0
    started_at = time.perf_counter()

    statement = sa.text(
        """
        WITH inserted AS (
            INSERT INTO files (
                id, name, text, blob, checksum, size, mimetype, file_type,
                transcription, user_id, tenant_id, parent_file_id
            )
            SELECT
                gen_random_uuid(),
                'file-icon-backfill-benchmark-' || :seed_batch || '-' || series,
                NULL,
                CAST(:payload AS bytea),
                :checksum,
                :payload_size,
                'application/octet-stream',
                'image',
                NULL,
                :user_id,
                :tenant_id,
                NULL
            FROM generate_series(1, :row_count) AS series
            RETURNING id, tenant_id, size
        )
        INSERT INTO file_icon_backfill_items (
            owner_kind, owner_id, variant, ordinal, tenant_id,
            payload_size_estimate
        )
        SELECT 'file', id, 'legacy_image', 0, tenant_id, size
        FROM inserted
        """
    )
    seed_batch = 0
    while seeded_rows < config.item_count:
        row_count = min(
            config.seed_rows_per_transaction,
            config.item_count - seeded_rows,
        )
        async with database.session() as session, session.begin():
            await session.execute(
                sa.text("SET LOCAL session_replication_role = replica")
            )
            await session.execute(
                statement,
                {
                    "seed_batch": str(seed_batch),
                    "payload": payload,
                    "checksum": checksum,
                    "payload_size": len(payload),
                    "row_count": row_count,
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                },
            )
        seeded_rows += row_count
        seed_batch += 1

    return seeded_rows, payload_sha256, time.perf_counter() - started_at


async def _database_snapshot(database: DatabaseSessionManager) -> _DatabaseSnapshot:
    async with database.session() as session, session.begin():
        row = (
            await session.execute(
                sa.text(
                    """
                    SELECT
                        pg_current_wal_lsn() AS wal_lsn,
                        pg_database_size(current_database()) AS database_bytes,
                        pg_total_relation_size('files') AS files_bytes,
                        pg_total_relation_size('file_icon_backfill_items')
                            AS ledger_bytes,
                        pg_total_relation_size('object_contents') AS content_bytes,
                        pg_total_relation_size('inline_content_payloads')
                            AS inline_bytes,
                        current_setting('server_version') AS server_version,
                        current_setting('shared_buffers') AS shared_buffers,
                        current_setting('work_mem') AS work_mem,
                        current_setting('max_wal_size') AS max_wal_size,
                        current_setting('checkpoint_completion_target')
                            AS checkpoint_completion_target,
                        current_setting('wal_compression') AS wal_compression,
                        current_setting('synchronous_commit') AS synchronous_commit
                    """
                )
            )
        ).one()
    return _DatabaseSnapshot(
        wal_lsn=int(row.wal_lsn),
        database_bytes=int(row.database_bytes),
        files_bytes=int(row.files_bytes),
        ledger_bytes=int(row.ledger_bytes),
        content_bytes=int(row.content_bytes),
        inline_bytes=int(row.inline_bytes),
        server_version=str(row.server_version),
        shared_buffers=str(row.shared_buffers),
        work_mem=str(row.work_mem),
        max_wal_size=str(row.max_wal_size),
        checkpoint_completion_target=str(row.checkpoint_completion_target),
        wal_compression=str(row.wal_compression),
        synchronous_commit=str(row.synchronous_commit),
    )


def _max_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if platform.system() == "Darwin" else value * 1024)


def _percentile(values: list[float], percentile: float) -> float:
    if len(values) == 1:
        return values[0]
    position = round((len(values) - 1) * percentile)
    return sorted(values)[position]


async def _run_backfill(
    database: DatabaseSessionManager,
    config: _BenchmarkConfig,
) -> tuple[_BackfillMetrics, FileIconBackfillState]:
    backfill = FileIconBackfill(
        FileIconBackfillSettings(
            auto_inline_max_bytes=config.seeded_bytes,
            batch_rows=config.batch_rows,
            batch_bytes=config.batch_mib * _MEBIBYTE,
        ),
        ObjectContentService(
            ObjectContentCoreSettings(
                _env_file=None,
                inline_maximum_bytes=_INLINE_MAXIMUM_BYTES,
                inline_io_chunk_bytes=_INLINE_IO_CHUNK_BYTES,
            ),
            database,
        ),
        database,
    )
    durations: list[float] = []
    completed_count = 0
    admitted_count = 0
    claimed_count = 0
    started_at = time.perf_counter()
    final_state = FileIconBackfillState.ACTIVE
    maximum_runs = config.item_count + 1
    for _ in range(maximum_runs):
        batch_started_at = time.perf_counter()
        result = await backfill.run_once()
        durations.append(time.perf_counter() - batch_started_at)
        completed_count += result.completed_count
        admitted_count += result.admitted_count
        claimed_count += result.claimed_count
        final_state = result.state
        if result.state is not FileIconBackfillState.ACTIVE:
            break
    elapsed = time.perf_counter() - started_at
    projected_cron_seconds = sum(max(60.0, value) for value in durations[:-1])
    projected_cron_seconds += durations[-1]
    return (
        _BackfillMetrics(
            active_seconds=elapsed,
            active_mib_per_second=config.seeded_bytes / _MEBIBYTE / elapsed,
            batch_count=len(durations),
            batch_seconds_mean=statistics.fmean(durations),
            batch_seconds_p50=_percentile(durations, 0.50),
            batch_seconds_p95=_percentile(durations, 0.95),
            batch_seconds_max=max(durations),
            projected_minute_cron_seconds=projected_cron_seconds,
            admitted_count=admitted_count,
            claimed_count=claimed_count,
            completed_count=completed_count,
        ),
        final_state,
    )


async def _verify_result(
    database: DatabaseSessionManager,
    expected_sha256: bytes,
) -> _VerificationResult:
    async with database.session() as session, session.begin():
        row = (
            await session.execute(
                sa.text(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE item.state = 'done') AS done_count,
                        COUNT(*) FILTER (WHERE item.state = 'failed') AS failed_count,
                        COUNT(reference.content_id) AS reference_count,
                        COUNT(payload.content_id) AS inline_count,
                        COALESCE(SUM(content.size_bytes), 0) AS content_bytes,
                        COUNT(*) FILTER (
                            WHERE content.sha256 IS DISTINCT FROM :sha256
                        ) AS digest_mismatch_count,
                        COUNT(*) FILTER (WHERE file.blob IS NOT NULL)
                            AS preserved_legacy_count,
                        MIN(campaign.state) AS campaign_state
                    FROM file_icon_backfill_items AS item
                    JOIN files AS file ON file.id = item.owner_id
                    LEFT JOIN object_contents AS content
                      ON content.id = item.content_id
                    LEFT JOIN inline_content_payloads AS payload
                      ON payload.content_id = content.id
                    LEFT JOIN file_content_references AS reference
                      ON reference.content_id = content.id
                    CROSS JOIN file_icon_backfill_campaign AS campaign
                    """
                ),
                {"sha256": expected_sha256},
            )
        ).one()
    return _VerificationResult(
        done_count=int(row.done_count),
        failed_count=int(row.failed_count),
        reference_count=int(row.reference_count),
        inline_count=int(row.inline_count),
        content_bytes=int(row.content_bytes),
        digest_mismatch_count=int(row.digest_mismatch_count),
        preserved_legacy_count=int(row.preserved_legacy_count),
        campaign_state=str(row.campaign_state),
    )


async def test_file_icon_inline_backfill_benchmark(
    object_content_database: DatabaseSessionManager,
) -> None:
    config = _benchmark_config()
    seeded_count, payload_sha256, seed_seconds = await _seed_legacy_payloads(
        object_content_database,
        config,
    )
    before = await _database_snapshot(object_content_database)
    rss_before = _max_rss_bytes()

    backfill, final_state = await _run_backfill(object_content_database, config)

    rss_after = _max_rss_bytes()
    after = await _database_snapshot(object_content_database)
    verification = await _verify_result(
        object_content_database,
        payload_sha256,
    )
    async with object_content_database.session() as session, session.begin():
        wal_bytes = int(
            await session.scalar(
                sa.text(
                    "SELECT pg_wal_lsn_diff("
                    "CAST(:after AS pg_lsn), CAST(:before AS pg_lsn))"
                ),
                {"after": after.wal_lsn, "before": before.wal_lsn},
            )
            or 0
        )

    batch_items_by_bytes = max(
        1,
        config.batch_mib * _MEBIBYTE // config.item_bytes,
    )
    expected_copy_batch_count = (
        config.item_count + min(config.batch_rows, batch_items_by_bytes) - 1
    ) // min(config.batch_rows, batch_items_by_bytes)
    expected_admission_batch_count = (
        config.item_count + config.batch_rows - 1
    ) // config.batch_rows
    expected_batch_count = (
        expected_admission_batch_count + expected_copy_batch_count - 1
    )
    report = {
        "config": asdict(config),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "object_content_inline_maximum_bytes": _INLINE_MAXIMUM_BYTES,
            "object_content_inline_io_chunk_bytes": _INLINE_IO_CHUNK_BYTES,
            "postgres": {
                "server_version": before.server_version,
                "shared_buffers": before.shared_buffers,
                "work_mem": before.work_mem,
                "max_wal_size": before.max_wal_size,
                "checkpoint_completion_target": before.checkpoint_completion_target,
                "wal_compression": before.wal_compression,
                "synchronous_commit": before.synchronous_commit,
            },
        },
        "seed": {
            "seconds": seed_seconds,
            "item_count": config.item_count,
            "seeded_bytes": config.seeded_bytes,
            "mib_per_second": config.seeded_bytes / _MEBIBYTE / seed_seconds,
        },
        "backfill": asdict(backfill),
        "resources": {
            "wal_bytes": wal_bytes,
            "max_rss_bytes_before": rss_before,
            "max_rss_bytes_after": rss_after,
            "database_bytes_before": before.database_bytes,
            "database_bytes_after": after.database_bytes,
            "files_bytes_before": before.files_bytes,
            "files_bytes_after": after.files_bytes,
            "inline_bytes_before": before.inline_bytes,
            "inline_bytes_after": after.inline_bytes,
        },
        "verification": asdict(verification),
    }
    serialized = json.dumps(report, sort_keys=True)
    output_path = os.getenv("ENEO_FILE_ICON_BENCHMARK_OUTPUT")
    if output_path is None:
        print("FILE_ICON_BACKFILL_BENCHMARK_RESULT=" + serialized)
    else:
        Path(output_path).write_text(serialized + "\n", encoding="utf-8")

    assert final_state is FileIconBackfillState.COMPLETE
    assert seeded_count == config.item_count
    assert backfill.admitted_count == config.item_count
    assert backfill.claimed_count == config.item_count
    assert backfill.completed_count == config.item_count
    assert backfill.batch_count == expected_batch_count
    assert verification == _VerificationResult(
        done_count=config.item_count,
        failed_count=0,
        reference_count=config.item_count,
        inline_count=config.item_count,
        content_bytes=config.seeded_bytes,
        digest_mismatch_count=0,
        preserved_legacy_count=config.item_count,
        campaign_state=FileIconBackfillState.COMPLETE.value,
    )
