import asyncio
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, cast

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from eneo.allowed_origins.get_origin_callback import get_origin
from eneo.internal_mcp import internal_mcp_mounts
from eneo.main.config import get_settings
from eneo.main.logging import get_logger
from eneo.main.observability import init_observability, instrument_fastapi
from eneo.main.request_context import get_request_context
from eneo.object_content.runtime import (
    ObjectContentReadinessCode,
    object_content_runtime,
)
from eneo.scim.app import scim_app
from eneo.server import api_documentation
from eneo.server.dependencies.lifespan import lifespan as app_lifespan
from eneo.server.exception_handlers import add_exception_handlers
from eneo.server.middleware.cors import CORSMiddleware
from eneo.server.middleware.request_context import RequestContextMiddleware
from eneo.server.middleware.trace_id import (
    TraceIdResponseMiddleware,
    current_trace_id,
)
from eneo.server.models.api import VersionResponse
from eneo.server.routers import router as api_router

logger = get_logger(__name__)

# Single source of truth for trace headers exposed to cross-origin callers.
# Used in both the normal CORSMiddleware config and the manual CORS block in
# 500 error handlers so they stay in sync.
_TRACE_EXPOSE_HEADERS = ("X-Trace-Id", "X-Correlation-ID")


# Initialise OTEL before the FastAPI app is created so that SQLAlchemy,
# Redis, and aiohttp auto-instrumentation is active before those
# engines/pools are created during lifespan startup.
init_observability()


def _log_api_key_security_overrides() -> None:
    settings = get_settings()

    if not settings.api_key_enforce_resource_permissions:
        logger.critical(
            "API key resource permission enforcement is disabled by configuration"
        )
    if settings.api_key_rate_limit_fail_open:
        logger.warning(
            "API key rate limiting is configured fail-open; requests may bypass limits when Redis is unavailable"
        )


# Pydantic models for /api/healthz/crawler endpoint


class CrawlerTransportHealth(BaseModel):
    """Dedicated queue depth and liveness of both crawler worker roles."""

    reconciliation_heartbeat_ttl_seconds: int | None = None
    executor_heartbeat_ttl_seconds: int | None = None
    queued: int | None = None


class CrawlLifecycleHealth(BaseModel):
    """Authoritative active crawl state from PostgreSQL."""

    database_ok: bool = True
    pending_dispatch: int | None = None
    queued: int | None = None
    running: int | None = None
    finalizing: int | None = None
    stopping: int | None = None
    active_total: int | None = None
    expired_leases: int | None = None
    pending_transport_cleanup: int | None = None
    oldest_active_age_seconds: int | None = None


class CrawlerCapacityHealth(BaseModel):
    """Configured cluster-wide crawl admission capacity."""

    max_concurrent_crawl_jobs: int


class CrawlerHealthDebugInfo(BaseModel):
    """Queue names and Redis database used by the health snapshot."""

    redis_db: int | None = None
    dispatcher_queue_name: str
    executor_queue_name: str


CrawlerHealthStatus = Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN"]


class CrawlerHealthResponse(BaseModel):
    """Crawler health status with operator-friendly signals."""

    status: CrawlerHealthStatus
    status_flags: list[str] = Field(default_factory=list)
    status_reason: str = ""
    response_timestamp_utc: str
    lifecycle: CrawlLifecycleHealth = Field(default_factory=CrawlLifecycleHealth)
    transport: CrawlerTransportHealth = Field(default_factory=CrawlerTransportHealth)
    capacity: CrawlerCapacityHealth
    debug: CrawlerHealthDebugInfo


