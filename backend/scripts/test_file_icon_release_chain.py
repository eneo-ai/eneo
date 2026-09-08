"""Rehearse the bridge and contract releases with disposable PostgreSQL databases.

Run from backend with ``uv run python scripts/test_file_icon_release_chain.py``.
The bridge runs from its frozen source and lockfile in a temporary directory;
the current application then upgrades and restore-tests its exported backup.
"""

import os
import subprocess
import sys
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

# Last bridge schema, including released-schema preflight and backup export.
_BRIDGE_COMMIT = "7e21a5438de91fada0d5cb4e5e562ca7f840055b"


def main() -> None:
    backend = Path(__file__).resolve().parents[1]
    repo = backend.parent
    if subprocess.run(
        ["git", "cat-file", "-e", f"{_BRIDGE_COMMIT}^{{commit}}"],
        cwd=repo,
        capture_output=True,
        check=False,
    ).returncode:
        # CI uses a shallow checkout. Fetch the fixed source without moving refs.
        subprocess.run(
            [
                "git",
                "fetch",
                "--no-tags",
                "--no-write-fetch-head",
                "origin",
                _BRIDGE_COMMIT,
            ],
            cwd=repo,
            check=True,
        )

    env = os.environ.copy()
    for key in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH"):
        env.pop(key, None)

    with TemporaryDirectory(prefix="eneo-file-icon-release-") as temporary:
        directory = Path(temporary)
        archive = directory / "bridge.tar"
        subprocess.run(
            ["git", "archive", f"--output={archive}", _BRIDGE_COMMIT, "backend"],
            cwd=repo,
            check=True,
        )
        with tarfile.open(archive) as source:
            source.extractall(directory, filter="data")
        backup = directory / "bridge.dump"
        bridge_env = env | {
            "ENEO_FILE_ICON_REHEARSAL_PROFILE": "smoke",
            "ENEO_FILE_ICON_REHEARSAL_BACKUP": str(backup),
        }
        for test in (
            "test_file_icon_preflight.py",
            "test_file_icon_bridge_rehearsal.py",
        ):
            subprocess.run(
                [
                    "uv",
                    "run",
                    "--frozen",
                    "--all-groups",
                    "python",
                    "-m",
                    "pytest",
                    "-q",
                    "-m",
                    "migration_isolation",
                    f"tests/integration/migrations/{test}",
                ],
                cwd=directory / "backend",
                env=bridge_env,
                check=True,
            )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-m",
                "migration_isolation",
                "tests/integration/migrations/test_file_icon_contraction_rehearsal.py",
            ],
            cwd=backend,
            env=env | {"ENEO_FILE_ICON_CONTRACTION_BACKUP": str(backup)},
            check=True,
        )


if __name__ == "__main__":
    main()
