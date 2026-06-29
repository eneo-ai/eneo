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


if __name__ == "__main__":
    unittest.main()
