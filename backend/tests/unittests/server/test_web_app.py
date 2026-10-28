import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    access_for,
    endpoint_access,
)
from eneo.main.config import get_settings, set_settings
from eneo.scim.app import scim_app
from eneo.server import web_app
from eneo.server.browser_platform import install_browser_platform
from eneo.server.exception_handlers import add_exception_handlers
from eneo.server.web_app import build_content_security_policy

INDEX = (
    '<!doctype html><html lang="__ENEO_HTML_LANG__"><head>'
    '<meta property="csp-nonce" nonce="__ENEO_CSP_NONCE__">'
    '<script type="module" nonce="__ENEO_CSP_NONCE__" src="/assets/app-1a2b.js">'
    '</script></head><body><div id="root"></div></body></html>'
)
CONTENT_BASE = "https://content.example.com"
SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "x-dns-prefetch-control": "off",
    "permissions-policy": "camera=(), geolocation=(), microphone=(self)",
}


@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Test route.",
)
async def _things() -> dict[str, bool]:
    return {"ok": True}


@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Test health stub.",
)
async def _healthz() -> dict[str, str]:
    return {"status": "HEALTHY"}


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "flows").mkdir()
    (root / "index.html").write_text(INDEX)
    (root / "assets" / "app-1a2b.js").write_text("console.log('app')")
    (root / "flows" / "pcm16-worklet.js").write_text("registerProcessor()")
    (tmp_path / "secret.txt").write_text("outside dist")
    return root


def _settings(**updates: object) -> None:
    set_settings(
        get_settings().model_copy(
            update={"environment": "production", "web_app_enabled": True, **updates}
        )
    )


def _app(
    monkeypatch: pytest.MonkeyPatch,
    dist: Path,
    *,
    documented: bool = False,
    **updates: object,
) -> FastAPI:
    monkeypatch.setattr(web_app, "WEB_APP_DIST", dist)
    _settings(**updates)
    if documented:
        app = FastAPI()
        app.mount("/scim/v2", scim_app)
    else:
        app = FastAPI(docs_url=None, redoc_url=None)
    app.add_api_route("/api/healthz", _healthz, methods=["GET"])
    app.add_api_route("/api/v1/things/", _things, methods=["GET"])
    add_exception_handlers(app)
    install_browser_platform(app)
    return app


def _client(monkeypatch: pytest.MonkeyPatch, dist: Path, **updates: object):
    return TestClient(_app(monkeypatch, dist, **updates))


def _nonce(csp: str) -> str:
    match = re.search(r"'nonce-([^']+)'", csp)
    assert match is not None
    return match.group(1)


def test_disabled_by_default_keeps_unknown_paths_json_404(
    monkeypatch: pytest.MonkeyPatch, dist: Path
):
    client = _client(monkeypatch, dist, web_app_enabled=False)

    for path in ("/", "/spaces/list", "/assets/app-1a2b.js"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.headers["content-type"] == "application/json"
        assert "referrer-policy" not in response.headers


def test_enabled_without_index_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    with pytest.raises(RuntimeError, match="index.html is missing"):
        _app(monkeypatch, tmp_path / "missing")


@pytest.mark.parametrize("placeholder", ["__ENEO_CSP_NONCE__", "__ENEO_HTML_LANG__"])
def test_index_without_placeholders_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch, dist: Path, placeholder: str
):
    (dist / "index.html").write_text(INDEX.replace(placeholder, "x"))

    with pytest.raises(RuntimeError, match=placeholder):
        _app(monkeypatch, dist)


@pytest.mark.parametrize("path", ["/", "/spaces/list", "/login", "/spaces/1/"])
def test_client_path_gets_templated_index(
    monkeypatch: pytest.MonkeyPatch, dist: Path, path: str
):
    response = _client(monkeypatch, dist).get(path)

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    assert response.headers["strict-transport-security"] == "max-age=31536000"
    assert "__ENEO_" not in response.text
    assert response.text.startswith('<!doctype html><html lang="sv">')


def test_head_gets_the_index_headers(monkeypatch: pytest.MonkeyPatch, dist: Path):
    response = _client(monkeypatch, dist).head("/spaces/list")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "content-security-policy" in response.headers


def test_csp_nonce_matches_meta_nonce_and_changes_per_request(
    monkeypatch: pytest.MonkeyPatch, dist: Path
):
    client = _client(monkeypatch, dist)
    nonces = []
    for _ in range(2):
        response = client.get("/")
        nonce = _nonce(response.headers["content-security-policy"])
        assert f'<meta property="csp-nonce" nonce="{nonce}">' in response.text
        assert response.text.count(f'nonce="{nonce}"') == 2
        nonces.append(nonce)

    assert nonces[0] != nonces[1]
    assert len(nonces[0]) >= 22  # 16 random bytes


