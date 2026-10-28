"""The single owner of browser-facing wiring on the FastAPI app.

``install_browser_platform(app)`` runs once from ``get_application()``, before
route validation. Later browser-platform work (gzip, the browser session, SSO
callbacks, runtime config, serving the web app) extends this function, so
``server/main.py`` keeps exactly one hook.

Middleware added here is outermost on purpose (outside OTEL and CORS): every
response, including CORS preflights, passes through it last.
"""

from fastapi import FastAPI

from eneo.main.config import get_settings
from eneo.server.middleware.api_response_headers import ApiResponseHeadersMiddleware


def install_browser_platform(app: FastAPI) -> None:
    app.add_middleware(
        ApiResponseHeadersMiddleware, hsts=not get_settings().is_development
    )
