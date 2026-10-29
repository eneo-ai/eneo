from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

from scripts.release_notes import format_json
from scripts.tests.test_check_whats_new import ENTRY, REPO_ROOT, _RepoCase

SCRIPT = REPO_ROOT / "scripts" / "release_notes.py"
NOTES = Path("frontend/packages/whats-new/releases.json")


def entry(entry_id: str, **changes: object) -> dict:
    return {**copy.deepcopy(ENTRY), "id": entry_id, **changes}


HISTORY = {"version": "2.2.0", "date": "2026-10-07", "entries": [entry("old-news")]}


class ReleaseNotesTests(_RepoCase):
    def run_notes(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(SCRIPT), "--repo-root", str(root), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def read(self, root: Path) -> list[dict]:
        return json.loads((root / NOTES).read_text(encoding="utf-8"))["releases"]

    def git(self, root: Path, *args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
            cwd=root,
            check=True,
            capture_output=True,
        )

    def write(self, root: Path, releases: list[dict]) -> None:
        (root / NOTES).write_text(format_json({"releases": releases}) + "\n", encoding="utf-8")

    def release_branch(self, root: Path, releases: list[dict]) -> None:
        """Commit `releases` as release/v2.3, leaving the worktree as it was."""
        develop = (root / NOTES).read_text(encoding="utf-8")
        self.git(root, "init", "-q", "-b", "develop")
        self.write(root, releases)
        self.git(root, "add", "-A")
        self.git(root, "commit", "-q", "-m", "release")
        self.git(root, "branch", "release/v2.3")
        (root / NOTES).write_text(develop, encoding="utf-8")

    def test_formatting_matches_the_committed_file(self) -> None:
        text = (REPO_ROOT / NOTES).read_text(encoding="utf-8")
        self.assertEqual(format_json(json.loads(text)) + "\n", text)

    def test_cut_names_next_after_the_release_line(self) -> None:
        root = self.make_repo({"releases": [{"version": "next", "entries": [ENTRY]}, HISTORY]})
        result = self.run_notes(root, "cut", "2.3")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(
            self.read(root)[0], {"version": "2.3.0", "entries": [ENTRY]}
        )
        self.assertIn("first change on release/v2.3", result.stdout)

    def test_cut_refuses_without_next_or_behind_an_existing_release(self) -> None:
        for releases, line, fragment in [
            ([HISTORY], "2.3", "no 'next' block"),
            ([{"version": "next", "entries": [ENTRY]}, HISTORY], "2.2", "2.2.0 already exists"),
            ([{"version": "next", "entries": [ENTRY]}, HISTORY], "2.2.1", "release line like 2.4"),
        ]:
            with self.subTest(line=line):
                root = self.make_repo({"releases": releases})
                before = (root / NOTES).read_text(encoding="utf-8")
                result = self.run_notes(root, "cut", line)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn(fragment, result.stdout)
                self.assertEqual((root / NOTES).read_text(encoding="utf-8"), before)

    def test_finalize_dates_the_release_and_runs_the_tag_rule(self) -> None:
        root = self.make_repo({"releases": [{"version": "2.3.0", "entries": [ENTRY]}, HISTORY]})
        result = self.run_notes(root, "finalize", "2.3.0", "--date", "2026-11-04")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(list(self.read(root)[0]), ["version", "date", "entries"])
        self.assertEqual(self.read(root)[0]["date"], "2026-11-04")

        hotfix = self.run_notes(root, "finalize", "2.3.1", "--date", "2026-11-20")
        self.assertEqual(hotfix.returncode, 0, hotfix.stdout)
        self.assertIn("needs none", hotfix.stdout)

    def test_finalize_restores_the_file_when_the_tag_rule_fails(self) -> None:
        undated_history = {"version": "2.2.0", "entries": [entry("old-news")]}
        root = self.make_repo(
            {"releases": [{"version": "2.3.0", "entries": [ENTRY]}, undated_history]}
        )
        before = (root / NOTES).read_text(encoding="utf-8")
        result = self.run_notes(root, "finalize", "2.3.0", "--date", "2026-11-04")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("entry 2.2.0 has no date", result.stdout)
        self.assertEqual((root / NOTES).read_text(encoding="utf-8"), before)

    def test_port_moves_released_entries_out_of_next(self) -> None:
        develop_only = entry(
            "shared", permissions={"allOf": ["assistants"]}, body={"en": "Old.", "sv": "Gammal."}
        )
        root = self.make_repo(
            {
                "releases": [
                    {"version": "next", "entries": [entry("later"), develop_only, entry("alias")]},
                    HISTORY,
                ]
            }
        )
        release = [
            {
                "version": "2.3.0",
                "date": "2026-11-04",
                "entries": [entry("shared"), entry("renamed", aliases=["alias"]), entry("rc-only")],
            },
            HISTORY,
        ]
        self.release_branch(root, release)

        result = self.run_notes(root, "port", "2.3.0", "--from", "release/v2.3")
        self.assertEqual(result.returncode, 0, result.stdout)
        releases = self.read(root)
        self.assertEqual([r["version"] for r in releases], ["next", "2.3.0", "2.2.0"])
        self.assertEqual([e["id"] for e in releases[0]["entries"]], ["later"])
        ported = releases[1]
        self.assertEqual(ported["date"], "2026-11-04")
        self.assertEqual([e["id"] for e in ported["entries"]], ["shared", "renamed", "rc-only"])
        shared = ported["entries"][0]
        self.assertEqual(shared["body"], ENTRY["body"])
        self.assertEqual(shared["permissions"], {"allOf": ["assistants"]})
        self.assertEqual(list(shared), ["id", "type", "area", "permissions", "title", "body", "showMe"])
        self.assertIn("Moved out of 'next': 2; still upcoming: 1.", result.stdout)
        self.assertIn("Kept develop-only fields: shared (permissions).", result.stdout)
        self.assertIn("text for: shared.", result.stdout)

    def test_port_places_an_older_hotfix_below_newer_releases_and_drops_empty_next(self) -> None:
        newer = {"version": "2.4.0", "date": "2027-01-10", "entries": [entry("newer")]}
        root = self.make_repo(
            {"releases": [{"version": "next", "entries": [entry("fix")]}, newer, HISTORY]}
        )
        hotfix = {"version": "2.3.1", "date": "2027-01-20", "entries": [entry("fix")]}
        self.release_branch(root, [hotfix, HISTORY])

        result = self.run_notes(root, "port", "2.3.1", "--from", "release/v2.3")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual([r["version"] for r in self.read(root)], ["2.4.0", "2.3.1", "2.2.0"])

        again = self.run_notes(root, "port", "2.3.1", "--from", "release/v2.3")
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertEqual([r["version"] for r in self.read(root)], ["2.4.0", "2.3.1", "2.2.0"])

    def test_port_refuses_undated_or_missing_releases(self) -> None:
        root = self.make_repo({"releases": [{"version": "next", "entries": [ENTRY]}, HISTORY]})
        self.release_branch(root, [{"version": "2.3.0", "entries": [ENTRY]}, HISTORY])
        for version, fragment in [
            ("2.3.0", "run finalize there"),
            ("2.3.1", "nothing to port"),
        ]:
            with self.subTest(version=version):
                result = self.run_notes(root, "port", version, "--from", "release/v2.3")
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn(fragment, result.stdout)
        missing = self.run_notes(root, "port", "2.3.0", "--from", "release/v9.9")
        self.assertEqual(missing.returncode, 2, missing.stdout)
        self.assertIn("cannot read", missing.stdout)