def determine_crawler_health(
    *,
    redis_error: str | None,
    database_ok: bool,
    executor_heartbeat_ttl: int,
    reconciliation_heartbeat_ttl: int,
    expired_leases: int | None,
    pending_transport_cleanup: int | None,
) -> tuple[CrawlerHealthStatus, list[str], str]:
    """Classify health from the two real crawler stores."""
    flags: list[str] = []
    reasons: list[str] = []

    if redis_error is not None:
        flags.append("REDIS_ERROR")
        # The endpoint is intentionally unauthenticated. Keep connection details
        # in the server log instead of exposing internal hostnames to callers.
        reasons.append("Redis transport health check failed")
    else:
        for role, heartbeat_ttl in (
            ("EXECUTOR", executor_heartbeat_ttl),
            ("RECONCILIATION", reconciliation_heartbeat_ttl),
        ):
            role_name = role.lower()
            if heartbeat_ttl == -2:
                flags.append(f"{role}_HEARTBEAT_MISSING")
                reasons.append(f"Crawler {role_name} heartbeat not found in Redis")
            elif heartbeat_ttl == -1:
                flags.append(f"{role}_HEARTBEAT_NO_TTL")
                reasons.append(f"Crawler {role_name} heartbeat has no expiry")
            elif heartbeat_ttl <= 0:
                flags.append(f"{role}_HEARTBEAT_EXPIRED")
                reasons.append(f"Crawler {role_name} heartbeat expired")
            else:
                flags.append(f"{role}_HEARTBEAT_OK")

    if database_ok:
        flags.append("DB_QUERY_OK")
    else:
        flags.append("DB_QUERY_ERROR")
        reasons.append("PostgreSQL lifecycle query failed")

    if expired_leases:
        flags.append("EXPIRED_LEASES")
        reasons.append(f"{expired_leases} crawl execution lease(s) expired")

    if pending_transport_cleanup:
        flags.append("TRANSPORT_CLEANUP_PENDING")
        reasons.append(
            f"{pending_transport_cleanup} expired crawl delivery cleanup(s) pending"
        )

    if redis_error is not None or not database_ok:
        status = "UNKNOWN"
    elif executor_heartbeat_ttl in {-2, 0} or reconciliation_heartbeat_ttl in {-2, 0}:
        status = "UNHEALTHY"
    elif (
        executor_heartbeat_ttl < 0
        or reconciliation_heartbeat_ttl < 0
        or expired_leases
        or pending_transport_cleanup
    ):
        status = "DEGRADED"
    else:
        status = "HEALTHY"
        reasons.append("Crawler workers and PostgreSQL lifecycle are healthy")

    return status, flags, "; ".join(reasons)


def _remove_invalid_defaults(schema: dict[str, Any]) -> None:
    """Remove invalid 'NOT_PROVIDED' defaults from OpenAPI schema recursively."""
    if schema.get("default") == "NOT_PROVIDED":
        del schema["default"]

    properties = schema.get("properties")
    if isinstance(properties, dict):
        for prop_schema in cast(dict[str, dict[str, Any]], properties).values():
            _remove_invalid_defaults(prop_schema)

    items = schema.get("items")
    if isinstance(items, dict):
        _remove_invalid_defaults(cast(dict[str, Any], items))

    additional_properties = schema.get("additionalProperties")
    if isinstance(additional_properties, dict):
        _remove_invalid_defaults(cast(dict[str, Any], additional_properties))

    for key in ("anyOf", "oneOf", "allOf"):
        variants = schema.get(key)
        if isinstance(variants, list):
            for sub_schema in cast(list[dict[str, Any]], variants):
                _remove_invalid_defaults(sub_schema)


