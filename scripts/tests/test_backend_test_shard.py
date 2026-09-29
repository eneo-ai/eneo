from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.backend_test_shard import integration_test_shard


class BackendTestShardTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="eneo-test-shard-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def create_files(self, names: list[str]) -> set[Path]:
        paths = set()
        for name in names:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
            paths.add(path)
        return paths

    def test_all_tests_belong_to_exactly_one_shard(self) -> None:
        expected = self.create_files(
            [f"area_{index % 3}/test_case_{index}.py" for index in range(13)]
            + ["nested/deeper/contract_test.py"]
        )
        self.create_files(["conftest.py", "fixtures/models.py", "test_notes.md"])
        shards = [integration_test_shard(self.root, index, 4) for index in range(1, 5)]
        combined = [path for shard in shards for path in shard]
        self.assertEqual(set(combined), expected)
        self.assertEqual(len(combined), len(expected))
        self.assertLessEqual(max(map(len, shards)) - min(map(len, shards)), 1)

    def test_selection_is_sorted_and_repeatable(self) -> None:
        self.create_files(["test_z.py", "test_b.py", "test_a.py", "test_c.py"])
        expected = [self.root / "test_a.py", self.root / "test_c.py"]
        self.assertEqual(integration_test_shard(self.root, 1, 2), expected)
        self.assertEqual(integration_test_shard(self.root, 1, 2), expected)

    def test_rejects_invalid_or_empty_shards(self) -> None:
        self.create_files(["test_single.py"])
        for index, count in [(0, 4), (5, 4), (1, 0), (1, -1), (2, 4)]:
            with self.subTest(index=index, count=count), self.assertRaises(ValueError):
                integration_test_shard(self.root, index, count)
        with self.assertRaises(ValueError):
            integration_test_shard(self.root / "missing", 1, 1)

    def test_cli_fails_without_printing_test_paths_for_empty_directory(self) -> None:
        script = Path(__file__).resolve().parents[1] / "backend_test_shard.py"
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--root",
                str(self.root),
                "--index",
                "1",
                "--count",
                "4",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
