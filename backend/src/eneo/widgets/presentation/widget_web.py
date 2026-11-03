"""The widget's public web documents and immutable loader assets.

FastAPI owns response policy now that web-next is a static Vite app. Visitor
API calls go directly to the existing widget API; no cookie-authenticated
proxy participates in an embedded conversation.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from starlette.responses import HTMLResponse, JSONResponse, Response

from eneo.allowed_origins.origin_matching import normalize_origin_pattern
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.main.config import LOOPBACK_HOSTS, get_settings, validate_content_base_url
from eneo.main.logging import get_logger
from eneo.mcp_apps.presentation.mcp_apps_router import on_content_origin
from eneo.server.dependencies.widget_auth import PublicContainer
from eneo.widgets.domain.exceptions import WidgetNotActiveError
from eneo.widgets.domain.widget import (
    Widget,
    WidgetColorScheme,
    WidgetLanguage,
    WidgetPosition,
)

logger = get_logger(__name__)

_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_CROSS_ORIGIN = {
    "Access-Control-Allow-Origin": "*",
    "Cross-Origin-Resource-Policy": "cross-origin",
    "X-Content-Type-Options": "nosniff",
}
_PUBLIC_REASON = (
    "Public widget presentation; the visitor API authorizes every chat request."
)


@dataclass(frozen=True)
class EmbedPolicy:
    frame_ancestors: str
    locale: Literal["sv", "en"]
    scheme: Literal["light", "dark", "system"]
    state: Literal["active", "preview", "unavailable"]


def embed_policy(
    request: Request, widget: Widget | None, *, failed: bool = False
) -> EmbedPolicy:
    """Only validated origin patterns may enter the document's CSP."""
    preview = request.query_params.get("preview") == "1"
    standalone = request.query_params.get("mode") == "full"
    if preview or standalone or failed:
        # A failed policy lookup must not grant a cross-origin frame access:
        # its subsequent public-config request may already succeed. Only a
        # confirmed unavailable widget may use the permissive notice policy.
        ancestors = "'self'"
    elif widget is None:
        # A paused/unknown widget renders only its unavailable notice. Allow
        # it to frame so the host's launcher never opens an unexplained blank.
        ancestors = "*"
    else:
        sources: list[str] = []
        for source in widget.allowed_origins:
            try:
                sources.append(normalize_origin_pattern(source))
            except ValueError:
                continue
        ancestors = (
            "'self' " + " ".join(dict.fromkeys(sources)) if sources else "'none'"
        )
    path_locale: Literal["sv", "en"] = (
        "en" if request.url.path.startswith("/en/") else "sv"
    )
    locale = path_locale
    if widget is not None and widget.language != WidgetLanguage.AUTO:
        locale = "en" if widget.language == WidgetLanguage.EN else "sv"
    scheme: Literal["light", "dark", "system"] = "system"
    selected = widget.theme.color_scheme.value if widget is not None else None
    if selected not in ("light", "dark"):
        selected = request.query_params.get("scheme")
    if selected in ("light", "dark"):
        scheme = "light" if selected == "light" else "dark"
    # Availability belongs to this document's policy snapshot. A permissively
    # framed unavailable notice must not become a live chat if the widget is
    # activated before the browser requests its public configuration.
    state: Literal["active", "preview", "unavailable"] = (
        "preview"
        if preview
        else "active"
        if widget is not None and not failed
        else "unavailable"
    )
    return EmbedPolicy(ancestors, locale, scheme, state)


