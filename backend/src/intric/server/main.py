import uvicorn
from fastapi import Depends, FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from intric.allowed_origins.get_origin_callback import get_origin
from intric.authentication import auth_dependencies
from intric.main.config import SETTINGS
from intric.main.logging import get_logger
from intric.server import api_documentation
from intric.server.dependencies.lifespan import lifespan
from intric.server.exception_handlers import add_exception_handlers
from intric.server.middleware.cors import CORSMiddleware
from intric.server.models.api import VersionResponse
from intric.server.routers import router as api_router
from intric.server.websockets.websocket_models import WS_MODELS
from intric.sessions.session import SSE_MODELS

logger = get_logger(__name__)


def get_application():
    app = FastAPI(
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        callback=get_origin,
    )

    app.include_router(api_router, prefix=SETTINGS.api_prefix)

    # Add handlers of all errors except 500
    add_exception_handlers(app)

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title=api_documentation.TITLE,
            version=SETTINGS.app_version,
            summary=api_documentation.SUMMARY,
            tags=api_documentation.TAGS_METADATA,
            routes=app.routes,
        )

        # Adding websocket models to the schema
        for model in WS_MODELS + SSE_MODELS:
            openapi_schema["components"]["schemas"][model.__name__] = model.model_json_schema(
                ref_template=f"#/components/schemas/{model.__name__}/$defs/{{model}}"
            )

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi

    return app


app = get_application()


@app.exception_handler(500)
async def custom_http_500_exception_handler(request, exc):
    # CORS Headers are not set on an internal server error. This is confusing, and hard to debug.
    # Solving this like this response:
    #   https://github.com/tiangolo/fastapi/issues/775#issuecomment-723628299
    response = JSONResponse(status_code=500, content={"error": "Something went wrong"})

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

@app.get("/healthz")
async def get_healthz():
    return "OK"

@app.get("/version", dependencies=[Depends(auth_dependencies.get_current_active_user)])
async def get_version():
    return VersionResponse(version=SETTINGS.app_version)


def start():
    uvicorn.run(
        "intric.server.main:app",
        host="0.0.0.0",
        port=8123,
        reload=True,
        reload_dirs="./src/",
    )
