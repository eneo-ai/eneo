#!/usr/bin/env python3
"""List one disjoint, deterministic shard of backend integration test files."""

from __future__ import annotations

import argparse
from pathlib import Path


def integration_test_shard(root: Path, index: int, count: int) -> list[Path]:
    if count < 1 or not 1 <= index <= count:
        raise ValueError("Shard index must be between 1 and a positive shard count")
    if not root.is_dir():
        raise ValueError(f"Integration test directory does not exist: {root}")

    # Match pytest's default python_files patterns, including future nested tests.
    files = sorted(
        path
        for path in root.rglob("*.py")
        if path.name.startswith("test_") or path.name.endswith("_test.py")
    )
    selected = files[index - 1 :: count]
    if not selected:
        # Never let an empty argument list silently run the entire pytest suite.
        raise ValueError(f"Integration shard {index}/{count} contains no test files")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True, type=int)
    parser.add_argument("--count", required=True, type=int)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "backend/tests/integration",
    )
    args = parser.parse_args()
    try:
        selected = integration_test_shard(args.root, args.index, args.count)
    except ValueError as error:
        parser.error(str(error))
    for path in selected:
        print(path)


if __name__ == "__main__":
    main()
