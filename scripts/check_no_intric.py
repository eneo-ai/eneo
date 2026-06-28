#!/usr/bin/env python3
"""Guard against re-introducing the old "intric" product name.

The project was renamed Intric -> Eneo. This check fails CI if any tracked
file references "intric" outside a small, documented allow-list of legitimate
survivors (backward-compat env aliases, real external endpoints, upstream
attribution, an immutable test fixture, and historical records).

Run locally:  python3 scripts/check_no_intric.py
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

# --- Paths that are never scanned -------------------------------------------
# CHANGELOG history and lockfiles are generated/immutable; this script and its
# tests necessarily contain the word.
EXCLUDED_PATHSPECS = [
    ":!**/CHANGELOG.md",
    ":!**/bun.lock",
    ":!**/uv.lock",
    ":!**/*.lock",
    ":!**/package-lock.json",
    ":!scripts/check_no_intric.py",
    ":!scripts/tests/test_no_intric.py",
    ":!.github/workflows/no-intric.yml",
]


@dataclass(frozen=True)
class AllowedOccurrence:
    pattern: re.Pattern[str]
    paths: tuple[str, ...] = ()

    def applies_to(self, path: str) -> bool:
        return not self.paths or any(fnmatch(path, pathspec) for pathspec in self.paths)


# --- Legitimate survivors ----------------------------------------------------
# A line is OK if, after removing every allowed occurrence, no "intric"
# (case-insensitive) remains. Keep this list in sync with docs/CONTRIBUTING and
# the rename keep-list.
ALLOWED = [
    # Backward-compat environment variable names (ENEO_* is primary; the
    # INTRIC_* aliases are still accepted, slated for removal in v3.0).
    AllowedOccurrence(
        re.compile(
            r"\b(?:"
            r"INTRIC_SUPER_API_KEY|"
            r"INTRIC_SUPER_DUPER_API_KEY|"
            r"INTRIC_BACKEND_URL|"
            r"INTRIC_BACKEND_SERVER_URL|"
            r"PUBLIC_INTRIC_BACKEND_URL|"
            r"INTRIC_MARKETPLACE_API_KEY|"
            r"INTRIC_MARKETPLACE_URL"
            r")\b"
        )
    ),
    AllowedOccurrence(re.compile(r"\bINTRIC_(?:\*|\b)")),
    # Deprecated pydantic-settings alias fields bound to the INTRIC_* env vars.
    AllowedOccurrence(re.compile(r"intric_super_(?:duper_)?api_key")),
    # Hardcoded JWT `aud` claim baked into an OIDC auth test fixture.
    AllowedOccurrence(re.compile(r'client_id="intric"')),
    # Real external endpoints on the intric.ai domain (hostname only, NOT a
    # module path such as `intric.ai_models`).
    AllowedOccurrence(re.compile(r"intric\.ai(?![_A-Za-z0-9])")),
    # Upstream attribution to the original project / company.
    AllowedOccurrence(re.compile(r"Intric AB")),
    AllowedOccurrence(re.compile(r"Intric \(now Eneo\)")),
    # This guard's own identifiers (CI job, pre-commit hook, script name, docs).
    AllowedOccurrence(re.compile(r"check_no_intric")),
    AllowedOccurrence(re.compile(r"no-intric")),
    AllowedOccurrence(re.compile(r"NO_INTRIC_RESULT")),
    AllowedOccurrence(re.compile(r"No intric references")),
    # Transitional ARQ pickle compatibility for queued jobs created before the
    # package rename. Remove this allowance with backend/src/eneo/jobs/job_serialization.py
    # after all pre-rename Redis job payloads have expired.
    AllowedOccurrence(
        re.compile(r"\bintric\b"),
        paths=(
            "backend/src/eneo/jobs/job_serialization.py",
            "backend/tests/unittests/jobs/test_job_serialization.py",
        ),
    ),
    # Immutable historical Alembic text. Migrations are still scanned so a new
    # `from intric...` import path will fail this guard.
    AllowedOccurrence(
        re.compile(r"into intric(?: and keeps it up-to-date|\.)"),
        paths=(
            "backend/alembic/versions/202503060954_7c492266359d_shorten_confluence_integration__.py",
            "backend/alembic/versions/202503141310_b127c46c7ebc_rename_confluence_table_.py",
            "backend/alembic/versions/202606281200_update_integration_descriptions_for_eneo.py",
        ),
    ),
    AllowedOccurrence(
        re.compile(r"backend/src/intric/[A-Za-z0-9_./-]*"),
        paths=(
            "backend/alembic/versions/202604281200_grant_api_keys_permission_to_owner.py",
            "backend/alembic/versions/migrate_global_to_tenant_models.py",
        ),
    ),
    AllowedOccurrence(
        re.compile(r"intric\.model_providers\.domain\.model_defaults_lookup"),
        paths=("backend/alembic/versions/20260501_backfill_model_costs.py",),
    ),
    AllowedOccurrence(
        re.compile(r"intric hosting"),
        paths=("backend/alembic/versions/2f8e9a1b3c5d_update_kb_whisper_to_berget.py",),
    ),
]

INTRIC_RE = re.compile(r"intric", re.IGNORECASE)


def tracked_hits(repo_root: Path) -> list[str]:
    """Return `path:lineno:line` for every tracked line containing 'intric'."""
    result = subprocess.run(
        ["git", "grep", "-I", "-i", "-n", "intric", "--", *EXCLUDED_PATHSPECS],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    # git grep exits 1 when there are no matches; that is success for us.
    if result.returncode not in (0, 1):
        sys.stderr.write(result.stderr)
        raise SystemExit(2)
    return [ln for ln in result.stdout.splitlines() if ln]


def is_violation(path: str, line_text: str) -> bool:
    stripped = line_text
    for allowance in ALLOWED:
        if allowance.applies_to(path):
            stripped = allowance.pattern.sub("", stripped)
    return bool(INTRIC_RE.search(stripped))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", type=Path)
    args = parser.parse_args()

    violations = []
    for hit in tracked_hits(args.repo_root):
        # hit == "path:lineno:line text"
        try:
            path, lineno, text = hit.split(":", 2)
        except ValueError:
            continue
        if is_violation(path, text):
            violations.append((path, lineno, text.strip()))

    if violations:
        print("Found disallowed 'intric' references (the project is now 'Eneo'):\n")
        for path, lineno, text in violations:
            print(f"  {path}:{lineno}: {text}")
        print(
            "\nRename these to 'eneo'. If a reference is a legitimate survivor "
            "(a documented legacy env alias, an intric.ai endpoint, upstream "
            "attribution, etc.), add a path-specific allow-list entry in "
            "scripts/check_no_intric.py."
        )
        return 1

    print("No disallowed 'intric' references found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
