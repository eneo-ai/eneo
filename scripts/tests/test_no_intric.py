from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_NO_INTRIC = REPO_ROOT / "scripts" / "check_no_intric.py"


class NoIntricGuardTests(unittest.TestCase):
    def make_repo(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="eneo-no-intric-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        subprocess.run(
            ["git", "init", "-b", "feature/demo"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        return root

    def run_check(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(CHECK_NO_INTRIC), "--repo-root", str(root)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_rejects_active_old_enum_names(self) -> None:
        root = self.make_repo()
        target = root / "backend" / "src" / "eneo" / "demo.py"
        target.parent.mkdir(parents=True)
        target.write_text('INTRIC_EVENT = "eneo_event"\n', encoding="utf-8")
        subprocess.run(
            ["git", "add", str(target.relative_to(root))],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        result = self.run_check(root)

        self.assertEqual(result.returncode, 1)
        self.assertIn("backend/src/eneo/demo.py", result.stdout)

    def test_rejects_old_package_imports_in_migrations(self) -> None:
        root = self.make_repo()
        target = root / "backend" / "alembic" / "versions" / "20260629_bad.py"
        target.parent.mkdir(parents=True)
        target.write_text("from intric.jobs.task_models import UploadInfoBlob\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", str(target.relative_to(root))],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        result = self.run_check(root)

        self.assertEqual(result.returncode, 1)
        self.assertIn("backend/alembic/versions/20260629_bad.py", result.stdout)

    def test_rejects_legacy_env_names(self) -> None:
        root = self.make_repo()
        target = root / "backend" / ".env.template"
        target.parent.mkdir(parents=True)
        target.write_text(
            "INTRIC_SUPER_API_KEY=old\n"
            "INTRIC_SUPER_DUPER_API_KEY=old\n"
            "INTRIC_BACKEND_URL=http://localhost:8123\n"
            "INTRIC_BACKEND_SERVER_URL=http://localhost:8123\n"
            "PUBLIC_INTRIC_BACKEND_URL=http://localhost:8123\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "add", str(target.relative_to(root))],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        result = self.run_check(root)

        self.assertEqual(result.returncode, 1)
        self.assertIn("backend/.env.template", result.stdout)

    def add_file(self, root: Path, relative: str, content: str) -> None:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        subprocess.run(
            ["git", "add", relative],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_allows_removed_env_names_in_the_startup_checks(self) -> None:
        root = self.make_repo()
        self.add_file(
            root,
            "backend/src/eneo/main/removed_env.py",
            'RemovedVariable("INTRIC_SUPER_API_KEY", replacement="ENEO_SUPER_API_KEY")\n',
        )
        self.add_file(
            root,
            "frontend/apps/web/src/lib/core/deploymentEnv.server.ts",
            '{ removed: "PUBLIC_INTRIC_BACKEND_URL", replacement: "PUBLIC_ENEO_BACKEND_URL" }\n',
        )

        result = self.run_check(root)

        self.assertEqual(result.returncode, 0, result.stdout)

    def test_startup_check_allowance_covers_only_env_names(self) -> None:
        root = self.make_repo()
        self.add_file(
            root,
            "backend/src/eneo/main/removed_env.py",
            "from intric.main.config import Settings\n",
        )

        result = self.run_check(root)

        self.assertEqual(result.returncode, 1)
        self.assertIn("backend/src/eneo/main/removed_env.py", result.stdout)

    def test_allows_old_names_only_in_the_2_2_upgrade_guide(self) -> None:
        root = self.make_repo()
        line = "| Error response field | `intric_error_code` | `eneo_error_code` |\n"
        self.add_file(root, "frontend/apps/docs-site/src/content/guides/upgrade-2-2-0.mdx", line)
        self.add_file(root, "frontend/apps/docs-site/src/content/guides/deployment.mdx", line)

        result = self.run_check(root)

        self.assertEqual(result.returncode, 1)
        self.assertIn("guides/deployment.mdx", result.stdout)
        self.assertNotIn("upgrade-2-2-0.mdx", result.stdout)


if __name__ == "__main__":
    unittest.main()
