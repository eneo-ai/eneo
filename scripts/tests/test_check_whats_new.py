from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK = REPO_ROOT / "scripts" / "check_whats_new.py"

ENTRY = {
    "id": "self-service-password",
    "type": "new",
    "area": "account",
    "title": {"en": "Change your own password", "sv": "Byt lösenord själv"},
    "body": {
        "en": "You can now change it under My account.",
        "sv": "Du kan nu byta det under Mitt konto.",
    },
    "showMe": {"href": "/account", "anchor": "account-password"},
}
VALID = {"releases": [{"version": "2.2.0", "entries": [ENTRY]}]}


class CheckWhatsNewTests(unittest.TestCase):
    def make_repo(self, data: object, anchors: str = "account-password") -> Path:
        root = Path(tempfile.mkdtemp(prefix="eneo-whats-new-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        releases = root / "frontend" / "packages" / "whats-new" / "releases.json"
        releases.parent.mkdir(parents=True)
        releases.write_text(json.dumps(data), encoding="utf-8")
        page = root / "frontend" / "apps" / "web" / "src" / "routes" / "page.svelte"
        page.parent.mkdir(parents=True)
        page.write_text(
            "".join(f'<div data-tour="{a}"></div>\n' for a in anchors.split()),
            encoding="utf-8",
        )
        return root

    def run_check(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(CHECK), "--repo-root", str(root)],
            text=True,
            capture_output=True,
            check=False,
        )

    def assert_rejected(self, data: object, fragment: str, anchors="account-password"):
        result = self.run_check(self.make_repo(data, anchors))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(fragment, result.stdout)

    def test_accepts_valid_file(self) -> None:
        result = self.run_check(self.make_repo(VALID))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("OK (1 release(s), 1 entries)", result.stdout)

    def test_requires_newest_release_first(self) -> None:
        data = {
            "releases": [
                {"version": "2.2.0", "entries": [ENTRY]},
                {"version": "2.3.0", "entries": [ENTRY]},
            ]
        }
        self.assert_rejected(data, "2.3.0 must come after 2.2.0")

    def test_prerelease_sorts_before_final(self) -> None:
        data = {
            "releases": [
                {"version": "2.3.0", "entries": [ENTRY]},
                {"version": "2.3.0-rc.1", "entries": [ENTRY]},
            ]
        }
        result = self.run_check(self.make_repo(data))
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_rejects_leading_v_in_version(self) -> None:
        data = {"releases": [{"version": "v2.2.0", "entries": [ENTRY]}]}
        self.assert_rejected(data, "semver without a leading v")

    def test_rejects_missing_swedish(self) -> None:
        data = copy.deepcopy(VALID)
        del data["releases"][0]["entries"][0]["body"]["sv"]
        self.assert_rejected(data, "body.sv: missing or empty")

    def test_rejects_developer_language(self) -> None:
        for text, label in [
            ("Fixed in #760.", "issue/PR number"),
            ("See github.com/eneo-ai/eneo.", "GitHub URL"),
            ("Call PATCH /users/me.", "API endpoint"),
            ("Set inline_file_text.", "snake_case identifier"),
            ("Edit `settings`.", "code formatting"),
        ]:
            with self.subTest(text=text):
                data = copy.deepcopy(VALID)
                data["releases"][0]["entries"][0]["body"]["en"] = text
                self.assert_rejected(data, label)

    def test_rejects_unknown_anchor(self) -> None:
        self.assert_rejected(VALID, 'no element with data-tour="account-password"', anchors="other")

    def test_rejects_duplicate_ids(self) -> None:
        data = {"releases": [{"version": "2.2.0", "entries": [ENTRY, ENTRY]}]}
        self.assert_rejected(data, "'self-service-password' is not unique")

    def test_rejects_long_titles(self) -> None:
        data = copy.deepcopy(VALID)
        data["releases"][0]["entries"][0]["title"]["en"] = "x" * 61
        self.assert_rejected(data, "61 characters, max 60")

    def test_rejects_unknown_keys(self) -> None:
        data = copy.deepcopy(VALID)
        data["releases"][0]["entries"][0]["pr"] = 760
        self.assert_rejected(data, "unexpected keys ['pr']")


if __name__ == "__main__":
    unittest.main()
