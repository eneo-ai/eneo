import asyncio
import json
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, cast

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from eneo.allowed_origins.get_origin_callback import get_origin
from eneo.flows.ai_builder.ai_builder_router import (
    AIBuilderEnvelopedError,
    ai_builder_enveloped_error_handler,
)
from eneo.flows.runtime.flow_runtime_health import (
    FlowRuntimeHealthResponse,
    FlowRuntimeProbe,
    FlowRuntimeProbeFailure,
    build_flow_runtime_health_policy,
    classify_flow_runtime_health,
    flow_runtime_health_probe_failure_response,
    load_flow_runtime_health_snapshot,
)
from eneo.main.config import get_settings
from eneo.main.logging import get_logger
from eneo.main.observability import init_observability, instrument_fastapi
from eneo.scim.app import scim_app
from eneo.server import api_documentation
from eneo.server.dependencies.lifespan import lifespan as app_lifespan
from eneo.server.exception_handlers import (
    add_exception_handlers,
    extract_request_id,
    validation_error_response_content,
)
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
_GENERAL_ERROR_SCHEMA_REF = "#/components/schemas/GeneralError"
_HTTP_VALIDATION_ERROR_SCHEMA_REF = "#/components/schemas/HTTPValidationError"
_FASTAPI_VALIDATION_ERROR_SCHEMA_NAMES = frozenset(
    {"HTTPValidationError", "ValidationError"}
)


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


class HealthThresholds(BaseModel):
    """Thresholds used for status decisions - helps explain status."""

    feeder_interval_seconds: int
    watchdog_stale_threshold_seconds: float  # 3x feeder_interval
    heartbeat_ttl_expected_seconds: int  # health_check_interval (60s)


class CrawlerActivity(BaseModel):
    """Real-time crawler activity from multiple sources."""

    db_in_progress: Optional[int] = Field(
        default=None,  # Jobs with status=IN_PROGRESS, None if query failed
    )
    db_query_ok: bool = True  # False if DB query timed out or failed
    arq_ongoing: int = 0  # From ARQ health string (j_ongoing)
    delta: Optional[int] = Field(
        default=None,  # Discrepancy between DB and ARQ, None if can't compute
    )


class ARQHealth(BaseModel):
    """Parsed ARQ health metrics (clean view)."""

    heartbeat_ttl_seconds: Optional[int] = Field(default=None)
    age_seconds: Optional[float] = Field(default=None)
    j_complete: int = 0
    j_failed: int = 0
    j_retried: int = 0
    j_ongoing: int = 0
    queued: int = 0


class WatchdogMetrics(BaseModel):
    """Watchdog activity metrics."""

    age_seconds: Optional[float] = Field(default=None)
    zombies_reconciled: int = 0
    expired_killed: int = 0
    rescued: int = 0
    early_zombies_failed: int = 0
    long_running_failed: int = 0
    slots_released: int = 0


class FeederLeader(BaseModel):
    """Feeder leader election status."""

    leader_id: Optional[str] = Field(default=None)
    leader_ttl_seconds: Optional[int] = Field(default=None)
    status: str = "UNKNOWN"  # LEADER_OK, LEADER_STALE, NO_LEADER


class PendingQueueSummary(BaseModel):
    """Pending crawl queue summary."""

    total: int = 0
    tenant_count: int = 0
    top_tenants: dict[str, int] = Field(default_factory=dict)


class DebugInfo(BaseModel):
    """Raw data for debugging - noisy, not for quick reads."""

    arq_raw: str = ""
    arq_timestamp: Optional[str] = Field(default=None)
    watchdog_timestamp: Optional[str] = Field(default=None)
    redis_db: Optional[int] = Field(default=None)
    queue_name: str = "arq:queue"


class ArqHealthData(TypedDict, total=False):
    raw: str
    timestamp: str
    arq_health_age_seconds: float
    heartbeat_ttl_seconds: int
    age_seconds: float
    j_complete: int
    j_failed: int
    j_retried: int
    j_ongoing: int
    queued: int


class WatchdogMetricsData(TypedDict, total=False):
    timestamp: str
    zombies_reconciled: int
    expired_killed: int
    rescued: int
    early_zombies_failed: int
    long_running_failed: int
    slots_released: int


class _ArqHealthParser(Protocol):
    def parse_arq_health_string(self, raw: str) -> ArqHealthData: ...


