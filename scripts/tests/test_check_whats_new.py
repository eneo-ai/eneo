from __future__ import annotations

import ast
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.check_whats_new import _semver_key

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK = REPO_ROOT / "scripts" / "check_whats_new.py"
SCHEMA = REPO_ROOT / "frontend" / "packages" / "whats-new" / "releases.schema.json"
WEB_NEXT = Path("frontend/apps/web-next/src")
LEGACY_PAGES = Path("backend/src/eneo/server/web_app_legacy.py")

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


class _RepoCase(unittest.TestCase):
    def make_repo(
        self,
        data: object,
        anchors: str = "account-password",
        routes: str = "account spaces/[spaceId]/knowledge dashboard/[assistantId]/[[sessionId]]",
    ) -> Path:
        root = Path(tempfile.mkdtemp(prefix="eneo-whats-new-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        package = root / "frontend" / "packages" / "whats-new"
        package.mkdir(parents=True)
        (package / "releases.json").write_text(json.dumps(data), encoding="utf-8")
        shutil.copy(SCHEMA, package / "releases.schema.json")
        app_routes = root / "frontend" / "apps" / "web" / "src" / "routes" / "(app)"
        for route in routes.split():
            page = app_routes / route / "+page.svelte"
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text("<div></div>\n", encoding="utf-8")
        (app_routes / "account" / "+page.svelte").write_text(
            "".join(f'<div data-tour="{a}"></div>\n' for a in anchors.split()),
            encoding="utf-8",
        )
        web_next = root / WEB_NEXT
        web_next.mkdir(parents=True)
        self.write_route_tree(
            root,
            [
                "/account",
                "/spaces/$spaceId/knowledge/",
                "/dashboard/$assistantId/{-$sessionId}",
                "/$",
            ],
        )
        (web_next / "account.tsx").write_text(
            '<Page.Title tour="account-password" />', encoding="utf-8"
        )
        (root / LEGACY_PAGES).parent.mkdir(parents=True)
        shutil.copy(REPO_ROOT / LEGACY_PAGES, root / LEGACY_PAGES)
        return root

    def write_route_tree(self, root: Path, paths: list[str]) -> None:
        (root / WEB_NEXT / "routeTree.gen.ts").write_text(
            "export interface FileRoutesByFullPath {\n"
            + "".join(f'  "{path}": typeof TestRoute\n' for path in paths)
            + "}\n",
            encoding="utf-8",
        )

    def run_check(self, root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(CHECK), "--repo-root", str(root), *extra],
            text=True,
            capture_output=True,
            check=False,
        )

    def assert_rejected(self, data: object, fragment: str, anchors="account-password"):
        result = self.run_check(self.make_repo(data, anchors))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(fragment, result.stdout)


class CheckWhatsNewTests(_RepoCase):
    def test_rejects_missing_react_route_despite_svelte_page_and_catch_all(
        self,
    ) -> None:
        root = self.make_repo(VALID)
        self.write_route_tree(root, ["/other", "/$"])
        result = self.run_check(root)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("no page at /account", result.stdout)
        self.assertIn(str(WEB_NEXT), result.stdout)

    def test_svelte_routes_remain_required_while_source_exists(self) -> None:
        root = self.make_repo(VALID)
        shutil.rmtree(root / "frontend/apps/web/src/routes")
        (root / "frontend/apps/web/src/anchor.svelte").write_text(
            '<div data-tour="account-password" />', encoding="utf-8"
        )
        result = self.run_check(root)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("no page at /account under frontend/apps/web/src", result.stdout)

    def test_rejects_missing_react_anchor_despite_svelte_anchor(self) -> None:
        root = self.make_repo(VALID)
        (root / WEB_NEXT / "account.tsx").unlink()
        for relative in [
            "account.test.tsx",
            "account.spec.jsx",
            "__tests__/account.tsx",
        ]:
            source = root / WEB_NEXT / relative
            source.parent.mkdir(exist_ok=True)
            source.write_text('<div data-tour="account-password" />', encoding="utf-8")
        result = self.run_check(root)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('no element with data-tour="account-password"', result.stdout)
        self.assertIn(str(WEB_NEXT), result.stdout)

    def test_accepts_react_literal_anchor_forms(self) -> None:
        for suffix, markup in [
            ("tsx", '<Page.Title tour="account-password" />'),
            ("jsx", "<div data-tour = {'account-password'} />"),
        ]:
            with self.subTest(markup=markup):
                root = self.make_repo(VALID)
                (root / WEB_NEXT / "account.tsx").unlink()
                (root / WEB_NEXT / f"page.{suffix}").write_text(
                    markup, encoding="utf-8"
                )
                result = self.run_check(root)
                self.assertEqual(result.returncode, 0, result.stdout)

    def test_react_routes_validate_without_svelte(self) -> None:
        for href in [
            "/",
            "/account/",
            "/spaces/abc/knowledge?tab=files#details",
            "/dashboard/assistant",
            "/dashboard/assistant/session",
        ]:
            with self.subTest(href=href):
                data = copy.deepcopy(VALID)
                data["releases"][0]["entries"][0]["showMe"]["href"] = href
                root = self.make_repo(data)
                shutil.rmtree(root / "frontend/apps/web")
                self.write_route_tree(
                    root,
                    [
                        "/",
                        "/account/",
                        "/spaces/$spaceId/knowledge/",
                        "/dashboard/$assistantId/{-$sessionId}",
                    ],
                )
                result = self.run_check(root)
                self.assertEqual(result.returncode, 0, result.stdout)

    def test_react_dynamic_routes_reject_missing_and_extra_segments(self) -> None:
        for href in ["/spaces/knowledge", "/dashboard", "/dashboard/a/b/c"]:
            with self.subTest(href=href):
                data = copy.deepcopy(VALID)
                data["releases"][0]["entries"][0]["showMe"]["href"] = href
                root = self.make_repo(data)
                shutil.rmtree(root / "frontend/apps/web")
                result = self.run_check(root)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(f"no page at {href}", result.stdout)

    def test_shared_legacy_target_must_resolve_to_a_react_route(self) -> None:
        data = copy.deepcopy(VALID)
        data["releases"][0]["entries"][0]["showMe"]["href"] = (
            "/admin/personal-assistant/configuration?tab=chat#settings"
        )
        root = self.make_repo(
            data, routes="admin/personal-assistant/configuration account"
        )
        self.write_route_tree(root, ["/admin/personal-assistant"])
        result = self.run_check(root)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.write_route_tree(root, ["/other"])
        result = self.run_check(root)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(
            "no page at /admin/personal-assistant/configuration", result.stdout
        )

    def test_requires_generated_react_routes(self) -> None:
        root = self.make_repo(VALID)
        tree = root / WEB_NEXT / "routeTree.gen.ts"
        for content in [
            None,
            "export interface FileRoutesById { '/account': unknown }",
        ]:
            with self.subTest(content=content):
                if content is None:
                    tree.unlink()
                else:
                    tree.write_text(content, encoding="utf-8")
                result = self.run_check(root)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("routeTree.gen.ts", result.stdout)

    def test_checker_needs_no_site_packages_or_backend_package_imports(self) -> None:
        root = self.make_repo(VALID)
        backend_package = root / "backend/src/eneo/__init__.py"
        backend_package.write_text(
            'raise RuntimeError("backend package imported")', encoding="utf-8"
        )
        result = subprocess.run(
            ["python3", "-S", str(CHECK), "--repo-root", str(root)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_permission_vocabulary_matches_backend_contract(self) -> None:
        source = REPO_ROOT / "backend/src/eneo/roles/permissions.py"
        permission_class = next(
            node
            for node in ast.parse(source.read_text()).body
            if isinstance(node, ast.ClassDef) and node.name == "Permission"
        )
        permissions = {
            node.value.value
            for node in permission_class.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
        }
        self.assertEqual(
            set(json.loads(SCHEMA.read_text())["$defs"]["permission"]["enum"]), permissions
        )

    def test_accepts_feature_permission_requirements(self) -> None:
        data = copy.deepcopy(VALID)
        data["releases"][0]["entries"][0]["permissions"] = {
            "allOf": ["file_creation"],
            "anyOf": ["personal_chat", "assistants"],
        }
        result = self.run_check(self.make_repo(data))
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_rejects_invalid_permission_requirements(self) -> None:
        for permissions in [
            None, [], {}, "admin", {"any": ["assistants"]},
            {"allOf": []}, {"anyOf": []}, {"allOf": "admin"},
            {"allOf": ["administrator"]}, {"anyOf": [None]},
            {"allOf": [{}]}, {"allOf": ["admin", "admin"]},
        ]:
            with self.subTest(permissions=permissions):
                data = copy.deepcopy(VALID)
                data["releases"][0]["entries"][0]["permissions"] = permissions
                self.assert_rejected(data, ".permissions")

    def test_release_order_matches_the_shared_cross_runtime_contract(self) -> None:
        cases = SCHEMA.parent / "version-order.cases.json"
        versions = json.loads(cases.read_text())["ordered"]
        for older, newer in zip(versions, versions[1:]):
            self.assertLess(_semver_key(older), _semver_key(newer))

    def test_accepts_valid_file(self) -> None:
        result = self.run_check(self.make_repo(VALID))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("OK (1 release(s), 1 entries)", result.stdout)

    def test_accepts_merged_entry_aliases(self) -> None:
        data = copy.deepcopy(VALID)
        data["releases"][0]["entries"][0]["aliases"] = ["old-password-entry"]
        result = self.run_check(self.make_repo(data))
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_rejects_invalid_aliases(self) -> None:
        for aliases in [None, [], "old-entry", [17], [{}], ["Bad ID"], ["bad\n"]]:
            with self.subTest(aliases=aliases):
                data = copy.deepcopy(VALID)
                data["releases"][0]["entries"][0]["aliases"] = aliases
                self.assert_rejected(data, ".aliases:")

    def test_rejects_duplicate_anchor_targets(self) -> None:
        for first, second in [
            (["old-entry", "old-entry"], []),
            ([ENTRY["id"]], []),
            (["second-entry"], []),
            ([], [ENTRY["id"]]),
            (["old-entry"], ["old-entry"]),
        ]:
            with self.subTest(first=first, second=second):
                entries = [copy.deepcopy(ENTRY), dict(copy.deepcopy(ENTRY), id="second-entry")]
                for entry, aliases in zip(entries, [first, second]):
                    if aliases:
                        entry["aliases"] = aliases
                self.assert_rejected(
                    {"releases": [{"version": "2.3.0", "entries": entries}]},
                    "is not unique in the release",
                )

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

    def test_accepts_page_title_tour_prop(self) -> None:
        root = self.make_repo(VALID, anchors="other")
        page = root / "frontend" / "apps" / "web" / "src" / "routes" / "(app)" / "account" / "+page.svelte"
        page.write_text('<Page.Title title="x" tour="account-password" />\n', encoding="utf-8")
        self.assertEqual(self.run_check(root).returncode, 0)

    def test_rejects_unknown_anchor(self) -> None:
        self.assert_rejected(VALID, 'no element with data-tour="account-password"', anchors="other")

    def test_rejects_href_without_a_page(self) -> None:
        data = copy.deepcopy(VALID)
        data["releases"][0]["entries"][0]["showMe"]["href"] = "/account/removed"
        self.assert_rejected(data, "no page at /account/removed")

    def test_href_matches_parameterised_and_optional_segments(self) -> None:
        for href in [
            "/spaces/abc-123/knowledge?tab=files",
            "/dashboard/assistant-1",
            "/dashboard/assistant-1/session-9",
            "/account#password",
        ]:
            with self.subTest(href=href):
                data = copy.deepcopy(VALID)
                data["releases"][0]["entries"][0]["showMe"]["href"] = href
                result = self.run_check(self.make_repo(data))
                self.assertEqual(result.returncode, 0, result.stdout)

    def test_vocabulary_comes_from_the_schema(self) -> None:
        data = copy.deepcopy(VALID)
        data["releases"][0]["entries"][0]["area"] = "reports"
        root = self.make_repo(data)
        self.assertEqual(self.run_check(root).returncode, 1)

        schema_path = root / "frontend" / "packages" / "whats-new" / "releases.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema["$defs"]["entry"]["properties"]["area"]["enum"].append("reports")
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        self.assertEqual(self.run_check(root).returncode, 0)

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


class UnreleasedBlockTests(_RepoCase):
    def notes(self, *releases: dict) -> dict:
        return {"releases": list(releases)}

    def upcoming(self, **extra: object) -> dict:
        return {"version": "next", "entries": [ENTRY], **extra}

    def released(self, version: str = "2.2.0", date: str | None = "2026-10-07") -> dict:
        release: dict = {"version": version, "entries": [ENTRY]}
        if date:
            release["date"] = date
        return release

    def test_accepts_next_above_the_released_history(self) -> None:
        result = self.run_check(self.make_repo(self.notes(self.upcoming(), self.released())))
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_next_must_come_first_and_stay_undated(self) -> None:
        self.assert_rejected(
            self.notes(self.released(), self.upcoming()), "release next: must be the first block"
        )
        self.assert_rejected(
            self.notes(self.upcoming(date="2026-11-01")), "unreleased notes have no date"
        )

    def test_rejects_other_words_for_unreleased(self) -> None:
        for version in ["Next", "unreleased", "2.4", "latest"]:
            with self.subTest(version=version):
                self.assert_rejected(
                    self.notes({"version": version, "entries": [ENTRY]}), "or 'next'"
                )

    def test_develop_keeps_unreleased_notes_only_in_next(self) -> None:
        for branch in ["develop", "refs/heads/develop"]:
            with self.subTest(branch=branch):
                accepted = self.run_check(
                    self.make_repo(self.notes(self.upcoming(), self.released())),
                    "--branch", branch,
                )
                self.assertEqual(accepted.returncode, 0, accepted.stdout)
                root = self.make_repo(
                    self.notes(self.upcoming(), self.released("2.3.0", None), self.released())
                )
                rejected = self.run_check(root, "--branch", branch)
                self.assertEqual(rejected.returncode, 1, rejected.stdout)
                self.assertIn("release 2.3.0 has no date; on develop", rejected.stdout)

    def test_release_branches_have_no_next_and_nothing_from_a_later_line(self) -> None:
        cases = [
            (self.notes(self.upcoming(), self.released()), "release/v2.2", "cannot carry 'next'"),
            (self.notes(self.released("2.3.0", None)), "release/v2.2", "newer than release/v2.2"),
            (self.notes(self.released("2.3.0-rc.1", None)), "release/v2.2", "newer than"),
            (self.notes(self.released("2.10.0", None)), "release/v2.9", "newer than"),
        ]
        for data, branch, fragment in cases:
            with self.subTest(branch=branch, data=data):
                result = self.run_check(self.make_repo(data), "--branch", branch)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(fragment, result.stdout)
        for data, branch in [
            (self.notes(self.released("2.3.0", None), self.released()), "release/v2.3"),
            (self.notes(self.released("2.3.1", None), self.released()), "release/v2.3"),
            (self.notes(self.released()), "release/v2.3"),
            (self.notes(self.upcoming(), self.released("2.3.0", None)), "feature/anything"),
        ]:
            with self.subTest(branch=branch, data=data):
                result = self.run_check(self.make_repo(data), "--branch", branch)
                self.assertEqual(result.returncode, 0, result.stdout)

    def test_no_tag_ships_next(self) -> None:
        for tag in ["v2.3.0-rc.1", "v2.3.0"]:
            with self.subTest(tag=tag):
                data = self.notes(self.upcoming(), self.released("2.3.0", "2026-11-01"))
                result = self.run_check(self.make_repo(data), "--release-tag", tag)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("would ship the 'next' block", result.stdout)

    def test_reads_release_branches_whose_schema_predates_next(self) -> None:
        root = self.make_repo(self.notes(self.released("2.3.0", None), self.released()))
        schema_path = root / "frontend" / "packages" / "whats-new" / "releases.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        pattern = schema["$defs"].pop("releaseVersion")["pattern"]
        schema["$defs"]["release"]["properties"]["version"] = {"type": "string", "pattern": pattern}
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        result = self.run_check(root, "--branch", "release/v2.3")
        self.assertEqual(result.returncode, 0, result.stdout)


class ReleaseTagTests(_RepoCase):
    def releases(self, version: str, date: str | None = None) -> dict:
        release = {"version": version, "entries": [ENTRY]}
        if date:
            release["date"] = date
        return {"releases": [release, {"version": "2.1.0", "date": "2026-06-12", "entries": [ENTRY]}]}

    def test_final_tag_requires_a_dated_entry(self) -> None:
        undated = self.run_check(self.make_repo(self.releases("2.2.0")), "--release-tag", "v2.2.0")
        self.assertEqual(undated.returncode, 1, undated.stdout)
        self.assertIn("has no date", undated.stdout)

        dated = self.run_check(
            self.make_repo(self.releases("2.2.0", "2026-10-01")), "--release-tag", "v2.2.0"
        )
        self.assertEqual(dated.returncode, 0, dated.stdout)

    def test_prerelease_tag_accepts_an_undated_entry(self) -> None:
        result = self.run_check(self.make_repo(self.releases("2.2.0")), "--release-tag", "v2.2.0-rc.1")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_hotfix_without_notes_is_fine(self) -> None:
        result = self.run_check(
            self.make_repo(self.releases("2.2.0", "2026-10-01")), "--release-tag", "v2.2.1"
        )
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_hotfix_rejects_undated_notes_for_an_earlier_release(self) -> None:
        result = self.run_check(self.make_repo(self.releases("2.2.0")), "--release-tag", "v2.2.1")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("entry 2.2.0 has no date", result.stdout)

    def test_final_tag_rejects_undated_history_even_with_a_dated_latest_release(self) -> None:
        data = self.releases("2.2.0", "2026-10-01")
        del data["releases"][1]["date"]
        result = self.run_check(self.make_repo(data), "--release-tag", "v2.2.0")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("entry 2.1.0 has no date", result.stdout)

    def test_notes_for_a_later_version_cannot_ship_in_an_older_release(self) -> None:
        result = self.run_check(self.make_repo(self.releases("2.3.0")), "--release-tag", "v2.2.0")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("newer than release tag", result.stdout)

    def test_rc_requires_its_own_release_content_instead_of_reusing_an_older_version(self) -> None:
        for data in [self.releases("2.2.0", "2026-10-01"), {"releases": []}]:
            with self.subTest(data=data):
                result = self.run_check(
                    self.make_repo(data), "--release-tag", "v2.3.0-rc.1",
                )
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("RC tag v2.3.0-rc.1 needs notes for 2.3.0", result.stdout)

    def test_rejects_malformed_tags(self) -> None:
        result = self.run_check(self.make_repo(self.releases("2.2.0")), "--release-tag", "2.2")
        self.assertEqual(result.returncode, 1, result.stdout)


if __name__ == "__main__":
    unittest.main()