@pytest.mark.parametrize(
    ("cookie", "lang"), [("en", "en"), ("sv", "sv"), ("de", "sv"), (None, "sv")]
)
def test_html_lang_follows_next_locale_cookie(
    monkeypatch: pytest.MonkeyPatch, dist: Path, cookie: str | None, lang: str
):
    client = _client(monkeypatch, dist)
    if cookie is not None:
        client.cookies.set("NEXT_LOCALE", cookie)

    assert f'<html lang="{lang}">' in client.get("/").text


def test_template_is_filled_in_one_pass(monkeypatch: pytest.MonkeyPatch, dist: Path):
    client = _client(monkeypatch, dist)
    monkeypatch.setattr(
        web_app.secrets, "token_urlsafe", lambda _: "__ENEO_HTML_LANG__"
    )

    response = client.get("/")

    assert 'nonce="__ENEO_HTML_LANG__"' in response.text
    assert '<html lang="sv">' in response.text


def test_csp_matches_the_next_production_policy():
    policy = build_content_security_policy("abc", ())

    assert policy == (
        "default-src 'self'; "
        "script-src 'self' 'nonce-abc' 'strict-dynamic'; "
        "style-src 'self' 'nonce-abc'; "
        "style-src-attr 'unsafe-inline'; "
        "img-src 'self' blob: data:; "
        "font-src 'self' data:; "
        "media-src 'self' blob: data:; "
        "frame-src blob:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'self'; "
        "script-src-attr 'none'; "
        "upgrade-insecure-requests"
    )
    framed = build_content_security_policy("abc", (CONTENT_BASE,))
    assert f"frame-src blob: {CONTENT_BASE};" in framed
    script_src = next(d for d in policy.split("; ") if d.startswith("script-src "))
    assert "unsafe-inline" not in script_src
    assert "unsafe-eval" not in script_src


def test_csp_frames_the_mcp_content_origin(monkeypatch: pytest.MonkeyPatch, dist: Path):
    client = _client(
        monkeypatch, dist, mcp_app_content_base_url=CONTENT_BASE + "/views"
    )

    csp = client.get("/").headers["content-security-policy"]

    assert f"frame-src blob: {CONTENT_BASE};" in csp


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/missing",
        "/api",
        "/scim/x",
        "/internal-mcp/x",
        "/docs/x",
        "/redoc",
        "/openapi.json/x",
        "/version/x",
    ],
)
def test_reserved_prefixes_never_return_html(
    monkeypatch: pytest.MonkeyPatch, dist: Path, path: str
):
    response = _client(monkeypatch, dist).get(path)

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json()["detail"] == "Not Found"


def test_api_slash_redirect_and_method_not_allowed_unchanged(
    monkeypatch: pytest.MonkeyPatch, dist: Path
):
    client = _client(monkeypatch, dist)

    redirect = client.get("/api/v1/things?x=1", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"].endswith("/api/v1/things/?x=1")
    assert client.post("/api/v1/things/").status_code == 405


def test_assets_are_immutable_and_missing_assets_404(
    monkeypatch: pytest.MonkeyPatch, dist: Path
):
    client = _client(monkeypatch, dist)

    response = client.get("/assets/app-1a2b.js")
    assert response.status_code == 200
    assert response.text == "console.log('app')"
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["x-content-type-options"] == "nosniff"

    missing = client.get("/assets/missing-9z.js")
    assert missing.status_code == 404
    assert missing.headers["content-type"] == "application/json"


@pytest.mark.parametrize(
    "path", ["/flows/pcm16-worklet.js", "/assets/%2E%2E/flows/pcm16-worklet.js"]
)
def test_public_files_revalidate(
    monkeypatch: pytest.MonkeyPatch, dist: Path, path: str
):
    response = _client(monkeypatch, dist).get(path)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "path", ["/index.html", "/x.html", "/INDEX.HTML", "/assets/%2E%2E/index.html"]
)
def test_raw_index_html_is_never_served(
    monkeypatch: pytest.MonkeyPatch, dist: Path, path: str
):
    response = _client(monkeypatch, dist).get(path)

    assert response.status_code == 404
    assert "__ENEO_" not in response.text


@pytest.mark.parametrize(
    "path", ["/assets/%2E%2E/%2E%2E/secret.txt", "/%2E%2E/secret.txt"]
)
def test_traversal_outside_dist_is_404(
    monkeypatch: pytest.MonkeyPatch, dist: Path, path: str
):
    response = _client(monkeypatch, dist).get(path)

    assert response.status_code == 404
    assert "outside dist" not in response.text


@pytest.mark.parametrize("path", ["/", "/spaces/list", "/assets/app-1a2b.js"])
def test_mcp_content_host_never_gets_the_app(
    monkeypatch: pytest.MonkeyPatch, dist: Path, path: str
):
    client = _client(monkeypatch, dist, mcp_app_content_base_url=CONTENT_BASE)

    response = client.get(path, headers={"host": "content.example.com"})

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"


def test_websocket_on_unknown_path_is_closed(
    monkeypatch: pytest.MonkeyPatch, dist: Path
):
    client = _client(monkeypatch, dist)

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/spaces/list"):
            pass


