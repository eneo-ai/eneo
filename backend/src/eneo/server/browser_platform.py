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

from eneo.main.config import get_settings
from eneo.server.middleware.api_response_headers import ApiResponseHeadersMiddleware
from eneo.server.middleware.compression import SelectiveGZipMiddleware
from eneo.server.runtime_config_router import log_unlinked_runtime_values
from eneo.server.runtime_config_router import router as runtime_config_router


def install_browser_platform(app: FastAPI) -> None:
    settings = get_settings()
    app.include_router(runtime_config_router, prefix=settings.api_prefix)
    if settings.browser_session_enabled or settings.web_app_enabled:
        log_unlinked_runtime_values(settings)

    app.add_middleware(ApiResponseHeadersMiddleware, hsts=not settings.is_development)
    # Added last, so it is outermost: it compresses the final headers and body.
    app.add_middleware(SelectiveGZipMiddleware)