class CrawlerHealthResponse(BaseModel):
    """Crawler health status with operator-friendly signals."""

    # Quick status overview
    status: str  # HEALTHY, DEGRADED, UNHEALTHY, or UNKNOWN
    status_flags: list[str] = Field(
        default_factory=list
    )  # ["ARQ_HEARTBEAT_OK", "WATCHDOG_OK", "DB_QUERY_OK"]
    status_reason: str = ""  # Human-readable explanation
    response_timestamp_utc: str  # For log correlation

    # Core metrics (clean view)
    crawler_activity: CrawlerActivity = Field(default_factory=CrawlerActivity)
    arq: ARQHealth = Field(default_factory=ARQHealth)
    watchdog: WatchdogMetrics = Field(default_factory=WatchdogMetrics)
    feeder: FeederLeader = Field(default_factory=FeederLeader)
    pending: PendingQueueSummary = Field(default_factory=PendingQueueSummary)

    # Configuration used for decisions
    thresholds: HealthThresholds

    # Raw data for deep debugging
    debug: DebugInfo = Field(default_factory=DebugInfo)


def _parse_arq_health_string(raw: str) -> ArqHealthData:
    from eneo.worker.redis import client as redis_client

    return cast(_ArqHealthParser, redis_client).parse_arq_health_string(raw)


def _parse_watchdog_metrics(raw: str) -> WatchdogMetricsData:
    return cast(WatchdogMetricsData, json.loads(raw))


def _json_obj(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


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


def _resolve_openapi_schema_ref(
    openapi_schema: dict[str, Any], schema: Any
) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}

    schema_obj = cast(dict[str, Any], schema)
    ref = schema_obj.get("$ref")
    if not isinstance(ref, str):
        return schema_obj

    prefix = "#/components/schemas/"
    if not ref.startswith(prefix):
        return {}

    component_name = ref.removeprefix(prefix)
    components = _json_obj(openapi_schema.get("components"))
    schemas = _json_obj(components.get("schemas"))
    return _json_obj(schemas.get(component_name))


def _normalize_multipart_upload_file_schemas(openapi_schema: dict[str, Any]) -> None:
    """Expose UploadFile fields in the shape most OpenAPI client generators expect."""
    paths = _json_obj(openapi_schema.get("paths"))

    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue
        path_operations = cast(dict[str, Any], path_item)
        for operation in path_operations.values():
            if not isinstance(operation, dict):
                continue

            operation_obj = cast(dict[str, Any], operation)
            request_body = _json_obj(operation_obj.get("requestBody"))
            content = _json_obj(request_body.get("content"))
            multipart = _json_obj(content.get("multipart/form-data"))
            request_schema = _resolve_openapi_schema_ref(
                openapi_schema, multipart.get("schema")
            )
            properties = _json_obj(request_schema.get("properties"))

            for property_schema in properties.values():
                if not isinstance(property_schema, dict):
                    continue
                property_schema_obj = cast(dict[str, Any], property_schema)
                if (
                    property_schema_obj.get("type") == "string"
                    and property_schema_obj.get("contentMediaType")
                    == "application/octet-stream"
                ):
                    property_schema_obj.pop("contentMediaType", None)
                    property_schema_obj["format"] = "binary"


def _retag_flow_ai_builder_operations(openapi_schema: dict[str, Any]) -> None:
    """Keep AI Builder operations grouped under their dedicated tag in OpenAPI.

    The runtime path stays nested under `/flows`, but from an API consumer perspective
    these operations read better as one workflow section instead of appearing under
    both `flows` and `ai-builder`.
    """
    paths = _json_obj(openapi_schema.get("paths"))

    for path, operations in paths.items():
        if not path.startswith("/api/v1/flows/ai-builder"):
            continue
        if not isinstance(operations, dict):
            continue
        for operation in _json_obj(operations).values():
            if isinstance(operation, dict):
                cast(dict[str, Any], operation)["tags"] = ["ai-builder"]


