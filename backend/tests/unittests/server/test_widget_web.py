import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import HTMLResponse

from eneo.main.config import get_settings, set_settings
from eneo.server.dependencies.widget_auth import PublicContainer
from eneo.server.middleware.cors import CORS_OPTIONS, CORSMiddleware, OriginCallback
from eneo.widgets.domain.exceptions import WidgetNotActiveError
from eneo.widgets.domain.widget import (
    Widget,
    WidgetColorScheme,
    WidgetLanguage,
    WidgetPersona,
)
from eneo.widgets.presentation import widget_web
from eneo.widgets.presentation.widget_web import embed_policy, launcher_settings
from tests.unittests.server.test_web_app import _app


def _widget() -> Widget:
    return Widget.create(
        tenant_id=uuid4(), space_id=uuid4(), target_id=uuid4(), name="Widget"
    )


def _client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    widget: Widget | None,
    *,
    cors_callback: OriginCallback | None = None,
) -> tuple[TestClient, AsyncMock]:
    dist = tmp_path / "web-dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        '<html lang="__ENEO_HTML_LANG__"><script nonce="__ENEO_CSP_NONCE__"></script></html>'
    )
    app = _app(monkeypatch, dist)
    if cors_callback is not None:
        app.add_middleware(
            CORSMiddleware, **{**CORS_OPTIONS, "callback": cors_callback}
        )
    get_active = AsyncMock(return_value=widget)
    if widget is None:
        get_active.side_effect = WidgetNotActiveError()
    container = SimpleNamespace(
        widget_authentication_service=lambda: SimpleNamespace(
            get_active_widget=get_active
        )
    )
    app.dependency_overrides[get_args(PublicContainer)[1].dependency] = (
        lambda: container
    )
    return TestClient(app), get_active


@pytest.mark.parametrize("path", ["/embed/wgt_test", "/en/embed/wgt_test"])
def test_embed_document_has_widget_policy_without_preference_cookies(
    monkeypatch, tmp_path, path
):
    widget = _widget().model_copy(
        update={
            "allowed_origins": ["https://site.example"],
            "language": WidgetLanguage.EN,
        }
    )
    widget.theme.color_scheme = WidgetColorScheme.DARK
    client, _ = _client(monkeypatch, tmp_path, widget)
    response = client.get(
        path + "?scheme=light",
        headers={"Cookie": "eneo_locale=sv; NEXT_LOCALE=sv"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    csp = response.headers["content-security-policy"]
    assert "frame-ancestors 'self' https://site.example" in csp
    assert "frame-src 'none'" in csp
    assert "worker-src 'self' blob:" in csp
    assert "base-uri 'none'" in csp
    assert "connect-src 'self'" in csp
    assert "img-src 'self' blob: data:" in csp
    assert 'data-eneo-embed-scheme="dark"' in response.text
    assert 'lang="en"' in response.text
    assert "__ENEO_CSP_NONCE__" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "set-cookie" not in response.headers


def test_preview_does_not_load_draft_configuration_on_the_server(monkeypatch, tmp_path):
    client, get_active = _client(monkeypatch, tmp_path, _widget())
    response = client.get("/en/embed/wgt_test?preview=1&scheme=dark")
    get_active.assert_not_awaited()
    assert "frame-ancestors 'self'" in response.headers["content-security-policy"]
    assert 'lang="en"' in response.text
    assert 'data-eneo-embed-scheme="dark"' in response.text
    assert "set-cookie" not in response.headers


def test_unavailable_notice_may_be_framed_and_does_not_migrate_locale(
    monkeypatch, tmp_path
):
    client, _ = _client(monkeypatch, tmp_path, None)
    response = client.get("/embed/wgt_test", headers={"Cookie": "NEXT_LOCALE=en"})
    assert response.status_code == 200
    assert "frame-ancestors *" in response.headers["content-security-policy"]
    assert 'lang="sv"' in response.text
    assert "set-cookie" not in response.headers


def test_embed_policy_drops_invalid_stored_origins():
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/embed/test",
            "query_string": b"",
            "headers": [],
            "scheme": "https",
            "server": ("eneo.example", 443),
        }
    )
    widget = _widget().model_copy(
        update={
            "allowed_origins": [
                "https://site.example; script-src *",
                "https://*.example.org",
            ]
        }
    )
    assert (
        embed_policy(request, widget).frame_ancestors == "'self' https://*.example.org"
    )


