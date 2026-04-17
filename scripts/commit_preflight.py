#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

JUNK_RULES = [
    (re.compile(r"(^|/)\.DS_Store$"), "staged macOS metadata file"),
    (re.compile(r"(^|/).+\.sw[op]$"), "staged editor swap file"),
    (re.compile(r"(^|/).+~$"), "staged editor backup file"),
    (re.compile(r"(^|/)\.pytest_cache(/|$)"), "staged pytest cache"),
    (re.compile(r"(^|/)\.ruff_cache(/|$)"), "staged ruff cache"),
    (re.compile(r"(^|/)\.svelte-kit(/|$)"), "staged SvelteKit build artifact"),
    (re.compile(r"(^|/)node_modules(/|$)"), "staged node_modules artifact"),
    (re.compile(r"(^|/)(dist|build)(/|$)"), "staged build artifact"),
    (re.compile(r"(^|/)\.claude/state(/|$)"), "staged Claude runtime state"),
    (re.compile(r"(^|/)\.claude/stats(/|$)"), "staged Claude runtime stats"),
    (re.compile(r"(^|/)backend/celerybeat-schedule$"), "staged Celery runtime schedule"),
]
ENV_PATH_RE = re.compile(r"(^|/)\.env(\.[^/]+)?$")
SAFE_ENV_TEMPLATE_RE = re.compile(
    r"(^|/)(\.env\.(example|template)|env_[^/]+\.(template|example))$"
)
SECRET_PATTERNS = [
    re.compile(r"^\+.*-----BEGIN [A-Z ]*PRIVATE KEY-----", re.MULTILINE),
    re.compile(r"^\+.*github_pat_[A-Za-z0-9_]{20,}", re.MULTILINE),
    re.compile(r"^\+.*ghp_[A-Za-z0-9]{20,}", re.MULTILINE),
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    args = parser.parse_args()

    try:
        repo_root = repo_root_from(args.repo_root)
        paths = staged_files(repo_root)
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
        for regex, label in JUNK_RULES:
            if regex.search(normalized):
                errors.append(f"{normalized}: {label}. Remove it from the commit.")
                break

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

    if any(path.startswith("backend/src/") and ("router" in path or "/routes/" in path) for path in paths):
        warnings.append(
            "Backend route files are staged. Verify OpenAPI docs (`description=`, `responses=`, `response_model=`) before push."
        )

    if any(path.startswith(("backend/src/", "frontend/apps/web/src/")) for path in paths) and not any(
        path.startswith(("docs/", "README.md", "frontend/apps/web/messages/")) for path in paths
    ):
        warnings.append(
            "Behavioral source changes are staged without docs updates. If behavior changed, add a small surgical docs update."
        )

    for warning in warnings:
        print(f"[preflight] warn: {warning}", file=sys.stderr)
    for error in errors:
        print(f"[preflight] error: {error}", file=sys.stderr)

    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