def _normalize_request_validation_error_responses(
    openapi_schema: dict[str, Any],
) -> None:
    paths = _json_obj(openapi_schema.get("paths"))

    for path, path_item in paths.items():
        if path.startswith("/scim/"):
            continue
        if not isinstance(path_item, dict):
            continue
        for operation in _json_obj(path_item).values():
            if not isinstance(operation, dict):
                continue
            operation_obj = _json_obj(operation)
            response = _json_obj(_json_obj(operation_obj.get("responses")).get("422"))
            content = _json_obj(response.get("content"))
            app_json = _json_obj(content.get("application/json"))
            schema = _json_obj(app_json.get("schema"))
            if schema.get("$ref") == _HTTP_VALIDATION_ERROR_SCHEMA_REF:
                app_json["schema"] = {"$ref": _GENERAL_ERROR_SCHEMA_REF}

    components = _json_obj(openapi_schema.get("components"))
    schemas = _json_obj(components.get("schemas"))
    removed_schemas: dict[str, Any] = {}
    for schema_name in _FASTAPI_VALIDATION_ERROR_SCHEMA_NAMES:
        removed_schema = schemas.pop(schema_name, None)
        if removed_schema is not None:
            removed_schemas[schema_name] = removed_schema

    openapi_json = json.dumps(openapi_schema)
    for schema_name, schema in removed_schemas.items():
        if f"#/components/schemas/{schema_name}" in openapi_json:
            schemas[schema_name] = schema


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

    # Add handlers of all errors except 500
    add_exception_handlers(app)

    # AI Builder errors carry a prepared envelope; the route adapter re-raises
    # them so the request transaction rolls back before this handler responds.
    app.add_exception_handler(
        AIBuilderEnvelopedError, ai_builder_enveloped_error_handler
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        detail = exc.detail
        headers = exc.headers or None

        if exc.status_code == 422:
            return JSONResponse(
                status_code=exc.status_code,
                content=validation_error_response_content(
                    request=request, detail=detail
                ),
                headers=headers,
            )

        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            normalized_detail: dict[str, Any] = cast(dict[str, Any], detail)
            request_id = extract_request_id(request)
            if request_id and "request_id" not in normalized_detail:
                normalized_detail["request_id"] = request_id
            return JSONResponse(
                status_code=exc.status_code, content=normalized_detail, headers=headers
            )

        return JSONResponse(
            status_code=exc.status_code, content={"detail": detail}, headers=headers
        )

    def custom_openapi() -> dict[str, Any]:
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
        components = _json_obj(openapi_schema.get("components"))
        security_schemes = _json_obj(components.get("securitySchemes"))
        if "default" in security_schemes:
            security_schemes["APIKeyAuth"] = security_schemes.pop("default")

        # Update all security references from "default" to "APIKeyAuth"
        for path in _json_obj(openapi_schema.get("paths")).values():
            for operation in _json_obj(path).values():
                if isinstance(operation, dict) and "security" in operation:
                    security = cast(list[dict[str, list[Any]]], operation["security"])
                    operation["security"] = [
                        {"APIKeyAuth" if k == "default" else k: v}
                        for sec in security
                        for k, v in sec.items()
                    ]

        # WSO2 compatibility: Remove invalid "NOT_PROVIDED" defaults from schemas
        schemas = _json_obj(components.get("schemas"))
        for schema in schemas.values():
            if isinstance(schema, dict):
                _remove_invalid_defaults(cast(dict[str, Any], schema))

        _normalize_multipart_upload_file_schemas(openapi_schema)
        _retag_flow_ai_builder_operations(openapi_schema)
        _normalize_request_validation_error_responses(openapi_schema)

        # Fix only the missing SSE-related schemas that FastAPI doesn't auto-detect
        components = _json_obj(openapi_schema.setdefault("components", {}))
        schemas = _json_obj(components.setdefault("schemas", {}))

        # Import SSE models and enums
        from eneo.flows.ai_builder.ai_builder_event_models import (
            AI_BUILDER_SCHEMA_HOIST_MODELS,
        )
        from eneo.sessions.session import SSE_MODELS, EneoEventType

        # Add EneoEventType enum if not already there
        if "EneoEventType" not in schemas:
            schemas["EneoEventType"] = {
                "type": "string",
                "enum": [item.value for item in EneoEventType],
            }

        # Add SSE model schemas, hoisting nested $defs to top-level component schemas
        # so that openapi-typescript can resolve all $ref pointers.
        for model in (*SSE_MODELS, *AI_BUILDER_SCHEMA_HOIST_MODELS):
            model_name = model.__name__
            if model_name not in schemas:
                schema = model.model_json_schema(
                    ref_template="#/components/schemas/{model}"
                )
                # Extract $defs and promote them to top-level schemas
                defs = schema.pop("$defs", {})
                for def_name, def_schema in defs.items():
                    if def_name not in schemas:
                        schemas[def_name] = def_schema
                schemas[model_name] = schema

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

    @app.get(
        "/api/healthz/flows",
        response_model=FlowRuntimeHealthResponse,
        description=(
            "Return Flow runtime readiness signals derived from persisted run, review, "
            "data-integrity, audit-outbox, and webhook-outbox state."
        ),
        responses={
            200: {
                "description": (
                    "Flow runtime health payload. Inspect the response status and flags "
                    "for healthy, degraded, unhealthy, or unknown runtime signals."
                )
            }
        },
    )
    async def flow_runtime_health() -> FlowRuntimeHealthResponse:
        from eneo.server.dependencies.container import Container

        settings = get_settings()
        policy = build_flow_runtime_health_policy(
            task_timeout_seconds=settings.flow_task_timeout_seconds
        )
        query_started_at = time.perf_counter()
        query_now = datetime.now(timezone.utc)

        async def _load_health_snapshot():
            async with Container.session_scope() as session:
                return await load_flow_runtime_health_snapshot(
                    session=session,
                    now=query_now,
                    policy=policy,
                )

        try:
            snapshot = await asyncio.wait_for(_load_health_snapshot(), timeout=2.0)
        except asyncio.TimeoutError:
            query_duration_ms = int((time.perf_counter() - query_started_at) * 1000)
            logger.warning("DB query timeout in flow runtime health check")
            return flow_runtime_health_probe_failure_response(
                now=query_now,
                policy=policy,
                query_duration_ms=query_duration_ms,
                failure=FlowRuntimeProbeFailure.TIMEOUT,
            )
        except Exception as exc:
            query_duration_ms = int((time.perf_counter() - query_started_at) * 1000)
            logger.warning(
                "DB query error in flow runtime health check",
                extra={"error": str(exc)},
            )
            return flow_runtime_health_probe_failure_response(
                now=query_now,
                policy=policy,
                query_duration_ms=query_duration_ms,
                failure=FlowRuntimeProbeFailure.ERROR,
            )

        query_duration_ms = int((time.perf_counter() - query_started_at) * 1000)
        return classify_flow_runtime_health(
            snapshot=snapshot,
            now=query_now,
            policy=policy,
            probe=FlowRuntimeProbe(
                db_query_ok=True,
                db_query_duration_ms=query_duration_ms,
            ),
        )

    @app.get(
        "/api/healthz/crawler",
        response_model=CrawlerHealthResponse,
        description="Get detailed crawler queue and worker diagnostics.",
        responses={200: {"description": "Crawler diagnostics"}},
    )
    async def crawler_health(include_all: bool = False) -> CrawlerHealthResponse:
        """Detailed crawler diagnostics. NOT for K8s probes.

        Public endpoint - no auth required. Shows only job counts and tenant IDs.

        Args:
            include_all: If True, return all tenant queue lengths instead of top-10.
        """
        from eneo.worker.redis.client import get_redis

        redis_client = cast(Any, get_redis())
        settings = get_settings()
        feeder_interval = settings.crawl_feeder_interval_seconds

        # Initialize defaults for graceful degradation on Redis errors
        arq_health: ArqHealthData = {}
        watchdog_metrics: WatchdogMetricsData = {}
        watchdog_age: float | None = None
        leader_id: str | None = None
        leader_ttl: int = -2
        pending_total: int = 0
        tenant_queues: dict[str, int] = {}
        redis_error: str | None = None

        # ARQ heartbeat TTL - timezone-independent liveness signal
        arq_heartbeat_ttl: int = -2

        try:
            # 1. Parse ARQ health with age (for debugging) + fetch TTL (for status)
            arq_raw = await redis_client.get("arq:queue:health-check") or ""
            if isinstance(arq_raw, bytes):
                arq_raw = arq_raw.decode()
            arq_health = _parse_arq_health_string(arq_raw)
            arq_heartbeat_ttl = await redis_client.ttl("arq:queue:health-check")

            # 2. Get watchdog metrics
            watchdog_raw = await redis_client.get("crawl_watchdog:last_metrics")
            if watchdog_raw:
                try:
                    if isinstance(watchdog_raw, bytes):
                        watchdog_raw = watchdog_raw.decode()
                    watchdog_metrics = _parse_watchdog_metrics(watchdog_raw)
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
                        length = int(await redis_client.llen(key))
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

            from eneo.database.tables.job_table import Jobs
            from eneo.jobs.job_models import Task
            from eneo.main.models import Status
            from eneo.server.dependencies.container import Container

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
        arq_ongoing = int(arq_health.get("j_ongoing", 0))
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
        queued_jobs = int(arq_health.get("queued", 0))
        if queued_jobs > 0 and arq_ongoing == 0:
            status_flags.append("WORKER_STUCK")
            status_reasons.append(f"Jobs queued ({queued_jobs}) but none processing")

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
        redis_db = cast(int | None, getattr(settings, "redis_db", None))

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
                zombies_reconciled=int(watchdog_metrics.get("zombies_reconciled", 0)),
                expired_killed=int(watchdog_metrics.get("expired_killed", 0)),
                rescued=int(watchdog_metrics.get("rescued", 0)),
                early_zombies_failed=int(
                    watchdog_metrics.get("early_zombies_failed", 0)
                ),
                long_running_failed=int(watchdog_metrics.get("long_running_failed", 0)),
                slots_released=int(watchdog_metrics.get("slots_released", 0)),
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
        get_healthz,
        flow_runtime_health,
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
