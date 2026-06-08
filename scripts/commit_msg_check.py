#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

BANNED_SUBJECTS = {
    "wip",
    "tmp",
    "misc",
    "update",
    "updates",
    "changes",
    "stuff",
    "fix",
    "minor fix",
    "test",
    "tests",
    "work",
}


def staged_files(repo_root: Path | None) -> list[str]:
    if repo_root is None:
        return []
    result = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return [line for line in result.stdout.splitlines() if line]


def repo_root_from(path_arg: str | None) -> Path | None:
    if path_arg:
        return Path(path_arg).resolve()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def load_message(args: argparse.Namespace) -> str:
    if args.message_file:
        return Path(args.message_file).read_text(encoding="utf-8")
    return args.message or ""


def validate(message: str, repo_root: Path | None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    lines = message.rstrip().splitlines()
    subject = lines[0].strip() if lines else ""

    if not subject:
        errors.append("Commit message subject is empty.")
        return errors, warnings

    normalized = re.sub(r"\s+", " ", subject).strip().lower()
    if normalized in BANNED_SUBJECTS:
        errors.append(
            f"Commit subject '{subject}' is too vague. Name the actual intent of the change."
        )

    if len(subject) > 100:
        errors.append(
            f"Commit subject is {len(subject)} characters. Keep it under 100."
        )
    elif len(subject) > 72:
        warnings.append(
            f"Commit subject is {len(subject)} characters. Prefer <= 72 for readability."
        )

    if subject.endswith("."):
        warnings.append("Commit subject ends with a period. Prefer a bare subject line.")

    if len(lines) > 1 and lines[1].strip():
        warnings.append("Keep a blank line between the subject and body.")

    if any(path.startswith("backend/alembic/versions/") for path in staged_files(repo_root)):
        if not normalized.startswith("alembic:"):
            warnings.append(
                "Staged Alembic migration detected. Prefer an `alembic:` subject prefix."
            )

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("message_file", nargs="?")
    parser.add_argument("--message")
    parser.add_argument("--repo-root")
    args = parser.parse_args()

    if not args.message_file and not args.message:
        print("Provide a commit message file or --message.", file=sys.stderr)
        return 2

    message = load_message(args)
    errors, warnings = validate(message, repo_root_from(args.repo_root))

    for warning in warnings:
        print(f"[commit-msg] warn: {warning}", file=sys.stderr)
    for error in errors:
        print(f"[commit-msg] error: {error}", file=sys.stderr)

    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
