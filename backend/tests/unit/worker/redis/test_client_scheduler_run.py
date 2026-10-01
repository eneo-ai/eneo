from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from eneo.websites.domain.crawl_schedule import (
    SchedulerRunRecord,
    SchedulerTenantCounts,
)
from eneo.worker.redis.client import (
    CRAWL_SCHEDULER_RUN_KEY,
    CRAWL_SCHEDULER_RUN_TTL_SECONDS,
    decode_scheduler_run,
    encode_scheduler_run,
    read_crawl_scheduler_run,
    record_crawl_scheduler_run,
)

RAN_AT = datetime(2026, 9, 21, 12, 0, 4, 123456, tzinfo=timezone.utc)


def _record() -> SchedulerRunRecord:
    tenant_a, tenant_b = uuid4(), uuid4()
    return SchedulerRunRecord(
        ran_at=RAN_AT,
        due=5,
        admitted=3,
        failed=2,
        tenants={
            tenant_a: SchedulerTenantCounts(due=3, admitted=3, failed=0),
            tenant_b: SchedulerTenantCounts(due=2, admitted=0, failed=2),
        },
    )


def test_scheduler_run_round_trips_through_json() -> None:
    record = _record()

    decoded = decode_scheduler_run(encode_scheduler_run(record).encode("utf-8"))

    assert decoded == record
    assert decoded is not None and decoded.ran_at.tzinfo is not None


def test_scheduler_run_without_tenants_round_trips() -> None:
    record = SchedulerRunRecord(ran_at=RAN_AT, due=0, admitted=0, failed=0)

    assert decode_scheduler_run(encode_scheduler_run(record)) == record


@pytest.mark.parametrize(
    "raw",
    [
        None,
        b"",
        b"not json",
        b'{"ran_at": "2026-09-21T12:00:00", "due": 1, "admitted": 1, "failed": 0}',
        b'{"due": 1, "admitted": 1, "failed": 0}',
        b'{"ran_at": "2026-09-21T12:00:00+00:00", "due": "many"}',
        b'{"ran_at": "2026-09-21T12:00:00+00:00", "due": 1, "admitted": 1, '
        b'"failed": 0, "tenants": {"nope": {"due": 1, "admitted": 1, "failed": 0}}}',
    ],
    ids=["missing", "empty", "not-json", "naive", "no-ran-at", "bad-int", "bad-uuid"],
)
def test_malformed_marker_reads_as_absent(raw: bytes | None) -> None:
    assert decode_scheduler_run(raw) is None


async def test_record_sets_marker_with_week_long_ttl() -> None:
    redis_client = SimpleNamespace(set=AsyncMock())
    record = _record()

    await record_crawl_scheduler_run(record, redis_client=cast(Any, redis_client))

    redis_client.set.assert_awaited_once_with(
        CRAWL_SCHEDULER_RUN_KEY,
        encode_scheduler_run(record),
        ex=CRAWL_SCHEDULER_RUN_TTL_SECONDS,
    )
    assert CRAWL_SCHEDULER_RUN_TTL_SECONDS == timedelta(days=7).total_seconds()


async def test_read_returns_none_when_marker_missing() -> None:
    redis_client = SimpleNamespace(get=AsyncMock(return_value=None))

    assert await read_crawl_scheduler_run(redis_client=cast(Any, redis_client)) is None
    redis_client.get.assert_awaited_once_with(CRAWL_SCHEDULER_RUN_KEY)


async def test_read_propagates_connection_errors() -> None:
    redis_client = SimpleNamespace(get=AsyncMock(side_effect=RedisConnectionError))

    with pytest.raises(RedisConnectionError):
        await read_crawl_scheduler_run(redis_client=cast(Any, redis_client))
