import hashlib
import json
from html.parser import HTMLParser

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eneo.server import api_docs
from eneo.server.endpoint_routes import (
    declare_framework_documentation_access,
    validate_endpoint_access,
)


class PageAssets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[str] = []
        self.styles: list[str] = []
        self.inline_script = False
        self._script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "script":
            self._script = True
            self.scripts.append(attributes.get("src") or "")
        if tag == "link" and attributes.get("rel") == "stylesheet":
            self.styles.append(attributes.get("href") or "")

    def handle_data(self, data: str) -> None:
        if self._script and data.strip():
            self.inline_script = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._script = False


@pytest.fixture
def client() -> TestClient:
    app = FastAPI(docs_url=None, redoc_url=None)
    declare_framework_documentation_access(app)
    api_docs.install_api_docs(app)
    validate_endpoint_access(app)
    return TestClient(app)


def test_docs_use_only_local_packaged_scripts_and_styles(client: TestClient) -> None:
    response = client.get("/docs")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    page = PageAssets()
    page.feed(response.text)
    assert page.scripts == [
        "/docs/assets/swagger-ui-bundle.js",
        "/docs/assets/eneo-swagger-initializer.js",
    ]
    assert page.styles == ["/docs/assets/swagger-ui.css"]
    assert not page.inline_script
    for url in [*page.scripts, *page.styles]:
        asset = client.get(url)
        assert asset.status_code == 200
        assert asset.headers["x-content-type-options"] == "nosniff"
        assert asset.headers["cache-control"] == "no-store"
        assert asset.content


def test_docs_security_policy_keeps_scripts_and_api_requests_on_this_origin(
    client: TestClient,
) -> None:
    response = client.get("/docs")
    policy = response.headers["content-security-policy"]
    assert "script-src 'self'" in policy
    assert "connect-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy
    assert "base-uri 'none'" in policy
    assert "unsafe-eval" not in policy
    assert "https:" not in policy
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize(
    "name,content_type",
    [
        ("swagger-ui-bundle.js", "text/javascript"),
        ("swagger-ui.css", "text/css"),
        ("eneo-swagger-initializer.js", "text/javascript"),
        ("swagger-ui-bundle.js.LICENSE.txt", "text/plain"),
    ],
)
def test_assets_have_browser_content_types(
    client: TestClient, name: str, content_type: str
) -> None:
    response = client.get(f"/docs/assets/{name}")
    assert response.headers["content-type"].startswith(content_type)


@pytest.mark.parametrize(
    "name", ["upstream.json", "README.md", "missing.js", "%2e%2e%2fapi_docs.py"]
)
def test_asset_route_is_an_exact_allowlist(client: TestClient, name: str) -> None:
    assert client.get(f"/docs/assets/{name}").status_code == 404


def test_query_parameters_cannot_replace_the_document(client: TestClient) -> None:
    assert (
        client.get("/docs?url=https://untrusted.invalid/spec.json").content
        == client.get("/docs").content
    )


def test_docs_do_not_publish_themselves_in_the_api_schema(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/docs" not in response.json()["paths"]
    assert "/docs/assets/{filename}" not in response.json()["paths"]


def test_framework_cdn_docs_cannot_shadow_the_local_viewer() -> None:
    with pytest.raises(ValueError, match="Disable FastAPI docs_url"):
        api_docs.install_api_docs(FastAPI())


def test_unexpected_schema_location_fails_explicitly() -> None:
    with pytest.raises(ValueError, match="/openapi.json"):
        api_docs.install_api_docs(FastAPI(docs_url=None, openapi_url="/other.json"))


def test_packaged_upstream_files_match_the_pinned_distribution(
    client: TestClient,
) -> None:
    manifest = json.loads((api_docs._ASSETS / "upstream.json").read_text())
    assert manifest["package"] == "swagger-ui-dist"
    assert manifest["version"] == "5.35.0"
    assert manifest["license"] == "Apache-2.0"
    assert manifest["integrity"].startswith("sha512-")
    for name, expected in manifest["files"].items():
        response = client.get(f"/docs/assets/{name}")
        assert response.status_code == 200
        assert len(response.content) == expected["size"]
        assert hashlib.sha256(response.content).hexdigest() == expected["sha256"]
