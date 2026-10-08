#!/usr/bin/env python3
"""CI-only smoke test: exact published images, isolated database, real signed files."""

import base64
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = "http://127.0.0.1:8124"
RUNTIME = "http://127.0.0.1:8310"


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
    config["networks"] = {"e2e": {}, "tools": {"internal": True}}
    backend = config["services"]["e2e-backend"]
    backend.pop("build", None)
    backend["image"] = bundle["images"]["backend"]
    backend["networks"] = ["e2e", "tools"]
    backend["environment"].update(
        {
            "TOOL_RUNTIME_URL": "http://tool-runtime:3010",
            "TOOL_RUNTIME_TOKEN": token,
            "FILE_REFERENCE_BASE_URL": "http://e2e-backend:8000",
        }
    )
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
                    break
                except (OSError, AssertionError):
                    if attempt == 59:
                        raise
                    time.sleep(1)
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
                "Verified frontend, backend, runtime, compute, signed-file analysis, chart, and document."
            )
        finally:
            subprocess.run(
                [*compose, "down", "--volumes", "--remove-orphans"], check=False
            )


if __name__ == "__main__":
    main()