class LoaderManifest(BaseModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    channel: str = Field(pattern=r"^v\d+$")
    file: Literal["eneo.js"]
    integrity: str
    css_file: Literal["eneo.css"] | None = None
    css_integrity: str | None = None


def _manifest(directory: Path) -> LoaderManifest | None:
    try:
        manifest = LoaderManifest.model_validate_json(
            (directory / "manifest.json").read_bytes()
        )
    except (OSError, ValidationError):
        return None
    if bool(manifest.css_file) != bool(manifest.css_integrity):
        return None
    return manifest


def _loader_asset(
    request: Request, version: str, asset: Literal["js", "css"]
) -> Response:
    loader_dir = get_settings().widget_loader_dir
    current = _manifest(loader_dir / "dist")
    directory = loader_dir / "dist"
    if current is not None and version in (current.channel, current.version):
        manifest = current
    elif _VERSION.fullmatch(version):
        directory = loader_dir / "releases" / version
        archived = _manifest(directory)
        if archived is None or archived.version != version:
            return Response(
                status_code=404, headers={**_CROSS_ORIGIN, "Cache-Control": "no-store"}
            )
        manifest = archived
    else:
        status = 503 if current is None else 404
        return Response(
            status_code=status,
            headers={**_CROSS_ORIGIN, "Retry-After": "60", "Cache-Control": "no-store"},
        )
    integrity = manifest.integrity if asset == "js" else manifest.css_integrity
    if integrity is None:
        return Response(
            status_code=404, headers={**_CROSS_ORIGIN, "Cache-Control": "no-store"}
        )
    try:
        content = (directory / f"eneo.{asset}").read_bytes()
    except OSError:
        return Response(
            status_code=503,
            headers={**_CROSS_ORIGIN, "Retry-After": "60", "Cache-Control": "no-store"},
        )
    actual = "sha384-" + base64.b64encode(hashlib.sha384(content).digest()).decode(
        "ascii"
    )
    if actual != integrity:
        logger.error(
            "Widget loader %s %s does not match its integrity manifest", version, asset
        )
        return Response(
            status_code=503, headers={**_CROSS_ORIGIN, "Cache-Control": "no-store"}
        )
    headers = {
        **_CROSS_ORIGIN,
        "Cache-Control": "public, max-age=3600"
        if version == manifest.channel
        else "public, max-age=31536000, immutable",
        "X-Eneo-Widget-Version": manifest.version,
        "ETag": f'"{integrity}"',
    }
    if request.headers.get("if-none-match") == headers["ETag"]:
        return Response(status_code=304, headers=headers)
    return Response(
        content,
        headers=headers,
        media_type="text/javascript" if asset == "js" else "text/css",
    )


class LauncherColor(BaseModel):
    accent: str
    on_accent: str


class LauncherColors(BaseModel):
    light: LauncherColor
    dark: LauncherColor


class LauncherPersona(BaseModel):
    name: str
    avatar_url: str | None


class LauncherSettings(BaseModel):
    language: WidgetLanguage
    position: WidgetPosition
    colors: LauncherColors
    persona: LauncherPersona | None


def _launcher_color(accent: str) -> LauncherColor:
    def luminance(color: str) -> float:
        channels = (int(color[index : index + 2], 16) / 255 for index in (1, 3, 5))
        linear = (
            value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
            for value in channels
        )
        return sum(
            weight * value for weight, value in zip((0.2126, 0.7152, 0.0722), linear)
        )

    value = luminance(accent)
    white = 1.05 / (value + 0.05)
    dark = (value + 0.05) / (luminance("#111111") + 0.05)
    return LauncherColor(
        accent=accent, on_accent="#FFFFFF" if white >= dark else "#111111"
    )


def launcher_settings(widget: Widget, origin: str) -> LauncherSettings:
    theme = widget.theme
    dark = theme.primary_color_dark or theme.primary_color
    light = (
        dark if theme.color_scheme == WidgetColorScheme.DARK else theme.primary_color
    )
    if theme.color_scheme == WidgetColorScheme.LIGHT:
        dark = light
    persona = widget.persona
    avatar = None
    if persona.avatar_icon_id is not None and persona.avatar_in_launcher:
        avatar = f"{origin}{get_settings().api_prefix}/icons/{quote(str(persona.avatar_icon_id), safe='')}/"
    return LauncherSettings(
        language=widget.language,
        position=theme.position,
        colors=LauncherColors(light=_launcher_color(light), dark=_launcher_color(dark)),
        persona=LauncherPersona(name=persona.name, avatar_url=avatar)
        if persona.name
        else None,
    )


def _require_web_host(request: Request) -> None:
    if on_content_origin(request):
        raise HTTPException(status_code=404)


def install_widget_web(
    app: FastAPI, render_embed: Callable[[EmbedPolicy], HTMLResponse] | None = None
) -> None:
    router = APIRouter(
        include_in_schema=False, dependencies=[Depends(_require_web_host)]
    )

    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason=_PUBLIC_REASON,
    )
    async def embed_document(
        request: Request, public_id: str, container: PublicContainer
    ) -> Response:
        assert render_embed is not None
        widget = None
        failed = False
        if request.query_params.get("preview") != "1":
            try:
                async with asyncio.timeout(2.5):
                    widget = await container.widget_authentication_service().get_active_widget(
                        public_id
                    )
            except WidgetNotActiveError:
                pass
            except Exception:
                failed = True
                logger.exception("Failed to load widget document policy")
        return render_embed(embed_policy(request, widget, failed=failed))

    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason=_PUBLIC_REASON,
    )
    async def loader_manifest() -> Response:
        manifest = _manifest(get_settings().widget_loader_dir / "dist")
        headers = {**_CROSS_ORIGIN, "Cache-Control": "no-store"}
        if manifest is None:
            return Response(status_code=503, headers={**headers, "Retry-After": "60"})
        metadata = {
            "version": manifest.version,
            "channel": manifest.channel,
            "integrity": manifest.integrity,
        }
        if manifest.css_integrity:
            metadata["cssIntegrity"] = manifest.css_integrity
        return JSONResponse(metadata, headers=headers)

    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason=_PUBLIC_REASON,
    )
    async def loader_script(request: Request, version: str) -> Response:
        return _loader_asset(request, version, "js")

    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason=_PUBLIC_REASON,
    )
    async def loader_stylesheet(request: Request, version: str) -> Response:
        return _loader_asset(request, version, "css")

    @endpoint_access(
        authentication=Authentication.PUBLIC,
        authorization=Authorization.PUBLIC,
        reason=_PUBLIC_REASON,
    )
    async def settings(
        request: Request, public_id: str, container: PublicContainer
    ) -> Response:
        headers = {**_CROSS_ORIGIN, "Cache-Control": "no-store"}
        try:
            async with asyncio.timeout(2.5):
                widget = (
                    await container.widget_authentication_service().get_active_widget(
                        public_id
                    )
                )
        except WidgetNotActiveError:
            return Response(status_code=404, headers=headers)
        except TimeoutError:
            return Response(status_code=503, headers={**headers, "Retry-After": "5"})
        # The optional beta serves the same backend on a second host while
        # PUBLIC_ORIGIN remains the main app's callback origin. The launcher
        # must load its avatar from the host its loader came from. Keep the
        # configured external scheme behind TLS termination; forwarded host
        # and scheme headers are never trusted here.
        configured_origin = get_settings().public_origin
        scheme = (
            urlsplit(configured_origin).scheme
            if configured_origin
            else request.url.scheme
        )
        if request.url.hostname in LOOPBACK_HOSTS:
            scheme = request.url.scheme
        try:
            origin = validate_content_base_url(f"{scheme}://{request.url.netloc}")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid widget host") from None
        return JSONResponse(
            launcher_settings(widget, origin).model_dump(mode="json"), headers=headers
        )

    if render_embed is not None:
        for path in ("/embed/{public_id}", "/en/embed/{public_id}"):
            router.add_api_route(path, embed_document, methods=["GET", "HEAD"])
    router.add_api_route(
        "/widget/manifest.json", loader_manifest, methods=["GET", "HEAD"]
    )
    router.add_api_route(
        "/widget/{version}/eneo.js", loader_script, methods=["GET", "HEAD"]
    )
    router.add_api_route(
        "/widget/{version}/eneo.css", loader_stylesheet, methods=["GET", "HEAD"]
    )
    router.add_api_route(
        "/widget/settings/{public_id}", settings, methods=["GET", "HEAD"]
    )
    app.include_router(router)
