from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_test_layout as guard  # noqa: E402


class FrozenUnittestsTests(unittest.TestCase):
    def test_allowlisted_file_passes(self) -> None:
        files = ["backend/tests/unittests/spaces/test_space.py"]
        self.assertEqual(guard.check_frozen_unittests(files, set(files)), [])

    def test_new_file_fails(self) -> None:
        files = ["backend/tests/unittests/spaces/test_new_thing.py"]
        violations = guard.check_frozen_unittests(files, set())
        self.assertEqual(len(violations), 1)
        self.assertIn("frozen legacy", violations[0])

    def test_other_roots_ignored(self) -> None:
        files = ["backend/tests/integration/spaces/test_space.py"]
        self.assertEqual(guard.check_frozen_unittests(files, set()), [])


class UnitMirrorTests(unittest.TestCase):
    def test_mirrored_dir_passes(self) -> None:
        files = ["backend/tests/unit/spaces/test_space.py"]
        violations = guard.check_unit_mirror(files, set(), lambda rel: rel == "spaces")
        self.assertEqual(violations, [])

    def test_nested_mirror_passes(self) -> None:
        files = ["backend/tests/unit/spaces/api/test_router.py"]
        violations = guard.check_unit_mirror(
            files, set(), lambda rel: rel == "spaces/api"
        )
        self.assertEqual(violations, [])

    def test_non_mirrored_dir_fails(self) -> None:
        files = ["backend/tests/unit/made_up/test_x.py"]
        violations = guard.check_unit_mirror(files, set(), lambda rel: False)
        self.assertEqual(len(violations), 1)
        self.assertIn("does not mirror", violations[0])

    def test_flat_file_fails_unless_allowlisted(self) -> None:
        files = ["backend/tests/unit/test_flat.py"]
        self.assertEqual(len(guard.check_unit_mirror(files, set(), lambda r: True)), 1)
        self.assertEqual(guard.check_unit_mirror(files, set(files), lambda r: True), [])

    def test_flat_init_passes(self) -> None:
        files = ["backend/tests/unit/__init__.py"]
        self.assertEqual(guard.check_unit_mirror(files, set(), lambda r: False), [])


class BannedDecoratorTests(unittest.TestCase):
    def test_asyncio_decorator_fails(self) -> None:
        content = "@pytest.mark.asyncio\nasync def test_x():\n    pass\n"
        violations = guard.check_banned_decorators(
            ["backend/tests/unit/spaces/test_space.py"], lambda p: content
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("asyncio_mode=auto", violations[0])

    def test_integration_decorator_fails(self) -> None:
        content = "    @pytest.mark.integration\n    def test_x(self): ...\n"
        violations = guard.check_banned_decorators(
            ["backend/tests/integration/test_x.py"], lambda p: content
        )
        self.assertEqual(len(violations), 1)

    def test_parametrize_and_pytestmark_pass(self) -> None:
        content = (
            "pytestmark = pytest.mark.migration_isolation\n"
            "@pytest.mark.parametrize('x', [1])\n"
            "def test_x(x): ...\n"
        )
        violations = guard.check_banned_decorators(
            ["backend/tests/integration/migrations/test_m.py"], lambda p: content
        )
        self.assertEqual(violations, [])

    def test_integration_conftest_exempt(self) -> None:
        violations = guard.check_banned_decorators(
            ["backend/tests/integration/conftest.py"],
            lambda p: "@pytest.mark.integration\n",
        )
        self.assertEqual(violations, [])


class InitFileTests(unittest.TestCase):
    def test_missing_init_fails(self) -> None:
        files = ["backend/tests/unit/spaces/test_space.py"]
        violations = guard.check_init_files(files)
        self.assertEqual(len(violations), 1)
        self.assertIn("__init__.py", violations[0])

    def test_present_init_passes(self) -> None:
        files = [
            "backend/tests/unit/spaces/test_space.py",
            "backend/tests/unit/spaces/__init__.py",
        ]
        self.assertEqual(guard.check_init_files(files), [])


class StaleAllowlistTests(unittest.TestCase):
    def test_stale_entry_fails(self) -> None:
        violations = guard.check_stale_allowlist(
            [], {"backend/tests/unittests/test_gone.py"}
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("only shrinks", violations[0])

    def test_live_entry_passes(self) -> None:
        files = ["backend/tests/unittests/test_here.py"]
        self.assertEqual(guard.check_stale_allowlist(files, set(files)), [])


class RepoSelfCheckTests(unittest.TestCase):
    def test_current_repo_is_clean(self) -> None:
        self.assertEqual(guard.run_checks(REPO_ROOT), [])


if __name__ == "__main__":
    unittest.main()
