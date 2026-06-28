from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMIT_MSG_CHECK = REPO_ROOT / "scripts" / "commit_msg_check.py"
COMMIT_PREFLIGHT = REPO_ROOT / "scripts" / "commit_preflight.py"
PRE_PUSH_CHECK = REPO_ROOT / "scripts" / "pre_push_check.py"
ROUTE_METADATA_CHECK = REPO_ROOT / "scripts" / "check_route_metadata.py"


def run_script(
    script: Path,
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(script), *args],
        text=True,
        capture_output=True,
        cwd=str(cwd) if cwd else None,
        env=env,
        check=False,
    )


class CommitHookTests(unittest.TestCase):
    def make_repo(self, branch: str = "feature/demo") -> Path:
        root = Path(tempfile.mkdtemp(prefix="eneo-commit-hooks-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        subprocess.run(["git", "init", "-b", branch], cwd=root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True, capture_output=True, text=True)
        (root / "backend" / "src" / "eneo").mkdir(parents=True)
        (root / "frontend" / "apps" / "web" / "src").mkdir(parents=True)
        return root

    def test_commit_msg_check_rejects_placeholder_subject(self) -> None:
        result = run_script(COMMIT_MSG_CHECK, "--message", "WIP")
        self.assertEqual(result.returncode, 2)
        self.assertIn("too vague", result.stderr)

    def test_commit_msg_check_warns_for_alembic_prefix(self) -> None:
        root = self.make_repo()
        migration = root / "backend" / "alembic" / "versions" / "1234_demo.py"
        migration.parent.mkdir(parents=True, exist_ok=True)
        migration.write_text("revision = '1234'\n", encoding="utf-8")
        subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True, capture_output=True, text=True)

        result = run_script(COMMIT_MSG_CHECK, "--repo-root", str(root), "--message", "Add migration")
        self.assertEqual(result.returncode, 0)
        self.assertIn("alembic:", result.stderr)

    def test_commit_preflight_blocks_env_and_junk(self) -> None:
        root = self.make_repo()
        (root / ".gitignore").write_text(".DS_Store\n.env\n.env.*\n!.env.example\n", encoding="utf-8")
        (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
        (root / ".DS_Store").write_text("junk\n", encoding="utf-8")
        subprocess.run(["git", "add", "-f", ".env", ".DS_Store"], cwd=root, check=True, capture_output=True, text=True)

        result = run_script(COMMIT_PREFLIGHT, "--repo-root", str(root))
        self.assertEqual(result.returncode, 2)
        self.assertIn(".env files must not be committed", result.stderr)
        self.assertIn("matches .gitignore and should not be committed", result.stderr)

    def test_commit_preflight_allows_env_templates(self) -> None:
        root = self.make_repo()
        backend_template = root / "backend" / ".env.template"
        frontend_example = root / "frontend" / "apps" / "web" / ".env.example"
        (root / ".gitignore").write_text(".env\n.env.*\n!.env.example\n", encoding="utf-8")
        backend_template.parent.mkdir(parents=True, exist_ok=True)
        frontend_example.parent.mkdir(parents=True, exist_ok=True)
        backend_template.write_text("API_PREFIX=/api/v1\n", encoding="utf-8")
        frontend_example.write_text("PUBLIC_API_URL=http://localhost:8123\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", ".gitignore"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "add", "-f", str(backend_template.relative_to(root)), str(frontend_example.relative_to(root))],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        result = run_script(COMMIT_PREFLIGHT, "--repo-root", str(root))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_commit_preflight_flags_high_confidence_secret_pattern(self) -> None:
        root = self.make_repo()
        (root / ".gitignore").write_text("", encoding="utf-8")
        target = root / "backend" / "src" / "eneo" / "pattern_demo.py"
        # Keep the scanner test fixture out of CodeQL/secret-scanning literals.
        candidate = "".join(["gh", "p_", "a" * 30])
        target.write_text(f'value = "{candidate}"\n', encoding="utf-8")
        subprocess.run(["git", "add", str(target.relative_to(root))], cwd=root, check=True, capture_output=True, text=True)

        result = run_script(COMMIT_PREFLIGHT, "--repo-root", str(root))
        self.assertEqual(result.returncode, 2)
        self.assertIn("High-confidence secret", result.stderr)

    def test_commit_preflight_flags_anthropic_key_pattern(self) -> None:
        root = self.make_repo()
        (root / ".gitignore").write_text("", encoding="utf-8")
        target = root / "backend" / "src" / "eneo" / "anthropic_pattern_demo.py"
        # Keep the scanner test fixture out of CodeQL/secret-scanning literals.
        candidate = "".join(["sk", "-ant-api03-", "a" * 40])
        target.write_text(f'value = "{candidate}"\n', encoding="utf-8")
        subprocess.run(["git", "add", str(target.relative_to(root))], cwd=root, check=True, capture_output=True, text=True)

        result = run_script(COMMIT_PREFLIGHT, "--repo-root", str(root))
        self.assertEqual(result.returncode, 2)
        self.assertIn("High-confidence secret", result.stderr)

    def test_pre_push_check_blocks_protected_branch_without_override(self) -> None:
        root = self.make_repo(branch="develop")
        target = root / "README.md"
        target.write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "docs: seed"], cwd=root, check=True, capture_output=True, text=True)

        result = run_script(PRE_PUSH_CHECK, cwd=root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("refusing direct push from protected branch", result.stderr)

    def test_pre_push_check_does_not_run_backend_or_frontend_type_checks(self) -> None:
        root = self.make_repo()
        bin_dir = root / "bin"
        marker = root / "type-check-ran"
        bin_dir.mkdir()
        for executable in ("bun",):
            candidate = bin_dir / executable
            candidate.write_text(
                f"#!/usr/bin/env sh\nprintf '%s\\n' {executable} > {marker}\nexit 99\n",
                encoding="utf-8",
            )
            candidate.chmod(0o755)

        readme = root / "README.md"
        readme.write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "docs: seed"], cwd=root, check=True, capture_output=True, text=True)

        backend_source = root / "backend" / "tests" / "service_test.py"
        backend_source.parent.mkdir(parents=True, exist_ok=True)
        frontend_source = root / "frontend" / "apps" / "web" / "src" / "page.ts"
        backend_source.write_text("VALUE = 1\n", encoding="utf-8")
        frontend_source.write_text("export const value = 1;\n", encoding="utf-8")
        subprocess.run(
            [
                "git",
                "add",
                str(backend_source.relative_to(root)),
                str(frontend_source.relative_to(root)),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(["git", "commit", "-m", "feat: add source files"], cwd=root, check=True, capture_output=True, text=True)

        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
        result = run_script(PRE_PUSH_CHECK, cwd=root, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists(), result.stderr)

    def test_pre_push_check_runs_schema_drift_for_backend_source_changes(self) -> None:
        root = self.make_repo()
        bin_dir = root / "bin"
        schema = root / "frontend" / "packages" / "eneo-js" / "src" / "types" / "schema.d.ts"
        bin_dir.mkdir()
        schema.parent.mkdir(parents=True, exist_ok=True)
        schema.write_text("export type Schema = 'current';\n", encoding="utf-8")

        uv = bin_dir / "uv"
        uv.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
        uv.chmod(0o755)

        bun = bin_dir / "bun"
        bun.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, sys\n"
            "args = sys.argv[1:]\n"
            "if 'openapi-typescript' in args:\n"
            "    out = pathlib.Path(args[args.index('-o') + 1])\n"
            "    out.write_text(\"export type Schema = 'current';\\n\", encoding='utf-8')\n"
            "sys.exit(0)\n",
            encoding="utf-8",
        )
        bun.chmod(0o755)

        readme = root / "README.md"
        readme.write_text("hello\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "README.md", str(schema.relative_to(root))],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(["git", "commit", "-m", "docs: seed"], cwd=root, check=True, capture_output=True, text=True)

        backend_source = root / "backend" / "src" / "eneo" / "service.py"
        backend_source.write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", str(backend_source.relative_to(root))], cwd=root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "feat: add backend source"], cwd=root, check=True, capture_output=True, text=True)

        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
        result = run_script(PRE_PUSH_CHECK, cwd=root, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("running schema drift", result.stderr)

    def test_pre_push_check_blocks_schema_drift(self) -> None:
        root = self.make_repo()
        bin_dir = root / "bin"
        schema = root / "frontend" / "packages" / "eneo-js" / "src" / "types" / "schema.d.ts"
        bin_dir.mkdir()
        schema.parent.mkdir(parents=True, exist_ok=True)
        schema.write_text("export type Schema = 'current';\n", encoding="utf-8")

        uv = bin_dir / "uv"
        uv.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
        uv.chmod(0o755)

        bun = bin_dir / "bun"
        bun.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, sys\n"
            "args = sys.argv[1:]\n"
            "if 'openapi-typescript' in args:\n"
            "    out = pathlib.Path(args[args.index('-o') + 1])\n"
            "    out.write_text(\"export type Schema = 'regenerated';\\n\", encoding='utf-8')\n"
            "sys.exit(0)\n",
            encoding="utf-8",
        )
        bun.chmod(0o755)

        readme = root / "README.md"
        readme.write_text("hello\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "README.md", str(schema.relative_to(root))],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(["git", "commit", "-m", "docs: seed"], cwd=root, check=True, capture_output=True, text=True)

        backend_source = root / "backend" / "src" / "eneo" / "service.py"
        backend_source.write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", str(backend_source.relative_to(root))], cwd=root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "feat: add backend source"], cwd=root, check=True, capture_output=True, text=True)

        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
        result = run_script(PRE_PUSH_CHECK, cwd=root, env=env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("schema.d.ts is out of sync", result.stderr)

    def test_pre_push_check_runs_route_metadata_for_endpoint_changes(self) -> None:
        root = self.make_repo()
        scripts_dir = root / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "check_route_metadata.py").write_text(
            ROUTE_METADATA_CHECK.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        readme = root / "README.md"
        readme.write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "docs: seed"], cwd=root, check=True, capture_output=True, text=True)

        router = root / "backend" / "src" / "eneo" / "resources" / "users.py"
        router.parent.mkdir(parents=True)
        router.write_text(
            "@router.post(\n"
            '    "/demo",\n'
            "    response_model=DemoResponse,\n"
            ")\n"
            "async def create_demo():\n"
            "    return {}\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "add", "scripts/check_route_metadata.py", str(router.relative_to(root))],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(["git", "commit", "-m", "feat: add demo route"], cwd=root, check=True, capture_output=True, text=True)

        result = run_script(PRE_PUSH_CHECK, cwd=root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("route decorator missing description, responses", result.stderr)

    def test_route_metadata_check_all_discovers_endpoints_in_any_python_file(
        self,
    ) -> None:
        root = self.make_repo()
        endpoint = root / "backend" / "src" / "eneo" / "resources" / "users.py"
        endpoint.parent.mkdir(parents=True)
        endpoint.write_text(
            "@router.post(\n"
            '    "/users",\n'
            "    response_model=UserResponse,\n"
            ")\n"
            "async def create_user():\n"
            "    return {}\n",
            encoding="utf-8",
        )

        result = run_script(
            ROUTE_METADATA_CHECK,
            "--repo-root",
            str(root),
            "--all",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn(str(endpoint), result.stderr)
        self.assertIn("missing description, responses", result.stderr)

    def test_route_metadata_check_flags_missing_fields_on_mutation_routes(self) -> None:
        root = self.make_repo()
        router = root / "backend" / "src" / "eneo" / "demo_router.py"
        router.write_text(
            "@router.post(\n"
            '    "/demo",\n'
            "    response_model=DemoResponse,\n"
            ")\n"
            "async def create_demo():\n"
            "    return {}\n",
            encoding="utf-8",
        )

        result = run_script(ROUTE_METADATA_CHECK, str(router))
        self.assertEqual(result.returncode, 2)
        self.assertIn("missing description, responses", result.stderr)

    def test_route_metadata_check_handles_named_router_variables(self) -> None:
        root = self.make_repo()
        router = root / "backend" / "src" / "eneo" / "demo_router.py"
        router.write_text(
            "@users_admin_router.post(\n"
            '    "/demo",\n'
            "    response_model=DemoResponse,\n"
            ")\n"
            "async def create_demo():\n"
            "    return {}\n",
            encoding="utf-8",
        )

        result = run_script(ROUTE_METADATA_CHECK, str(router))
        self.assertEqual(result.returncode, 2)
        self.assertIn("missing description, responses", result.stderr)

    def test_route_metadata_check_allows_204_without_response_model(self) -> None:
        root = self.make_repo()
        router = root / "backend" / "src" / "eneo" / "demo_router.py"
        router.write_text(
            "@router.post(\n"
            '    "/transfer",\n'
            "    status_code=204,\n"
            '    description="Transfer resource",\n'
            "    responses=responses.get_responses([404]),\n"
            ")\n"
            "async def transfer_demo():\n"
            "    return None\n",
            encoding="utf-8",
        )

        result = run_script(ROUTE_METADATA_CHECK, str(router))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_route_metadata_check_can_scope_to_changed_blocks_only(self) -> None:
        root = self.make_repo()
        router = root / "backend" / "src" / "eneo" / "demo_router.py"
        router.write_text(
            "@router.post(\n"
            '    "/legacy",\n'
            "    response_model=LegacyResponse,\n"
            ")\n"
            "async def legacy_route():\n"
            "    return {}\n\n"
            "@router.post(\n"
            '    "/new",\n'
            "    response_model=NewResponse,\n"
            '    description="Create new thing",\n'
            "    responses=responses.get_responses([400]),\n"
            ")\n"
            "async def new_route():\n"
            "    return {}\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", str(router.relative_to(root))], cwd=root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "seed"], cwd=root, check=True, capture_output=True, text=True)

        router.write_text(
            "@router.post(\n"
            '    "/legacy",\n'
            "    response_model=LegacyResponse,\n"
            ")\n"
            "async def legacy_route():\n"
            "    return {}\n\n"
            "@router.post(\n"
            '    "/new",\n'
            "    response_model=NewResponse,\n"
            '    description="Create new thing safely",\n'
            "    responses=responses.get_responses([400]),\n"
            ")\n"
            "async def new_route():\n"
            "    return {}\n",
            encoding="utf-8",
        )

        result = run_script(
            ROUTE_METADATA_CHECK,
            "--repo-root",
            str(root),
            "--base",
            "HEAD",
            str(router),
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
