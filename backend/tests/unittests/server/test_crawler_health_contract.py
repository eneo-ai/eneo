from eneo.server.main import CrawlerHealthResponse, determine_crawler_health


def test_crawler_health_contract_uses_authoritative_lifecycle_signals() -> None:
    properties = CrawlerHealthResponse.model_json_schema()["properties"]

    assert {"lifecycle", "transport", "capacity"}.issubset(properties)
    assert {"watchdog", "feeder", "pending"}.isdisjoint(properties)


def test_missing_crawler_worker_is_unhealthy() -> None:
    status, flags, reason = determine_crawler_health(
        redis_error=None,
        database_ok=True,
        executor_heartbeat_ttl=-2,
        reconciliation_heartbeat_ttl=30,
        expired_leases=0,
        pending_transport_cleanup=0,
    )

    assert status == "UNHEALTHY"
    assert flags == [
        "EXECUTOR_HEARTBEAT_MISSING",
        "RECONCILIATION_HEARTBEAT_OK",
        "DB_QUERY_OK",
    ]
    assert "not found" in reason


def test_expired_execution_lease_degrades_health() -> None:
    status, flags, reason = determine_crawler_health(
        redis_error=None,
        database_ok=True,
        executor_heartbeat_ttl=30,
        reconciliation_heartbeat_ttl=30,
        expired_leases=2,
        pending_transport_cleanup=0,
    )

    assert status == "DEGRADED"
    assert flags == [
        "EXECUTOR_HEARTBEAT_OK",
        "RECONCILIATION_HEARTBEAT_OK",
        "DB_QUERY_OK",
        "EXPIRED_LEASES",
    ]
    assert "2" in reason


def test_pending_transport_cleanup_degrades_health() -> None:
    status, flags, reason = determine_crawler_health(
        redis_error=None,
        database_ok=True,
        executor_heartbeat_ttl=30,
        reconciliation_heartbeat_ttl=30,
        expired_leases=0,
        pending_transport_cleanup=2,
    )

    assert status == "DEGRADED"
    assert "TRANSPORT_CLEANUP_PENDING" in flags
    assert "2" in reason


def test_unavailable_authoritative_store_makes_health_unknown() -> None:
    status, flags, _ = determine_crawler_health(
        redis_error=None,
        database_ok=False,
        executor_heartbeat_ttl=30,
        reconciliation_heartbeat_ttl=30,
        expired_leases=None,
        pending_transport_cleanup=None,
    )

    assert status == "UNKNOWN"
    assert flags == [
        "EXECUTOR_HEARTBEAT_OK",
        "RECONCILIATION_HEARTBEAT_OK",
        "DB_QUERY_ERROR",
    ]


def test_missing_reconciliation_success_is_unhealthy() -> None:
    status, flags, reason = determine_crawler_health(
        redis_error=None,
        database_ok=True,
        executor_heartbeat_ttl=30,
        reconciliation_heartbeat_ttl=-2,
        expired_leases=0,
        pending_transport_cleanup=0,
    )

    assert status == "UNHEALTHY"
    assert "RECONCILIATION_HEARTBEAT_MISSING" in flags
    assert "reconciliation" in reason.lower()


def test_redis_failure_does_not_expose_internal_connection_details() -> None:
    status, flags, reason = determine_crawler_health(
        redis_error="redis.internal.example:6379 refused connection",
        database_ok=True,
        executor_heartbeat_ttl=-2,
        reconciliation_heartbeat_ttl=-2,
        expired_leases=0,
        pending_transport_cleanup=0,
    )

    assert status == "UNKNOWN"
    assert flags == ["REDIS_ERROR", "DB_QUERY_OK"]
    assert reason == "Redis transport health check failed"


def test_non_expiring_worker_heartbeat_degrades_health() -> None:
    status, flags, reason = determine_crawler_health(
        redis_error=None,
        database_ok=True,
        executor_heartbeat_ttl=-1,
        reconciliation_heartbeat_ttl=30,
        expired_leases=0,
        pending_transport_cleanup=0,
    )

    assert status == "DEGRADED"
    assert "EXECUTOR_HEARTBEAT_NO_TTL" in flags
    assert "no expiry" in reason
