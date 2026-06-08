#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from check_route_metadata import is_router_file_path

ENV_PATH_RE = re.compile(r"(^|/)\.env(\.[^/]+)?$")
SAFE_ENV_TEMPLATE_RE = re.compile(
    r"(^|/)(\.env\.(example|template)|env_[^/]+\.(template|example))$"
)
SECRET_PATTERNS = [
    re.compile(r"^\+.*-----BEGIN [A-Z ]*PRIVATE KEY-----", re.MULTILINE),
    re.compile(r"^\+.*github_pat_[A-Za-z0-9_]{20,}", re.MULTILINE),
    re.compile(r"^\+.*ghp_[A-Za-z0-9]{20,}", re.MULTILINE),
    re.compile(r"^\+.*sk-ant-api\d+-[A-Za-z0-9_\-]{30,}", re.MULTILINE),
    re.compile(r"^\+.*sk-[A-Za-z0-9]{20,}", re.MULTILINE),
    re.compile(r"^\+.*AIza[0-9A-Za-z\-_]{20,}", re.MULTILINE),
    re.compile(r"^\+.*AKIA[0-9A-Z]{16}", re.MULTILINE),
]


def repo_root_from(path_arg: str | None) -> Path:
    if path_arg:
        return Path(path_arg).resolve()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Not inside a git repository and --repo-root was not provided")
    return Path(result.stdout.strip()).resolve()


def run_git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def staged_files(repo_root: Path) -> list[str]:
    output = run_git(repo_root, "diff", "--cached", "--name-only", "--diff-filter=ACMR")
    return [line for line in output.splitlines() if line.strip()]


def staged_diff(repo_root: Path) -> str:
    return run_git(repo_root, "diff", "--cached", "--no-color", "--unified=0")


def staged_added_files(repo_root: Path) -> set[str]:
    output = run_git(repo_root, "diff", "--cached", "--name-only", "--diff-filter=A")
    return {line for line in output.splitlines() if line.strip()}


def ignored_cached_files(repo_root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-i", "--exclude-standard", "--cached"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {line for line in result.stdout.splitlines() if line.strip()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    args = parser.parse_args()

    try:
        repo_root = repo_root_from(args.repo_root)
        paths = staged_files(repo_root)
        added_paths = staged_added_files(repo_root)
        ignored_added_paths = ignored_cached_files(repo_root) & added_paths
        diff = staged_diff(repo_root)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    errors: list[str] = []
    warnings: list[str] = []

    if not paths:
        errors.append("No staged files. Stage the intended changes before committing.")

    for path in paths:
        normalized = path.replace("\\", "/")

        if normalized in ignored_added_paths and not SAFE_ENV_TEMPLATE_RE.search(normalized):
            errors.append(
                f"{normalized}: matches .gitignore and should not be committed. Remove it from the commit."
            )

        if ENV_PATH_RE.search(normalized):
            if not SAFE_ENV_TEMPLATE_RE.search(normalized):
                errors.append(
                    f"{normalized}: .env files must not be committed. Keep secrets in local env files."
                )

    for pattern in SECRET_PATTERNS:
        match = pattern.search(diff)
        if match:
            errors.append(
                "High-confidence secret or private key material detected in the staged diff."
            )
            break

    if any(path.startswith("backend/src/") and is_router_file_path(path) for path in paths):
        warnings.append(
            "Backend route files are staged. Verify OpenAPI docs (`description=`, `responses=`, `response_model=`) before push."
        )

    for warning in warnings:
        print(f"[preflight] warn: {warning}", file=sys.stderr)
    for error in errors:
        print(f"[preflight] error: {error}", file=sys.stderr)

    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
