import asyncio
import json
import time
import traceback
import uuid
import uvicorn
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from intric.allowed_origins.get_origin_callback import get_origin
from intric.main.config import get_settings
from intric.main.logging import get_logger
from intric.server import api_documentation
from intric.server.dependencies.lifespan import lifespan
from intric.server.exception_handlers import add_exception_handlers
from intric.server.middleware.cors import CORSMiddleware
from intric.server.middleware.request_context import RequestContextMiddleware
from intric.server.models.api import VersionResponse
from intric.server.routers import router as api_router

logger = get_logger(__name__)


# Pydantic models for /api/healthz/crawler endpoint


class HealthThresholds(BaseModel):
    """Thresholds used for status decisions - helps explain status."""

    feeder_interval_seconds: int
    watchdog_stale_threshold_seconds: float  # 3x feeder_interval
    heartbeat_ttl_expected_seconds: int  # health_check_interval (60s)


class CrawlerActivity(BaseModel):
    """Real-time crawler activity from multiple sources."""

    db_in_progress: Optional[int] = (
        None  # Jobs with status=IN_PROGRESS, None if query failed
    )
    db_query_ok: bool = True  # False if DB query timed out or failed
    arq_ongoing: int = 0  # From ARQ health string (j_ongoing)
    delta: Optional[int] = None  # Discrepancy between DB and ARQ, None if can't compute


class ARQHealth(BaseModel):
    """Parsed ARQ health metrics (clean view)."""

    heartbeat_ttl_seconds: Optional[int] = None  # TTL-based liveness signal
    age_seconds: Optional[float] = None  # For debugging only, not used for status
    j_complete: int = 0
    j_failed: int = 0
    j_retried: int = 0
    j_ongoing: int = 0
    queued: int = 0


class WatchdogMetrics(BaseModel):
    """Watchdog activity metrics."""

    age_seconds: Optional[float] = None
    zombies_reconciled: int = 0
    expired_killed: int = 0
    rescued: int = 0
    early_zombies_failed: int = 0
    long_running_failed: int = 0
    slots_released: int = 0


class FeederLeader(BaseModel):
    """Feeder leader election status."""

    leader_id: Optional[str] = None
    leader_ttl_seconds: Optional[int] = None
    status: str = "UNKNOWN"  # LEADER_OK, LEADER_STALE, NO_LEADER


class PendingQueueSummary(BaseModel):
    """Pending crawl queue summary."""

    total: int = 0
    tenant_count: int = 0
    top_tenants: dict[str, int] = {}


class DebugInfo(BaseModel):
    """Raw data for debugging - noisy, not for quick reads."""

    arq_raw: str = ""
    arq_timestamp: Optional[str] = None
    watchdog_timestamp: Optional[str] = None
    redis_db: Optional[int] = None
    queue_name: str = "arq:queue"


class CrawlerHealthResponse(BaseModel):
    """Crawler health status with operator-friendly signals."""

    # Quick status overview
    status: str  # HEALTHY, DEGRADED, UNHEALTHY, or UNKNOWN
    status_flags: list[str] = []  # ["ARQ_HEARTBEAT_OK", "WATCHDOG_OK", "DB_QUERY_OK"]
    status_reason: str = ""  # Human-readable explanation
    response_timestamp_utc: str  # For log correlation

    # Core metrics (clean view)
    crawler_activity: CrawlerActivity = CrawlerActivity()
    arq: ARQHealth = ARQHealth()
    watchdog: WatchdogMetrics = WatchdogMetrics()
    feeder: FeederLeader = FeederLeader()
    pending: PendingQueueSummary = PendingQueueSummary()

    # Configuration used for decisions
    thresholds: HealthThresholds

    # Raw data for deep debugging
    debug: DebugInfo = DebugInfo()


def _remove_invalid_defaults(schema: dict) -> None:
    """Remove invalid 'NOT_PROVIDED' defaults from OpenAPI schema recursively."""
    if not isinstance(schema, dict):
        return

    if schema.get("default") == "NOT_PROVIDED":
        del schema["default"]

    if "properties" in schema and isinstance(schema["properties"], dict):
        for prop_schema in schema["properties"].values():
            _remove_invalid_defaults(prop_schema)

    if "items" in schema and isinstance(schema["items"], dict):
        _remove_invalid_defaults(schema["items"])

    if "additionalProperties" in schema and isinstance(
        schema["additionalProperties"], dict
    ):
        _remove_invalid_defaults(schema["additionalProperties"])

    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema and isinstance(schema[key], list):
            for sub_schema in schema[key]:
                _remove_invalid_defaults(sub_schema)


