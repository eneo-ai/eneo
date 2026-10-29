import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


release = module("release_bundle", "scripts/release_bundle.py")
setup = module("deployment_setup", "docs/deployment/setup.py")
smoke = module("smoke_release_bundle", "scripts/smoke_release_bundle.py")


class WebAppSmokeTests(unittest.TestCase):
    def test_secure_cookie_exception_is_limited_to_localhost(self):
        policy = smoke.LocalhostCookiePolicy()
        cookie = SimpleNamespace(secure=True)
        for url, allowed in [
            ("http://localhost:8124/", True),
            ("http://localhost.example.invalid/", False),
            ("https://example.invalid/", True),
        ]:
            with self.subTest(url=url):
                self.assertEqual(
                    policy.return_ok_secure(cookie, urllib.request.Request(url)),
                    allowed,
                )

    def test_index_nonce_must_match_the_policy(self):
        headers = Message()
        headers["Content-Security-Policy"] = "script-src 'self' 'nonce-test-nonce'"
        html = b'<meta property="csp-nonce" nonce="test-nonce"><script type="module" src="/assets/index-test.js"></script>'
        self.assertEqual(smoke.web_app_asset(headers, html), "/assets/index-test.js")
        with self.assertRaises(AssertionError):
            smoke.web_app_asset(headers, html.replace(b"test-nonce", b"wrong-nonce"))

    def test_index_without_an_asset_is_rejected(self):
        headers = Message()
        headers["Content-Security-Policy"] = "script-src 'nonce-test-nonce'"
        with self.assertRaises(AssertionError):
            smoke.web_app_asset(
                headers, b'<meta property="csp-nonce" nonce="test-nonce">'
            )

    def test_browser_session_sends_the_cookie_and_bootstrapped_generation(self):
        observed = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def respond(self, status, headers=None, body=b""):
                self.send_response(status)
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                observed.append((self.path, self.headers.get("Sec-Fetch-Site")))
                self.rfile.read(int(self.headers["Content-Length"]))
                self.respond(
                    204,
                    {
                        "Set-Cookie": "__Host-eneo_web=test-cookie; Path=/; Secure; HttpOnly"
                    },
                )

            def do_GET(self):
                if self.path == "/redirect":
                    self.respond(303, {"Location": "/api/v1/auth/session/password/"})
                    return
                if self.path == "/missing":
                    self.respond(404, body=b"missing")
                    return
                if self.headers.get("Cookie") != "__Host-eneo_web=test-cookie":
                    self.respond(401)
                    return
                if self.path == "/api/v1/auth/session/":
                    self.respond(204, {"Eneo-Session-Generation": "test-generation"})
                    return
                observed.append(
                    (self.path, self.headers.get("Eneo-Session-Generation"))
                )
                if self.headers.get("Eneo-Session-Generation") != "test-generation":
                    self.respond(401)
                    return
                self.respond(200, body=b'{"email":"smoke@example.invalid"}')

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            origin = f"http://localhost:{server.server_port}"
            try:
                smoke.verify_browser_session(
                    origin, "smoke@example.invalid", "test-password"
                )
                self.assertEqual(smoke.fetch(origin + "/redirect")[0], 303)
                status, _, body = smoke.fetch(origin + "/missing")
                self.assertEqual((status, body), (404, b"missing"))
            finally:
                server.shutdown()
                thread.join()
        self.assertEqual(
            observed,
            [
                ("/api/v1/auth/session/password/", "same-origin"),
                ("/api/v1/users/me/", "test-generation"),
            ],
        )


