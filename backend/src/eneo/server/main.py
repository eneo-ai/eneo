import asyncio
import json
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, cast

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from eneo.allowed_origins.get_origin_callback import get_origin
from eneo.authentication.auth import authenticate_super_api_key
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
    require_endpoint_access,
)
from eneo.data_retention.infrastructure.gallring_tasks import (
    disabled_gallring_tasks,
    enabled_gallring_tasks,
)
from eneo.flow_packages.api.flow_package_models import (
    FLOW_PACKAGE_OMITTED_MCP_ASSISTANT_COUNT_HEADER,
)
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
from eneo.internal_mcp import internal_mcp_mounts
from eneo.main.config import get_settings
from eneo.main.exceptions import ErrorCodes
from eneo.main.logging import get_logger
from eneo.main.models import GeneralError
from eneo.main.observability import init_observability, instrument_fastapi
from eneo.object_content.runtime import (
    ObjectContentReadinessCode,
    object_content_runtime,
)
from eneo.scim.app import scim_app
from eneo.server import api_documentation
from eneo.server.dependencies.lifespan import lifespan as app_lifespan
from eneo.server.endpoint_routes import (
    declare_framework_documentation_access,
    validate_endpoint_access,
)
from eneo.server.exception_handlers import (
    add_exception_handlers,
    default_error_code_for_status,
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
from eneo.tasks.health import load_task_worker_readiness

logger = get_logger(__name__)

# Used in normal middleware and manual error responses so browser clients see
# the same public response headers on every path.
_CORS_EXPOSE_HEADERS = (
    "X-Trace-Id",
    "X-Correlation-ID",
    FLOW_PACKAGE_OMITTED_MCP_ASSISTANT_COUNT_HEADER,
)
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
        reasons.append(f"{pending_transport_cleanup} crawl delivery cleanup(s) pending")

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


def _schema_allows_null(schema: dict[str, Any]) -> bool:
    if schema.get("type") == "null":
        return True
    options: list[Any] = cast(
        list[Any], schema.get("anyOf") or schema.get("oneOf") or []
    )
    return any(
        isinstance(option, dict) and cast(dict[str, Any], option).get("type") == "null"
        for option in options
    )


def _object_schema(
    openapi_schema: dict[str, Any], schema: Any, depth: int = 0
) -> dict[str, Any]:
    """The object schema behind a reference or an unambiguous composition.

    A composition with more than one object option (a discriminated union)
    is left alone: which option an example belongs to is not knowable from
    the schema, and a wrong guess would add keys the right option forbids.
    """
    resolved = _resolve_openapi_schema_ref(openapi_schema, schema)
    if "properties" in resolved:
        return resolved
    if depth > 8:
        return {}
    for key in ("allOf", "anyOf", "oneOf"):
        candidates = [
            candidate
            for candidate in (
                _object_schema(openapi_schema, option, depth + 1)
                for option in cast(list[Any], resolved.get(key) or [])
            )
            if candidate
        ]
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            return {}
    return {}


def _restore_example_nulls(
    openapi_schema: dict[str, Any], schema: Any, example: Any, depth: int = 0
) -> None:
    if depth > 16:
        return
    if isinstance(example, list):
        resolved = _resolve_openapi_schema_ref(openapi_schema, schema)
        for item in cast(list[Any], example):
            _restore_example_nulls(
                openapi_schema, resolved.get("items"), item, depth + 1
            )
        return
    if not isinstance(example, dict):
        return
    example_obj = cast(dict[str, Any], example)
    object_schema = _object_schema(openapi_schema, schema)
    properties = _json_obj(object_schema.get("properties"))
    for name in cast(list[Any], object_schema.get("required") or []):
        if name in example_obj or not isinstance(name, str):
            continue
        property_schema = _json_obj(properties.get(name))
        if _schema_allows_null(property_schema):
            example_obj[name] = None
    for name, value in example_obj.items():
        if name in properties:
            _restore_example_nulls(openapi_schema, properties[name], value, depth + 1)


def _restore_stripped_example_nulls(openapi_schema: dict[str, Any]) -> None:
    """Put back the nulls FastAPI drops from declared examples.

    `fastapi.openapi.utils.get_openapi` encodes the whole document with
    `exclude_none=True`, so a `None` in a model or route example vanishes
    together with its key. A required nullable property then looks absent and
    the example no longer matches the schema it documents. Restoring `null`
    for exactly those keys keeps the response contract strict (the field stays
    required) and the example honest.
    """
    components = _json_obj(openapi_schema.get("components"))
    for schema in _json_obj(components.get("schemas")).values():
        if not isinstance(schema, dict):
            continue
        schema_obj = cast(dict[str, Any], schema)
        if "example" in schema_obj:
            _restore_example_nulls(openapi_schema, schema_obj, schema_obj["example"])
        for example in cast(list[Any], schema_obj.get("examples") or []):
            _restore_example_nulls(openapi_schema, schema_obj, example)

    for path_item in _json_obj(openapi_schema.get("paths")).values():
        for operation in _json_obj(path_item).values():
            if not isinstance(operation, dict):
                continue
            operation_obj = cast(dict[str, Any], operation)
            contents: list[dict[str, Any]] = [
                _json_obj(_json_obj(operation_obj.get("requestBody")).get("content"))
            ]
            for response in _json_obj(operation_obj.get("responses")).values():
                contents.append(_json_obj(_json_obj(response).get("content")))
            for content in contents:
                for media_object in content.values():
                    if not isinstance(media_object, dict):
                        continue
                    media = cast(dict[str, Any], media_object)
                    schema = media.get("schema")
                    if "example" in media:
                        _restore_example_nulls(openapi_schema, schema, media["example"])
                    for named in _json_obj(media.get("examples")).values():
                        named_obj = _json_obj(named)
                        if "value" in named_obj:
                            _restore_example_nulls(
                                openapi_schema, schema, named_obj["value"]
                            )


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
        dependencies=[Depends(require_endpoint_access)],
    )
    declare_framework_documentation_access(app)

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
        expose_headers=list(_CORS_EXPOSE_HEADERS),
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

        if exc.status_code == 500:
            return await _internal_server_error_response(request, exc)

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
            # Every raiser of this shape means it as the documented error, but
            # each built the dict by hand and most left the required numeric
            # category out. Fill it here, where the dict becomes the body, so a
            # direct `raise HTTPException` cannot bypass the contract.
            if "eneo_error_code" not in normalized_detail:
                normalized_detail["eneo_error_code"] = default_error_code_for_status(
                    exc.status_code
                ).value
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
                        {
                            "APIKeyAuth" if k == "default" else k: v
                            for k, v in sec.items()
                        }
                        for sec in security
                    ]

        # WSO2 compatibility: Remove invalid "NOT_PROVIDED" defaults from schemas
        schemas = _json_obj(components.get("schemas"))
        for schema in schemas.values():
            if isinstance(schema, dict):
                _remove_invalid_defaults(cast(dict[str, Any], schema))

        _normalize_multipart_upload_file_schemas(openapi_schema)
        _retag_flow_ai_builder_operations(openapi_schema)
        _normalize_request_validation_error_responses(openapi_schema)
        _restore_stripped_example_nulls(openapi_schema)

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
    @app.exception_handler(Exception)
    async def _internal_server_error_response(
        request: Request, exc: Exception
    ) -> JSONResponse:
        error_id = str(uuid.uuid4())[:8]
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
        response = JSONResponse(
            status_code=500,
            content=GeneralError(
                message=(
                    "An unexpected error occurred. Please try again or contact support "
                    "with the error_id."
                ),
                eneo_error_code=ErrorCodes.INTERNAL_SERVER_ERROR,
                code="internal_error",
                request_id=extract_request_id(request),
                error_id=error_id,
            ).model_dump(mode="json", exclude_none=True),
        )

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
                expose_headers=list(_CORS_EXPOSE_HEADERS),
                callback=get_origin,
            )
            response.headers.update(cors.simple_headers)

            if cors.allow_all_origins and cors.allow_credentials:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers.add_vary_header("Origin")
            elif not cors.allow_all_origins and await cors.is_allowed_origin(
                origin=origin, request_headers=request.headers, request_url=request.url
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
    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason="Deployment health probes and version discovery are intentionally public.",
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
    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason="Deployment health probes and version discovery are intentionally public.",
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
        "/api/healthz/flows",
        response_model=FlowRuntimeHealthResponse,
        dependencies=[Security(authenticate_super_api_key)],
        description=(
            "Return super-key-protected Flow runtime readiness signals derived from "
            "persisted run, review, data-integrity, audit-outbox, webhook-outbox, "
            "gallring job, and platform task worker readiness. GALLRING_JOB_STALE "
            "(UNHEALTHY) means an enabled nightly gallring task has not completed "
            "within twice its daily cadence; GALLRING_DISABLED (UNHEALTHY) means the "
            "deployment's emergency switch turned a gallring task off."
        ),
        responses={
            200: {
                "description": (
                    "Flow runtime health payload. Inspect the response status and flags "
                    "for healthy, degraded, unhealthy, or unknown runtime signals."
                )
            },
            401: {"description": "Missing or invalid Eneo super API key."},
        },
    )
    @endpoint_access(
        authentication=Authentication.SYSADMIN,
        authorization=Authorization.SYSADMIN,
        reason="Flow runtime diagnostics require deployment administrator access.",
    )
    async def flow_runtime_health() -> FlowRuntimeHealthResponse:
        from eneo.server.dependencies.container import Container

        settings = get_settings()
        policy = build_flow_runtime_health_policy(
            task_timeout_seconds=settings.task_execution_timeout_seconds,
            gallring_tasks=enabled_gallring_tasks(settings),
            gallring_disabled_tasks=disabled_gallring_tasks(settings),
        )
        worker_readiness = await load_task_worker_readiness(timeout_seconds=1.0)
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
                execution_worker_ready=worker_readiness.execution_ready,
                maintenance_worker_ready=worker_readiness.maintenance_ready,
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
                execution_worker_ready=worker_readiness.execution_ready,
                maintenance_worker_ready=worker_readiness.maintenance_ready,
            )

        query_duration_ms = int((time.perf_counter() - query_started_at) * 1000)
        return classify_flow_runtime_health(
            snapshot=snapshot,
            now=query_now,
            policy=policy,
            probe=FlowRuntimeProbe(
                db_query_ok=True,
                db_query_duration_ms=query_duration_ms,
                execution_worker_ready=worker_readiness.execution_ready,
                maintenance_worker_ready=worker_readiness.maintenance_ready,
            ),
        )

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
    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason="Deployment health probes and version discovery are intentionally public.",
    )
    async def get_readyz():
        return await get_healthz()

    @app.get(
        "/api/healthz/crawler",
        dependencies=[Security(authenticate_super_api_key)],
        response_model=CrawlerHealthResponse,
        description="Get detailed crawler queue and worker diagnostics.",
        responses={
            200: {"description": "Crawler diagnostics"},
            401: {
                "model": GeneralError,
                "description": "Missing or invalid super API key",
            },
        },
    )
    @endpoint_access(
        authentication=Authentication.SYSADMIN,
        authorization=Authorization.SYSADMIN,
        reason="Crawler diagnostics require deployment administrator access.",
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
    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason="Deployment health probes and version discovery are intentionally public.",
    )
    async def get_version():
        return VersionResponse(version=get_settings().app_version)

    _registered_endpoints = (
        http_exception_handler,
        _internal_server_error_response,
        get_livez,
        get_healthz,
        flow_runtime_health,
        get_readyz,
        crawler_health,
        get_version,
    )
    del _registered_endpoints

    validate_endpoint_access(app)
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
