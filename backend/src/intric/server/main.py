import uvicorn
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastmcp import FastMCP

from intric.allowed_origins.get_origin_callback import get_origin
from intric.authentication import auth_dependencies
from intric.main.config import get_settings
from intric.main.logging import get_logger
from intric.server import api_documentation
from intric.server.dependencies.lifespan import lifespan as app_lifespan
from intric.server.exception_handlers import add_exception_handlers
from intric.server.middleware.cors import CORSMiddleware
from intric.server.middleware.request_context import RequestContextMiddleware
from intric.server.models.api import VersionResponse
from intric.server.routers import router as api_router

logger = get_logger(__name__)

mcp = FastMCP("mcp proxy")

@mcp.tool
def add_two_numbers(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

config = {
    "mcpServers": {
        "math": {
            "url": "http://host.docker.internal:8080/mcp",
            "transport": "sse"
        },
    }
}

# Create MCP ASGI app
# Set path to match where it will be accessed
mcp_app = mcp.http_app(path="/mcp", transport="streamable-http")



# Combine both lifecycles
@asynccontextmanager
async def combined_lifespan(app: FastAPI):
    async with app_lifespan(app):
        async with mcp_app.lifespan(app):
            yield


def get_application():
    app = FastAPI(
        lifespan=combined_lifespan,
    )

    @app.middleware("http")
    async def log_mcp_requests(request, call_next):
        if "/mcp" in request.url.path:
            logger.info(f"MCP request: {request.method} {request.url.path}")
            logger.info(f"Headers: {dict(request.headers)}")
        response = await call_next(request)
        if "/mcp" in request.url.path:
            logger.info(f"MCP response status: {response.status_code}")
        return response

    app.add_middleware(RequestContextMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],  # Expose all headers including session-related ones
        callback=get_origin,
    )

    # Mount MCP before including API router to avoid conflicts
    app.mount(get_settings().api_prefix, mcp_app)

    app.include_router(api_router, prefix=get_settings().api_prefix)

    # Add handlers of all errors except 500
    add_exception_handlers(app)

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
                "enum": [item.value for item in IntricEventType]
            }

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi

    @app.exception_handler(500)
    async def custom_http_500_exception_handler(request, exc):
        # CORS Headers are not set on an internal server error. This is confusing, and hard to debug.
        # Solving this like this response:
        #   https://github.com/tiangolo/fastapi/issues/775#issuecomment-723628299
        response = JSONResponse(status_code=500, content={
                                "error": "Something went wrong"})

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
            elif not cors.allow_all_origins and await cors.is_allowed_origin(origin=origin):
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
                    "details": "Backend API server operational"
                },
                "worker": {
                    "status": worker_health.status,
                    "last_heartbeat": worker_health.last_heartbeat,
                    "details": worker_health.details
                }
            }
        }

        if status_code == 503:
            raise HTTPException(status_code=503, detail=response_data["detail"])

        return response_data

    @app.get("/version", dependencies=[Depends(auth_dependencies.get_current_active_user)])
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
        reload_dirs="./src/"
    )
