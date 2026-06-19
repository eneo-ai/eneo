#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROUTE_START_RE = re.compile(
    r"^(\s*)@[A-Za-z_][A-Za-z0-9_]*\.(get|post|put|patch|delete)\("
)
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def iter_route_blocks(text: str) -> list[tuple[int, str, str]]:
    lines = text.splitlines()
    blocks: list[tuple[int, str, str]] = []
    i = 0
    while i < len(lines):
        match = ROUTE_START_RE.match(lines[i])
        if not match:
            i += 1
            continue
        method = match.group(2)
        start_line = i + 1
        block_lines = [lines[i]]
        # Heuristic block-end detection by paren balance. Parentheses inside
        # string literals (e.g. description="see (note)") are not discounted, so
        # a decorator with unbalanced parens in a string could be mis-bounded.
        # Acceptable for a guardrail; revisit with a real parser if it bites.
        depth = lines[i].count("(") - lines[i].count(")")
        i += 1
        while i < len(lines) and depth > 0:
            block_lines.append(lines[i])
            depth += lines[i].count("(") - lines[i].count(")")
            i += 1
        blocks.append((start_line, method, "\n".join(block_lines)))
    return blocks


def contains_route_decorator(path: Path) -> bool:
    if path.suffix != ".py" or not path.is_file():
        return False
    return bool(iter_route_blocks(path.read_text(encoding="utf-8")))


def discover_route_files(repo_root: Path) -> list[Path]:
    source_root = repo_root / "backend" / "src"
    return [
        path
        for path in sorted(source_root.rglob("*.py"))
        if contains_route_decorator(path)
    ]


def is_allowed_without_response_model(block: str) -> bool:
    lowered = block.lower()
    return "status_code=204" in lowered or "streaming_response(" in lowered


def changed_lines(repo_root: Path, base: str, path: Path) -> set[int]:
    rel = path.relative_to(repo_root).as_posix()
    result = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--unified=0", base, "--", rel],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return set()

    lines: set[int] = set()
    for line in result.stdout.splitlines():
        match = HUNK_RE.match(line)
        if not match:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or "1")
        if count == 0:
            continue
        lines.update(range(start, start + count))
    return lines


def check_file(path: Path, changed: set[int] | None = None) -> list[str]:
    text = path.read_text(encoding="utf-8")
    failures: list[str] = []
    for line_no, method, block in iter_route_blocks(text):
        block_end = line_no + block.count("\n")
        if changed is not None and not any(line_no <= line <= block_end for line in changed):
            continue

        missing: list[str] = []
        if "description=" not in block:
            missing.append("description")
        if "responses=" not in block:
            missing.append("responses")
        if "response_model=" not in block and not is_allowed_without_response_model(block):
            missing.append("response_model")

        if not missing:
            continue

        if method == "get" and missing == ["description"]:
            continue

        failures.append(
            f"{path}:{line_no} route decorator missing {', '.join(missing)}"
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--repo-root")
    parser.add_argument("--base")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Check every HTTP route decorator under backend/src.",
    )
    args = parser.parse_args()

    failures: list[str] = []
    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path.cwd()
    if args.all and args.paths:
        parser.error("--all cannot be combined with explicit paths")
    paths = (
        discover_route_files(repo_root)
        if args.all
        else [Path(raw) for raw in args.paths]
    )

    for path in paths:
        if not contains_route_decorator(path):
            continue
        changed = None
        if args.base:
            changed = changed_lines(repo_root, args.base, path.resolve())
            if not changed:
                continue
        failures.extend(check_file(path, changed))

    for failure in failures:
        print(f"[route-metadata] error: {failure}", file=sys.stderr)

    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
