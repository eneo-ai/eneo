#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from check_route_metadata import is_router_file_path

PREFERRED_BRANCH_RE = re.compile(
    r"^(feature|feat|fix|hotfix|security|chore|deps|docs|test|refactor|remove|ci)/"
)
PROTECTED_BRANCHES = {"main", "master", "develop"}


def run_git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Not inside a git repository")
    return Path(result.stdout.strip()).resolve()


def diff_base(repo: Path) -> str:
    # A configured upstream is the normal feature-branch case; the fallbacks keep
    # the hook useful in freshly-created local repos and test fixtures.
    upstream = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if upstream.returncode == 0:
        return f"{upstream.stdout.strip()}...HEAD"

    origin_develop = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "origin/develop"],
        text=True,
        capture_output=True,
        check=False,
    )
    if origin_develop.returncode == 0:
        return "origin/develop...HEAD"

    head_parent = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD~1"],
        text=True,
        capture_output=True,
        check=False,
    )
    if head_parent.returncode == 0:
        return "HEAD~1...HEAD"

    return "HEAD"


def changed_files(repo: Path, base: str) -> list[str]:
    output = run_git(repo, "diff", "--name-only", base)
    return [line for line in output.splitlines() if line]


def run_check(label: str, command: list[str], cwd: Path) -> None:
    print(f"[pre-push] running {label}...", file=sys.stderr)
    result = subprocess.run(command, cwd=cwd, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed")


def main() -> int:
    try:
        root = repo_root()
        branch = run_git(root, "branch", "--show-current")
    except RuntimeError as exc:
        print(f"[pre-push] error: {exc}", file=sys.stderr)
        return 2

    if branch in PROTECTED_BRANCHES and os.environ.get("ENEO_ALLOW_PROTECTED_PUSH") != "1":
        print(
            f"[pre-push] error: refusing direct push from protected branch '{branch}'. "
            "Create a feature branch or set ENEO_ALLOW_PROTECTED_PUSH=1 if this is intentional.",
            file=sys.stderr,
        )
        return 2

    try:
        base = diff_base(root)
        paths = changed_files(root, base)
    except RuntimeError as exc:
        print(f"[pre-push] error: {exc}", file=sys.stderr)
        return 2

    if branch and branch not in PROTECTED_BRANCHES and not PREFERRED_BRANCH_RE.match(branch):
        print(
            f"[pre-push] warn: branch '{branch}' does not match the preferred prefixes. "
            "CI will enforce the naming rule on PRs.",
            file=sys.stderr,
        )

    if not paths:
        print("[pre-push] no branch-local file changes detected.", file=sys.stderr)
        return 0

    router_paths = [
        path for path in paths if path.startswith("backend/src/") and is_router_file_path(path)
    ]
    router_changed = bool(router_paths)

    try:
        if router_changed:
            run_check(
                "route metadata",
                ["python3", "scripts/check_route_metadata.py", "--repo-root", str(root), "--base", base, *router_paths],
                root,
            )
    except RuntimeError as exc:
        print(f"[pre-push] error: {exc}", file=sys.stderr)
        return 2

    if router_changed:
        print(
            "[pre-push] warn: backend route files changed. OpenAPI metadata was checked locally; "
            "still confirm the rendered docs look right before opening the PR.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