def test_post_to_client_path_is_404(monkeypatch: pytest.MonkeyPatch, dist: Path):
    response = _client(monkeypatch, dist).post("/spaces/list")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"


def test_fallback_is_declared_public(monkeypatch: pytest.MonkeyPatch, dist: Path):
    app = _app(monkeypatch, dist)

    policy = access_for(app.router.default)

    assert policy is not None
    assert policy.authentication is Authentication.PUBLIC
    assert policy.authorization is Authorization.PUBLIC


def test_get_application_with_web_app_enabled_validates(
    monkeypatch: pytest.MonkeyPatch, dist: Path
):
    from eneo.server.main import get_application

    monkeypatch.setattr(web_app, "WEB_APP_DIST", dist)
    _settings()

    app = get_application()
    client = TestClient(app)

    assert client.get("/spaces/list").headers["content-type"].startswith("text/html")
    missing = client.get("/api/v1/does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["message"] == "Not Found"
    assert client.get("/docs").status_code == 404
    assert client.get("/scim/v2/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 200
    endpoints = {
        route.path: route.endpoint
        for route in app.router.routes
        if isinstance(route, APIRoute)
    }
    assert endpoints["/healthz"] is endpoints["/api/healthz"]


@pytest.mark.parametrize(
    "path", ["/module-login", "/module-login/failed", "/module-login/"]
)
def test_module_login_paths_are_noindex_no_referrer(
    monkeypatch: pytest.MonkeyPatch, dist: Path, path: str
):
    response = _client(monkeypatch, dist).get(f"{path}?state=s&redirect_uri=x")

    assert response.headers.get_list("referrer-policy") == ["no-referrer"]
    assert response.headers["x-robots-tag"] == "noindex, nofollow, noarchive"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/", "/login", "/module-login/x"])
def test_other_paths_keep_strict_origin_referrer(
    monkeypatch: pytest.MonkeyPatch, dist: Path, path: str
):
    response = _client(monkeypatch, dist).get(path)

    assert response.headers.get_list("referrer-policy") == [
        "strict-origin-when-cross-origin"
    ]
    assert "x-robots-tag" not in response.headers


def test_healthz_alias_serves_the_api_healthz_endpoint(
    monkeypatch: pytest.MonkeyPatch, dist: Path
):
    app = _app(monkeypatch, dist)

    endpoints = {
        route.path: route.endpoint
        for route in app.router.routes
        if isinstance(route, APIRoute)
    }
    assert endpoints["/healthz"] is endpoints["/api/healthz"]
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "HEALTHY"}
    assert "/healthz" not in app.openapi()["paths"]


def test_healthz_alias_requires_api_healthz(
    monkeypatch: pytest.MonkeyPatch, dist: Path
):
    monkeypatch.setattr(web_app, "WEB_APP_DIST", dist)
    _settings()

    with pytest.raises(RuntimeError, match="/api/healthz"):
        install_browser_platform(FastAPI())


def test_healthz_absent_when_disabled(monkeypatch: pytest.MonkeyPatch, dist: Path):
    response = _client(monkeypatch, dist, web_app_enabled=False).get("/healthz")

    assert response.status_code == 404


DOCUMENTATION_PAGES = (
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/scim/v2/docs",
    "/scim/v2/docs/oauth2-redirect",
    "/scim/v2/redoc",
)
BROWSER_FLAGS = (
    {"web_app_enabled": True},
    {"web_app_enabled": False, "browser_session_enabled": True},
)


@pytest.mark.parametrize("flags", BROWSER_FLAGS)
@pytest.mark.parametrize("path", DOCUMENTATION_PAGES)
def test_documentation_pages_are_404_when_the_web_app_is_on(
    monkeypatch: pytest.MonkeyPatch, dist: Path, path: str, flags: dict[str, bool]
):
    response = TestClient(_app(monkeypatch, dist, documented=True, **flags)).get(path)

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"


@pytest.mark.parametrize("flags", BROWSER_FLAGS)
@pytest.mark.parametrize("path", ["/openapi.json", "/scim/v2/openapi.json"])
def test_openapi_json_stays_available(
    monkeypatch: pytest.MonkeyPatch, dist: Path, path: str, flags: dict[str, bool]
):
    response = TestClient(_app(monkeypatch, dist, documented=True, **flags)).get(path)

    assert response.status_code == 200
    assert "openapi" in response.json()


@pytest.mark.parametrize("flags", BROWSER_FLAGS)
def test_documentation_stays_in_development(
    monkeypatch: pytest.MonkeyPatch, dist: Path, flags: dict[str, bool]
):
    client = TestClient(
        _app(monkeypatch, dist, documented=True, environment="development", **flags)
    )

    for path in DOCUMENTATION_PAGES:
        assert client.get(path).status_code == 200, path


def test_documentation_unchanged_when_disabled(
    monkeypatch: pytest.MonkeyPatch, dist: Path
):
    client = TestClient(_app(monkeypatch, dist, documented=True, web_app_enabled=False))

    for path in DOCUMENTATION_PAGES:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith("text/html")
