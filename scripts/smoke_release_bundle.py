#!/usr/bin/env python3
"""CI-only smoke test: exact published images, isolated database, real signed files."""

import base64
import json
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message
from html.parser import HTMLParser
from http.cookiejar import CookieJar, DefaultCookiePolicy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = "http://127.0.0.1:8124"
RUNTIME = "http://127.0.0.1:8310"
WEB_NEXT = "http://127.0.0.1:8135"
# The numeric loopback address is the stack's MCP content host, not its web app.
WEB_APP = "http://localhost:8124"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LocalhostCookiePolicy(DefaultCookiePolicy):
    def return_ok_secure(self, cookie, request):
        # Match Chromium's trusted-localhost exception for Secure cookies.
        # Other HTTP hosts retain the standard policy.
        return super().return_ok_secure(cookie, request) or (
            request.type == "http"
            and urllib.parse.urlsplit(request.full_url).hostname == "localhost"
        )


def fetch(url, headers=None, data=None, opener=None) -> tuple[int, Message, bytes]:
    opener = opener or urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(
            urllib.request.Request(url, data=data, headers=headers or {}), timeout=60
        ) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.headers, error.read()


class WebAppIndex(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nonce = None
        self.asset = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("property") == "csp-nonce":
            self.nonce = attrs.get("nonce")
        if tag == "script" and self.asset is None:
            src = attrs.get("src") or ""
            if src.startswith("/assets/") and src.endswith(".js"):
                self.asset = src


def web_app_asset(headers: Message, html: bytes) -> str:
    index = WebAppIndex()
    index.feed(html.decode("utf-8"))
    assert index.nonce, "Web app HTML has no CSP nonce"
    assert f"'nonce-{index.nonce}'" in headers.get("Content-Security-Policy", ""), (
        "Web app HTML nonce does not match its CSP"
    )
    assert index.asset, "Web app HTML has no built JavaScript asset"
    return index.asset


def verify_web_app(origin, bundle):
    status, headers, html = fetch(origin + "/")
    assert status == 200, f"Web app index returned {status}"
    assert "text/html" in headers.get("Content-Type", ""), "Web app index is not HTML"
    asset = web_app_asset(headers, html)
    status, headers, _ = fetch(origin + asset)
    assert status == 200, f"Built web asset returned {status}"
    cache = {part.strip() for part in headers.get("Cache-Control", "").split(",")}
    assert {"immutable", "max-age=31536000"} <= cache, (
        "Built asset cache policy changed"
    )
    assert fetch(origin + "/assets/__release_smoke_missing__.js")[0] == 404
    assert fetch(origin + "/healthz")[0] == 200, "Backend web app is not healthy"
    status, _, body = fetch(origin + "/api/v1/runtime-config")
    assert status == 200, f"Runtime configuration returned {status}"
    config = json.loads(body)
    assert config["version"] == bundle["version"], (
        "Web app version does not match bundle"
    )
    assert config["revision"] == bundle["revision"], (
        "Web app revision does not match bundle"
    )


def verify_browser_session(origin, username, password):
    cookies = CookieJar(policy=LocalhostCookiePolicy())
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.HTTPCookieProcessor(cookies)
    )
    same_origin = {"Sec-Fetch-Site": "same-origin"}
    status, _, _ = fetch(
        origin + "/api/v1/auth/session/password/",
        {**same_origin, "Content-Type": "application/x-www-form-urlencoded"},
        urllib.parse.urlencode({"username": username, "password": password}).encode(),
        opener,
    )
    assert status == 204, f"Browser password login returned {status}"
    assert any(
        cookie.name in {"eneo_web", "__Host-eneo_web"} and cookie.value
        for cookie in cookies
    ), "Browser login did not set a usable session cookie"
    status, headers, _ = fetch(
        origin + "/api/v1/auth/session/", same_origin, opener=opener
    )
    assert status == 204, f"Browser session bootstrap returned {status}"
    generation = headers.get("Eneo-Session-Generation")
    assert generation, "Browser session bootstrap did not identify its generation"
    status, _, body = fetch(
        origin + "/api/v1/users/me/",
        {**same_origin, "Eneo-Session-Generation": generation},
        opener=opener,
    )
    assert status == 200, f"Cookie-authenticated user read returned {status}"
    assert json.loads(body)["email"] == username, (
        "Browser session belongs to another user"
    )