def _write_bundle(directory: Path, version: str, *, css: bool = True) -> dict[str, str]:
    directory.mkdir(parents=True)
    source = f"/* {version} */".encode()
    style = b":host { color: red; }"
    integrity = (
        lambda value: "sha384-"
        + base64.b64encode(hashlib.sha384(value).digest()).decode()
    )
    manifest = {
        "version": version,
        "channel": "v1",
        "file": "eneo.js",
        "integrity": integrity(source),
    }
    (directory / "eneo.js").write_bytes(source)
    if css:
        manifest.update(css_file="eneo.css", css_integrity=integrity(style))
        (directory / "eneo.css").write_bytes(style)
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return manifest


@pytest.mark.parametrize("asset", ["js", "css"])
def test_loader_bytes_cache_and_sri_survive_the_vite_migration(
    monkeypatch, tmp_path, asset
):
    manifest = _write_bundle(tmp_path / "dist", "1.0.0")
    archived = _write_bundle(tmp_path / "releases" / "0.9.0", "0.9.0", css=False)
    monkeypatch.setattr(widget_web, "WIDGET_LOADER_DIR", tmp_path)
    app = FastAPI()
    widget_web.install_widget_web(app, lambda policy: HTMLResponse(""))
    client = TestClient(app)
    channel = client.get(f"/widget/v1/eneo.{asset}")
    assert channel.status_code == 200
    assert channel.headers["cache-control"] == "public, max-age=3600"
    assert channel.headers["access-control-allow-origin"] == "*"
    assert channel.headers["cross-origin-resource-policy"] == "cross-origin"
    expected_integrity = manifest["integrity" if asset == "js" else "css_integrity"]
    assert channel.headers["etag"] == f'"{expected_integrity}"'
    pinned = client.get(f"/widget/1.0.0/eneo.{asset}")
    assert pinned.content == channel.content
    assert pinned.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert (
        client.get(
            f"/widget/v1/eneo.{asset}",
            headers={"If-None-Match": channel.headers["etag"]},
        ).status_code
        == 304
    )
    old = client.get(f"/widget/0.9.0/eneo.{asset}")
    assert old.status_code == (200 if asset == "js" else 404)
    if asset == "js":
        assert old.headers["etag"] == f'"{archived["integrity"]}"'
    assert client.get(f"/widget/v2/eneo.{asset}").status_code == 404
    assert client.get("/widget/manifest.json").json()["version"] == "1.0.0"


def test_loader_refuses_changed_bytes_and_reports_missing_build(monkeypatch, tmp_path):
    monkeypatch.setattr(widget_web, "WIDGET_LOADER_DIR", tmp_path)
    app = FastAPI()
    widget_web.install_widget_web(app, lambda policy: HTMLResponse(""))
    client = TestClient(app)
    assert client.get("/widget/v1/eneo.js").status_code == 503
    _write_bundle(tmp_path / "dist", "1.0.0")
    (tmp_path / "dist" / "eneo.js").write_text("changed")
    assert client.get("/widget/1.0.0/eneo.js").status_code == 503


def test_launcher_settings_preserve_pinned_colors_persona_and_public_cache(
    monkeypatch, tmp_path
):
    widget = _widget()
    widget.theme.primary_color_dark = "#FFFFFF"
    widget.theme.color_scheme = WidgetColorScheme.DARK
    avatar = uuid4()
    widget.persona = WidgetPersona(
        name="Eneo", avatar_icon_id=avatar, avatar_in_launcher=True
    )
    colors = launcher_settings(widget, "https://eneo.example").colors
    assert colors.light == colors.dark
    assert colors.light.accent == "#FFFFFF"
    assert colors.light.on_accent == "#111111"
    client, _ = _client(monkeypatch, tmp_path, widget)
    response = client.get("/widget/settings/wgt_test")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.json()["persona"]["avatar_url"].endswith(f"/api/v1/icons/{avatar}/")


def test_archived_loader_is_available_without_a_current_build(monkeypatch, tmp_path):
    _write_bundle(tmp_path / "releases" / "0.9.0", "0.9.0", css=False)
    monkeypatch.setattr(widget_web, "WIDGET_LOADER_DIR", tmp_path)
    app = FastAPI()
    widget_web.install_widget_web(app, lambda policy: HTMLResponse(""))
    client = TestClient(app)
    assert client.get("/widget/v1/eneo.js").status_code == 503
    archived = client.get("/widget/0.9.0/eneo.js")
    assert archived.status_code == 200
    assert archived.content == b"/* 0.9.0 */"
    assert archived.headers["cache-control"] == "public, max-age=31536000, immutable"


