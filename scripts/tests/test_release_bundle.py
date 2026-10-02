import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


release = module("release_bundle", "scripts/release_bundle.py")
setup = module("deployment_setup", "docs/deployment/setup.py")


class ReleaseTests(unittest.TestCase):
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
        self.assertEqual(len(result["images"]), 3)
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
            ):
                shutil.copy(ROOT / "docs/deployment" / name, root / name)
            for name in ("backend", "frontend", "db"):
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