class ReleaseTests(unittest.TestCase):
    def test_frontend_runtime_gate_rejects_unpatched_node_versions(self):
        workflow = (ROOT / ".github/workflows/application_image.yml").read_text()
        gate = re.search(
            r'--entrypoint node "\$IMAGE" -e \'\n(.*?)\n\s*\'',
            workflow,
            re.DOTALL,
        )
        self.assertIsNotNone(
            gate, "Published frontend images must check their Node runtime"
        )
        program = """
const vm = require('node:vm');
vm.runInNewContext(process.argv[1], {
  process: { versions: { node: process.argv[2] } },
  console: { log() {} }
});
"""
        for version, allowed in [
            ("20.20.2", False),
            ("22.22.0", False),
            ("22.23.3", False),
            ("22.23.4", True),
            ("22.24.0", True),
        ]:
            with self.subTest(version=version):
                result = subprocess.run(
                    ["node", "-e", program, gate.group(1), version],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode == 0, allowed, result.stderr)

    def test_shared_identity(self):
        sha = "a" * 40
        for ref, expected in [
            ("refs/tags/v2.3.0", "2.3.0"),
            ("refs/tags/v2.3.0-rc.1", "2.3.0-rc.1"),
            ("refs/heads/develop", "develop-" + sha[:12]),
            ("refs/heads/feat/runtime", "feat-runtime-" + sha[:12]),
        ]:
            self.assertEqual(release.resolve(ref, sha)["version"], expected)
        with self.assertRaises(ValueError):
            release.resolve("refs/tags/not-a-version", sha)

    def test_incomplete_or_mutable_bundle_is_rejected(self):
        images = {
            c: release.REGISTRY + c + "@sha256:" + "b" * 64 for c in release.COMPONENTS
        }
        result = release.bundle("2.3.0", "a" * 40, images)
        self.assertEqual(len(result["images"]), 4)
        self.assertIn("web-next", result["images"])
        for bad in [{}, {**images, "backend": release.REGISTRY + "backend:latest"}]:
            with self.assertRaises(ValueError):
                release.bundle("2.3.0", "a" * 40, bad)

    def test_promotion_never_rewinds(self):
        self.assertFalse(
            release.may_promote(
                "refs/tags/v2.2.0", "a" * 40, ["v2.3.0", "v2.2.0"], None
            )
        )
        self.assertFalse(
            release.may_promote("refs/tags/v2.4.0-rc.1", "a" * 40, ["v2.3.0"], None)
        )
        self.assertFalse(
            release.may_promote("refs/heads/develop", "a" * 40, [], "b" * 40)
        )
        self.assertTrue(
            release.may_promote("refs/heads/develop", "a" * 40, [], "a" * 40)
        )
        self.assertTrue(
            release.may_promote(
                "refs/tags/v2.3.0", "a" * 40, ["v2.3.0", "v2.2.0"], None
            )
        )

    def test_existing_image_source_must_match(self):
        manifest = {
            "manifests": [
                {
                    "digest": "sha256:" + "b" * 64,
                    "platform": {"os": "linux", "architecture": "amd64"},
                }
            ]
        }
        import json

        with (
            patch.object(release, "inspect", return_value=manifest),
            patch.object(
                release,
                "run",
                side_effect=[
                    json.dumps({"digest": "sha256:" + "b" * 64}),
                    json.dumps(
                        {
                            "config": {
                                "Labels": {
                                    "org.opencontainers.image.version": "2.3.0",
                                    "org.opencontainers.image.revision": "c" * 40,
                                }
                            }
                        }
                    ),
                ],
            ),
        ):
            with self.assertRaises(ValueError):
                release.verify_image("backend", "2.3.0", "a" * 40)

    def test_partial_publication_never_writes_a_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bundle"
            with (
                patch.dict(
                    os.environ,
                    {"GITHUB_REF": "refs/tags/v2.3.0", "GITHUB_SHA": "a" * 40},
                ),
                patch(
                    "sys.argv", ["release_bundle.py", "bundle", "--output", str(output)]
                ),
                patch.object(
                    release, "verify_image", side_effect=["sha256:" + "b" * 64, None]
                ),
            ):
                with self.assertRaisesRegex(ValueError, "Missing image"):
                    release.main()
            self.assertFalse(output.exists())

    def test_retry_reuses_attested_matching_image(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            with (
                patch.dict(
                    os.environ,
                    {
                        "GITHUB_REF": "refs/tags/v2.3.0",
                        "GITHUB_SHA": "a" * 40,
                        "GITHUB_OUTPUT": str(output),
                        "GITHUB_REPOSITORY": "eneo-ai/eneo",
                    },
                ),
                patch(
                    "sys.argv", ["release_bundle.py", "reuse", "--component", "backend"]
                ),
                patch.object(
                    release, "verify_image", return_value="sha256:" + "b" * 64
                ) as verify,
                patch.object(release, "run", return_value="verified") as run,
            ):
                release.main()
            verify.assert_called_once_with("backend", "2.3.0", "a" * 40)
            run.assert_called_once_with(
                "gh",
                "attestation",
                "verify",
                "oci://" + release.REGISTRY + "backend@sha256:" + "b" * 64,
                "--repo",
                "eneo-ai/eneo",
            )
            self.assertIn("exists=true", output.read_text())
            self.assertIn("digest=sha256:" + "b" * 64, output.read_text())

    def test_runtime_requires_both_supported_architectures(self):
        with (
            patch.object(release, "inspect", return_value={"manifests": []}),
            patch.object(
                release,
                "run",
                return_value=json.dumps({"digest": "sha256:" + "b" * 64}),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "Unexpected platforms"):
                release.verify_image("tool-runtime", "2.3.0", "a" * 40)

    def test_setup_is_idempotent_and_preserves_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "# deployment\nCUSTOM=keep\nTOOL_RUNTIME_TOKEN=\n"
            )
            setup.configure(root, "v2.3.0")
            first = (root / ".env").read_text()
            setup.configure(root, "2.4.0")
            self.assertEqual(first, (root / ".env").read_text())
            self.assertIn("CUSTOM=keep", first)
            self.assertIn("ENEO_VERSION=2.3.0", first)
            self.assertEqual((root / ".env").stat().st_mode & 0o777, 0o600)
            token = next(
                line.split("=", 1)[1]
                for line in first.splitlines()
                if line.startswith("TOOL_RUNTIME_TOKEN=")
            )
            self.assertEqual(len(token), 64)

    def test_setup_migrates_existing_backend_overrides_without_rotating_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text('TOOL_RUNTIME_TOKEN="" # empty default\n')
            (root / "env_backend.env").write_text(
                'TOOL_RUNTIME_TOKEN="existing-token"\n'
                "TOOL_RUNTIME_URL=http://existing-tools:3010\n"
                "FILE_REFERENCE_BASE_URL=http://existing-backend:8000\n"
            )
            setup.configure(root)
            first = (root / ".env").read_text()
            self.assertIn('TOOL_RUNTIME_TOKEN="existing-token"', first)
            self.assertIn("TOOL_RUNTIME_URL=http://existing-tools:3010", first)
            self.assertIn("FILE_REFERENCE_BASE_URL=http://existing-backend:8000", first)
            setup.configure(root)
            self.assertEqual(first, (root / ".env").read_text())

    def test_bundle_gate_and_default_deployment(self):
        workflow = (ROOT / ".github/workflows/build_and_push_images.yml").read_text()
        self.assertLess(
            workflow.index("Smoke test the exact bundle"),
            workflow.index("Publish complete bundle"),
        )
        self.assertLess(
            workflow.index("Publish complete bundle"), workflow.index("Promote aliases")
        )
        compose = (ROOT / "docs/deployment/docker-compose.yml").read_text()
        self.assertNotIn("eneo-backend:latest", compose)
        self.assertNotIn("eneo-frontend:latest", compose)
        self.assertIn("  tool-runtime:", compose)
        self.assertNotIn("profiles:", compose)
        self.assertFalse((ROOT / "tool-runtime/VERSION").exists())


class ComposeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI required")
    def test_bundle_pins_every_service_and_legacy_overlay_is_inert(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "docker-compose.yml",
                "docker-compose.tool-runtime.yml",
                "docker-compose.without-tools.yml",
                "docker-compose.web-next.yml",
            ):
                shutil.copy(ROOT / "docs/deployment" / name, root / name)
            for name in ("backend", "frontend", "db", "web_next"):
                (root / f"env_{name}.env").write_text("")
            images = {
                c: release.REGISTRY + c + "@sha256:" + "b" * 64
                for c in release.COMPONENTS
            }
            env = {
                "PATH": os.environ["PATH"],
                "ENEO_VERSION": "2.3.0",
                "TOOL_RUNTIME_TOKEN": "x" * 64,
                **{
                    "ENEO_" + c.upper().replace("-", "_") + "_IMAGE": ref
                    for c, ref in images.items()
                },
            }

            def config(*overlays):
                args = ["docker", "compose", "-f", str(root / "docker-compose.yml")]
                for overlay in overlays:
                    args += ["-f", str(root / overlay)]
                return json.loads(
                    subprocess.check_output(
                        [*args, "config", "--format", "json"], env=env, text=True
                    )
                )

            normal = config()
            self.assertEqual(normal, config("docker-compose.tool-runtime.yml"))
            services = normal["services"]
            for name in ("backend", "worker", "crawler-worker", "db-init"):
                self.assertEqual(services[name]["image"], images["backend"])
                self.assertNotIn("tool-runtime", services[name].get("depends_on", {}))
            runtime = services["tool-runtime"]
            self.assertEqual(runtime["image"], images["tool-runtime"])
            self.assertTrue(runtime["read_only"])
            self.assertNotIn("POSTGRES_PASSWORD", runtime["environment"])
            self.assertTrue(normal["networks"]["tool_runtime_net"]["internal"])
            omitted = config("docker-compose.without-tools.yml")
            self.assertNotIn("tool-runtime", omitted["services"])
            self.assertEqual(
                omitted["services"]["backend"]["environment"]["TOOL_RUNTIME_URL"], ""
            )
            # The beta overlay adds nothing until its profile is enabled, and
            # then runs the bundle's web-next image against the same backend.
            env["WEB_NEXT_HOST"] = "beta.example.com"
            self.assertNotIn(
                "web-next", config("docker-compose.web-next.yml")["services"]
            )
            env["COMPOSE_PROFILES"] = "web-next"
            beta = config("docker-compose.web-next.yml")["services"]["web-next"]
            del env["COMPOSE_PROFILES"]
            self.assertEqual(beta["image"], images["web-next"])
            self.assertEqual(
                beta["environment"]["ENEO_BACKEND_URL"], "http://backend:8000"
            )
            self.assertIn("backend", beta["depends_on"])
            env["FILE_REFERENCE_BASE_URL"] = "http://custom-backend:8000"
            custom = config()["services"]
            self.assertEqual(
                custom["tool-runtime"]["environment"]["TOOL_RUNTIME_FILE_ORIGINS"],
                "http://custom-backend:8000",
            )
            self.assertEqual(
                custom["worker"]["environment"]["FILE_REFERENCE_BASE_URL"],
                "http://custom-backend:8000",
            )


if __name__ == "__main__":
    unittest.main()