@pytest.mark.parametrize(
    "path",
    [
        "/embed/wgt_test",
        "/en/embed/wgt_test",
        "/widget/v1/eneo.js",
        "/widget/v1/eneo.css",
        "/widget/manifest.json",
        "/widget/settings/wgt_test",
    ],
)
def test_widget_web_does_not_serve_on_the_mcp_content_host(monkeypatch, tmp_path, path):
    client, get_active = _client(monkeypatch, tmp_path, _widget())
    set_settings(
        get_settings().model_copy(
            update={"mcp_app_content_base_url": "https://content.example"}
        )
    )
    response = client.get(path, headers={"Host": "content.example"})
    assert response.status_code == 404
    get_active.assert_not_awaited()


@pytest.mark.parametrize(
    "error", [TimeoutError(), RuntimeError("database unavailable")]
)
def test_failed_policy_lookup_never_grants_cross_origin_framing(
    monkeypatch, tmp_path, error
):
    client, get_active = _client(monkeypatch, tmp_path, _widget())
    get_active.side_effect = error
    response = client.get("/embed/wgt_test")
    assert response.status_code == 200
    assert "frame-ancestors 'self'" in response.headers["content-security-policy"]
    assert "frame-ancestors *" not in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "path",
    [
        "/widget/v1/eneo.js",
        "/widget/1.0.0/eneo.css",
        "/widget/manifest.json",
        "/widget/settings/wgt_test",
    ],
)
def test_public_widget_cors_bypasses_the_tenant_allowlist_only_for_reads(
    monkeypatch, tmp_path, path
):
    _write_bundle(tmp_path / "dist", "1.0.0")
    monkeypatch.setattr(widget_web, "WIDGET_LOADER_DIR", tmp_path)
    callback = AsyncMock(return_value=False)
    client, _ = _client(monkeypatch, tmp_path, _widget(), cors_callback=callback)
    response = client.get(
        path,
        headers={
            "Origin": "https://external-widget-host.example",
            "Cookie": "eneo_session=ignored",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers
    callback.assert_not_awaited()
    set_settings(
        get_settings().model_copy(
            update={"mcp_app_content_base_url": "https://content.example"}
        )
    )
    isolated = client.get(
        path,
        headers={
            "Origin": "https://external-widget-host.example",
            "Host": "content.example",
        },
    )
    assert isolated.status_code == 404
    callback.assert_not_awaited()

    for method, guarded_path, headers in (
        ("GET", "/api/v1/things/", {}),
        ("GET", "/embed/wgt_test", {}),
        ("POST", path, {}),
        ("OPTIONS", path, {"Access-Control-Request-Method": "GET"}),
    ):
        refused = client.request(
            method,
            guarded_path,
            headers={"Origin": "https://external-widget-host.example", **headers},
        )
        assert refused.status_code == 400
        assert refused.headers.get("access-control-allow-origin") != "*"
    assert callback.await_count == 4


@pytest.mark.asyncio
async def test_unhandled_public_widget_error_has_the_same_noncredentialed_cors(
    monkeypatch,
):
    from starlette.responses import Response

    from eneo.server.middleware import cors

    callback = AsyncMock(side_effect=AssertionError("must not query tenant origins"))
    monkeypatch.setitem(cors.CORS_OPTIONS, "callback", callback)
    set_settings(get_settings().model_copy(update={"web_app_enabled": True}))
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/widget/v1/eneo.js",
            "query_string": b"",
            "headers": [(b"origin", b"https://external.example")],
            "scheme": "https",
            "server": ("eneo.example", 443),
        }
    )
    response = Response(status_code=500)
    await cors.add_cors_headers(request, response)
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers
    callback.assert_not_awaited()


def test_beta_launcher_avatar_stays_on_the_loader_host_behind_tls(
    monkeypatch, tmp_path
):
    widget = _widget()
    avatar = uuid4()
    widget.persona = WidgetPersona(
        name="Eneo", avatar_icon_id=avatar, avatar_in_launcher=True
    )
    client, _ = _client(monkeypatch, tmp_path, widget)
    set_settings(
        get_settings().model_copy(update={"public_origin": "https://main.example"})
    )
    response = client.get(
        "/widget/settings/wgt_test",
        headers={
            "Host": "beta.example",
            "X-Forwarded-Host": "untrusted.example",
            "X-Forwarded-Proto": "http",
        },
    )
    assert response.status_code == 200
    assert (
        response.json()["persona"]["avatar_url"]
        == f"https://beta.example/api/v1/icons/{avatar}/"
    )
    assert get_settings().public_origin == "https://main.example"
