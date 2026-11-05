"""Serve the web app (the web-next Vite build) from FastAPI.

With ``WEB_APP_ENABLED`` on, the router's default handler serves the build. It
runs only when no route matched and no slash redirect applied, so the API keeps
its 307 and 405 answers (``Mount("/")`` would take both over):

- a reserved prefix, or the MCP content host, gets the API's JSON 404;
- a path with a file extension is a build file: hashed ``/assets/`` are
  immutable, other files revalidate, a missing one is not stored.
  ``index.html`` is never served raw;
- legacy pages and English-prefixed URLs redirect to their canonical pages;
- any other GET or HEAD gets ``index.html`` with a fresh nonce, its CSP and
  ``<html lang>``, never stored.

``/healthz`` answers like ``/api/healthz``, for monitoring on the web host.

The other browser headers come from the one default-header owner
(``middleware/response_headers.py``); headers set here win over them.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Sequence
from pathlib import Path, PurePath, PurePosixPath
from urllib.parse import quote, quote_from_bytes

from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.main.config import get_settings, serialize_origin
from eneo.mcp_apps.presentation.mcp_apps_router import on_content_origin
from eneo.server.web_app_legacy import legacy_page_target
from eneo.widgets.presentation.widget_web import EmbedPolicy, install_widget_web

# Where the backend image puts `vite build` output (P4-build-pipeline-1).
WEB_APP_DIST = Path("/app/web-dist")

# The placeholder contract with index.html and vite.config.mts (html.cspNonce).
_NONCE = "__ENEO_CSP_NONCE__"
_LANG = "__ENEO_HTML_LANG__"
_PLACEHOLDER = re.compile(f"{_NONCE}|{_LANG}")

# Reserved and retired paths get JSON 404 on a miss, never app HTML.
_RESERVED = (
    "/api",
    "/scim",
    "/internal-mcp",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/version",
    "/admin/audit-logs/export",
    "/widget",
)

# Module hand-off URLs carry state and redirect_uri: no Referer, no indexing.
_MODULE_LOGIN_HEADERS = {
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
}
_PATH_HEADERS = {
    "/module-login": _MODULE_LOGIN_HEADERS,
    "/module-login/failed": _MODULE_LOGIN_HEADERS,
}

_IMMUTABLE = "public, max-age=31536000, immutable"
# A build file missing now may exist after the next release swap.
_NOT_STORED = {"Cache-Control": "no-store"}


def build_content_security_policy(nonce: str, frame_origins: Sequence[str]) -> str:
    """The production policy for the backend-served React app."""
    return "; ".join(
        (
            "default-src 'self'",
            f"script-src 'self' 'nonce-{nonce}' 'strict-dynamic'",
            f"style-src 'self' 'nonce-{nonce}'",
            "style-src-attr 'unsafe-inline'",
            "img-src 'self' blob: data:",
            "font-src 'self' data:",
            "media-src 'self' blob: data:",
            # File previews are framed from in-memory blobs; MCP app views
            # come from their own content origin.
            " ".join(("frame-src 'self' blob:", *frame_origins)),
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            # Blob documents inherit this policy: the PDF viewer needs 'self'.
            "frame-ancestors 'self'",
            "script-src-attr 'none'",
            "upgrade-insecure-requests",
        )
    )


def _is_reserved(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in _RESERVED)


def _redirect_location(path: str, query: bytes) -> str:
    # The ASGI path is decoded; its ?/# are path data, not new delimiters.
    location = quote(path, safe="/")
    if query:
        location += "?" + quote_from_bytes(query, safe="!$&'()*+,-./:;=?@_%~[]")
    return location


def _is_local_redirect_path(path: str) -> bool:
    # Browser dot-segment normalization must not change a reserved-path decision.
    return (
        path.startswith("/")
        and not path.startswith("//")
        and not any(part in (".", "..") for part in path.split("/"))
        and not any(
            char == "\\" or ord(char) < 32 or 127 <= ord(char) <= 159 for char in path
        )
    )


_LOCALE_COOKIE = "eneo_locale"
# This app's earlier name for the preference: adopted once, then cleared.
_RETIRED_LOCALE_COOKIE = "NEXT_LOCALE"
# The SvelteKit app's preference, kept because that app still reads it.
_LEGACY_LOCALE_COOKIE = "PARAGLIDE_LOCALE"


def _set_locale_cookie(response: Response, locale: str, *, secure: bool) -> None:
    response.set_cookie(
        _LOCALE_COOKIE,
        locale,
        max_age=31536000,
        path="/",
        secure=secure,
        samesite="lax",
    )


def _read_index(dist: Path) -> str:
    index = dist / "index.html"
    try:
        template = index.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise RuntimeError(f"WEB_APP_ENABLED is on, but {index} is missing") from None
    missing = [name for name in (_NONCE, _LANG) if name not in template]
    if missing:
        raise RuntimeError(f"{index} lacks the placeholders {', '.join(missing)}")
    return template


def _alias_healthz(app: FastAPI) -> None:
    """``/healthz`` for monitoring on the web host: the same endpoint, and so
    the same access policy, as ``/api/healthz``."""
    route = next(
        (
            route
            for route in app.router.routes
            if isinstance(route, APIRoute) and route.path == "/api/healthz"
        ),
        None,
    )
    if route is None:
        raise RuntimeError("The /healthz alias needs the /api/healthz route")
    app.add_api_route(
        "/healthz",
        route.endpoint,
        methods=["GET", "HEAD"],
        include_in_schema=False,
        response_model=None,
        description=route.description,
        responses=route.responses,
    )


def install_web_app(app: FastAPI) -> None:
    settings = get_settings()
    if not settings.web_app_enabled:
        if settings.is_development:
            # Vite serves the development document; FastAPI still owns the
            # public loader assets and settings proxied from that origin.
            install_widget_web(app)
        return

    # Read once, at startup: a missing or wrong build fails loud here.
    template = _read_index(WEB_APP_DIST)
    static = StaticFiles(directory=WEB_APP_DIST)
    content_base = settings.mcp_app_content_base_url
    content_origin = serialize_origin(content_base) if content_base else None
    frame_origins = (content_origin,) if content_origin else ()

    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason=(
            "Public web app shell and build files; the API authorizes every "
            "data request."
        ),
    )
    async def web_app_fallback(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await app.router.not_found(scope, receive, send)  # closes a websocket
            return
        path: str = scope["path"]
        request = Request(scope)
        if _is_reserved(path) or on_content_origin(request):
            raise HTTPException(status_code=404)

        if scope["method"] in ("GET", "HEAD"):
            english = path == "/en" or path.startswith("/en/")
            remainder = (path[3:] or "/") if english else path
            if _is_reserved(remainder):
                raise HTTPException(status_code=404)
            target = legacy_page_target(remainder)
            if english or target is not None:
                if not _is_local_redirect_path(remainder):
                    raise HTTPException(status_code=404)
                target = target or remainder
                response = RedirectResponse(
                    _redirect_location(target, scope["query_string"]),
                    status_code=308,
                    headers=_PATH_HEADERS.get(target.rstrip("/"), {}),
                )
                if english:
                    response.headers["Cache-Control"] = "no-store"
                    _set_locale_cookie(
                        response, "en", secure=not settings.is_development
                    )
                await response(scope, receive, send)
                return

        suffix = PurePosixPath(path).suffix.lower()
        if suffix == ".html":
            # Raw index.html would carry no CSP and the literal placeholders.
            raise HTTPException(status_code=404, headers=_NOT_STORED)
        if suffix:
            # Normalized; StaticFiles refuses traversal out of dist and
            # methods other than GET and HEAD.
            file = static.get_path(scope)
            try:
                response = await static.get_response(file, scope)
            except StarletteHTTPException as exc:
                if exc.status_code != 404:
                    raise
                raise HTTPException(status_code=404, headers=_NOT_STORED) from None
            hashed = PurePath(file).parts[:1] == ("assets",)
            response.headers["Cache-Control"] = _IMMUTABLE if hashed else "no-cache"
            await response(scope, receive, send)
            return
        if scope["method"] not in ("GET", "HEAD"):
            raise HTTPException(status_code=404)

        nonce = secrets.token_urlsafe(16)
        current_locale = request.cookies.get(_LOCALE_COOKIE)
        legacy_locales = (
            request.cookies.get(name)
            for name in (_RETIRED_LOCALE_COOKIE, _LEGACY_LOCALE_COOKIE)
        )
        migrated_locale = (
            next((value for value in legacy_locales if value in ("sv", "en")), None)
            if current_locale is None
            else None
        )
        values = {
            _NONCE: nonce,
            _LANG: "en" if (migrated_locale or current_locale) == "en" else "sv",
        }
        # One pass: an inserted value is never scanned for placeholders.
        html = _PLACEHOLDER.sub(lambda match: values[match.group(0)], template)
        response = HTMLResponse(
            html,
            headers={
                "Content-Security-Policy": build_content_security_policy(
                    nonce, frame_origins
                ),
                "Cache-Control": "no-store",
                **_PATH_HEADERS.get(path.rstrip("/"), {}),
            },
        )
        if migrated_locale is not None:
            _set_locale_cookie(
                response, migrated_locale, secure=not settings.is_development
            )
        if _RETIRED_LOCALE_COOKIE in request.cookies:
            response.delete_cookie(
                _RETIRED_LOCALE_COOKIE, secure=not settings.is_development
            )
        await response(scope, receive, send)

    def render_embed(policy: EmbedPolicy) -> HTMLResponse:
        nonce = secrets.token_urlsafe(16)
        values = {_NONCE: nonce, _LANG: policy.locale}
        html = _PLACEHOLDER.sub(lambda match: values[match.group(0)], template)
        html = html.replace(
            "<html ",
            f'<html data-eneo-embed-scheme="{policy.scheme}" data-eneo-embed-state="{policy.state}" ',
            1,
        )
        overrides = {
            "frame-ancestors": policy.frame_ancestors,
            "frame-src": "'none'",
            "worker-src": "'self'",
            "base-uri": "'none'",
        }
        directives = build_content_security_policy(nonce, ()).split("; ")
        csp = "; ".join(
            [
                directive
                for directive in directives
                if directive.split(" ", 1)[0] not in overrides
            ]
            + [f"{name} {value}" for name, value in overrides.items()]
        )
        return HTMLResponse(
            html,
            headers={
                "Content-Security-Policy": csp,
                "Cache-Control": "no-store",
                "Referrer-Policy": "strict-origin-when-cross-origin",
                "X-Robots-Tag": "noindex, nofollow, noarchive",
            },
        )

    install_widget_web(app, render_embed)

    app.router.default = web_app_fallback
    _alias_healthz(app)
