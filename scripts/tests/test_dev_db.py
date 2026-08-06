from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_DB = REPO_ROOT / "scripts" / "dev-db.sh"


class DevDbTestCase(unittest.TestCase):
    """Exercises dev-db.sh's pure helpers by sourcing it, so no Docker or
    Postgres is involved. The script only dispatches when executed directly."""

    def run_bash(
        self, snippet: str, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", f'source "{DEV_DB}"\n{snippet}\n'],
            cwd=str(cwd or REPO_ROOT),
            text=True,
            capture_output=True,
            check=False,
        )

    def make_env_file(self, content: str) -> Path:
        root = Path(tempfile.mkdtemp(prefix="eneo-dev-db-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        env_file = root / ".env"
        env_file.write_text(content, encoding="utf-8")
        return env_file


class NamingTests(DevDbTestCase):
    def test_sanitizes_slashes_case_and_drops_hyphens(self) -> None:
        result = self.run_bash('db_name_for "feat/Some-Branch_2"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "eneo_feat_somebranch_2")

    def test_rejects_branch_that_sanitizes_to_nothing(self) -> None:
        result = self.run_bash('db_name_for "---"')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("empty database name", result.stderr)

    def test_rejects_name_over_the_postgres_identifier_limit(self) -> None:
        branch = "feature/" + ("a" * 60)
        result = self.run_bash(f'db_name_for "{branch}"')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("63", result.stderr)


class ReadEnvDbTests(DevDbTestCase):
    def read(self, content: str) -> subprocess.CompletedProcess[str]:
        env_file = self.make_env_file(content)
        return self.run_bash(f'ENV_FILE="{env_file}"\nread_env_db')

    def test_reads_plain_value(self) -> None:
        result = self.read("POSTGRES_USER=postgres\nPOSTGRES_DB=eneo_develop\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "eneo_develop")

    def test_strips_quotes_comments_and_whitespace(self) -> None:
        for line, expected in [
            ('POSTGRES_DB="eneo_a"\n', "eneo_a"),
            ("POSTGRES_DB='eneo_b'\n", "eneo_b"),
            ("POSTGRES_DB=eneo_c  # active\n", "eneo_c"),
            ("POSTGRES_DB=eneo_d   \n", "eneo_d"),
        ]:
            with self.subTest(line=line):
                result = self.read(line)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)

    def test_rejects_missing_key(self) -> None:
        result = self.read("POSTGRES_USER=postgres\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no POSTGRES_DB=", result.stderr)

    def test_refuses_to_guess_between_duplicate_keys(self) -> None:
        result = self.read("POSTGRES_DB=one\nPOSTGRES_DB=two\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to guess", result.stderr)

    def test_rejects_value_that_is_not_an_identifier(self) -> None:
        # The value is interpolated into CREATE DATABASE / DROP DATABASE.
        result = self.read('POSTGRES_DB=foo"; DROP DATABASE bar; --\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a plain identifier", result.stderr)


class WriteEnvDbTests(DevDbTestCase):
    def test_rewrites_only_the_postgres_db_line(self) -> None:
        env_file = self.make_env_file(
            "# comment\nPOSTGRES_USER=postgres\nPOSTGRES_DB=postgres\nREDIS_PORT=6379\n"
        )
        result = self.run_bash(f'ENV_FILE="{env_file}"\nwrite_env_db eneo_feature')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            env_file.read_text(encoding="utf-8"),
            "# comment\nPOSTGRES_USER=postgres\nPOSTGRES_DB=eneo_feature\nREDIS_PORT=6379\n",
        )

    def test_preserves_file_mode(self) -> None:
        env_file = self.make_env_file("POSTGRES_DB=postgres\n")
        os.chmod(env_file, 0o600)
        result = self.run_bash(f'ENV_FILE="{env_file}"\nwrite_env_db eneo_x')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)

    def test_round_trips_with_read_env_db(self) -> None:
        env_file = self.make_env_file('POSTGRES_DB="postgres"  # active\n')
        result = self.run_bash(
            f'ENV_FILE="{env_file}"\nwrite_env_db eneo_round_trip\nread_env_db'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "eneo_round_trip")


class BaseResolutionTests(DevDbTestCase):
    def make_repo(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="eneo-dev-db-git-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.git(root, "init", "-b", "develop")
        self.git(root, "config", "user.email", "dev@example.com")
        self.git(root, "config", "user.name", "Dev")
        (root / "file.txt").write_text("hello\n", encoding="utf-8")
        self.git(root, "add", "file.txt")
        self.git(root, "commit", "-m", "initial")
        return root

    def git(self, root: Path, *args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=str(root), check=True, capture_output=True, text=True
        )

    def resolve(self, root: Path, branch: str, db_list: str) -> tuple[str, str]:
        result = self.run_bash(
            f'REPO_ROOT="{root}"\n'
            f"DB_LIST=$(printf '%s' '{db_list}')\n"
            f'resolve_base "{branch}"\n'
            'printf "%s|%s" "$RESOLVED_BASE" "$BASE_RULE"'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        base, _, rule = result.stdout.partition("|")
        return base, rule

    def test_uses_the_branch_the_new_branch_was_created_from(self) -> None:
        # `git switch -c new <start-point>` records the start point in the
        # branch's own reflog. The HEAD reflog would report the branch you
        # happened to be standing on, which is a different thing.
        root = self.make_repo()
        self.git(root, "switch", "-c", "feat/side")
        self.git(root, "switch", "-c", "feat/target", "develop")

        base, rule = self.resolve(root, "feat/target", "eneo_develop")
        self.assertEqual(base, "develop")
        self.assertIn("created from it", rule)

    def test_handles_a_branch_created_from_head(self) -> None:
        # `git switch -c new` with no start point records "Created from HEAD",
        # which names no branch. Resolution has to fall through to the HEAD
        # reflog rather than abort the script under `set -e`.
        root = self.make_repo()
        self.git(root, "switch", "-c", "feat/target")

        base, rule = self.resolve(root, "feat/target", "eneo_develop")
        self.assertEqual(base, "develop")
        self.assertIn("branched off it", rule)

    def test_recorded_config_wins_over_reflog(self) -> None:
        root = self.make_repo()
        self.git(root, "switch", "-c", "feat/other")
        self.git(root, "switch", "-c", "feat/target", "develop")
        self.git(root, "config", "branch.feat/target.eneoDbBase", "feat/other")

        base, rule = self.resolve(root, "feat/target", "eneo_develop\neneo_feat_other")
        self.assertEqual(base, "feat/other")
        self.assertIn("git config", rule)

    def test_skips_a_creation_source_that_has_no_database(self) -> None:
        # Cloning from a database that does not exist would fail; fall through
        # to the ancestor scan instead.
        root = self.make_repo()
        self.git(root, "switch", "-c", "feat/no-db", "develop")
        self.git(root, "switch", "-c", "feat/target", "feat/no-db")

        base, rule = self.resolve(root, "feat/target", "eneo_develop")
        self.assertEqual(base, "develop")
        self.assertIn("ancestor", rule)

    def test_falls_back_to_develop_when_nothing_else_matches(self) -> None:
        root = self.make_repo()
        self.git(root, "switch", "-c", "feat/target", "develop")

        base, rule = self.resolve(root, "feat/target", "")
        self.assertEqual(base, "develop")
        self.assertEqual(rule, "fallback")


if __name__ == "__main__":
    unittest.main()
