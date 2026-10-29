"""The single owner of browser-facing wiring on the FastAPI app.

``install_browser_platform(app)`` runs once from ``get_application()``, before
route validation. Later browser-platform work (gzip, the browser session, SSO
callbacks, runtime config, serving the web app) extends this function, so
``server/main.py`` keeps exactly one hook.

Middleware added here is the outermost user middleware (outside CORS, so CORS
preflights pass through it too). OTEL and Starlette's ServerErrorMiddleware
still wrap the whole user stack, so unhandled-exception 500s do not get it.
"""

from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from eneo.authentication.browser_session_router import (
    callback_router,
)
from eneo.authentication.browser_session_router import (
    router as browser_session_router,
)
from eneo.main.config import get_settings
from eneo.server.middleware.compression import SelectiveGZipMiddleware
from eneo.server.middleware.response_headers import ResponseHeadersMiddleware
from eneo.server.runtime_config_router import log_unlinked_runtime_values
from eneo.server.runtime_config_router import router as runtime_config_router
from eneo.server.web_app import install_web_app

# FastAPI's and SCIM's interactive documentation; the openapi.json files stay.
_DOCUMENTATION_PAGES = frozenset(
    {
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/scim/v2/docs",
        "/scim/v2/docs/oauth2-redirect",
        "/scim/v2/redoc",
    }
)


class _DocumentationOff:
    """404 for the documentation pages.

    They load unpinned CDN scripts without SRI. On the host that holds the
    browser session, such a script would run with the signed-in user's session.
    Middleware, not route removal: the SCIM app is a module singleton, so
    removing its routes would leak into every other app instance.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] in _DOCUMENTATION_PAGES:
            await JSONResponse({"detail": "Not Found"}, 404)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def install_browser_platform(app: FastAPI) -> None:
    settings = get_settings()
    app.include_router(runtime_config_router, prefix=settings.api_prefix)
    app.include_router(browser_session_router, prefix=settings.api_prefix)
    app.include_router(callback_router)
    browser_platform_on = settings.browser_session_enabled or settings.web_app_enabled
    if browser_platform_on:
        log_unlinked_runtime_values(settings)

    if browser_platform_on and not settings.is_development:
        app.add_middleware(_DocumentationOff)
    app.add_middleware(
        ResponseHeadersMiddleware,
        hsts=not settings.is_development,
        web_app=settings.web_app_enabled,
    )
    # Added last, so it is outermost: it compresses the final headers and body.
    app.add_middleware(SelectiveGZipMiddleware)
    install_web_app(app)