def get_application():
    app = FastAPI(
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        callback=get_origin,
    )

    app.include_router(api_router, prefix=get_settings().api_prefix)

    # Add handlers of all errors except 500
    add_exception_handlers(app)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc: HTTPException):
        detail = exc.detail
        headers = exc.headers or None
        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            return JSONResponse(
                status_code=exc.status_code, content=detail, headers=headers
            )
        return JSONResponse(
            status_code=exc.status_code, content={"detail": detail}, headers=headers
        )

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title=api_documentation.TITLE,
            version=get_settings().app_version,
            description=api_documentation.SUMMARY,
            tags=api_documentation.TAGS_METADATA,
            routes=app.routes,
        )

        # WSO2 compatibility: Rename "default" security scheme to "APIKeyAuth"
        # WSO2 API Manager treats "default" as a reserved keyword expecting a boolean
        if (
            "components" in openapi_schema
            and "securitySchemes" in openapi_schema["components"]
        ):
            schemes = openapi_schema["components"]["securitySchemes"]
            if "default" in schemes:
                schemes["APIKeyAuth"] = schemes.pop("default")

        # Update all security references from "default" to "APIKeyAuth"
        for path in openapi_schema.get("paths", {}).values():
            for operation in path.values():
                if isinstance(operation, dict) and "security" in operation:
                    operation["security"] = [
                        {"APIKeyAuth" if k == "default" else k: v}
                        for sec in operation["security"]
                        for k, v in sec.items()
                    ]

        # WSO2 compatibility: Remove invalid "NOT_PROVIDED" defaults from schemas
        if "components" in openapi_schema and "schemas" in openapi_schema["components"]:
            for schema in openapi_schema["components"]["schemas"].values():
                _remove_invalid_defaults(schema)

        # Fix only the missing SSE-related schemas that FastAPI doesn't auto-detect
        if "components" not in openapi_schema:
            openapi_schema["components"] = {}
        if "schemas" not in openapi_schema["components"]:
            openapi_schema["components"]["schemas"] = {}

        # Import the actual IntricEventType enum
        from intric.sessions.session import IntricEventType

        # Add the missing schema if it's not already there
        if "IntricEventType" not in openapi_schema["components"]["schemas"]:
            openapi_schema["components"]["schemas"]["IntricEventType"] = {
                "type": "string",
                "enum": [item.value for item in IntricEventType],
            }

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi

    @app.exception_handler(500)
    async def custom_http_500_exception_handler(request, exc):
        # Generate unique error ID for tracing
        error_id = str(uuid.uuid4())[:8]

        # Log the full exception with traceback
        logger.error(
            f"Internal Server Error [error_id={error_id}]",
            extra={
                "error_id": error_id,
                "path": request.url.path,
                "method": request.method,
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )

        # Build error response
        settings = get_settings()
        is_dev = settings.environment in ("development", "local", "dev")

        error_content = {
            "error": "Internal server error",
            "error_id": error_id,
            "message": "An unexpected error occurred. Please try again or contact support with the error_id.",
        }

        # In development mode, include more details
        if is_dev:
            error_content["detail"] = {
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "path": request.url.path,
                "method": request.method,
            }

        # CORS Headers are not set on an internal server error. This is confusing, and hard to debug.
        # Solving this like this response:
        #   https://github.com/tiangolo/fastapi/issues/775#issuecomment-723628299
        response = JSONResponse(status_code=500, content=error_content)

        origin = request.headers.get("origin")

        if origin:
            # Have the middleware do the heavy lifting for us to parse
            # all the config, then update our response headers
            cors = CORSMiddleware(
                app=app,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
                callback=get_origin,
            )

            # Logic directly from Starlette's CORSMiddleware:
            # https://github.com/encode/starlette/blob/master/starlette/middleware/cors.py#L152

            response.headers.update(cors.simple_headers)
            has_cookie = "cookie" in request.headers

            # If request includes any cookie headers, then we must respond
            # with the specific origin instead of '*'.
            if cors.allow_all_origins and has_cookie:
                response.headers["Access-Control-Allow-Origin"] = origin

            # If we only allow specific origins, then we have to mirror back
            # the Origin header in the response.
            elif not cors.allow_all_origins and await cors.is_allowed_origin(
                origin=origin
            ):
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers.add_vary_header("Origin")

        return response

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request, exc):
        """Catch-all handler for unhandled exceptions"""
        # Generate unique error ID for tracing
        error_id = str(uuid.uuid4())[:8]

        # Log the full exception with traceback
        logger.error(
            f"Unhandled Exception [error_id={error_id}]",
            extra={
                "error_id": error_id,
                "path": request.url.path,
                "method": request.method,
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )

        # Build error response
        settings = get_settings()
        is_dev = settings.environment in ("development", "local", "dev")

        error_content = {
            "error": "Internal server error",
            "error_id": error_id,
            "message": "An unexpected error occurred. Please try again or contact support with the error_id.",
        }

        # In development mode, include more details
        if is_dev:
            error_content["detail"] = {
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "path": request.url.path,
                "method": request.method,
            }

        response = JSONResponse(status_code=500, content=error_content)

        origin = request.headers.get("origin")

        if origin:
            cors = CORSMiddleware(
                app=app,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
                callback=get_origin,
            )
            response.headers.update(cors.simple_headers)
            has_cookie = "cookie" in request.headers
            if cors.allow_all_origins and has_cookie:
                response.headers["Access-Control-Allow-Origin"] = origin
            elif not cors.allow_all_origins and await cors.is_allowed_origin(
                origin=origin
            ):
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers.add_vary_header("Origin")

        return response

    @app.get("/api/healthz")
    async def get_healthz():
        from intric.worker.redis import get_worker_health
        from datetime import datetime, timezone
        from fastapi import HTTPException

        # Get worker health status
        worker_health = await get_worker_health()

        # Backend is always healthy if we can respond
        backend_status = "HEALTHY"
        backend_timestamp = datetime.now(timezone.utc).isoformat()

        # Determine overall system health
        if worker_health.status == "HEALTHY" and backend_status == "HEALTHY":
            overall_status = "HEALTHY"
            status_code = 200
        else:
            overall_status = "UNHEALTHY"
            status_code = 503

        # Assemble health response
        response_data = {
            "detail": {
                "status": overall_status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "backend": {
                    "status": backend_status,
                    "last_heartbeat": backend_timestamp,
                    "details": "Backend API server operational",
                },
                "worker": {
                    "status": worker_health.status,
                    "last_heartbeat": worker_health.last_heartbeat,
                    "details": worker_health.details,
                },
            }
        }

        if status_code == 503:
            raise HTTPException(status_code=503, detail=response_data["detail"])

        return response_data

    @app.get("/api/healthz/crawler", response_model=CrawlerHealthResponse)
    async def crawler_health(include_all: bool = False):
        """Detailed crawler diagnostics. NOT for K8s probes.

        Public endpoint - no auth required. Shows only job counts and tenant IDs.

        Args:
            include_all: If True, return all tenant queue lengths instead of top-10.
        """
        from intric.worker.redis.client import get_redis, parse_arq_health_string

        redis_client = get_redis()
        settings = get_settings()
        feeder_interval = settings.crawl_feeder_interval_seconds

        # Initialize defaults for graceful degradation on Redis errors
        arq_health: dict = {}
        watchdog_metrics: dict = {}
        watchdog_age: float | None = None
        leader_id: str | None = None
        leader_ttl: int = -2
        pending_total = 0
        tenant_queues: dict[str, int] = {}
        redis_error: str | None = None

        # ARQ heartbeat TTL - timezone-independent liveness signal
        arq_heartbeat_ttl: int = -2

        try:
            # 1. Parse ARQ health with age (for debugging) + fetch TTL (for status)
            arq_raw = await redis_client.get("arq:queue:health-check") or ""
            if isinstance(arq_raw, bytes):
                arq_raw = arq_raw.decode()
            arq_health = parse_arq_health_string(arq_raw)
            arq_heartbeat_ttl = await redis_client.ttl("arq:queue:health-check")

            # 2. Get watchdog metrics
            watchdog_raw = await redis_client.get("crawl_watchdog:last_metrics")
            if watchdog_raw:
                try:
                    if isinstance(watchdog_raw, bytes):
                        watchdog_raw = watchdog_raw.decode()
                    watchdog_metrics = json.loads(watchdog_raw)
                except json.JSONDecodeError:
                    pass

            # 3. Get watchdog age
            last_success = await redis_client.get("crawl_watchdog:last_success_epoch")
            if last_success:
                try:
                    if isinstance(last_success, bytes):
                        last_success = last_success.decode()
                    watchdog_age = time.time() - float(last_success)
                except (ValueError, TypeError):
                    pass

            # 4. Get feeder leader info
            leader_id = await redis_client.get("crawl_feeder:leader")
            leader_ttl = await redis_client.ttl("crawl_feeder:leader")
            if isinstance(leader_id, bytes):
                leader_id = leader_id.decode()

            # 5. SCAN for pending queues (aggregate totals + top-N)
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(
                    cursor=cursor, match="tenant:*:crawl_pending", count=100
                )
                for key in keys:
                    key_str = key.decode() if isinstance(key, bytes) else key
                    parts = key_str.split(":")
                    if len(parts) >= 2:
                        tenant_id = parts[1]
                        length = await redis_client.llen(key)
                        pending_total += length
                        tenant_queues[tenant_id] = length
                if cursor == 0:
                    break

        except Exception as e:
            # Redis connection error - return UNKNOWN status with error info
            redis_error = str(e)
            logger.warning(
                "Redis error in crawler health check",
                extra={"error": redis_error},
            )

        # Top N tenants (default 10)
        sorted_tenants = sorted(tenant_queues.items(), key=lambda x: x[1], reverse=True)
        top_tenants = dict(sorted_tenants if include_all else sorted_tenants[:10])

        # 6. Query DB for in-progress crawl jobs (with timeout guard)
        db_in_progress: int | None = None
        db_query_error = False

        async def _query_db_crawl_count():
            from sqlalchemy import func, select
            from intric.database.tables.job_table import Jobs
            from intric.jobs.job_models import Task
            from intric.main.models import Status
            from intric.server.dependencies.container import Container

            async with Container.session_scope() as session:
                return await session.scalar(
                    select(func.count())
                    .select_from(Jobs)
                    .where(
                        Jobs.task == Task.CRAWL.value,
                        Jobs.status == Status.IN_PROGRESS.value,
                    )
                )

        try:
            # 2 second timeout to keep endpoint responsive
            db_in_progress = await asyncio.wait_for(
                _query_db_crawl_count(), timeout=2.0
            )
        except asyncio.TimeoutError:
            db_query_error = True
            logger.warning("DB query timeout in crawler health check")
        except Exception as e:
            db_query_error = True
            logger.warning(
                "DB query error in crawler health check",
                extra={"error": str(e)},
            )

        # Calculate delta if both values available
        arq_ongoing = arq_health.get("j_ongoing", 0)
        activity_delta: int | None = None
        if db_in_progress is not None:
            activity_delta = abs(db_in_progress - arq_ongoing)

        # 7. Build status flags and determine overall status
        # TTL values: -2 = key missing, -1 = no expiry (suspicious), >0 = seconds remaining
        status_flags: list[str] = []
        status_reasons: list[str] = []
        watchdog_stale_threshold = 3 * feeder_interval

        # Check ARQ heartbeat
        if redis_error:
            status_flags.append("REDIS_ERROR")
            status_reasons.append(f"Redis connection failed: {redis_error}")
        elif arq_heartbeat_ttl == -2:
            status_flags.append("ARQ_HEARTBEAT_MISSING")
            status_reasons.append("Worker heartbeat key not found in Redis")
        elif arq_heartbeat_ttl == -1:
            status_flags.append("ARQ_HEARTBEAT_NO_TTL")
            status_reasons.append(
                "Worker heartbeat key has no expiry (misconfiguration)"
            )
        elif arq_heartbeat_ttl == 0:
            status_flags.append("ARQ_HEARTBEAT_EXPIRED")
            status_reasons.append("Worker heartbeat key about to expire")
        elif arq_heartbeat_ttl > 0:
            status_flags.append("ARQ_HEARTBEAT_OK")

        # Check watchdog
        if watchdog_age is None:
            status_flags.append("WATCHDOG_UNKNOWN")
            status_reasons.append("Watchdog status unknown (no timestamp)")
        elif watchdog_age > watchdog_stale_threshold:
            status_flags.append("WATCHDOG_STALE")
            status_reasons.append(
                f"Watchdog stale ({watchdog_age:.0f}s > {watchdog_stale_threshold:.0f}s threshold)"
            )
        else:
            status_flags.append("WATCHDOG_OK")

        # Check DB query
        if db_query_error:
            status_flags.append("DB_QUERY_ERROR")
            status_reasons.append("Database query failed or timed out")
        else:
            status_flags.append("DB_QUERY_OK")

        # Check for stuck worker (queued but not processing)
        if arq_health.get("queued", 0) > 0 and arq_ongoing == 0:
            status_flags.append("WORKER_STUCK")
            status_reasons.append(
                f"Jobs queued ({arq_health.get('queued', 0)}) but none processing"
            )

        # Check activity delta
        if activity_delta is not None and activity_delta > 0:
            status_flags.append(f"ACTIVITY_DELTA_{activity_delta}")

        # Determine feeder leader status
        if leader_id is None:
            feeder_status = "NO_LEADER"
        elif leader_ttl <= 0:
            feeder_status = "LEADER_STALE"
        elif leader_ttl < feeder_interval:
            feeder_status = "LEADER_EXPIRING"
        else:
            feeder_status = "LEADER_OK"

        # Determine overall status based on flags
        if "REDIS_ERROR" in status_flags:
            status = "UNKNOWN"
        elif any(
            f in status_flags
            for f in [
                "ARQ_HEARTBEAT_MISSING",
                "ARQ_HEARTBEAT_EXPIRED",
                "WATCHDOG_STALE",
            ]
        ):
            status = "UNHEALTHY"
        elif any(
            f in status_flags
            for f in ["ARQ_HEARTBEAT_NO_TTL", "WORKER_STUCK", "DB_QUERY_ERROR"]
        ):
            status = "DEGRADED"
        else:
            status = "HEALTHY"
            if not status_reasons:
                status_reasons.append("All signals healthy")
                if activity_delta == 0:
                    status_reasons.append("crawler activity consistent (delta=0)")

        # Build status reason string
        status_reason = (
            "; ".join(status_reasons) if status_reasons else "All signals healthy"
        )

        # Get redis_db for debug info
        redis_db = getattr(settings, "redis_db", None)

        return CrawlerHealthResponse(
            status=status,
            status_flags=status_flags,
            status_reason=status_reason,
            response_timestamp_utc=datetime.now(timezone.utc).isoformat(),
            crawler_activity=CrawlerActivity(
                db_in_progress=db_in_progress,
                db_query_ok=not db_query_error,
                arq_ongoing=arq_ongoing,
                delta=activity_delta,
            ),
            arq=ARQHealth(
                heartbeat_ttl_seconds=arq_heartbeat_ttl
                if arq_heartbeat_ttl > 0
                else None,
                age_seconds=arq_health.get("arq_health_age_seconds"),
                j_complete=arq_health.get("j_complete", 0),
                j_failed=arq_health.get("j_failed", 0),
                j_retried=arq_health.get("j_retried", 0),
                j_ongoing=arq_ongoing,
                queued=arq_health.get("queued", 0),
            ),
            watchdog=WatchdogMetrics(
                age_seconds=watchdog_age,
                zombies_reconciled=watchdog_metrics.get("zombies_reconciled", 0),
                expired_killed=watchdog_metrics.get("expired_killed", 0),
                rescued=watchdog_metrics.get("rescued", 0),
                early_zombies_failed=watchdog_metrics.get("early_zombies_failed", 0),
                long_running_failed=watchdog_metrics.get("long_running_failed", 0),
                slots_released=watchdog_metrics.get("slots_released", 0),
            ),
            feeder=FeederLeader(
                leader_id=leader_id,
                leader_ttl_seconds=leader_ttl if leader_ttl > 0 else None,
                status=feeder_status,
            ),
            pending=PendingQueueSummary(
                total=pending_total,
                tenant_count=len(tenant_queues),
                top_tenants=top_tenants,
            ),
            thresholds=HealthThresholds(
                feeder_interval_seconds=feeder_interval,
                watchdog_stale_threshold_seconds=watchdog_stale_threshold,
                heartbeat_ttl_expected_seconds=60,  # health_check_interval
            ),
            debug=DebugInfo(
                arq_raw=arq_health.get("raw", ""),
                arq_timestamp=arq_health.get("timestamp"),
                watchdog_timestamp=watchdog_metrics.get("timestamp"),
                redis_db=redis_db,
                queue_name="arq:queue",
            ),
        )

    @app.get("/version")
    async def get_version():
        return VersionResponse(version=get_settings().app_version)

    return app


app = get_application()


def start():
    uvicorn.run(
        "intric.server.main:app",
        host="0.0.0.0",
        port=8123,
        reload=True,
        reload_dirs="./src/",
    )