def request(url, payload=None, headers=None, raw=False):
    data = (
        payload
        if isinstance(payload, bytes)
        else json.dumps(payload).encode()
        if payload is not None
        else None
    )
    headers = {"Content-Type": "application/json", **(headers or {})}
    with urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=headers), timeout=60
    ) as response:
        body = response.read()
        return body if raw else json.loads(body)


def main():
    bundle = json.loads(Path(sys.argv[1]).read_text())
    token = secrets.token_hex(32)
    config = json.loads(
        subprocess.check_output(
            [
                "docker",
                "compose",
                "-f",
                str(ROOT / "docker-compose.e2e.ci.yml"),
                "config",
                "--format",
                "json",
            ],
            text=True,
        )
    )
    config["name"] = "eneo-release-smoke"
    # The runtime network is not internal here: the calls below reach the
    # runtime through a published port, which Docker does not map for an
    # internal network. The deployment contract test covers that isolation.
    config["networks"] = {"e2e": {}, "tools": {}}
    backend = config["services"]["e2e-backend"]
    backend.pop("build", None)
    backend["image"] = bundle["images"]["backend"]
    backend["networks"] = ["e2e", "tools"]
    # The e2e stack builds a runtime of its own; this test runs the bundle's.
    del config["services"]["e2e-tool-runtime"]
    backend["depends_on"]["tool-runtime"] = backend["depends_on"].pop(
        "e2e-tool-runtime"
    )
    backend["environment"].update(
        {
            "TOOL_RUNTIME_URL": "http://tool-runtime:3010",
            "TOOL_RUNTIME_TOKEN": token,
            "FILE_REFERENCE_BASE_URL": "http://e2e-backend:8000",
            "WEB_APP_ENABLED": "true",
            "BROWSER_SESSION_ENABLED": "true",
        }
    )
    # /healthz includes the real worker heartbeat. Use the bundle's normal
    # worker entry point after the backend has migrated and seeded the database.
    config["services"]["worker"] = {
        "image": bundle["images"]["backend"],
        "environment": {
            **backend["environment"],
            "RUN_AS_WORKER": "true",
            "WORKER_ROLE": "general",
        },
        "networks": ["e2e", "tools"],
        "depends_on": {"e2e-backend": {"condition": "service_healthy"}},
    }
    config["services"]["tool-runtime"] = {
        "image": bundle["images"]["tool-runtime"],
        "environment": {
            "TOOL_RUNTIME_TOKEN": token,
            "TOOL_RUNTIME_REQUIRE_CONFINEMENT": "true",
            "TOOL_RUNTIME_FILE_ORIGINS": "http://e2e-backend:8000",
        },
        "networks": ["tools"],
        "ports": ["127.0.0.1:8310:3010"],
        "read_only": True,
        "tmpfs": ["/tmp:rw,noexec,nosuid,nodev,size=512m"],
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "mem_limit": "2g",
        "cpus": 2,
        "pids_limit": 256,
    }
    config["services"]["frontend"] = {
        "image": bundle["images"]["frontend"],
        "networks": ["e2e"],
        "ports": ["127.0.0.1:8134:3000"],
        "environment": {
            "ORIGIN": "http://127.0.0.1:8134",
            "PUBLIC_ORIGIN": "http://127.0.0.1:8134",
            "ENEO_BACKEND_URL": "http://e2e-backend:8000",
            "ENEO_BACKEND_SERVER_URL": "http://e2e-backend:8000",
            "PUBLIC_ENEO_BACKEND_URL": BACKEND,
            "JWT_SECRET": backend["environment"]["JWT_SECRET"],
        },
    }
    # The optional Next beta ships in the bundle; it must at least start and
    # answer its health probe against this release's backend.
    config["services"]["web-next"] = {
        "image": bundle["images"]["web-next"],
        "networks": ["e2e"],
        "ports": ["127.0.0.1:8135:3000"],
        "environment": {
            "ENEO_BACKEND_URL": "http://e2e-backend:8000",
            "APP_ORIGIN": WEB_NEXT,
            "SESSION_SECRET": secrets.token_hex(32),
        },
    }
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "compose.json"
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        compose = ["docker", "compose", "-f", str(path), "-p", "eneo-release-smoke"]
        try:
            subprocess.run(
                [*compose, "up", "-d", "--no-build", "--wait", "--wait-timeout", "240"],
                check=True,
            )
            for attempt in range(60):
                try:
                    version = request(BACKEND + "/version")
                    assert version["version"] == bundle["version"]
                    assert version["revision"] == bundle["revision"]
                    request("http://127.0.0.1:8134", raw=True)
                    frontend = request("http://127.0.0.1:8134/eneo-release.json")
                    assert frontend == {
                        "version": bundle["version"],
                        "revision": bundle["revision"],
                    }
                    request(WEB_NEXT + "/healthz", raw=True)
                    assert fetch(WEB_APP + "/healthz")[0] == 200
                    break
                except (OSError, AssertionError):
                    if attempt == 59:
                        raise
                    time.sleep(1)
            verify_web_app(WEB_APP, bundle)
            verify_browser_session(
                WEB_APP,
                backend["environment"]["DEFAULT_USER_EMAIL"],
                backend["environment"]["DEFAULT_USER_PASSWORD"],
            )
            login = request(
                BACKEND + "/api/v1/users/login/token/",
                urllib.parse.urlencode(
                    {"username": "e2e@example.com", "password": "E2ePassword123!"}
                ).encode(),
                {"Content-Type": "application/x-www-form-urlencoded"},
            )
            auth = {"Authorization": "Bearer " + login["access_token"]}
            user = request(BACKEND + "/api/v1/users/me/", headers=auth)
            # Read only the identity claims from the token just issued by our isolated backend.
            claims = json.loads(
                base64.urlsafe_b64decode(login["access_token"].split(".")[1] + "==")
            )
            # Multipart against the real upload API; the file remains scoped to the seeded user.
            boundary = "eneo-release-smoke"
            csv = b"region,amount\\nnorth,10\\nsouth,20\\n".replace(b"\\n", b"\n")
            body = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="upload_file"; filename="smoke.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode()
                + csv
                + f"\r\n--{boundary}--\r\n".encode()
            )
            uploaded = request(
                BACKEND + "/api/v1/files/",
                body,
                {**auth, "Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            signed = request(
                BACKEND + f"/api/v1/files/{uploaded['id']}/original/signed-url/",
                {},
                {**auth, "Host": "e2e-backend:8000"},
            )
            file = {"url": signed["url"], "filename": "smoke.csv"}
            headers = {
                "Authorization": "Bearer " + token,
                "Accept": "application/json, text/event-stream",
                "X-Eneo-Tenant-Id": claims["tenant_id"],
                "X-Eneo-User-Id": user["id"],
                "X-Eneo-File-Origin": "http://e2e-backend:8000",
            }
            diagnostic = request(RUNTIME + "/diagnostics", headers=headers)
            assert (
                diagnostic["version"] == bundle["version"]
                and diagnostic["revision"] == bundle["revision"]
            )
            assert diagnostic["confinement"]["files"]

            def call(endpoint, name, args):
                response = request(
                    RUNTIME + "/mcp/" + endpoint,
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": args},
                    },
                    headers,
                )
                assert "error" not in response, name
                result = response["result"]
                assert not result.get("isError"), name
                return result

            result = call(
                "compute", "run_javascript", {"code": "return input + 1", "input": 41}
            )
            assert result["structuredContent"]["result"] == 42
            call("file-analysis", "inspect_table", {"files": [file]})
            result = call(
                "file-analysis",
                "query_table",
                {
                    "file": file,
                    "sql": "SELECT CAST(SUM(amount) AS DOUBLE) AS total FROM t",
                },
            )
            assert result["structuredContent"]["rows"] == [[30]]
            chart = call(
                "charts",
                "create_chart",
                {
                    "type": "bar",
                    "title": "Release check",
                    "source": {
                        **file,
                        "label_column": "region",
                        "value_columns": ["amount"],
                    },
                    "format": "png",
                },
            )
            assert any(block["type"] == "image" for block in chart["content"])
            document = call(
                "file-creation",
                "create_document",
                {
                    "title": "Release check",
                    "content": "# Verified bundle",
                    "format": "docx",
                },
            )
            assert any(block["type"] == "resource" for block in document["content"])
            logs = subprocess.check_output(
                [*compose, "logs", "--no-log-prefix", "tool-runtime"], text=True
            )
            assert '"revalidated":true,"transferred_bytes":0' in logs
            # Diagnostics agree with the bundle; they do not gate the calls above.
            status = request(BACKEND + "/api/v1/mcp-servers/bundled/", headers=auth)
            assert status["runtime"]["state"] == "ready"
            assert "version_mismatch" not in status["runtime"]["warnings"]
            print(
                "Verified frontend, Next beta, backend web app and browser session, runtime, compute, signed-file analysis, chart, and document."
            )
        finally:
            subprocess.run(
                [*compose, "down", "--volumes", "--remove-orphans"], check=False
            )


if __name__ == "__main__":
    main()
