#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from check_route_metadata import contains_route_decorator

PREFERRED_BRANCH_RE = re.compile(
    r"^(feature|feat|fix|hotfix|security|chore|deps|docs|test|refactor|remove|ci)/"
)
PROTECTED_BRANCHES = {"main", "master", "develop"}
SCHEMA_PATH = Path("frontend/packages/eneo-js/src/types/schema.d.ts")
# Mirror CI's schema-drift env so local OpenAPI dumps use the same placeholder settings.
SCHEMA_DRIFT_ENV = {
    "POSTGRES_USER": "placeholder",
    "POSTGRES_HOST": "placeholder",
    "POSTGRES_PASSWORD": "placeholder",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "placeholder",
    "REDIS_HOST": "localhost",
    "REDIS_PORT": "6379",
    "UPLOAD_FILE_TO_SESSION_MAX_SIZE": "10485760",
    "UPLOAD_IMAGE_TO_SESSION_MAX_SIZE": "10485760",
    "UPLOAD_MAX_FILE_SIZE": "10485760",
    "TRANSCRIPTION_MAX_FILE_SIZE": "10485760",
    "FLOW_TASK_TIMEOUT_SECONDS": "3600",
    "CELERY_VISIBILITY_TIMEOUT_SECONDS": "7200",
    "MAX_IN_QUESTION": "1",
    "API_PREFIX": "/api/v1",
    "API_KEY_LENGTH": "64",
    "API_KEY_HEADER_NAME": "X-API-Key",
    "JWT_AUDIENCE": "test",
    "JWT_ISSUER": "test",
    "JWT_EXPIRY_TIME": "3600",
    "JWT_ALGORITHM": "HS256",
    "JWT_SECRET": "ci-test-jwt-secret-not-for-production-0123456789",
    "JWT_TOKEN_PREFIX": "Bearer",
    "URL_SIGNING_KEY": "test_key",
    "ENCRYPTION_KEY": "yPIAaWTENh5knUuz75NYHblR3672X-7lH-W6AD4F1hs=",
    "OPENAI_API_KEY": "test-api-key",
}


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


def schema_drift_relevant(paths: list[str]) -> bool:
    return str(SCHEMA_PATH) in paths or any(path.startswith("backend/src/") for path in paths)


def run_schema_drift_check(repo: Path) -> None:
    print("[pre-push] running schema drift...", file=sys.stderr)

    with tempfile.TemporaryDirectory(prefix="eneo-schema-drift-") as tmp:
        tmp_dir = Path(tmp)
        openapi_path = tmp_dir / "openapi.gen.json"
        generated_schema = tmp_dir / "schema.d.ts"
        schema_env = {**os.environ, **SCHEMA_DRIFT_ENV}

        dump_result = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-c",
                (
                    "import json; "
                    "from eneo.server.main import app; "
                    f"json.dump(app.openapi(), open({str(openapi_path)!r}, 'w'))"
                ),
            ],
            cwd=repo / "backend",
            env=schema_env,
            text=True,
            check=False,
        )
        if dump_result.returncode != 0:
            raise RuntimeError("schema drift failed while dumping backend OpenAPI")

        gen_result = subprocess.run(
            [
                "bun",
                "x",
                "openapi-typescript",
                str(openapi_path),
                "-o",
                str(generated_schema),
                "--default-non-nullable=false",
            ],
            cwd=repo / "frontend" / "packages" / "eneo-js",
            text=True,
            check=False,
        )
        if gen_result.returncode != 0:
            raise RuntimeError("schema drift failed while regenerating schema.d.ts")

        fmt_result = subprocess.run(
            [
                "bun",
                "x",
                "prettier",
                "--config",
                str(repo / "frontend" / "packages" / "eneo-js" / ".prettierrc"),
                "--write",
                str(generated_schema),
            ],
            cwd=repo / "frontend" / "packages" / "eneo-js",
            text=True,
            check=False,
        )
        if fmt_result.returncode != 0:
            raise RuntimeError("schema drift failed while formatting schema.d.ts")

        committed_schema = repo / SCHEMA_PATH
        if committed_schema.read_bytes() != generated_schema.read_bytes():
            raise RuntimeError(
                f"{SCHEMA_PATH} is out of sync with the backend OpenAPI spec. "
                "Regenerate and commit it before pushing."
            )


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
        path
        for path in paths
        if path.startswith("backend/src/") and contains_route_decorator(root / path)
    ]
    router_changed = bool(router_paths)

    try:
        if router_changed:
            run_check(
                "route metadata",
                ["python3", "scripts/check_route_metadata.py", "--repo-root", str(root), "--base", base, *router_paths],
                root,
            )
        if schema_drift_relevant(paths):
            run_schema_drift_check(root)
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
