"""Self-hosted interactive API documentation; API admission stays with Eneo."""

from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from starlette.responses import FileResponse, HTMLResponse

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)

_ASSETS = Path(__file__).with_name("swagger_ui")
_PUBLIC_FILES = {
    "swagger-ui-bundle.js": "text/javascript",
    "swagger-ui.css": "text/css",
    "eneo-swagger-initializer.js": "text/javascript",
    "LICENSE": "text/plain",
    "NOTICE": "text/plain",
    "swagger-ui-bundle.js.LICENSE.txt": "text/plain",
}
_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "Content-Security-Policy": "; ".join(
        (
            "default-src 'none'",
            "script-src 'self'",
            "style-src 'self'",
            "style-src-attr 'unsafe-inline'",
            "img-src 'self' data:",
            "font-src 'self'",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        )
    ),
}
_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Eneo API</title>
  <link rel="stylesheet" href="/docs/assets/swagger-ui.css">
  <script src="/docs/assets/swagger-ui-bundle.js" defer></script>
  <script src="/docs/assets/eneo-swagger-initializer.js" defer></script>
</head>
<body><main id="swagger-ui" aria-label="Eneo API documentation"></main></body>
</html>
"""

router = APIRouter()


@router.get(
    "/docs",
    include_in_schema=False,
    response_class=HTMLResponse,
    response_model=None,
    description="Serve the locally packaged Swagger UI document.",
    responses={200: {"description": "Interactive API documentation."}},
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Self-hosted viewer of the already published API specification.",
)
async def interactive_api_docs() -> HTMLResponse:
    return HTMLResponse(_HTML, headers=_HEADERS)


@router.get(
    "/docs/assets/{filename}",
    include_in_schema=False,
    response_model=None,
    description="Serve an allowlisted, locally packaged API documentation asset.",
    responses={
        200: {"description": "Packaged documentation asset."},
        404: {"description": "Filename is not a published documentation asset."},
    },
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Fixed, locally packaged assets for interactive API documentation.",
)
async def api_docs_asset(filename: str) -> FileResponse:
    media_type = _PUBLIC_FILES.get(filename)
    if media_type is None:
        raise HTTPException(status_code=404)
    return FileResponse(_ASSETS / filename, media_type=media_type, headers=_HEADERS)


def install_api_docs(app: FastAPI) -> None:
    # A framework-generated /docs would precede our router and load a CDN.
    if app.docs_url is not None:
        raise ValueError("Disable FastAPI docs_url before installing local API docs")
    if app.openapi_url != "/openapi.json":
        raise ValueError("Local API docs require the published /openapi.json contract")
    app.include_router(router)
