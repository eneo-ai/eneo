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
        headers["Content-Security-Policy"] = (
            "script-src 'self' 'nonce-test-nonce' 'strict-dynamic'"
        )
        html = b'<meta property="csp-nonce" nonce="test-nonce"><script type="module" nonce="test-nonce" src="/assets/index-test.js"></script>'
        self.assertEqual(smoke.web_app_asset(headers, html), "/assets/index-test.js")
        with self.assertRaises(AssertionError):
            smoke.web_app_asset(headers, html.replace(b"test-nonce", b"wrong-nonce"))

    def test_entry_script_must_have_a_nonce_allowed_by_script_src(self):
        headers = Message()
        headers["Content-Security-Policy"] = (
            "script-src 'self' 'nonce-test-nonce' 'strict-dynamic'"
        )
        for nonce in [b"", b'nonce="wrong-nonce"']:
            with self.subTest(nonce=nonce):
                html = (
                    b'<meta property="csp-nonce" nonce="test-nonce"><script src="/assets/index.js" '
                    + nonce
                    + b"></script>"
                )
                with self.assertRaises(AssertionError):
                    smoke.web_app_asset(headers, html)
        headers.replace_header(
            "Content-Security-Policy", "script-src 'none'; style-src 'nonce-test-nonce'"
        )
        with self.assertRaises(AssertionError):
            smoke.web_app_asset(
                headers,
                b'<meta property="csp-nonce" nonce="test-nonce"><script src="/assets/index.js" nonce="test-nonce"></script>',
            )

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
        self.assertEqual(set(result["images"]), {"backend", "frontend", "tool-runtime"})
        self.assertNotIn("web-next", result["images"])
        for bad in [{}, {**images, "backend": release.REGISTRY + "backend:latest"}]:
            with self.assertRaises(ValueError):
                release.bundle("2.3.0", "a" * 40, bad)

    def test_promotion_never_rewinds(self):
        self.assertFalse(release.may_promote("refs/tags/v2.2.0", "a" * 40, ["v2.3.0", "v2.2.0"]))
        self.assertFalse(release.may_promote("refs/tags/v2.4.0-rc.1", "a" * 40, ["v2.3.0"]))
        self.assertTrue(release.may_promote("refs/tags/v2.3.0", "a" * 40, ["v2.3.0", "v2.2.0"]))
        # An unprefixed tag is not a release and never outranks one.
        self.assertTrue(release.may_promote("refs/tags/v2.3.0", "a" * 40, ["v2.3.0", "99.0.0"]))
        with self.assertRaises(ValueError):
            release.may_promote("refs/heads/develop", "a" * 40, [])

    def test_a_branch_alias_moves_forward_and_repairs_but_never_back(self):
        # develop: one -> two -> three -> four (head); "old" is no longer on it.
        line = ["one", "two", "three", "four"]

        def contains(ancestor, descendant):
            return ancestor in line and descendant in line and line.index(ancestor) <= line.index(descendant)

        def moves(revision, destinations, head="four"):
            return release.may_move_branch_alias(revision, head, destinations, contains)

        self.assertTrue(moves("two", [None, None, None]))  # bootstrap
        self.assertTrue(moves("three", ["two", "two", "two"]))  # forward
        self.assertTrue(moves("three", ["three", "two", "two"]))  # (B, A, A) is repaired to B
        self.assertTrue(moves("three", ["three"] * 3))  # a retry rewrites the same revision
        self.assertFalse(moves("two", ["three", "two", "two"]))  # B is refused once one is at C
        self.assertFalse(moves("three", ["two", "four", "two"]))
        self.assertTrue(moves("four", ["old", "two", None]))  # an alias left by a rebase follows
        self.assertTrue(moves("three", ["two"] * 3, head="four"))  # the branch moved on meanwhile
        self.assertFalse(moves("old", ["two"] * 3))  # a commit off the branch never moves it
        self.assertFalse(moves("three", ["two"] * 3, head=None))  # the branch is gone
        # A revert is a new commit after the one it reverts: forward like any other.
        line.append("revert-of-four")
        self.assertTrue(moves("revert-of-four", ["four"] * 3, head="revert-of-four"))

    def test_an_unreadable_alias_is_not_an_absent_one(self):
        manifest = {"digest": "sha256:" + "d" * 64, "manifests": [
            {"digest": "sha256:" + "1" * 64, "platform": {"os": "linux", "architecture": "amd64"}},
            {"digest": "sha256:" + "2" * 64, "platform": {"os": "linux", "architecture": "arm64"}},
        ]}
        label = lambda revision: json.dumps({"config": {"Labels": {"org.opencontainers.image.revision": revision}}})
        with patch.object(release, "inspect", return_value=None):
            self.assertEqual(release.alias_state("backend", "develop"), (None, None))
        with patch.object(release, "inspect", return_value=manifest), patch.object(release, "run", side_effect=[label("a" * 40)] * 2):
            self.assertEqual(release.alias_state("tool-runtime", "develop"), (manifest["digest"], "a" * 40))
        for labels in ([label("a" * 40), label("b" * 40)], [json.dumps({}), json.dumps({})]):
            with patch.object(release, "inspect", return_value=manifest), patch.object(release, "run", side_effect=labels):
                with self.assertRaisesRegex(ValueError, "Cannot read the source revision"):
                    release.alias_state("tool-runtime", "develop")
        with patch.object(release, "inspect", side_effect=RuntimeError("Cannot verify registry image")):
            with self.assertRaises(RuntimeError):
                release.alias_state("backend", "develop")

    def test_promotion_writes_and_checks_the_bundled_digests(self):
        images = {c: f"{release.REGISTRY}{c}@sha256:" + str(i) * 64 for i, c in enumerate(release.COMPONENTS, 1)}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.json"
            path.write_text(json.dumps(release.bundle("develop-" + "a" * 12, "a" * 40, images)))
            history = ["b" * 40, "a" * 40]
            written = {}

            def run(*args):
                if args[:2] == ("git", "ls-remote"):
                    return "a" * 40 + "\trefs/heads/develop"
                if args[:2] == ("git", "rev-parse"):
                    return "a" * 40
                if args[:4] == ("docker", "buildx", "imagetools", "create"):
                    written[args[5].rsplit(":", 1)[0]] = args[6]
                return ""

            def state(component, alias):
                image = written.get(release.REGISTRY + component)
                return (image.rsplit("@", 1)[1], "a" * 40) if image else (None, "b" * 40 if component == "backend" else None)

            env = {"GITHUB_REF": "refs/heads/develop", "GITHUB_SHA": "a" * 40}
            with (
                patch.dict(os.environ, env),
                patch("sys.argv", ["release_bundle.py", "promote", "--bundle", str(path)]),
                patch.object(release, "run", side_effect=run),
                patch.object(release, "alias_state", side_effect=state),
                patch.object(release, "contains", side_effect=lambda a, b: history.index(a) <= history.index(b)),
                patch.object(release, "verify_image") as by_tag,
                patch.object(release, "verify_digest", side_effect=lambda c, d, v, r: d) as by_digest,
            ):
                release.main()
            by_tag.assert_not_called()
            # Every bundled image is checked again, by digest, against this version and revision.
            self.assertEqual(
                sorted(call.args for call in by_digest.call_args_list),
                sorted((c, i.rsplit("@", 1)[1], "develop-" + "a" * 12, "a" * 40) for c, i in images.items()),
            )
            self.assertEqual(written, {release.REGISTRY + c: images[c] for c in release.COMPONENTS})
            # An alias that does not name the bundled digest after the write fails the job.
            with (
                patch.dict(os.environ, env),
                patch("sys.argv", ["release_bundle.py", "promote", "--bundle", str(path)]),
                patch.object(release, "run", side_effect=run),
                patch.object(release, "alias_state", return_value=("sha256:" + "f" * 64, "a" * 40)),
                patch.object(release, "contains", return_value=True),
                patch.object(release, "verify_digest", side_effect=lambda c, d, v, r: d),
            ):
                with self.assertRaisesRegex(ValueError, "does not name"):
                    release.main()
            # A bundle for another revision is refused before anything is read or written.
            path.write_text(json.dumps(release.bundle("develop-" + "b" * 12, "b" * 40, images)))
            with (
                patch.dict(os.environ, env),
                patch("sys.argv", ["release_bundle.py", "promote", "--bundle", str(path)]),
                patch.object(release, "run") as run_mock,
            ):
                with self.assertRaisesRegex(ValueError, "different version or source"):
                    release.main()
                run_mock.assert_not_called()

    def test_reserved_aliases_and_unprefixed_tags_publish_nothing(self):
        sha = "a" * 40
        for ref in (
            "refs/heads/latest", "refs/heads/DEVELOP", "refs/heads/develop-", "refs/tags/1.2.3",
            # Aliases shaped like a release's or a branch's version tag.
            "refs/heads/2.3.0", "refs/heads/2.3.0-rc.1", "refs/heads/develop-aaaaaaaaaaaa",
            "refs/heads/feat/x-0123456789ab",
        ):
            with self.assertRaises(ValueError, msg=ref):
                release.resolve(ref, sha)
        self.assertEqual(release.resolve("refs/heads/develop", sha)["alias"], "develop")
        self.assertEqual(release.resolve("refs/heads/feat/v2-layout", sha)["alias"], "feat-v2-layout")

    def test_deployment_environment_is_derived_from_the_complete_bundle(self):
        images = {c: release.REGISTRY + c + "@sha256:" + "b" * 64 for c in reversed(release.COMPONENTS)}
        content = release.environment("2.4.0", "a" * 40, images)
        values = dict(line.split("=", 1) for line in content.splitlines())
        self.assertEqual(values["ENEO_VERSION"], "2.4.0")
        self.assertEqual(values["ENEO_REVISION"], "a" * 40)
        for component, image in images.items():
            self.assertEqual(values[f"ENEO_{component.upper().replace('-', '_')}_IMAGE"], image)
        with self.assertRaises(ValueError):
            release.environment("2.4.0", "a" * 40, {})

    def test_trusted_controller_resolves_the_tag_instead_of_its_default_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs"
            with patch.dict(os.environ, {"GITHUB_REF": "refs/heads/develop", "GITHUB_SHA": "b" * 40, "GITHUB_OUTPUT": str(output)}), patch(
                "sys.argv", ["release_bundle.py", "resolve", "--ref", "refs/tags/v2.4.0", "--revision", "a" * 40]
            ):
                release.main()
            self.assertIn("version=2.4.0\n", output.read_text())
            self.assertIn("revision=" + "a" * 40 + "\n", output.read_text())

    def test_existing_image_source_must_match(self):
        manifest = {
            "digest": "sha256:" + "d" * 64,
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
                    "sys.argv",
                    ["release_bundle.py", "bundle", "--output", str(output),
                     "--digest", "backend=sha256:" + "b" * 64, "--digest", "frontend="],
                ),
                patch.object(release, "verify_digest", side_effect=lambda c, d, v, r: d),
            ):
                with self.assertRaisesRegex(ValueError, "Missing image: frontend"):
                    release.main()
            self.assertFalse(output.exists())

    def test_bundle_names_the_digests_the_component_jobs_checked(self):
        digests = {c: "sha256:" + str(i) * 64 for i, c in enumerate(release.COMPONENTS, 1)}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bundle"
            with (
                patch.dict(os.environ, {"GITHUB_REF": "refs/tags/v2.3.0", "GITHUB_SHA": "a" * 40}),
                patch(
                    "sys.argv",
                    ["release_bundle.py", "bundle", "--output", str(output)]
                    + [arg for c, d in digests.items() for arg in ("--digest", f"{c}={d}")],
                ),
                patch.object(release, "verify_digest", side_effect=lambda c, d, v, r: d) as verify,
                patch.object(release, "verify_image") as by_tag,
            ):
                release.main()
            by_tag.assert_not_called()
            self.assertEqual(
                sorted(call.args for call in verify.call_args_list),
                sorted((c, d, "2.3.0", "a" * 40) for c, d in digests.items()),
            )
            recorded = json.loads((output / "release.json").read_text())
            self.assertEqual(
                recorded["images"], {c: f"{release.REGISTRY}{c}@{d}" for c, d in digests.items()}
            )

    def test_a_tag_that_moves_between_reads_cannot_swap_the_checked_image(self):
        # The tag is read once; its platforms and labels are read by digest.
        child = "sha256:" + "c" * 64
        manifest = {
            "digest": "sha256:" + "d" * 64,
            "manifests": [{"digest": child, "platform": {"os": "linux", "architecture": "amd64"}}],
        }
        labels = {"config": {"Labels": {
            "org.opencontainers.image.version": "2.3.0",
            "org.opencontainers.image.revision": "a" * 40,
        }}}
        with (
            patch.object(release, "inspect", return_value=manifest) as inspect,
            patch.object(release, "run", return_value=json.dumps(labels)) as run,
        ):
            self.assertEqual(release.verify_image("backend", "2.3.0", "a" * 40), manifest["digest"])
        inspect.assert_called_once_with(release.REGISTRY + "backend:2.3.0")
        self.assertEqual(run.call_args.args[4], release.REGISTRY + "backend@" + child)
        # A digest the registry answers for with another manifest is refused.
        with patch.object(release, "inspect", return_value={**manifest, "digest": "sha256:" + "e" * 64}):
            with self.assertRaisesRegex(ValueError, "Cannot read"):
                release.verify_digest("backend", "sha256:" + "d" * 64, "2.3.0", "a" * 40)
        with self.assertRaisesRegex(ValueError, "Invalid digest"):
            release.verify_digest("backend", "backend:latest", "2.3.0", "a" * 40)

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

    def test_retry_rebuilds_instead_of_reusing_unverified_image(self):
        for verification in (
            "verified",
            subprocess.CalledProcessError(1, ["gh", "attestation", "verify"]),
            subprocess.CalledProcessError(4, ["gh", "attestation", "verify"]),
        ):
            with (
                self.subTest(verification=verification),
                tempfile.TemporaryDirectory() as directory,
            ):
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
                        "sys.argv",
                        ["release_bundle.py", "reuse", "--component", "frontend"],
                    ),
                    patch.object(
                        release, "verify_image", return_value="sha256:" + "b" * 64
                    ),
                    patch.object(release, "run", side_effect=[verification]),
                ):
                    release.main()
                expected = (
                    "exists=true\ndigest=sha256:" + "b" * 64 + "\n"
                    if verification == "verified"
                    else "exists=false\ndigest=\n"
                )
                self.assertEqual(output.read_text(), expected)

    def test_retry_never_rebuilds_on_registry_or_identity_errors(self):
        for failure in (
            ValueError("Refusing to replace image: version or source revision differs"),
            ValueError("Unexpected platforms"),
            RuntimeError("Cannot verify registry image: access denied"),
        ):
            with (
                self.subTest(failure=failure),
                tempfile.TemporaryDirectory() as directory,
            ):
                output = Path(directory) / "output"
                with (
                    patch.dict(
                        os.environ,
                        {
                            "GITHUB_REF": "refs/tags/v2.3.0",
                            "GITHUB_SHA": "a" * 40,
                            "GITHUB_OUTPUT": str(output),
                        },
                    ),
                    patch(
                        "sys.argv",
                        ["release_bundle.py", "reuse", "--component", "frontend"],
                    ),
                    patch.object(release, "verify_image", side_effect=failure),
                ):
                    with self.assertRaises(type(failure)):
                        release.main()
                self.assertFalse(output.exists())

    def test_failed_frontend_checks_leave_attested_image_for_retry(self):
        workflow = (ROOT / ".github/workflows/application_image.yml").read_text()
        self.assertLess(
            workflow.index("Build immutable component image"),
            workflow.index("Attest component provenance"),
        )
        self.assertLess(
            workflow.index("Attest component provenance"),
            workflow.index("Release build disk space"),
        )
        self.assertLess(
            workflow.index("Release build disk space"),
            workflow.index("Verify frontend runtime"),
        )
        self.assertLess(
            workflow.index("Verify frontend runtime"),
            workflow.index("Block frontend HIGH and CRITICAL vulnerabilities"),
        )
        # Reuse still has to pass both gates; attestation alone must not bypass them.
        for name in (
            "Verify frontend runtime",
            "Block frontend HIGH and CRITICAL vulnerabilities",
        ):
            step = workflow.split(f"- name: {name}\n", 1)[1].split("\n      - ", 1)[0]
            self.assertNotIn("steps.reuse.outputs.exists", step)
        self.assertIn("fail-build: true", workflow)
        self.assertIn("severity-cutoff: high", workflow)
        self.assertIn("sudo swapoff /mnt/eneo-frontend.swap", workflow)
        self.assertIn("docker buildx prune --all --force", workflow)

    def test_runtime_requires_both_supported_architectures(self):
        with (
            patch.object(
                release, "inspect", return_value={"digest": "sha256:" + "b" * 64, "manifests": []}
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
    def test_release_smoke_runs_every_backend_role_on_the_bundle_image(self):
        # Kills: only e2e-backend is swapped, so a worker role keeps the
        # locally built image name and the smoke's --no-build start fails.
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
        services = config["services"]
        local = services["e2e-backend"]["image"]
        roles = [name for name, s in services.items() if s.get("image") == local]
        self.assertIn("task-execution-worker", roles)
        image = release.REGISTRY + "backend@sha256:" + "c" * 64
        smoke.use_bundle_backend(services, image, "token")
        for name in roles:
            self.assertEqual(services[name]["image"], image)
            self.assertNotIn("build", services[name])
            self.assertEqual(
                services[name]["environment"]["TOOL_RUNTIME_URL"],
                "http://tool-runtime:3010",
            )

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI required")
    def test_native_web_app_tool_frames_allow_the_browser_origin(self):
        config = json.loads(
            subprocess.check_output(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(ROOT / "docker-compose.e2e.ci.yml"),
                    "-f",
                    str(ROOT / "docker-compose.e2e.web-app.yml"),
                    "config",
                    "--format",
                    "json",
                ],
                env={**os.environ, "E2E_APP_CONTENT_ORIGIN": ""},
                text=True,
            )
        )
        backend = config["services"]["e2e-backend"]
        port = next(p["published"] for p in backend["ports"] if p["target"] == 8000)
        self.assertEqual(
            backend["environment"]["PUBLIC_ORIGIN"], f"http://localhost:{port}"
        )
        self.assertEqual(
            backend["environment"]["MCP_APP_CONTENT_BASE_URL"],
            f"http://127.0.0.1:{port}",
        )

    def deployment_config(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(directory)
        for name in (
            "docker-compose.yml",
            "docker-compose.tool-runtime.yml",
            "docker-compose.without-tools.yml",
            "docker-compose.web-next.yml",
        ):
            shutil.copy(ROOT / "docs/deployment" / name, root / name)
        for name in ("backend", "frontend", "db"):
            (root / f"env_{name}.env").write_text("")
        images = {
            c: release.REGISTRY + c + "@sha256:" + "b" * 64 for c in release.COMPONENTS
        }
        env = {
            "PATH": os.environ["PATH"],
            "ENEO_VERSION": "2.3.0",
            "TOOL_RUNTIME_TOKEN": "x" * 64,
            **{
                name: "c" * 64
                for name in (
                    "TRAEFIK_IMAGE_DIGEST",
                    "PGVECTOR_IMAGE_DIGEST",
                    "REDIS_IMAGE_DIGEST",
                )
            },
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

        return config, env, images

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI required")
    def test_main_host_serves_react_and_preserves_svelte_rollback(self):
        config, env, _ = self.deployment_config()
        for priority in (None, "7"):
            with self.subTest(priority=priority):
                if priority is not None:
                    env["FRONTEND_ROUTER_PRIORITY"] = priority
                services = config()["services"]
                backend = services["backend"]
                for flag in ("WEB_APP_ENABLED", "BROWSER_SESSION_ENABLED"):
                    self.assertEqual(backend["environment"].get(flag), "true")
                labels = backend["labels"]
                app = "traefik.http.routers.eneo-web-app-main-secure"
                api = "traefik.http.routers.eneo-backend-secure"
                self.assertEqual(
                    labels[app + ".rule"],
                    "Host(`your-domain.com`) && !(Path(`/internal-mcp`) || PathPrefix(`/internal-mcp/`))",
                )
                self.assertEqual(labels[app + ".entrypoints"], "websecure")
                self.assertEqual(labels[app + ".tls"], "true")
                self.assertEqual(labels[app + ".tls.certresolver"], "letsencrypt")
                self.assertEqual(labels[app + ".service"], "eneo-backend-svc")
                self.assertEqual(labels[app + ".priority"], "5")
                self.assertEqual(labels[api + ".priority"], "10")
                frontend = services["frontend"]["labels"]
                self.assertEqual(
                    frontend["traefik.http.routers.eneo-frontend-secure.priority"],
                    priority or "1",
                )
                self.assertLess(int(priority or "1"), int(labels[api + ".priority"]))
                if priority:
                    self.assertGreater(int(priority), int(labels[app + ".priority"]))
                else:
                    self.assertLess(1, int(labels[app + ".priority"]))

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI required")
    def test_beta_overlay_preserves_main_host_rollback_and_api_priority(self):
        config, env, _ = self.deployment_config()
        for host in ("your-domain.com", "beta.example.com"):
            for priority in ("1", "7"):
                with self.subTest(host=host, priority=priority):
                    env.update(WEB_NEXT_HOST=host, FRONTEND_ROUTER_PRIORITY=priority)
                    normal = config()["services"]
                    services = config("docker-compose.web-next.yml")["services"]
                    self.assertEqual(services["frontend"], normal["frontend"])
                    labels = services["backend"]["labels"]
                    main = "traefik.http.routers.eneo-web-app-main-secure"
                    api = "traefik.http.routers.eneo-backend-secure"
                    for router in ("eneo-web-next", "eneo-web-next-secure"):
                        prefix = f"traefik.http.routers.{router}"
                        self.assertEqual(
                            labels[prefix + ".rule"],
                            f"Host(`{host}`) && !(Path(`/internal-mcp`) || PathPrefix(`/internal-mcp/`))",
                        )
                        self.assertEqual(
                            labels[prefix + ".service"], "eneo-backend-svc"
                        )
                        self.assertEqual(labels[prefix + ".priority"], "5")
                        self.assertLess(
                            int(labels[prefix + ".priority"]),
                            int(labels[api + ".priority"]),
                        )
                        if priority == "7":
                            self.assertLess(
                                int(labels[prefix + ".priority"]), int(priority)
                            )
                    self.assertEqual(
                        labels[main + ".rule"],
                        normal["backend"]["labels"][main + ".rule"],
                    )
                    self.assertEqual(
                        labels[api + ".rule"],
                        normal["backend"]["labels"][api + ".rule"],
                    )
                    self.assertEqual(labels[api + ".priority"], "10")
                    for service in services.values():
                        for label in service.get("labels", {}):
                            self.assertNotIn("stsseconds", label.lower())
                            self.assertNotIn("strict-transport-security", label.lower())

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI required")
    def test_bundle_pins_every_service_and_legacy_overlay_is_inert(self):
        config, env, images = self.deployment_config()
        normal = config()
        self.assertEqual(normal, config("docker-compose.tool-runtime.yml"))
        services = normal["services"]
        for name, repository in (
            ("traefik", "traefik"),
            ("db", "pgvector/pgvector"),
            ("redis", "redis"),
        ):
            self.assertEqual(
                services[name]["image"], repository + "@sha256:" + "c" * 64
            )
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
        env["WEB_NEXT_HOST"] = "beta.example.com"
        beta = config("docker-compose.web-next.yml")["services"]
        self.assertNotIn("web-next", beta)
        self.assertEqual(beta["frontend"], services["frontend"])
        backend = beta["backend"]
        self.assertEqual(backend["image"], images["backend"])
        for flag in ("WEB_APP_ENABLED", "BROWSER_SESSION_ENABLED"):
            self.assertEqual(backend["environment"][flag], "true")
        labels = backend["labels"]
        rule = "Host(`beta.example.com`) && !(Path(`/internal-mcp`) || PathPrefix(`/internal-mcp/`))"
        for router in ("eneo-web-next", "eneo-web-next-secure"):
            self.assertEqual(labels[f"traefik.http.routers.{router}.rule"], rule)
            self.assertEqual(
                labels[f"traefik.http.routers.{router}.service"], "eneo-backend-svc"
            )
            self.assertEqual(labels[f"traefik.http.routers.{router}.priority"], "5")
        self.assertEqual(
            labels["traefik.http.routers.eneo-web-next.entrypoints"], "web"
        )
        self.assertEqual(
            labels["traefik.http.routers.eneo-web-next.middlewares"],
            "redirect-to-https",
        )
        self.assertEqual(
            labels["traefik.http.routers.eneo-web-next-secure.entrypoints"], "websecure"
        )
        self.assertEqual(
            labels["traefik.http.routers.eneo-web-next-secure.tls"], "true"
        )
        self.assertEqual(
            labels["traefik.http.routers.eneo-web-next-secure.tls.certresolver"],
            "letsencrypt",
        )
        env["COMPOSE_PROFILES"] = "web-next"
        self.assertEqual(config("docker-compose.web-next.yml")["services"], beta)
        del env["COMPOSE_PROFILES"]
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