def get_application():
    app = FastAPI(
        lifespan=app_lifespan,
    )

    _log_api_key_security_overrides()

    app.add_middleware(RequestContextMiddleware)

    # TraceIdResponseMiddleware injects X-Trace-Id at the ASGI send level.
    # It must sit inside the OTEL middleware (added before instrument_fastapi)
    # so the server span is guaranteed active when http.response.start fires.
    app.add_middleware(TraceIdResponseMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=list(_TRACE_EXPOSE_HEADERS),
        callback=get_origin,
    )

    # OTEL middleware must be outermost so the span is active when inner
    # middlewares run. instrument_fastapi adds it last.
    instrument_fastapi(app)

    app.include_router(api_router, prefix=get_settings().api_prefix)
    app.mount("/scim/v2", scim_app)
    # Loopback internal-MCP servers (knowledge search, attachment reading;
    # their session managers are driven by the parent lifespan in
    # dependencies/lifespan.py).
    for mount_path, internal_mcp_app in internal_mcp_mounts():
        app.mount(mount_path, internal_mcp_app)

    # Add handlers of all errors except 500
    add_exception_handlers(app)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        detail = exc.detail
        headers = exc.headers or None
        request_id = request.headers.get("x-correlation-id") or request.headers.get(
            "x-request-id"
        )
        if not request_id:
            request_id = cast(str | None, get_request_context().get("correlation_id"))

        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            normalized_detail: dict[str, Any] = cast(dict[str, Any], detail)
            if request_id and "request_id" not in normalized_detail:
                normalized_detail["request_id"] = request_id
            return JSONResponse(
                status_code=exc.status_code, content=normalized_detail, headers=headers
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
        for path in cast(dict[str, Any], openapi_schema.get("paths", {})).values():
            for operation in cast(dict[str, Any], path).values():
                if isinstance(operation, dict) and "security" in operation:
                    security = cast(list[dict[str, list[Any]]], operation["security"])
                    operation["security"] = [
                        {"APIKeyAuth" if k == "default" else k: v}
                        for sec in security
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

        # Import SSE models and enums
        from eneo.sessions.session import SSE_MODELS, EneoEventType

        # Add EneoEventType enum if not already there
        if "EneoEventType" not in openapi_schema["components"]["schemas"]:
            openapi_schema["components"]["schemas"]["EneoEventType"] = {
                "type": "string",
                "enum": [item.value for item in EneoEventType],
            }

        # Add SSE model schemas, hoisting nested $defs to top-level component schemas
        # so that openapi-typescript can resolve all $ref pointers.
        for model in SSE_MODELS:
            model_name = model.__name__
            if model_name not in openapi_schema["components"]["schemas"]:
                schema = model.model_json_schema(
                    ref_template="#/components/schemas/{model}"
                )
                # Extract $defs and promote them to top-level schemas
                defs = schema.pop("$defs", {})
                for def_name, def_schema in defs.items():
                    if def_name not in openapi_schema["components"]["schemas"]:
                        openapi_schema["components"]["schemas"][def_name] = def_schema
                openapi_schema["components"]["schemas"][model_name] = schema

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi

    @app.exception_handler(500)
    async def custom_http_500_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
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

        error_content: dict[str, Any] = {
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

        # Attach trace_id so the client can correlate the error with backend logs
        trace_id = current_trace_id()
        if trace_id:
            response.headers["X-Trace-Id"] = trace_id
            response.headers["X-Correlation-ID"] = trace_id

        origin = request.headers.get("origin")

        if origin:
            # Have the middleware do the heavy lifting for us to parse
            # all the config, then update our response headers
            cors = CORSMiddleware(
                app=app,
                allow_origins=[],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
                expose_headers=list(_TRACE_EXPOSE_HEADERS),
                callback=get_origin,
            )

            # Logic directly from Starlette's CORSMiddleware:
            # https://github.com/encode/starlette/blob/master/starlette/middleware/cors.py#L152

            response.headers.update(cors.simple_headers)

            if cors.allow_all_origins and cors.allow_credentials:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers.add_vary_header("Origin")
            elif not cors.allow_all_origins and await cors.is_allowed_origin(
                origin=origin
            ):
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers.add_vary_header("Origin")

        return response

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
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

        error_content: dict[str, Any] = {
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

        # Attach trace_id so the client can correlate the error with backend logs
        trace_id = current_trace_id()
        if trace_id:
            response.headers["X-Trace-Id"] = trace_id
            response.headers["X-Correlation-ID"] = trace_id

        origin = request.headers.get("origin")

        if origin:
            cors = CORSMiddleware(
                app=app,
                allow_origins=[],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
                expose_headers=list(_TRACE_EXPOSE_HEADERS),
                callback=get_origin,
            )
            response.headers.update(cors.simple_headers)

            if cors.allow_all_origins and cors.allow_credentials:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers.add_vary_header("Origin")
            elif not cors.allow_all_origins and await cors.is_allowed_origin(
                origin=origin
            ):
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers.add_vary_header("Origin")

        return response

    @app.get(
        "/api/livez",
        include_in_schema=False,
        description="Report that the API process can serve requests.",
        responses={200: {"description": "API process is alive"}},
        response_model=None,
    )
    async def get_livez():
        return {"detail": {"status": "HEALTHY"}}

    @app.get(
        "/api/healthz",
        description="Report backend and worker health for deployment probes.",
        responses={
            200: {"description": "Backend and worker are healthy"},
            503: {"description": "Worker health check failed"},
        },
        response_model=None,
    )
    async def get_healthz():
        from datetime import datetime, timezone

        from fastapi import HTTPException

        from eneo.worker.redis import get_worker_health

        # Get worker health status
        worker_health = await get_worker_health()
        object_content = await object_content_runtime.readiness()

        # Backend is always healthy if we can respond
        backend_status = "HEALTHY"
        backend_timestamp = datetime.now(timezone.utc).isoformat()

        # Determine overall system health
        if (
            worker_health.status == "HEALTHY"
            and backend_status == "HEALTHY"
            and object_content.ready
        ):
            overall_status = (
                "DEGRADED"
                if object_content.code is ObjectContentReadinessCode.STORE_DEGRADED
                else "HEALTHY"
            )
            status_code = 200
        else:
            overall_status = "UNHEALTHY"
            status_code = 503

        if (
            object_content.code
            is ObjectContentReadinessCode.OBJECT_STORE_NOT_CONFIGURED
        ):
            object_content_status = "NOT_CONFIGURED"
        elif object_content.code is ObjectContentReadinessCode.STORE_DEGRADED:
            object_content_status = "DEGRADED"
        elif object_content.ready:
            object_content_status = "HEALTHY"
        else:
            object_content_status = "UNHEALTHY"

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
                "object_content": {
                    "status": object_content_status,
                    "code": object_content.code.value,
                },
            }
        }

        if status_code == 503:
            raise HTTPException(status_code=503, detail=response_data["detail"])

        return response_data

    @app.get(
        "/api/readyz",
        include_in_schema=False,
        description="Report readiness of the API and required dependencies.",
        responses={
            200: {"description": "API and required dependencies are ready"},
            503: {"description": "A required dependency is unavailable"},
        },
        response_model=None,
    )
    async def get_readyz():
        return await get_healthz()

    @app.get(
        "/api/healthz/crawler",
        response_model=CrawlerHealthResponse,
        description="Get detailed crawler queue and worker diagnostics.",
        responses={200: {"description": "Crawler diagnostics"}},
    )
    async def crawler_health() -> CrawlerHealthResponse:
        """Report aggregate transport and PostgreSQL lifecycle health."""
        from eneo.jobs.job_manager import CRAWLER_QUEUE_NAME, DEFAULT_QUEUE_NAME
        from eneo.worker.redis.client import (
            CRAWL_RECONCILIATION_HEALTH_KEY,
            get_redis,
        )

        redis_client = cast(Any, get_redis())
        settings = get_settings()
        redis_error: str | None = None
        executor_heartbeat_ttl = -2
        reconciliation_heartbeat_ttl = -2
        queued: int | None = None

        try:
            executor_heartbeat_ttl = await redis_client.ttl(
                f"{CRAWLER_QUEUE_NAME}:health-check"
            )
            reconciliation_heartbeat_ttl = await redis_client.ttl(
                CRAWL_RECONCILIATION_HEALTH_KEY
            )
            queued = int(await redis_client.zcard(CRAWLER_QUEUE_NAME))
        except Exception as e:
            redis_error = str(e)
            logger.warning(
                "Redis error in crawler health check",
                extra={"error": redis_error},
            )

        from eneo.websites.domain.crawl_run_repo import (
            CrawlLifecycleSnapshot,
            CrawlRunRepository,
        )

        snapshot: CrawlLifecycleSnapshot | None = None
        db_query_error = False

        async def _query_db_lifecycle() -> CrawlLifecycleSnapshot:
            from eneo.server.dependencies.container import Container

            async with Container.session_scope() as session:
                return await CrawlRunRepository(session).health_snapshot()

        try:
            snapshot = await asyncio.wait_for(_query_db_lifecycle(), timeout=2.0)
        except asyncio.TimeoutError:
            db_query_error = True
            logger.warning("DB query timeout in crawler health check")
        except Exception as e:
            db_query_error = True
            logger.warning(
                "DB query error in crawler health check",
                extra={"error": str(e)},
            )

        status, status_flags, status_reason = determine_crawler_health(
            redis_error=redis_error,
            database_ok=not db_query_error,
            executor_heartbeat_ttl=executor_heartbeat_ttl,
            reconciliation_heartbeat_ttl=reconciliation_heartbeat_ttl,
            expired_leases=snapshot.expired_leases if snapshot else None,
            pending_transport_cleanup=(
                snapshot.pending_transport_cleanup if snapshot else None
            ),
        )

        redis_db = cast(int | None, getattr(settings, "redis_db", None))

        return CrawlerHealthResponse(
            status=status,
            status_flags=status_flags,
            status_reason=status_reason,
            response_timestamp_utc=datetime.now(timezone.utc).isoformat(),
            lifecycle=CrawlLifecycleHealth(
                database_ok=not db_query_error,
                pending_dispatch=snapshot.pending_dispatch if snapshot else None,
                queued=snapshot.queued if snapshot else None,
                running=snapshot.running if snapshot else None,
                finalizing=snapshot.finalizing if snapshot else None,
                stopping=snapshot.stopping if snapshot else None,
                active_total=snapshot.active_total if snapshot else None,
                expired_leases=snapshot.expired_leases if snapshot else None,
                pending_transport_cleanup=(
                    snapshot.pending_transport_cleanup if snapshot else None
                ),
                oldest_active_age_seconds=(
                    snapshot.oldest_active_age_seconds if snapshot else None
                ),
            ),
            transport=CrawlerTransportHealth(
                reconciliation_heartbeat_ttl_seconds=reconciliation_heartbeat_ttl
                if reconciliation_heartbeat_ttl > 0
                else None,
                executor_heartbeat_ttl_seconds=executor_heartbeat_ttl
                if executor_heartbeat_ttl > 0
                else None,
                queued=queued,
            ),
            capacity=CrawlerCapacityHealth(
                max_concurrent_crawl_jobs=(
                    settings.effective_crawl_job_concurrency_limit
                ),
            ),
            debug=CrawlerHealthDebugInfo(
                redis_db=redis_db,
                dispatcher_queue_name=DEFAULT_QUEUE_NAME,
                executor_queue_name=CRAWLER_QUEUE_NAME,
            ),
        )

    @app.get(
        "/version",
        description="Get the running backend version.",
        responses={200: {"description": "Backend version"}},
        response_model=None,
    )
    async def get_version():
        return VersionResponse(version=get_settings().app_version)

    _registered_endpoints = (
        http_exception_handler,
        custom_http_500_exception_handler,
        unhandled_exception_handler,
        get_livez,
        get_healthz,
        get_readyz,
        crawler_health,
        get_version,
    )
    del _registered_endpoints

    return app


app = get_application()


def start():
    uvicorn.run(
        "eneo.server.main:app",
        host="0.0.0.0",
        port=8123,
        reload=True,
        reload_dirs="./src/",
    )
